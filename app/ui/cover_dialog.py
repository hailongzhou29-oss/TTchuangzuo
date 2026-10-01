from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog,
    QFontComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget, QTextEdit, QListWidget, QTabWidget, QInputDialog)

from app.core.cover import RATIOS, default_cover, import_image, render_cover
from app.core.files import atomic_write
from app.core.image_service import ImageService
from app.providers.contracts import CancelToken
from app.ui.image_worker import ImageWorker


class CoverDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.owner = parent
        self.image_connections = getattr(parent, 'image_connections', None)
        self.image_service = ImageService(store, parent.resources, self.image_connections) if self.image_connections else None
        self.worker = None
        self.cancel = None
        self.last_image_task = None
        self.plan_worker = None
        self.completion_poll=QTimer(self)
        self.completion_poll.setInterval(50)
        self.completion_poll.timeout.connect(self.poll_workers)
        self.reference_ids = []
        self.mask_id = None
        self.setWindowTitle('项目封面 · 图片生成与本地排版')
        self.resize(1040, 740)
        self.setMinimumSize(760, 540)
        metadata = store.metadata()
        self.spec = store.setting('cover_draft') or default_cover(metadata['name'], metadata['kind'])
        layout = QHBoxLayout(self)
        left = QVBoxLayout()
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.preview, 1)
        self.message = QLabel('本地模板／导入图片；编辑标题不调用模型')
        self.message.setWordWrap(True)
        left.addWidget(self.message)
        self.safe = QCheckBox('预览安全区（不导出到图片）')
        self.safe.toggled.connect(self.update_preview)
        left.addWidget(self.safe)
        layout.addLayout(left, 1)
        controls = QWidget()
        controls.setMaximumWidth(380)
        tabs_layout = QVBoxLayout(controls)
        self.tabs = QTabWidget()
        tabs_layout.addWidget(self.tabs)
        typography = QWidget()
        right = QVBoxLayout(typography)
        self.tabs.addTab(typography, '本地排版')
        form = QFormLayout()
        self.title = QLineEdit(self.spec['title'])
        self.subtitle = QLineEdit(self.spec['subtitle'])
        self.author = QLineEdit(self.spec['author'])
        self.ratio = QComboBox()
        self.ratio.addItems(RATIOS)
        self.ratio.setCurrentText(self.spec['ratio'])
        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont(self.spec['font']))
        self.font_size = QSpinBox()
        self.font_size.setRange(20, 160)
        self.font_size.setValue(self.spec['font_size'])
        self.position = QComboBox()
        self.position.addItems(['上部', '中部', '下部'])
        self.position.setCurrentText(self.spec['position'])
        self.focus_x = QSpinBox()
        self.focus_y = QSpinBox()
        for spin, key in [(self.focus_x, 'focus_x'), (self.focus_y, 'focus_y')]:
            spin.setRange(0, 100)
            spin.setValue(self.spec.get(key, 50))
        for name, control in [('标题', self.title), ('副标题', self.subtitle), ('作者', self.author), ('比例', self.ratio), ('字体', self.font), ('字号', self.font_size), ('位置', self.position), ('水平焦点 %', self.focus_x), ('垂直焦点 %', self.focus_y)]:
            form.addRow(name, control)
        right.addLayout(form)
        self.local_text = QCheckBox('叠加可编辑的本地标题层')
        self.local_text.setChecked(self.spec.get('include_local_text', True))
        right.addWidget(self.local_text)
        self.transparent = QCheckBox('导出透明背景（PNG；已有底图仍保留其像素）')
        self.transparent.setChecked(self.spec.get('transparent', False))
        right.addWidget(self.transparent)
        for text, function in [('标题颜色', lambda: self.pick_color('color')), ('模板背景', lambda: self.pick_color('background')), ('导入底图', self.import_background), ('使用本地模板', self.remove_background), ('保存排版草稿', self.save_draft), ('设为项目封面', self.adopt), ('导出 PNG / JPEG', self.export), ('恢复已保存版本', self.history)]:
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, fn=function: self.run(fn))
            right.addWidget(button)
        right.addStretch()
        if self.image_service:
            self.tabs.addTab(self.build_generation(), '生成底图')
            self.generation_toolbar = QWidget()
            self.generate_button.setText('生成底图')
            self.generate_button.setToolTip('按当前完整请求发起新的图片生成，可能计费')
            self.stop_image_button.setText('停止')
            self.stop_image_button.setToolTip('只停止本地等待，不能保证远端停止或退费')
            self.use_image_button.setText('用作底图')
            self.use_image_button.setToolTip('使用已校验候选预览排版；项目封面仍需明确采用')
            toolbar = QHBoxLayout(self.generation_toolbar)
            toolbar.setContentsMargins(0, 0, 0, 0)
            toolbar.addWidget(self.generate_button, 1)
            toolbar.addWidget(self.stop_image_button)
            toolbar.addWidget(self.use_image_button)
            left.addWidget(self.generation_toolbar)
            self.generation_toolbar.hide()
            self.tabs.currentChanged.connect(lambda index: self.generation_toolbar.setVisible(index == 1))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(controls)
        scroll.setMinimumWidth(280)
        layout.addWidget(scroll)
        for edit in (self.title, self.subtitle, self.author):
            edit.textChanged.connect(self.update_preview)
        for combo in (self.ratio, self.position):
            combo.currentTextChanged.connect(self.update_preview)
        self.font.currentFontChanged.connect(self.update_preview)
        for spin in (self.font_size, self.focus_x, self.focus_y):
            spin.valueChanged.connect(self.update_preview)
        self.local_text.toggled.connect(self.update_preview)
        self.transparent.toggled.connect(self.update_preview)
        self.update_preview()
        if self.image_service:
            self.image_service.recover()
            self.refresh_image_models()
            self.refresh_image_history()

    def run(self, function):
        try:
            function()
        except Exception as exc:
            QMessageBox.warning(self, '封面操作未完成', str(exc))

    def read_spec(self):
        self.spec.update(title=self.title.text(), subtitle=self.subtitle.text(), author=self.author.text(),
            ratio=self.ratio.currentText(), font=self.font.currentFont().family(), font_size=self.font_size.value(),
            position=self.position.currentText(), focus_x=self.focus_x.value(), focus_y=self.focus_y.value())
        self.spec.update(include_local_text=self.local_text.isChecked(), transparent=self.transparent.isChecked())
        return dict(self.spec)

    def update_preview(self, *_):
        try:
            spec = self.read_spec()
            image = render_cover(spec, self.store.root, width=360, safe_area=self.safe.isChecked())
            self.preview.setPixmap(QPixmap.fromImage(image).scaled(440, 520, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            width, height = RATIOS[spec['ratio']]
            label = '标题为可编辑本地图层' if spec.get('include_local_text', True) else '底图内文字已栅格化，改字需重生成；本地叠字关闭'
            native = f"；原图 {spec['image_source_width']}×{spec['image_source_height']}" if spec.get('image_source_width') else ''
            self.message.setText(f"{spec['origin']} · 导出 {width} × {height}{native}\n{label}；排版费用：本地操作")
        except Exception as exc:
            self.preview.clear()
            self.message.setText(str(exc))

    def pick_color(self, key):
        color = QColorDialog.getColor(parent=self, title='选择颜色')
        if color.isValid():
            self.spec[key] = color.name()
            self.update_preview()

    def import_background(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入本地底图', '', '图片 (*.png *.jpg *.jpeg *.webp)')
        if path:
            relative, _ = import_image(self.store, Path(path))
            self.spec.update(image=relative, origin='用户导入底图＋本地排版')
            self.update_preview()

    def remove_background(self):
        self.spec.update(image=None, origin='本地排版模板')
        self.update_preview()

    def save_draft(self):
        spec = self.read_spec()
        render_cover(spec, self.store.root)
        self.store.set_setting('cover_draft', spec)
        self.message.setText('排版草稿已保存；标题与底图分开保留')

    def adopt(self):
        self.save_draft()
        cid = self.store.save_cover(self.read_spec())
        self.store.set_setting('active_cover', cid)
        self.message.setText('已设为项目封面；历史版本保留')

    def history(self):
        from PySide6.QtWidgets import QInputDialog
        versions = self.store.covers()
        if not versions:
            self.message.setText('尚未保存封面版本')
            return
        labels = [f"{v['created']} · {v['spec']['title']} · {v['id'][:6]}" for v in versions]
        choice, ok = QInputDialog.getItem(self, '恢复封面版本', '选择版本', labels, editable=False)
        if ok:
            self.spec = dict(versions[labels.index(choice)]['spec'])
            for widget, value in [(self.title, self.spec['title']), (self.subtitle, self.spec['subtitle']), (self.author, self.spec['author'])]:
                widget.setText(value)
            self.ratio.setCurrentText(self.spec['ratio'])
            self.position.setCurrentText(self.spec['position'])
            self.font.setCurrentFont(QFont(self.spec['font']))
            self.font_size.setValue(self.spec['font_size'])
            self.local_text.setChecked(self.spec.get('include_local_text', True))
            self.transparent.setChecked(self.spec.get('transparent', False))
            self.focus_x.setValue(self.spec.get('focus_x', 50))
            self.focus_y.setValue(self.spec.get('focus_y', 50))
            self.update_preview()

    def export(self):
        spec = self.read_spec()
        image = render_cover(spec, self.store.root)
        path, _ = QFileDialog.getSaveFileName(self, '导出封面', str(self.store.root / 'exports' / '封面.png'), 'PNG (*.png);;JPEG (*.jpg)')
        if path:
            from PySide6.QtCore import QBuffer, QIODevice
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            jpeg = Path(path).suffix.lower() in {'.jpg', '.jpeg'}
            if jpeg and spec.get('transparent'):
                from PySide6.QtGui import QColor, QImage, QPainter
                flattened = QImage(image.size(), QImage.Format.Format_RGB32)
                flattened.fill(QColor(spec['background']))
                painter = QPainter(flattened)
                painter.drawImage(0, 0, image)
                painter.end()
                image = flattened
            if not image.save(buffer, 'JPEG' if jpeg else 'PNG'):
                raise ValueError('图片编码失败')
            atomic_write(Path(path), bytes(buffer.data()))
            self.message.setText('封面已导出：' + path)

    def build_generation(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.image_model = QComboBox()
        self.image_model.currentIndexChanged.connect(self.image_model_changed)
        layout.addWidget(QLabel('独立图片连接 / 模型'))
        layout.addWidget(self.image_model)
        self.image_operation = QComboBox()
        self.image_operation.addItem('文生图', 'generate')
        self.image_operation.addItem('参考编辑', 'edit')
        layout.addWidget(self.image_operation)
        self.prompt = QTextEdit()
        self.prompt.setPlaceholderText('输入已确认的画面提示词。默认无字底图，标题在本地排版。')
        self.prompt.setMinimumHeight(120)
        self.prompt.setPlainText(self.store.setting('cover_prompt', ''))
        layout.addWidget(self.prompt)
        self.brief = QTextEdit()
        self.brief.setPlaceholderText('可选：已确认简介、人物或产品资料。文字策划只发送这段简报，不发送整部作品。')
        self.brief.setMaximumHeight(110)
        self.brief.setPlainText(self.store.setting('cover_brief', ''))
        layout.addWidget(self.brief)
        self.plan_button = QPushButton('生成画面提示词 · 文字模型可能计费')
        self.plan_button.clicked.connect(lambda: self.run(self.generate_prompt_plan))
        layout.addWidget(self.plan_button)
        self.image_size, self.image_quality = QComboBox(), QComboBox()
        self.image_count = QSpinBox()
        self.image_count.setRange(1, 1)
        form = QFormLayout()
        form.addRow('通道原生尺寸', self.image_size)
        form.addRow('质量声明', self.image_quality)
        form.addRow('生成数量', self.image_count)
        layout.addLayout(form)
        self.no_text = QCheckBox('生成无字底图，本地排版（默认）')
        self.no_text.setChecked(True)
        layout.addWidget(self.no_text)
        self.no_spoiler = QCheckBox('避免披露结局与关键反转')
        self.no_spoiler.setChecked(True)
        layout.addWidget(self.no_spoiler)
        self.references_label = QLabel('参考图：无；仅生成时发送所选副本')
        self.references_label.setWordWrap(True)
        layout.addWidget(self.references_label)
        self.negative = QLineEdit()
        self.negative.setPlaceholderText('独立负面提示词，仅支持通道启用')
        layout.addWidget(self.negative)
        self.seed = QLineEdit()
        self.seed.setPlaceholderText('seed，未知能力时禁用；不承诺跨模型复现')
        layout.addWidget(self.seed)
        for text, function in [('添加参考图', self.add_reference), ('导入透明蒙版', self.add_mask), ('清除参考', self.clear_references),
            ('查看完整图片请求', self.view_image_request), ('配置图片连接', self.configure_images), ('保存提示词模板', self.save_prompt_template)]:
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, fn=function: self.run(fn))
            layout.addWidget(button)
        self.generate_button = QPushButton('生成底图 · 可能收费')
        self.generate_button.setObjectName('primary')
        self.generate_button.clicked.connect(lambda: self.run(self.generate_background))
        layout.addWidget(self.generate_button)
        row = QHBoxLayout()
        self.stop_image_button = QPushButton('停止本地等待')
        self.stop_image_button.clicked.connect(self.stop_image)
        self.stop_image_button.setEnabled(False)
        row.addWidget(self.stop_image_button)
        query = QPushButton('查询状态')
        query.clicked.connect(lambda: self.run(lambda: self.resume_image('query')))
        row.addWidget(query)
        layout.addLayout(row)
        retry = QPushButton('重试下载 · 不重新生成')
        retry.clicked.connect(lambda: self.run(lambda: self.resume_image('download')))
        layout.addWidget(retry)
        self.image_history = QListWidget()
        self.image_history.setMinimumHeight(150)
        self.image_history.currentRowChanged.connect(self.choose_image_task)
        layout.addWidget(self.image_history)
        accept = QPushButton('使用所选图片作底图')
        self.use_image_button = accept
        accept.clicked.connect(lambda: self.run(self.use_candidate))
        layout.addWidget(accept)
        recycle = QPushButton('回收所选候选 / 恢复回收区')
        recycle.clicked.connect(lambda: self.run(self.recycle_image_candidate))
        layout.addWidget(recycle)
        return page

    def refresh_image_models(self):
        previous = self.image_model.currentData() or self.owner.options.get('default_image_connection')
        self.image_model.blockSignals(True)
        self.image_model.clear()
        for connection in self.image_connections.all():
            if connection.enabled:
                self.image_model.addItem(connection.name + ' / ' + connection.model, connection.id)
        if not self.image_model.count():
            self.image_model.addItem('尚未配置图片连接', None)
        index = self.image_model.findData(previous)
        if index >= 0:
            self.image_model.setCurrentIndex(index)
        self.image_model.blockSignals(False)
        self.image_model_changed()

    def image_model_changed(self, *_):
        cid = self.image_model.currentData()
        self.image_size.clear()
        self.image_quality.clear()
        self.image_size.addItem('不发送尺寸参数', None)
        self.image_quality.addItem('不发送质量参数', None)
        if cid:
            connection = self.image_connections.get(cid)
            for value in connection.sizes:
                self.image_size.addItem(value, value)
            x, y = (int(value) for value in self.ratio.currentText().split(':'))
            for value in connection.sizes:
                if value != 'auto':
                    w, h = (int(part) for part in value.split('x'))
                    if abs(w / h - x / y) < .02:
                        self.image_size.setCurrentIndex(self.image_size.findData(value))
                        break
            for value in connection.qualities:
                self.image_quality.addItem(value, value)
            self.image_count.setMaximum(connection.max_count)
            self.negative.setEnabled(connection.supports_negative)
            self.seed.setEnabled(connection.supports_seed)
            model = self.image_operation.model()
            model.item(1).setEnabled(connection.supports_edit)
            if not connection.supports_edit:
                self.image_operation.setCurrentIndex(0)
            self.generate_button.setEnabled(self.worker is None)
        else:
            self.generate_button.setEnabled(False)
            self.negative.setEnabled(False)
            self.seed.setEnabled(False)

    def configure_images(self):
        self.owner.settings_dialog()
        self.refresh_image_models()

    def add_reference(self):
        if len(self.reference_ids) >= 4:
            raise ValueError('参考图最多4张')
        path, _ = QFileDialog.getOpenFileName(self, '添加本次封面参考', '', '图片 (*.png *.jpg *.jpeg *.webp)')
        if path:
            relative, _ = import_image(self.store, Path(path))
            with self.store.connection() as con:
                aid = con.execute('SELECT id FROM assets WHERE relative=?', (relative,)).fetchone()[0]
            if aid not in self.reference_ids:
                self.reference_ids.append(aid)
            self.references_label.setText(f'当前项目所选参考：{len(self.reference_ids)} 张；生成时上传这些副本')

    def add_mask(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择与第一张底图同尺寸的透明PNG蒙版', '', 'PNG (*.png)')
        if path:
            relative, _ = import_image(self.store, Path(path))
            with self.store.connection() as con:
                self.mask_id = con.execute('SELECT id FROM assets WHERE relative=?', (relative,)).fetchone()[0]
            self.references_label.setText(f'参考 {len(self.reference_ids)} 张；已选择蒙版（提交前校验）')

    def clear_references(self):
        self.reference_ids, self.mask_id = [], None
        self.references_label.setText('参考图：无')

    def request_preview(self):
        cid = self.image_model.currentData()
        if not cid:
            raise ValueError('请先配置独立图片连接')
        connection = self.image_connections.get(cid)
        prompt = self.prompt.toPlainText().strip()
        if self.no_text.isChecked():
            prompt += '\n生成无字底图，不添加标题、副标题、作者或营销文字；标题由本地排版。'
        else:
            prompt += '\n画面文字必须逐字准确：' + self.title.text() + '。生成文字为栅格化内容，需要人工核对。'
        if self.no_spoiler.isChecked():
            prompt += '\n避免披露未在视觉要求中明确允许的结局或关键反转。'
        prompt += '\n画幅意图：' + self.ratio.currentText() + '。按原生能力生成，如实返回实际尺寸。'
        return dict(connection=connection.name, model=connection.model, operation=self.image_operation.currentData(),
            prompt=prompt, ratio=self.ratio.currentText(), provider_size=self.image_size.currentData(), quality=self.image_quality.currentData(),
            count=self.image_count.value(), reference_ids=list(self.reference_ids), mask_asset_id=self.mask_id,
            seed=int(self.seed.text()) if self.seed.isEnabled() and self.seed.text().strip() else None,
            negative_prompt=self.negative.text() if self.negative.isEnabled() else '', fee='费用未知；将发新请求')

    def view_image_request(self):
        import json
        self.owner.text_dialog('本次完整图片请求 · 不含 KEY', json.dumps(self.request_preview(), ensure_ascii=False, indent=2))

    def generate_background(self, provider=None, confirmed=False):
        if self.worker or getattr(self.owner, 'active_image_task', None):
            raise ValueError('已有图片操作正在执行，未重复提交')
        if not self.prompt.toPlainText().strip():
            raise ValueError('请填写已确认的画面提示词')
        preview = self.request_preview()
        if not confirmed and QMessageBox.question(self, '生成图片可能收费', f"连接：{preview['connection']}\n模型：{preview['model']}\n数量：{preview['count']}；参考：{len(self.reference_ids)}张\n费用未知；本次会发送上方完整图片请求。执行？") != QMessageBox.StandardButton.Yes:
            return
        connection = self.image_connections.get(self.image_model.currentData())
        self.store.set_setting('cover_prompt', self.prompt.toPlainText())
        spec = dict(self.read_spec(), image_text_mode='local' if self.no_text.isChecked() else 'raster')
        snapshot = self.image_service.prepare(connection, preview['prompt'], spec, operation=preview['operation'],
            reference_ids=self.reference_ids, mask_id=self.mask_id, size=preview['provider_size'], count=preview['count'],
            negative_prompt=preview['negative_prompt'], quality=preview['quality'], seed=preview['seed'], development_test=provider is not None)
        self.last_image_task = snapshot['task_id']
        self.start_image_worker('submit', snapshot, provider)

    def start_image_worker(self, operation, snapshot=None, provider=None):
        self.cancel = CancelToken()
        self.worker = ImageWorker(self.image_service, self.last_image_task, self.cancel, operation, snapshot, provider)
        self.owner.active_image_task = dict(worker=self.worker, cancel=self.cancel, service=self.image_service, task_id=self.last_image_task)
        self.worker.signals.state.connect(lambda task, state: self.message.setText('图片任务：' + state + ' · 原封面保留'))
        self.worker.signals.finished.connect(self.image_finished)
        self.generate_button.setEnabled(False)
        self.stop_image_button.setEnabled(True)
        self.completion_poll.start()
        QThreadPool.globalInstance().start(self.worker)

    def poll_workers(self):
        worker=self.worker
        if worker and worker.completed.is_set():
            self.image_finished(worker.task_id,worker.result)
        worker=self.plan_worker
        if worker and worker.completed.is_set():
            self.finish_plan(worker.snapshot['task_id'],worker.result)
        if not self.worker and not self.plan_worker:
            self.completion_poll.stop()

    def image_finished(self, task_id, result):
        if not self.worker or self.worker.task_id!=task_id:
            return
        self.worker = None
        self.owner.image_task_finished(task_id,result)
        self.generate_button.setEnabled(bool(self.image_model.currentData()))
        self.stop_image_button.setEnabled(False)
        images = result.get('images', [])
        message = f"图片任务：{result['status']} · 已校验 {len(images)} 张，原封面尚未替换"
        if result.get('development_test'):
            message = '开发测试固定图片响应，未请求真实生图\n' + message
        if result.get('error'):
            message += '\n' + result['error']
        if result.get('errors'):
            message += '\n' + '\n'.join(result['errors'])
        self.message.setText(message)
        self.refresh_image_history()

    def stop_image(self):
        if self.worker and self.cancel:
            self.cancel.cancel()
            self.message.setText('正在停止本地等待；服务端可能仍生成或计费')
        elif self.last_image_task:
            task = self.image_service.get(self.last_image_task)
            if task['state'] in {'accepted', 'uncertain', 'generating'} and QMessageBox.question(self, '停止本地追踪', '不能保证远端停止或退费。确认只停止本地追踪？发新图片任务可能再次计费。') == QMessageBox.StandardButton.Yes:
                result = dict(task['result'] or {}, status='cancelled', job_id=task['job_id'], error='用户停止本地追踪；未承诺远端取消或退费')
                self.image_service.update(task['id'], result)
                self.refresh_image_history()

    def refresh_image_history(self):
        self.history_rows = self.image_service.history()
        self.image_history.clear()
        for row in self.history_rows:
            changed = ' · 项目依据已更新' if self.image_service.basis_changed(row['id']) else ''
            self.image_history.addItem(row['created'] + ' · ' + row['state'] + ' · ' + row['id'][:8] + changed)

    def choose_image_task(self, index):
        if index >= 0 and not self.worker:
            self.last_image_task = self.history_rows[index]['id']
            self.stop_image_button.setEnabled(self.history_rows[index]['state'] in {'accepted', 'uncertain', 'generating'})

    def resume_image(self, operation):
        if not self.last_image_task:
            raise ValueError('请先选择任务')
        if self.worker or self.owner.active_image_task:
            raise ValueError('图片操作正在执行，请等待结果')
        task = self.image_service.get(self.last_image_task)
        if operation == 'query' and not task['job_id']:
            raise ValueError('没有服务端任务号，不能查询；重发生成可能再次计费')
        if operation == 'download' and not task['private_result']:
            raise ValueError('没有可重试下载的信息')
        self.start_image_worker(operation)

    def use_candidate(self):
        if not self.last_image_task:
            raise ValueError('请先选择已校验任务')
        task = self.image_service.get(self.last_image_task)
        result = task['result'] or {}
        images = result.get('images', [])
        if not images or task['state'] in {'trash', 'failed', 'storage_failed'}:
            raise ValueError('该任务没有实际校验通过的图片')
        selected = 0
        if len(images) > 1:
            choices = [f"{i + 1} · {image['width']}×{image['height']} · {image['sha256'][:8]}" for i, image in enumerate(images)]
            choice, ok = QInputDialog.getItem(self, '选择底图候选', '已校验图片', choices, editable=False)
            if not ok:
                return
            selected = choices.index(choice)
        image = images[selected]
        self.spec.update(image=image['relative'], origin='已校验模型底图（开发固定响应）' if result.get('development_test') else '已校验模型底图',
                         image_task_id=self.last_image_task, image_source_width=image['width'], image_source_height=image['height'])
        if task['snapshot']['cover_spec'].get('image_text_mode') == 'raster':
            self.local_text.setChecked(False)
        self.update_preview()
        self.tabs.setCurrentIndex(0)

    def save_prompt_template(self):
        if not self.prompt.toPlainText().strip():
            raise ValueError('提示词为空')
        title, ok = QInputDialog.getText(self, '保存当前项目提示词模板', '模板名称')
        if ok and title.strip():
            templates = self.store.setting('cover_prompt_templates', [])
            templates.append(dict(title=title.strip(), prompt=self.prompt.toPlainText(), ratio=self.ratio.currentText()))
            self.store.set_setting('cover_prompt_templates', templates)
            self.message.setText('模板已保存，仅当前项目生效')

    def recycle_image_candidate(self):
        choices = ['回收当前所选候选', '恢复回收区候选']
        choice, ok = QInputDialog.getItem(self, '图片候选回收区', '操作不会永久删除素材', choices, editable=False)
        if not ok:
            return
        if choice == choices[0]:
            if not self.last_image_task:
                raise ValueError('请先选择候选')
            self.image_service.trash(self.last_image_task)
        else:
            rows = [row for row in self.image_service.history(include_trash=True) if row['state'] == 'trash']
            if not rows:
                self.message.setText('图片回收区为空')
                return
            labels = [row['created'] + ' · ' + row['id'][:8] for row in rows]
            selected, ok = QInputDialog.getItem(self, '恢复图片候选', '选择任务', labels, editable=False)
            if not ok:
                return
            self.image_service.trash(rows[labels.index(selected)]['id'], restore=True)
        self.refresh_image_history()

    def generate_prompt_plan(self, provider=None, confirmed=False):
        if self.plan_worker or self.owner.active_task:
            raise ValueError('文字任务正在执行，请先等待或停止')
        connection_id = self.owner.model_combo.currentData()
        if not connection_id:
            raise ValueError('请先在主助手选择已配置的文字模型；已有提示词可直接生图')
        if len(self.brief.toPlainText()) > 8000:
            raise ValueError('封面简报超过8000字符，请只选必要内容')
        connection = self.owner.connections.get(connection_id)
        brief = dict(title=self.title.text(), synopsis=self.brief.toPlainText(), ratio=self.ratio.currentText(),
                     text_mode='local' if self.no_text.isChecked() else 'native', no_spoiler=self.no_spoiler.isChecked(),
                     confirmed_facts=[], reference_assets=[dict(asset_id=aid, purpose='用户选定画面参考；未向文字模型发送图片像素') for aid in self.reference_ids])
        if not confirmed and QMessageBox.question(self, '封面文字策划可能收费', f'文字连接：{connection.name}\n只发送标题、此处确认简报、比例与参考用途ID。\n不发送整部作品、不生成图片。请求次数1。执行？') != QMessageBox.StandardButton.Yes:
            return
        from app.core.tasks import TaskService
        from app.ui.task_worker import TaskWorker
        document_id = self.store.documents()[0]['id'] if self.owner.store.root != self.store.root else self.owner.document_id
        service = TaskService(self.store, self.owner.resources, self.owner.connections)
        snapshot = service.prepare(document_id, '按确认封面简报规划单个方案；主标题逐字保留，返回正负提示、文字模式、建议区域和待确认项。',
            connection, 'cover_plan', 0, 0, cover_brief=brief, development_test=provider is not None)
        cancel = CancelToken()
        worker = TaskWorker(service, snapshot, cancel, provider)
        self.plan_worker = worker
        self.owner.active_task = dict(service=service, snapshot=snapshot, cancel=cancel, worker=worker)
        self.owner.last_task = service, snapshot['task_id']
        worker.signals.finished.connect(self.finish_plan)
        self.plan_button.setEnabled(False)
        self.store.set_setting('cover_brief', self.brief.toPlainText())
        self.completion_poll.start()
        QThreadPool.globalInstance().start(worker)

    def finish_plan(self,task_id,result):
        if not self.plan_worker or self.plan_worker.snapshot['task_id']!=task_id:
            return
        self.owner.task_finished(task_id,result)
        self.prompt_plan_finished(task_id,result)

    def prompt_plan_finished(self, task_id, result):
        self.plan_worker = None
        self.plan_button.setEnabled(True)
        if result['status'] != 'completed':
            self.message.setText('封面文字方案未通过：' + result.get('error', '请在文字任务历史查看'))
            return
        candidate = result['candidate']
        text = candidate['cover_concept'] + '\n\n画面提示：\n' + candidate['positive_prompt'] + '\n\n避免项：\n' + candidate['negative_prompt']
        if candidate['warnings']:
            text += '\n\n待确认：\n' + '\n'.join(candidate['warnings'])
        box = QMessageBox(self)
        box.setWindowTitle('封面方案待确认 · 尚未生图')
        box.setText(text)
        accept = box.addButton('采用到提示词', QMessageBox.ButtonRole.AcceptRole)
        box.addButton('保留现有提示词', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() == accept:
            self.prompt.setPlainText(candidate['positive_prompt'])
            if self.negative.isEnabled():
                self.negative.setText(candidate['negative_prompt'])
            elif candidate['negative_prompt']:
                self.prompt.append('语义避免项：' + candidate['negative_prompt'])
            self.spec['cover_plan_task_id'] = task_id
            self.message.setText('提示词方案已采用；生成底图仍需单独点击，不会自动生图')
