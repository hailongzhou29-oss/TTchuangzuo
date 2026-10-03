"""Native cancellation/reopen evidence, simulated transport and zero paid calls."""
import sys,json,tempfile,time,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from app.core.services import Workspace
from app.providers.contracts import Connection,TextResult
from app.ui.v2_window import MainWindow

class Provider:
    def __init__(self): self.calls=0; self.started=threading.Event(); self.mode='cancel'
    def generate(self,c,secret,messages,cancel,on_text,**kw):
        self.calls+=1; on_text('已收到的讨论草稿。'); self.started.set()
        if self.mode=='fail': return TextResult(text='已收到的讨论草稿。',status='uncertain',accepted=True,error='模拟传输中断，无完整结束标记')
        while not cancel.cancelled: time.sleep(.02)
        return TextResult(text='已收到的讨论草稿。',status='cancelled',accepted=True)

def main():
    app=QApplication([]); out=ROOT/'docs/evidence/upgrade_chat_recovery'; out.mkdir(parents=True,exist_ok=True); checks=[]
    def spin(): app.processEvents(); QTest.qWait(30)
    def wait(window):
        end=time.monotonic()+60
        while window.active_task and time.monotonic()<end: spin()
        check('task finishes without a blocked UI',not window.active_task)
    def check(name,value):
        checks.append(dict(check=name,passed=bool(value)))
        if not value: raise AssertionError(name)
    with tempfile.TemporaryDirectory(prefix='tt_chat_recovery_') as temp:
        root=Path(temp); workspace=Workspace(root/'data'); prefs=root/'prefs/preferences.json'; p=Provider()
        def attach(window):
            window.allow_test_connections=True; window.text_test_provider=p; window.connections.save(Connection('fixture','隔离模拟','deepseek','fixture',base_url='https://example.org',max_output=1024,context_limit=65536,verification=dict(development_test=True))); window.options['default_connection']='fixture'; window.assistant.refresh_models()
        window=MainWindow(workspace,ROOT/'resources',prefs); attach(window); window.show(); window.new_work('novel'); spin(); work=window.ensure_work(window.creators['novel']); body='正文与结尾保持。'; work.edit(body); work.save(); window.replace_editor(window.creators['novel'],body); window.set_assistant_visible(True); project=work.store.root; did=work.document_id; revision=work.revision
        window.assistant.input.setPlainText('只讨论，不改稿：取消也保留这条消息。'); QTest.mouseClick(window.assistant.send_button,Qt.MouseButton.LeftButton); spin(); check('user message persists before model completion','取消也保留这条消息' in window.assistant.chat.toPlainText())
        with work.store.connection() as con: check('user message is durable immediately',bool(con.execute("SELECT 1 FROM messages WHERE role='user'").fetchone()))
        deadline=time.monotonic()+60
        while not p.started.is_set() and window.active_task and time.monotonic()<deadline: spin()
        check('partial response received before cancellation',p.started.is_set())
        QTest.mouseClick(window.assistant.send_button,Qt.MouseButton.LeftButton); wait(window); check('cancellation preserves body and saved revision',work.text==body and work.revision==revision); window.grab().save(str(out/'01-cancelled.png')); window.close(); spin()
        window=MainWindow(workspace,ROOT/'resources',prefs); attach(window); window.open_project(project); window.select_document(did); window.show(); spin(); check('reopen retains cancelled user message and original manuscript','取消也保留这条消息' in window.assistant.chat.toPlainText() and window.work.text==body); p.mode='fail'; window.assistant.input.setPlainText('只讨论，不改稿：模拟传输结束标记缺失。'); QTest.mouseClick(window.assistant.send_button,Qt.MouseButton.LeftButton); spin(); wait(window); check('failure retains user message with no automatic retransmission',p.calls==2 and '模拟传输结束标记缺失' in window.assistant.chat.toPlainText() and window.work.text==body); check('failed task leaves send and input usable',window.assistant.send_button.isEnabled() and window.assistant.input.isEnabled() and not window.active_task); window.grab().save(str(out/'02-failed-reopened.png')); window.close(); spin()
    result=dict(checks=checks,passed=len(checks),total=len(checks),simulated_calls=p.calls,paid_calls=0,transport='simulated interruption; not physical network outage'); (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8'); print(json.dumps(result)); return 0
if __name__=='__main__': raise SystemExit(main())
