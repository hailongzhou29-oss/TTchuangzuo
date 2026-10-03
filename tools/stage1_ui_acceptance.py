"""Isolated native Qt regression checks; no model calls or user credentials."""
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import Qt, QPoint, QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QFileDialog, QPushButton
from app.core.files import write_json
from app.core.services import Workspace
from app.ui.v2_window import MainWindow
from app.core.work_context import locate
from app.providers.contracts import Connection, TextResult


class FixtureProvider:
    def __init__(self):
        self.calls = 0
        self.messages = []
        self.value = dict(title='最后一分钟', outline='维修员为同伴争取最后一分钟。', scenes=[
            dict(title='机房·夜', nodes=[dict(type='action', speaker='', text='林远拉下开关。'), dict(type='dialogue', speaker='林远', text='只有一分钟。')]),
            dict(title='门外·夜', nodes=[dict(type='action', speaker='', text='阿宁按住门把。'), dict(type='dialogue', speaker='阿宁', text='我替你守住。')])])

    def generate(self, connection, secret, messages, cancel, on_text, **options):
        self.calls += 1
        self.messages = messages
        raw = json.dumps(self.value, ensure_ascii=False) if isinstance(self.value, dict) else self.value
        on_text(raw)
        return TextResult(text=raw, status='completed', model=connection.model, accepted=True)


def main():
    app = QApplication([])
    import os
    factor = os.environ.get('QT_SCALE_FACTOR')
    evidence = ROOT / 'docs' / 'evidence' / ('stage1_scale_' + factor.replace('.', '_') if factor else 'stage1')
    evidence.mkdir(parents=True, exist_ok=True)
    checks = []

    def check(name, condition, **details):
        checks.append(dict(check=name, passed=bool(condition), **details))

    def settle():
        app.processEvents()
        QTest.qWait(80)

    with tempfile.TemporaryDirectory(prefix='tt_stage1_') as temp:
        root = Path(temp)
        prefs = root / 'settings' / 'preferences.json'
        write_json(prefs, dict(restore_last=False, splitter_sizes=[900, 0]))
        window = MainWindow(Workspace(root / 'data'), ROOT / 'resources', prefs)
        window.show()
        window.navigate(1)
        settle()
        check('legacy zero-width layout recovers visible assistant',
              window.splitter.sizes()[1] >= 300,
              sizes=window.splitter.sizes(), toggle=window.assistant_toggle.text())
        window.grab().save(str(evidence / 'initial.png'))
        # Exercise a real splitter-handle drag as well as old persisted sizes.
        handle = window.splitter.handle(1)
        QTest.mousePress(handle, Qt.MouseButton.LeftButton)
        QTest.mouseMove(handle, handle.rect().center() + QPoint(1500, 0))
        QTest.mouseRelease(handle, Qt.MouseButton.LeftButton)
        settle()
        check('drag cannot reduce assistant to zero', window.splitter.sizes()[1] >= 300,
              sizes=window.splitter.sizes())
        for i in range(5):
            QTest.mouseClick(window.assistant_toggle, Qt.MouseButton.LeftButton)
            settle()
            check(f'collapse {i}', not window.assistant.isVisible())
            QTest.mouseClick(window.assistant_toggle, Qt.MouseButton.LeftButton)
            settle()
            check(f'restore {i}', window.assistant.isVisible() and window.splitter.sizes()[1] >= 300,
                  sizes=window.splitter.sizes())
        window.splitter.setSizes([850, 420])
        settle()
        window.save_layout()
        restored_width = window.splitter.sizes()[1]
        window.toggle_assistant()
        settle()
        window.toggle_assistant()
        settle()
        check('user resized width survives collapse', abs(window.splitter.sizes()[1] - restored_width) <= 2,
              sizes=window.splitter.sizes(), expected_width=restored_width)
        window.grab().save(str(evidence / 'restored.png'))
        for index in (0, 4, 2, 3, 1):
            window.navigate(index)
            settle()
            check(f'navigate {index}',
                  window.assistant.isVisible() == (1 <= index <= 3)
                  and (index not in (1, 2, 3) or window.splitter.sizes()[1] >= 300),
                  sizes=window.splitter.sizes())
        window.toggle_assistant()
        settle()
        window.grab().save(str(evidence / 'collapsed.png'))
        window.close()
        settle()
        check('collapse preserves expanded width in preferences',
              json.loads(prefs.read_text(encoding='utf-8'))['splitter_sizes'][1] >= 300)
        window = MainWindow(Workspace(root / 'data'), ROOT / 'resources', prefs)
        window.show()
        window.navigate(1)
        settle()
        check('restart preserves collapse', not window.assistant.isVisible())
        window.toggle_assistant()
        settle()
        check('restart restores assistant width', abs(window.splitter.sizes()[1] - restored_width) <= 2,
              sizes=window.splitter.sizes(), previous_width=restored_width)
        page = window.creators['script']
        page.fields['genre'].setCurrentIndex(page.fields['genre'].findData('G07'))
        page.fields['subgenres'].set_values(['G07.1', 'G07.2', 'G07.3'])
        page.idea.setPlainText('长文本与多选标签验证。' * 200)
        page.config_changed()
        check('long idea and multiple selections retain bindings',
              page.read_config()['subgenres'] == ['G07.1', 'G07.2', 'G07.3']
              and len(page.read_config()['idea']) == 2200)
        pane = QWidget()
        window.show_inline('隔离返回检查', pane)
        settle()
        window.close_inline()
        settle()
        check('inline return restores assistant', window.assistant.isVisible() and window.splitter.sizes()[1] >= 300)
        window.read_mode(page)
        settle()
        window.read_mode(page)
        settle()
        check('reading mode return restores assistant', window.assistant.isVisible() and window.splitter.sizes()[1] >= 300)
        for width, height in ((1100, 720), (1280, 800), (1440, 900)):
            window.resize(width, height)
            settle()
            check(f'resize {width}x{height} retains assistant width',
                  window.splitter.sizes()[1] >= 300 and window.pages.width() > 300,
                  sizes=window.splitter.sizes())
            for widget in (window.assistant.model, window.assistant.input, window.assistant.send_button):
                bounds = QRect(widget.mapTo(window.assistant, QPoint()), widget.size())
                check(f'resize {width}x{height} contains {widget.metaObject().className()}',
                      window.assistant.rect().contains(bounds) and widget.isVisible())
        window.assistant.input.setPlainText('保留人物关系，只检查当前作品。\n' * 120)
        check('long assistant input retains complete text',
              window.assistant.input.toPlainText().endswith('只检查当前作品。\n')
              and window.assistant.input.document().blockCount() == 121)
        window.resize(1100, 720)
        settle()
        check('narrow window composer visible',
              window.assistant.input.isVisible() and window.assistant.send_button.isVisible()
              and window.pages.width() > 300)
        window.grab().save(str(evidence / 'narrow.png'))
        page = window.creators['script']
        page.toggle_advanced()
        settle()
        check('basic settings remain available with advanced open', page.form_scroll.isVisible())
        check('settings view excludes the empty body editor', not page.editor.isVisible() and page.settings_scroll.isVisible())
        for index in range(6):
            page.advanced.setCurrentIndex(index)
            settle()
            check(f'details tab {index} fits current content',
                  page.advanced.currentWidget().isVisible()
                  and page.advanced.height() >= page.advanced.currentWidget().sizeHint().height())
        page.advanced.setCurrentIndex(0)
        window.grab().save(str(evidence / 'advanced.png'))
        page.toggle_advanced()
        page.idea.clear()
        window.resize(1440, 900)
        window.splitter.setSizes([870, 386])
        window.save_layout()
        provider = FixtureProvider()
        window.allow_test_connections = True
        window.text_test_provider = provider
        connection = Connection('fixture_stage1', '界面验证（固定响应）', 'custom', 'fixture', base_url='https://fixture.invalid', max_output=8192, context_limit=65536)
        window.connections.save(connection, 'fixture-secret')
        window.assistant.refresh_models()
        window.assistant.model.setCurrentIndex(window.assistant.model.findData(connection.id))
        page.script_form.set_value('time',['time.linear']); page.script_form.changed('time')
        page.script_form.set_value('density','density.03'); page.script_form.changed('density')
        page.settings_scroll.verticalScrollBar().setValue(0)
        settle()
        window.grab().save(str(evidence / 'settings.png'))

        def wait_task():
            until = time.monotonic() + 15
            while (window.active_task or window.segmented) and time.monotonic() < until:
                app.processEvents()
                QTest.qWait(20)
            settle()
            check('fixture task finishes', window.active_task is None and window.segmented is None)

        QTest.mouseClick(page.generate_button, Qt.MouseButton.LeftButton)
        wait_task()
        check('generate button uses provider and opens body',
              provider.calls == 1 and page.views.currentIndex() == 1
              and '第三部分｜完整人物台词' in page.editor.toPlainText())
        check('existing controls reach the real request',
              page.read_config()['dialogue_ratio'] == .75
              and 'time.linear' in provider.messages[1]['content']
              and '主要事件按发生先后推进' in provider.messages[0]['content'])
        check('generated body persists through existing store',
              window.work.store.document(window.work.document_id)['text'] == page.editor.toPlainText())
        window.grab().save(str(evidence / 'body.png'))
        QTest.mouseClick(page.view_tabs, Qt.MouseButton.LeftButton, pos=page.view_tabs.tabRect(0).center())
        settle()
        check('settings tab retains configuration and body',
              page.views.currentIndex() == 0 and not page.editor.isVisible()
              and page.fields['density'].currentText() == '语言密集')
        QTest.mouseClick(page.view_tabs, Qt.MouseButton.LeftButton, pos=page.view_tabs.tabRect(1).center())
        settle()
        page.editor.append('最新手工内容')
        window.save_work()
        before = window.work.text
        revision = window.work.revision
        provider.value = '已检查最新作品内容，未修改正文。'
        window.assistant.input.setPlainText('检查不要修改')
        QTest.mouseClick(window.assistant.send_button, Qt.MouseButton.LeftButton)
        wait_task()
        check('assistant send reads latest buffer without changing it',
              provider.calls == 2 and '最新手工内容' in provider.messages[1]['content']
              and window.work.text == before and window.work.revision == revision)
        start, end = locate(before, '只改第二场')
        provider.value = dict(text=before[start:end].replace('按住', '用肩膀抵住'), explanation='加强第二场动作，保留台词。')
        window.assistant.input.setPlainText('只改第二场，保留台词')
        QTest.mouseClick(window.assistant.send_button, Qt.MouseButton.LeftButton)
        wait_task()
        check('assistant modification keeps existing writeback',
              provider.calls == 3 and '用肩膀抵住' in window.work.text
              and window.work.text[:start] == before[:start])
        check('unresolved third draft survives assistant modification',
              window.work.store.setting('v2_third_unsynced:'+window.work.document_id) and '最新手工内容' in window.work.text)
        window.show_speech_conflict()
        rebuild=next(b for b in window.inline.findChildren(QPushButton) if b.text()=='保留正文并重建台词')
        QTest.mouseClick(rebuild,Qt.MouseButton.LeftButton); settle()
        export = root / 'export.md'
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(export), '')):
            window.export_work('md')
        check('existing export contains exactly the work', export.read_text(encoding='utf-8') == window.work.text)
        window.toggle_assistant()
        settle()
        cursor = page.editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(5, cursor.MoveMode.KeepAnchor)
        page.editor.setTextCursor(cursor)
        page.bind_selection()
        settle()
        check('selection modification restores collapsed assistant',
              window.assistant.isVisible() and window.bound_selection == (0, 5))
        window.assistant.clear_scope()
        page.set_view(0)
        page.show_find()
        settle()
        check('find switches to body and remains usable', page.views.currentIndex() == 1 and page.find_row.isVisible())
        page.find_row.hide()
        window.toggle_assistant()
        settle()
        window.grab().save(str(evidence / 'ai-collapsed.png'))
        window.toggle_assistant()
        settle()
        window.grab().save(str(evidence / 'ai-restored.png'))
        window.close()
        settle()
        remembered_width = json.loads(prefs.read_text(encoding='utf-8'))['splitter_sizes'][1]
        window = MainWindow(Workspace(root / 'data'), ROOT / 'resources', prefs)
        window.show()
        window.navigate(1)
        settle()
        check('restart while expanded restores width and label',
              window.assistant.isVisible()
              and abs(window.splitter.sizes()[1] - remembered_width) <= 2
              and window.assistant_toggle.text() == '收起 AI 助手',
              sizes=window.splitter.sizes(), expected_width=remembered_width)
        check('existing script resumes body', window.creators['script'].views.currentIndex() == 1)
        window.new_work('script')
        settle()
        check('new script starts in settings with no empty editor',
              window.creators['script'].views.currentIndex() == 0
              and not window.creators['script'].editor.isVisible()
              and window.creators['script'].fields['genre'].currentData() == 'auto')
        window.grab().save(str(evidence / 'empty-settings.png'))
        window.close()
        settle()
    result = dict(mode='isolated native Qt; fixed provider responses; no paid model calls; original layout image inspected',
                  device_scale=app.devicePixelRatio(), checks=checks)
    (evidence / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(row['passed'] for row in checks) else 1


if __name__ == '__main__':
    raise SystemExit(main())
