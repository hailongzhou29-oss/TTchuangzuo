import unittest
import test_agent_workflow as fixtures
from app.core.explicit_constraints import length_range,timeline_constraint,timeline_review
from app.core.writing_progress import metrics,goal_status,record_completion,chapter_status
from app.core.agent_candidates import AgentCandidates
from app.providers.contracts import CancelToken
from app.storage.project import ConflictError,LockedError

class ConstraintRulesTests(unittest.TestCase):
    def test_explicit_range_is_separate_from_ninety_percent_and_tokens(self):
        limit=length_range({},'修改已选完整短篇到约5200非空白字符，正文目标4800到5500，不把标题、简介、空白、JSON算正文。')
        config=dict(words=5000,length='短篇小说',_length_range=limit)
        value=metrics('中'*3982+'，'*666,config)
        self.assertEqual((value['actual_chars'],value['chinese_chars'],value['range_gap'],value['target_gap']),(4648,3982,152,352))
        self.assertTrue(value['minimum_threshold_met']);self.assertEqual(value['state'],'target_not_met')
        self.assertIn('最低阈值已达',goal_status(value));self.assertIn('范围4,800—5,500非空白字符未达',goal_status(value))
        self.assertEqual(length_range({},'修改全文（正文字符目标4800—5500，不把标题算入）。')['min'],4800)
    def test_priority_and_no_arbitrary_story_number_or_quoted_policy(self):
        facts=[dict(state='confirmed',content='正文目标4800到5500非空白字符。')]
        explicit=dict(min=100,max=200,unit='chinese')
        self.assertEqual(length_range(dict(length_range=explicit),'正文目标300到400',facts)['min'],100)
        self.assertEqual(length_range({},'正文目标300到400',facts)['min'],4800)
        for text in ['身高160至180厘米。写5000字','创意：他有4800到5500枚硬币','原文：她说“正文目标4800到5500”','全部字数可能有很多数字']:
            self.assertIsNone(length_range(dict(idea=text),text))
        self.assertIsNone(length_range({},'', [dict(state='candidate',content=facts[0]['content'])]))
    def test_upper_bound_and_explicit_units_are_not_fudged(self):
        config=dict(words=5000,length='短篇小说',length_range=dict(min=4800,max=5500,unit='nonwhitespace'))
        value=metrics('字'*5600,config);self.assertEqual((value['state'],value['range_state'],value['range_gap']),('target_not_met','above_range',100))
        config['length_range']['unit']='chinese';value=metrics('字'*4384+'x'*647,config)
        self.assertEqual((value['actual_chars'],value['chinese_chars'],value['range_gap']),(5031,4384,416));self.assertEqual(value['state'],'target_not_met')
        config['length_range']['scope']='whole_book';self.assertIsNone(length_range(config))
    def test_invalid_structured_limit_is_not_silently_guessed(self):
        for limit in [dict(min=5500,max=4800),dict(min=True,max=5000),dict(min=10,max=20,unit='tokens')]:
            with self.assertRaises(ValueError):length_range(dict(length_range=limit))
    def test_confirmed_same_day_order_checks_the_composed_boundary(self):
        before='2026年10月3日，十一点五十五分，他下楼。\n\n十二点整，钟响。\n\n结尾保留。';start=before.index('十二点整');end=start+len('十二点整')
        snapshot=dict(constraints=dict(timeline_constraint=dict(order='chronological',date='2026-10-03',end='11:59')),target_start=start,target_end=end,frozen=dict(text=before))
        proposed=before[:start]+'十一点整'+before[end:];notes=timeline_review(snapshot,proposed)
        self.assertTrue(any(n['level']=='conflict' and '范围外相邻' in n['message'] for n in notes))
        self.assertEqual((proposed[:start],proposed[start+4:]),(before[:start],before[end:]))
    def test_unconfirmed_order_flashbacks_quotes_and_cross_day_do_not_get_rejected(self):
        text='2026年10月3日，十一点五十五分，他下楼。\n十一点整，钟响。'
        self.assertTrue(timeline_review(dict(constraints={}),text));self.assertFalse(any(n['level']=='conflict' for n in timeline_review(dict(constraints={}),text)))
        rule=dict(timeline_constraint=dict(order='chronological',date='2026-10-03',end='11:59'))
        for text in ['2026年10月3日，十一点五十五分，他下楼。\n她回忆起往事。\n十一点整，旧事在记忆里重现。','2026年10月3日，十一点五十五分，他下楼。\n“十一点整，”她念旧日的信。']:
            self.assertFalse(any(n['kind']=='time_order' and n['level']=='conflict' for n in timeline_review(dict(constraints=rule),text)))
        notes=timeline_review(dict(constraints={}), '2026年10月3日，二十三点，他睡下。\n2026年10月4日，六点，他醒来。')
        self.assertFalse(any(n['kind']=='time_order' for n in notes))
    def test_clock_range_and_unconfirmed_fact_state(self):
        fact=dict(state='confirmed',content='本章时间范围：2026年10月3日上午，顺叙。')
        rule=timeline_constraint({},'', [fact]);self.assertEqual(rule['end'],719)
        self.assertIsNone(timeline_constraint({},'', [dict(fact,state='disputed')]))
        notes=timeline_review(dict(constraints=dict(_timeline_constraint=rule)),'2026年10月3日，十二点零一分，他离开。')
        self.assertTrue(any(n['kind']=='time_range' and n['level']=='conflict' for n in notes))

class AdoptionConstraintTests(unittest.TestCase):
    setUp=fixtures.AgentTests.setUp
    tearDown=fixtures.AgentTests.tearDown
    def setup_time(self):
        self.work.config.update(length='短篇小说',words=1000)
        before='2026年10月3日，十一点五十五分，他下楼。\n\n十二点整，钟响。\n\n结尾保留。';self.work.edit(before);self.work.save()
        self.store.lock(self.did,'十一点五十五分',before.index('十一点五十五分'))
        entity=self.flow.service.facts.add_entity('本章时间限制','other');fact=self.flow.service.facts.propose(entity,'本章时间范围：2026年10月3日上午，顺叙。');self.flow.service.facts.set_state(fact,'confirmed')
        return before
    def candidate(self,text,span):
        snap=self.flow.prepare(self.c,'modify','只改已选时间，保留范围外原文',span,True)
        result=self.flow.service.execute(snap,CancelToken(),provider=fixtures.Provider([dict(text=text,explanation='时间修改')]))
        self.assertEqual(result['status'],'completed');return self.candidates.save(snap,result),snap,result
    def test_confirmed_time_fact_blocks_invalid_candidate_atomically_without_unlocking(self):
        before=self.setup_time();start=before.index('十二点整');cid,snapshot,result=self.candidate('十一点整',(start,start+4));head=self.work.revision
        self.assertEqual(snapshot['constraints']['_timeline_constraint']['end'],719)
        review=self.candidates.review(cid);self.assertTrue(review['conflicts'])
        with self.assertRaisesRegex(ConflictError,'扩大修改范围'):self.candidates.adopt(cid,self.work)
        self.assertEqual(self.work.text,before);self.assertEqual(self.work.revision,head);self.assertEqual(self.candidates.row(cid)['state'],'pending');self.assertEqual(self.store.locks(self.did)[0]['text'],'十一点五十五分')
        with self.assertRaises(ConflictError):self.flow.apply(snapshot,result)
        self.assertEqual(self.store.document(self.did)['text'],before)
    def test_time_adjustment_can_fit_scope_without_changing_locked_outside_text(self):
        before=self.setup_time();start=before.index('十二点整');cid,_,_=self.candidate('十一点五十六分',(start,start+4))
        self.assertFalse(self.candidates.review(cid)['conflicts']);self.candidates.adopt(cid,self.work)
        self.assertEqual(self.work.text[:start],before[:start]);self.assertEqual(self.work.text[start+len('十一点五十六分'):],before[start+4:]);self.assertEqual(self.store.locks(self.did)[0]['text'],'十一点五十五分')
        self.candidates.undo(cid,self.work);self.assertEqual(self.work.text,before)
    def test_expanding_scope_does_not_bypass_an_explicit_text_lock(self):
        before=self.setup_time();cid,_,_=self.candidate(before.replace('十一点五十五分','十点五十五分').replace('十二点整','十一点整'),(0,len(before)));head=self.work.revision
        with self.assertRaises(LockedError):self.candidates.adopt(cid,self.work)
        self.assertEqual(self.work.revision,head);self.assertEqual(self.store.document(self.did)['text'],before)
    def test_full_preview_counts_and_persists_request_range_without_metadata_or_auto_rewrite(self):
        self.work.config.update(words=100,length='短篇小说');body='字'*90;self.work.edit('题目\n\n简介\n\n'+body);self.work.save();self.store.set_setting('v2_payload:'+self.did,dict(payload=dict(title='题目',synopsis='简介')))
        before=self.work.text;snap=self.flow.prepare(self.c,'modify','正文目标95到110非空白字符。只改选区',(len(before)-1,len(before)),True)
        result=self.flow.service.execute(snap,CancelToken(),provider=fixtures.Provider([dict(text='字',explanation='保留')]))
        cid=self.candidates.save(snap,result);value=self.candidates.review(cid)['length'];self.assertEqual(value['actual_chars'],90);self.assertTrue(value['minimum_threshold_met']);self.assertEqual(value['range_gap'],5);self.assertEqual(value['state'],'target_not_met');self.assertEqual(self.work.text,before)
        self.candidates.adopt(cid,self.work);value=chapter_status(self.store,self.did,self.work.config);self.assertEqual(value['explicit_range']['min'],95);self.assertEqual(value['state'],'target_not_met')
        self.work.edit(self.work.text+'字'*5);self.work.save();record_completion(self.work);self.assertEqual(chapter_status(self.store,self.did,self.work.config)['range_state'],'range_met')
        next_snap=self.flow.prepare(self.c,'modify','只改语气',(len(self.work.text)-1,len(self.work.text)),True);self.assertEqual(next_snap['constraints']['_length_range']['min'],95)

if __name__=='__main__':unittest.main()
