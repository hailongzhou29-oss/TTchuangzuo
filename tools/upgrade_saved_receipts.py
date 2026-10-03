"""Inspect already saved responses only; no provider invocation or retransmission."""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from app.core.services import Workspace
from app.core.tasks import TaskService
from app.storage.project import ProjectStore
from app.storage.connections import ConnectionStore
from app.ui.v2_window import MainWindow
from app.ui.memory_panel import MemoryPanel
def main():
    out=ROOT/'docs/evidence/upgrade_live_memory'; reportfile=out/'results.json'; report=json.loads(reportfile.read_text('utf8')); prior=json.loads((ROOT/'docs/evidence/live_merged/ds.json').read_text('utf8')); store=ProjectStore(Path(prior['project_root'])); task=TaskService(store,ROOT/'resources',ConnectionStore(out/'unused_preferences')).get(report['task_id']); snapshot=task['snapshot']; value=json.loads(task['result']['text']); source=snapshot['frozen']['text']; bad=[f for f in value['facts'] if f['evidence'] not in source]; document=store.document(snapshot['target_id']); report['invalid_evidence']=bad; report['model_categories_present']={k:bool(value[k]) for k in ('characters','relationships','events','foreshadow')}; report['manuscript_unchanged']=document['text']==source and document['head']==snapshot['base_revision']; report['model_memory_not_accepted']=store.setting('v2_memories',{}).get(snapshot['target_id'],{}).get('method')=='当前原文自动节选'; report['saved_response_inspection_only']=True; report['error']='模型事实引用改了标点，未逐字匹配原文，完整语义记忆被拒绝；没有重发。'; report['raw_model_response']=value
    app=QApplication([]); window=MainWindow(Workspace(ROOT/'docs/evidence/live_merged/ds_data'),ROOT/'resources',out/'inspect_prefs/preferences.json'); window.open_project(store.root); window.select_document(snapshot['target_id']); window.show(); window.open_memory(); app.processEvents(); panel=window.inline.findChild(MemoryPanel); index=panel.documents.findData(snapshot['target_id']); panel.documents.setCurrentIndex(index); window.statusBar().showMessage(report['error']); app.processEvents(); window.grab().save(str(out/'01-real-memory-rejected.png')); window.close(); reportfile.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    bookfile=ROOT/'docs/evidence/upgrade_live_book/results.json'; book=json.loads(bookfile.read_text('utf8')); book['stage_states']=dict(cross_chapter_review='passed',later_discussion_memory='failed_uncertain_no_retransmission',new_independent_refresh='failed_literal_evidence_validation'); book['state']='partial'; bookfile.write_text(json.dumps(book,ensure_ascii=False,indent=2),'utf8'); print(json.dumps(dict(invalid_quotes=len(bad),unchanged=report['manuscript_unchanged'],accepted=not report['model_memory_not_accepted'],network_calls=0)))
if __name__=='__main__': main()
