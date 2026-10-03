import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.core import script_settings as settings
from app.core.creation_flow import parse_output
from app.core.speech_records import THIRD,save_speech_work,verify,estimate_speech
from app.core.work_context import CurrentWork
from app.core.services import Workspace
from test_script_unified import config,output

ROOT=Path(__file__).resolve().parents[1]

class ScriptSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='tt_script_safety_'); self.root=Path(self.temp.name)
        self.store=Workspace(self.root/'data').create('保存安全验证','剧本'); self.did=self.store.documents()[0]['id']
        self.work=CurrentWork.load(self.store,self.did,config())
        value=parse_output(json.dumps(output([dict(type='dialogue',speaker='阿宁',text='原句。')]),ensure_ascii=False),'generate',self.work.config)
        self.work.edit(value['text']); self.work.save()
        self.store.set_setting('v2_speech:'+self.did,dict(revision=self.work.revision,records=value['speech_records']))
    def tearDown(self): settings.reload_catalog(); self.temp.cleanup()
    def changed(self,body=False,third=False):
        parts=self.work.text.split(THIRD,1)
        if body: parts[0]=parts[0].replace('原句。','正文新句。')
        if third: parts[1]=parts[1].replace('原句。','台词手改草稿。')
        self.work.edit(THIRD.join(parts)); return self.work.text
    def test_both_edits_save_complete_text_without_overwrite(self):
        text=self.changed(True,True); before=self.work.revision
        self.assertTrue(save_speech_work(self.work)); self.assertEqual(self.work.text,text)
        self.assertNotEqual(self.work.revision,before); self.assertEqual(self.store.document(self.did)['text'],text)
        self.assertEqual(self.store.setting('v2_third_draft:'+self.did)['text'],text)
    def test_third_then_body_draft_survives_repeated_save_and_reopen(self):
        self.changed(third=True); self.assertTrue(save_speech_work(self.work))
        text=self.changed(body=True); self.assertTrue(save_speech_work(self.work))
        reopened=CurrentWork.load(self.store,self.did,self.work.config)
        self.assertEqual(reopened.text,text); self.assertTrue(save_speech_work(reopened))
        self.assertEqual(reopened.text,text); self.assertTrue(self.store.setting('v2_third_unsynced:'+self.did))
    def test_explicit_rebuild_keeps_full_conflicting_revision_and_draft(self):
        text=self.changed(True,True); save_speech_work(self.work); original_revision=self.work.revision
        self.assertFalse(save_speech_work(self.work,rebuild=True)); verify(self.work.text)
        self.assertIn('正文新句。',self.work.text.split(THIRD)[1]); self.assertNotIn('台词手改草稿。',self.work.text)
        self.assertNotEqual(self.work.revision,original_revision)
        self.assertEqual(self.store.setting('v2_third_draft:'+self.did)['text'],text)
        with self.store.connection() as con:
            row=con.execute('SELECT * FROM revisions WHERE id=?',(original_revision,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row['text'],text)
    def test_only_body_edit_syncs_and_manual_corrected_third_resolves(self):
        self.changed(body=True); self.assertFalse(save_speech_work(self.work)); verify(self.work.text)
        self.work.edit(self.work.text+'\n手改'); save_speech_work(self.work)
        self.work.edit(self.work.text.removesuffix('\n手改')); self.assertFalse(save_speech_work(self.work)); verify(self.work.text)
    def test_legacy_unsynced_third_is_preserved_without_previous_records(self):
        self.store.set_setting('v2_speech:'+self.did,{})
        self.changed(third=True); self.work.save('旧草稿')
        text=self.changed(body=True); self.assertTrue(save_speech_work(self.work)); self.assertEqual(self.work.text,text)
    def test_catalog_missing_damaged_empty_and_retry_preserve_migration(self):
        original=settings.CATALOG_PATH; settings.CATALOG_PATH=self.root/'rules.json'
        try:
            for content,kind in [(None,'missing'),('{bad','damaged'),('{"groups":{}}','empty')]:
                if content is not None: settings.CATALOG_PATH.write_text(content,encoding='utf-8')
                self.assertFalse(settings.reload_catalog()); self.assertEqual(settings.CATALOG_STATE['kind'],kind)
                with self.assertRaisesRegex(ValueError,'规则'): settings.validate_script(self.work.config)
            old={'kind':'script','format':'电影片段','density':'台词主导','advanced':{'未知旧项':'不丢原文'}}
            pending=settings.migrate(old); self.assertEqual(pending['script_settings']['migration_original'],old)
            settings.CATALOG_PATH.write_bytes(original.read_bytes()); self.assertTrue(settings.reload_catalog())
            result=settings.migrate(pending)
            self.assertEqual(result['script_settings']['values']['form'],'form.04')
            self.assertTrue(result['script_settings']['unresolved'])
        finally: settings.CATALOG_PATH=original; settings.reload_catalog()
    def test_initial_missing_catalog_module_import_does_not_crash(self):
        code="""from pathlib import Path
from unittest.mock import patch
import runpy
original=Path.read_text
def read(path,*a,**k):
    if path.name=='script_rules.json': raise FileNotFoundError(str(path))
    return original(path,*a,**k)
with patch.object(Path,'read_text',read):
    module=runpy.run_path('app/core/script_settings.py')
    assert module['CATALOG_STATE']['kind']=='missing'
    assert len(module['CATALOG'])==45
"""
        result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
    def test_auto_budget_varies_and_adopted_strategy_does_not_change_choices(self):
        cinematic=config(form='form.04'); spoken=config(form='form.06'); normal=config(form='form.01')
        self.assertEqual([settings.budget(c)['range'] for c in [cinematic,spoken,normal]],[(.2,.4),(.65,.85),(.4,.65)])
        before=copy.deepcopy(spoken['script_settings'])
        result=parse_output(json.dumps(output([dict(type='dialogue',speaker='阿宁',text='说出选择。')]),ensure_ascii=False),'generate',spoken)
        self.assertIn('自动预算',result['adopted']['budget_strategy']); self.assertEqual(spoken['script_settings'],before)
        self.assertFalse(result['speech_estimate']['time_windows_available'])
    def test_foreign_language_has_no_chinese_estimate_or_soft_hard_block(self):
        c=config(word_range='10000-20000'); c['idea']='用英语写'; c['duration']=30
        self.assertFalse(settings.budget(c)['reliable']); self.assertIsNone(settings.budget(c)['word_budget'])
        self.assertTrue(settings.validate_script(c))
        english=config(); result=parse_output(json.dumps(output([dict(type='dialogue',speaker='阿宁',text='We need to leave now.')]),ensure_ascii=False),'generate',english)
        self.assertIsNone(result['estimated_duration']); self.assertIsNone(result['speech_estimate']['seconds'])
        self.assertIn('不支持可靠',result['text'])
        self.assertEqual(result['adopted']['budget_speed'],'没有适用估算器')
        auto=config(required_lines='汉'*1000); auto['duration']=30
        self.assertTrue(settings.validate_script(auto))
        auto['script_settings']['values']['speed']='speed.01'
        with self.assertRaisesRegex(ValueError,'全部目标时长'): settings.validate_script(auto)
    def test_narration_ratio_uses_estimated_time_not_record_count(self):
        c=config(language='language.03',narration_ratio='50')
        records=[dict(source='narration',text='汉'*30),dict(source='dialogue',text='汉'*10)]
        estimate=estimate_speech(c,records)
        self.assertEqual(estimate['narration_percent'],75); self.assertEqual(estimate['segments'],2)
        self.assertTrue(any('指定50%' in w for w in estimate['warnings']))

if __name__=='__main__': unittest.main()
