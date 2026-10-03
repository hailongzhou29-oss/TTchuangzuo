"""Native evidence for viewing and correcting source-bound semantic facts."""
import json,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication,QPushButton
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from app.ui.v2_window import MainWindow
from app.ui.memory_panel import MemoryPanel
from app.core.services import Workspace
from app.core.project_memory import parse_memory,accept_memory
from app.core.knowledge import FactService
def main():
    app=QApplication([]); out=ROOT/'docs/evidence/memory_upgrade'; out.mkdir(parents=True,exist_ok=True); checks=[]
    def spin():
        end=time.monotonic()+.12
        while time.monotonic()<end: app.processEvents(); time.sleep(.01)
    def check(name,value):
        checks.append(dict(check=name,passed=bool(value)))
        if not value: raise AssertionError(name)
    with tempfile.TemporaryDirectory(prefix='tt_memory_ui_') as temp:
        root=Path(temp); window=MainWindow(Workspace(root/'data'),ROOT/'resources',root/'prefs/preferences.json'); window.show(); window.new_work('novel'); spin(); page=window.creators['novel']; work=window.ensure_work(page); source='阿宁右手受伤。\n阿宁是林远的姐姐。\n阿宁锁好了车站大门。\n抽屉里的红钥匙尚未使用。'; work.edit(source); work.save(); window.replace_editor(page,source)
        memory=dict(summary='阿宁受伤并锁门，红钥匙未用。',characters=['阿宁右手受伤'],relationships=['阿宁是林远的姐姐'],events=['锁好车站门'],foreshadow=['红钥匙未使用'],unresolved=['红钥匙用途'],evidence=source.splitlines(),facts=[dict(category=k,content=v.rstrip('。'),entities=['阿宁'],evidence=v) for k,v in zip(['character','relationship','event','foreshadow'],source.splitlines())]); accept_memory(work.store,work.document_id,work.revision,parse_memory(json.dumps(memory),source)); window.open_memory(); spin(); panel=window.inline.findChild(MemoryPanel); check('current project memory and four semantic categories are visible',panel.model_facts.count()==4 and '关系' in panel.summary.toPlainText() and '来源版本' in panel.summary.toPlainText()); window.grab().save(str(out/'01-memory-source.png'))
        panel.model_facts.setCurrentRow(1); QTest.mouseClick(panel.propose_button,Qt.MouseButton.LeftButton); spin(); service=FactService(work.store); fact=service.facts()[0]; check('promotion is candidate with exact source evidence',fact['state']=='candidate' and fact['source_revision']==work.revision and fact['evidence']=='阿宁是林远的姐姐。'); panel.fact_text.setPlainText('阿宁是林远的妹妹'); QTest.mouseClick(panel.revise_button,Qt.MouseButton.LeftButton); spin(); revised=service.get(fact['id']); check('user correction stays candidate and preserves immutable original source',revised['state']=='candidate' and revised['content']=='阿宁是林远的妹妹' and service.versions(fact['id'])[0]['evidence']=='阿宁是林远的姐姐。'); window.grab().save(str(out/'02-corrected-candidate.png'))
        QTest.mouseClick(panel.confirm_button,Qt.MouseButton.LeftButton); spin(); action=next(b for b in panel.findChildren(QPushButton) if b.text()=='确认'); QTest.mouseClick(action,Qt.MouseButton.LeftButton); spin(); check('explicit confirmation activates corrected user fact',service.active(work.document_id)[0]['content']=='阿宁是林远的妹妹'); window.grab().save(str(out/'03-confirmed-fact.png')); window.close(); spin()
    result=dict(checks=checks,passed=len(checks),total=len(checks),network_calls=0,paid_calls=0); (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(result)); return 0
if __name__=='__main__': raise SystemExit(main())
