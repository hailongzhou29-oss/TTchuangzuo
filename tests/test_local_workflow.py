import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.core.files import digest, inside
from app.core.services import Workspace, RuleService, export_document, import_preview
from app.storage.project import ConflictError, LockedError, ProjectStore

ROOT = Path(__file__).resolve().parents[1]


class LocalWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='TT创作助手 中文 空格 ')
        self.root = Path(self.temporary.name)
        self.workspace = Workspace(self.root / '工作区')
        self.store = self.workspace.create('测试作品', '剧本')
        self.did = self.store.documents()[0]['id']

    def tearDown(self):
        self.temporary.cleanup()

    def save(self, text):
        doc = self.store.document(self.did)
        return self.store.save_document(self.did, doc['head'], text)

    def test_create_save_reopen_and_unicode(self):
        self.save('【场1】历史教室\n老师：这句话必须保留。\n学生：🙂明白了。')
        reopened = self.workspace.open(self.store.root)
        self.assertEqual(reopened.document(self.did)['text'], self.store.document(self.did)['text'])
        self.assertEqual({p.name for p in self.store.root.iterdir()}, {'project.sqlite', 'assets', 'exports', 'backups'})

    def test_external_project_location_is_discovered_after_workspace_reopen(self):
        parent=self.root/'自选 作品目录'
        parent.mkdir()
        external=self.workspace.create('外部项目','小说',parent=parent)
        did=external.documents()[0]['id']
        external.save_document(did,external.document(did)['head'],'自选位置的正文')
        # An unrelated project in the same parent is not silently imported.
        unregistered=ProjectStore.create(parent/'不自动扫描的项目','旁边的项目','小说')
        reopened=Workspace(self.workspace.root)
        found=reopened.projects('all')
        self.assertEqual(external.root.parent,parent.resolve())
        self.assertIn(str(external.root),{p['root'] for p in found})
        self.assertNotIn(str(unregistered.root),{p['root'] for p in found})
        self.assertEqual(reopened.open(external.root).document(did)['text'],'自选位置的正文')
        reopened.register(external)
        self.assertEqual(sum(p['id']==external.metadata()['id'] for p in reopened.projects('all')),1)

    def test_external_project_registration_failure_preserves_created_files(self):
        from unittest.mock import patch
        parent=self.root/'登记失败时保留的目录'
        parent.mkdir()
        with patch.object(self.workspace,'register',side_effect=sqlite3.OperationalError('isolated registry failure')):
            with self.assertRaisesRegex(ValueError,'项目已创建在'):
                self.workspace.create('仍可通过目录打开','小说',parent=parent)
        projects=list(parent.iterdir())
        self.assertEqual(len(projects),1)
        self.assertTrue((projects[0]/'project.sqlite').is_file())
        self.assertEqual(self.workspace.open(projects[0]).metadata()['name'],'仍可通过目录打开')

    def test_invalid_external_parent_does_not_create_project(self):
        parent=self.root/'不存在的目录'
        before={p['id'] for p in self.workspace.projects('all')}
        with self.assertRaisesRegex(ValueError,'存在的项目存放目录'):
            self.workspace.create('无效目录','小说',parent=parent)
        self.assertFalse(parent.exists())
        self.assertEqual({p['id'] for p in self.workspace.projects('all')},before)

    def test_revision_restore_creates_new_version(self):
        original = self.save('第一版')
        second = self.save('第二版')
        restored = self.store.restore_revision(self.did, original, second)
        self.assertNotIn(restored, {original, second})
        self.assertEqual(self.store.document(self.did)['text'], '第一版')
        self.assertEqual(len(self.store.revisions(self.did)), 4)

    def test_concurrent_revision_rejected_without_loss(self):
        base = self.store.document(self.did)['head']
        self.save('另一个窗口先保存')
        with self.assertRaises(ConflictError):
            self.store.save_document(self.did, base, '过期窗口的正文')
        self.assertEqual(self.store.document(self.did)['text'], '另一个窗口先保存')

    def test_lock_rejects_modified_text_and_remaps_after_insert(self):
        self.save('开场。\n老师：原文。\n结束。')
        self.store.lock(self.did, '老师：原文。', 4)
        with self.assertRaises(LockedError):
            self.save('开场。\n老师：改写。\n结束。')
        self.save('新增。\n开场。\n老师：原文。\n结束。')
        self.assertEqual(self.store.locks(self.did)[0]['ordinal'], 8)
        with self.assertRaises(LockedError):
            self.save('新增。\n开场。\n老师：改写。\n结束。')
        self.store.unlock(self.did)
        self.save('现在允许修改')

    def test_stable_blocks_keep_annotations_after_insert(self):
        self.save('第一段\n第二段')
        old = self.store.document(self.did)['blocks']
        self.store.annotate(self.did, old[1]['block_id'], '批注')
        self.save('新增段\n第一段\n第二段')
        blocks = self.store.document(self.did)['blocks']
        self.assertEqual(blocks[2]['block_id'], old[1]['block_id'])
        self.assertEqual(self.store.annotations(self.did)[0]['block_id'], blocks[2]['block_id'])

    def test_readonly_reference_and_branch_provenance(self):
        source = self.store.add_document('来源', '不要覆盖来源', kind='reference')
        doc = self.store.document(source)
        with self.assertRaises(LockedError):
            self.store.save_document(source, doc['head'], '修改来源')
        target = self.store.add_document('新稿', '独立作品', kind='剧本', source_id=source)
        self.assertEqual(self.store.document(target)['source_id'], source)

    def test_reorder_preserves_content_and_rejects_bad_mapping(self):
        second = self.store.add_document('第二场', '内容')
        self.store.reorder([second, self.did])
        self.assertEqual(self.store.documents()[0]['id'], second)
        with self.assertRaises(ValueError):
            self.store.reorder([second, second])
        self.assertEqual(self.store.document(second)['text'], '内容')

    def test_trash_restore_is_reversible(self):
        self.save('回收仍保留')
        self.store.trash_document(self.did)
        self.assertEqual(len(self.store.documents()), 0)
        self.store.trash_document(self.did, restore=True)
        self.assertEqual(self.store.document(self.did)['text'], '回收仍保留')

    def test_confirm_then_edit_returns_to_draft(self):
        self.save('完成稿')
        current = self.store.document(self.did)
        revision = self.store.save_document(self.did, current['head'], current['text'], status='confirmed')
        self.assertEqual(self.store.document(self.did)['status'], 'confirmed')
        self.store.save_document(self.did, revision, '新修改')
        self.assertEqual(self.store.document(self.did)['status'], 'draft')

    def test_backup_restore_with_assets_and_new_project_identity(self):
        self.save('一致性备份')
        asset = self.store.root / 'assets' / '样例.bin'
        asset.write_bytes(b'test-asset')
        self.store.register_asset('assets/样例.bin', digest(b'test-asset'))
        archive = self.root / '备份.ttbackup'
        self.workspace.backup(self.store, archive)
        result = self.workspace.restore(archive)
        self.assertNotEqual(result.metadata()['id'], self.store.metadata()['id'])
        self.assertEqual(result.document(self.did)['text'], '一致性备份')
        self.assertEqual((result.root / 'assets' / '样例.bin').read_bytes(), b'test-asset')
        self.assertEqual(len(self.workspace.projects()), 2)

    def test_tampered_backup_rejected(self):
        archive = self.root / '备份.ttbackup'
        self.workspace.backup(self.store, archive)
        with zipfile.ZipFile(archive) as package:
            contents = {name: package.read(name) for name in package.namelist()}
        contents['project.sqlite'] = b'corrupted'
        with zipfile.ZipFile(archive, 'w') as package:
            for name, data in contents.items():
                package.writestr(name, data)
        with self.assertRaisesRegex(ValueError, '校验失败'):
            self.workspace.restore(archive)
        self.assertEqual(len(self.workspace.projects()), 1)

    def test_archive_path_escape_rejected(self):
        archive = self.root / '恶意.ttbackup'
        manifest = {'format': 'tt-create-backup', 'schema_version': 1, 'files': {'project.sqlite': digest(b'bad'), 'assets/../../escape': digest(b'bad')}}
        with zipfile.ZipFile(archive, 'w') as package:
            package.writestr('manifest.json', json.dumps(manifest))
            package.writestr('project.sqlite', b'bad')
            package.writestr('assets/../../escape', b'bad')
        with self.assertRaisesRegex(ValueError, '路径超出'):
            self.workspace.restore(archive)
        self.assertFalse((self.root / 'escape').exists())

    def test_missing_asset_prevents_incomplete_backup(self):
        self.store.register_asset('assets/missing.png', 'hash')
        with self.assertRaisesRegex(ValueError, '素材缺失'):
            self.workspace.backup(self.store, self.root / '不完整.ttbackup')

    def test_export_formats_preserve_dialogue(self):
        text = '老师：这是原话。\n学生：不能漏句。'
        self.save(text)
        for suffix in ('.md', '.txt', '.json'):
            path = self.root / ('导出' + suffix)
            export_document(self.store, self.did, path)
            result = path.read_text(encoding='utf-8')
            if suffix == '.json':
                result = json.loads(result)['text']
            self.assertIn(text, result)

    def test_import_chinese_encoding_and_json_preview(self):
        path = self.root / '中文.txt'
        path.write_bytes('来源原文'.encode('gb18030'))
        self.assertEqual(import_preview(path)['text'], '来源原文')
        path = self.root / '未知.json'
        path.write_text('{"videos": [{"videoId": "v1", "prompt": "原提示"}]}', encoding='utf-8')
        self.assertIn('原结构保留', import_preview(path)['note'])

    def test_copy_is_independent(self):
        self.save('原项目')
        copied = self.workspace.copy(self.store)
        copied.save_document(self.did, copied.document(self.did)['head'], '副本修改')
        self.assertEqual(self.store.document(self.did)['text'], '原项目')

    def test_copy_without_assets_keeps_writing_and_local_cover_layout(self):
        from app.core.cover import default_cover
        self.save('正文不会因不复制素材而丢失')
        asset=self.store.root/'assets'/'cover.bin'
        asset.write_bytes(b'isolated-source-asset')
        self.store.register_asset('assets/cover.bin',digest(asset.read_bytes()))
        spec=default_cover('测试封面','剧本')
        spec.update(image='assets/cover.bin',include_local_text=False)
        cid=self.store.save_cover(spec)
        self.store.set_setting('active_cover',cid)
        self.store.set_setting('cover_draft',spec)
        self.store.set_setting('assistant_note','旧助手讨论')
        copied=self.workspace.copy(self.store,include_assets=False)
        self.assertNotEqual(copied.metadata()['id'],self.store.metadata()['id'])
        self.assertEqual(copied.document(self.did)['text'],'正文不会因不复制素材而丢失')
        self.assertEqual(list((copied.root/'assets').iterdir()),[])
        with copied.connection() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM assets').fetchone()[0],0)
        self.assertIsNone(copied.covers()[0]['spec']['image'])
        self.assertTrue(copied.covers()[0]['spec']['include_local_text'])
        self.assertIsNone(copied.setting('cover_draft')['image'])
        self.assertEqual(copied.setting('active_cover'),cid)
        self.assertIsNone(copied.setting('assistant_note'))
        self.assertFalse(copied.setting('copied_assets'))
        self.assertEqual(asset.read_bytes(),b'isolated-source-asset')
        self.assertEqual(self.store.covers()[0]['spec']['image'],'assets/cover.bin')

    def test_copy_can_omit_missing_assets_but_full_backup_still_rejects(self):
        self.save('只复制文字')
        self.store.register_asset('assets/missing.bin','missing-hash')
        copied=self.workspace.copy(self.store,include_assets=False)
        self.assertEqual(copied.document(self.did)['text'],'只复制文字')
        with self.assertRaisesRegex(ValueError,'素材缺失'):
            self.workspace.copy(self.store,include_assets=True)

    def test_rules_and_seed_evidence_bounds(self):
        rules = RuleService(ROOT / 'resources').rules()
        self.assertEqual(len(rules), 19)
        self.assertEqual(len({r['rule_id'] for r in rules}), 19)
        seed = json.loads((ROOT / 'resources' / '影视案例库_改编关系种子_V0.1.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(len(seed['records']), 6)
        self.assertEqual(sum(len(r['adaptation_sources']) for r in seed['records']), 7)
        altai = next(r for r in seed['records'] if r['title'] == '我的阿勒泰')
        self.assertEqual(altai['adaptation_sources'][0]['source_type'], 'essay_collection')
        self.assertTrue(all(not r['rating_snapshots'] for r in seed['records']))


if __name__ == '__main__':
    unittest.main()
