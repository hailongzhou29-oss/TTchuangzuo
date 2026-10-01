"""Actual stage→candidate→adoption→confirmed dialogue export UI; fixed model response."""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from app.core.knowledge import FactService
from app.core.services import Workspace
from app.core.writing import WritingService
from app.providers.contracts import Connection, TextResult
from app.ui.window import MainWindow

app = QApplication([])
checks = []
evidence = ROOT / 'docs' / 'evidence'
with tempfile.TemporaryDirectory(prefix='TT 结构剧本验收 ') as temporary:
    root = Path(temporary)
    workspace = Workspace(root / 'data')
    store = workspace.create('结构化剧本 · 隔离验收', '剧本')
    source_id = store.documents()[0]['id']
    eid = FactService(store).add_entity('老师')
    script = dict(title='历史教室', outline='老师用原始材料回答学生的问题。', scenes=[dict(scene_id='S1',location='历史教室',time_of_day='日',interior_exterior='内',
        estimated_seconds=10,duration_status='estimated',blocks=[dict(block_id='A1',kind='action',text='老师展开地图。',order=0),
        dict(block_id='D1',kind='dialogue',speaker_id=eid,text='这句话逐字保留。',order=1)])])
    class Provider:
        def generate(self, connection, secret, messages, cancel, on_text, **kwargs):
            text=json.dumps(script,ensure_ascii=False)
            on_text(text)
            return TextResult(text=text,status='completed',finish_reason='stop',model='fixture')
    window=MainWindow(workspace,ROOT/'resources',root/'settings'/'preferences.json')
    window.show()
    window.open_project(store.root)
    window.connections.save(Connection('fixture','开发测试固定剧本','deepseek','fixture',base_url='https://example.invalid'),'fixture-key')
    window.refresh_models()
    window.start_text_task(stage_override='screenplay_generate',instruction_override='只生成一个场次，绑定老师。',provider=Provider())
    deadline=time.monotonic()+5
    while window.active_task and time.monotonic()<deadline:
        QTest.qWait(30)
    checks.append(dict(check='结构化候选在助手审核前不改原稿',passed=store.document(source_id)['text']=='' and window.review_candidate_button.isEnabled()))
    def accept_work():
        for dialog in app.topLevelWidgets():
            if dialog.windowTitle()=='作品/方案候选 · 来源稿与旧版本保留':
                button=next((b for b in dialog.findChildren(QPushButton) if b.text()=='采用作品'),None)
                if button:
                    QTest.mouseClick(button,Qt.MouseButton.LeftButton)
    QTimer.singleShot(100,accept_work)
    window.review_candidate()
    did=window.document_id
    checks.append(dict(check='实际采用到同项目新文档并保留来源',passed=did!=source_id and store.document(did)['source_id']==source_id and store.document(source_id)['text']==''))
    window.confirm_draft()
    export=WritingService(store).export_screenplay(did)
    checks.append(dict(check='确认后人物台词从数据导出且不混动作',passed='老师：这句话逐字保留。' in export.split('## 三、完整人物台词')[1] and '展开地图' not in export.split('## 三、完整人物台词')[1]))
    window.grab().save(str(evidence/'ui_结构化剧本与人物绑定.png'))
    window.navigation.setCurrentRow(6)
    QTest.qWait(60)
    page=window.cases_page
    page.query.setText('我的阿勒泰')
    QTest.qWait(30)
    checks.append(dict(check='案例界面按片名筛选并保持散文改编类型',passed=page.list.count()==1 and '散文集' in page.pages[2].toPlainText()))
    page.query.setText('Wolf Hall')
    checks.append(dict(check='案例界面多原作关系不覆盖',passed='Bring Up the Bodies' in page.pages[2].toPlainText() and 'Wolf Hall' in page.pages[2].toPlainText()))
    page.clear_filters()
    window.grab().save(str(evidence/'ui_案例库五页签与来源关系.png'))
    checks.append(dict(check='案例详情五页签与未知数据保留',passed=page.details.count()==5 and len(page.library.records(min_rating=8))==0))
    window.close()

(evidence/'writing_ui_results.json').write_text(json.dumps(dict(mode='隔离固定剧本响应与真实本地案例库，没有真实模型调用',checks=checks),ensure_ascii=False,indent=2),encoding='utf-8')
for check in checks:
    print(('PASS ' if check['passed'] else 'FAIL ')+check['check'])
if not all(check['passed'] for check in checks):
    raise SystemExit(1)
