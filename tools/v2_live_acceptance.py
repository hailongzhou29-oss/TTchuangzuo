"""Few explicitly authorized live calls through the real window and task services."""
import argparse
import json
import os
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from app.ui.v2_window import MainWindow
from app.core.services import Workspace
from app.core.creation_flow import dialogues,script_body
from app.core.work_context import locate
from app.core.files import digest
from app.storage.connections import ConnectionStore
from app.storage.image_connections import ImageConnectionStore
from dataclasses import replace

class LiveConnections(ConnectionStore):
    def all(self):
        return super().all()

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--image',action='store_true'); parser.add_argument('--resume',action='store_true'); args=parser.parse_args()
    from app.core.test_isolation import start_test_runtime
    import tempfile
    isolated=start_test_runtime(Path(tempfile.mkdtemp(prefix='tt_v2_live_')))
    source=ConnectionStore(Path(os.environ['LOCALAPPDATA'])/'TTChuangzuo')
    settings=isolated/'prefs'; selected=source.all()
    class ReadOnlyCredentials(LiveConnections):
        def secret_snapshot(self,c):return source.secret_snapshot(c)
    connections=ReadOnlyCredentials(settings)
    for c in selected:connections.save(c)
    evidence=isolated/'evidence'; evidence.mkdir(parents=True,exist_ok=True)
    app=QApplication([]); window=MainWindow(Workspace(evidence/'data'),ROOT/'resources',evidence/'preferences.json')
    window.connections=connections; window.image_connections=ImageConnectionStore(settings); window.assistant.refresh_models(); window.settings.c.reload(); window.options['restore_last']=False; window.show(); app.processEvents()
    records=[]
    def wait():
        deadline=time.monotonic()+400
        while (window.active_task or window.active_image_task) and time.monotonic()<deadline: app.processEvents(); time.sleep(.03)
        if window.active_task or window.active_image_task: window.stop_task(); window.stop_image(); raise TimeoutError('真实通道测试超时，已停止本地等待')
        app.processEvents()
    try:
        connection=next(c for c in window.connections.all() if c.provider=='deepseek' and c.enabled)
        if args.resume:
            saved=json.loads((evidence/'preferences.json').read_text(encoding='utf-8'))['last_project']; window.open_project(Path(saved)); page=window.current_page()
        else:
            window.new_work('script'); page=window.current_page(); window.assistant.model.setCurrentIndex(window.assistant.model.findData(connection.id))
            page.fields['genre'].setCurrentIndex(page.fields['genre'].findData('G07')); page.fields['subgenres'].set_values(['G07.3']); page.config_changed(); window.generate(page); wait()
        window.assistant.model.setCurrentIndex(window.assistant.model.findData(connection.id))
        work=window.work; original=work.text
        if '第三部分｜完整人物台词' not in original: raise AssertionError('真实模型未交付完整三部分：'+page.banner.text())
        with work.store.connection() as con: row=con.execute("SELECT id,result,snapshot FROM tasks WHERE json_extract(snapshot,'$.v2_task')='generate' ORDER BY rowid DESC LIMIT 1").fetchone()
        result=json.loads(row['result']); snap=json.loads(row['snapshot']); records.append(dict(test='DS整篇生成',status=result['status'],model=connection.model,usage=result.get('usage'),task_id=row['id'],rule_refs=[r['rule_id'] for r in snap['rule_snapshot']]))
        (evidence/'真实剧本_生成.md').write_text(original,encoding='utf-8'); window.grab().save(str(evidence/'真实剧本.png'))
        start,end=locate(original,'只改第二场'); window.chat_request('保留情节和所有台词，只改第二场动作，让第二场冲突更强。不要修改其他场。'); wait()
        modified=work.text
        if modified==original: raise AssertionError('定点修改没有应用：'+page.banner.text())
        if modified[:start]!=original[:start] or dialogues(script_body(original))!=dialogues(script_body(modified)): raise AssertionError('局部范围或对白保护失效')
        with work.store.connection() as con: row=con.execute('SELECT id,result FROM tasks ORDER BY rowid DESC LIMIT 1').fetchone()
        result=json.loads(row['result']); records.append(dict(test='DS定点修改',status=result['status'],model=connection.model,usage=result.get('usage'),task_id=row['id'],dialogues_unchanged=True))
        (evidence/'真实剧本_修改.md').write_text(modified,encoding='utf-8'); window.undo_ai(row['id'])
        if work.text!=original: raise AssertionError('撤销未恢复原稿')
        project_root=work.store.root; window.save_work(); window.navigate(0); window.open_project(project_root)
        if window.work.text!=original: raise AssertionError('保存重开内容不一致')
        records.append(dict(test='撤销保存重开',status='passed',hash=digest(original)))
        if args.image:
            window.open_cover(); panel=window.inline.findChild(__import__('app.ui.cover_panel',fromlist=['CoverPanel']).CoverPanel); panel.generate(); wait()
            if not panel.candidate: raise AssertionError('真实封面未获得图片：'+panel.status.text())
            records.append(dict(test='Codex自动封面',status='verified',dimensions=[panel.candidate['width'],panel.candidate['height']],sha256=panel.candidate['sha256'],provider_size=panel.snapshot['provider_size'],ratio=panel.ratio.currentText()))
            panel.adopt(); window.navigate(0); window.grab().save(str(evidence/'真实封面首页.png'))
        # Evidence project stays outside normal workspace and its home list.
        work.store.set_setting('system_test_project',True); work.store.update_project(status='archived')
        print(json.dumps(dict(passed=True,checks=records),ensure_ascii=False))
    except Exception as exc:
        records.append(dict(test='失败',status='failed',error=str(exc))); print(json.dumps(dict(passed=False,checks=records),ensure_ascii=False)); raise
    finally:
        (evidence/'live_results.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        if not window.active_task and not window.active_image_task: window.close()

if __name__=='__main__': main()
