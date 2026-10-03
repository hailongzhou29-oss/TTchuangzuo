import json,sys,time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import unittest
import test_agent_workflow as fixtures
Provider=fixtures.Provider
ROOT=fixtures.ROOT
from app.core.work_context import intent,CurrentWork
from app.core.agent_candidates import AgentCandidates
from app.core.creation_flow import CreationFlow
from app.core.task_messages import failure_message
from app.providers.contracts import TextResult,CancelToken,Connection
from app.providers.codex_text import CodexTextProvider
from app.storage.project import ConflictError,LockedError

class UpgradeTests(unittest.TestCase):
    setUp=fixtures.AgentTests.setUp
    tearDown=fixtures.AgentTests.tearDown
    candidate=fixtures.AgentTests.candidate
    def official(self,**changes):
        self.c=replace(self.c,base_url='https://api.deepseek.com',model='deepseek-flash',**changes); self.connections.save(self.c); self.c=self.connections.get(self.c.id)
    def test_feedback_intent_and_explicit_discussion(self):
        self.assertEqual(intent('台词太少，画面不够详细'),'modify')
        self.assertEqual(intent('先讨论：台词太少，画面不够详细怎么办？'),'discuss')
    def test_prefetch_reads_current_and_requested_chapter_and_rules(self):
        self.official(); other=self.store.add_document('第二章 遗失的钥匙','钥匙在旧仓库。',kind='chapter'); self.store.set_setting('v2_document:'+other,True)
        snap=self.flow.prepare(self.c,'modify','参考第二章钥匙所在位置，修改已选内容',(0,3),True)
        context=json.loads(snap['messages'][1]['content'].split('\n',1)[1]); docs=context['prefetched_documents']
        self.assertTrue(any(d['document_id']==self.did and d['complete'] for d in docs))
        self.assertTrue(any(d['document_id']==other and d['blocks'][0]['text']=='钥匙在旧仓库。' for d in docs))
        self.assertFalse(snap['context_coverage']['model_tool_calls']); self.assertTrue(snap['rule_snapshot'])
        class Capture(Provider):
            def generate(this,c,secret,messages,cancel,on_text,**kw):
                self.assertNotIn('tools',kw); self.assertIn('钥匙在旧仓库',json.dumps(messages,ensure_ascii=False))
                return super(Capture,this).generate(c,secret,messages,cancel,on_text,**kw)
        result=self.flow.service.execute(snap,CancelToken(),provider=Capture([dict(text='改稿',explanation='对应选段')]))
        cid=self.candidates.save(snap,result); original=self.work.text; self.candidates.adopt(cid,self.work)
        self.assertEqual(self.work.text,'改稿'+original[3:]); self.assertEqual(self.store.document(other)['text'],'钥匙在旧仓库。')
    def test_prefetch_coverage_does_not_claim_unread_chapters(self):
        self.official(); other=self.store.add_document('第二章 超长材料','材料'*7000,kind='chapter')
        snap=self.flow.prepare(self.c,'discuss','说明第二章有什么',development_test=True)
        self.assertIn(other,[d['document_id'] for d in snap['context_coverage']['omitted']])
        self.assertIn('不得声称已读全书',snap['messages'][0]['content'])
    def test_dsml_is_not_executed_and_used_round_receipt_survives(self):
        self.official(); original=self.work.text
        response=TextResult(text='<｜｜DSML｜｜ calls><invoke name="read_document"/>',status='completed',accepted=True,request_id='offline-dsml',raw_usage={'prompt_tokens':20,'completion_tokens':10})
        snap=self.flow.prepare(self.c,'modify','修改第一段',(0,3),True)
        result=self.flow.service.execute(snap,CancelToken(),provider=Provider([response]))
        self.assertEqual(result['status'],'invalid_output'); self.assertEqual(result['used_calls'],1)
        self.assertEqual(result['request_id'],'offline-dsml'); self.assertEqual(result['external_receipts'][0]['request_id'],'offline-dsml')
        self.assertEqual(self.work.text,original); self.assertFalse(result.get('tool_trace'))
    def test_native_tools_remain_whitelisted_and_close_protocol(self):
        self.official(tool_call=True)
        calls=[dict(id='read-1',type='function',function=dict(name='read_document',arguments=json.dumps(dict(document_id=self.did))))]
        provider=Provider([TextResult(status='tool_required',accepted=True,tool_calls=calls),dict(text='已读修改',explanation='以原文为依据')])
        snap=self.flow.prepare(self.c,'modify','修改第一段',(0,3),True)
        result=self.flow.service.execute(snap,CancelToken(),provider=provider)
        self.assertEqual(result['status'],'completed',result.get('error')); self.assertEqual(provider.calls,2)
        self.assertTrue(any(x['role']=='tool' for x in result['protocol_transcript']))
        self.assertNotIn('context_coverage',snap)
    def test_regeneration_is_candidate_then_atomic_save_and_undo(self):
        before=self.work.text; n=len(self.store.revisions(self.did))
        value=dict(title='新作',synopsis='新简介',plan=['开篇'],characters='林晚',chapter_title='开篇',text='新的正文。')
        snap=self.flow.prepare(self.c,'generate',development_test=True)
        result=self.flow.service.execute(snap,CancelToken(),provider=Provider([value])); self.flow.apply(snap,result)
        self.assertEqual(self.work.text,before); self.assertEqual(len(self.store.revisions(self.did)),n)
        cid=snap['task_id']; self.candidates.adopt(cid,self.work); self.assertIn('新的正文',self.work.text)
        self.candidates.undo(cid,self.work); self.assertEqual(self.work.text,before)
    def test_setting_switch_and_locks_reject_regeneration(self):
        value=dict(title='新作',synopsis='新简介',plan=[],characters='',chapter_title='',text='覆盖正文。')
        snap=self.flow.prepare(self.c,'generate',development_test=True); result=self.flow.service.execute(snap,CancelToken(),provider=Provider([value])); cid=self.candidates.save(snap,result)
        self.store.lock(self.did,'结尾保持。',self.work.text.index('结尾保持。'))
        with self.assertRaises(LockedError): self.candidates.adopt(cid,self.work)
        self.store.set_setting('v2_selection',{'output':'script'})
        with self.assertRaises(ConflictError): self.candidates.adopt(cid,self.work)
    def test_unsaved_setting_change_also_invalidates_candidate(self):
        cid,_=self.candidate('新稿'); self.work.config=dict(self.work.config,words=4000)
        self.assertEqual(self.candidates.history(self.work)[0]['state'],'stale')
        with self.assertRaises(ConflictError): self.candidates.adopt(cid,self.work)
    def test_partial_and_complete_history_follow_request_order(self):
        partial=self.flow.prepare(self.c,'modify','修改第一段',(0,3),True)
        result=self.flow.service.execute(partial,CancelToken(),provider=Provider([TextResult(text='仅收到片段',status='incomplete',accepted=True)]))
        self.flow.save_candidate(partial,result,'未完成','仅收到片段')
        cid,_=self.candidate('新改稿')
        entries=self.candidates.history(self.work)
        self.assertEqual([r['id'] for r in entries],[partial['task_id'],cid])
        self.assertEqual([r['state'] for r in entries],['partial','pending'])
    def test_legacy_complete_uses_original_baseline_and_zero_output_is_empty(self):
        cid,snap=self.candidate('替换句'); result=self.candidates.row(cid)['result']
        with self.store.connection(write=True) as con: con.execute('DELETE FROM agent_candidates WHERE id=?',(cid,))
        self.flow.save_candidate(snap,result,'完整旧入口结果'); self.assertEqual(self.candidates.history(self.work)[0]['state'],'pending')
        self.work.edit('用户已经修改'); self.work.save()
        with self.assertRaises(ConflictError): self.candidates.adopt(cid,self.work)
        old=len(self.store.setting('v2_candidates',[])); self.flow.save_candidate(snap,dict(status='failed',text=''),'失败')
        self.assertEqual(len(self.store.setting('v2_candidates',[])),old)
        self.assertIn('未收到正文',failure_message(dict(status='failed',text='')))
    def test_codex_error_event_is_terminal_with_safe_diagnostics(self):
        path=Path(self.temp.name)/'failed_cli.py'
        path.write_text('import json,sys,time\nsys.stdin.read()\nprint(json.dumps({"type":"thread.started","thread_id":"synthetic-thread"}),flush=True)\nprint(json.dumps({"type":"turn.started","model":"safe-model"}),flush=True)\nprint(json.dumps({"type":"turn.failed","error":{"code":"unauthorized","message":"PRIVATE_TOKEN_DO_NOT_STORE"}}),flush=True)\ntime.sleep(30)\n',encoding='utf-8')
        prefix=[sys.executable,str(path)]; provider=CodexTextProvider(); provider.probes[tuple(prefix)]={'features':[]}
        c=Connection('cli','CLI','codex','',timeout=30,max_output=512)
        with patch('app.providers.codex_text.command_prefix',return_value=prefix):
            start=time.monotonic(); result=provider.generate(c,[dict(role='user',content='合成失败')],CancelToken())
        self.assertLess(time.monotonic()-start,8); self.assertEqual(result.status,'failed'); self.assertEqual(result.finish_reason,'error')
        self.assertEqual(result.request_id,'synthetic-thread'); self.assertEqual(result.model,'safe-model')
        self.assertEqual(result.diagnostics['error_category'],'unauthorized'); self.assertIsNotNone(result.diagnostics['exit_code'])
        self.assertNotIn('PRIVATE_TOKEN',json.dumps(result.public())); self.assertEqual(result.text,'')
