"""Native Windows evidence using disposable projects and simulated responses."""
import json,sys,tempfile,time,threading
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication,QPushButton
from app.core.services import Workspace
from app.ui.v2_window import MainWindow
from app.core.context import ChatService
from app.providers.contracts import Connection,TextResult

class Provider:
    def __init__(self): self.release=threading.Event(); self.value='仅讨论，正文保持。'
    def generate(self,c,secret,messages,cancel,on_text,**kw):
        while not self.release.wait(.03):
            if cancel.cancelled: return TextResult(status='cancelled',accepted=False)
        on_text(self.value); return TextResult(text=self.value,status='completed',accepted=True,model=c.model)

def main():
    app=QApplication([]); out=ROOT/'docs/evidence/merged_fix'
    if '--output' in sys.argv: out=Path(sys.argv[sys.argv.index('--output')+1]).resolve()
    out.mkdir(parents=True,exist_ok=True); checks=[]
    def spin(ms=100):
        stop=time.monotonic()+ms/1000
        while time.monotonic()<stop: app.processEvents(); time.sleep(.01)
    def check(name,value): checks.append(dict(check=name,passed=bool(value)))
    def capture(name): spin(); window.grab().save(str(out/name))
    def wait():
        stop=time.monotonic()+10
        while window.active_task and time.monotonic()<stop: spin(30)
        check('任务完成无阻塞',not window.active_task)
    with tempfile.TemporaryDirectory(prefix='tt_merged_native_') as tmp:
        root=Path(tmp); workspace=Workspace(root/'data'); prefs=root/'prefs/preferences.json'; window=MainWindow(workspace,ROOT/'resources',prefs)
        window.allow_test_connections=True; p=Provider(); window.text_test_provider=p
        c=Connection('fixture','隔离验证（模拟）','deepseek','fixture',base_url='https://example.org',max_output=1024,context_limit=65536,verification=dict(development_test=True)); window.connections.save(c); window.options['default_connection']=c.id; window.assistant.refresh_models()
        window.resize(1280,800); window.show(); window.new_work('script'); page=window.current_page(); spin()
        page.idea.setPlainText('一封旧信让两名值班员重新面对未完成的约定。'); form=page.script_form; form.set_value('genre','G04'); form.changed('genre'); form.set_value('subgenres',['G04.1','G04.2','custom:旧信与约定']); form.changed('subgenres')
        capture('01-script-settings.png'); check('设置和正文切换入口可用',page.view_settings.isVisible() if hasattr(page,'view_settings') else page.views.currentIndex()==0)
        work=window.ensure_work(page); body='第一部分｜故事大纲与建议时长\n\n旧信让值班员面对约定。\n预计时长：约30秒（未配音实测）\n\n第二部分｜完整剧本\n\n第1场 值班室·夜\n[动作] 阿宁把旧信放在桌上。\n阿宁：这一次，我会留下。\n林远：我替你守住门。\n\n第三部分｜完整人物台词\n\n阿宁：这一次，我会留下。\n林远：我替你守住门。'
        work.edit(body); work.save(); window.replace_editor(page,work.text); page.set_view(1); capture('02-script-body.png')
        check('正文无常驻旧设置处理按钮',not page.history_button.isVisible() if hasattr(page,'history_button') else not form.history_button.isVisible())
        window.set_assistant_visible(False); capture('03-assistant-collapsed.png'); window.set_assistant_visible(True); capture('04-assistant-restored.png')
        width=window.assistant.width(); window.assistant.input.setPlainText('未发送输入保留')
        for _ in range(8): window.toggle_assistant(); spin(20); window.toggle_assistant(); spin(20)
        check('反复收起恢复宽度和输入',abs(window.assistant.width()-width)<45 and window.assistant.input.toPlainText()=='未发送输入保留')
        check('助手只保留顶栏收起入口',not any(b.accessibleName()=='收起 AI 助手' for b in window.assistant.findChildren(QPushButton)))
        instruction='只讨论旧信含义，不改稿'; window.chat_request(instruction); spin(40)
        check('用户消息立即可见',instruction in window.assistant.chat.toPlainText())
        with work.store.connection() as con: check('用户消息发送时已持久化',con.execute('SELECT COUNT(*) FROM messages WHERE role=? AND content=?',('user',instruction)).fetchone()[0]==1)
        p.release.set(); wait(); check('讨论保持正文和台词',work.text==body)
        chat=ChatService(work.store); chat.append(chat.current(),work.document_id,'discussion','assistant',json.dumps(dict(text='候选文本',explanation='已加强人物决心'),ensure_ascii=False),'nested-fixture','completed',protocol=[dict(role='assistant',content='候选文本')]); window.assistant.refresh(); spin()
        check('历史解析嵌套合同', '已加强人物决心' in window.assistant.chat.toPlainText() and '"explanation"' not in window.assistant.chat.toPlainText())
        project_root=work.store.root; window.navigate(0); window.open_project(project_root); spin(); check('切页返回正文一致',window.work.text==body)
        window.resize(800,650); capture('05-narrow-script.png'); check('窄窗口模型输入发送可用',window.assistant.model.isVisible() and window.assistant.input.isVisible() and window.assistant.send_button.isVisible())
        check('窄窗口助手不覆盖顶栏收起入口',not window.assistant.geometry().contains(window.assistant_toggle.mapTo(window.centralWidget(),window.assistant_toggle.rect().center())))
        window.resize(1280,800); window.navigate(4); window.settings.tabs.setCurrentIndex(1); spin()
        with patch.object(window.settings.c,'detect_codex',return_value=dict(available=True,authenticated=True,version='模拟版本',command='模拟命令',features=[])):
            window.settings.activate_current_model()
        check('默认Codex无需API保存门禁',window.options.get('default_connection')==window.settings.c.channel_configs['codex_local'].id); capture('06-codex-settings.png')
        window.settings.tabs.setCurrentIndex(3); capture('07-advanced-paths.png'); check('高级第四页可访问',window.settings.tabs.count()==4)
        from app.ui.cover_panel import CoverPanel
        cover=CoverPanel(window,window.work); custom='用户手编：旧信，无人物，无文字'; cover.prompt.setPlainText(custom); cover.ratio.setCurrentText('1:1'); cover.style.setCurrentText('极简设计'); cover.title.setText('新封面标题')
        check('改变封面比例风格标题保留手编提示',cover.prompt.toPlainText()==custom)
        cover.auto_prompt(); check('明确重新填入才替换提示',cover.prompt.toPlainText()!=custom and not cover.prompt_dirty)
        window.close(); spin(); window=MainWindow(Workspace(root/'data'),ROOT/'resources',prefs); window.allow_test_connections=True; window.open_project(project_root); window.show(); spin()
        check('重开正文保持且历史无JSON',window.work.text==body and '"explanation"' not in window.assistant.chat.toPlainText() and '已加强人物决心' in window.assistant.chat.toPlainText()); capture('08-reopened.png'); window.close(); spin()
    result=dict(checks=checks,passed=sum(c['passed'] for c in checks),total=len(checks),network_calls=0,paid_calls=0,model='simulated',qt_platform=app.platformName(),physical_dpr=app.primaryScreen().devicePixelRatio())
    (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(result,ensure_ascii=True)); return int(result['passed']!=result['total'])
if __name__=='__main__': raise SystemExit(main())
