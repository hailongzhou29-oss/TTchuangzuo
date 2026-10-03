"""Native UI and mock-provider acceptance for the frozen script specification."""
import copy
import json
import os
if os.environ.get('TT_UI_VISIBLE_TEST')!='1': os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QPoint,QRect,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QFileDialog,QPushButton,QWidget
from app.core.services import Workspace
from app.core.files import write_json
from app.core.script_settings import CATALOG,active_settings
from app.core.speech_records import verify
from app.core.work_context import locate
from app.ui.v2_window import MainWindow
from app.providers.contracts import Connection,TextResult
from stage1_ui_acceptance import FixtureProvider

def main():
    app=QApplication([]); checks=[]; factor=os.environ.get('QT_SCALE_FACTOR','native')
    evidence=ROOT/'docs/evidence'/('script_unified_'+app.platformName()+'_'+factor.replace('.','_')); evidence.mkdir(parents=True,exist_ok=True)
    def check(name,value,**details):
        checks.append(dict(check=name,passed=bool(value),**details))
        if not value: print('FAIL',name,details)
    def settle(): app.processEvents(); QTest.qWait(65); app.processEvents()
    def capture(name): settle(); window.grab().save(str(evidence/(name+'.png')))
    def wait_task():
        deadline=time.monotonic()+15
        while window.active_task and time.monotonic()<deadline: app.processEvents(); QTest.qWait(20)
        settle(); check('task completes',window.active_task is None)
    def choose(key,value):
        form.set_value(key,value); form.changed(key); settle()
    with tempfile.TemporaryDirectory(prefix='tt_unified_ui_') as temp:
        root=Path(temp); prefs=root/'settings/preferences.json'; write_json(prefs,dict(restore_last=False,splitter_sizes=[900,0],autosave=False))
        window=MainWindow(Workspace(root/'data'),ROOT/'resources',prefs); window.show(); window.new_work('script'); window.resize(1440,900); settle()
        page=window.creators['script']; form=page.script_form
        check('legacy zero width restores',window.splitter.sizes()[1]>=300,sizes=window.splitter.sizes())
        check('default basic six fields and genre empty popup disabled',form.value('form')=='form.01' and form.value('language')=='auto' and not form.fields['subgenres'].isEnabled())
        page.set_view(1); check('empty body selector and actions disabled',page.location.currentText()=='暂无正文' and not page.location.isEnabled() and not page.cover_button.isEnabled() and not page.export_button.isEnabled()); page.set_view(0)
        for row in CATALOG['genre']['rows']:
            choose('genre',row['id']); check('genre children '+row['id'],len(form.fields['subgenres'].rows)==6)
            first=next(r['id'] for r in CATALOG['subgenres']['rows'] if r['parent']==row['id']); choose('subgenres',[first]); check('genre active child '+row['id'],page.read_config()['subgenres']==[first])
        choose('genre','G04'); choose('subgenres',['G04.1','G04.2','custom:密室中的旧信']); choose('genre','G11'); choose('subgenres',['G11.1']); choose('genre','G04')
        check('parent switch restores custom and registered drafts',form.value('subgenres')==['G04.1','G04.2','custom:密室中的旧信'])
        check('inactive sibling not sent',active_settings(page.read_config())['explicit']['subgenres']==['G04.1','G04.2','custom:密室中的旧信'])
        form.fields['subgenres'].remove('G04.2'); check('selected chip removal',form.value('subgenres')==['G04.1','custom:密室中的旧信'])
        choose('carrier','carrier.04'); choose('carrier_item','carrier.04.1'); choose('carrier','carrier.05'); choose('carrier_item','carrier.05.2'); choose('carrier','carrier.04')
        check('carrier child draft restores',form.value('carrier_item')=='carrier.04.1')
        choose('mode','mode.02'); form.fields['object'].setText('虚构保温杯'); choose('mode','mode.03'); form.fields['object'].setText('虚构咖啡店'); choose('mode','mode.02')
        check('commercial parent draft restores',form.value('object')=='虚构保温杯')
        choose('mode','mode.01'); choose('carrier','auto'); choose('genre','auto')
        heights={}
        for i in range(6):
            form.tabs.setCurrentIndex(i); settle(); title=form.tabs.bar.tabText(i); collapsed=page.details_card.height(); form.toggle_more(); settle(); expanded=page.details_card.height()
            check('tab content visible '+title,form.tabs.currentWidget().height()>0)
            check('tab grows only for own details '+title,expanded>=collapsed,collapsed=collapsed,expanded=expanded)
            form.tabs.setCurrentIndex((i+1)%6); settle(); form.tabs.setCurrentIndex(i); settle(); check('per tab expansion remembered '+title,form.state['expanded'][title])
            form.toggle_more(); settle(); heights[title]=page.details_card.height()
        check('no longest tab placeholder',heights['人物']<heights['参考'] and heights['风格']<heights['台词'],heights=heights)
        form.tabs.setCurrentIndex(3); choose('language','language.08'); form.toggle_more(); settle()
        check('silent hides density speed and numeric ranges',all(form.cells[k].isHidden() for k in ['density','speed','word_range','segment_range','narration_ratio']))
        choose('language','language.09'); choose('sources',['sources.01','sources.02']); choose('delivery',['delivery.03']); choose('language','language.01'); choose('language','language.09')
        check('mixed voice draft restores',form.value('sources')==['sources.01','sources.02'] and form.value('delivery')==['delivery.03'])
        choose('sources',['sources.01']); check('source edit labels custom mixed',form.value('language')=='language.09')
        choose('language','auto'); form.toggle_more(); form.tabs.setCurrentIndex(0)
        page.idea.setPlainText('长文本与多选标签验证。'*200); check('long idea preserved',len(page.read_config()['idea'])==2200); page.idea.clear()
        # Real popup at all screen corners, with internal scroll and visible actions.
        chooser=form.fields['emotion'].control
        host=QWidget(None,Qt.WindowType.Tool); host.resize(290,52); chooser.setParent(host); chooser.setGeometry(0,0,280,40); host.show()
        available=host.screen().availableGeometry()
        for name,x,y in [('top-left',available.left(),available.top()),('bottom-left',available.left(),available.bottom()-70),('top-right',available.right()-300,available.top()),('bottom-right',available.right()-300,available.bottom()-70)]:
            host.move(x,y); settle(); chooser.open_menu(); settle(); menu=chooser.last_menu
            check('popup screen bound '+name,available.contains(menu.geometry()),geometry=[menu.x(),menu.y(),menu.width(),menu.height()],available=[available.x(),available.y(),available.width(),available.height()])
            chooser.last_search.setText('不存在的选项XYZ'); settle(); check('search no result visible '+name,chooser.empty_label.isVisible()); menu.close()
        chooser.setParent(form.fields['emotion']); form.fields['emotion'].layout().insertWidget(0,chooser); host.close(); form.reflow(); settle()
        for i in range(6):
            window.toggle_assistant(); settle(); check('assistant collapsed '+str(i),window.assistant.isHidden()); window.toggle_assistant(); settle(); check('assistant restored '+str(i),window.assistant.isVisible() and window.splitter.sizes()[1]>=300)
        window.splitter.setSizes([850,420]); settle(); window.save_layout(); width=window.splitter.sizes()[1]; window.toggle_assistant(); window.toggle_assistant(); settle(); check('remember user width',abs(width-window.splitter.sizes()[1])<=2)
        for i in [0,2,3,1]: window.navigate(i); settle()
        check('page return restores assistant',window.assistant.isVisible() and window.splitter.sizes()[1]>=300)
        window.read_mode(page); settle(); window.read_mode(page); settle(); check('reading return restores assistant',window.assistant.isVisible() and window.splitter.sizes()[1]>=300)
        window.show_inline('返回验证',QWidget(),page); settle(); window.close_inline(); settle(); check('inline return restores assistant',window.assistant.isVisible() and window.splitter.sizes()[1]>=300)
        window.assistant.input.setPlainText('多行输入保持完整。\n'*120); check('long assistant input preserved',window.assistant.input.document().blockCount()==121); window.assistant.input.clear()
        provider=FixtureProvider(); window.text_test_provider=provider; window.allow_test_connections=True
        conn=Connection('fixture_unified','本地模拟 · 固定响应','custom','fixture',base_url='https://fixture.invalid',max_output=8192,context_limit=65536)
        window.connections.save(conn,'fixture-only'); window.assistant.refresh_models(); window.assistant.model.setCurrentIndex(window.assistant.model.findData(conn.id)); settle()
        choose('density','density.03'); choose('speed','speed.01'); choose('view','view.subjective'); choose('role','role.01'); choose('role_detail','role_detail.01'); choose('role_name','男友'); choose('carrier','carrier.02'); choose('carrier_item','carrier.02.1'); choose('info',['info.behind']); choose('time',['time.insert'])
        page.settings_scroll.verticalScrollBar().setValue(0); capture('settings-selected')
        before=copy.deepcopy(page.read_config()['script_settings']); window.generate(page); wait_task(); check('generate real provider and three parts',provider.calls==1 and page.views.currentIndex()==1 and '第三部分' in page.editor.toPlainText()); verify(window.work.text,window.work.store.setting('v2_speech:'+window.work.document_id)['records'])
        check('settings reach real request',all(t in provider.messages[0]['content'] for t in ['指定角色感官','手机随拍','观众','舒缓','插入相关过去']))
        check('no adopted choice backfill',window.work.config['script_settings']==before); capture('body')
        page.editor.append('最新手动动作'); latest=page.editor.toPlainText(); provider.value='只检查，未修改。'; window.chat_request('不要续写，只检查'); wait_task()
        check('assistant reads unsaved latest content',latest in json.loads(provider.messages[1]['content'].split('\n',1)[1])['target_text']); check('check preserves text',window.work.text==latest)
        window.save_work(); check('third-only manual changes preserved on save',window.work.text==latest)
        with patch.object(QFileDialog,'getSaveFileName',return_value=(str(root/'bad-export.md'),'')):
            try: window.export_work('md')
            except ValueError: blocked=True
            else: blocked=False
        check('inconsistent third part blocks complete export',blocked and not (root/'bad-export.md').exists())
        start,end=locate(window.work.text,'只改第二场'); provider.value=dict(text=window.work.text[start:end].replace('按住','用肩膀抵住'),explanation='只改动作'); window.chat_request('只改第二场，保留台词'); wait_task(); check('modify updates correct range','用肩膀抵住' in window.work.text)
        check('modify keeps unresolved third draft',window.work.store.setting('v2_third_unsynced:'+window.work.document_id) and latest.split('第三部分',1)[1] in window.work.text)
        window.show_speech_conflict(); settle(); capture('speech-conflict')
        rebuild=next(b for b in window.inline.findChildren(QPushButton) if b.text()=='保留正文并重建台词'); QTest.mouseClick(rebuild,Qt.MouseButton.LeftButton); settle()
        check('explicit rebuild preserves prior draft and resolves',not window.work.store.setting('v2_third_unsynced:'+window.work.document_id) and bool(window.work.store.setting('v2_third_draft:'+window.work.document_id)))
        verify(window.work.text,window.work.store.setting('v2_speech:'+window.work.document_id)['records'])
        export=root/'export.md'
        with patch.object(QFileDialog,'getSaveFileName',return_value=(str(export),'')): window.export_work('md')
        check('export exact synchronized work',export.exists() and export.read_text(encoding='utf-8')==window.work.text)
        # Deterministic delayed response: no network and no timed race.
        from app.core.creation_flow import CreationFlow
        from app.providers.contracts import CancelToken
        flow=CreationFlow(window.work,ROOT/'resources',window.connections); snapshot=flow.prepare(window.connections.get(conn.id),'generate',development_test=True); provider.value=FixtureProvider().value; result=flow.service.execute(snapshot,CancelToken(),provider=provider)
        page.editor.append('请求后的手动改动'); window.save_work(); current=window.work.text
        try: flow.apply(snapshot,result)
        except RuntimeError: pass
        check('late response candidate survives',window.work.text==current and bool(window.work.store.setting('v2_candidates')))
        window.show_candidates(); settle(); capture('candidate-compare')
        revision=window.work.revision; apply_button=next(b for b in window.inline.findChildren(QPushButton) if b.text()=='应用为新版本' and b.isEnabled()); QTest.mouseClick(apply_button,Qt.MouseButton.LeftButton); settle()
        check('candidate applies only by explicit action as new revision',window.work.revision!=revision and window.inline is None and '第三部分' in window.work.text)
        current=window.work.text; window.generate(page,True); window.stop_task(); wait_task()
        check('cancel preserves original body and draft is candidate',window.work.text==current and any(not c['complete'] for c in window.work.store.setting('v2_candidates')) and window.work.store.setting('v2_generation_draft') is None)
        page.set_view(0); form.tabs.setCurrentIndex(0); page.settings_scroll.verticalScrollBar().setValue(0); capture('settings')
        window.toggle_assistant(); capture('ai-collapsed'); window.toggle_assistant(); capture('ai-restored')
        window.resize(1100,720); settle(); capture('narrow')
        check('narrow central settings uses one or two columns',form.basic_grid.columnCount()<=3 and form.cells['form'].width()>=120)
        for w in [page.generate_button,window.assistant.model,window.assistant.input,window.assistant.send_button]:
            bounds=QRect(w.mapTo(window,QPoint()),w.size()); check('narrow visible '+w.metaObject().className(),w.isVisible() and window.rect().contains(bounds))
        desktop=window.screen().availableGeometry(); window.resize(min(1100,desktop.width()-16),min(720,desktop.height()-40)); window.move(desktop.left()+4,desktop.top()+4); settle(); capture('screen-fit')
        check('client fits target desktop at current DPI',desktop.contains(window.frameGeometry()),frame=[window.frameGeometry().x(),window.frameGeometry().y(),window.frameGeometry().width(),window.frameGeometry().height()],desktop=[desktop.x(),desktop.y(),desktop.width(),desktop.height()])
        for w in [page.generate_button,window.assistant.model,window.assistant.input,window.assistant.send_button]:
            bounds=QRect(w.mapTo(window,QPoint()),w.size()); check('desktop-fit visible '+w.metaObject().className(),w.isVisible() and window.rect().contains(bounds))
        window.resize(1440,900); page.set_view(0); form.tabs.setCurrentIndex(5); form.fields['reference_name'].setText('某作品第2场'); form.add_reference(); check('name-only reference marked',form.state['references'][-1]['status']=='仅名称参考')
        form.tabs.setCurrentIndex(1); form.toggle_more(); saved=page.read_config(); project=window.work.store.root; window.save_work(); settle(); window.save_layout(); remembered=window.splitter.sizes()[1]; window.toggle_assistant(); window.close(); settle()
        window=MainWindow(Workspace(root/'data'),ROOT/'resources',prefs); window.show(); window.resize(1440,900); window.open_project(project); settle(); page=window.creators['script']; form=page.script_form
        check('restart collapsed assistant remembered',window.assistant.isHidden()); window.toggle_assistant(); settle(); check('restart width restores',abs(window.splitter.sizes()[1]-remembered)<=2,remembered=remembered,actual=window.splitter.sizes(),cached=window.assistant_width)
        restored=page.read_config(); check('restart unified state and references persist',restored['script_settings']==saved['script_settings'])
        window.new_work('script'); settle(); page=window.creators['script']; form=page.script_form; capture('empty-settings'); page.set_view(1); capture('empty-body')
        check('new work has silent-free automatic settings',page.read_config()['script_settings']['values']['language']=='auto' and page.location.currentText()=='暂无正文'); window.close(); settle()
    result=dict(device_scale=app.devicePixelRatio(),scale_factor=factor,platform=app.platformName(),mode='PySide6, isolated temporary data, fixed provider; no paid requests',checks=checks)
    (evidence/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    passed=sum(c['passed'] for c in checks); print(f'{passed}/{len(checks)} UI checks passed; DPR={app.devicePixelRatio()}; {evidence}')
    return 0 if passed==len(checks) else 1

if __name__=='__main__': raise SystemExit(main())
