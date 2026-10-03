"""One authorized no-people Codex cover, then local visual-review/adoption phase."""
import json,sys,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from app.core.services import Workspace
from app.core.work_context import CurrentWork
from app.core.selection import selection
from app.core.files import write_json,digest,inside
from app.core.cover import validate_image
from app.providers.codex_text import CodexTextProvider
from app.providers.image_contracts import ImageConnection
from app.ui.v2_window import MainWindow
from app.ui.cover_panel import CoverPanel

PROMPT='只生成一张方形摄影质感小说封面背景：一间已废弃且完全无人使用的旧车站值班室，空桌上只有一封封好的旧信，抽屉旁放一把红钥匙，窗外微雨与柔和路灯光。安静、克制、深蓝和暖棕色。画面只能出现空房间和静物；绝不出现人物、人体、脸、手、人影、剪影、雕像或人的照片。不要文字、字母、标志、水印。'

def main():
    out=ROOT/'docs/evidence/upgrade_cover_live'; out.mkdir(parents=True,exist_ok=True); path=out/'results.json'; local='--adopt-existing' in sys.argv
    if local:
        report=json.loads(path.read_text(encoding='utf-8'))
        if report['state']!='awaiting_visual_review' or '--no-people-confirmed' not in sys.argv: raise ValueError('只在本次图片已实际查看且确认无人物后本地采用')
    else:
        if path.exists(): raise SystemExit('已有单张请求记录，不重复生成或调用图片API')
        if not CodexTextProvider().detect(login=True)['logged_in']: raise ValueError('当前登录不可用，未请求且不重新登录')
        report=dict(state='started',additional_authorized_count=1,submitted_count=0,records=[],checks=[],api_fallback=False); write_json(path,report)
    def record(**value): report['records'].append(value); write_json(path,report); print(json.dumps(value,ensure_ascii=True),flush=True)
    def check(name,value):
        report['checks'].append(dict(check=name,passed=bool(value))); write_json(path,report)
        if not value: raise AssertionError(name)
    app=QApplication([]); workspace=Workspace(out/'data'); prefs=out/'prefs/preferences.json'; window=None
    def spin(ms=90):
        end=time.monotonic()+ms/1000
        while time.monotonic()<end: app.processEvents(); time.sleep(.02)
    try:
        if local: store=workspace.open(Path(report['project_root']))
        else:
            store=workspace.create('无人旧站_合成封面','小说'); store.set_setting('v2_kind','novel'); config=selection('novel'); store.set_setting('v2_selection',config); did=store.documents()[0]['id']; store.set_setting('v2_document:'+did,True); store.set_setting('v2_plan',dict(synopsis='空置旧车站的桌上有封旧信，抽屉旁的红钥匙尚未使用。没有人物。',characters='',chapters=['空置值班室与静物'],source_stale=False)); report['project_root']=str(store.root); write_json(path,report)
        window=MainWindow(workspace,ROOT/'resources',prefs); connection=ImageConnection('approved_no_people_cover','Codex 无人物单张实测','image_codex','',timeout=300,sizes=('1024x1024',)); window.image_connections.save(connection); window.options['default_image']=connection.id; window.open_project(store.root); window.show(); spin(); panel=CoverPanel(window,window.work); window.show_inline('无人物封面实测',panel); spin()
        if not local:
            check('outline prepares editable prompt',not panel.prompt.isReadOnly() and '红钥匙' in panel.prompt.toPlainText()); panel.ratio.setCurrentText('3:4'); panel.mode.setCurrentText('无文字'); panel.prompt.setPlainText(PROMPT); panel.ratio.setCurrentText('1:1'); panel.style.setCurrentText('摄影质感'); panel.title.setText('无人旧站'); check('manual no-people prompt survives parameter changes',panel.prompt.toPlainText()==PROMPT); window.grab().save(str(out/'01-prompt-before-submit.png'))
            original=CodexTextProvider.generate
            def audited(provider,connection,messages,cancel,*args,**kwargs):
                if kwargs.get('image_request'):
                    if report['submitted_count']>=1: raise ValueError('只允许本轮追加的一张图片请求')
                    report['submitted_count']+=1; report['outbound_codex_prompt']=messages[0]['content']; write_json(path,report)
                return original(provider,connection,messages,cancel,*args,**kwargs)
            with patch.object(CodexTextProvider,'generate',audited):
                QTest.mouseClick(panel.generate_button,Qt.MouseButton.LeftButton); spin(30); report['task_id']=(panel.snapshot or {}).get('task_id'); write_json(path,report); record(event='submitted',task_id=report['task_id'],count_cap=1)
                stop=time.monotonic()+315
                while window.active_image_task and time.monotonic()<stop: spin(50)
                if window.active_image_task: window.stop_image(); raise TimeoutError('本轮单张请求超时，未重发')
            if not panel.candidate: raise ValueError('没有可核验产物：'+panel.status.text())
            check('actual outbound prompt contains preserved manual requirement',PROMPT in report.get('outbound_codex_prompt','') and panel.snapshot['prompt']==PROMPT and report['submitted_count']==1)
            source=inside(store.root,panel.candidate['relative']); image=validate_image(source); report['source_path']=str(source); report['source_sha256']=digest(source.read_bytes()); report['actual_pixels']=[image.width(),image.height()]; report['request_id']=panel.service.get(panel.snapshot['task_id'])['result'].get('request_id'); window.grab().save(str(out/'02-generated-preview.png')); report['state']='awaiting_visual_review'; record(event='generated',pixels=report['actual_pixels'],source_sha256=report['source_sha256']); window.close(); spin(); window=None
        else:
            source=Path(report['source_path']); check('reviewed source is unchanged',digest(source.read_bytes())==report['source_sha256']); check('reopened preview preserves prompt ratio and mode',panel.prompt.toPlainText()==PROMPT and panel.ratio.currentText()=='1:1' and panel.mode.currentText()=='无文字' and bool(panel.candidate)); report['visual_review']=dict(no_people_confirmed=True,method='assistant viewed actual generated pixels'); QTest.mouseClick(panel.adopt_button,Qt.MouseButton.LeftButton); spin(); active=store.setting('active_cover'); spec=next(c['spec'] for c in store.covers() if c['id']==active); output=Path(spec['output_file']); check('adopted source prompt and disk output match',spec['prompt']==PROMPT and spec['source_hash']==report['source_sha256'] and output.is_file() and digest(output.read_bytes())==spec['file_hash']); report['adopted_cover_id']=active; report['output_file']=str(output); report['composed_pixels']=[validate_image(output).width(),validate_image(output).height()]; window.close(); spin(); window=MainWindow(workspace,ROOT/'resources',prefs); window.open_project(store.root); window.show(); spin(); panel=CoverPanel(window,window.work); window.show_inline('已采用无人物封面',panel); spin(); check('adopted cover reopens without another request',store.setting('active_cover')==active and panel.prompt.toPlainText()==PROMPT and panel.ratio.currentText()=='1:1' and panel.mode.currentText()=='无文字' and not panel.adopt_button.isVisible() and report['submitted_count']==1); window.grab().save(str(out/'03-adopted-reopened.png')); window.close(); spin(); window=None; report['state']='passed'; record(event='local_adoption_completed',new_requests=0)
    except Exception as exc: report['state']='failed'; report['error']=str(exc); print(json.dumps(dict(state='failed',error=report['error']),ensure_ascii=True),flush=True)
    finally: write_json(path,report)
    return int(report['state']=='failed')
if __name__=='__main__': raise SystemExit(main())
