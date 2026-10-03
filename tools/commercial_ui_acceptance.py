"""Real Qt input events on tiny isolated fixtures; no paid providers or production data."""
import os,sys,json,tempfile
from pathlib import Path
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
os.environ['QT_QPA_PLATFORM']='windows' if '--native' in sys.argv else 'offscreen'
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QWidget
from app.core.test_isolation import start_test_runtime
from app.core.services import Workspace
from app.core.selection import selection
from app.core.files import write_json
from app.core.codex_state import remember
from app.ui.v2_window import MainWindow
from app.ui.interaction import ui_font,ChoicePopup
from app.ui.cover_panel import story_outline


def main():
    app=QApplication([]); app.setFont(ui_font()); app.setProperty('native_hidden_test',True); checks=[]
    with tempfile.TemporaryDirectory(prefix='commercial-ui-',dir=ROOT/'logs') as temporary:
        base=start_test_runtime(Path(temporary)); workspace=Workspace(base/'internal_data'); window=MainWindow(workspace,ROOT/'resources',base/'preferences.json'); window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen); window.resize(1440,940); window.show(); QTest.qWait(100)
        assert window.pages.currentIndex()==0 and window.title_bar.height()==48
        for kind,index in [('script',1),('novel',2),('rewrite',3)]:
            window.navigate(0); app.processEvents(); QTest.mouseClick(window.home.create_buttons[kind],Qt.MouseButton.LeftButton); app.processEvents(); assert window.pages.currentIndex()==index,(kind,window.statusBar().currentMessage()); assert window.work is None
        checks.append('首页三个入口真实点击，启动首页与自定义标题栏')
        evidence=ROOT/'docs'/'evidence'/'commercial_ui_upgrade'/('native' if '--native' in sys.argv else 'scale-'+os.environ.get('QT_SCALE_FACTOR','1')); evidence.mkdir(parents=True,exist_ok=True)
        window.navigate(0); QTest.qWait(30); window.grab().save(str(evidence/'01-home.png'))
        from app.ui.v2_widgets import QMenu
        def choose_creation():
            menus=[menu for menu in window.home.findChildren(QMenu) if menu.isVisible()]
            if menus:
                menu=menus[-1]; menu.grab().save(str(evidence/'09-menu.png')); QTest.mouseClick(menu,Qt.MouseButton.LeftButton,pos=menu.actionGeometry(menu.actions()[0]).center())
        QTimer.singleShot(50,choose_creation); QTimer.singleShot(1500,lambda:[menu.close() for menu in window.home.findChildren(QMenu)]); QTest.mouseClick(window.home.new_button,Qt.MouseButton.LeftButton); assert window.pages.currentIndex()==1; checks.append('新建项目菜单真实选择与圆角浮层')
        stores={}
        for kind in ('script','novel','rewrite'):
            store=workspace.create('验收 · '+kind,{'script':'剧本','novel':'小说','rewrite':'仿写'}[kind]); config=selection(kind)
            if kind!='script': config.update(output='novel',length='短篇小说')
            store.set_setting('v2_kind',kind); store.set_setting('v2_selection',config)
            text='第一部分｜故事大纲\n雨夜，旅人寻找失踪同伴。\n第二部分｜完整剧本\nBODY_ONLY，只供测试的正文。' if kind=='script' else 'BODY_ONLY，'+kind+'的测试正文。'
            did=store.add_document('正文',text,{'script':'剧本','novel':'小说','rewrite':'仿写'}[kind]); store.set_setting('v2_last_document',did)
            if kind!='script': store.add_document('故事大纲','雨夜，旅人寻找失踪同伴。','outline')
            stores[kind]=store; window.open_project(store.root); page=window.creators[kind]; page.set_view(1); QTest.qWait(50)
            assert page.editor_toolbar.isVisible() and page.editor_footer.copy_button.isEnabled()
            original=page.editor.toPlainText(); cursor=page.editor.textCursor(); cursor.movePosition(cursor.MoveOperation.End); page.editor.setTextCursor(cursor); page.editor.insertPlainText(' edited'); QTest.mouseClick(page.editor_toolbar.actions['撤销'],Qt.MouseButton.LeftButton); assert page.editor.toPlainText()==original
            QTest.mouseClick(page.editor_toolbar.actions['重做'],Qt.MouseButton.LeftButton); assert page.editor.toPlainText()==original+' edited'
            clipboard=Mock()
            with patch('app.ui.commercial_controls.QApplication.clipboard',return_value=clipboard):
                QTest.mouseClick(page.editor_footer.copy_button,Qt.MouseButton.LeftButton); clipboard.setText.assert_called_once_with(original+' edited')
            QTest.mouseClick(page.editor_toolbar.actions['查找'],Qt.MouseButton.LeftButton); assert page.find_row.isVisible(); page.find_row.hide()
            QTest.mouseClick(page.editor_toolbar.actions['版本历史'],Qt.MouseButton.LeftButton); assert window.inline is not None
            from PySide6.QtWidgets import QPushButton,QTextBrowser
            compare=window.inline.findChild(QPushButton,'versionCompare'); QTest.mouseClick(compare,Qt.MouseButton.LeftButton); assert compare.isChecked() and '当前正文' in window.inline.findChild(QTextBrowser).toPlainText(); window.close_inline(); page.set_view(1)
            before=page.editor.toPlainText(); dirty=window.work.dirty; QTest.mouseClick(page.font_controls.more,Qt.MouseButton.LeftButton); assert page.editor.toPlainText()==before and window.work.dirty==dirty; assert page.editor.font().pixelSize()==window.options['editor_font_size']; page.font_controls.size_value.click()
            QTest.mouseClick(page.editor_toolbar.actions['阅读模式'],Qt.MouseButton.LeftButton); assert window.reading; window.escape(); assert not window.reading
            checks.append(kind+'：真实点击撤销／重做／查找／版本历史／复制／字号／阅读')
            if kind!='script':
                second=store.add_document('第二章','第二章的测试正文。','小说'); page.refresh_documents(window.work); page.editor_footer.refresh(); clipboard=Mock()
                with patch('app.ui.commercial_controls.QApplication.clipboard',return_value=clipboard):
                    QTest.mouseClick(page.editor_footer.book_copy,Qt.MouseButton.LeftButton); copied=clipboard.setText.call_args.args[0]; assert '第二章的测试正文。' in copied and '雨夜，旅人寻找失踪同伴。' not in copied
            window.grab().save(str(evidence/('02-'+kind+'.png')))
        page=window.creators['script']; window.open_project(stores['script'].root); page.set_view(0); QTest.qWait(100)
        scroll=page.settings_scroll.verticalScrollBar(); scroll.setValue(min(100,scroll.maximum())); initial=scroll.value()
        for _ in range(3):
            QTest.mouseClick(page.script_form.basic_more,Qt.MouseButton.LeftButton); QTest.qWait(240)
        assert abs(scroll.value()-initial)<=6,(initial,scroll.value()); checks.append('补充设置连续真实点击，布局与滚动稳定')
        combo=page.script_form.fields['form']; QTest.mouseClick(combo,Qt.MouseButton.LeftButton); QTest.qWait(180); popup=combo.choice_popup; assert popup and popup.isVisible(); assert popup.windowFlags() & Qt.WindowType.FramelessWindowHint and popup.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        popup.grab().save(str(evidence/'08-dropdown.png')); corner=popup.grab().toImage().pixelColor(0,0); assert corner.alpha()<64,corner.name()
        before=combo.currentIndex(); target=1 if before!=1 else 0; item=popup.list.item(target); QTest.mouseClick(popup.list.viewport(),Qt.MouseButton.LeftButton,pos=popup.list.visualItemRect(item).center()); QTest.qWait(40); assert combo.currentIndex()==target; checks.append('下拉选择真实点击、无系统粗框与透明圆角')
        window.work=None; window.navigate(0); QTest.qWait(50); old_index=window.pages.currentIndex(); old_work=window.work; window.home.select_card(str(stores['novel'].root))
        window.open_home_cover(stores['novel'].root); QTest.qWait(80); dialog=window.cover_dialog; panel=dialog.panel
        assert window.pages.currentIndex()==old_index and window.work is old_work; assert 'BODY_ONLY' not in panel.prompt.toPlainText(); assert panel.outline.toPlainText().strip()
        for ratio in ('3:4','16:9','9:16','4:3'):
            panel.ratio.setCurrentText(ratio); assert '画幅：'+ratio in panel.prompt.toPlainText()
            with patch('app.ui.cover_panel.ImageService') as service,patch('app.ui.cover_panel.QThreadPool.globalInstance') as pool:
                service.return_value.prepare.return_value={'task_id':'fixture','model_selection':{},'requested_ratio':ratio}; panel.connection.addItem('测试渠道','fixture'); panel.connection.setCurrentIndex(panel.connection.findData('fixture'))
                from app.providers.image_contracts import ImageConnection
                panel.fixed_connection=ImageConnection('fixture','测试渠道','image_codex','',sizes=('1024x1024',)); panel.generate(); assert service.return_value.prepare.call_args.args[2]['ratio']==ratio; window.active_image_task=None; panel.worker=None
        assert panel.generate_button.isVisible() and panel.generate_button.mapTo(dialog,panel.generate_button.rect().bottomRight()).y()<dialog.height()
        window.grab().save(str(evidence/'03-home-cover-owner.png')); dialog.grab().save(str(evidence/'04-cover-dialog.png')); dialog.close(); QTest.qWait(30); assert window.pages.currentIndex()==0 and window.work is old_work; checks.append('首页封面原位弹窗、四画幅进入请求、名称与大纲取材、关闭恢复')
        window.open_home_cover(stores['novel'].root); QTest.qWait(40); dialog=window.cover_dialog; panel=dialog.panel
        from PySide6.QtGui import QImage,QColor
        from app.core.files import digest
        from app.ui.cover_panel import cover_image
        image=QImage(320,240,QImage.Format.Format_RGB32); image.fill(QColor('#27364C')); image_path=stores['novel'].root/'assets'/'cover-fixture.png'; image.save(str(image_path)); panel.candidate=dict(relative='assets/cover-fixture.png',sha256=digest(image_path.read_bytes()),width=320,height=240); panel.composed=cover_image(image_path,panel.title.text(),panel.ratio.currentText(),panel.mode.currentText()); panel.adopt_button.show(); QTest.mouseClick(panel.adopt_button,Qt.MouseButton.LeftButton); QTest.qWait(40)
        assert stores['novel'].setting('active_cover') and window.pages.currentIndex()==0 and window.work is old_work; checks.append('采用测试封面更新对应项目，首页和当前编辑作品不切换')
        window.open_project(stores['script'].root); page=window.creators['script']; page.set_view(1); window.active_task={'page':page}; page.notify('正在构思…'); QTest.qWait(120); assert page.banner.busy and page.banner.spinner.angle>0; window.active_task=None; page.notify('作品已保存'); assert not page.banner.busy
        window.assistant.append('助手','## 修改建议\n**人物动机**需要提前交代。\n- 保留结尾\n- 调整开场'); window.grab().save(str(evidence/'05-assistant-status.png')); checks.append('真实加载动画与 AI 消息标题／列表层级')
        for theme in ('清透白','石墨紫','暖纸色'):
            window.set_theme(theme); QTest.qWait(30)
            for kind in ('script','novel','rewrite'):
                window.navigate({'script':1,'novel':2,'rewrite':3}[kind]); window.creators[kind].set_view(1); app.processEvents(); assert window.creators[kind].editor_toolbar.isVisible()
            window.grab().save(str(evidence/('06-theme-'+theme+'.png')))
        checks.append('三主题、三个正文栏目共同渲染')
        window.resize(900,720)
        for kind,index in [('script',1),('novel',2),('rewrite',3)]:
            window.navigate(index); page=window.creators[kind]; page.set_view(1); QTest.qWait(40)
            for action in (page.editor_footer.copy_button,page.generate_button):
                rect=action.rect(); top_left=action.mapTo(window,rect.topLeft()); bottom_right=action.mapTo(window,rect.bottomRight()); assert window.rect().contains(top_left) and window.rect().contains(bottom_right),(kind,window.size(),top_left,bottom_right)
        window.grab().save(str(evidence/'10-compact.png')); window.resize(1440,940); checks.append('窄窗口三个栏目复制与生成按钮保持可见')
        remember(base,'',dict(prefix=[str(base/'fake-codex.exe')],features=['shell_tool','image_generation'],version='codex-cli fixture',logged_in=True)); window.settings.refresh_cached_codex_ui(); window.navigate(4); window.settings.tabs.setCurrentIndex(1); QTest.mouseClick(window.settings.channel_save,Qt.MouseButton.LeftButton); assert window.settings.channel_save.text()=='当前使用中' and not window.settings.channel_save.isEnabled(); QTest.qWait(30); window.grab().save(str(evidence/'11-model-active.png')); window.settings.codex_model.setText('changed'); assert window.settings.channel_save.text()=='请先保存修改'; checks.append('启用模型真实点击、当前使用中与未保存状态')
        window.settings.tabs.setCurrentIndex(3); window.settings.motion_selector.setCurrentIndex(1); assert window.motion.reduced(); window.grab().save(str(evidence/'07-settings.png')); window.close(); app.processEvents()
        (evidence/'results.json').write_text(json.dumps(dict(platform=app.platformName(),scale=app.devicePixelRatio(),passed=checks,paid_calls=0,production_data_read=False,build=False),ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(dict(passed=len(checks),checks=checks,platform=app.platformName(),paid_calls=0,build=False),ensure_ascii=False))

if __name__=='__main__': main()
