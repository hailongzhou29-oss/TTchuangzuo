"""Focused regression of the reported crashes and edit/adopt path, with local fake responses."""
import os,sys,json,tempfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'tests')); os.environ['QT_QPA_PLATFORM']='windows'
from PySide6.QtCore import Qt,QPoint,QPointF,QEvent,QThreadPool,QTimer
from PySide6.QtGui import QMouseEvent,QWheelEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app.core.test_isolation import start_test_runtime
from app.core.services import Workspace
from app.core.selection import selection
from app.core.creation_flow import CreationFlow
from app.core.agent_candidates import AgentCandidates
from app.core.work_context import intent
from app.providers.contracts import Connection,CancelToken
from app.ui.v2_window import MainWindow
from app.ui.v2_widgets import QMenu
from app.ui.interaction import theme_tokens,ui_font
from test_agent_workflow import Provider

def main():
    app=QApplication([]); app.setProperty('native_hidden_test',True); errors=[]; checks=[]
    def capture_error(kind,value,trace):
        errors.append(str(value)); __import__('traceback').print_exception(kind,value,trace)
    sys.excepthook=capture_error
    with tempfile.TemporaryDirectory(prefix='ui-foundation-',dir=ROOT/'logs') as temporary:
        base=start_test_runtime(Path(temporary)); window=MainWindow(Workspace(base/'internal_data'),ROOT/'resources',base/'preferences.json'); window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen); window.resize(1440,900); window.show(); QTest.qWait(50)
        evidence=ROOT/'docs'/'evidence'/'ui_foundation_fix'; evidence.mkdir(parents=True,exist_ok=True)
        assert intent('帮我拓展到60秒')=='modify' and intent('只讨论怎么拓展到60秒，不要修改正文')=='discuss'
        for kind,index in [('script',1),('novel',2),('rewrite',3)]:
            store=window.workspace.create('定向验收 '+kind,{'script':'剧本','novel':'小说','rewrite':'仿写'}[kind]); config=selection(kind)
            if kind=='rewrite': config['reference_description']='起因、冲突与结尾的三段叙事结构'
            store.set_setting('v2_kind',kind); store.set_setting('v2_selection',config); did=store.documents()[0]['id']; store.save_document(did,store.document(did)['head'],'原稿第一句。\n结尾保持。','测试原稿'); store.set_setting('v2_last_document',did)
            window.open_project(store.root); page=window.creators[kind]; original=window.work.text; connection=Connection('fixture','本地测试','deepseek','test-model',base_url='https://example.org',max_output=8192,context_limit=65536); window.connections.save(connection)
            flow=CreationFlow(window.work,ROOT/'resources',window.connections); snapshot=flow.prepare(connection,'modify','改写第一句，保留结尾',(0,6),True); result=flow.service.execute(snapshot,CancelToken(),provider=Provider([dict(text='新的第一句。',explanation='本地模拟改稿')]))
            assert result['status']=='completed',(kind,result.get('error')); cid=AgentCandidates(store).save(snapshot,result); window.assistant.refresh_candidates(); assert window.assistant.apply_button.isEnabled() and window.work.text==original
            if kind=='script': window.grab().save(str(evidence/'pending-apply.png'))
            QTest.mouseClick(window.assistant.candidate_button,Qt.MouseButton.LeftButton); app.processEvents(); assert page.candidate_pane and page.candidate_pane.adopt_button.isEnabled(); QTest.mouseClick(page.editor_toolbar.actions['阅读模式'],Qt.MouseButton.LeftButton); app.processEvents(); assert page.candidate_pane is None and page.editor.isVisible(); window.escape()
            QTest.mouseClick(window.assistant.apply_button,Qt.MouseButton.LeftButton); app.processEvents(); assert window.work.text.startswith('新的第一句。') and '结尾保持。' in window.work.text and store.document(did)['text']==window.work.text,(kind,window.work.text)
            checks.append(kind+'：打开改稿→阅读→应用到正文→保存，没有 count 异常')
            adopted=window.work.text; snapshot2=flow.prepare(connection,'modify','改写第一句',(0,6),True); result2=flow.service.execute(snapshot2,CancelToken(),provider=Provider([dict(text='这份改稿会放弃。',explanation='本地模拟放弃')]))
            cid2=AgentCandidates(store).save(snapshot2,result2); window.assistant.refresh_candidates(); QTest.mouseClick(window.assistant.discard_button,Qt.MouseButton.LeftButton); assert AgentCandidates(store).row(cid2)['state']=='discarded' and window.work.text==adopted
            page.set_view(0); QTest.qWait(60); script_output=page.config.get('output')=='script'; form=page.script_form if script_output else page.novel_form; field=form.fields['form' if script_output else 'length']; assert field.minimumHeight()<=field.maximumHeight() and field.y()+field.height()<=field.parentWidget().height(),(kind,field.height(),field.parentWidget().height())
            scrollbar=page.settings_scroll.verticalScrollBar(); scrollbar.setValue(0); event=QWheelEvent(QPointF(8,8),QPointF(field.mapToGlobal(QPoint(8,8))),QPoint(),QPoint(0,-120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False); app.sendEvent(field,event); assert scrollbar.value()>0,(kind,scrollbar.maximum())
            page.generate_button._progress(None); page.generate_button._hover(1.0); page.generate_button._hover(0.0); QTest.qWait(140); assert not errors,errors
            checks.append(kind+'：44 高控件完整、输入框上滚轮可滚动、空值动画不崩溃')
        page=window.current_page(); page.set_view(1); window.assistant.append('助手','## 改稿说明\n**应用后**更新左侧正文，原版本保留。'); page.notify('改稿已应用并保存'); window.grab().save(str(evidence/'01-shared-ui.png'))
        for theme in ('清透白','石墨紫','暖纸色'):
            window.set_theme(theme); app.processEvents(); window.assistant.chat.selectAll()
            def close_menu():
                menus=[menu for menu in window.assistant.chat.findChildren(QMenu) if menu.isVisible()]
                if menus:
                    menus[-1].grab().save(str(evidence/('menu-'+theme+'.png'))); menus[-1].close()
            QTimer.singleShot(30,close_menu)
            from PySide6.QtGui import QContextMenuEvent
            event=QContextMenuEvent(QContextMenuEvent.Reason.Mouse,QPoint(8,8),window.assistant.chat.viewport().mapToGlobal(QPoint(8,8))); app.sendEvent(window.assistant.chat.viewport(),event); app.processEvents()
            window.grab().save(str(evidence/('ui-'+theme+'.png')))
        checks.append('AI 回复 viewport 右键菜单三主题适配')
        grip=window.resize_grips[1]; window.showNormal(); app.processEvents(); initial=window.height(); position=QPointF(grip.width()/2,4); origin=QPointF(grip.mapToGlobal(position.toPoint()))
        app.sendEvent(grip,QMouseEvent(QEvent.Type.MouseButtonPress,position,origin,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)); app.sendEvent(grip,QMouseEvent(QEvent.Type.MouseMove,position+QPointF(0,35),origin+QPointF(0,35),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)); app.sendEvent(grip,QMouseEvent(QEvent.Type.MouseButtonRelease,position,origin+QPointF(0,35),Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)); assert window.height()>=initial+30,(initial,window.height()); checks.append('底部控件实际拖动改变窗口高度')
        assert not errors,errors; QThreadPool.globalInstance().waitForDone(2000); window.close(); app.processEvents()
        (evidence/'results.json').write_text(json.dumps(dict(passed=checks,unhandled_errors=errors,platform=app.platformName(),font=ui_font().family(),paid_calls=0,production_data_read=False,build=False),ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(dict(passed=len(checks),checks=checks,unhandled_errors=errors,font=ui_font().family(),paid_calls=0),ensure_ascii=False))

if __name__=='__main__': main()
