import copy,json,tempfile,unittest
from pathlib import Path
from app.core.writing_views import normalize_budget,writing_config,active_config,source_snapshot,validate_rewrite,ensure_outline,chapter_documents
from app.core.selection import selection,Registry
from app.core.creation_flow import parse_output
from app.core.services import Workspace

ROOT=Path(__file__).resolve().parents[1]
class WritingViewTests(unittest.TestCase):
    def test_total_is_authoritative(self):
        c=normalize_budget(dict(words=12001,chapters=5,chapter_words=2500))
        self.assertEqual((c['words'],c['chapters'],c['chapter_words']),(12001,5,2401))
    def test_chapter_budget_updates_count_not_total(self):
        c=normalize_budget(dict(words=12000,chapters=4,chapter_words=2500),'chapter_words')
        self.assertEqual((c['words'],c['chapters'],c['chapter_words']),(12000,5,2500))
    def test_old_conflicting_budget_keeps_original(self):
        old=dict(selection('novel'),length='长篇连载',words=3000,chapters=30,chapter_words=2500)
        c=writing_config(old,'novel')
        self.assertEqual(c['writing_original'],old); self.assertEqual(c['chapter_words'],100); self.assertTrue(c['writing_notes'])
    def test_inactive_branch_never_enters_request(self):
        c=dict(selection('rewrite'),output='novel',script_settings={'old':'retained'},rewrite_branches={'script':{'duration':90}})
        active=active_config(c)
        self.assertNotIn('duration',active); self.assertNotIn('script_settings',active); self.assertNotIn('rewrite_branches',active); self.assertIn('words',active)
        c['output']='script'; active=active_config(c); self.assertNotIn('words',active); self.assertNotIn('perspective',active); self.assertEqual(c['rewrite_branches']['script']['duration'],90)
    def test_snapshot_is_immutable_and_structure_description_is_explicit(self):
        c=dict(reference='原参考',reference_source=dict(name='原文.md',revision='r1')); frozen=source_snapshot(c); c['reference']='替换原文'; c['reference_source']['name']='新文件'
        self.assertEqual(frozen['text'],'原参考'); self.assertEqual(frozen['name'],'原文.md'); self.assertEqual(frozen['source_revision'],'r1')
        described=source_snapshot(dict(reference='',reference_description='先隐藏真相，再用旧信揭示'))
        self.assertEqual(described['status'],'用户结构描述')
    def test_empty_reference_and_conflicting_constraints_are_blocked(self):
        with self.assertRaises(ValueError): source_snapshot({})
        c=dict(selection('rewrite'),reference='可读原文',must_change='钟楼',advanced={'必须保留':'钟楼'})
        with self.assertRaises(ValueError): validate_rewrite(c)
    def test_novel_rules_do_not_inherit_camera_or_commerce(self):
        c=dict(selection('novel'),mode='剧情带货',object='',advanced={'世界规则':'夜间才能进站'})
        rows=Registry(ROOT/'resources').effective(active_config(c)); ids={r['id'] for r in rows}
        self.assertIn('R03',ids); self.assertNotIn('R10',ids); self.assertIn('novel.世界规则',ids)
    def test_outline_has_real_id_and_is_not_a_chapter(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Workspace(Path(temp)/'data').create('旧长篇','小说'); c=dict(selection('novel'),length='长篇连载'); plan=dict(synopsis='旧简介',characters='人物约束',chapters=['第一章'])
            store.set_setting('v2_plan',plan); first=store.documents()[0]['id']; store.save_document(first,store.document(first)['head'],'现有第一章','手写')
            did=ensure_outline(store,c); self.assertNotEqual(did,first); self.assertEqual(store.document(did)['kind'],'outline'); self.assertEqual([d['id'] for d in chapter_documents(store)],[first]); self.assertEqual(store.document(first)['text'],'现有第一章'); self.assertEqual(ensure_outline(store,c),did)
    def test_long_empty_outline_is_invalid_not_fake_complete(self):
        value=dict(title='标题',synopsis='简介',characters='角色',chapter_title='第一章',text='正文',plan=[])
        with self.assertRaises(ValueError): parse_output(json.dumps(value,ensure_ascii=False),'generate',dict(selection('novel'),length='长篇连载'))

if __name__=='__main__': unittest.main()
