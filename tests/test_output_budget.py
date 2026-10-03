import json,os,unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import test_agent_workflow as fixtures
from app.core.output_budget import output_plan,AUTO_LIMIT
from app.providers.contracts import Connection,TextResult,CancelToken
from app.storage.connections import ConnectionStore
from app.core.agent_candidates import AgentCandidates

class OutputBudgetTests(unittest.TestCase):
    setUp=fixtures.AgentTests.setUp
    tearDown=fixtures.AgentTests.tearDown
    def official(self,**values):
        self.c=replace(self.c,model='deepseek-flash',base_url='https://api.deepseek.com',**values)
        self.connections.save(self.c); self.c=self.connections.get(self.c.id)
    def test_legacy_saved_limit_remains_manual_128(self):
        value=self.c.public(); value.pop('output_mode'); value['max_output']=128
        self.connections.path.write_text(json.dumps(dict(schema_version=1,connections=[value])),encoding='utf-8')
        reopened=ConnectionStore(self.connections.path.parent).get(self.c.id)
        self.assertEqual((reopened.max_output,reopened.output_mode),(128,'manual'))
    def test_low_manual_limit_blocks_before_task_and_keeps_body(self):
        self.official(max_output=128); before=self.work.text
        with self.assertRaisesRegex(ValueError,'输出长度'):
            self.flow.prepare(self.c,'modify','修改全文',(0,len(before)),True)
        self.assertEqual(self.work.text,before)
        with self.store.connection() as con: self.assertEqual(con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)
        self.assertEqual(self.connections.get(self.c.id).max_output,128)
    def test_auto_effective_limit_is_frozen_and_sent_without_mutating_saved_value(self):
        self.official(max_output=128,output_mode='auto')
        snap=self.flow.prepare(self.c,'modify','修改全文',(0,len(self.work.text)),True)
        self.assertEqual(snap['model_selection']['max_output'],1536)
        self.assertEqual(snap['budget']['max_output'],1536)
        seen=[]
        class Capture(fixtures.Provider):
            def generate(p,c,*a,**kw): seen.append(c.max_output); return super().generate(c,*a,**kw)
        result=self.flow.service.execute(snap,CancelToken(),provider=Capture([dict(text='完整的新句。',explanation='改写完成')]))
        self.assertEqual(result['status'],'completed'); self.assertEqual(seen[0],1536)
        self.assertEqual(self.connections.get(self.c.id).max_output,128)
    def test_long_novel_uses_current_chapter_and_segment_uses_current_segment(self):
        self.official(output_mode='auto')
        short=output_plan(self.c,dict(output='novel',words=150))
        long=output_plan(self.c,dict(output='novel',length='长篇连载',words=1000000,chapter_words=2500))
        self.assertEqual(short['effective_tokens'],1536); self.assertEqual(long['effective_tokens'],4096)
        segmented=output_plan(self.c,dict(output='novel',words=20000,_segment=dict(words=3000)))
        self.assertEqual(segmented['effective_tokens'],4096)
        script=output_plan(self.c,dict(output='script',duration=3600,_segment=dict(duration=180)))
        self.assertLess(script['effective_tokens'],AUTO_LIMIT)
    def test_auto_is_bounded_by_app_context_and_known_model(self):
        self.official(output_mode='auto')
        large=output_plan(self.c,dict(output='novel',words=1000000)); self.assertEqual(large['effective_tokens'],AUTO_LIMIT); self.assertTrue(large['needs_attention'])
        constrained=output_plan(self.c,dict(output='novel',words=150),input_tokens=64000)
        self.assertEqual(constrained['effective_tokens'],1024)
        unknown=output_plan(replace(self.c,model='unverified-model'),{},'generate')
        self.assertLessEqual(unknown['effective_tokens'],min(self.c.max_output,4096));self.assertIsNone(unknown['provider_cap'])
        with self.assertRaises(ValueError): output_plan(self.c,{},input_tokens=65535)
    def test_truncated_draft_survives_reopen_but_cannot_be_adopted(self):
        self.official(output_mode='auto'); before=self.work.text
        snap=self.flow.prepare(self.c,'modify','修改全文',(0,len(before)),True)
        result=self.flow.service.execute(snap,CancelToken(),provider=fixtures.Provider([TextResult(text='{"text":"未完成',status='incomplete',finish_reason='length',accepted=True,error='输出被截断')]))
        self.flow.save_candidate(snap,result,'输出被截断',result.get('text','')); cid=snap['task_id']
        reopened=AgentCandidates(self.store); self.assertEqual(reopened.row(cid)['state'],'partial')
        from app.storage.project import ConflictError
        with self.assertRaises((ValueError,ConflictError)): reopened.adopt(cid,self.work)
        self.assertEqual(self.work.text,before)

class OutputSettingsTests(unittest.TestCase):
    def test_save_reopen_isolate_connections_and_preserve_production_limit(self):
        import tempfile
        from PySide6.QtWidgets import QApplication
        from app.ui.v2_window import MainWindow
        from app.core.services import Workspace
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory(prefix='tt_output_ui_') as temp,patch('socket.socket.connect',side_effect=AssertionError('offline test')):
            root=Path(temp); connections=ConnectionStore(root/'prefs')
            connections.save(Connection('live_deepseek','Existing','deepseek','deepseek-flash',base_url='https://api.deepseek.com',max_output=128,timeout=60))
            connections.save(Connection('other','Other','custom','model',base_url='https://example.org',max_output=4096))
            win=MainWindow(Workspace(root/'data'),fixtures.ROOT/'resources',root/'prefs'/'prefs.json')
            try:
                settings=win.settings; mode,tokens,structured,note=settings.output_controls['deepseek_official']
                self.assertEqual((tokens.value(),mode.currentData()),(128,'manual'))
                self.assertEqual(connections.get('live_deepseek').max_output,128)
                mode.setCurrentIndex(mode.findData('auto')); structured.setChecked(True)
                self.assertTrue(settings.channel_form_is_dirty('deepseek_official'))
                settings.save_current_channel('deepseek_official')
                self.assertFalse(settings.channel_form_is_dirty('deepseek_official'))
                reopened=ConnectionStore(root/'prefs').get('live_deepseek')
                self.assertEqual((reopened.max_output,reopened.output_mode,reopened.json_mode),(128,'auto',True))
                self.assertEqual(connections.get('other').max_output,4096)
                settings.provider_list.setCurrentRow(settings.api_provider_keys.index('deepseek_official')); settings.activate_current_model()
                self.assertEqual(win.options['default_connection'],'live_deepseek')
            finally: win.close(); win.deleteLater(); app.processEvents()
            win=MainWindow(Workspace(root/'data'),fixtures.ROOT/'resources',root/'prefs'/'prefs.json')
            try:
                mode,tokens,structured,_=win.settings.output_controls['deepseek_official']
                self.assertEqual((tokens.value(),mode.currentData(),structured.isChecked()),(128,'auto',True))
            finally: win.close(); win.deleteLater(); app.processEvents()

if __name__=='__main__': unittest.main()
