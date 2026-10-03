"""Focused local-only checks of pane widths, sidebar and file-based notification sounds."""
import sys,tempfile,time,json,wave,struct,shutil,traceback
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtCore import Qt,QPoint,QThreadPool
from PySide6.QtWidgets import QApplication,QStyleOptionButton,QStyle
from PySide6.QtTest import QTest
from app.core.test_isolation import start_test_runtime
from app.core.services import Workspace
from app.ui.v2_window import MainWindow
from app.ui.notifications import audio_directory,available_audio,play_completion_sound

def main():
    app=QApplication([]); app.setProperty('native_hidden_test',True); errors=[]; checks=[]; sys.excepthook=lambda kind,value,tb:(errors.append(str(value)),traceback.print_exception(kind,value,tb))
    evidence=ROOT/'docs'/'evidence'/'panel_audio'; evidence.mkdir(parents=True,exist_ok=True)
    for filename,title in available_audio():
        with wave.open(str(audio_directory()/filename),'rb') as audio:
            assert audio.getnchannels()==1 and audio.getsampwidth()==2 and audio.getframerate()==44100 and .6<=audio.getnframes()/audio.getframerate()<=1
            samples=struct.unpack('<'+'h'*audio.getnframes(),audio.readframes(audio.getnframes())); assert max(abs(value) for value in samples)<10000 and abs(samples[-1])<20
    assert len(available_audio())==3; checks.append('three original WAVs: duration, PCM format, peak and smooth ending')
    with tempfile.TemporaryDirectory(prefix='panel-audio-',dir=ROOT/'logs') as temporary:
        base=start_test_runtime(Path(temporary)); prefs=base/'preferences.json'; w=MainWindow(Workspace(base/'internal_data'),ROOT/'resources',prefs); w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen); w.resize(1440,900); w.show(); app.processEvents()
        w.new_work('script'); app.processEvents(); original_width=w.sidebar.width(); QTest.mouseClick(w.sidebar_toggle,Qt.MouseButton.LeftButton); app.processEvents(); assert w.sidebar.width()==56 and w.options['sidebar_collapsed'] and not w.sidebar_toggle.icon().isNull(); assert json.loads(prefs.read_text(encoding='utf-8'))['sidebar_collapsed']
        QTest.mouseClick(w.sidebar_toggle,Qt.MouseButton.LeftButton); app.processEvents(); assert w.sidebar.width()==160 and not w.options['sidebar_collapsed']; checks.append('sidebar toggle, icons, accessibility and preference')
        for kind in ('script','novel','rewrite'):
            w.new_work(kind); app.processEvents(); page=w.creators[kind]; page.set_view(1); page.editor.setPlainText('左侧原稿保留。'); w.assistant.append('助手','右侧完整改稿候选，未应用。')
            QTest.mouseDClick(w.splitter_handle,Qt.MouseButton.LeftButton,pos=w.splitter_handle.rect().center()); app.processEvents(); sizes=w.splitter.sizes(); assert w.splitter.orientation()==Qt.Orientation.Horizontal and abs(sizes[0]-sizes[1])<=2,(kind,sizes,w.width())
            assert w.assistant.width()>420 and w.assistant_ratio>=.49 and page.editor.toPlainText()=='左侧原稿保留。' and '未应用' in w.assistant.chat.toPlainText(); assert w.splitter_handle.width()>=10
            w.splitter.moveSplitter(5,1); app.processEvents(); sizes=w.splitter.sizes(); assert sizes[1]/sum(sizes)<=.501,(kind,sizes)
            QTest.mouseClick(w.sidebar_toggle,Qt.MouseButton.LeftButton); app.processEvents(); assert w.sidebar.width()==56; sizes=w.splitter.sizes(); assert abs(sizes[0]-sizes[1])<=2
            QTest.mouseClick(w.sidebar_toggle,Qt.MouseButton.LeftButton); app.processEvents(); checks.append(kind+': 50% panes, resize limit, unchanged manuscript, sidebar layout')
        w.grab().save(str(evidence/'half-width.png')); ratio=w.assistant_ratio; w.set_assistant_visible(False); w.set_assistant_visible(True); app.processEvents(); assert abs(w.assistant_ratio-ratio)<.001
        for theme in ('清透白','石墨紫','暖纸色'):
            w.set_theme(theme); w.navigate(4); w.settings.tabs.setCurrentWidget(w.settings.advanced_tab); app.processEvents(); toggle=w.settings.sound_toggle; option=QStyleOptionButton(); option.initFrom(toggle); rect=toggle.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator,option,toggle)
            toggle.setChecked(False); app.processEvents(); off=toggle.grab().toImage().copy(rect); toggle.setChecked(True); app.processEvents(); on=toggle.grab().toImage().copy(rect); assert off!=on and rect.width()>=18
            on.save(str(evidence/('checkbox-on-'+theme+'.png'))); off.save(str(evidence/('checkbox-off-'+theme+'.png'))); checks.append(theme+': checkbox checked and unchecked visibly different')
        folder=base/'audio'; folder.mkdir()
        for filename,_ in available_audio(): shutil.copyfile(audio_directory()/filename,folder/filename)
        shutil.copyfile(folder/'gentle-bell.wav',folder/'custom-fixture.wav')
        import winsound
        with patch('app.ui.notifications.audio_directory',return_value=folder),patch.object(winsound,'PlaySound') as playback:
            settings=w.settings; settings.refresh_audio_files(); assert settings.sound_selector.count()==4
            for index in range(settings.sound_selector.count()):
                settings.sound_selector.setCurrentIndex(index); assert w.options.get('task_completion_audio',settings.sound_selector.currentData())==settings.sound_selector.currentData(); assert w.play_task_sound(force=True); assert Path(playback.call_args.args[0]).name==settings.sound_selector.currentData(); assert playback.call_args.args[1]&winsound.SND_FILENAME
            assert settings.sound_selector.findData('custom-fixture.wav')>=0; settings.sound_selector.setCurrentIndex(settings.sound_selector.findData('custom-fixture.wav')); w.grab().save(str(evidence/'sound-selection.png')); checks.append('built-in and custom WAV selection, persistence, exact file playback')
        assert not errors,errors; QThreadPool.globalInstance().waitForDone(2000); w.close(); app.processEvents()
        stored=json.loads(prefs.read_text(encoding='utf-8')); assert 'assistant_ratio' in stored and stored['task_completion_audio']=='custom-fixture.wav'
        restored=MainWindow(Workspace(base/'internal_data'),ROOT/'resources',prefs); restored.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen); restored.resize(1440,900); restored.show(); restored.new_work('script'); app.processEvents(); sizes=restored.splitter.sizes(); assert abs(sizes[0]-sizes[1])<=2; restored.close(); app.processEvents(); checks.append('reopen retains pane ratio and audio preference')
    (evidence/'results.json').write_text(json.dumps(dict(passed=checks,errors=errors,paid_calls=0,real_audio_played=False,build=False),ensure_ascii=False,indent=2),encoding='utf-8'); print('PASS',len(checks),'focused panel/audio groups; no real requests or speaker playback')

if __name__=='__main__': main()
