import unittest,json
import test_agent_workflow as workflow
from test_agent_workflow import Provider,ROOT
from app.core.work_context import intent,locate
from app.core.agent_candidates import AgentCandidates
from app.providers.contracts import CancelToken

class UpgradeTests(unittest.TestCase):
    setUp=workflow.AgentTests.setUp
    tearDown=workflow.AgentTests.tearDown
    candidate=workflow.AgentTests.candidate
    def test_natural_rewrite_intent_and_nonwriting_requests(self):
        for text in ['帮我改写一下','请帮我改写这段，让他多蒸了十分钟','只改这里，保留结尾','台词不动，只改动作']:
            self.assertEqual(intent(text),'modify',text)
        for text in ['只讨论，不改稿','把这段解释一下','优化建议，不要修改正文']:
            self.assertIn(intent(text),{'inspect','discuss'},text)
        self.assertEqual(intent('只检查，不要改写'),'inspect')
        with self.assertRaises(ValueError): locate(self.work.text,'只改这里')
    def test_plaintext_rewrite_requires_explicit_review(self):
        original=self.work.text; snap=self.flow.prepare(self.c,'modify','帮我改写已选内容',(0,3),True); snap['tools_enabled']=False
        result=self.flow.service.execute(snap,CancelToken(),provider=Provider(['修改后的完整句子。']))
        self.assertEqual(result['status'],'completed'); self.assertTrue(result['candidate']['needs_review']); cid=self.candidates.save(snap,result)
        with self.assertRaises(ValueError): self.flow.apply(snap,result)
        with self.assertRaises(ValueError): self.candidates.adopt(cid,self.work)
        self.assertEqual(self.work.text,original); self.candidates.adopt(cid,self.work,'已核对的新句'); self.assertEqual(self.work.text,'已核对的新句'+original[3:]); self.candidates.undo(cid,self.work); self.assertEqual(self.work.text,original)
    def test_keep_overall_ending_allows_local_first_sentence_edit(self):
        cid,snap=self.candidate('开头改变','只改这里，保留结尾',span=(0,3)); self.candidates.adopt(cid,self.work); self.assertTrue(self.work.text.endswith('结尾保持。'))
    def test_do_not_move_dialogue_synonym_is_enforced(self):
        cid,snap=self.candidate('男主：我走了。','台词不动，改写动作')
        from app.storage.project import LockedError
        with self.assertRaises(LockedError): self.candidates.adopt(cid,self.work)
    def test_semantic_refresh_does_not_block_undo_or_erase_other_memory(self):
        original=self.work.text; cid,_=self.candidate(); self.candidates.adopt(cid,self.work)
        self.store.set_setting('v2_memories',{self.did:{'summary':'检查后生成的新派生摘要'},'other-document':{'summary':'另一章的现有摘要'}})
        self.candidates.undo(cid,self.work); self.assertEqual(self.work.text,original)
        self.assertNotIn(self.did,self.store.setting('v2_memories')); self.assertEqual(self.store.setting('v2_memories')['other-document']['summary'],'另一章的现有摘要')

if __name__=='__main__': unittest.main()
