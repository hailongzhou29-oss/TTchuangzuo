"""Local-only checks of settings completion state and notification routing."""
import sys,tempfile,time,json,traceback
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtCore import Qt,QThreadPool
from PySide6.QtWidgets import QApplication
from app.core.test_isolation import start_test_runtime
from app.core.services import Workspace
from app.ui.v2_window import MainWindow

def main():
    app=QApplication([]); app.setProperty('native_hidden_test',True); errors=[]; checks=[]
    def capture(kind,value,tb): errors.append(str(value)); traceback.print_exception(kind,value,tb)
    sys.excepthook=capture
    evidence=ROOT/'docs'/'evidence'/'ui_candidate_theme'; evidence.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='settings-feedback-',dir=ROOT/'logs') as temporary:
        base=start_test_runtime(Path(temporary)); w=MainWindow(Workspace(base/'internal_data'),ROOT/'resources',base/'preferences.json'); w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen); w.resize(1440,900); w.show(); w.navigate(4); app.processEvents(); settings=w.settings; key=settings.current_provider(); status=settings.status
        def wait():
            limit=time.monotonic()+5
            while settings.operations and time.monotonic()<limit: app.processEvents(); time.sleep(.015)
            app.processEvents(); assert not settings.operations and not errors,errors
        with patch.object(settings.c,'list_models',return_value=[{'id':'fixture-model-'+str(i)} for i in range(3)]),patch.object(w,'play_task_sound',return_value=True) as sound:
            settings.load_models(key); assert status.busy and '读取模型' in status.caption.text(); wait()
            assert not status.busy and not status.feedback_timer.isActive() and not status.spinner.timer.isActive() and '3' in status.text() and '完成' in status.text() and '正在' not in status.caption.text(); assert sound.call_count==1
            assert settings.status_stack.mapTo(settings,settings.status_stack.rect().topLeft()).y()<settings.tabs.y()
            w.grab().save(str(evidence/'settings-models-completed.png')); checks.append('model list: accurate completed status, no remaining spinner, feedback in heading')
        with patch.object(w,'play_task_sound',return_value=True) as sound:
            settings.operation(lambda:(_ for _ in ()).throw(ValueError('fixture failure')),lambda result:None,status,title='读取模型'); wait(); assert not status.busy and 'fixture failure' in status.text() and sound.call_count==0; checks.append('failed operation: stops feedback and does not play completion sound')
            settings.operation(lambda:3,lambda result:None,status,title='读取模型'); wait(); assert status.text()=='读取模型完成' and sound.call_count==1; checks.append('callback without own status: processing text cleared at completion')
        app.setProperty('native_hidden_test',False)
        with patch('app.ui.notifications.play_completion_sound',return_value=True) as sound:
            settings.sound_toggle.setChecked(False); assert w.options['task_completion_sound'] is False and not w.play_task_sound(); sound.assert_not_called()
            assert w.play_task_sound(force=True); settings.sound_toggle.setChecked(True); assert w.play_task_sound() and sound.call_count==2
            settings.tabs.setCurrentWidget(settings.advanced_tab); app.processEvents(); w.grab().save(str(evidence/'settings-sound.png')); checks.append('sound switch persists; disabled tasks silent; preview and enabled completion route to audio')
        import winsound
        from app.ui.notifications import play_completion_sound
        with patch.object(winsound,'PlaySound') as playback:
            assert play_completion_sound(); assert playback.call_count==1 and playback.call_args.args[1]&winsound.SND_ASYNC
        app.setProperty('native_hidden_test',True); QThreadPool.globalInstance().waitForDone(2000); w.close(); app.processEvents()
    (evidence/'settings-results.json').write_text(json.dumps(dict(passed=checks,unhandled_errors=errors,real_audio_played=False,paid_calls=0,build=False),ensure_ascii=False,indent=2),encoding='utf-8'); print('PASS',len(checks),'settings checks; audio dispatch mocked, no real requests')

if __name__=='__main__': main()
