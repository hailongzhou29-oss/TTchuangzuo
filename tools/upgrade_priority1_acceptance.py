"""Actual native send/adopt/reopen UI; isolated data and simulated, unpaid text."""
import json,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication,QPushButton,QCheckBox
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtGui import QTextCursor,QWheelEvent
from PySide6.QtTest import QTest
from app.ui.v2_window import MainWindow
from app.core.services import Workspace
from app.core.agent_candidates import AgentCandidates
from app.providers.contracts import Connection,TextResult

class Provider:
    calls=0
    def generate(self,c,secret,messages,cancel,on_text,**options):
        self.calls+=1
        text='他又多蒸了十分钟。'
        on_text(text)
        return TextResult(text=text,status='completed',model=c.model,accepted=True)

def main():
    app=QApplication([]); checks=[]; out=ROOT/'docs/evidence/upgrade_priority1'
    if '--output' in sys.argv: out=Path(sys.argv[sys.argv.index('--output')+1]).resolve()
    out.mkdir(parents=True,exist_ok=True)
    def spin(ms=100):
        end=time.monotonic()+ms/1000
        while time.monotonic()<end: app.processEvents(); time.sleep(.01)
    def check(name,value):
        checks.append(dict(check=name,passed=bool(value)))
        if not value: raise AssertionError(name)
    with tempfile.TemporaryDirectory(prefix='tt_upgrade_native_') as temp:
        root=Path(temp); prefs=root/'prefs/preferences.json'; workspace=Workspace(root/'data')
        window=MainWindow(workspace,ROOT/'resources',prefs); provider=Provider(); window.allow_test_connections=True; window.text_test_provider=provider
        c=Connection('upgrade_fixture','模拟改写验收','deepseek','fixture-only',base_url='https://example.org',context_limit=65536,max_output=2048,verification=dict(development_test=True))
        window.connections.save(c); window.options['default_connection']=c.id; window.assistant.refresh_models(); window.show(); window.new_work('novel'); spin()
        page=window.creators['novel']; work=window.ensure_work(page); first='他只蒸了十分钟。'; base=first+'\n窗外下着雨。\n结尾保持。'; work.edit(base); work.save(); original_head=work.revision; project=work.store.root
        window.replace_editor(page,base); page.set_view(1); window.set_assistant_visible(True); spin()
        cursor=page.editor.textCursor(); cursor.setPosition(0); cursor.setPosition(len(first),QTextCursor.MoveMode.KeepAnchor); page.editor.setTextCursor(cursor)
        window.assistant.input.setPlainText('请帮我改写已选这一句，让他多蒸了十分钟；只改这里，保留结尾。')
        QTest.mouseClick(window.assistant.send_button,Qt.MouseButton.LeftButton); spin(20)
        if window.active_task: check('natural send freezes modify intent and exact selection',window.active_task['snapshot']['v2_task']=='modify' and window.active_task['snapshot']['target_end']==len(first))
        deadline=time.monotonic()+15
        while window.active_task and time.monotonic()<deadline: spin(30)
        check('actual send completes with one simulated call',window.active_task is None and provider.calls==1)
        pending=AgentCandidates(work.store).pending(); check('raw reply leaves manuscript unchanged and exposes candidate',len(pending)==1 and work.text==base and window.assistant.candidate_button.isVisible())
        cid=pending[0]['id']; window.grab().save(str(out/'01-visible-pending.png'))
        window.close(); spin(); window=MainWindow(workspace,ROOT/'resources',prefs); window.open_project(project); window.show(); spin(); work=window.work; page=window.creators['novel']; page.set_view(1); window.set_assistant_visible(True); spin()
        check('pending candidate and unchanged body survive reopen',work.text==base and window.assistant.candidate_button.isVisible())
        QTest.mouseClick(window.assistant.candidate_button,Qt.MouseButton.LeftButton); spin()
        action=next(b for b in window.inline.findChildren(QPushButton) if b.text()=='采用修改'); confirm=window.inline.findChild(QCheckBox,'confirmCandidateScope')
        check('unstructured replacement requires explicit scope confirmation',confirm is not None and not action.isEnabled())
        window.grab().save(str(out/'02-review-required.png')); QTest.mouseClick(confirm,Qt.MouseButton.LeftButton,pos=QPoint(8,confirm.height()//2)); spin(); check('scope checkbox enables adoption',confirm.isChecked() and action.isEnabled()); QTest.mouseClick(action,Qt.MouseButton.LeftButton); spin()
        expected='他又多蒸了十分钟。'+base[len(first):]
        check('adoption updates only selected sentence and saves new head',work.text==expected and work.revision!=original_head and work.store.document(work.document_id)['text']==expected)
        check('saved body status and candidate dismissal are explicit',page.saved.text()=='正文已保存' and not window.assistant.candidate_box.isVisible())
        window.grab().save(str(out/'03-adopted-saved.png')); window.close(); spin(); window=MainWindow(workspace,ROOT/'resources',prefs); window.open_project(project); window.show(); spin(); work=window.work
        check('adopted manuscript survives second reopen',work.text==expected)
        window.grab().save(str(out/'04-reopened-saved.png')); window.undo_agent_candidate(cid); spin(); check('undo restores original and persists another revision',work.text==base and work.store.document(work.document_id)['text']==base); window.grab().save(str(out/'05-undone.png'))
        window.new_work('script'); spin(); page=window.creators['script']; form=page.script_form
        for width,height in [(1280,800),(800,650)]:
            window.resize(width,height); window.set_assistant_visible(False); spin(); bar=form.tabs.bar; page.settings_scroll.ensureWidgetVisible(bar); spin(); before=[bar.tabRect(i) for i in range(bar.count())]; index=bar.currentIndex()
            for delta in [QPoint(0,120),QPoint(0,-120),QPoint(120,0),QPoint(-120,0)]:
                pos=bar.rect().center(); wheel=QWheelEvent(QPointF(pos),QPointF(bar.mapToGlobal(pos)),QPoint(),delta,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.ScrollUpdate,False); app.sendEvent(bar,wheel); spin(20)
            check(f'tab wheel keeps selection and coordinates at width {width}',bar.currentIndex()==index and before==[bar.tabRect(i) for i in range(bar.count())])
            target=(index+1)%bar.count(); QTest.mouseClick(bar,Qt.MouseButton.LeftButton,pos=bar.tabRect(target).center()); spin(); check(f'explicit tab click remains available at width {width}',bar.currentIndex()==target)
        window.close(); spin()
    result=dict(checks=checks,passed=sum(x['passed'] for x in checks),total=len(checks),network_calls=0,paid_calls=0,provider='simulated',physical_dpr=app.primaryScreen().devicePixelRatio())
    (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(result,ensure_ascii=True)); return 0
if __name__=='__main__': raise SystemExit(main())
