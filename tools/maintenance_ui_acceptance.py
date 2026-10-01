"""Native views/layout/background backup/budget settings without model calls."""
import json,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app.core.maintenance import diagnostics
from app.core.services import Workspace
from app.ui.budget_settings import BudgetSettingsPage
from app.ui.maintenance_settings import BackupSettingsPage
from app.ui.window import MainWindow

app=QApplication([])
checks=[]
evidence=ROOT/'docs'/'evidence'
with tempfile.TemporaryDirectory(prefix='TT 运维视图验收 ') as temporary:
    root=Path(temporary)
    workspace=Workspace(root/'data')
    project=workspace.create('隔离验收项目','小说')
    did=project.documents()[0]['id']
    doc=project.document(did)
    project.save_document(did,doc['head'],'PRIVATE_DOCUMENT_TEXT测试正文')
    prefs=root/'settings'/'preferences.json'
    window=MainWindow(workspace,ROOT/'resources',prefs)
    window.show()
    window.open_project(project.root)
    for index,name in [(1,'大纲'),(2,'对照'),(3,'审稿')]:
        window.view_combo.setCurrentIndex(index)
        QTest.qWait(25)
        checks.append(dict(check=name+'中央工作视图可切换，正文保留',passed=window.work_views.currentIndex()==index and project.document(did)['text']=='PRIVATE_DOCUMENT_TEXT测试正文'))
    window.view_combo.setCurrentIndex(4)
    window.exit_focus()
    checks.append(dict(check='专注Esc语义返回写作视图',passed=window.view_combo.currentIndex()==0 and window.work_views.currentIndex()==0))
    budget=BudgetSettingsPage(window)
    budget.calls['节省'].setValue(1)
    budget.enabled.setChecked(True)
    budget.task_amount.setText('1.25')
    budget.project_amount.setText('5')
    budget.save()
    saved=project.setting('budget_settings')
    checks.append(dict(check='预算控件保存当前项目范围和次数/币种',passed=saved['call_limits']['节省']==1 and saved['monetary_limits']['task_amount']=='1.25'))
    backup=BackupSettingsPage(window)
    backup.enabled.setChecked(True)
    backup.interval.setValue(1)
    backup.keep.setValue(2)
    backup.save()
    checks.append(dict(check='自动备份设置真实启用定时器',passed=window.backup_timer.isActive() and window.backup_timer.interval()==60000))
    window.start_automatic_backup(force=True)
    deadline=time.monotonic()+5
    while window.backup_operation and time.monotonic()<deadline:
        QTest.qWait(25)
    checks.append(dict(check='后台自动一致性备份实际落盘',passed=not window.backup_operation and len(list((project.root/'backups').glob('auto_*.ttbackup')))==1))
    checks.append(dict(check='诊断不含正文',passed='PRIVATE_DOCUMENT_TEXT' not in json.dumps(diagnostics(window))))
    window.sidebar.hide()
    window.save_preferences()
    window.close()
    reopened=MainWindow(workspace,ROOT/'resources',prefs)
    reopened.show()
    QTest.qWait(25)
    checks.append(dict(check='重开恢复相对布局而不把隐藏主窗误存为全隐藏',passed=reopened.sidebar.isHidden() and not reopened.directory.isHidden()))
    reopened.restore_layout_defaults()
    checks.append(dict(check='恢复默认字号与布局',passed=not reopened.sidebar.isHidden() and reopened.options['editor_font_size']==18))
    reopened.grab().save(str(evidence/'ui_布局恢复与工作视图.png'))
    reopened.close()
(evidence/'maintenance_ui_results.json').write_text(json.dumps(dict(mode='实际本地操作，无模型调用',checks=checks),ensure_ascii=False,indent=2),encoding='utf-8')
for check in checks:
    print(('PASS ' if check['passed'] else 'FAIL ')+check['check'])
if not all(check['passed'] for check in checks):
    raise SystemExit(1)
