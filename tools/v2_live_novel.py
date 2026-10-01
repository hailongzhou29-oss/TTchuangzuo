"""Three short chapters via the actual software channel, with a source edit between 2 and 3."""
import json
import os
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from app.ui.v2_window import MainWindow
from app.core.services import Workspace
from app.core.files import digest
from tools.v2_live_acceptance import LiveConnections

def main():
    evidence=ROOT/'docs'/'evidence'/'v2_novel'; evidence.mkdir(parents=True,exist_ok=True)
    app=QApplication([]); window=MainWindow(Workspace(evidence/'data'),ROOT/'resources',evidence/'preferences.json')
    window.connections=LiveConnections(Path(os.environ['LOCALAPPDATA'])/'TTChuangzuo'); window.assistant.refresh_models(); window.show(); app.processEvents(); records=[]
    def wait():
        end=time.monotonic()+350
        while window.active_task and time.monotonic()<end: app.processEvents(); time.sleep(.02)
        if window.active_task: window.stop_task(); raise TimeoutError('章节测试超时，已停止本地等待')
        with window.work.store.connection() as con: row=con.execute('SELECT result,snapshot FROM tasks ORDER BY rowid DESC LIMIT 1').fetchone()
        result=json.loads(row['result']); snapshot=json.loads(row['snapshot']); records.append(dict(status=result['status'],model=snapshot['model_selection']['model'],usage=result.get('usage'),task=snapshot['v2_task']))
        if result['status']!='completed': raise AssertionError(result.get('error') or result['status'])
        return snapshot
    try:
        window.new_work('novel'); page=window.current_page(); connection=next(c for c in window.connections.all() if c.provider=='deepseek' and c.enabled); window.assistant.model.setCurrentIndex(window.assistant.model.findData(connection.id))
        page.fields['length'].setCurrentText('长篇连载'); page.fields['chapters'].setValue(3); page.fields['chapter_words'].setValue(600); page.fields['genre'].setCurrentIndex(page.fields['genre'].findData('G04')); page.idea.setPlainText('修理员阿宁与值班员林远在旧车站寻找一封信的来历。三章，人物名字固定，每章约600字，不写超自然设定。'); window.generate(page); wait()
        store=window.work.store; first=window.work.document_id; first_original=window.work.text
        if '阿宁' not in first_original: raise AssertionError('第一章没有使用固定人物')
        window.next_chapter(); wait(); second=window.work.document_id
        window.select_document(first); page.editor.setPlainText(window.work.text.replace('阿宁','小雨')); window.save_work()
        store.set_setting('v2_settings',{'人物与关系':dict(text='作者已将原阿宁正式更名为小雨。当前有效名字为小雨；林远不改。第二章旧稿的阿宁指同一人，第三章不得再用旧名字。',source='用户编辑',source_revision=window.work.revision)})
        window.select_document(second); snapshot=None; window.next_chapter('续写第三章，以第一章当前修订和用户人物设定为准'); snapshot=wait()
        third=window.work.text
        if '小雨' not in third or '阿宁' in third: raise AssertionError('第三章未遵循当前人物设定')
        context=json.loads(snapshot['messages'][1]['content'].split('\n',1)[1])
        if '小雨' not in context['previous_chapters'][0]['text'] or context['planning'].get('characters'): raise AssertionError('第三章请求没有失效旧人物摘要')
        for i,d in enumerate(store.documents(),1): (evidence/f'第{i}章.md').write_text(store.document(d['id'])['text'],encoding='utf-8')
        records.append(dict(test='连续三章与前文修改失效',status='passed',chapter_count=len(store.documents()),third_hash=digest(third),old_character_summary_removed=True))
        store.set_setting('system_test_project',True); store.update_project(status='archived'); window.grab().save(str(evidence/'第三章.png')); print(json.dumps(dict(passed=True,checks=records),ensure_ascii=False))
    except Exception as exc:
        records.append(dict(status='failed',error=str(exc))); print(json.dumps(dict(passed=False,checks=records),ensure_ascii=False)); raise
    finally:
        (evidence/'novel_results.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        if not window.active_task: window.close()

if __name__=='__main__': main()
