import json

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QLabel, QLineEdit, QListWidget, QTextEdit, QVBoxLayout)

from app.core.writing import WritingService
from app.storage.project import new_id

LABELS = {'idea_generate': '生成构思', 'outline_generate': '生成大纲', 'prose_generate': '生成小说正文',
          'screenplay_generate': '生成场次剧本', 'copy_generate': '生成文案', 'reference_analyze': '拆解文字/分镜来源',
          'rewrite_plan': '仿写新方案', 'adaptation_plan': '建立改编映射'}


def configure_creation(owner):
    if not owner.store:
        raise ValueError('请先打开项目')
    dialog = QDialog(owner)
    dialog.setWindowTitle('当前项目创作设定 · 未填字段不自动推断')
    dialog.resize(700, 600)
    layout = QVBoxLayout(dialog)
    old = owner.store.setting('creation_constraints', {})
    fields = {}
    form = QFormLayout()
    for key, label in [('topic','主题'),('primary_genre','主类型'),('subgenres','细分标签（逗号分隔）'),('audience','读者/观众'),
        ('purpose','用途/商业目的'),('tone','语气风格'),('perspective','叙事视角'),('target_length','目标字数'),('target_duration','目标秒数'),
        ('tolerance','长度/时长容差'),('allowed_new','允许新增范围')]:
        value = old.get(key, '')
        edit = QLineEdit(','.join(value) if isinstance(value, list) else str(value))
        fields[key] = edit
        form.addRow(label, edit)
    layout.addLayout(form)
    preserve = QTextEdit()
    preserve.setMaximumHeight(100)
    preserve.setPlaceholderText('每行一项必须保留事件，将分配稳定事件ID；不是锁定台词。')
    preserve.setPlainText('\n'.join(event['text'] for event in old.get('preserve_events', [])))
    layout.addWidget(QLabel('必须保留事件'))
    layout.addWidget(preserve)
    duration = QLineEdit(json.dumps(owner.store.setting('duration_estimation', dict(dialogue_chars_per_second=3.5,pause_per_line=.5,action_min_seconds=1.5,scene_change_seconds=1)), ensure_ascii=False))
    layout.addWidget(QLabel('时长估算初值可调：对白语速/句间停顿/动作/转场；结果均为预计，不是音频实测。'))
    layout.addWidget(duration)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        data = {key: edit.text().strip() for key, edit in fields.items() if edit.text().strip()}
        for key in ('target_length','target_duration','tolerance'):
            if key in data:
                data[key] = float(data[key])
                if data[key] <= 0:
                    raise ValueError('长度、时长及容差须为正数')
        if 'subgenres' in data:
            data['subgenres'] = [s.strip() for s in data['subgenres'].split(',') if s.strip()]
        previous = {event['text']: event['event_id'] for event in old.get('preserve_events', [])}
        events = [line.strip() for line in preserve.toPlainText().splitlines() if line.strip()]
        if len(set(events)) != len(events):
            raise ValueError('保留事件重复，请先合并')
        if events:
            data['preserve_events'] = [dict(event_id=previous.get(line, new_id()), text=line) for line in events]
        estimate_config = json.loads(duration.text())
        from app.core.writing import estimate_scene
        estimate_scene(dict(blocks=[]),estimate_config)
        owner.store.set_setting('creation_constraints', data)
        owner.store.set_setting('duration_estimation',estimate_config)
        owner.status.setText('创作设定已保存；不修改既有文稿，下一任务使用新快照')


def generate_workflow(owner):
    owner.require_document()
    dialog = QDialog(owner)
    dialog.setWindowTitle('创作阶段 · 候选先审核，模型请求可能计费')
    dialog.resize(740, 550)
    layout = QVBoxLayout(dialog)
    stage = QComboBox()
    for key, label in LABELS.items():
        stage.addItem(label, key)
    doc = owner.store.document(owner.document_id)
    initial = {'小说':'prose_generate','剧本':'screenplay_generate','文案':'copy_generate','reference':'reference_analyze'}.get(doc['kind'])
    stage.setCurrentIndex(stage.findData(initial))
    layout.addWidget(stage)
    instruction = QTextEdit()
    instruction.setPlaceholderText('明确本次目标；生成正文只生成当前章/场/单篇，不生成全项目。')
    instruction.setPlainText(owner.assistant_input.toPlainText())
    layout.addWidget(instruction, 1)
    plans = WritingService(owner.store).planning()
    chosen = QComboBox()
    chosen.addItem('不选用旧方案', None)
    for plan in plans:
        chosen.addItem(LABELS.get(plan['kind'], plan['kind']) + ' · ' + plan['title'], plan['id'])
    layout.addWidget(QLabel('选用一个已确认构思/大纲/拆解/改编方案，来源过期会阻止使用'))
    layout.addWidget(chosen)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText('发送本次阶段任务')
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        text = instruction.toPlainText().strip()
        if not text:
            raise ValueError('请填写创作目标，不虚构主题或人群')
        selected = [chosen.currentData()] if chosen.currentData() else []
        if stage.currentData() in {'outline_generate','rewrite_plan'} and not selected:
            raise ValueError('生成大纲/新方案前，先选择已确认构思或拆解')
        owner.start_text_task(stage_override=stage.currentData(), instruction_override=text, planning_ids=selected)


def planning_dialog(owner):
    if not owner.store:
        raise ValueError('请先打开项目')
    service = WritingService(owner.store)
    rows = service.planning()
    dialog = QDialog(owner)
    dialog.setWindowTitle('已确认创作规划 · 来源可追溯')
    dialog.resize(820, 580)
    layout = QVBoxLayout(dialog)
    items = QListWidget()
    for row in rows:
        items.addItem(LABELS.get(row['kind'], row['kind']) + ' · ' + row['title'])
    layout.addWidget(items, 1)
    preview = QTextEdit()
    preview.setReadOnly(True)
    layout.addWidget(preview, 1)
    def selected(index):
        if index >= 0:
            row = rows[index]
            status = '依据已更新' if owner.store.document(row['source_document_id'])['head'] != row['source_revision'] else '来源版本有效'
            preview.setPlainText(status + '\n' + json.dumps(row['payload'], ensure_ascii=False, indent=2))
    items.currentRowChanged.connect(selected)
    if rows:
        items.setCurrentRow(0)
    def materialize():
        index = items.currentRow()
        if index < 0:
            raise ValueError('请先选择含节点的方案')
        service.import_outline_nodes(rows[index]['id'])
        owner.refresh_documents(owner.document_id)
        owner.status.setText('方案节点已落实为稳定目录ID；已有正文保留')
    layout.addWidget(owner.button('将所选节点落实为项目目录', materialize))
    dialog.exec()
