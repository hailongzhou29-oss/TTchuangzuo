"""Show saved book results and replay a saved real candidate locally: zero requests."""
import sys,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication,QPushButton,QCheckBox
from PySide6.QtCore import Qt,QPoint
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from app.core.services import Workspace
from app.core.full_book_review import FullBookReview
from app.core.agent_candidates import AgentCandidates
from app.core.creation_flow import CreationFlow
from app.core.budget import BudgetBook
from app.storage.project import ProjectStore
from app.storage.connections import ConnectionStore
from app.providers.contracts import Connection
from app.ui.v2_window import MainWindow

def main():
    out=ROOT/'docs/evidence/upgrade_final_saved_ui'; out.mkdir(parents=True,exist_ok=True); prior=json.loads((ROOT/'docs/evidence/live_merged/ds.json').read_text('utf8')); store=ProjectStore(Path(prior['project_root'])); baseline=json.loads((ROOT/'backups/upgrade_round_20261002/baseline.json').read_text('utf8')); book=BudgetBook(Path(baseline['budget_root'])); before=book.rows(baseline['project_id']); checks=[]
    def check(name,value):
        checks.append(dict(check=name,passed=bool(value)))
        if not value: raise AssertionError(name)
    app=QApplication([]); window=MainWindow(Workspace(ROOT/'docs/evidence/live_merged/ds_data'),ROOT/'resources',out/'prefs/preferences.json'); window.open_project(store.root); window.select_document('3fe9681b061f4a0e935823af85e73665'); window.show(); window.creators['novel'].set_view(1); window.set_assistant_visible(True)
    def spin(): app.processEvents(); QTest.qWait(110)
    spin(); window.select_document('a349eca67d224bbba9e3be7ba8bcbe8e'); window.open_memory(); spin()
    from app.ui.memory_panel import MemoryPanel
    panel=window.inline.findChild(MemoryPanel); check('memory view opens the current chapter and shows four actual saved semantic facts',panel.documents.currentData()==window.work.document_id and panel.model_facts.count()==4); window.grab().save(str(ROOT/'docs/evidence/upgrade_memory_citation_fix/01-real-source-memory.png')); panel.model_facts.scrollToBottom(); panel.summary.verticalScrollBar().setValue(panel.summary.verticalScrollBar().maximum()); spin(); window.grab().save(str(ROOT/'docs/evidence/upgrade_memory_citation_fix/02-real-foreshadow-evidence.png'))
    if '--memory-only' in sys.argv:
        check('memory evidence capture adds no request or ledger row',book.rows(baseline['project_id'])==before); window.close(); print(json.dumps(dict(passed=len(checks),network_calls=0))); return
    window.close_inline(); window.select_document('3fe9681b061f4a0e935823af85e73665'); spin()
    review=FullBookReview(store,ROOT/'resources',window.connections); value=review.get('42596470ed4244d3b6ed6efe5094ffe2'); result=review.result(value); check('saved review has completed five parts and verified synthesis',value['state']=='completed' and len(result['coverage']['completed_parts'])==5 and result['coverage']['completed_characters']==9953 and result['coverage']['cross_chapter_completed'])
    citations=[]
    for i,issue in enumerate(value['synthesis']['contradictions']):
        row=dict(index=i+1,issue=issue['issue'],references=[])
        for side in ('left','right'):
            c=issue[side]; part=value['parts'][c['part_index']]; document=store.document(part['document_id']); exact=c['quote'] in document['text'][part['start']:part['end']]; check(f'issue {i+1} {side} citation is literal in source range',exact); row['references'].append(dict(side=side,title=part['title'],revision=part['revision'],quote=c['quote'],literal_match=exact))
        citations.append(row)
    report=result['text']; (out/'final-cross-chapter-report.md').write_text(report,'utf8')
    lines=['# 已保存整本综合结果的独立核对','', '范围：5/5段，9,953/9,953字。三章合成长篇加两篇独立测试短文。没有重新发送模型请求。','', '| 预置问题 | 模型发现 | 原文核对 |','|---|---|---|','| 右手完好且从未受伤 / 已伤三天并包扎 | 第1项 | 成立，原文引用有效 |','| 姐姐 / 妹妹，出生年份未变 | 第2项 | 成立，原文引用有效 |','| 唯一红钥匙烧毁 / 完好取出且非复制品 | 第3项 | 成立，原文引用有效 |','| 大门锁着 / 敞开且从未上锁 | 第4项 | 成立，原文引用有效 |','| 同一晚19:00的无解释变化 | 第5项 | 对前述矛盾的综合重述，不算第5个独立矛盾 |','', '准确性限制：模型第1项叙述含“第四章”，实际合成长篇只有三章。这是章号表述错误；该项两条程序定位引用正确指向第1章与第2章。保留原模型结果，不静默改写。综合摘要也有含混章号，因此不能把“五条输出”说成“五个完全独立且全无错误的发现”。','', '## 五项原始模型输出与逐字来源','']
    for row in citations:
        lines.extend([f'### {row["index"]}. '+row['issue'],''])
        for c in row['references']: lines.extend([f'{c["title"]}，来源版本 `{c["revision"]}`，逐字引用核对通过：','', '> '+c['quote'],''])
    (out/'seeded-contradictions-audit.md').write_text('\n'.join(lines),'utf8')
    chat=window.assistant.chat; plain=chat.toPlainText(); marker='整本检查：已完成 5/5 段、9953/9953 字。'; check('final completion exists in durable chat',marker in plain)
    def locate(text):
        cursor=chat.document().find(text); check('saved chat contains '+text,bool(not cursor.isNull())); chat.setTextCursor(cursor); chat.ensureCursorVisible(); spin()
    locate(marker); window.grab().save(str(out/'01-final-five-of-five.png')); locate('矛盾：青禾与墨川'); window.grab().save(str(out/'02-final-relationships-key.png')); locate('矛盾：车站大门'); window.grab().save(str(out/'03-final-door-time.png'))
    actual=json.loads((ROOT/'docs/evidence/upgrade_live_text/results.json').read_text('utf8')); event=next(r for r in actual['records'] if r['event']=='adopted'); candidates=AgentCandidates(store); original=candidates.row(event['candidate_id']); window.select_document(original['document_id']); spin(); work=window.work; page=window.creators[work.config['kind']]; page.set_view(1); old=work.text
    check('original manuscript restored before cached response replay',old==original['snapshot']['frozen']['text']); connection=Connection('cached_real','既有真实响应本地复验','deepseek','deepseek-flash',base_url='https://example.org',max_output=4096,context_limit=65536); window.connections.save(connection); flow=CreationFlow(work,ROOT/'resources',window.connections); snap=flow.prepare(connection,'modify','既有真实响应本地复验，无模型请求',(original['snapshot']['target_start'],original['snapshot']['target_end']),True); cached=original['result']; flow.service._save_state(snap['task_id'],'completed',cached); cid=candidates.save(snap,cached); page.notify('对话／候选已保存；正文尚未采用'); window.assistant.refresh(); window.show_agent_candidate(cid); spin(); box=window.inline.findChild(QCheckBox,'confirmCandidateScope')
    if box: QTest.mouseClick(box,Qt.MouseButton.LeftButton,pos=QPoint(8,box.height()//2)); spin()
    action=next(b for b in window.inline.findChildren(QPushButton) if b.text()=='采用修改'); QTest.mouseClick(action,Qt.MouseButton.LeftButton); spin(); check('cached real candidate immediately synchronizes manuscript banner saved status and chat',work.text!=old and '已采用修改' in page.banner.text() and page.saved.text()=='正文已保存' and '尚未采用' not in window.assistant.chat.toPlainText()); window.grab().save(str(out/'04-real-response-adopted-local.png')); window.undo_agent_candidate(cid); spin(); check('cached real candidate undo immediately synchronizes all states',work.text==old and '已撤销修改' in page.banner.text() and '已撤销并保存恢复版本' in window.assistant.chat.toPlainText()); window.grab().save(str(out/'05-real-response-undone-local.png')); check('all evidence work adds no ledger rows or provider requests',book.rows(baseline['project_id'])==before); window.close(); (out/'results.json').write_text(json.dumps(dict(checks=checks,passed=len(checks),total=len(checks),network_calls=0,citations=citations,candidate_source='saved real response, local replay only',accuracy_limits=['first issue incorrectly mentions a fourth chapter','fifth issue overlaps earlier contradictions']),ensure_ascii=False,indent=2),'utf8'); print(json.dumps(dict(passed=len(checks),network_calls=0)))
if __name__=='__main__': main()
