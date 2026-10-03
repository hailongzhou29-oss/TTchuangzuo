import json,tempfile,unittest
from pathlib import Path
from app.core.services import Workspace
from app.core.work_context import CurrentWork
from app.core.selection import selection
from app.core.project_memory import ProjectMemory,parse_memory,accept_memory
from app.core.knowledge import FactService

class MemoryUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='tt_memory_'); self.store=Workspace(Path(self.temp.name)/'data').create('合成记忆','小说'); self.did=self.store.documents()[0]['id']; self.work=CurrentWork.load(self.store,self.did,selection('novel')); self.source='阿宁右手受伤。\n阿宁是林远的姐姐。\n阿宁锁好了车站大门。\n抽屉里的红钥匙尚未使用。'; self.work.edit(self.source); self.work.save()
    def tearDown(self): self.temp.cleanup()
    def memory(self):
        return dict(summary='阿宁受伤并锁门，红钥匙未用。',characters=['阿宁右手受伤'],relationships=['阿宁是林远的姐姐'],events=['锁好车站门'],foreshadow=['红钥匙未使用'],unresolved=['红钥匙用途'],evidence=self.source.splitlines(),facts=[dict(category=k,content=v.rstrip('。'),entities=['阿宁'],evidence=v) for k,v in zip(['character','relationship','event','foreshadow'],self.source.splitlines())])
    def accepted(self):
        value=parse_memory(json.dumps(self.memory(),ensure_ascii=False),self.source); self.assertTrue(accept_memory(self.store,self.did,self.work.revision,value)); return ProjectMemory(self.store)
    def test_all_semantic_kinds_have_exact_evidence(self):
        memory=self.accepted(); record=memory.refresh()[self.did]; self.assertEqual({f['category'] for f in record['facts']},{'character','relationship','event','foreshadow'})
        value=self.memory(); value['facts'][0]['evidence']='原文没有的手伤'
        with self.assertRaises(ValueError): parse_memory(json.dumps(value),self.source)
    def test_fact_source_revision_invalidates_current_confirmed_fact(self):
        memory=self.accepted(); fid=memory.propose_fact(self.did,1); service=FactService(self.store); service.set_state(fid,'confirmed'); self.assertEqual(len(service.active(self.did)),1); old=service.get(fid)
        self.work.edit(self.source.replace('姐姐','妹妹')); self.work.save(); self.assertFalse(service.source_current(old)); self.assertEqual(service.active(self.did),[]); self.assertEqual(memory.refresh()[self.did]['method'],'当前原文自动节选'); self.assertEqual(memory.refresh()[self.did].get('facts',[]),[])
    def test_user_correction_keeps_old_provenance_and_requires_confirmation(self):
        fid=self.accepted().propose_fact(self.did,1); service=FactService(self.store); before=service.get(fid); service.revise(fid,'阿宁是林远的妹妹'); after=service.get(fid); self.assertEqual(after['state'],'candidate'); self.assertIsNone(after['source_document_id']); self.assertEqual(service.versions(fid)[0]['source_revision'],before['source_revision']); service.set_state(fid,'confirmed'); self.assertEqual(service.active(self.did)[0]['content'],'阿宁是林远的妹妹')
    def test_memory_and_facts_are_project_isolated(self):
        self.accepted(); other=Workspace(Path(self.temp.name)/'other').create('另一个合成项目','小说')
        with self.assertRaises(ValueError): ProjectMemory(other).propose_fact(self.did,0)
        self.assertEqual(FactService(other).facts(),[])
    def test_cross_block_evidence_cannot_be_promoted(self):
        value=self.memory(); value['facts'][0]['evidence']='阿宁右手受伤。\n阿宁是林远的姐姐。'; parsed=parse_memory(json.dumps(value),self.source); accept_memory(self.store,self.did,self.work.revision,parsed)
        with self.assertRaises(ValueError): ProjectMemory(self.store).propose_fact(self.did,0)
    def test_terminal_punctuation_resolves_only_unique_literal_source(self):
        value=self.memory(); value['facts'][1]['evidence']='阿宁是林远的姐姐，'; parsed=parse_memory(json.dumps(value),self.source)
        self.assertEqual(parsed['facts'][1]['evidence'],'阿宁是林远的姐姐。'); receipt=parsed['evidence_resolutions'][0]; self.assertEqual(self.source[receipt['start']:receipt['end']],receipt['source_quote']); self.assertEqual(receipt['model_quote'],'阿宁是林远的姐姐，'); self.assertTrue(accept_memory(self.store,self.did,self.work.revision,parsed))
        fid=ProjectMemory(self.store).propose_fact(self.did,1); self.assertEqual(FactService(self.store).get(fid)['evidence'],'阿宁是林远的姐姐。')
    def test_punctuation_locator_rejects_ambiguity_words_numbers_and_internal_changes(self):
        from app.core.project_memory import resolve_evidence
        for quote,source in [('阿宁是林远的姐姐，',self.source+'\n阿宁是林远的姐姐。'),('阿宁是林远的妹妹，',self.source),('同一晚19:01拿出唯一的红钥匙。','同一晚19:00拿出唯一的红钥匙，钥匙完好。'),('同一晚19，00拿出唯一的红钥匙。','同一晚19:00拿出唯一的红钥匙，钥匙完好。')]:
            with self.subTest(quote=quote),self.assertRaises(ValueError): resolve_evidence(quote,source)
    def test_resolved_citation_still_invalidates_on_revision_change(self):
        value=self.memory(); value['facts'][1]['evidence']='阿宁是林远的姐姐，'; parsed=parse_memory(json.dumps(value),self.source); old=self.work.revision; self.work.edit(self.source.replace('姐姐','妹妹')); self.work.save(); self.assertFalse(accept_memory(self.store,self.did,old,parsed))

if __name__=='__main__': unittest.main()
