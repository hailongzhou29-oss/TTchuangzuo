"""Targeted UI checks using tiny isolated works and a local fake provider only."""
import json,sys,tempfile,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtCore import Qt,QTimer,QPoint,QThreadPool
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication,QPushButton
from PySide6.QtTest import QTest
from app.core.test_isolation import start_test_runtime
from app.core.services import Workspace
from app.core.selection import selection
from app.core.creation_flow import CreationFlow,initial_generation_ready
from app.core.agent_candidates import AgentCandidates
from app.providers.contracts import Connection,TextResult,CancelToken
from app.ui.v2_window import MainWindow
from app.ui.v2_widgets import QMenu
from app.ui.interaction import theme_tokens

class LocalProvider:
    def __init__(self,value): self.value=value
    def generate(self,connection,secret,messages,cancel,on_text,**kwargs):
        text=self.value if isinstance(self.value,str) else json.dumps(self.value,ensure_ascii=False); time.sleep(.12); on_text(text)
        return TextResult(text=text,status='completed',accepted=True,model=connection.model)

def main():
    app=QApplication([]); app.setProperty('native_hidden_test',True); errors=[]; checks=[]
    def capture(kind,value,tb): errors.append(str(value)); traceback.print_exception(kind,value,tb)
    sys.excepthook=capture
    evidence=ROOT/'docs'/'evidence'/'ui_candidate_theme'; evidence.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='candidate-theme-',dir=ROOT/'logs') as temporary:
        base=start_test_runtime(Path(temporary)); w=MainWindow(Workspace(base/'internal_data'),ROOT/'resources',base/'preferences.json'); w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen); w.resize(1440,900); w.show(); app.processEvents()
        connection=Connection('fixture','Local fixture','deepseek','test-model',base_url='https://example.org',max_output=8192,context_limit=65536); w.connections.save(connection)
        for kind in ('script','novel','rewrite'):
            config=selection(kind)
            if kind=='rewrite': config['reference_description']='开场、冲突、结尾的三段叙事结构'
            store=w.workspace.create('UI fixture '+kind,{'script':'剧本','novel':'小说','rewrite':'仿写'}[kind]); store.set_setting('v2_kind',kind); store.set_setting('v2_selection',config); did=store.documents()[0]['id']; original='原稿开场。\n'+''.join(f'第{i}段，人物沿着河岸走向村口。\n' for i in range(28))+'结尾保留。'; store.save_document(did,store.document(did)['head'],original,'fixture'); store.set_setting('v2_last_document',did)
            w.open_project(store.root); page=w.creators[kind]; page.set_view(1); flow=CreationFlow(w.work,ROOT/'resources',w.connections); snapshot=flow.prepare(connection,'modify','修改开场，保留结尾',(0,6),True); w.text_test_provider=LocalProvider(dict(text='新的开场。',explanation='修改第一句，其余保留。'))
            w.launch_snapshot(page,w.work,flow,snapshot,True); app.processEvents()
            assert page.banner.busy and page.banner.caption.text() and page.banner.detail.text() and page.banner.width()>=270
            page.banner.elapsed.start(); page.banner.render_feedback(); first_phrase=page.banner.detail.text(); clock=page.banner.elapsed; page.banner.elapsed=type('ElapsedFixture',(),{'elapsed':lambda self:9000})(); page.banner.render_feedback(); assert page.banner.detail.text()!=first_phrase; assert '00:09' in page.banner.caption.text(); page.banner.elapsed=clock
            if kind=='script': w.grab().save(str(evidence/'status.png'))
            limit=time.monotonic()+10
            while w.active_task and time.monotonic()<limit: app.processEvents(); time.sleep(.025)
            assert not w.active_task and not errors,errors
            service=AgentCandidates(store); cid=service.pending()[-1]['id']; expected=service.preview(cid)
            assert w.work.text==original and expected in w.assistant.chat.toPlainText()
            assert [b.text() for b in w.assistant.candidate_box.findChildren(QPushButton)]==['应用到正文','查看差异','放弃']
            assert not any(b.text()=='查看改稿' for b in w.findChildren(QPushButton)) and '查看改稿' not in w.assistant.chat.toPlainText()
            QTest.mouseClick(w.assistant.candidate_button,Qt.MouseButton.LeftButton); app.processEvents(); pane=page.candidate_pane; assert pane and pane.adopt_button.isHidden()
            for theme in ('暖纸色','清透白','石墨紫'):
                mode=pane.modes.currentIndex(); cursor=pane.right.textCursor(); cursor.setPosition(2); cursor.setPosition(4,QTextCursor.MoveMode.KeepAnchor); pane.right.setTextCursor(cursor); pane.right.verticalScrollBar().setValue(min(120,pane.right.verticalScrollBar().maximum())); position=pane.right.verticalScrollBar().value()
                w.assistant.chat.verticalScrollBar().setValue(0); w.set_theme(theme); app.processEvents(); c=theme_tokens(theme)
                assert pane.right.toPlainText()==expected and pane.modes.currentIndex()==mode and pane.right.textCursor().selectedText()==expected[2:4]
                assert pane.right.verticalScrollBar().value()==position
                assert expected in w.assistant.chat.toPlainText() and w.assistant.chat.verticalScrollBar().value()==0
                for editor,key in ((pane.left,'diff_removed'),(pane.right,'diff_added')):
                    assert editor.extraSelections()
                    for highlight in editor.extraSelections(): assert highlight.format.background().color().name()==c[key].lower() and highlight.format.foreground().color().name()==c['text'].lower()
                assert page.banner.width()>=270
                if kind=='script': w.grab().save(str(evidence/('compare-'+theme+'.png')))
            checks.append(kind+': complete candidate, three actions, three-theme diff and view state')
            QTest.mouseClick(w.assistant.apply_button,Qt.MouseButton.LeftButton); app.processEvents(); assert w.work.text==expected and store.document(did)['text']==expected and not page.candidate_pane and not w.assistant.candidate_box.isVisible()
            assert ' '.join(expected.split()) in ' '.join(w.assistant.chat.toPlainText().split())
            snapshot=flow.prepare(connection,'modify','修改第一句',(0,6),True); result=flow.service.execute(snapshot,CancelToken(),provider=LocalProvider(dict(text='放弃的开场。',explanation='fixture'))); cid=service.save(snapshot,result); w.assistant.refresh_candidates(); QTest.mouseClick(w.assistant.discard_button,Qt.MouseButton.LeftButton); assert w.work.text==expected and service.row(cid)['state']=='discarded'
            checks.append(kind+': apply persists body, discard preserves body')
            page.set_view(1); app.processEvents(); captured=[]
            def inspect_menu():
                menus=[menu for menu in page.findChildren(QMenu) if menu.isVisible()]
                if menus:
                    menu=menus[-1]; anchor=page.export_button.mapToGlobal(page.export_button.rect().bottomRight()); captured.append((menu.x()+menu.width()-1-anchor.x(),menu.y()-anchor.y())); menu.grab().save(str(evidence/('export-'+kind+'.png'))); menu.close()
            QTimer.singleShot(30,inspect_menu); page.export_menu(); assert captured and abs(captured[0][0])<=2 and 3<=captured[0][1]<=6,captured
            checks.append(kind+': export popup anchored to button')
        w.new_work('novel'); page=w.creators['novel']; page.config['target_chars']=100; work=w.ensure_work(page); flow=CreationFlow(work,ROOT/'resources',w.connections); value=dict(title='初稿测试',synopsis='渡口的故事',plan=['第一章'],characters='守渡人',chapter_title='第一章',text='师父让我守住渡口。\n'+('水已经漫过石狮的脚。\n'*20))
        snapshot=flow.prepare(connection,'generate','生成小说',development_test=True); result=flow.service.execute(snapshot,CancelToken(),provider=LocalProvider(value)); assert result['status']=='completed',result
        result.update(requires_adoption=True,postprocessing=dict(primary_status='completed',summary_status='failed')); assert initial_generation_ready(snapshot,result)
        active=dict(flow=flow,snapshot=snapshot,page=page,work=work,cancel=CancelToken(),manual=False,preview=False,partial='',assistant_request=False); w.active_task=active; w.finish_task(active,result); app.processEvents()
        assert work.text.strip() and work.store.document(work.document_id)['text']==work.text and not AgentCandidates(work.store).pending() and not w.assistant.candidate_box.isVisible()
        complete=lambda:' '.join(work.text.split()) in ' '.join(w.assistant.chat.toPlainText().split())
        assert complete() and '作品已生成并保存' in w.assistant.chat.toPlainText(); w.assistant.refresh(); assert complete(); w.grab().save(str(evidence/'first-novel.png'))
        checks.append('first novel: complete primary saved despite missing summary; no rewrite prompt')
        snapshot=flow.prepare(connection,'generate','重新生成小说',development_test=True); result=flow.service.execute(snapshot,CancelToken(),provider=LocalProvider(value)); assert not initial_generation_ready(snapshot,result); original=work.text
        active=dict(flow=flow,snapshot=snapshot,page=page,work=work,cancel=CancelToken(),manual=False,preview=False,partial='',assistant_request=False); w.active_task=active; w.finish_task(active,result); assert AgentCandidates(work.store).pending() and work.text==original
        checks.append('existing novel: regeneration retains original until explicit application')
        snapshot=flow.prepare(connection,'modify','修改第一句',(0,6),True); result=flow.service.execute(snapshot,CancelToken(),provider=LocalProvider('人工核对后的开场。')); assert result['candidate']['needs_review']; service=AgentCandidates(work.store); cid=service.save(snapshot,result); original=work.text; w.assistant.refresh_candidates(); QTest.mouseClick(w.assistant.apply_button,Qt.MouseButton.LeftButton); app.processEvents(); pane=page.candidate_pane
        assert pane and pane.confirm.isVisible() and work.text==original; pane.confirm.setChecked(True); QTest.mouseClick(w.assistant.apply_button,Qt.MouseButton.LeftButton); app.processEvents(); assert work.text.startswith('人工核对后的开场。') and service.row(cid)['state']=='applied'
        checks.append('unstructured reply: three-action flow requires confirmation before application')
        w.navigate(0); w.home.refresh(); app.processEvents(); QTest.qWait(120); app.processEvents()
        for card in w.home.cards:
            action=card.actions['生成封面']; assert card.width()>=300 and action.width()>=action.fontMetrics().horizontalAdvance(action.text())+10
            assert card.cover.geometry().bottom()<card.title.geometry().top(),(card.cover.geometry().getRect(),card.title.geometry().getRect())
        w.grab().save(str(evidence/'home-larger-cards.png')); checks.append('home cards: larger width and unabridged cover button')
        assert not errors,errors; QThreadPool.globalInstance().waitForDone(2000); w.close(); app.processEvents()
    (evidence/'results.json').write_text(json.dumps(dict(passed=checks,unhandled_errors=errors,paid_calls=0,build=False,production_data_read=False),ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS',len(checks),'targeted groups; zero paid calls and no production data reads')

if __name__=='__main__': main()
