import json,os,tempfile,unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import test_agent_workflow as fixtures
from app.core.test_isolation import guard_test_write,legacy_test_profile
from app.core.files import write_json
from app.storage.connections import ConnectionStore
from app.providers.contracts import Connection,CancelToken,TextResult
from app.core.writing_progress import metrics,book_progress,require_reconciled,record_completion
from app.core.output_budget import output_plan
from app.core.agent_candidates import AgentCandidates

class IsolationTests(unittest.TestCase):
    def test_production_writes_and_credential_clear_block_before_mutation(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);production=root/'AppData'/'TTChuangzuo';production.mkdir(parents=True);path=production/'connections.json';path.write_text('{"schema_version":1,"connections":[]}',encoding='utf-8');before=path.read_bytes()
            with patch.dict(os.environ,dict(LOCALAPPDATA=str(root/'AppData'),TT_CREATOR_TEST_MODE='1',TT_CREATOR_TEST_ROOT=str(root/'test'))):
                store=ConnectionStore(production)
                with self.assertRaises(PermissionError):store.save(Connection('test','fixture','deepseek','model',base_url='https://example.org'))
                with self.assertRaises(PermissionError):store.vault.clear()
                with self.assertRaises(PermissionError):write_json(production/'preferences.json',{})
                with self.assertRaises(PermissionError):guard_test_write(root/'other'/'budget.sqlite')
                self.assertEqual(path.read_bytes(),before)
                write_json(root/'test'/'allowed.json',dict(isolated=True))
    def test_legacy_profile_requires_exact_test_provenance_and_manual_mode(self):
        c=Connection('live_deepseek','DeepSeek 软件通道实测','deepseek','deepseek-flash',base_url='https://api.deepseek.com',max_output=128,timeout=60,reasoning_levels=('none',))
        self.assertTrue(legacy_test_profile(c))
        renamed=replace(c,name='DeepSeek',context_limit=32768,verification={'auth_models':{'checked':'2026-10-01T01:26:43.472494+00:00'},'text_generation':{'checked':'2026-10-01T01:26:50+00:00'}})
        self.assertTrue(legacy_test_profile(renamed));self.assertFalse(legacy_test_profile(replace(renamed,verification={})))
        for value in [replace(c,id='user'),replace(c,name='我的连接'),replace(c,output_mode='auto'),replace(c,timeout=90)]:self.assertFalse(legacy_test_profile(value))

class ReliabilityTests(unittest.TestCase):
    setUp=fixtures.AgentTests.setUp
    tearDown=fixtures.AgentTests.tearDown
    def test_completed_content_survives_summary_cancel_but_requires_explicit_adoption(self):
        token=CancelToken();before=self.work.text
        class Replay(fixtures.Provider):
            def generate(provider,*args,**kwargs):
                if provider.calls==0:return super(Replay,provider).generate(*args,**kwargs)
                provider.calls+=1;token.cancel();return TextResult(status='cancelled',accepted=True,error='summary stopped')
        snap=self.flow.prepare(self.c,'modify','修改选区，保留结尾',(0,3),True);snap['memory_policy']='semantic'
        result=self.flow.service.execute(snap,token,provider=Replay([dict(text='新开头',explanation='仅修改开头')]))
        self.assertEqual(result['status'],'completed');self.assertTrue(result['requires_adoption']);self.assertEqual(result['postprocessing']['summary_status'],'cancelled')
        notice=self.flow.apply(snap,result);self.assertIn('摘要未完成',notice);self.assertEqual(self.work.text,before)
        cid=AgentCandidates(self.store).pending()[0]['id'];self.work.edit(before+'手改')
        with self.assertRaises(Exception):AgentCandidates(self.store).adopt(cid,self.work)
    def test_summary_failure_keeps_completed_content_and_boundary_cancel_does_not(self):
        for boundary in [False,True]:
            token=CancelToken()
            class Replay(fixtures.Provider):
                def generate(provider,*args,**kwargs):
                    if boundary:token.cancel()
                    return super(Replay,provider).generate(*args,**kwargs)
            snap=self.flow.prepare(self.c,'modify','修改开头',(0,3),True);snap['memory_policy']='semantic'
            result=self.flow.service.execute(snap,token,provider=Replay([dict(text='新开头',explanation='开头'),TextResult(status='failed',accepted=True,error='summary failed')]))
            self.assertEqual(result['status'],'cancelled' if boundary else 'completed')
            if not boundary:self.assertTrue(result['requires_adoption']);self.assertEqual(result['postprocessing']['summary_status'],'failed')
    def test_character_and_chinese_goals_are_distinct_and_tolerance_is_explicit(self):
        text='中'*4384+'x'*647;config=dict(self.work.config,words=5000,length='短篇小说')
        a=metrics(text,config);b=metrics(text,dict(config,word_count_unit='chinese'))
        self.assertEqual((a['actual_chars'],a['chinese_chars'],a['minimum_chars']),(5031,4384,4500));self.assertEqual(a['state'],'target_met');self.assertEqual(b['state'],'target_not_met')
    def test_initial_save_records_saved_state_in_chat_instead_of_pending_candidate(self):
        self.work.edit('');self.work.save();snap=self.flow.prepare(self.c,'generate','创作完整故事',development_test=True)
        result=self.flow.service.execute(snap,CancelToken(),provider=fixtures.Provider([dict(title='新作',synopsis='梗概',plan=[],characters='人物',chapter_title='',text='完整正文。')]))
        notice=self.flow.apply(snap,result);self.assertIn('生成并保存',notice)
        with self.store.connection() as con:message=con.execute("SELECT content FROM messages WHERE task_id=? AND role='assistant'",(snap['task_id'],)).fetchone()['content']
        self.assertIn('生成并保存',message);self.assertNotIn('候选',message)
    def test_quality_reminders_preserve_user_constraints_and_are_not_story_specific(self):
        from app.core.quality_checks import requirements,review_notes,reminder
        snap=dict(constraints=dict(idea='次日上午结束，人物仅甲乙',advanced={'必须保留':'事件顺序'}),instruction='只改最后一句',locked_content=['结尾不变'],confirmed_facts=[dict(content='人物甲是医生')])
        req=requirements(snap);self.assertEqual(len(req),5);notes=review_notes(snap,'十二点零一分，他叫周叔广叔。');self.assertTrue(any(n['kind']=='timeline' for n in notes));self.assertTrue(any(n['kind']=='names' for n in notes));self.assertIn('核对',reminder(snap,'十二点零一分'))
    def test_cancelled_fragment_displays_received_body_without_exposing_tool_protocol(self):
        from app.core.agent_candidates import readonly_fragment_text
        body='正文保留，结果仍不能采用。'
        raw=json.dumps(dict(action='final',arguments='{}',text=json.dumps(dict(text=body,explanation='修改说明'),ensure_ascii=False)),ensure_ascii=False)
        self.assertEqual(readonly_fragment_text(raw),body)
        self.assertEqual(readonly_fragment_text('尚未完整的正文'), '尚未完整的正文')
        for value in ['{"action":',json.dumps(dict(action='read_document',arguments='{}',text='')), '<｜DSML｜function_calls>']:
            shown=readonly_fragment_text(value);self.assertNotIn('read_document',shown);self.assertNotIn('DSML',shown);self.assertIn('不能采用',shown)
    def test_normal_official_format_adapts_without_mutating_manual_json_flag(self):
        c=replace(self.c,base_url='https://api.deepseek.com',model='deepseek-flash',output_mode='auto',json_mode=False)
        self.connections.save(c);c=self.connections.get(c.id)
        snap=self.flow.prepare(c,'modify','修改已选内容',(0,3),True)
        self.assertTrue(snap['model_selection']['json_mode']);self.assertFalse(self.connections.get(c.id).json_mode)
        self.assertTrue(snap['context_coverage']['documents'])
    def test_generic_http_prefetch_keeps_cross_chapter_capability_without_tool_bridge(self):
        other=self.store.add_document('第二章 门锁','门锁只有母亲能打开。',kind='chapter')
        snap=self.flow.prepare(self.c,'modify','根据第二章门锁修改已选内容',(0,3),True)
        self.assertIn(other,[d['document_id'] for d in snap['context_coverage']['documents'] if d['complete']])
        result=self.flow.service.execute(snap,CancelToken(),provider=fixtures.Provider([dict(text='母亲开门。',explanation='依据当前第二章')]));self.assertEqual(result['status'],'completed')
    def test_5000_is_a_target_and_larger_totals_are_not_capped_at_5000(self):
        c=replace(self.c,base_url='https://api.deepseek.com',model='deepseek-flash',output_mode='auto')
        self.assertEqual(output_plan(c,dict(output='novel',words=5000))['effective_tokens'],8192)
        long=output_plan(c,dict(output='novel',length='长篇小说',words=1000000,chapters=400,chapter_words=2500));self.assertEqual(long['effective_tokens'],4096)
        expanded=output_plan(c,dict(output='novel'),task='modify',selected_chars=10,instruction='请扩写到约5000字');self.assertEqual(expanded['effective_tokens'],8192)
    def test_finished_short_body_has_explicit_unmet_goal_and_can_be_saved(self):
        config=dict(self.work.config,words=100,length='短篇小说')
        self.assertEqual(metrics('完整的小故事。',config)['state'],'target_not_met')
        self.work.config=config;record_completion(self.work)
        p=book_progress(self.store,config);self.assertEqual(p['state'],'in_progress');self.assertEqual(p['target_chars'],100)
    def test_unknown_external_submission_blocks_new_writing_but_keeps_old_state(self):
        snap=self.flow.prepare(self.c,'modify','修改',(0,3),True)
        with self.store.connection(write=True) as con:
            con.execute('CREATE TABLE agent_external_rounds(task_id TEXT,ordinal INTEGER,state TEXT,request_id TEXT,updated TEXT,response TEXT,request_hash TEXT,PRIMARY KEY(task_id,ordinal))')
            con.execute('INSERT INTO agent_external_rounds VALUES(?,?,?,?,?,?,?)',(snap['task_id'],0,'submitted','', '',None,'hash'))
            con.execute('UPDATE tasks SET state=? WHERE id=?',('uncertain',snap['task_id']))
        with self.assertRaisesRegex(ValueError,'结果待确认'):require_reconciled(self.store,self.did)
        with self.assertRaises(ValueError):self.flow.prepare(self.c,'modify','新要求',(0,3),True)
        self.assertEqual(self.flow.service.get(snap['task_id'])['state'],'uncertain')
    def test_script_candidate_preview_and_adoption_use_same_speech_source(self):
        self.work.config.update(output='script',duration=60,speech_speed=4.5,dialogue_ratio=.5)
        body='第一部分｜故事大纲与建议时长\n旧店来信\n\n第二部分｜完整剧本\n第1场 旧书店·夜\n林晚：我找到信了。\n\n第三部分｜完整人物台词\n林晚：我找到信了。'
        self.work.edit(body);self.work.save();start=body.index('林晚：');end=start+len('林晚：我找到信了。')
        snap=self.flow.prepare(self.c,'modify','修改这句',(start,end),True);result=self.flow.service.execute(snap,CancelToken(),provider=fixtures.Provider([dict(text='林晚：我终于读懂信了。',explanation='调整对白')]))
        service=AgentCandidates(self.store);cid=service.save(snap,result);preview=service.preview(cid)
        self.assertEqual(preview.count('林晚：我终于读懂信了。'),2)
        service.adopt(cid,self.work);self.assertEqual(self.work.text,preview)
    def test_only_unnamed_narration_gets_generic_narrator(self):
        from app.core.script_settings import migrate,adapt
        from app.core.speech_records import payload,verify
        config=adapt(migrate(dict(self.work.config,output='script',duration=60),new=True))
        raw=dict(title='旧信',outline='修书',scenes=[dict(title='书店',nodes=[dict(type='narration',speaker='',text='雨停了。',delivery='画外')])])
        value=payload(raw,config);self.assertEqual(value['speech_records'][0]['speaker'],'旁白');verify(value['text']);self.assertEqual(raw['scenes'][0]['nodes'][0]['speaker'],'')
        for kind in ['dialogue','inner']:
            raw['scenes'][0]['nodes'][0]['type']=kind
            with self.assertRaisesRegex(ValueError,'稳定说话者'):payload(raw,config)
    def test_completed_chapters_and_manual_edits_update_finite_plan(self):
        from app.core.writing_progress import chapter_status
        self.work.config.update(output='novel',length='长篇小说',words=300,chapters=3,chapter_words=100)
        self.work.edit('章'*100);self.work.save();record_completion(self.work)
        for title in ['第二章','第三章']:
            did=self.store.add_document(title,'章'*100,kind='chapter')
            doc=self.store.document(did);self.store.set_setting('v2_completion:'+did,dict(metrics(doc['text'],self.work.config),revision=doc['head']))
        self.assertEqual(book_progress(self.store,self.work.config)['state'],'plan_met')
        self.work.edit('短章');self.work.save();self.assertEqual(chapter_status(self.store,self.did,self.work.config)['state'],'target_not_met')
        self.assertEqual(book_progress(self.store,self.work.config)['saved_chapters'],3)
    def test_completion_counts_body_without_title_and_synopsis(self):
        from app.core.writing_progress import body_text
        self.work.config.update(output='novel',words=100,length='短篇小说')
        payload=dict(title='题目',synopsis='简介',text='正文'*50)
        self.store.set_setting('v2_payload:'+self.did,dict(payload=payload))
        self.work.edit('题目\n\n简介\n\n'+payload['text']);self.work.save()
        self.assertEqual(record_completion(self.work)['actual_chars'],100)
        modified='题目\n\n'+payload['text'];self.assertEqual(body_text(self.store,self.did,modified,self.work.config),payload['text'])

if __name__=='__main__':unittest.main()
