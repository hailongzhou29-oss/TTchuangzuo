from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QInputDialog, QLabel, QListWidget, QMessageBox, QSpinBox, QTextEdit, QVBoxLayout)

from app.core.knowledge import FactService

STATUS = {'candidate': '候选，待确认', 'confirmed': '已确认', 'disputed': '争议', 'invalid': '失效'}


class KnowledgeDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner, self.service = owner, FactService(owner.store)
        self.setWindowTitle('人物与设定 · 当前项目')
        self.resize(860, 620)
        layout = QVBoxLayout(self)
        label = QLabel('事实按对象、来源版本和剧情区间保存；候选与争议项不会当作已确认设定。')
        label.setWordWrap(True)
        layout.addWidget(label)
        self.timeline = QSpinBox()
        self.timeline.setRange(1, 100000)
        self.timeline.setValue(self.service.timeline(owner.document_id))
        form = QFormLayout()
        form.addRow('当前文档剧情位置', self.timeline)
        layout.addLayout(form)
        self.timeline.valueChanged.connect(self.set_timeline)
        self.filter = QComboBox()
        self.filter.addItems(['全部事实', '当前剧情有效且已确认', '候选，待确认', '争议', '失效'])
        self.filter.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.filter)
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        for name, function in [('新增对象', self.add_entity), ('新增事实', self.add_fact), ('修订所选', self.revise), ('确认所选', lambda: self.set_state('confirmed')),
                               ('标为争议', lambda: self.set_state('disputed')), ('标为失效', lambda: self.set_state('invalid')), ('来源 / 历史', self.history)]:
            row.addWidget(owner.button(name, function))
        layout.addLayout(row)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.button(QDialogButtonBox.StandardButton.Close).setText('关闭')
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.refresh()

    def set_timeline(self, position):
        self.owner.run(lambda: self.service.set_timeline(self.owner.document_id, position))
        self.refresh()

    def refresh(self, *_):
        index = self.filter.currentIndex()
        if index == 1:
            rows = self.service.active(self.owner.document_id)
        else:
            state = {2: 'candidate', 3: 'disputed', 4: 'invalid'}.get(index)
            rows = self.service.facts(state)
        self.rows = rows
        self.list.clear()
        for fact in rows:
            interval = f"剧情 {fact['valid_from'] or '起始'}—{fact['valid_to'] or '末尾'}"
            self.list.addItem(f"{fact['entity_name']} · {STATUS[fact['state']]} · v{fact['version']} · {interval}\n{fact['content']}")

    def selected(self):
        index = self.list.currentRow()
        if index < 0:
            raise ValueError('请先选择一条事实')
        return self.rows[index]

    def add_entity(self):
        name, ok = QInputDialog.getText(self, '新增人物 / 商品 / 地点对象', '对象名称')
        if not ok:
            return
        titles = ['人物', '地点', '商品', '其他']
        kind, ok = QInputDialog.getItem(self, '对象类型', '选择类型', titles, editable=False)
        if ok:
            self.service.add_entity(name, ['character', 'location', 'product', 'other'][titles.index(kind)])

    def add_fact(self):
        entities = self.service.entities()
        if not entities:
            raise ValueError('请先新增对象，再添加其设定')
        dialog = QDialog(self)
        dialog.setWindowTitle('新增手工事实 · 先保存为候选')
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        entity = QComboBox()
        for item in entities:
            entity.addItem(item['name'], item['id'])
        body = QTextEdit()
        body.setPlaceholderText('例如：第8章开始，右手受伤。只填写已确认或待讨论的具体内容。')
        start, end = QSpinBox(), QSpinBox()
        for spin in (start, end):
            spin.setRange(0, 100000)
            spin.setSpecialValueText('不限')
        form.addRow('绑定对象', entity)
        form.addRow('事实内容', body)
        form.addRow('从剧情位置', start)
        form.addRow('至剧情位置', end)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('保存候选')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.service.propose(entity.currentData(), body.toPlainText(), valid_from=start.value() or None, valid_to=end.value() or None)
            self.refresh()

    def set_state(self, state):
        fact = self.selected()
        if state == 'confirmed' and QMessageBox.question(self, '确认项目事实', '确认把以下内容作为对应剧情区间的正式设定？\n\n' + fact['content']) != QMessageBox.StandardButton.Yes:
            return
        self.service.set_state(fact['id'], state)
        self.refresh()

    def history(self):
        import json
        fact = self.selected()
        self.owner.text_dialog('事实来源与不可变版本', json.dumps(self.service.versions(fact['id']), ensure_ascii=False, indent=2))

    def revise(self):
        fact = self.selected()
        content, ok = QInputDialog.getMultiLineText(self, '用户手工修订 · 原来源保留在历史中', '修订后将重新成为候选；当前来源记为用户手工设定。', fact['content'])
        if ok:
            self.service.revise(fact['id'], content, fact['valid_from'], fact['valid_to'])
            self.refresh()
