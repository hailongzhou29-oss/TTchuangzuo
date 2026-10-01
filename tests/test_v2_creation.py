import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from app.core.selection import Registry,selection,dialogue_budget
from app.core.work_context import CurrentWork,locate,intent
from app.core.creation_flow import CreationFlow,parse_output,dialogues,script_body,sync_dialogues
from app.core.services import Workspace
from app.core.project_tools import ProjectTools
from app.providers.contracts import Connection,TextResult,CancelToken
from app.storage.project import ConflictError,LockedError,ProjectStore

RESOURCES=Path(__file__).resolve().parents[1]/'resources'
SCRIPT=dict(title='最后一分钟',outline='维修员发现时钟异常，在停电前决定救人。',scenes=[dict(title='机房·夜',nodes=[dict(type='action',speaker='',text='林远按住闪烁的开关。'),dict(type='dialogue',speaker='林远',text='还剩一分钟。')]),dict(title='门外·夜',nodes=[dict(type='action',speaker='',text='阿宁将备用电池推过门缝。'),dict(type='dialogue',speaker='阿宁',text='别等我，先接上！')])])
NOVEL=dict(title='旧站',synopsis='两个人为一封旧信重返车站。',plan=['第1章：收到信','第2章：重回车站','第3章：线索兑现'],characters='阿宁：修理员。林远：值班员。',chapter_title='第1章 旧信',text='阿宁打开旧信，雨声像石子敲打窗沿。她没有回头，径直走进值班室。')

class Connections:
    def __init__(self,root,c): self.path=root/'connections.json'; self.c=c
    def get(self,cid): return self.c
    def secret_snapshot(self,c): return 'fixture-secret'

class Provider:
    def __init__(self,value): self.value=value; self.calls=0; self.messages=[]
    def generate(self,c,secret,messages,cancel,on_text,**options):
        self.calls+=1; self.messages=messages
        text=json.dumps(self.value,ensure_ascii=False) if isinstance(self.value,dict) else self.value
        on_text(text); return TextResult(text=text,status='completed',model=c.model,accepted=True)

class V2CreationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.workspace=Workspace(self.root/'data'); self.store=self.workspace.create('未命名剧本','剧本'); self.did=self.store.documents()[0]['id']; self.store.set_setting('v2_document:'+self.did,True)
        self.config=selection('script'); self.work=CurrentWork.load(self.store,self.did,self.config)
        self.connection=Connection('fixture','隔离单元测试','custom','fixture',base_url='https://fixture.invalid',max_output=8192,context_limit=65536)
        self.connections=Connections(self.root,self.connection)
    def tearDown(self): self.tmp.cleanup()
    def run_task(self,task,value,instruction='',selected=(0,0)):
        flow=CreationFlow(self.work,RESOURCES,self.connections); snapshot=flow.prepare(self.connection,task,instruction,selected,True); provider=Provider(value); result=flow.service.execute(snapshot,CancelToken(),provider=provider); self.assertEqual(result['status'],'completed',result.get('error')); flow.apply(snapshot,result); return flow,snapshot,result
    def test_catalogue_bodies_and_inherited_selection(self):
        registry=Registry(RESOURCES)
        self.assertEqual([len(registry.of(k)) for k in ('genre','subgenre','formula')],[24,144,30])
        c=selection('script'); c.update(genre='G07',subgenres=['G07.3']); c['advanced']={'结构公式':'F02','情绪标签':[registry.of('emotion')[0]['id']]}
        rules=registry.effective(c); ids=[r['id'] for r in rules]
        self.assertIn('G07',ids); self.assertIn('G07.3',ids); self.assertNotIn('G01',ids)
        self.assertTrue(all(r['body'].strip() for r in rules))
    def test_invalid_rule_does_not_silently_disappear(self):
        self.config['subgenres']=['G99.1']
        with self.assertRaises(ValueError): Registry(RESOURCES).effective(self.config)
    def test_empty_idea_generates_three_parts_directly(self):
        _,snapshot,_=self.run_task('generate',SCRIPT)
        self.assertEqual(self.store.document(self.did)['text'],self.work.text)
        self.assertEqual(self.work.text.count('第三部分｜完整人物台词'),1)
        body=dialogues(script_body(self.work.text)); third=dialogues(self.work.text.split('第三部分｜完整人物台词')[1]); self.assertEqual(body,third)
        self.assertEqual(snapshot['constraints']['idea'],'')
        self.assertEqual(self.store.metadata()['name'],SCRIPT['title'])
    def test_second_scene_patch_preserves_everything_else_and_syncs_lines(self):
        self.run_task('generate',SCRIPT); before=self.work.text; start,end=locate(before,'把第二场冲突加强'); patch=before[start:end].replace('推过','猛地踢过')
        self.run_task('modify',dict(text=patch,explanation='加强第二场动作'),'只改第二场，保留台词',(start,end))
        self.assertEqual(self.work.text[:start],before[:start]); self.assertEqual(dialogues(script_body(before)),dialogues(script_body(self.work.text)))
        reopened=ProjectStore(self.store.root); reopened.check(); self.assertEqual(reopened.document(self.did)['text'],self.work.text)
    def test_explicit_check_never_writes(self):
        self.run_task('generate',SCRIPT); head=self.work.revision; self.run_task('inspect','第二场阿宁通过门缝递上电池。','第二场讲了什么')
        self.assertEqual(self.work.revision,head)
    def test_latest_unsaved_buffer_is_frozen(self):
        self.work.edit('未保存的新设定'); flow=CreationFlow(self.work,RESOURCES,self.connections); s=flow.prepare(self.connection,'inspect','检查不要修改')
        self.assertIn('未保存的新设定',s['messages'][1]['content'])
    def test_generation_cannot_overwrite_concurrent_manual_edit(self):
        flow=CreationFlow(self.work,RESOURCES,self.connections); s=flow.prepare(self.connection,'generate'); r=flow.service.execute(s,CancelToken(),provider=Provider(SCRIPT)); self.work.edit('用户刚输入的新字')
        with self.assertRaises(ConflictError): flow.apply(s,r)
        self.assertEqual(self.work.text,'用户刚输入的新字')
    def test_local_patch_can_merge_nonoverlapping_user_edit(self):
        self.work.edit('甲\n要改的一句\n乙'); self.work.save(); frozen=self.work.freeze(); self.work.edit('新增开头\n甲\n要改的一句\n乙'); self.work.save(); self.work.apply(frozen,'改好的一句',2,7)
        self.assertTrue(self.work.text.startswith('新增开头'))
    def test_lock_and_dialogue_preservation(self):
        self.run_task('generate',SCRIPT); self.store.lock(self.did,'还剩一分钟。',self.work.text.index('还剩一分钟。')); frozen=self.work.freeze()
        with self.assertRaises(LockedError): self.work.apply(frozen,self.work.text.replace('还剩一分钟。','还剩十分钟。'))
    def test_double_submit_is_blocked(self):
        flow=CreationFlow(self.work,RESOURCES,self.connections); flow.prepare(self.connection,'generate')
        with self.assertRaises(ValueError): flow.prepare(self.connection,'generate')
    def test_cancelled_task_is_not_adopted(self):
        flow=CreationFlow(self.work,RESOURCES,self.connections); s=flow.prepare(self.connection,'generate'); cancel=CancelToken(); cancel.cancel(); r=flow.service.execute(s,cancel,provider=Provider(SCRIPT)); self.assertEqual(r['status'],'cancelled'); self.assertIsNone(flow.apply(s,r)); self.assertEqual(self.work.text,'')
    def test_commerce_only_name_has_fact_boundary(self):
        self.config.update(mode='剧情带货',object='保温杯',genre='G13'); _,snapshot,_=self.run_task('generate',SCRIPT)
        system=snapshot['messages'][0]['content']; self.assertIn('未知',system); self.assertIn('保温杯',snapshot['messages'][1]['content']); self.assertIn('B',','.join(r['rule_id'] for r in snapshot['rule_snapshot']))
    def test_rewrite_novel_uses_novel_output(self):
        self.config.update(selection('rewrite')); self.config.update(output='novel',reference='用户拥有的参考原文'); self.run_task('generate',NOVEL)
        self.assertNotIn('第三部分',self.work.text); self.assertIn('阿宁打开旧信',self.work.text)
    def test_real_conflict_is_rejected_but_emotions_can_mix(self):
        self.config['advanced']={'反转':['无反转','身份揭示']}
        with self.assertRaises(ValueError): Registry(RESOURCES).effective(self.config)
        self.config['advanced']={'情绪标签':[r['id'] for r in Registry(RESOURCES).of('emotion')[:2]]}; Registry(RESOURCES).effective(self.config)
    def test_duration_budget_reserves_action(self):
        self.config.update(duration=180,dialogue_ratio=.7,speech_speed=5); self.assertEqual(dialogue_budget(self.config),630)
        out=parse_output(json.dumps(SCRIPT,ensure_ascii=False),'generate',self.config); self.assertLess(out['estimated_duration'],180)
    def test_pagination_reads_after_thirty_blocks(self):
        self.work.edit('\n'.join('段落'+str(i) for i in range(70))); self.work.save(); flow=CreationFlow(self.work,RESOURCES,self.connections); s=flow.prepare(self.connection,'inspect','检查'); tools=ProjectTools(self.store,RESOURCES,s)
        first=tools.read_document(self.did); second=tools.read_document(self.did,first['next_cursor']); third=tools.read_document(self.did,second['next_cursor'])
        self.assertTrue(first['has_more']); self.assertEqual(third['blocks'][-1]['text'],'段落69'); self.assertFalse(third['has_more'])
    def test_old_memory_is_invalidated_and_later_chapter_marked(self):
        second=self.store.add_document('第二章',kind='小说'); self.store.set_setting('v2_memories',{self.did:dict(revision=self.work.revision,text='旧设定')}); self.work.edit('新设定'); self.work.save(); self.assertNotIn(self.did,self.store.setting('v2_memories')); self.assertTrue(self.store.setting('v2_stale:'+second))
    def test_new_chapter_reads_current_predecessor(self):
        self.config.update(selection('novel')); self.run_task('generate',NOVEL); self.work.edit(self.work.text+'\n主角改名为小雨。'); self.work.save(); second=self.store.add_document('第二章',kind='小说'); work=CurrentWork.load(self.store,second,self.config); flow=CreationFlow(work,RESOURCES,self.connections); snapshot=flow.prepare(self.connection,'next','续写下一章'); context=json.loads(snapshot['messages'][1]['content'].split('\n',1)[1]); self.assertIn('小雨',context['previous_chapters'][0]['text'])
    def test_vague_target_does_not_become_full_rewrite(self):
        with self.assertRaises(ValueError): locate('甲\n乙','改一下那段')
    def test_instruction_routes(self):
        self.assertEqual(intent('检查不要修改'),'inspect'); self.assertEqual(intent('只改动作，保留台词'),'modify'); self.assertEqual(intent('续写下一章'),'next')
        self.assertEqual(intent('保留情节和所有台词，只改第二场动作，让第二场冲突更强。不要修改其他场。'),'modify')
    def test_planning_modifies_plan_only(self):
        self.run_task('generate',SCRIPT); original=self.work.text
        self.run_task('planning',dict(synopsis='新的冲突说明',chapters=['第一场发现危机','第二场付出代价'],characters='林远与阿宁'),'调整故事规划')
        self.assertEqual(self.work.text,original); self.assertEqual(self.store.setting('v2_plan')['synopsis'],'新的冲突说明')
        self.assertEqual(intent('调整故事规划'),'planning')
    def test_segment_snapshot_retains_total_target_and_bounded_part(self):
        self.config['duration']=1200; flow=CreationFlow(self.work,RESOURCES,self.connections)
        snapshot=flow.prepare(self.connection,'generate',segment=dict(index=0,count=4,words=0,duration=300))
        self.assertEqual(snapshot['constraints']['duration'],1200); self.assertIn('第1/4段',snapshot['messages'][0]['content']); self.assertIn('本段对白预算',snapshot['messages'][0]['content'])
    def test_migration_copies_current_work_and_retains_original(self):
        self.run_task('generate',SCRIPT); destination=Workspace(self.root/'moved'); mapping=self.workspace.migrate_to(destination)
        import os
        new_root=mapping[os.path.normcase(str(self.store.root.resolve()))]; migrated=destination.open(new_root)
        self.assertEqual(migrated.metadata()['id'],self.store.metadata()['id']); self.assertEqual(migrated.document(self.did)['text'],self.work.text); self.assertTrue(self.store.path.exists())
    def test_dialogue_sync_keeps_narration_and_excludes_colon_scene_headers(self):
        text='第二部分｜完整剧本\n第1场 车站：夜\n[动作] 看见时钟：八点整。\n[VO]：旧信终于到了。\n阿宁：我来晚了。\n第三部分｜完整人物台词\n旧内容'
        synced=sync_dialogues(text)
        self.assertEqual(dialogues(script_body(synced)),[('[VO]','旧信终于到了。'),('阿宁','我来晚了。')])
        self.assertEqual(dialogues(synced.split('第三部分｜完整人物台词')[1]),dialogues(script_body(synced)))

if __name__=='__main__': unittest.main()
