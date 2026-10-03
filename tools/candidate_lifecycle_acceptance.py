"""Focused immediate candidate-state checks; no provider request."""
import json,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication,QPushButton
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from app.ui.v2_window import MainWindow
from app.core.services import Workspace
from app.core.creation_flow import CreationFlow
from app.core.agent_candidates import AgentCandidates
from app.providers.contracts import Connection
def main():
    app=QApplication([]); out=ROOT/'docs/evidence/candidate_lifecycle'; out.mkdir(parents=True,exist_ok=True); checks=[]
    def spin():
        end=time.monotonic()+.12
        while time.monotonic()<end: app.processEvents(); time.sleep(.01)
    def check(name,value):
        checks.append(dict(check=name,passed=bool(value)))
        if not value: raise AssertionError(name)
    with tempfile.TemporaryDirectory(prefix='tt_lifecycle_') as temp:
        root=Path(temp); window=MainWindow(Workspace(root/'data'),ROOT/'resources',root/'prefs/preferences.json'); window.show(); window.new_work('novel'); spin(); page=window.creators['novel']; work=window.ensure_work(page); work.edit('他只蒸了十分钟。\n结尾保持。'); work.save(); window.replace_editor(page,work.text); page.set_view(1); window.set_assistant_visible(True)
        service=AgentCandidates(work.store); c=Connection('fixture','模拟状态验收','deepseek','fixture',base_url='https://example.org',max_output=2048,context_limit=65536); window.connections.save(c)
        def candidate():
            flow=CreationFlow(work,ROOT/'resources',window.connections); snapshot=flow.prepare(c,'modify','帮我改写第一句，保留结尾',(0,len('他只蒸了十分钟。')),True)
            result=dict(status='completed',candidate=dict(text='他又多蒸了十分钟。',explanation='模拟候选'),text='模拟候选'); flow.service._save_state(snapshot['task_id'],'completed',result)
            return service.save(snapshot,result)
        cid=candidate(); page.notify('对话／候选已保存；正文尚未采用'); window.assistant.refresh(); spin(); check('pending is visible before adoption','尚未采用' in window.assistant.chat.toPlainText())
        window.show_agent_candidate(cid); spin(); action=next(b for b in window.inline.findChildren(QPushButton) if b.text()=='采用修改'); QTest.mouseClick(action,Qt.MouseButton.LeftButton); spin(); text=window.assistant.chat.toPlainText(); check('adopted history immediately removes pending status','尚未采用' not in text and '已采用并保存正文新版本' in text); check('adopted banner is dismissed',not window.assistant.candidate_box.isVisible()); window.grab().save(str(out/'01-immediate-adopted.png'))
        check('page banner immediately agrees with adoption','已采用修改' in page.banner.text() and '尚未采用' not in page.banner.text())
        window.undo_agent_candidate(cid); spin(); text=window.assistant.chat.toPlainText(); check('undo history is immediate and consistent','已撤销并保存恢复版本' in text and '已采用并保存正文新版本' not in text and '尚未采用' not in text); check('page banner immediately agrees with undo','已撤销修改' in page.banner.text() and '尚未采用' not in page.banner.text()); window.grab().save(str(out/'02-immediate-undone.png'))
        candidate(); work.edit(work.text+'\n手改内容'); work.save(); window.assistant.refresh(); spin(); check('stale candidate is labelled and no adoption banner is offered','已失效' in window.assistant.chat.toPlainText() and '尚未采用' not in window.assistant.chat.toPlainText() and not window.assistant.candidate_box.isVisible()); window.grab().save(str(out/'03-stale.png')); window.close()
    result=dict(checks=checks,passed=len(checks),total=len(checks),network_calls=0,paid_calls=0); (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(result)); return 0
if __name__=='__main__': raise SystemExit(main())
