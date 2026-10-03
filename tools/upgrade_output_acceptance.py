"""Focused native export scope and flat versioned outputs, no provider calls."""
import sys,json,tempfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication,QFileDialog
from app.core.services import Workspace
from app.core.work_context import CurrentWork
from app.core.output_files import OutputFiles,CATEGORIES
from app.ui.v2_window import MainWindow

def main():
    app=QApplication([]); checks=[]; out=ROOT/'docs/evidence/upgrade_output'; out.mkdir(parents=True,exist_ok=True)
    def check(name,value):
        checks.append(dict(check=name,passed=bool(value)))
        if not value: raise AssertionError(name)
    with tempfile.TemporaryDirectory(prefix='tt_output_') as temp:
        root=Path(temp); window=MainWindow(Workspace(root/'data'),ROOT/'resources',root/'prefs/preferences.json'); window.new_work('novel'); page=window.creators['novel']; first=window.ensure_work(page); first.edit('第一章正文。'); first.save(); window.replace_editor(page,first.text); store=first.store; second_id=store.add_document('第二章 后续',kind='小说'); second=CurrentWork.load(store,second_id,first.config); second.edit('第二章正文。'); second.save(); outline=store.add_document('大纲',kind='outline'); plan=CurrentWork.load(store,outline,first.config); plan.edit('技术规划与检查备注，不属于正式正文。'); plan.save(); store.set_setting('technical_notes','模型诊断与提示词记录，不属于正式正文。'); window.select_document(second_id); app.processEvents(); chosen=root/'exports/当前.md'
        with patch.object(QFileDialog,'getSaveFileName',return_value=(str(chosen),'')): saved=window.export_work('md')
        check('current chapter export includes only selected manuscript',saved.read_text('utf8')=='第二章正文。')
        with patch.object(QFileDialog,'getSaveFileName',return_value=(str(chosen),'')): whole=window.export_work('md',whole_book=True)
        text=whole.read_text('utf8'); check('whole book uses actual chapter order and excludes outline and notes',text=='第一章正文。\n\n第二章正文。'); check('versioned export preserves earlier file',saved!=whole and saved.read_text('utf8')=='第二章正文。')
        output=OutputFiles(root/'作品'); [output.folder(k) for k in CATEGORIES]; output.write('小说','书名',b'v1'); output.write('小说','书名',b'v2'); output.write('图片','封面',b'image',extension='png'); check('exactly three flat category folders',{p.name for p in output.root.iterdir()}==set(CATEGORIES) and not any(p.is_dir() for k in CATEGORIES for p in output.folder(k).iterdir())); check('old project data and saved chapter selection remain unchanged',store.document(first.document_id)['text']=='第一章正文。' and store.document(second_id)['text']=='第二章正文。' and window.work.document_id==second_id); window.close()
    result=dict(checks=checks,passed=len(checks),total=len(checks),paid_calls=0); (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8'); print(json.dumps(result)); return 0
if __name__=='__main__': raise SystemExit(main())
