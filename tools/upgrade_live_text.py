"""Authorized native production-path requests, sharing the original CNY10 ledger."""
import json,os,sys,time
from pathlib import Path
from dataclasses import replace
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication,QPushButton,QCheckBox
from PySide6.QtCore import Qt,QPoint
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from app.core.services import Workspace
from app.core.work_context import CurrentWork
from app.core.selection import selection
from app.core.budget import BudgetBook
from app.core.agent_candidates import AgentCandidates
from app.core.files import write_json,digest
from app.storage.project import ProjectStore
from app.storage.connections import ConnectionStore
from app.providers.contracts import redact
from app.core.tasks import TaskService
from app.ui.v2_window import MainWindow
from merged_live_acceptance import StoredConnections,PRICE

def main():
    out=ROOT/'docs/evidence/upgrade_live_text'; out.mkdir(parents=True,exist_ok=True); reportfile=out/'results.json'
    if reportfile.exists(): raise SystemExit('已存在本轮真实请求记录，不重复提交；先核对原记录。')
    baseline=json.loads((ROOT/'backups/upgrade_round_20261002/baseline.json').read_text(encoding='utf-8')); prior=json.loads((ROOT/'docs/evidence/live_merged/ds.json').read_text(encoding='utf-8')); store=ProjectStore(Path(prior['project_root'])); project_id=store.metadata()['id']
    if project_id!=baseline['project_id']: raise ValueError('原累计预算项目不匹配，未提交')
    book=BudgetBook(Path(baseline['budget_root']))
    def budget():
        rows=book.rows(project_id); unknown=[r['id'] for r in rows if r['state'] in {'reserved','unconfirmed'}]; total=sum((Decimal(r['amount']) for r in rows if r['state']!='released'),Decimal(0)); return dict(cumulative_cny=str(total),remaining_cny=str(Decimal('10')-total),unknown=unknown,cumulative_calls=len([r for r in rows if r['state']!='released']))
    before=budget()
    if before['unknown'] or Decimal(before['remaining_cny'])<Decimal('.2'): raise ValueError('原费用未知或剩余预算不足，未提交')
    source=ConnectionStore(Path(os.environ['LOCALAPPDATA'])/'TTChuangzuo'); original=next(c for c in source.all() if c.provider=='deepseek' and c.enabled)
    if original.model!='deepseek-flash': raise ValueError('实际模型与已核验价表不符，未提交')
    report=dict(state='started',synthetic_project=True,project_id=project_id,cumulative_cap_cny='10',before=before,records=[],checks=[],production_provider=True)
    write_json(reportfile,report)
    def record(**value): report['records'].append(value); report['after']=budget(); write_json(reportfile,report); print(json.dumps(value,ensure_ascii=True),flush=True)
    def check(name,value):
        report['checks'].append(dict(check=name,passed=bool(value))); write_json(reportfile,report)
        if not value: raise AssertionError(name)
    app=QApplication([]); window=None
    def spin(ms=90):
        end=time.monotonic()+ms/1000
        while time.monotonic()<end: app.processEvents(); time.sleep(.01)
    try:
        connections=StoredConnections(Path(baseline['budget_root']),source); c=replace(original,max_output=4096,context_limit=65536,timeout=120,json_mode=True); c=replace(c,pricing=PRICE); connections.save(c)
        store.set_setting('budget_settings',dict(monetary_limits=dict(currency='CNY',task_amount='1',project_amount='10')))
        config=selection('novel'); config.update(words=120,chapters=1,chapter_words=120)
        did=store.add_document('生产路径合成蒸汽测试',kind='小说'); store.set_setting('v2_document:'+did,True); store.set_setting('v2_kind','novel'); store.set_setting('v2_selection',config); store.set_setting('v2_last_document',did)
        work=CurrentWork.load(store,did,config); first='他只蒸了十分钟。'; body=first+'\n阿宁：火候不能乱。\n窗外下着雨。\n结尾保持。'; work.edit(body); work.save(); report['document_id']=did; report['project_root']=str(store.root); write_json(reportfile,report)
        workspace=Workspace(ROOT/'docs/evidence/live_merged/ds_data'); prefs=out/'ui_prefs/preferences.json'; window=MainWindow(workspace,ROOT/'resources',prefs); window.connections=connections; window.options['default_connection']=c.id; window.assistant.refresh_models(); window.open_project(store.root); window.select_document(did); window.show(); spin(); page=window.creators['novel']; page.set_view(1); window.set_assistant_visible(True); spin(); work=window.work
        check('production provider is used without fixture hook',not hasattr(window,'text_test_provider'))
        def send(instruction):
            if budget()['unknown']: raise ValueError('有未对账费用，停止下一请求')
            window.assistant.input.setPlainText(instruction); QTest.mouseClick(window.assistant.send_button,Qt.MouseButton.LeftButton); spin(20)
            active=window.active_task
            if not active: raise ValueError('生产任务没有启动，未重复发送')
            snapshot=active['snapshot']; record(event='submitted',task_id=snapshot['task_id'],intent=snapshot['v2_task'],target_id=snapshot['target_id'],start=snapshot['target_start'],end=snapshot['target_end'],instruction=instruction,model=c.model)
            deadline=time.monotonic()+135
            while window.active_task and time.monotonic()<deadline: spin(30)
            if window.active_task: window.stop_task(); raise TimeoutError('真实请求等待超时，不自动重发')
            result=TaskService(store,ROOT/'resources',connections).get(snapshot['task_id'])['result']; record(event='result',task_id=snapshot['task_id'],status=result['status'],usage=result['usage'],used_calls=result['used_calls'],request_id=result.get('request_id'),memory_updated=bool(result.get('semantic_memory')),error=result.get('error'))
            if result['status']!='completed' or budget()['unknown']: raise ValueError('任务未完成或费用未确认，停止后续请求')
            return snapshot,result
        cursor=page.editor.textCursor(); cursor.setPosition(0); cursor.setPosition(len(first),QTextCursor.MoveMode.KeepAnchor); page.editor.setTextCursor(cursor)
        snapshot,result=send('请帮我改写已选这一句，让他多蒸了十分钟；只改这里，保留结尾，台词不动。只输出所需改文，不调用工具。')
        check('natural production rewrite uses frozen selected range',snapshot['v2_task']=='modify' and snapshot['target_start']==0 and snapshot['target_end']==len(first)); candidates=AgentCandidates(store); rows=[r for r in candidates.pending() if r['document_id']==did]; check('actual model response is pending with original unchanged',len(rows)==1 and work.text==body and window.assistant.candidate_button.isVisible()); cid=rows[0]['id']; window.grab().save(str(out/'01-real-pending.png'))
        QTest.mouseClick(window.assistant.candidate_button,Qt.MouseButton.LeftButton); spin(); window.grab().save(str(out/'02-real-compare.png')); action=next(b for b in window.inline.findChildren(QPushButton) if b.text()=='采用修改'); confirm=window.inline.findChild(QCheckBox,'confirmCandidateScope')
        if confirm is not None: QTest.mouseClick(confirm,Qt.MouseButton.LeftButton,pos=QPoint(8,confirm.height()//2)); spin()
        old_revision=work.revision; QTest.mouseClick(action,Qt.MouseButton.LeftButton); spin(); adopted=work.text
        check('adoption preserves outside range ending and dialogue',adopted!=body and adopted.endswith(body[len(first):]) and '阿宁：火候不能乱。' in adopted and adopted.endswith('结尾保持。')); check('new revision is saved and immediate history is consistent',work.revision!=old_revision and store.document(did)['text']==adopted and '尚未采用' not in window.assistant.chat.toPlainText() and '已采用并保存正文新版本' in window.assistant.chat.toPlainText()); window.grab().save(str(out/'03-real-adopted.png')); record(event='adopted',body_hash=digest(adopted),body=adopted,revision=work.revision,candidate_id=cid)
        window.close(); spin(); window=MainWindow(workspace,ROOT/'resources',prefs); window.connections=connections; window.options['default_connection']=c.id; window.assistant.refresh_models(); window.open_project(store.root); window.select_document(did); window.show(); spin(); page=window.creators['novel']; page.set_view(1); window.set_assistant_visible(True); spin(); work=window.work; check('real adopted body survives reopen',work.text==adopted); window.grab().save(str(out/'04-real-reopened.png'))
        versions=len(store.revisions(did)); snap,result=send('只检查刚才这段故事，确认蒸了多久、台词与结尾是否保留；不修改、不续写。两句以内，不调用工具。'); check('real inspect preserves manuscript and revision count',snap['v2_task']=='inspect' and work.text==adopted and len(store.revisions(did))==versions); window.grab().save(str(out/'05-real-inspect.png')); record(event='inspection_reply',text=result['candidate']['text'])
        window.undo_agent_candidate(cid); spin(); check('undo restores original after real inspect',work.text==body and '已撤销并保存恢复版本' in window.assistant.chat.toPlainText()); window.grab().save(str(out/'06-real-undone.png')); window.close(); spin(); window=None; report['state']='passed'
    except Exception as exc: report['state']='failed'; report['error']=redact(str(exc)); print(json.dumps(dict(state='failed',error=report['error']),ensure_ascii=True),flush=True)
    finally: report['after']=budget(); write_json(reportfile,report)
    return int(report['state']!='passed')
if __name__=='__main__': raise SystemExit(main())
