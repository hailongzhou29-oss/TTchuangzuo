"""Actual Qt knowledge/rule dialogs and local fact confirmation; no generation."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from app.core.knowledge import FactService
from app.core.rules import ProjectRules
from app.core.services import Workspace
from app.ui.knowledge_dialog import KnowledgeDialog
from app.ui.window import MainWindow

app = QApplication([])
checks = []
evidence = ROOT / 'docs' / 'evidence'
with tempfile.TemporaryDirectory(prefix='TT 设定规则验收 ') as temporary:
    root = Path(temporary)
    workspace = Workspace(root / 'data')
    store = workspace.create('人物连续性 · 本地验收', '小说')
    did = store.documents()[0]['id']
    facts = FactService(store)
    eid = facts.add_entity('林舟')
    fid = facts.propose(eid, '第8章开始右手受伤。', valid_from=8)
    window = MainWindow(workspace, ROOT / 'resources', root / 'preferences.json')
    window.show()
    window.open_project(store.root)
    dialog = KnowledgeDialog(window)
    dialog.show()
    dialog.list.setCurrentRow(0)
    QTest.qWait(50)
    def approve_fact():
        for widget in app.topLevelWidgets():
            if isinstance(widget, QMessageBox) and widget.windowTitle() == '确认项目事实':
                widget.button(QMessageBox.StandardButton.Yes).click()
    QTimer.singleShot(80, approve_fact)
    dialog.set_state('confirmed')
    checks.append(dict(check='通过实际确认弹窗采用事实', passed=facts.get(fid)['state'] == 'confirmed'))
    dialog.timeline.setValue(2)
    dialog.filter.setCurrentIndex(1)
    checks.append(dict(check='第2章有效设定视图不显示第8章受伤', passed=dialog.list.count() == 0))
    dialog.timeline.setValue(8)
    checks.append(dict(check='第8章有效设定视图显示受伤', passed=dialog.list.count() == 1))
    dialog.grab().save(str(evidence / 'ui_人物事实与剧情区间.png'))
    dialog.close()
    window.navigation.setCurrentRow(8)
    QTest.qWait(70)
    window.grab().save(str(evidence / 'ui_规则库与基础目录.png'))
    checks.append(dict(check='规则页面包含14赛道核心与原有规则',passed=window.rule_list.count()==60 and any('历史剧情核心创作规则' in window.rule_list.item(i).text() for i in range(window.rule_list.count()))))
    rules = ProjectRules(store, ROOT / 'resources')
    package = dict(schema_version=1, rules=[dict(rule_id='CUSTOM_UI', version='ui-1', stages=['draft_patch'], applies_to=['小说'],
        title='角色动机约定', body='角色行动服从已确认动机。', priority=60, enabled=True, source='隔离UI测试')])
    rules.import_package(package)
    window.refresh_rules()
    checks.append(dict(check='项目规则刷新可见，内置资源不被覆盖', passed=window.rule_list.count() == 61))
    window.new_chat()
    checks.append(dict(check='新会话保留确认事实', passed=facts.get(fid)['state'] == 'confirmed'))
    window.close()

result = dict(mode='真实本地窗口与数据，无模型调用', checks=checks)
(evidence / 'knowledge_ui_results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
for check in checks:
    print(('PASS ' if check['passed'] else 'FAIL ') + check['check'])
if not all(check['passed'] for check in checks):
    raise SystemExit(1)
