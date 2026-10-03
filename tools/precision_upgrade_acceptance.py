"""Focused offline checks using one tiny disposable workspace; no production reads."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QPushButton
from app.core.test_isolation import start_test_runtime
from app.core.files import write_json
from app.core.data_root import startup_paths,DataMigration,validate_root
from app.core.codex_state import remember,status,cached_probe
from app.core.services import Workspace
from app.core.selection import selection
from app.ui.v2_window import MainWindow
from app.ui.icons import application_icon
from app.ui.interaction import ui_font
from app.providers.codex_text import CodexTextProvider


def main():
    app=QApplication([]); app.setFont(ui_font()); checks=[]
    original_temp=tempfile.tempdir; original_env={k:os.environ.get(k) for k in ('TMP','TEMP','TT_CREATOR_TEST_MODE','TT_CREATOR_TEST_ROOT')}
    (ROOT/'logs').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='precision-ui-',dir=ROOT/'logs') as temporary:
        base=start_test_runtime(Path(temporary)); source=base/'原数据'; source.mkdir(); workspace=Workspace(source/'internal_data')
        store=workspace.create('精准验收作品','剧本'); config=selection('script'); store.set_setting('v2_kind','script'); store.set_setting('v2_selection',config)
        did=store.add_document('正文','验收正文：雨停以后，两人继续过桥。','剧本'); store.set_setting('v2_last_document',did)
        write_json(source/'preferences.json',dict(theme='雾白浅色',restore_last=True,last_project=str(store.root)))
        root,prefs,_=startup_paths(base,data_root=source)
        assert root==source and prefs==source/'preferences.json'
        if os.name=='nt':
            try: validate_root('C:/禁止写入测试')
            except ValueError: pass
            else: raise AssertionError('C 盘未被拒绝')
        checks.append('统一数据根目录与 C 盘限制')
        probe=dict(prefix=[str(base/'fake-codex.exe')],version='codex-cli fixture',features=['image_generation','shell_tool'],logged_in=True)
        remember(source,'',probe)
        with patch.object(CodexTextProvider,'detect',side_effect=AssertionError('不应自动检测')):
            window=MainWindow(workspace,ROOT/'resources',source/'preferences.json'); window.resize(1440,900); window.show(); app.processEvents()
            assert window.pages.currentIndex()==0 and window.work is None
            assert window.settings.codex_auth.text().startswith('账号：已登录')
            window.settings.c.activate_model_channel('codex_local')
            assert not window.settings.operations
        assert len(application_icon().availableSizes())==7 and not window.windowIcon().isNull()
        checks.extend(['启动首页，不恢复上次作品','缓存登录状态，启用模型不重复检测','七尺寸窗口图标'])
        assert len(window.home.cards)==1
        card=window.home.cards[0]; assert list(card.actions)==['重命名','生成封面','导出','删除']
        QTest.mouseClick(card.title,Qt.MouseButton.LeftButton); app.processEvents(); assert card.property('selected')
        for text,method in [('生成封面','open_home_cover'),('导出','export_home'),('删除','trash_project')]:
            with patch.object(window,method) as action:
                card.actions[text].click(); action.assert_called_once_with(str(store.root))
        card.actions['重命名'].click(); card.rename.setText('精准验收改名'); card.save_name(); assert store.metadata()['name']=='精准验收改名'
        app.processEvents(); QTest.qWait(30)
        card=window.home.cards[0]; assert card.property('selected')
        assert card.isVisible() and card.width()<=260
        for control in card.actions.values(): assert control.width()>=control.fontMetrics().horizontalAdvance(control.text())+6
        checks.append('卡片四按钮、选中状态、改名和操作路由')
        evidence=base/'screens'; evidence.mkdir()
        window.grab().save(str(evidence/'home.png'))
        window.open_project(store.root); page=window.creators['script']; before=page.editor.toPlainText(); dirty=window.work.dirty; size=window.options['editor_font_size']
        page.font_controls.more.click(); app.processEvents()
        assert window.options['editor_font_size']==size+1 and page.editor.toPlainText()==before and window.work.dirty==dirty
        page.font_controls.less.click(); page.font_controls.size_value.click(); assert window.options['editor_font_size']==18
        for kind in ('novel','rewrite'):
            other=window.creators[kind]; other.font_controls.more.click(); assert window.options['editor_font_size']==19; other.font_controls.size_value.click()
        page.set_view(1); window.grab().save(str(evidence/'editor.png'))
        checks.append('三个编辑器字号同步、范围控制、正文与脏标记不变')
        selector=window.settings.theme_selector
        assert [selector.itemText(i) for i in range(selector.count())]==['雾白浅色','石墨深色','暖纸写作']
        for index in range(3):
            selector.setCurrentIndex(index); app.processEvents(); assert window.theme==selector.itemData(index)
            assert window.options['theme']==window.theme
            for index_page in range(5): window.navigate(index_page); app.processEvents()
        selector.setCurrentIndex(0); window.navigate(4); window.settings.tabs.setCurrentIndex(3); app.processEvents(); window.grab().save(str(evidence/'settings.png'))
        texts=[button.text() for button in window.settings.advanced_tab.findChildren(QPushButton)]
        assert not any('历史' in text or '旧设置' in text for text in texts)
        checks.append('五栏目与原始三主题渲染、移除历史目录入口')
        window.navigate(1); window.save_work(); output=window.output_files.write('剧本','验收',b'tiny output')
        store.set_setting('v2_output_receipts',[dict(root=str(source),path=str(output),hash='fixture')])
        (source/'logs').mkdir(exist_ok=True); (source/'logs'/'fixture.log').write_text('tiny log',encoding='utf-8')
        (source/'cache').mkdir(exist_ok=True); (source/'cache'/'fixture.tmp').write_bytes(b'tiny cache')
        (source/'credentials.dat').write_bytes(b'opaque fixture; not a real credential')
        locator=base/'local.runtime.json'; write_json(locator,dict(python='fixture-python',data_root=str(source))); window.runtime_locator=locator
        window.settings.operations.append(object())
        try:
            try: window.migrate_data_root(base/'禁止迁移')
            except ValueError: pass
            else: raise AssertionError('后台操作期间不应迁移')
        finally: window.settings.operations.clear()
        target=base/'新数据'; target.mkdir(); message=window.migrate_data_root(target)
        assert '已清理' in message and not source.exists() and window.data_root==target
        assert window.connections.path.parent==target and window.preferences.parent==target and window.workspace.root.is_relative_to(target)
        assert window.work.store.document(window.work.document_id)['text']==before
        assert (target/'剧本'/output.name).read_bytes()==b'tiny output'
        assert (target/'logs'/'fixture.log').read_text(encoding='utf-8')=='tiny log' and (target/'cache'/'fixture.tmp').read_bytes()==b'tiny cache'
        assert (target/'credentials.dat').read_bytes()==b'opaque fixture; not a real credential'
        receipt=window.work.store.setting('v2_output_receipts')[0]; assert receipt['root']==str(target) and Path(receipt['path']).is_file()
        assert startup_paths(base)[0]==target and status(target,'')['authenticated'] and cached_probe(target,probe['prefix'])
        assert tempfile.tempdir==str(target/'cache')
        checks.append('整目录迁移、项目与输出引用更新、凭据不解密、旧目录清理、启动定位更新')
        occupied=base/'非空'; occupied.mkdir(); (occupied/'other.txt').write_text('keep',encoding='utf-8')
        for invalid in (target/'子目录',base,occupied):
            try: DataMigration(target,invalid)
            except ValueError: pass
            else: raise AssertionError('不安全的目录应被拒绝')
        failed=base/'失败目标'
        with patch('app.core.data_root.shutil.copytree',side_effect=OSError('模拟复制失败')):
            try: window.migrate_data_root(failed)
            except OSError: pass
            else: raise AssertionError('复制失败应上报')
        assert window.data_root==target and (target/'preferences.json').is_file() and not failed.exists() and not window.migrating
        checks.append('嵌套／非空目录拒绝与迁移失败回退')
        window.close(); app.processEvents()
        with patch.object(CodexTextProvider,'detect',side_effect=AssertionError('重启不应自动检测')):
            reopened=MainWindow(Workspace(target/'internal_data'),ROOT/'resources',target/'preferences.json')
            assert reopened.pages.currentIndex()==0 and reopened.settings.codex_auth.text().startswith('账号：已登录') and reopened.options['editor_font_size']==18
            reopened.close()
        checks.append('迁移后重启、主题／字号／登录记录持久化')
        report=ROOT/'docs'/'evidence'/'precision_upgrade'; report.mkdir(parents=True,exist_ok=True)
        # Evidence is generated from fixtures only; no actual account/session was queried.
        import shutil
        for filename in ('home.png','editor.png','settings.png'): shutil.copyfile(evidence/filename,report/filename)
        (report/'results.json').write_text(json.dumps(dict(passed=checks,live_codex=False,production_data_read=False,build=False),ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(passed=len(checks),checks=checks,live_codex=False,build=False),ensure_ascii=False))
    tempfile.tempdir=original_temp
    for key,value in original_env.items():
        if value is None: os.environ.pop(key,None)
        else: os.environ[key]=value

if __name__=='__main__': main()
