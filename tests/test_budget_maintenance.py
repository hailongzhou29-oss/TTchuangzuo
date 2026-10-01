import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from app.core.budget import BudgetBook,BudgetError,estimate,validate_price
from app.core.maintenance import automatic_backup,diagnostics
from app.core.services import Workspace
from app.core.tasks import TaskService
from app.providers.contracts import CancelToken,Connection,TextResult
from app.storage.connections import ConnectionStore
from app.storage.image_connections import ImageConnectionStore

ROOT=Path(__file__).resolve().parents[1]
PRICE=dict(currency='CNY',version='user-test-1',source='用户测试单价，非当前官方价格',input_per_million='1',cached_read_per_million='.1',output_per_million='2',input_includes_cached=True)

class Provider:
    calls=0
    def generate(self,connection,secret,messages,cancel,on_text,**kwargs):
        self.calls+=1
        on_text('中性固定响应')
        return TextResult(text='中性固定响应',status='completed',finish_reason='stop',model=connection.model,
            usage=dict(input=1000,output=100,cached_read=300,reasoning=40),raw_usage=dict(prompt_tokens=1000,completion_tokens=100))

class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='TT 预算并发 ')
        self.root=Path(self.temp.name)
        self.book=BudgetBook(self.root/'settings')
    def tearDown(self):
        self.temp.cleanup()
    def test_cached_and_reasoning_subitems_not_double_billed(self):
        result=estimate(PRICE,usage=dict(input=1000,output=100,cached_read=300,reasoning=40))
        self.assertEqual(result,'0.00093000')
    def test_unknown_actual_usage_keeps_unknown_and_reservation_upper_bound(self):
        key=self.book.reserve('p','t',0,'0.5',PRICE,{'currency':'CNY','project_amount':'1'})
        self.book.settle(key,None)
        row=self.book.rows('p')[0]
        self.assertEqual((row['state'],row['amount']),('unconfirmed','0.5'))
        self.assertIsNone(estimate(PRICE,usage={'input':None,'output':None}))
    def test_manual_bill_reconciliation_requires_explanation_and_project_scope(self):
        key=self.book.reserve('p','t',0,'0.5',PRICE,{'currency':'CNY','project_amount':'1'})
        self.book.settle(key,None)
        with self.assertRaises(BudgetError):
            self.book.reconcile(key,'0','',project_id='p')
        with self.assertRaises(BudgetError):
            self.book.reconcile(key,'0.3','隔离测试账单核对',project_id='other')
        self.assertEqual(self.book.rows('p')[0]['amount'],'0.5')
        self.book.reconcile(key,'0.3','隔离测试账单核对',project_id='p')
        row=self.book.rows('p')[0]
        self.assertEqual((row['state'],row['amount']),('user_reconciled','0.3'))
        self.assertIn('用户对照账单',json.loads(row['price_snapshot'])['reconciliation']['source'])
    def test_concurrent_reservations_do_not_each_pass_full_budget(self):
        def reserve(i):
            try:
                self.book.reserve('p','task'+str(i),0,'.6',PRICE,{'currency':'CNY','project_amount':'1'})
                return True
            except BudgetError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(reserve,[1,2]))
        self.assertEqual(results.count(True),1)
    def test_currency_not_automatically_converted(self):
        with self.assertRaises(BudgetError):
            self.book.reserve('p','t',0,'.1',PRICE,{'currency':'USD','project_amount':'1'})
    def test_unknown_price_cannot_claim_money_control(self):
        with self.assertRaises(BudgetError):
            self.book.reserve('p','t',0,None,{}, {'currency':'CNY','task_amount':'1'})
        self.assertIsNone(self.book.reserve('p','t',0,None,{},{}))
    def test_same_call_reservation_cannot_be_repeated(self):
        self.book.reserve('p','t',0,'.1',PRICE,{})
        with self.assertRaises(BudgetError):
            self.book.reserve('p','t',0,'.1',PRICE,{})
    def test_rejected_request_releases_only_local_reservation(self):
        key=self.book.reserve('p','t',0,'.7',PRICE,{'project_amount':'1'})
        self.book.settle(key,rejected=True)
        self.book.reserve('p','new',0,'.7',PRICE,{'project_amount':'1'})
        self.assertEqual(next(row for row in self.book.rows('p') if row['task_id']=='t')['state'],'released')
    def test_invalid_or_undeclared_price_schema_rejected(self):
        with self.assertRaises(BudgetError):
            validate_price(dict(PRICE,input_per_million='-1'))
        with self.assertRaises(BudgetError):
            validate_price(dict(PRICE,extra='untrusted'))
    def test_task_budget_blocks_provider_before_generation(self):
        workspace=Workspace(self.root/'data')
        project=workspace.create('金额阻止','小说')
        did=project.documents()[0]['id']
        connections=ConnectionStore(self.root/'settings')
        connections.save(Connection('c','测试连接','deepseek','fixture',base_url='https://example.invalid',pricing=PRICE),'fixture-only-key')
        project.set_setting('budget_settings',dict(monetary_limits=dict(currency='CNY',task_amount='.00000001')))
        service=TaskService(project,ROOT/'resources',connections)
        snapshot=service.prepare(did,'只做中性测试',connections.get('c'),'discussion',0,0,development_test=True)
        provider=Provider()
        result=service.execute(snapshot,CancelToken(),provider=provider)
        self.assertEqual(result['status'],'budget_paused')
        self.assertEqual(provider.calls,0)
        self.assertEqual(result['used_calls'],0)

class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='TT 自动备份 ')
        self.root=Path(self.temp.name)
        self.workspace=Workspace(self.root/'data')
        self.store=self.workspace.create('备份项目','小说')
        self.did=self.store.documents()[0]['id']
        doc=self.store.document(self.did)
        self.store.save_document(self.did,doc['head'],'PRIVATE_MANUSCRIPT不能进诊断')
    def tearDown(self):
        self.temp.cleanup()
    def test_auto_backup_retains_manual_and_only_rotates_auto_files(self):
        manual=self.store.root/'backups'/'manual.ttbackup'
        self.workspace.backup(self.store,manual)
        for _ in range(3):
            path=automatic_backup(self.workspace,self.store,2)
        self.assertEqual(len(list((self.store.root/'backups').glob('auto_*.ttbackup'))),2)
        self.assertTrue(manual.is_file())
        restored=self.workspace.restore(path)
        self.assertEqual(restored.document(self.did)['text'],'PRIVATE_MANUSCRIPT不能进诊断')
    def test_diagnostics_excludes_keys_manuscript_prompt_and_signed_urls(self):
        connections=ConnectionStore(self.root/'settings')
        connections.save(Connection('c','名称','deepseek','fixture',base_url='https://example.invalid'),'MY_PRIVATE_ACCOUNT_KEY')
        owner=SimpleNamespace(store=self.store,connections=connections,image_connections=ImageConnectionStore(self.root/'settings'),
            theme='雾白浅色',options={})
        data=json.dumps(diagnostics(owner),ensure_ascii=False)
        self.assertNotIn('MY_PRIVATE_ACCOUNT_KEY',data)
        self.assertNotIn('PRIVATE_MANUSCRIPT',data)
        self.assertNotIn('Authorization',data)
    def test_backup_rotation_count_invalid_does_not_touch_data(self):
        with self.assertRaises(ValueError):
            automatic_backup(self.workspace,self.store,0)
        self.assertEqual(self.store.document(self.did)['text'],'PRIVATE_MANUSCRIPT不能进诊断')

if __name__=='__main__':
    unittest.main()
