"""Fault-injection checks for production summaries, checkpoints and book coverage."""
import json,tempfile,unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import app
from langgraph.checkpoint.sqlite import SqliteSaver
from app.core.services import Workspace
from app.core.work_context import CurrentWork
from app.core.selection import selection
from app.core.creation_flow import CreationFlow
from app.core.full_book_review import FullBookReview
from app.core.project_memory import ProjectMemory,parse_memory,accept_memory
from app.core.agent_candidates import AgentCandidates
from app.core.output_files import OutputFiles,publish_work,safe_name
from app.storage.connections import ConnectionStore
from app.providers.contracts import Connection,TextResult,CancelToken

ROOT=Path(__file__).resolve().parents[1]
class Provider:
    def __init__(self,values,callback=None): self.values=values; self.calls=0; self.callback=callback
    def generate(self,c,secret,messages,cancel,on_text,**kw):
        value=self.values[min(self.calls,len(self.values)-1)]; self.calls+=1
        if callable(value): value=value(messages)
        if self.callback: self.callback(messages)
        if isinstance(value,Exception): raise value
        text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)
        on_text(text); return TextResult(text=text,status='completed',accepted=True,model=c.model,usage=dict(input=100,output=40,cached_read=0))

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='tt_merged_'); root=Path(self.temp.name)
        self.store=Workspace(root/'data').create('隔离测试','小说'); self.did=self.store.documents()[0]['id']; self.config=selection('novel')
        self.work=CurrentWork.load(self.store,self.did,self.config); self.work.edit('阿宁把信藏进抽屉。林远仍在门外等她。'); self.work.save()
        self.connections=ConnectionStore(root/'prefs'); self.c=Connection('fixture','隔离模拟','deepseek','fixture',base_url='https://example.org',max_output=1024,context_limit=65536); self.connections.save(self.c)
        self.flow=CreationFlow(self.work,ROOT/'resources',self.connections)
    def tearDown(self): self.temp.cleanup()
    def summary(self,source): return dict(summary='阿宁藏信，林远等待。',characters=['阿宁藏起信'],events=['藏信'],unresolved=['信的来历'],evidence=[source[:8]])
    def snap(self,task='inspect',**kw):
        snap=self.flow.prepare(self.c,task,'只检查，不改稿',development_test=True,**kw); snap['tools_enabled']=False; return snap
    def test_semantic_summary_generated_read_invalidated_and_isolated(self):
        before=self.work.text; revisions=len(self.store.revisions(self.did)); snap=self.snap(); snap['memory_policy']='semantic'
        p=Provider(['发现人物等待关系。',self.summary(before)]); result=self.flow.service.execute(snap,CancelToken(),provider=p)
        self.assertEqual(result['status'],'completed'); self.assertEqual(p.calls,2); self.flow.apply(snap,result)
        record=ProjectMemory(self.store).context()['documents'][0]; self.assertIn('模型语义',record['method']); self.assertEqual(record['summary'],'阿宁藏信，林远等待。')
        self.assertEqual(self.work.text,before); self.assertEqual(len(self.store.revisions(self.did)),revisions)
        other=Workspace(Path(self.temp.name)/'other').create('另项目','小说'); self.assertEqual(ProjectMemory(other).context()['documents'],[])
        self.work.edit(before+'手改。'); self.work.save(); record=ProjectMemory(self.store).context()['documents'][0]; self.assertEqual(record['method'],'当前原文自动节选')
        self.assertFalse(accept_memory(self.store,self.did,self.work.revision,result['semantic_memory']))
    def test_invalid_summary_keeps_paid_round_count_and_body(self):
        snap=self.snap(); snap['memory_policy']='semantic'; p=Provider(['检查完成',dict(self.summary(self.work.text),evidence=['原文不存在'])]); result=self.flow.service.execute(snap,CancelToken(),provider=p)
        self.assertEqual(result['status'],'completed'); self.assertEqual(result['used_calls'],2); self.assertIn('证据',result['memory_warning']); self.assertFalse(result['semantic_memory'])
        with self.store.connection() as con: self.assertEqual(con.execute('SELECT COUNT(*) FROM usage_ledger').fetchone()[0],2)
    def test_candidate_memory_waits_for_adopt_and_undo(self):
        new='阿宁推开门，递出了信。'; snap=self.snap('modify',selected=(0,len(self.work.text))); snap['memory_policy']='semantic'; result=self.flow.service.execute(snap,CancelToken(),provider=Provider([dict(text=new,explanation='修改'),self.summary(new)]))
        candidates=AgentCandidates(self.store); cid=candidates.save(snap,result); old=self.work.text
        self.assertNotIn('模型语义',ProjectMemory(self.store).context()['documents'][0]['method']); candidates.adopt(cid,self.work)
        self.assertEqual(self.work.text,new); self.assertIn('模型语义',ProjectMemory(self.store).context()['documents'][0]['method']); candidates.undo(cid,self.work); self.assertEqual(self.work.text,old)
        self.assertEqual(ProjectMemory(self.store).context()['documents'][0]['method'],'当前原文自动节选')
    def test_actual_checkpoint_resume_reconciles_response_without_resubmission(self):
        snap=self.snap(); p=Provider(['检查完成']); original=SqliteSaver.put; injected=[]
        def fault(saver,*a,**k):
            if p.calls and not injected: injected.append(True); raise OSError('模拟响应后检查点写入中断')
            return original(saver,*a,**k)
        with patch.object(SqliteSaver,'put',fault): result=self.flow.service.execute(snap,CancelToken(),provider=p)
        self.assertEqual(result['status'],'failed'); self.assertTrue(injected)
        resumed=self.flow.service.resume_snapshot(snap['task_id']); result=self.flow.service.execute(resumed,CancelToken(),provider=p)
        self.assertEqual(result['status'],'completed',result.get('error')); self.assertEqual(p.calls,1)
        with self.store.connection() as con: self.assertEqual(con.execute('SELECT COUNT(*) FROM usage_ledger').fetchone()[0],1)
    def test_unknown_acceptance_timeout_never_replayed(self):
        snap=self.snap(); p=Provider([TimeoutError('模拟提交后无回执')]); result=self.flow.service.execute(snap,CancelToken(),provider=p); self.assertEqual(result['status'],'failed')
        with self.assertRaises(ValueError): self.flow.service.resume_snapshot(snap['task_id'])
        self.assertEqual(p.calls,1)
    def test_monetary_budget_prevents_any_external_submit(self):
        price=dict(currency='CNY',version='fixture',source='fixture',input_per_million=2,cached_read_per_million=.04,output_per_million=8,input_includes_cached=True)
        self.c=replace(self.c,pricing=price); self.connections.save(self.c); snap=self.snap(); snap['budget']['monetary_limits']=dict(currency='CNY',project_amount='.000001'); p=Provider(['unused'])
        result=self.flow.service.execute(snap,CancelToken(),provider=p); self.assertEqual(result['status'],'budget_paused'); self.assertEqual(p.calls,0)
    def review(self):
        self.work.edit('甲乙丙丁戊己庚辛壬癸'*5); self.work.save(); review=FullBookReview(self.store,ROOT/'resources',self.connections); rid=review.create(self.work,self.c,'整本检查',chunk_size=10,development_test=True); return review,rid
    def test_segmented_review_exact_coverage_and_resume_after_reopen(self):
        def response(messages):
            if messages[0]['content'].startswith('跨章节综合检查'):
                parts=json.loads(messages[1]['content'].split('\n',1)[1])['parts']; return dict(summary='全部已读分段已综合，未发现可证实矛盾。',reviewed_parts=[p['part_index'] for p in parts],contradictions=[],citations=[dict(part_index=p['part_index'],quote=p['analysis']['facts'][0]['evidence']) for p in parts])
            context=json.loads(messages[1]['content'].split('\n',1)[1]); source=context['target_text']; return dict(summary='本段检查完成。',facts=[dict(category='event',subject='本段',predicate='内容',value='已提供原文',evidence=source)],issues=[])
        review,rid=self.review(); p=Provider([response]); first=review.run(rid,CancelToken(),provider=p)
        self.assertEqual(first['review_state'],'budget_paused'); self.assertEqual(first['coverage']['completed_characters'],30); self.assertEqual(p.calls,3)
        second=FullBookReview(self.store,ROOT/'resources',self.connections).run(rid,CancelToken(),provider=p); self.assertEqual(second['review_state'],'completed'); self.assertEqual(p.calls,6); self.assertTrue(second['coverage']['cross_chapter_completed'])
        spans=second['coverage']['completed_parts']; self.assertEqual([(p['start'],p['end']) for p in spans],[(0,10),(10,20),(20,30),(30,40),(40,50)])
        review.run(rid,CancelToken(),provider=p); self.assertEqual(p.calls,6)
        with self.store.connection() as con: self.assertEqual(con.execute('SELECT COUNT(*) FROM messages').fetchone()[0],0)
    def test_cancel_review_no_provider_and_no_false_completion(self):
        review,rid=self.review(); token=CancelToken(); token.cancel(); p=Provider(['unused']); result=review.run(rid,token,provider=p)
        self.assertEqual(result['review_state'],'cancelled'); self.assertEqual(result['coverage']['completed_characters'],0); self.assertEqual(p.calls,0)
    def test_edits_during_review_stop_current_coverage(self):
        review,rid=self.review()
        def edit(messages): self.store.save_document(self.did,self.store.document(self.did)['head'],'用户已改正文')
        p=Provider(['旧版本发现'],edit); result=review.run(rid,CancelToken(),provider=p); self.assertEqual(result['review_state'],'source_changed'); self.assertEqual(result['coverage']['completed_characters'],0); self.assertEqual(p.calls,1)
    def test_output_versions_safe_names_and_no_overwrite(self):
        out=OutputFiles(Path(self.temp.name)/'作品'); self.assertEqual(safe_name('CON.txt'),'_CON.txt'); self.assertNotIn('/',safe_name('作品:/标题'))
        path=publish_work(out,self.work); before=path.read_bytes(); self.assertEqual(publish_work(out,self.work),path)
        self.work.edit(self.work.text+'新内容'); self.work.save(); new=publish_work(out,self.work); self.assertNotEqual(new,path); self.assertEqual(path.read_bytes(),before)
        paths=[out.write('图片','封面',b'fixture','png',cover=True) for _ in range(2)]; self.assertEqual([p.name for p in paths],['封面_01.png','封面_02.png'])
    def test_nested_history_does_not_expose_output_contract(self):
        from app.core.context import ChatService
        chat=ChatService(self.store); chat.append(chat.current(),self.did,'discussion','assistant',json.dumps(dict(text='修改正文',explanation='已加强人物决心'),ensure_ascii=False),'fixture','completed',protocol=[])
        snap=self.snap('discuss'); history=[m['content'] for m in snap['messages'][2:-1]]; self.assertIn('已加强人物决心',history); self.assertFalse(any('"explanation"' in m for m in history))

    def test_output_create_failure_never_deletes_concurrent_existing_file(self):
        folder=Path(self.temp.name)/'作品'; folder.mkdir(); target=folder/'标题_v001.md'; original=Path.open
        def race(path,mode='r',*a,**kw):
            if path==target and mode=='xb':
                with original(path,'wb') as handle: handle.write(b'other-writer-data')
                raise PermissionError('模拟竞争写入后访问被拒绝')
            return original(path,mode,*a,**kw)
        with patch.object(Path,'open',race):
            with self.assertRaises(PermissionError): OutputFiles.write_to(folder,'标题',b'new')
        self.assertEqual(target.read_bytes(),b'other-writer-data')

if __name__=='__main__': unittest.main()
