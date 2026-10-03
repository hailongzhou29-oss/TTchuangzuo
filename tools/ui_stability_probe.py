"""Read-only, offscreen reproduction of the pre-spec layout event chain."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontDatabase
from app.ui.v2_window import MainWindow
from app.core.services import Workspace
from app.core.files import write_json

def main():
    app=QApplication([]); result=dict(pid=os.getpid(),platform=app.platformName(),steps=[],fonts=[f for f in QFontDatabase.families() if f in ['Microsoft YaHei UI','Microsoft YaHei','SimSun','Segoe UI']])
    output=ROOT/'docs/evidence/ui_stability_before'; output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='tt_ui_probe_') as temporary:
        root=Path(temporary); prefs=root/'settings/preferences.json'; write_json(prefs,dict(restore_last=False,autosave=False))
        window=MainWindow(Workspace(root/'data'),ROOT/'resources',prefs); window.show(); window.new_work('script'); window.resize(1440,900)
        page=window.creators['script']; form=page.script_form
        def settle(): app.processEvents(); QTest.qWait(40); app.processEvents()
        def choose(key,value): form.set_value(key,value); form.changed(key); settle()
        choose('form','form.03'); choose('genre','G02'); form.toggle_basic_more(); choose('carrier','carrier.06')
        result['steps'].append(dict(action='series basic supplement',basic_height=form.basic_card.height(),form_detail_width=form.cells['form_detail'].width(),grid_columns=form.basic_grid.columnCount()))
        window.grab().save(str(output/'series-before.png'))
        choose('view','view.follow'); choose('role','role.01'); choose('role_detail','custom:关联身份')
        positions={k:dict(label_y=form.cells[k].mapTo(page,form.cells[k].rect().topLeft()).y(),control_y=form.fields[k].mapTo(page,form.fields[k].rect().topLeft()).y(),height=form.cells[k].height()) for k in ['role','role_detail','role_name']}
        result['steps'].append(dict(action='custom identity alignment',positions=positions))
        window.grab().save(str(output/'custom-before.png'))
        custom=form.custom['role_detail']; custom.setFocus(); settle()
        with patch.object(form,'reflow',wraps=form.reflow) as reflow,patch.object(form,'layout_cells',wraps=form.layout_cells) as grids:
            for i in range(10): custom.setText('中文输入'+str(i)); settle()
            result['steps'].append(dict(action='ten text edits',reflow_calls=reflow.call_count,grid_rebuild_calls=grids.call_count,focus_retained=app.focusWidget() is custom,scroll=page.settings_scroll.verticalScrollBar().value()))
        window.close(); settle()
    (output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))

if __name__=='__main__': main()
