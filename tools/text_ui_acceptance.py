"""Qt asynchronous assistant workflow using clearly marked fixed responses."""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from app.core.services import Workspace
from app.providers.contracts import Connection, TextResult
from app.ui.model_settings import SettingsDialog
from app.ui.window import MainWindow


class FixtureProvider:
    def generate(self, connection, secret, messages, cancel, on_text, **kwargs):
        text = '{"text":"乙：先听他的理由。"}'
        on_text(text[:10])
        time.sleep(.15)
        if cancel.cancelled:
            return TextResult(text=text[:10], status='cancelled', model=connection.model)
        on_text(text[10:])
        return TextResult(text=text, status='completed', finish_reason='stop', model=connection.model)


app = QApplication([])
checks = []
evidence = ROOT / 'docs' / 'evidence'
with tempfile.TemporaryDirectory(prefix='TT 助手界面验证 ') as temporary:
    directory = Path(temporary)
    workspace = Workspace(directory / 'data')
    window = MainWindow(workspace, ROOT / 'resources', directory / 'settings' / 'preferences.json')
    window.show()
    store = workspace.create('开发测试 · 固定响应', '剧本')
    did = store.documents()[0]['id']
    text = '甲：开始。\n乙：原句。\n结束。'
    store.save_document(did, store.document(did)['head'], text)
    window.open_project(store.root)
    window.connections.save(Connection('fixture', '开发测试固定响应', 'deepseek', 'fixture', base_url='https://example.invalid'), 'fixture-key-not-real')
    window.refresh_models()
    cursor = window.editor.textCursor()
    cursor.setPosition(text.index('乙'))
    cursor.setPosition(text.index('乙') + len('乙：原句。'), QTextCursor.MoveMode.KeepAnchor)
    window.editor.setTextCursor(cursor)
    window.assistant_mode.setCurrentIndex(1)
    window.assistant_input.setPlainText('只改选区，其他原文保留')
    window.start_text_task(provider=FixtureProvider())
    # Model a missing queued notification: completion must remain observable.
    window.active_task['worker'].signals.blockSignals(True)
    checks.append(dict(check='后台生成期间原稿不变', passed=store.document(did)['text'] == text))
    deadline = time.monotonic() + 5
    while window.active_task and time.monotonic() < deadline:
        QTest.qWait(30)
    finished=not window.active_task and window.review_candidate_button.isEnabled() and store.document(did)['text']==text
    with store.connection() as con:
        db_state=con.execute('SELECT state FROM tasks ORDER BY rowid DESC LIMIT 1').fetchone()[0]
    checks.append(dict(check='异步完成 / 输出合同检查 / 仅显示候选',passed=finished,
                       evidence=dict(active_worker=bool(window.active_task),candidate_enabled=window.review_candidate_button.isEnabled(),database_state=db_state)))
    checks.append(dict(check='完成信号不可用时仍恢复候选按钮',passed=finished))
    checks.append(dict(check='固定响应不会标成真实模型已测试', passed=window.connections.get('fixture').capability_status == '未验证' and '开发测试固定响应' in window.connection_notice.text()))
    def click_adopt():
        for dialog in app.topLevelWidgets():
            if dialog.windowTitle() == '修改建议 · 原稿尚未改变':
                button = next((b for b in dialog.findChildren(QPushButton) if b.text() == '接受修改'), None)
                if button:
                    QTest.mouseClick(button, __import__('PySide6.QtCore', fromlist=['Qt']).Qt.MouseButton.LeftButton)
    QTimer.singleShot(100, click_adopt)
    window.review_candidate()
    expected = '甲：开始。\n乙：先听他的理由。\n结束。'
    checks.append(dict(check='确认采纳一处 / 其他文字逐字保留', passed=store.document(did)['text'] == expected and window.editor.toPlainText() == expected))
    window.editor.undo()
    window.save()
    checks.append(dict(check='AI 采纳可撤销并保存为新版本', passed=store.document(did)['text'] == text))
    window.grab().save(str(evidence / 'ui_助手固定响应测试.png'))
    settings = SettingsDialog(window)
    settings.show()
    settings.tabs.setCurrentIndex(0)
    settings.select_connection(0)
    QTest.qWait(80)
    settings.grab().save(str(evidence / 'ui_文字模型设置.png'))
    checks.append(dict(check='设置不回显已保存 KEY', passed=not settings.key.text()))
    settings.close()
    # Switching projects while a request runs must not redirect its callback.
    window.assistant_input.setPlainText('再写一个版本')
    window.start_text_task(provider=FixtureProvider())
    other = workspace.create('另一个项目', '文案')
    other_id = other.documents()[0]['id']
    window.open_project(other.root)
    deadline = time.monotonic() + 5
    while window.active_task and time.monotonic() < deadline:
        QTest.qWait(30)
    checks.append(dict(check='切换项目后的回调不污染新项目', passed=window.chat_output.toPlainText() == '' and other.document(other_id)['text'] == ''))
    window.resize(1024, 640)
    QTest.qWait(80)
    def check_overlay():
        for dialog in app.topLevelWidgets():
            if dialog.windowTitle() == 'AI 创作助手':
                checks.append(dict(check='窄屏覆盖助手保留模型与发送控件', passed=window.assistant.isVisible() and window.model_combo.isVisible() and window.send_button.isVisible()))
                dialog.reject()
    QTimer.singleShot(100, check_overlay)
    window.toggle_assistant()
    checks.append(dict(check='关闭覆盖助手后恢复原分栏', passed=window.assistant.parent() == window.outer and not window.assistant.isVisible()))
    window.close()

result = dict(mode='开发测试固定响应，无真实模型调用', checks=checks)
(evidence / 'text_ui_results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
for check in checks:
    print(('PASS ' if check['passed'] else 'FAIL ') + check['check'])
if not all(check['passed'] for check in checks):
    raise SystemExit(1)
