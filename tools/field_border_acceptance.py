"""Focused field clipping regression; isolated data and actual rendered pixels."""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--visible',action='store_true')
args=parser.parse_args()
if not args.visible: os.environ['QT_QPA_PLATFORM']='offscreen'
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QPoint,Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app.core.files import write_json
from app.core.services import Workspace
from app.ui.v2_window import MainWindow

def main():
    app=QApplication([])
    folder=ROOT/'docs/evidence'/('field_borders_visible' if args.visible else 'field_borders_offscreen')
    folder.mkdir(parents=True,exist_ok=True)
    checks=[]
    def check(name,value,**detail): checks.append(dict(check=name,passed=bool(value),**detail))
    with tempfile.TemporaryDirectory(prefix='tt_field_borders_') as temporary:
        root=Path(temporary)
        write_json(root/'preferences.json',dict(restore_last=False,autosave=False,reduce_motion=True))
        window=MainWindow(Workspace(root/'data'),ROOT/'resources',root/'preferences.json')
        window.show(); window.new_work('script')
        if args.visible: window.raise_(); window.activateWindow()
        page=window.creators['script']; form=page.script_form
        def capture(name,keys):
            QTest.qWait(220); app.processEvents()
            pixmap=window.grab(); pixmap.save(str(folder/(name+'.png')))
            image=pixmap.toImage(); dpr=pixmap.devicePixelRatio()
            for key in keys:
                field=form.fields[key]
                control=getattr(field,'control',field)
                cell=form.cells[key]
                check(name+' parent contains '+key,field.y()+field.height()<=cell.height(),cell_height=cell.height(),control_bottom=field.y()+field.height())
                origin=control.mapTo(window,QPoint())
                left=round((origin.x()+control.width()*.3)*dpr)
                right=round((origin.x()+control.width()*.7)*dpr)
                bottom=round((origin.y()+control.height())*dpr)-1
                ratios=[]
                for y in range(bottom-2,bottom+1):
                    if not 0<=y<image.height(): continue
                    count=sum(min(image.pixelColor(x,y).red(),image.pixelColor(x,y).green(),image.pixelColor(x,y).blue())<220 for x in range(left,right))
                    ratios.append(count/max(1,right-left))
                check(name+' rendered bottom border '+key, bool(ratios) and max(ratios)>.7,bottom_row_dark_ratios=ratios,logical_origin=[origin.x(),origin.y()],control_size=[control.width(),control.height()],dpr=dpr)
            return pixmap
        keys=['form','genre','subgenres','duration_label','mode','language','view','carrier','narrative']
        pixmap=capture('01-default-settings-fixed',keys)
        # A crop of the running window makes the complete field borders easy to inspect.
        for name,card in [('02-basic-card-fixed',form.basic_card),('03-presentation-card-fixed',form.presentation_card)]:
            origin=card.mapTo(window,QPoint()); dpr=pixmap.devicePixelRatio()
            pixmap.copy(round(origin.x()*dpr),round(origin.y()*dpr),round(card.width()*dpr),round(card.height()*dpr)).save(str(folder/(name+'.png')))
        form.set_value('view','view.follow'); form.changed('view'); form.toggle_presentation()
        form.set_value('role_detail','custom:边框核对'); form.changed('role_detail'); QTest.qWait(220)
        page.settings_scroll.ensureWidgetVisible(form.custom['role_detail'])
        capture('04-custom-field-fixed',['role','role_detail','role_name'])
        window.resize(720,720); window.set_assistant_visible(False); page.settings_scroll.verticalScrollBar().setValue(0)
        capture('05-narrow-settings-fixed',['form','genre','subgenres','duration_label','mode','language'])
        window.close(); QTest.qWait(100)
    result=dict(platform=app.platformName(),dpr=app.devicePixelRatio(),checks=checks,passed=sum(c['passed'] for c in checks),total=len(checks))
    (folder/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=result['passed'],total=result['total'],result=str(folder/'results.json'))))
    for item in checks:
        if not item['passed']: print('FAIL',json.dumps(item))
    return 0 if result['passed']==result['total'] else 1

if __name__=='__main__': raise SystemExit(main())
