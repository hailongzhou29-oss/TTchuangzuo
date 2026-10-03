import json,tempfile,unittest,sqlite3
from pathlib import Path
from unittest.mock import patch
from app.core.services import Workspace
from app.core.selection import selection
from app.core.work_context import CurrentWork,intent
from app.core.creation_flow import CreationFlow
from app.core.agent_candidates import AgentCandidates
from app.core.files import digest
from app.providers.contracts import Connection,TextResult,CancelToken
from app.storage.connections import ConnectionStore
from app.storage.project import ConflictError,LockedError
ROOT=Path(__file__).resolve().parents[1]

class Provider:
    def __init__(self,values): self.values=list(values); self.calls=0
    def generate(self,c,secret,messages,cancel,on_text,**kwargs):
        value=self.values[min(self.calls,len(self.values)-1)]; self.calls+=1
        if isinstance(value,TextResult): return value
        text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False); on_text(text)
        return TextResult(text=text,status='completed',accepted=True,model=c.model)

class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='tt_agent_test_'); root=Path(self.temp.name); self.store=Workspace(root/'data').create('隔离作品','小说'); self.did=self.store.documents()[0]['id']; self.store.set_setting('v2_document:'+self.did,True); self.config=selection('novel'); self.work=CurrentWork.load(self.store,self.did,self.config); self.work.edit('第一段\n男主：我不会走。\n相同台词\n男主：我不会走。\n结尾保持。'); self.work.save(); self.connections=ConnectionStore(root/'prefs'); self.c=Connection('isolated','测试模型','deepseek','test-model',base_url='https://example.org',max_output=8192,context_limit=65536); self.connections.save(self.c); self.flow=CreationFlow(self.work,ROOT/'resources',self.connections); self.candidates=AgentCandidates(self.store)
    def tearDown(self): self.temp.cleanup()
    def candidate(self,text='新句',instruction='修改这句',span=None):
        span=span or (0,len(self.work.text)); snapshot=self.flow.prepare(self.c,'modify',instruction,span,True); result=self.flow.service.execute(snapshot,CancelToken(),provider=Provider([dict(text=text,explanation='模拟修改')])); self.assertEqual(result['status'],'completed',result.get('error')); cid=self.candidates.save(snapshot,result); return cid,snapshot
    def test_only_check_intent_and_no_revision_write(self):
        self.assertEqual(intent('只检查，别续写'),'inspect'); before=self.work.text; versions=len(self.store.revisions(self.did)); snap=self.flow.prepare(self.c,'inspect','只检查，别续写',development_test=True); result=self.flow.service.execute(snap,CancelToken(),provider=Provider(['只做检查。'])); self.assertEqual(self.flow.apply(snap,result),'只做检查。'); self.assertEqual(self.work.text,before); self.assertEqual(len(self.store.revisions(self.did)),versions)
    def test_candidate_does_not_write_before_adoption(self):
        before=self.work.text; n=len(self.store.revisions(self.did)); cid,_=self.candidate(); self.assertEqual(self.work.text,before); self.assertEqual(len(self.store.revisions(self.did)),n); self.assertEqual(self.candidates.row(cid)['state'],'pending')
    def test_repeated_text_targets_exact_second_id(self):
        before=self.work.text; start=before.rindex('男主：'); end=start+len('男主：我不会走。'); cid,_=self.candidate('男主：我在这里。',span=(start,end)); self.candidates.adopt(cid,self.work); self.assertIn('男主：我不会走。',self.work.text); self.assertEqual(self.work.text.count('男主：我在这里。'),1)
    def test_atomic_adopt_undo_idempotence(self):
        before=self.work.text; cid,_=self.candidate(); n=len(self.store.revisions(self.did)); receipt=self.candidates.adopt(cid,self.work); self.assertEqual(self.work.text,'新句'); self.assertEqual(len(self.store.revisions(self.did)),n+1); self.assertEqual(self.candidates.adopt(cid,self.work),receipt); self.assertEqual(len(self.store.revisions(self.did)),n+1); self.candidates.undo(cid,self.work); self.assertEqual(self.work.text,before); self.assertFalse(self.candidates.undo(cid,self.work))
    def test_manual_edit_blocks_old_candidate(self):
        cid,_=self.candidate(); self.work.edit(self.work.text+'用户手改'); changed=self.work.text
        with self.assertRaises(ConflictError): self.candidates.adopt(cid,self.work)
        self.assertEqual(self.work.text,changed)
    def test_another_window_change_blocks_candidate(self):
        cid,_=self.candidate(); self.store.save_document(self.did,self.work.revision,'另一个窗口已保存')
        with self.assertRaises(ConflictError): self.candidates.adopt(cid,self.work)
        self.assertEqual(self.store.document(self.did)['text'],'另一个窗口已保存')
    def test_another_project_rejects_candidate(self):
        cid,_=self.candidate(); other=Workspace(Path(self.temp.name)/'other').create('另一个作品','小说'); work=CurrentWork.load(other,other.documents()[0]['id'],self.config)
        with self.assertRaises(ConflictError): self.candidates.adopt(cid,work)
    def test_locked_text_rolls_back_all_updates(self):
        self.store.lock(self.did,'男主：我不会走。',self.work.text.index('男主：')); cid,_=self.candidate(); n=len(self.store.revisions(self.did))
        with self.assertRaises(LockedError): self.candidates.adopt(cid,self.work)
        self.assertEqual(len(self.store.revisions(self.did)),n); self.assertEqual(self.candidates.row(cid)['state'],'pending')
    def test_ending_preservation_enforced(self):
        cid,_=self.candidate('整段新结尾','第三章更狠，结尾不改')
        with self.assertRaises(ValueError): self.candidates.adopt(cid,self.work)
    def test_atomic_failure_rolls_back_revision_and_receipt(self):
        cid,_=self.candidate(); before=self.store.document(self.did); original=self.store.save_document
        def fail(*a,**k): original(*a,**k); raise OSError('模拟写入失败')
        with patch.object(self.store,'save_document',side_effect=fail):
            with self.assertRaises(OSError): self.candidates.adopt(cid,self.work)
        self.assertEqual(self.store.document(self.did)['head'],before['head']); self.assertEqual(self.candidates.row(cid)['state'],'pending')
    def test_pending_survives_reopen(self):
        cid,_=self.candidate(); self.assertEqual(AgentCandidates(self.store).pending()[0]['id'],cid)
        reopened=CurrentWork.load(self.store,self.did,self.config); self.candidates.adopt(cid,reopened); self.assertEqual(reopened.text,'新句')
    def test_latest_user_settings_invalidate_candidate(self):
        cid,_=self.candidate(); self.store.set_setting('v2_settings',{'关系':'朋友变成仇人'})
        with self.assertRaises(ConflictError): self.candidates.adopt(cid,self.work)
    def test_memory_invalidated_with_adoption(self):
        self.store.set_setting('v2_memories',{self.did:{'summary':'旧关系'}}); cid,_=self.candidate(); self.candidates.adopt(cid,self.work); self.assertNotIn(self.did,self.store.setting('v2_memories'))
    def test_invalid_json_and_empty_output_do_not_change_body(self):
        before=self.work.text
        for raw in ('{坏 JSON}','{"text":"","explanation":"空结果"}'):
            snap=self.flow.prepare(self.c,'modify','修改',development_test=True); r=self.flow.service.execute(snap,CancelToken(),provider=Provider([raw])); self.assertEqual(r['status'],'invalid_output'); self.assertEqual(self.work.text,before)
    def test_checkpoint_and_external_receipt_saved_locally(self):
        cid,snapshot=self.candidate()
        with self.store.connection() as con:
            self.assertGreater(con.execute('SELECT COUNT(*) FROM checkpoints WHERE thread_id=?',('agent:'+cid,)).fetchone()[0],0); self.assertEqual(con.execute('SELECT state FROM agent_external_rounds WHERE task_id=?',(cid,)).fetchone()[0],'completed')
        with self.assertRaises(ValueError): self.flow.service.execute(snapshot,CancelToken(),provider=Provider(['should not run']))
    def test_cancel_does_not_call_model(self):
        snap=self.flow.prepare(self.c,'inspect','检查',development_test=True); token=CancelToken(); token.cancel(); p=Provider(['unused']); result=self.flow.service.execute(snap,token,provider=p); self.assertEqual(p.calls,0); self.assertEqual(result['status'],'cancelled')
    def test_read_tools_only_in_inspection(self):
        from app.core.project_tools import ProjectTools
        snap=self.flow.prepare(self.c,'inspect','检查',development_test=True); tools=ProjectTools(self.store,ROOT/'resources',snap)
        with self.assertRaises(ValueError): tools.execute('propose_fact',{})
        with self.assertRaises(ValueError): tools.execute('shell',{})
        with self.assertRaises(ValueError): tools.execute('read_document',{'document_id':'other-project'})
    def test_tool_budget_closes_protocol_without_extra_round(self):
        from dataclasses import replace
        c=replace(self.c,tool_call=True); self.connections.save(c); snap=self.flow.prepare(c,'inspect','跨章节检查',development_test=True)
        calls=[dict(id='call-'+str(i),type='function',function=dict(name='search_project',arguments=json.dumps({'query':str(i)}))) for i in range(10)]
        p=Provider([TextResult(status='tool_required',tool_calls=calls,accepted=True)]); result=self.flow.service.execute(snap,CancelToken(),provider=p); self.assertEqual(result['status'],'budget_paused'); self.assertEqual(p.calls,1); self.assertEqual(sum(not v['outcome'].get('error') for v in result['tool_trace']),8); self.assertEqual(sum(m['role']=='tool' for m in result['protocol_transcript']),10)
    def test_planning_candidate_preserves_body_and_undo(self):
        self.work.config['length']='长篇连载'; before=self.work.text; snap=self.flow.prepare(self.c,'planning','修改大纲',development_test=True); result=self.flow.service.execute(snap,CancelToken(),provider=Provider([dict(synopsis='新简介',characters='角色',chapters=['第一章'])])); cid=self.candidates.save(snap,result); self.candidates.adopt(cid,self.work); self.assertEqual(self.work.text,before); self.assertEqual(self.store.setting('v2_plan')['synopsis'],'新简介'); self.candidates.undo(cid,self.work); self.assertEqual(self.work.text,before); self.assertIsNone(self.store.setting('v2_outline_id'))
    def test_compatible_model_bridge_reads_then_finishes(self):
        self.c=__import__('dataclasses').replace(self.c,verification={'json_tool_bridge':{'status':'已实测','supported':True}});self.connections.save(self.c)
        snap=self.flow.prepare(self.c,'inspect','检查',development_test=True); p=Provider([dict(action='read_document',arguments=json.dumps(dict(document_id=self.did)),text=''),dict(action='final',arguments='{}',text='当前正文的结尾是“结尾保持。”。')]); result=self.flow.service.execute(snap,CancelToken(),provider=p); self.assertEqual(result['status'],'completed'); self.assertEqual(result['used_calls'],2); self.assertEqual(result['tool_trace'][0]['outcome']['result']['document_id'],self.did); self.assertIn('结尾保持',result['candidate']['text'])
    def test_bridge_unauthorized_action_cannot_write(self):
        self.c=__import__('dataclasses').replace(self.c,verification={'json_tool_bridge':{'status':'已实测','supported':True}});self.connections.save(self.c)
        before=self.work.text; snap=self.flow.prepare(self.c,'inspect','检查',development_test=True); p=Provider([dict(action='shell',arguments='{}',text=''),dict(action='final',arguments='{}',text='只能讨论正文。')]); result=self.flow.service.execute(snap,CancelToken(),provider=p); self.assertEqual(self.work.text,before); self.assertIn('未授权',result['tool_trace'][0]['outcome']['error'])
    def test_bridge_three_model_round_limit(self):
        self.c=__import__('dataclasses').replace(self.c,verification={'json_tool_bridge':{'status':'已实测','supported':True}});self.connections.save(self.c)
        snap=self.flow.prepare(self.c,'inspect','检查',development_test=True); p=Provider([dict(action='search_project',arguments=json.dumps(dict(query='查询'+str(i))),text='') for i in range(4)]); result=self.flow.service.execute(snap,CancelToken(),provider=p); self.assertEqual(p.calls,3); self.assertEqual(result['status'],'budget_paused')

if __name__=='__main__': unittest.main()
