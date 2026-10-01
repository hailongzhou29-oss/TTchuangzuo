import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from PySide6.QtGui import QColor,QImage
from app.core.cover import default_cover
from app.core.image_service import ImageService
from app.core.processes import process_alive,process_started
from app.core.services import Workspace
from app.core.task_runtime import execution_owner,owned_task,owner_alive,task_execution
from app.providers.contracts import CancelToken
from app.providers.image_contracts import ImageConnection
from app.storage.image_connections import ImageConnectionStore
from app.storage.project import ProjectStore,new_id,now

ROOT=Path(__file__).resolve().parents[1]

class TaskRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='TT RUNTIME_TEST_ONLY ')
        self.root=Path(self.temporary.name)
        self.workspace=Workspace(self.root/'data')
        self.store=self.workspace.create('RUNTIME_TEST_ONLY','小说')
        self.store.set_setting('runtime_test_fixture',True)

    def tearDown(self):
        self.temporary.cleanup()

    def task(self):
        task_id=new_id()
        with self.store.connection(write=True) as con:
            con.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?)',
                (task_id,self.store.metadata()['id'],None,'discussion',json.dumps(dict(owner_pid=0)),
                 'ready',None,now(),now()))
        return task_id

    def test_nested_operations_share_one_lease_and_release_on_error(self):
        task=self.task()
        with self.assertRaisesRegex(RuntimeError,'fixture'):
            with task_execution(self.store,task,'submit') as outer:
                with task_execution(self.store,task,'download') as inner:
                    self.assertEqual(outer,inner)
                    self.assertEqual(execution_owner(self.store,task)['operation'],'submit')
                    raise RuntimeError('fixture')
        self.assertEqual(execution_owner(self.store,task)['active'],0)

    def test_keyword_arguments_preserved_and_snapshot_not_mutated(self):
        task=self.task()
        class Example:
            store=self.store
            @owned_task('fixture')
            def execute(self,snapshot,*,value):
                return value
        snapshot=dict(task_id=task,owner_pid=0)
        self.assertEqual(Example().execute(snapshot=snapshot,value='kept'),'kept')
        self.assertEqual(snapshot,dict(task_id=task,owner_pid=0))
        self.assertEqual(execution_owner(self.store,task)['active'],0)

    def test_process_creation_time_distinguishes_reused_pid(self):
        started=process_started(os.getpid())
        self.assertIsNotNone(started)
        self.assertTrue(process_alive(os.getpid()))
        self.assertFalse(owner_alive({},dict(pid=os.getpid(),process_started='different-process-creation')))
        self.assertTrue(owner_alive({},dict(pid=os.getpid(),process_started=started)))

    def test_v5_upgrade_backs_up_before_adding_runtime_ownership(self):
        with self.store.connection(write=True) as con:
            con.execute('DROP TABLE task_leases')
            con.execute('PRAGMA user_version=5')
        self.store.check()
        backups=list((self.store.root/'backups').glob('升级前_v5_*.sqlite'))
        self.assertTrue(backups)
        import sqlite3
        # The newest backup is the actual pre-upgrade database, still at v5.
        with closing(sqlite3.connect(max(backups,key=lambda path:path.stat().st_mtime_ns))) as con:
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0],5)
            self.assertIsNone(con.execute("SELECT name FROM sqlite_master WHERE name='task_leases'").fetchone())
        with self.store.connection() as con:
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0],6)

    def test_actual_process_takeover_query_nested_download_and_restore_isolation(self):
        settings=self.root/'settings'
        connections=ImageConnectionStore(settings)
        connections.save(ImageConnection('runtime_image','隔离固定响应','image_http','runtime-image',
            base_url='https://example.invalid',sizes=('1024x1536',),poll_path='/jobs/{job_id}'),'runtime-fixture-key')
        image=self.root/'fixture.png'
        fixture=QImage(64,96,QImage.Format.Format_RGB32)
        fixture.fill(QColor('#446688'))
        self.assertTrue(fixture.save(str(image)))
        command=[sys.executable,str(ROOT/'tools'/'runtime_task_fixture.py')]
        options=dict(cwd=str(ROOT),text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        original=subprocess.run(command+['submit',str(self.store.root),str(settings),str(image)],
                                capture_output=True,timeout=10,**options)
        self.assertEqual(original.returncode,0,original.stderr)
        metadata=json.loads(original.stdout.strip())
        service=ImageService(self.store,ROOT/'resources',connections)
        task_id=metadata['task_id']
        before=service.get(task_id)['snapshot']
        with self.store.connection() as con:
            frozen_json=con.execute('SELECT snapshot FROM tasks WHERE id=?',(task_id,)).fetchone()[0]
        self.assertFalse(process_alive(metadata['pid']))
        self.assertEqual(service.get(task_id)['state'],'accepted')
        child=subprocess.Popen(command+['query',str(self.store.root),str(settings),str(image),'--task-id',task_id],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**options)
        try:
            ready=json.loads(child.stdout.readline())
            self.assertTrue(ready['ready'])
            self.assertIsNone(child.poll())
            runtime=execution_owner(self.store,task_id)
            # Windows venv python.exe may launch a different execution process.
            self.assertEqual(runtime['pid'],ready['pid'])
            self.assertEqual(runtime['active'],1)
            self.assertEqual(runtime['operation'],'image_query')
            self.assertTrue(owner_alive(before,runtime))
            self.assertEqual(service.recover(),[])
            self.assertEqual(service.get(task_id)['state'],'accepted')
            class NeverCalled:
                calls=0
                def query(self,*args,**kwargs):
                    self.calls+=1
                    raise AssertionError('duplicate provider call')
            duplicate=NeverCalled()
            with self.assertRaisesRegex(ValueError,'仍在处理'):
                service.query(task_id,CancelToken(),duplicate)
            self.assertEqual(duplicate.calls,0)
            with self.assertRaisesRegex(ValueError,'仍在处理'):
                service.materialize(task_id,CancelToken())
            with self.assertRaisesRegex(ValueError,'仍在处理'):
                service.trash(task_id)
            archive=self.root/'active-task.ttbackup'
            self.workspace.backup(self.store,archive)
            restored=self.workspace.restore(archive)
            self.assertIsNone(execution_owner(restored,task_id))
            self.assertEqual(ImageService(restored,ROOT/'resources',connections).get(task_id)['state'],'uncertain')
            self.assertEqual(execution_owner(self.store,task_id)['active'],1)
            child.stdin.write('release\n')
            child.stdin.flush()
            result=json.loads(child.stdout.readline())
            child.wait(timeout=10)
            self.assertEqual(child.returncode,0,child.stderr.read())
            self.assertEqual(result,dict(status='verified',queries=1,downloads=1))
            current=service.get(task_id)
            self.assertEqual(current['snapshot'],before)
            with self.store.connection() as con:
                self.assertEqual(con.execute('SELECT snapshot FROM tasks WHERE id=?',(task_id,)).fetchone()[0],frozen_json)
            self.assertEqual(execution_owner(self.store,task_id)['active'],0)
            self.assertEqual(len(current['asset_ids']),1)
            self.assertTrue((self.store.root/current['result']['images'][0]['relative']).is_file())
        finally:
            if child.poll() is None:
                child.stdin.close()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    child.wait(timeout=5)
            for stream in (child.stdin,child.stdout,child.stderr):
                if stream:
                    stream.close()
