"""One distinct, source-bound refresh; never retry an earlier uncertain request."""
import json,os,sys,time
from pathlib import Path
from dataclasses import replace
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from app.core.services import Workspace
from app.core.budget import BudgetBook
from app.core.tasks import TaskService
from app.core.files import write_json
from app.storage.connections import ConnectionStore
from app.storage.project import ProjectStore
from app.ui.v2_window import MainWindow
from app.ui.memory_panel import MemoryPanel
from merged_live_acceptance import StoredConnections,PRICE

def main():
    repair='--citation-fix' in sys.argv or '--replay-only' in sys.argv
    out=ROOT/'docs/evidence'/('upgrade_memory_citation_fix' if repair else 'upgrade_live_memory'); out.mkdir(parents=True,exist_ok=True); reportfile=out/'results.json'
    if reportfile.exists(): raise SystemExit('Existing receipt: no resubmission.')
    baseline=json.loads((ROOT/'backups/upgrade_round_20261002/baseline.json').read_text('utf8')); prior=json.loads((ROOT/'docs/evidence/live_merged/ds.json').read_text('utf8')); store=ProjectStore(Path(prior['project_root']))
    assert store.metadata()['id']==baseline['project_id']; book=BudgetBook(Path(baseline['budget_root']))
    replay=None
    if repair:
        from app.core.project_memory import parse_memory
        original_receipt=json.loads((ROOT/'docs/evidence/upgrade_live_memory/results.json').read_text('utf8')); task=TaskService(store,ROOT/'resources',ConnectionStore(out/'unused')).get(original_receipt['task_id']); frozen=task['snapshot']['frozen']['text']; original_value=json.loads(task['result']['text']); parsed=parse_memory(task['result']['text'],frozen)
        assert len(parsed['evidence_resolutions'])==1 and all(f['evidence'] in frozen for f in parsed['facts'])
        assert all({k:v for k,v in a.items() if k!='evidence'}=={k:v for k,v in b.items() if k!='evidence'} for a,b in zip(original_value['facts'],parsed['facts']))
        replay=dict(state='passed',original_task=task['id'],changed_only_citation=True,semantic_fields_unchanged=all(parsed[k]==original_value[k] for k in ('summary','characters','relationships','events','foreshadow','unresolved')),resolutions=parsed['evidence_resolutions'],network_calls=0)
        write_json(out/'saved_response_replay.json',replay)
        if '--replay-only' in sys.argv: print(json.dumps(replay,ensure_ascii=True)); return 0
    def budget():
        rows=[r for r in book.rows(baseline['project_id']) if r['state']!='released']; total=sum((Decimal(r['amount']) for r in rows),Decimal(0)); return dict(cumulative_cny=str(total),calls=len(rows),unknown=[r['id'] for r in rows if r['state'] in {'reserved','unconfirmed'}])
    before=budget(); assert not before['unknown'] and Decimal(before['cumulative_cny'])<Decimal('9.8')
    source=ConnectionStore(Path(os.environ['LOCALAPPDATA'])/'TTChuangzuo'); original=next(c for c in source.all() if c.provider=='deepseek' and c.enabled); assert original.model=='deepseek-flash'
    connections=StoredConnections(Path(baseline['budget_root']),source); connection=replace(original,pricing=PRICE,max_output=4096,context_limit=65536,timeout=120,json_mode=True); connections.save(connection)
    report=dict(state='started',before=before,checks=[],distinct_operation='one source-bound semantic refresh after deterministic citation fix' if repair else 'one source-bound semantic refresh',saved_response_replay=replay,previous_uncertain_task_not_retried='53adf8e3b60440d29e4e41cf40ae6ce9'); write_json(reportfile,report)
    app=QApplication([]); window=MainWindow(Workspace(ROOT/'docs/evidence/live_merged/ds_data'),ROOT/'resources',out/'prefs/preferences.json'); window.connections=connections; window.options['default_connection']=connection.id; window.assistant.refresh_models(); window.open_project(store.root); window.select_document('a349eca67d224bbba9e3be7ba8bcbe8e'); window.show()
    def spin(): app.processEvents(); QTest.qWait(30)
    def check(name,value):
        report['checks'].append(dict(check=name,passed=bool(value))); write_json(reportfile,report)
        if not value: raise AssertionError(name)
    try:
        spin(); work=window.work; body,revision=work.text,work.revision; window.open_memory(); spin(); panel=window.inline.findChild(MemoryPanel); QTest.mouseClick(panel.refresh_button,Qt.MouseButton.LeftButton); spin(); active=window.active_task
        check('native button launches exactly one production memory request',active is not None and active['snapshot'].get('memory_refresh') and not hasattr(window,'text_test_provider')); task_id=active['snapshot']['task_id']; report['task_id']=task_id; write_json(reportfile,report)
        deadline=time.monotonic()+140
        while window.active_task and time.monotonic()<deadline: spin()
        if window.active_task: window.stop_task(); raise TimeoutError('No automatic retry after deadline')
        result=TaskService(store,ROOT/'resources',connections).get(task_id)['result']; report.update(status=result['status'],usage=result['usage'],error=result.get('error')); write_json(reportfile,report)
        check('production response completed',result['status']=='completed')
        record=panel.memory.refresh().get(work.document_id,{})
        check('four semantic categories and literal evidence accepted',all(record.get(k) for k in ('characters','relationships','events','foreshadow')) and {f['category'] for f in record.get('facts',[])}=={'character','relationship','event','foreshadow'} and all(f['evidence'] in body for f in record['facts']))
        check('refresh leaves saved manuscript and revision unchanged',work.text==body and work.revision==revision and store.document(work.document_id)['text']==body)
        check('one new settled ledger row without uncertainty',budget()['calls']==before['calls']+1 and not budget()['unknown']); report['memory']=record; window.grab().save(str(out/'01-real-source-memory.png')); report['state']='passed'
    except Exception as exc: report.update(state='failed',error=str(exc)); print(type(exc).__name__,str(exc),flush=True)
    finally:
        report['after']=budget(); write_json(reportfile,report)
        if not window.active_task: window.close()
    print(json.dumps(dict(state=report['state'],after=report['after']))); return int(report['state']!='passed')
if __name__=='__main__': raise SystemExit(main())
