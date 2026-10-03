"""Focused native wheel boundaries, selection and unsent-draft preservation."""
import sys,json,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication,QTextEdit,QComboBox,QVBoxLayout,QWidget,QScrollArea
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtGui import QWheelEvent,QTextCursor
from PySide6.QtTest import QTest
from app.ui.v2_window import MainWindow
from app.core.services import Workspace
from app.core.context import ChatService

def main():
    app=QApplication([]); checks=[]; out=ROOT/'docs/evidence/upgrade_scroll'; out.mkdir(parents=True,exist_ok=True)
    def spin(): app.processEvents(); QTest.qWait(80)
    def check(name,value):
        checks.append(dict(check=name,passed=bool(value)))
        if not value: raise AssertionError(name)
    def wheel(widget,delta=-120):
        pos=QPoint(10,10); app.sendEvent(widget,QWheelEvent(QPointF(pos),QPointF(widget.mapToGlobal(pos)),QPoint(),QPoint(0,delta),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)); spin()
    with tempfile.TemporaryDirectory(prefix='tt_scroll_') as temp:
        root=Path(temp); window=MainWindow(Workspace(root/'data'),ROOT/'resources',root/'prefs/preferences.json'); window.show(); window.new_work('script'); spin(); page=window.creators['script']; work=window.ensure_work(page); work.edit('正文保持。'); work.save(); window.replace_editor(page,work.text); window.set_assistant_visible(True)
        combo=page.script_form.fields['genre']; old=combo.currentIndex(); scroll=page.settings_scroll.verticalScrollBar().value(); wheel(combo); check('closed combo wheel preserves value and outer scroll',combo.currentIndex()==old and page.settings_scroll.verticalScrollBar().value()==scroll)
        bar=page.script_form.tabs.bar; old=bar.currentIndex(); wheel(bar); check('tab wheel preserves selected tab',bar.currentIndex()==old)
        pane=QWidget(); layout=QVBoxLayout(pane); outer=QScrollArea(); content=QWidget(); col=QVBoxLayout(content); inner=QTextEdit(); inner.setFixedHeight(180); inner.setPlainText('测试长文本\n'*200); col.addWidget(inner); filler=QWidget(); filler.setFixedHeight(1200); col.addWidget(filler); outer.setWidget(content); outer.setWidgetResizable(True); layout.addWidget(outer); window.show_inline('滚动边界验证',pane,page); spin(); outer.verticalScrollBar().setValue(90); inner.verticalScrollBar().setValue(100); before=outer.verticalScrollBar().value(); wheel(inner.viewport()); check('inner scrolling changes only inner position',inner.verticalScrollBar().value()>100 and outer.verticalScrollBar().value()==before)
        inner.verticalScrollBar().setValue(inner.verticalScrollBar().maximum()); wheel(inner.viewport()); check('inner bottom wheel never jumps outer page',outer.verticalScrollBar().value()==before); inner.verticalScrollBar().setValue(0); wheel(inner.viewport(),120); check('inner top wheel never jumps outer page',outer.verticalScrollBar().value()==before); window.close_inline(); spin()
        combo.showPopup(); spin(); popup=combo.choice_popup; view=popup.findChild(QScrollArea)
        from PySide6.QtWidgets import QAbstractItemView
        itemview=popup.findChild(QAbstractItemView); check('choice popup is available',itemview is not None); outer_before=page.settings_scroll.verticalScrollBar().value(); itemview.verticalScrollBar().setValue(itemview.verticalScrollBar().maximum()); wheel(itemview.viewport()); check('popup boundary never scrolls settings page',page.settings_scroll.verticalScrollBar().value()==outer_before); combo.hidePopup(); spin()
        chat=ChatService(work.store); thread=chat.current()
        for i in range(35): chat.append(thread,work.document_id,'writing','assistant',f'可读历史第{i}条。\n'+'长对话测试。'*10,'scroll-'+str(i),'completed')
        window.assistant.refresh(); spin(); browser=window.assistant.chat; cursor=browser.textCursor(); cursor.setPosition(2); cursor.setPosition(8,QTextCursor.MoveMode.KeepAnchor); browser.setTextCursor(cursor); selected=cursor.selectedText(); browser.verticalScrollBar().setValue(50); window.assistant.input.setPlainText('未发送的草稿'); window.assistant.input.setFocus(); spin(); position=browser.verticalScrollBar().value(); focus=app.focusWidget(); window.assistant.append('助手','新增回复不抢阅读位置。'); spin(); check('reply preserves reading scroll selection and input focus',browser.verticalScrollBar().value()==position and browser.textCursor().selectedText()==selected and app.focusWidget() is focus)
        window.assistant.refresh(); spin(); check('history refresh preserves reading scroll selection and unsent input',browser.verticalScrollBar().value()==position and browser.textCursor().selectedText()==selected and window.assistant.input.toPlainText()=='未发送的草稿' and app.focusWidget() is focus); window.grab().save(str(out/'01-reading-position.png')); window.close(); spin()
    result=dict(checks=checks,passed=len(checks),total=len(checks),network_calls=0); (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8'); print(json.dumps(result)); return 0
if __name__=='__main__': raise SystemExit(main())
