import json
from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
    QLabel, QLineEdit, QSpinBox, QTextEdit, QVBoxLayout)

from app.core.rules import ProjectRules
from app.storage.project import new_id


def edit_rule(owner, rule=None):
    if not owner.store:
        raise ValueError('请先打开项目；规则覆盖保存在当前项目')
    service = ProjectRules(owner.store, owner.resources)
    dialog = QDialog(owner)
    dialog.setWindowTitle('项目规则版本 · 修改只影响新任务')
    dialog.resize(800, 620)
    layout = QVBoxLayout(dialog)
    form = QFormLayout()
    rid = QLineEdit(rule['rule_id'] if rule else 'CUSTOM_' + new_id()[:8].upper())
    title = QLineEdit(rule['title'] if rule else '')
    version = QLineEdit('project-' + new_id()[:8])
    stages = QLineEdit(','.join(rule.get('stages', [])) if rule else 'draft_patch')
    kinds = QLineEdit(','.join(rule.get('applies_to', [])) if rule else '')
    priority = QSpinBox()
    priority.setRange(1, 100)
    priority.setValue(rule.get('priority', 50) if rule else 50)
    enabled = QCheckBox('启用这份规则')
    enabled.setChecked(rule.get('enabled', True) if rule else True)
    for name, widget in [('规则 ID', rid), ('名称', title), ('新版本', version), ('适用阶段（逗号分隔）', stages), ('形式（小说/剧本/文案，留空通用）', kinds), ('建议优先级', priority)]:
        form.addRow(name, widget)
    layout.addLayout(form)
    body = QTextEdit()
    body.setPlainText(rule['body'] if rule else '')
    layout.addWidget(body, 1)
    layout.addWidget(enabled)
    notice = QLabel('程序安全、文字锁和本次明确要求优先于类型建议。正文仅作规则文本，不加载可执行脚本。')
    notice.setWordWrap(True)
    layout.addWidget(notice)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Save).setText('预览后保存新版本')
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        data = dict(schema_version=1, rules=[dict(rule_id=rid.text().strip(), title=title.text().strip(), version=version.text().strip(),
            stages=[s.strip() for s in stages.text().split(',') if s.strip()], applies_to=[s.strip() for s in kinds.text().split(',') if s.strip()],
            body=body.toPlainText(), priority=priority.value(), enabled=enabled.isChecked(), source=(rule.get('source') if rule else None) or '用户在当前项目编辑')])
        preview_and_import(owner, service, data)


def preview_and_import(owner, service, data):
    preview = service.preview_package(data)
    dialog = QDialog(owner)
    dialog.setWindowTitle('规则覆盖预览 · 不修改已有任务快照')
    dialog.resize(780, 570)
    layout = QVBoxLayout(dialog)
    details = QTextEdit()
    details.setReadOnly(True)
    lines = []
    for item in preview:
        rule = item['rule']
        previous = item['previous']
        lines.append(f"{item['change']} {rule['rule_id']} {rule['title']}\n版本：{previous['version'] if previous else '未配置'} → {rule['version']}\n阶段：{rule['stages']}\n形式：{rule['applies_to']}\n正文：\n{rule['body']}")
    details.setPlainText('\n\n'.join(lines))
    layout.addWidget(details, 1)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText('确认导入当前项目')
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        service.import_package(data)
        owner.refresh_rules()


def load_package(path):
    path = Path(path)
    if path.suffix.lower() != '.json' or path.stat().st_size > 2 * 1024**2:
        raise ValueError('规则包仅支持不超过 2MB 的 JSON 文件')
    return json.loads(path.read_text(encoding='utf-8-sig'))
