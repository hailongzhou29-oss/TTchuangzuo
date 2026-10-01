import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.actions import freeze,record
from app.core.files import digest
from app.core.services import Workspace

class ActionScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='TT 操作归属隔离 ')
        self.workspace=Workspace(Path(self.temp.name)/'data')
        self.first=self.workspace.create('第一个项目','小说')
        self.second=self.workspace.create('第二个项目','小说')
        self.owner=SimpleNamespace(store=self.first,document_id=self.first.documents()[0]['id'])
    def tearDown(self):
        self.temp.cleanup()
    def test_selected_project_does_not_inherit_other_editor_document(self):
        snapshot=freeze(self.owner,'P07','重命名',store=self.second)
        self.assertEqual(snapshot['scope']['project_id'],self.second.metadata()['id'])
        self.assertIsNone(snapshot['scope']['document_id'])
        self.assertEqual(snapshot['input_snapshot']['text_hash'],digest(''))
    def test_record_remains_with_original_project_after_window_switch(self):
        snapshot=freeze(self.owner,'E01','保存')
        self.owner.store=self.second
        record(self.owner,snapshot,'handler_returned',store=self.first)
        with self.first.connection() as con:
            row=con.execute('SELECT snapshot,state FROM action_operations').fetchone()
        self.assertEqual(json.loads(row['snapshot'])['scope']['project_id'],self.first.metadata()['id'])
        self.assertEqual(row['state'],'handler_returned')
        with self.second.connection() as con:
            self.assertIsNone(con.execute("SELECT name FROM sqlite_master WHERE name='action_operations'").fetchone())
    def test_wrong_project_destination_is_rejected(self):
        snapshot=freeze(self.owner,'E01','保存')
        with self.assertRaises(ValueError):
            record(self.owner,snapshot,'handler_returned',store=self.second)
    def test_new_project_result_is_separate_from_empty_input_scope(self):
        snapshot=freeze(self.owner,'P01','新建',store=None)
        record(self.owner,snapshot,'handler_returned',store=self.second)
        with self.second.connection() as con:
            saved=json.loads(con.execute('SELECT snapshot FROM action_operations').fetchone()[0])
        self.assertIsNone(saved['scope']['project_id'])
        self.assertEqual(saved['result_project_id'],self.second.metadata()['id'])
    def test_empty_workspace_view_toggle_does_not_require_selected_project(self):
        from app.ui.window import MainWindow
        owner=SimpleNamespace(store=None,document_id=None)
        def toggle_project_view():
            return 'view_changed'
        self.assertEqual(MainWindow.run_action(owner,toggle_project_view,'P05','列表视图'),'view_changed')
