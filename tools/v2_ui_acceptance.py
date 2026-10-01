"""Exercise the actual V2 window in isolated storage. Responses are controlled UI tests."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtCore import Qt,QEvent,QPoint
from PySide6.QtGui import QMouseEvent,QTextCursor
from PySide6.QtWidgets import QApplication,QDialog,QTextEdit,QLineEdit
from app.core.services import Workspace
from app.ui.v2_window import MainWindow
from app.providers.contracts import Connection,TextResult
from app.core.creation_flow import SCRIPT,NOVEL

class Provider:
    def __init__(self): self.value=None; self.calls=0; self.messages=[]
    def generate(self,c,secret,messages,cancel,on_text,**options):
        self.calls+=1; self.messages=messages; value=self.value
        raw=json.dumps(value,ensure_ascii=False) if isinstance(value,dict) else value
        on_text(raw); return TextResult(text=raw,status='completed',model=c.model,accepted=True)

def main():
    app=QApplication([]); report=[]; evidence=ROOT/'docs'/'evidence'/('v2_scale_'+os.environ['QT_SCALE_FACTOR'].replace('.','_') if os.environ.get('QT_SCALE_FACTOR') else 'v2'); evidence.mkdir(parents=True,exist_ok=True)
    def check(name,condition):
        report.append(dict(check=name,passed=bool(condition)))
        if not condition: raise AssertionError(name)
    def wait(window):
        until=time.monotonic()+15
        while (window.active_task or window.segmented) and time.monotonic()<until: app.processEvents(); time.sleep(.01)
        app.processEvents(); check('任务结束',window.active_task is None and window.segmented is None)
    with tempfile.TemporaryDirectory(prefix='tt_v2_ui_') as temp:
        root=Path(temp); window=MainWindow(Workspace(root/'data'),ROOT/'resources',root/'settings'/'preferences.json'); window.show(); app.processEvents()
        provider=Provider(); window.text_test_provider=provider; window.allow_test_connections=True
        # Keep mocks in this isolated executable, never in user connection files.
        connection=Connection('fixture','界面测试','custom','fixture',base_url='https://fixture.invalid',max_output=8192,context_limit=65536)
        window.connections.save(connection,'fixture-secret'); window.assistant.refresh_models(); window.assistant.model.setCurrentIndex(window.assistant.model.findData(connection.id))
        check('五页顺序',window.pages.count()==5 and [window.navigation.item(i).text() for i in range(4)]==['首页','剧本','小说','仿写'])
        window.navigate(4); app.processEvents(); check('设置在主页面，无设置弹窗',window.current_page() is window.settings and not window.assistant.isVisible() and not any(isinstance(w,QDialog) and w.isVisible() for w in app.topLevelWidgets()))
        window.new_work('script'); app.processEvents(); page=window.creators['script']; check('无想法默认3分钟',page.read_config()['duration']==180 and not page.idea.toPlainText())
        page.fields['genre'].setCurrentIndex(page.fields['genre'].findData('G07')); page.fields['subgenres'].set_values(['G07.3']); page.config_changed()
        provider.value=dict(title='最后一分钟',outline='维修员争取最后一分钟，为同伴打开门。',scenes=[dict(title='机房·夜',nodes=[dict(type='action',speaker='',text='林远拉下开关。'),dict(type='dialogue',speaker='林远',text='只有一分钟。')]),dict(title='门外·夜',nodes=[dict(type='action',speaker='',text='阿宁按住门把。'),dict(type='dialogue',speaker='阿宁',text='我替你守住。')])])
        window.generate(page); wait(window); original=page.editor.toPlainText(); check('直接生成三部分并进入统一正文','第三部分｜完整人物台词' in original and original==window.work.text and original==window.work.store.document(window.work.document_id)['text'])
        check('选择正文实际进入请求', '固定改写或闭环规则' in provider.messages[0]['content'] and '古代商战' not in provider.messages[0]['content'])
        provider.value='第二场阿宁守住门把，为林远争取时间。'; window.chat_request('第二场讲了什么，检查不要修改'); wait(window); check('助手立即读取新作品且检查不修改',original==window.work.text and '阿宁' in provider.messages[1]['content'])
        from app.core.work_context import locate
        start,end=locate(original,'只改第二场'); provider.value=dict(text=original[start:end].replace('按住','用肩膀死死抵住'),explanation='加强第二场动作，保留台词')
        window.chat_request('只改第二场，保留台词'); wait(window); modified=window.work.text; check('定点修改已回写且前文不变',modified!=original and modified[:start]==original[:start])
        with window.work.store.connection() as con: task_id=con.execute('SELECT id FROM tasks ORDER BY rowid DESC LIMIT 1').fetchone()[0]
        window.undo_ai(task_id); check('AI修改可撤销',window.work.text==original and page.editor.toPlainText()==original)
        from PySide6.QtGui import QImage,QColor
        from app.core.cover import import_image
        from app.ui.cover_panel import CoverPanel,cover_image
        background=QImage(300,400,QImage.Format.Format_RGB32); background.fill(QColor('#6285AC')); png=root/'候选.png'; background.save(str(png)); relative,_=import_image(window.work.store,png)
        window.open_cover(); panel=window.inline.findChild(CoverPanel); panel.candidate=dict(relative=relative); panel.composed=cover_image(png,window.work.store.metadata()['name'],'3:4','后期排字'); panel.adopt()
        check('采用封面绑定正式封面记录',bool(window.work.store.setting('active_cover')))
        root_project=window.work.store.root; window.save_work(); window.navigate(0); check('首页不显示助手',not window.assistant.isVisible())
        app.processEvents(); check('首页有真实项目封面卡片',len(window.home.cards)==1)
        check('首页恢复实际封面资产',bool(window.home.cards[0].cover_spec.get('image')))
        card=window.home.cards[0]
        for target in (card.cover,card.title,card):
            event=QMouseEvent(QEvent.Type.MouseButtonDblClick,QPoint(8,8),Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier); app.sendEvent(target,event); app.processEvents(); check('封面标题卡片双击恢复正文',window.work.text==original)
            window.navigate(0); app.processEvents(); card=window.home.cards[0]
        window.open_project(root_project); page=window.current_page(); cursor=page.editor.textCursor(); cursor.movePosition(QTextCursor.MoveOperation.End); cursor.insertText('\n手工增加的最新内容'); window.save_work()
        provider.value='已读取新增内容。'; window.chat_request('检查不要修改'); wait(window); check('读取最新手工正文','手工增加的最新内容' in provider.messages[1]['content'])
        window.new_work('novel'); novel=window.current_page(); novel.fields['length'].setCurrentText('长篇连载'); provider.value=dict(title='旧站',synopsis='旧信引起重返车站的选择。',plan=['第1章 收到信','第2章 重返车站','第3章 查明来历'],characters='阿宁，修理员；林远，值班员。',chapter_title='第1章 收到信',text='阿宁将旧信塞进外套，快步走出值班室。')
        window.generate(novel); wait(window)
        for n in (2,3):
            provider.value=dict(title='旧站',synopsis='旧信引起重返车站的选择。',plan=[],characters='阿宁，修理员；林远，值班员。',chapter_title=f'第{n}章 回声',text=f'阿宁在第{n}章继续寻找旧信来历。林远在站台递给她另一张纸。')
            window.next_chapter(); wait(window)
        check('三章独立保存',len(window.work.store.documents())==3)
        window.new_work('script'); segment_page=window.current_page(); segment_page.fields['duration_label'].setCurrentText('10分钟'); provider.value=dict(title='长剧测试',outline='主线跨多个场次逐步推进。',scenes=[dict(title='车站',nodes=[dict(type='action',speaker='',text='阿宁向前走。'),dict(type='dialogue',speaker='阿宁',text='还要继续找。')])]); old_calls=provider.calls; window.generate(segment_page); wait(window); check('长剧自动分两段，正文累计保存',provider.calls-old_calls==2 and window.work.text.count('第2场')==1)
        window.new_work('rewrite'); rewrite=window.current_page(); rewrite.fields['output'].setCurrentText('小说'); rewrite.reference.setPlainText('用户拥有的短故事参考：陌生人在候车室留下了一封信。'); window.generate(rewrite); wait(window); check('仿写小说不套剧本三段', '第三部分' not in window.work.text)
        for theme in ('石墨紫','清透白','暖纸色'):
            window.set_theme(theme)
            for size in ((1100,720),(1440,900),(1920,1080)):
                window.resize(*size)
                for index in range(5):
                    window.navigate(index); app.processEvents(); check(f'{theme} {size} 第{index}页正文空间',window.pages.width()>300)
                    if index in (1,2,3):
                        p=window.current_page(); check(f'正文保持可用高度 {p.kind} {size} height={p.editor.height()}',p.editor.height()>100)
                if size==(1440,900):
                    for index in range(5): window.navigate(index); app.processEvents(); window.grab().save(str(evidence/f'{theme}_{index}.png'))
        window.navigate(1); window.show_materials(window.current_page()); app.processEvents(); window.grab().save(str(evidence/'资料与规则.png')); window.current_page().materials.close_panel()
        window.navigate(4); check('文本及图片表单密钥不明文',window.settings.text['key'].echoMode()==QLineEdit.EchoMode.Password and window.settings.image['key'].echoMode()==QLineEdit.EchoMode.Password)
        for kind in ('script','novel','rewrite'):
            window.navigate({'script':1,'novel':2,'rewrite':3}[kind]); p=window.current_page(); window.resize(1100,720); p.toggle_advanced(); app.processEvents(); check('高级选择展开保留正文空间',p.editor.height()>100); p.toggle_advanced()
        from PySide6.QtGui import QInputMethodEvent,QKeyEvent
        inp=window.assistant.input; sent=[]; inp.send.connect(lambda:sent.append(True)); app.sendEvent(inp,QInputMethodEvent('候选',[])); app.sendEvent(inp,QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_Return,Qt.KeyboardModifier.NoModifier)); check('输入法预编辑期间不误发',not sent)
        ratio=window.devicePixelRatioF(); report.append(dict(check='实际设备缩放',ratio=ratio,passed=True))
        from PySide6.QtCore import QThreadPool
        window.close(); app.processEvents(); QThreadPool.globalInstance().waitForDone(3000)
    (evidence/'ui_results.json').write_text(json.dumps(dict(type='隔离UI测试，使用固定响应，不代表真实模型质量',checks=report),ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(dict(checks=len(report),passed=True,device_scale=ratio),ensure_ascii=False))

if __name__=='__main__': main()
