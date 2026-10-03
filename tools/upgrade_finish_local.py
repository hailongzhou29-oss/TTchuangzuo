"""Finish the already-paid adoption receipt locally; never submits a request."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from app.ui.v2_window import MainWindow
from app.core.services import Workspace
from app.core.agent_candidates import AgentCandidates
from app.core.budget import BudgetBook
from app.storage.connections import ConnectionStore
from app.core.files import write_json
def main():
    out=ROOT/'docs/evidence/upgrade_live_text'; path=out/'results.json'; report=json.loads(path.read_text(encoding='utf-8')); baseline=json.loads((ROOT/'backups/upgrade_round_20261002/baseline.json').read_text(encoding='utf-8'))
    if report['state']!='failed' or report.get('error')!='设定或衍生记录又发生变化，不能直接撤销': raise ValueError('不是本次已确认的本地撤销问题，未处理')
    book=BudgetBook(Path(baseline['budget_root'])); before=book.rows(report['project_id']); app=QApplication([]); window=MainWindow(Workspace(ROOT/'docs/evidence/live_merged/ds_data'),ROOT/'resources',out/'ui_prefs/preferences.json'); window.connections=ConnectionStore(Path(baseline['budget_root'])); window.assistant.refresh_models(); window.open_project(Path(report['project_root'])); window.select_document(report['document_id']); window.show(); window.creators['novel'].set_view(1); window.set_assistant_visible(True); app.processEvents()
    cid=next(r['candidate_id'] for r in report['records'] if r['event']=='adopted'); service=AgentCandidates(window.work.store); expected=service.row(cid)['snapshot']['frozen']['text']; window.undo_agent_candidate(cid); app.processEvents()
    restored=window.work.text==expected and window.work.store.document(window.work.document_id)['text']==expected and '已撤销并保存恢复版本' in window.assistant.chat.toPlainText()
    if not restored: raise ValueError('同一结果的本地撤销未通过')
    window.grab().save(str(out/'06-real-undone.png')); window.close(); app.processEvents(); after=book.rows(report['project_id'])
    if after!=before: raise ValueError('本地完成步骤意外改变账本')
    report.setdefault('previous_failures',[]).append(report.pop('error')); report['checks'].append(dict(check='undo restores original after real inspect and does not submit again',passed=True)); report['records'].append(dict(event='local_repair_completed',network_calls=0,paid_calls=0,ledger_unchanged=True)); report['state']='passed'; write_json(path,report); print(json.dumps(dict(state='passed',local_undo=True,ledger_unchanged=True,after=report['after']))); return 0
if __name__=='__main__': raise SystemExit(main())
