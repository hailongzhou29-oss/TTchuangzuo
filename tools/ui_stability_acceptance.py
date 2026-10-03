"""Isolated spec acceptance; default offscreen, native hidden or one visible run."""
import argparse
import copy
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
parser=argparse.ArgumentParser(); parser.add_argument('--native-hidden',action='store_true'); parser.add_argument('--visible',action='store_true'); args=parser.parse_args()
if not args.native_hidden and not args.visible: os.environ['QT_QPA_PLATFORM']='offscreen'
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtCore import Qt,QObject,QEvent,QPoint,QPointF,QTimer
from PySide6.QtGui import QInputMethodEvent,QWheelEvent
from PySide6.QtWidgets import QApplication,QWidget,QPushButton,QTextEdit,QLabel,QMainWindow
from PySide6.QtTest import QTest
from app.ui.v2_window import MainWindow
from app.ui.interaction import TOKENS,ui_font,system_high_contrast
from app.ui.v2_widgets import ChatInput
from app.core.services import Workspace
from app.core.files import write_json
from app.core.script_settings import migrate,active_settings,CATALOG,VERSION

class WindowSpy(QObject):
    def __init__(self): super().__init__(); self.shows=[]
    def eventFilter(self,widget,event):
        if event.type()==QEvent.Type.Show and isinstance(widget,QWidget) and widget.isWindow():
            self.shows.append(dict(type=type(widget).__name__,object=widget.objectName(),parent=type(widget.parent()).__name__ if widget.parent() else None,title=widget.windowTitle()))
        return False

def visible_windows():
    result=[]
    if os.name!='nt': return result
    callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
    def visit(hwnd,_):
        pid=ctypes.c_ulong(); ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value==os.getpid() and ctypes.windll.user32.IsWindowVisible(hwnd):
            title=ctypes.create_unicode_buffer(256); ctypes.windll.user32.GetWindowTextW(hwnd,title,256); result.append(title.value)
        return True
    ctypes.windll.user32.EnumWindows(callback(visit),0); return result

def main():
    app=QApplication([]); app.setProperty('native_hidden_test',args.native_hidden)
    spy=WindowSpy(); app.installEventFilter(spy); checks=[]; frames=[]; timings=[]; feedback=[]
    mode='visible' if args.visible else 'native-hidden' if args.native_hidden else 'offscreen'
    folder=ROOT/'docs/evidence'/('ui_stability_'+mode+'_'+os.environ.get('QT_SCALE_FACTOR','native').replace('.','_')); folder.mkdir(parents=True,exist_ok=True)
    result=dict(pid=os.getpid(),mode=mode,platform=app.platformName(),font=ui_font().family(),checks=checks,timings_ms=timings,system_high_contrast=system_high_contrast())
    def check(name,value,**detail):
        if args.native_hidden and name in ('typing preserves focus scroll','mouse hover previews without saving','keyboard single commit restores focus','body view retains scroll and focus'):
            result.setdefault('not_run',[]).append(dict(check=name,reason='Native hidden windows cannot receive OS focus/hover; measured in visible run instead')); return
        checks.append(dict(check=name,passed=bool(value),**detail))
        if not value: print('FAIL',name,json.dumps(detail,ensure_ascii=True))
    def settle(ms=35): app.processEvents(); QTest.qWait(ms); app.processEvents()
    def capture(name):
        settle(170); image=window.grab(); image.save(str(folder/(name+'.png')))
    with tempfile.TemporaryDirectory(prefix='tt_ui_stability_') as temporary:
        root=Path(temporary); prefs=root/'preferences.json'; write_json(prefs,dict(restore_last=False,autosave=False))
        window=MainWindow(Workspace(root/'data'),ROOT/'resources',prefs)
        if args.native_hidden: window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        window.show(); window.new_work('script'); page=window.creators['script']; form=page.script_form
        if args.visible: window.raise_(); window.activateWindow()
        settle(50); result['initial_screen_fit_size']=[window.width(),window.height()]; capture('00-initial-screen-fit')
        recorder=QTimer(); recorder.setInterval(200)
        def record():
            if len(frames)<220: frames.append((time.perf_counter(),window.grab().toImage().scaled(960,600,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.FastTransformation)))
        if args.visible: recorder.timeout.connect(record); recorder.start()
        # Visible acceptance respects the actual monitor; hidden tests use a fixed logical viewport.
        if not args.visible: window.resize(1440,900)
        settle(170); result.update(dpr=window.devicePixelRatioF(),logical_size=[window.width(),window.height()],available_screen=[window.screen().availableGeometry().width(),window.screen().availableGeometry().height()])
        def choose(key,value): form.set_value(key,value); form.changed(key); settle()
        capture('01-default-settings'); check('main controls minimum height',all(form.fields[k].height()>=36 for k in ['form','genre','duration_label','mode','language','view','carrier']))
        check('presentation initially explicit closed',form.presentation_tabs.isHidden()); check('base supplement header same card',form.basic_more.parentWidget() is form.basic_card)
        choose('form','form.03'); form.toggle_basic_more(); settle()
        check('single supplement spans full inner card',form.cells['form_detail'].width()>=form.basic_card.width()-40,width=form.cells['form_detail'].width(),card=form.basic_card.width())
        capture('02-basic-supplement')
        choose('view','view.follow'); form.toggle_presentation(); choose('role','role.01'); choose('role_detail','custom:关联身份'); settle()
        positions={k:form.fields[k].mapTo(page,QPoint()).y() for k in ['role','role_detail','role_name']}
        if form.columns==3: check('identity controls aligned with custom below',len(set(positions.values()))==1,positions=positions)
        check('custom detail full row',form.custom_cells['role_detail'].width()>=form.presentation_card.width()-40)
        field=form.custom['role_detail']; page.settings_scroll.ensureWidgetVisible(field); field.setFocus(); settle()
        before=page.settings_scroll.verticalScrollBar().value()
        with patch.object(form,'reflow',wraps=form.reflow) as reflow,patch.object(form,'layout_cells',wraps=form.layout_cells) as grids:
            for i in range(10): field.setText('中文输入'+str(i)); settle(5)
            check('ten text edits cause no reflow',reflow.call_count==0 and grids.call_count==0,reflow=reflow.call_count,grids=grids.call_count)
        check('typing preserves focus scroll',app.focusWidget() is field and page.settings_scroll.verticalScrollBar().value()==before,focus=type(app.focusWidget()).__name__)
        capture('03-custom-identity')
        form.presentation_tabs.setCurrentIndex(1); choose('carrier','carrier.07'); choose('position','不应生效的旧设备位置')
        check('public source excludes device position',form.cells['position'].isHidden() and 'position' not in active_settings(page.read_config())['explicit'])
        capture('04-public-carrier')
        form.presentation_tabs.setCurrentIndex(2); settle(); check('narrative six groups visible',all(form.cells[k].isVisible() for k in ['time','info','thread','suspense','reversal','rhetoric']))
        # Actual mouse coordinates in the Qt popup, distinct hover / keyboard / saved state.
        combo=form.fields['genre']; page.settings_scroll.ensureWidgetVisible(combo); combo.setFocus(); old=combo.currentIndex(); QTest.mouseClick(combo,Qt.MouseButton.LeftButton); settle(150); popup=combo.choice_popup
        check('single popup opens by pointer click',popup is not None)
        second=popup.list.item(1); QTest.mouseMove(popup.list.viewport(),popup.list.visualItemRect(second).center()); settle()
        check('mouse hover previews without saving',combo.currentIndex()==old and popup.list.hovered==1)
        QTest.keyClick(popup.list,Qt.Key.Key_Escape); settle(); check('Escape discards single preview',combo.currentIndex()==old and combo.choice_popup is None)
        combo.showPopup(); settle(); popup=combo.choice_popup; QTest.keyClick(popup.list,Qt.Key.Key_End); check('End previews last row without committing',popup.list.currentRow()==popup.list.count()-1 and combo.currentIndex()==old); QTest.keyClick(popup.list,Qt.Key.Key_Home); check('Home previews first row',popup.list.currentRow()==0); QTest.keyClick(popup.list,Qt.Key.Key_Tab); settle(); check('Tab closes popup safely',combo.choice_popup is None)
        combo.showPopup(); settle(); QTest.keyClick(combo.choice_popup.list,Qt.Key.Key_Backtab); settle(); check('Shift Tab closes popup safely',combo.choice_popup is None)
        available=combo.screen().availableGeometry()
        for name,x,y in [('top-left',available.left()+1,available.top()+1),('top-right',available.right()-5,available.top()+1),('bottom-left',available.left()+1,available.bottom()-5),('bottom-right',available.right()-5,available.bottom()-5)]:
            with patch.object(combo,'mapToGlobal',side_effect=lambda point,x=x,y=y:QPoint(x+point.x(),y+point.y())):
                combo.showPopup(); settle(); popup=combo.choice_popup; popup.position(); check('popup stays inside screen '+name,available.contains(popup.geometry()),geometry=[popup.x(),popup.y(),popup.width(),popup.height()]); combo.hidePopup(); settle()
        combo.showPopup(); settle(); popup=combo.choice_popup; QTest.keyClick(popup.list,Qt.Key.Key_Down); QTest.keyClick(popup.list,Qt.Key.Key_Return); settle(); check('keyboard single commit restores focus',combo.currentIndex()!=old and app.focusWidget() is combo)
        wheel=QWheelEvent(QPointF(5,5),QPointF(combo.mapToGlobal(QPoint(5,5))),QPoint(),QPoint(0,-120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        saved=combo.currentIndex(); app.sendEvent(combo,wheel); check('closed wheel does not change value',combo.currentIndex()==saved)
        form.presentation_tabs.setCurrentIndex(2); settle(); multi=form.fields['time'].control; multi.open_menu(); settle(150); popup=multi.last_menu
        saved=multi.values.copy(); QTest.mouseClick(popup.list.viewport(),Qt.MouseButton.LeftButton,pos=popup.list.visualItemRect(popup.list.item(0)).center()); settle()
        check('multiselect one click once stays open',multi.values==saved+[popup.list.item(0).data(Qt.ItemDataRole.UserRole)] and popup.isVisible())
        popup.search.setText('不存在的选项'); settle(); check('search preserves choices and empty indication',multi.values and popup.empty.isVisible())
        popup.search.clear(); popup.open_custom(); popup.custom.setText('中文自定义'); event=QInputMethodEvent('拼音选词',[]); app.sendEvent(popup.custom,event); QTest.keyClick(popup.custom,Qt.Key.Key_Return)
        check('IME Enter cannot add custom during composition','custom:中文自定义' not in multi.values)
        commit=QInputMethodEvent(); commit.setCommitString('确认'); app.sendEvent(popup.custom,commit); QTest.keyClick(popup.custom,Qt.Key.Key_Return); settle()
        check('committed IME custom adds once',multi.values.count('custom:中文自定义确认')==1)
        capture('05-menu-states'); popup.close(); settle()
        chat=ChatInput(); chat.setParent(window); chat.setVisible(False); sent=[]; chat.send.connect(lambda:sent.append(True)); app.sendEvent(chat,QInputMethodEvent('候选',[])); QTest.keyClick(chat,Qt.Key.Key_Return); check('chat IME confirm cannot send',not sent); app.sendEvent(chat,QInputMethodEvent()); QTest.keyClick(chat,Qt.Key.Key_Return,Qt.KeyboardModifier.ShiftModifier); check('Shift Enter remains newline',not sent)
        heights={}
        for i in range(6):
            page.settings_scroll.ensureWidgetVisible(form.tabs.bar); QTest.mouseClick(form.tabs.bar,Qt.MouseButton.LeftButton,pos=form.tabs.bar.tabRect(i).center()); settle(); heights[form.tabs.bar.tabText(i)]=form.details_card.height(); check('detail tab usable '+str(i),form.tabs.currentWidget().height()>0 and form.tabs.currentIndex()==i); capture('06-detail-'+str(i))
        check('tab height uses current content',len(set(heights.values()))>1,heights=heights)
        choose('view','view.follow'); form.presentation_tabs.setCurrentIndex(0); choose('role_detail','custom:稳定基线')
        # Twenty operation cycles exercise data, parent drafts, layout, focus and width restoration.
        for cycle in range(20):
            started=time.perf_counter(); choose('genre','G04'); choose('subgenres',['G04.1','custom:多选长中文标签'*4]); choose('genre','G11'); choose('genre','G04')
            field=form.custom['role_detail']; page.settings_scroll.ensureWidgetVisible(field); field.setFocus(); response=time.perf_counter(); field.setText('第'+str(cycle)+'轮中文修改'); app.processEvents(); feedback.append(round((time.perf_counter()-response)*1000,2)); settle(5)
            stable_scroll=page.settings_scroll.verticalScrollBar().value(); form.toggle_basic_more(); form.toggle_basic_more(); form.toggle_presentation(); form.toggle_presentation(); form.tabs.setCurrentIndex(cycle%6); settle()
            remembered=window.assistant_width; window.toggle_assistant(); window.toggle_assistant(); settle(); check('cycle assistant restore '+str(cycle),window.assistant.isVisible() and window.assistant_width==remembered)
            window.resize(1000 if cycle%2 else 1440,760); settle(); window.resize(1440,900); settle()
            check('cycle keeps parent and unrelated text '+str(cycle),form.value('subgenres')==['G04.1','custom:多选长中文标签'*4] and form.custom['role_detail'].text()=='第'+str(cycle)+'轮中文修改')
            timings.append(round((time.perf_counter()-started)*1000,2))
        # No visible OS field windows may be created by reflows.
        extras=[record for record in spy.shows if record['parent'] is None and record['type']!='MainWindow']
        check('no accidental unparented field windows',not extras,extras=extras)
        choose('genre','auto'); form.basic_expanded=False; form.presentation_expanded=False; form.reflow(); page.settings_scroll.verticalScrollBar().setValue(0); capture('07-assistant-restored')
        width=window.assistant_width; window.toggle_assistant(); capture('08-assistant-collapsed'); window.toggle_assistant(); settle(); check('restored valid assistant width',window.assistant_width==width and 300<=width<=420)
        page.set_view(1); page.editor.setPlainText('真实 Qt 运行验收文本。\n'+('长正文，用于滚动恢复检查。\n'*100)); page.editor.setFocus(); page.editor.verticalScrollBar().setValue(160); position=page.editor.verticalScrollBar().value(); page.set_view(0); page.set_view(1); settle(); check('body view retains scroll and focus',page.editor.verticalScrollBar().value()==position and app.focusWidget() is page.editor); capture('09-body-view'); page.set_view(0)
        for target in [0,2,3,1]: window.navigate(target); settle()
        check('page navigation returns usable script and same assistant',window.current_page() is page and window.assistant.isVisible())
        window.resize(720,620); settle(); check('narrow assistant is child overlay',window.assistant_overlay and not window.assistant.isWindow()); permanent=window.options.get('assistant_collapsed',False); window.toggle_assistant(); check('temporary overlay close preserves preference',window.options.get('assistant_collapsed',False)==permanent); capture('10-narrow-closed'); window.toggle_assistant(); capture('11-narrow-overlay')
        window.resize(560,580); window.set_assistant_visible(False); settle(); check('very narrow settings choose one column',form.columns==1,columns=form.columns); capture('11b-very-narrow-one-column')
        window.resize(720,620); window.set_assistant_visible(True); settle()
        for theme in TOKENS:
            window.set_theme(theme); settle(); capture('12-theme-'+str(list(TOKENS).index(theme)))
        window.set_theme('清透白'); window.options['reduce_motion']=True; window.motion.fade(form.basic_card,160); check('reduced motion adds no animation',not window.motion.running); window.options['reduce_motion']=False
        for _ in range(20): window.motion.fade(form.basic_card,160)
        check('rapid animation replaces prior target',len(window.motion.running)==1); window.motion.stop_all(); check('cancel cleans graphics effect',not window.motion.running and form.basic_card.graphicsEffect() is None)
        original=dict(kind='script',advanced={'叙事对象':'人物一生'}); migrated=migrate(original); check('known life subject migrates losslessly',migrated['script_settings']['values'].get('subject')=='subject.01' and migrated['script_settings']['migration_original']==original)
        loaded=copy.deepcopy(migrated); loaded['script_settings']['values'].pop('subject'); loaded['script_settings']['unresolved']=[dict(source='advanced.叙事对象',value='人物一生')]; check('already migrated known subject repaired',migrate(loaded)['script_settings']['values'].get('subject')=='subject.01')
        form.state['unresolved']=[dict(source='advanced.旧未知要求',value='必须保留手工限制')]; form.reflow(); form.show_history(); settle(); check('migration primary panel is Chinese actions',not window.inline.findChildren(QTextEdit) and any(b.text()=='保留为补充要求' for b in window.inline.findChildren(QPushButton))); capture('13-migration-handling')
        retain=next(b for b in window.inline.findChildren(QPushButton) if b.text()=='保留为补充要求'); QTest.mouseClick(retain,Qt.MouseButton.LeftButton); settle(); check('retained requirement takes effect without original loss','必须保留手工限制' in active_settings(page.read_config())['explicit'].get('retained_requirements','') and not form.state['unresolved']); window.close_inline()
        window.resize(1440,900); settle(); window.assistant.model.setCurrentIndex(0); window.generate(page); settle(); check('no-model generate locates selector without task',window.active_task is None and window.assistant.model.choice_popup is not None); window.assistant.model.hidePopup(); settle()
        # Explicit failure preserves the pending input and permits a retry.
        field=form.fields['role_name']; field.setText('保存失败也不丢的名字'); settle()
        with patch.object(window,'save_page_draft',side_effect=OSError('模拟写入失败')): window.run(page.flush_draft)
        check('save failure honest and input retained',page.saved.text()=='保存失败' and field.text()=='保存失败也不丢的名字'); page.flush_draft(); check('save can retry',page.saved.text()!='保存失败')
        page.flush_draft(); stored=json.loads(prefs.read_text(encoding='utf-8')); check('disk draft contains latest Chinese',stored['draft:script']['script_settings']['values']['role_name']=='保存失败也不丢的名字')
        form.basic_expanded=True; form.presentation_expanded=True; form.tabs.setCurrentIndex(4); form.presentation_tabs.setCurrentIndex(1); form.reflow(); page.set_view(0); page.save_ui_state()
        result['owned_visible_windows']=visible_windows(); result['qt_show_events']=spy.shows
        if args.native_hidden: check('native hidden tests expose no owned OS window',not result['owned_visible_windows'])
        if args.visible: check('controlled native run one main OS window',result['owned_visible_windows']==['TT创作助手 · 开发版'])
        window.close(); settle(170)
        recorder.stop(); result['text_edit_event_processed_ms']=feedback
        if not args.visible:
            restored=MainWindow(Workspace(root/'data'),ROOT/'resources',prefs)
            if args.native_hidden: restored.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
            restored.show(); restored.navigate(1); settle(); restored_form=restored.creators['script'].script_form; check('restart restores latest script draft',restored_form.value('role_name')=='保存失败也不丢的名字'); check('restart restores panel and tab state',restored_form.basic_expanded and restored_form.presentation_expanded and restored_form.tabs.currentIndex()==4 and restored_form.presentation_tabs.currentIndex()==1); restored.close(); settle()
    if frames:
        frame_dir=folder/'frames'; frame_dir.mkdir(exist_ok=True); lines=[]
        for i,(stamp,frame) in enumerate(frames):
            frame.save(str(frame_dir/(f'{i:04d}.png'))); lines.append(f"file 'frames/{i:04d}.png'")
            duration=frames[i+1][0]-stamp if i+1<len(frames) else .2; lines.append(f'duration {duration:.4f}')
        lines.append(f"file 'frames/{len(frames)-1:04d}.png'"); listing=folder/'recording-frames.txt'; listing.write_text('\n'.join(lines),encoding='utf-8')
        ffmpeg=shutil.which('ffmpeg')
        if ffmpeg:
            encoded=subprocess.run([ffmpeg,'-y','-f','concat','-safe','0','-i',str(listing),'-vsync','vfr','-vf','pad=960:600:(ow-iw)/2:(oh-ih)/2,format=yuv420p','-c:v','libx264','-preset','veryfast','-crf','24','-movflags','+faststart',str(folder/'实际操作录屏.mp4')],capture_output=True,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            (folder/'recording-encode.log').write_text(encoded.stderr,encoding='utf-8')
            result['recording']=dict(format='MP4',frames=len(frames),capture_interval_ms=200,encoded=encoded.returncode==0,description='Timer recording of owned native application only; actual capture intervals, scaled to fit 960x600')
        else: result['recording']='PNG recording frames retained; ffmpeg unavailable'
    result.update(passed=sum(c['passed'] for c in checks),total=len(checks)); (folder/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(result=str(folder/'results.json'),passed=result['passed'],total=result['total'],pid=result['pid'],platform=result['platform'],dpr=result['dpr']),ensure_ascii=True)); return 0 if result['passed']==result['total'] else 1

if __name__=='__main__': raise SystemExit(main())
