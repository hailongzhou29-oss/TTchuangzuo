import copy
import json
import tempfile
import unittest
from pathlib import Path
from app.core.script_settings import CATALOG,DETAILS,defaults,migrate,active_settings,adapt,validate_script,rules,budget
from app.core.selection import selection,Registry
from app.core.creation_flow import CreationFlow,parse_output
from app.core.speech_records import verify,sync,extract
from app.core.work_context import CurrentWork,intent
from app.core.services import Workspace
from app.providers.contracts import Connection,CancelToken,TextResult
from app.storage.project import ConflictError

ROOT=Path(__file__).resolve().parents[1]

class Connections:
    def __init__(self,root,connection): self.path=root/'connections.json'; self.connection=connection
    def get(self,cid): return self.connection
    def secret_snapshot(self,c): return ''

class Provider:
    def __init__(self,value): self.value=value
    def generate(self,c,secret,messages,cancel,on_text,**options):
        raw=json.dumps(self.value,ensure_ascii=False); on_text(raw)
        return TextResult(text=raw,status='completed',model=c.model,accepted=True)

def config(**values):
    c=migrate(selection('script'),new=True); c['script_settings']['values'].update(values)
    return adapt(c)

def output(nodes):
    return dict(title='模拟作品',outline='人物用选择应对阻力。',scenes=[dict(title='屋内·夜',nodes=nodes)],adopted=dict(genre='悬疑',anchor='阿宁',characters='阿宁',emotion_order='紧张→释然'))

class UnifiedScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='tt_unified_unit_'); self.root=Path(self.tmp.name)
        self.store=Workspace(self.root/'data').create('隔离测试','剧本'); self.did=self.store.documents()[0]['id']
        self.work=CurrentWork.load(self.store,self.did,config())
        self.connection=Connection('mock','本地模拟','custom','fixture',base_url='https://fixture.invalid',max_output=4096,context_limit=65536)
        self.connections=Connections(self.root,self.connection)
    def tearDown(self): self.tmp.cleanup()
    def flow(self): return CreationFlow(self.work,ROOT/'resources',self.connections)
    def test_catalogue_counts_and_exact_narrative_ids(self):
        self.assertEqual([len(CATALOG[k]['rows']) for k in ['genre','subgenres','formula','emotion']],[24,144,30,24])
        self.assertEqual(sum(len(CATALOG[k]['rows']) for k in ['time','info','thread','suspense','reversal','rhetoric']),41)
        self.assertEqual(list(DETAILS),['故事','人物','情绪','台词','风格','参考'])
        for key,g in CATALOG.items():
            for r in g['rows']:
                self.assertTrue(r['body'].strip(),r['id']); self.assertEqual(r['applicable'],'script'); self.assertTrue(r['version'])
    def test_every_selectable_id_enters_real_request(self):
        for key,g in CATALOG.items():
            for row in g['rows']:
                with self.subTest(key=key,id=row['id']):
                    c=config(); v=c['script_settings']['values']; v[key]=[row['id']] if g['multi'] else row['id']
                    if key=='subgenres': v['genre']=row['parent']
                    if key in ('role','role_detail'): v['view']='view.subjective'; v['role']=row['parent'] if key=='role_detail' else row['id']
                    if key=='carrier_item': v['carrier']=row['parent']
                    if key=='mixed_sources': v['carrier']='carrier.09'
                    if key in ('sources','delivery'): v['language']='language.09'; v.setdefault('sources',['sources.01'])
                    if key in ('strategy','cta'): v['mode']='mode.02'; c['object']='虚构产品类别'
                    if key=='mode' and row['id']!='mode.01': c['object']='虚构对象类别'
                    self.work.config=adapt(c); flow=self.flow(); snapshot=flow.prepare(self.connection,'generate',development_test=True)
                    system=snapshot['messages'][0]['content']
                    if row['id']=='view.auto': self.assertNotIn('script.view.auto',[r['id'] for r in snapshot['rule_snapshot']])
                    else:
                        self.assertIn(row['body'],system)
                        self.assertIn('script.'+row['id'],[r['id'] for r in snapshot['rule_snapshot']])
                    with self.store.connection(write=True) as con: con.execute("UPDATE tasks SET state='cancelled' WHERE id=?",(snapshot['task_id'],))
    def test_inactive_state_and_migration_original_excluded_from_request(self):
        c=config(genre='G04',subgenres=['G04.1','G11.1']); c['script_settings']['drafts']={'subgenres':{'G11':['G11.1']}}; c['script_settings']['migration_original']={'secret_text':'历史但不生效'}
        self.work.config=c; s=self.flow().prepare(self.connection,'inspect','不要续写，只检查',development_test=True)
        serialized=json.dumps(s['messages'],ensure_ascii=False)
        self.assertNotIn('历史但不生效',serialized); self.assertNotIn('G11.1',serialized)
        self.assertEqual(s['effective_settings']['values']['subgenres'],['G04.1'])
        self.assertEqual(s['request_id'],s['task_id']); self.assertEqual(s['rule_version'],'2026-10-01')
    def test_silent_excludes_hidden_language_budgets(self):
        self.work.config=config(language='language.08',density='density.03',speed='speed.01',word_range='900-1000',segment_range='4-10',narration_ratio='50',sources=['sources.02'])
        s=self.flow().prepare(self.connection,'generate',development_test=True)
        a=s['effective_settings']['values']; self.assertEqual(a['sources'],[])
        for key in ['density','speed','word_range','segment_range','narration_ratio']: self.assertNotIn(key,a)
        self.assertNotIn('speech_speed',s['constraints']); self.assertNotIn('dialogue_ratio',s['constraints'])
    def test_all_language_modes_and_source_limits(self):
        from app.core.script_settings import LANGUAGE_SOURCES
        source_types={'sources.01':'dialogue','sources.02':'narration','sources.03':'inner'}
        for mode,sources in LANGUAGE_SOURCES.items():
            c=config(language=mode); nodes=[dict(type='action',speaker='',text='她推开门。')]+[dict(type=source_types[src],speaker='阿宁' if src!='sources.02' else '旁白',text='门后有人。',delivery='画外') for src in sources]
            value=parse_output(json.dumps(output(nodes),ensure_ascii=False),'generate',c)
            self.assertEqual(len(value['speech_records']),len(sources)); verify(value['text'],value['speech_records'])
            if not sources: self.assertIn('本作品无发声台词',value['text'])
        with self.assertRaisesRegex(ValueError,'不允许'):
            parse_output(json.dumps(output([dict(type='narration',speaker='旁白',text='后来她知道了。')]),ensure_ascii=False),'generate',config(language='language.01'))
    def test_viewpoint_boyfriend_combinations_have_different_rules(self):
        subjective=config(view='view.subjective',role='role.01',role_detail='role_detail.01',role_name='男友')
        addressed=config(view='view.address',viewer_role='男友',address_role='女友')
        a='\n'.join(r['body'] for r in rules(subjective)); b='\n'.join(r['body'] for r in rules(addressed))
        self.assertIn('感官位置',a); self.assertIn('不把交流角色眼睛当镜头',b); self.assertNotEqual(a,b)
    def test_real_conflicts_and_permitted_combinations(self):
        for c in [config(reversal=['reversal.none','reversal.identity']),config(formula='F03',reversal=['reversal.none']),config(formula='F16',thread=['thread.single']),config(language='language.08',required_lines='必须说这句')]:
            with self.assertRaises(ValueError): validate_script(c)
        validate_script(config(formula='F03',reversal=['reversal.optional'],emotion=['emotion.02','emotion.01'],tone='tone.01',genre='G07'))
    def test_hard_budget_and_soft_density(self):
        c=config(density='density.03',speed='speed.01'); b=budget(c); self.assertEqual(b['speed'],3)
        c['duration']=30; c['script_settings']['values']['word_range']='100-200'
        with self.assertRaisesRegex(ValueError,'最低发声'): validate_script(c)
        c['duration']=180; c['script_settings']['values']['density']='density.01'; c['script_settings']['values']['word_range']='400-500'
        self.assertTrue(validate_script(c)); self.assertEqual(budget(c)['speed'],3)
    def test_migration_preserves_original_ambiguous_values_and_density_intent(self):
        old=selection('script'); old.update(format='电影片段',density='台词主导',genre='G04',subgenres=['G04.1']); old['advanced']={'叙事顺序':'倒叙','反转':['身份翻面'],'旁白':'少量旁白','台词风格':['口语']}
        c=migrate(old,legacy_registry=Registry(ROOT/'resources')); s=c['script_settings']; self.assertEqual(s['migration_original'],old)
        self.assertEqual(s['values']['form'],'form.04'); self.assertEqual(s['values']['time'],['time.reverse']); self.assertTrue(s['unresolved']); self.assertTrue(s['migration_notes']); self.assertNotIn('language',s['values'])
        self.assertEqual(migrate(c),c)
    def test_speech_records_survive_sync_and_detect_corrupt_third_part(self):
        value=parse_output(json.dumps(output([dict(type='dialogue',speaker='阿宁',text='第一行。\n第二行。',delivery='电话'),dict(type='inner',speaker='阿宁',text='不能告诉他。'),dict(type='narration',speaker='旁白',text='十年前。')]),ensure_ascii=False),'generate',config())
        synced,records=sync(value['text'],value['speech_records']); self.assertEqual(synced,value['text']); self.assertEqual([r['id'] for r in records],[r['id'] for r in value['speech_records']]); verify(synced,records)
        with self.assertRaises(ValueError): verify(synced+'重复台词',records)
        silent='第二部分｜完整剧本\n[动作] 推门。\n第三部分｜完整人物台词\n旧台词'; self.assertIn('本作品无发声台词',sync(silent)[0])
    def test_stale_same_document_response_is_durable_candidate(self):
        flow=self.flow(); s=flow.prepare(self.connection,'generate',development_test=True); value=output([dict(type='dialogue',speaker='阿宁',text='我来开门。')]); r=flow.service.execute(s,CancelToken(),provider=Provider(value))
        self.assertEqual(r['status'],'completed',r.get('error')); self.work.edit('用户的新正文'); self.work.save()
        with self.assertRaises(ConflictError): flow.apply(s,r)
        self.assertEqual(self.work.text,'用户的新正文'); candidates=self.store.setting('v2_candidates'); self.assertEqual(candidates[0]['base_revision'],s['base_revision']); self.assertTrue(candidates[0]['complete'])
    def test_manual_edit_and_revert_still_rejects_late_result(self):
        flow=self.flow(); s=flow.prepare(self.connection,'generate',development_test=True); value=output([dict(type='dialogue',speaker='阿宁',text='我来开门。')]); r=flow.service.execute(s,CancelToken(),provider=Provider(value))
        self.work.edit('临时编辑'); self.work.edit('')
        with self.assertRaises(ConflictError): flow.apply(s,r)
    def test_unsaved_latest_discussion_and_check_do_not_write(self):
        self.assertEqual(intent('不要续写，只检查'),'inspect')
        self.work.edit('最新但未点保存的正文'); flow=self.flow(); s=flow.prepare(self.connection,'discuss','聊聊动机',development_test=True)
        self.assertIn('最新但未点保存',s['messages'][1]['content']); self.assertIsNone(s['schema']); self.assertIn('不强制三段格式',s['messages'][0]['content'])
    def test_adopted_values_stay_out_of_user_selection(self):
        flow=self.flow(); before=copy.deepcopy(self.work.config['script_settings']); s=flow.prepare(self.connection,'generate',development_test=True); r=flow.service.execute(s,CancelToken(),provider=Provider(output([dict(type='dialogue',speaker='阿宁',text='我来开门。')]))); flow.apply(s,r)
        self.assertEqual(self.work.config['script_settings'],before); self.assertEqual(self.store.setting('v2_adopted:'+self.did)['values']['genre'],'悬疑'); verify(self.work.text,self.store.setting('v2_speech:'+self.did)['records'])

if __name__=='__main__': unittest.main()
