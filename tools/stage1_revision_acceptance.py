"""Focused native UI regression for the user's stage-one screenshot findings."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QPoint,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.core.services import Workspace
from app.ui.v2_window import MainWindow


def main():
    app=QApplication([])
    evidence=ROOT/'docs/evidence/stage1_revision'
    evidence.mkdir(parents=True,exist_ok=True)
    measurements=[]
    with tempfile.TemporaryDirectory(prefix='tt_revision_') as temp:
        root=Path(temp); window=MainWindow(Workspace(root/'data'),ROOT/'resources',root/'settings/preferences.json')
        window.show(); window.new_work('script'); window.resize(1440,900); app.processEvents(); QTest.qWait(100)
        page=window.creators['script']; page.toggle_advanced()
        for i in range(6):
            page.advanced.setCurrentIndex(i); app.processEvents(); QTest.qWait(80)
            body=page.advanced.currentWidget(); heading=page.details_card.layout().itemAt(0).widget()
            measurements.append(dict(tab=page.advanced.tabBar().tabText(i),card=page.details_card.height(),heading_height=heading.height(),tabs_y=page.advanced.y(),tabs_height=page.advanced.height(),body_height=body.height(),body_hint=body.sizeHint().height()))
            if i in (2,4): window.grab().save(str(evidence/f'baseline-tab-{i}.png'))
        page.set_view(1); app.processEvents()
        measurements.append(dict(empty_document_text=page.location.currentText(),empty_document_enabled=page.location.isEnabled()))
        print(json.dumps(measurements,ensure_ascii=False,indent=2))
        (evidence/'baseline.json').write_text(json.dumps(measurements,ensure_ascii=False,indent=2),encoding='utf-8')
        window.close(); app.processEvents()


if __name__=='__main__': main()
