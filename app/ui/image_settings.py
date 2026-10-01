from dataclasses import replace

from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QScrollArea, QSpinBox, QTextBrowser, QVBoxLayout, QWidget)

from app.providers.codex_image import CodexImageProvider
from app.providers.image_contracts import ImageConnection
from app.storage.project import new_id, now


class ImageSettingsPage(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner, self.store = owner, owner.image_connections
        self.current_id = None
        layout = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.select)
        left.addWidget(self.list, 1)
        left.addWidget(owner.button('新增图片连接', self.new))
        left.addWidget(owner.button('停用 / 启用', self.toggle))
        left.addWidget(owner.button('删除图片连接', self.delete))
        layout.addLayout(left, 1)
        panel = QWidget()
        right = QVBoxLayout(panel)
        form = QFormLayout()
        self.name, self.model, self.base, self.key, self.cli = (QLineEdit() for _ in range(5))
        self.provider = QComboBox()
        self.provider.addItem('通用 HTTP 图片', 'image_http')
        self.provider.addItem('Codex CLI 内置图片', 'image_codex')
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText('独立图片 KEY；不会读取或继承文字连接 KEY')
        self.base.setPlaceholderText('例如 https://供应商/v1；程序不猜地域或改地址')
        self.cli.setPlaceholderText('已有 CLI 路径；留空使用 PATH')
        self.sizes = QLineEdit('1024x1024')
        self.qualities, self.asset_hosts, self.poll = QLineEdit(), QLineEdit(), QLineEdit()
        self.pricing=QLineEdit()
        self.pricing.setPlaceholderText('用户价表JSON：currency/version/source/per_image；CLI金额未知')
        self.sizes.setPlaceholderText('模型支持的实际尺寸，逗号分隔；CLI 为目标意图')
        self.qualities.setPlaceholderText('支持的质量枚举，未知留空')
        self.asset_hosts.setPlaceholderText('允许下载的资产域名，逗号分隔；默认只允许服务域名')
        self.poll.setPlaceholderText('例如 /tasks/{job_id}；仅按明确协议配置')
        self.timeout, self.count = QSpinBox(), QSpinBox()
        self.timeout.setRange(10, 1800)
        self.timeout.setValue(300)
        self.count.setRange(1, 8)
        self.count.setValue(1)
        self.edit, self.mask, self.seed, self.negative = (QCheckBox(text) for text in
            ['声明支持参考编辑', '声明支持透明蒙版', '声明支持 seed', '声明支持独立 negative_prompt'])
        self.basic_form=form
        for label, field in [('连接名称',self.name),('生图方式',self.provider),('模型名称',self.model),
            ('接口地址',self.base),('API Key',self.key),('Codex程序',self.cli),('支持的尺寸',self.sizes)]:
            form.addRow(label, field)
        right.addLayout(form)
        from app.ui.advanced import fold
        self.advanced,advanced_layout,self.advanced_toggle=fold(right)
        advanced_form=QFormLayout()
        for label,field in [('质量',self.qualities),('每次最多图片',self.count),('等待秒数',self.timeout),('任务查询路径',self.poll),('下载域名',self.asset_hosts),('估算价表',self.pricing)]:
            advanced_form.addRow(label,field)
        advanced_layout.addLayout(advanced_form)
        for checkbox in (self.edit, self.mask, self.seed, self.negative):
            advanced_layout.addWidget(checkbox)
        actions = QHBoxLayout()
        actions.addWidget(owner.button('保存图片连接', self.save))
        actions.addWidget(owner.button('选择CLI', self.choose_cli))
        actions.addWidget(owner.button('检测CLI图片入口', self.detect))
        actions.addWidget(owner.button('设为默认图片模型',self.set_default))
        right.addLayout(actions)
        self.status = QTextBrowser()
        self.status.setMaximumHeight(140)
        self.status.setPlainText('能力为手动声明，尚未实测。CLI 检测仅确认版本、登录和工具入口；不会生成图片。文字测试成功不代表生图权限。')
        right.addWidget(self.status)
        right.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        layout.addWidget(scroll, 3)
        self.provider.currentIndexChanged.connect(self.provider_changed)
        self.refresh()
        self.provider_changed()

    def provider_changed(self):
        cli = self.provider.currentData() == 'image_codex'
        for field in (self.base,self.key):
            self.basic_form.setRowVisible(field,not cli)
        self.basic_form.setRowVisible(self.cli,cli)
        for field in (self.base, self.key, self.poll, self.asset_hosts):
            field.setEnabled(not cli)
        self.cli.setEnabled(cli)
        self.count.setMaximum(1 if cli else 8)

    def refresh(self, selected=None):
        self.rows = self.store.all()
        self.list.blockSignals(True)
        self.list.clear()
        for item in self.rows:
            self.list.addItem(item.name + ('（停用）' if not item.enabled else '') + '\n' + item.model)
        chosen=selected or self.current_id or self.owner.options.get('default_image_connection')
        index = next((i for i,item in enumerate(self.rows) if item.id==chosen),0 if self.rows else -1)
        self.list.setCurrentRow(index)
        self.list.blockSignals(False)
        if index >= 0:
            self.select(index)

    def new(self):
        self.current_id = None
        self.list.setCurrentRow(-1)
        for field in (self.name, self.model, self.base, self.key, self.cli, self.poll, self.qualities, self.asset_hosts,self.pricing):
            field.clear()
        self.provider.setCurrentIndex(0)
        self.sizes.setText('1024x1024')
        for checkbox in (self.edit, self.mask, self.seed, self.negative):
            checkbox.setChecked(False)
        self.count.setValue(1)

    def select(self, index):
        if index < 0 or index >= len(self.rows):
            return
        item = self.rows[index]
        self.current_id = item.id
        self.name.setText(item.name)
        self.model.setText(item.model)
        self.provider.setCurrentIndex(self.provider.findData(item.provider))
        self.base.setText(item.base_url)
        self.cli.setText(item.cli_path)
        self.key.clear()
        self.sizes.setText(','.join(item.sizes))
        self.qualities.setText(','.join(item.qualities))
        self.asset_hosts.setText(','.join(item.asset_hosts))
        self.poll.setText(item.poll_path)
        self.pricing.setText(__import__('json').dumps(item.pricing,ensure_ascii=False) if item.pricing else '')
        self.timeout.setValue(item.timeout)
        self.count.setValue(item.max_count)
        self.edit.setChecked(item.supports_edit)
        self.mask.setChecked(item.supports_mask)
        self.seed.setChecked(item.supports_seed)
        self.negative.setChecked(item.supports_negative)
        self.status.setPlainText(item.capability_status)

    def save(self):
        old = self.store.get(self.current_id) if self.current_id else None
        item = ImageConnection(id=self.current_id or 'image_' + new_id(), name=self.name.text().strip(),
            provider=self.provider.currentData(), model=self.model.text().strip(), base_url=self.base.text().strip(),
            cli_path=self.cli.text().strip(), timeout=self.timeout.value(), max_count=self.count.value(),
            supports_edit=self.edit.isChecked(), supports_mask=self.mask.isChecked(), supports_seed=self.seed.isChecked(),
            supports_negative=self.negative.isChecked(), sizes=tuple(x.strip() for x in self.sizes.text().split(',') if x.strip()),
            qualities=tuple(x.strip() for x in self.qualities.text().split(',') if x.strip()),
            asset_hosts=tuple(x.strip() for x in self.asset_hosts.text().split(',') if x.strip()), poll_path=self.poll.text().strip(),
            enabled=old.enabled if old else True, verification=old.verification if old else {},
            capability_status=old.capability_status if old else '手动声明，未实测')
        item=replace(item,pricing=__import__('json').loads(self.pricing.text()) if self.pricing.text().strip() else {})
        if self.key.text().strip() or (old and (old.provider, old.model, old.base_url, old.cli_path) != (item.provider, item.model, item.base_url, item.cli_path)):
            item = replace(item, verification={}, capability_status='手动声明，未实测')
        self.store.save(item, self.key.text().strip() or None)
        self.current_id = item.id
        self.refresh(item.id)
        self.status.setPlainText('图片连接已保存；实际生成能力与产物仍需单独验收。')
        return self.store.get(item.id)

    def choose_cli(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择已有CLI', '', 'CLI (*.exe *.cmd *.ps1 *.js)')
        if path:
            self.cli.setText(path)

    def set_default(self):
        item=self.save()
        self.owner.options['default_image_connection']=item.id
        self.owner.save_preferences()
        self.status.setPlainText('默认图片模型已保存，独立于文字模型；下一图片任务生效。')

    def detect(self):
        item = self.save()
        if item.provider != 'image_codex':
            raise ValueError('请先选择 CLI 图片通道')
        from app.ui.model_settings import Operation
        from PySide6.QtCore import QThreadPool
        operation = Operation(lambda: CodexImageProvider().detect(item))
        self.operation = operation
        def finish(result, error):
            if error:
                self.status.setPlainText(error)
                return
            self.status.setPlainText(result['version'] + '\n登录：' + str(result['logged_in']) + '\n内置图片入口：' + str(result['image_tool_declared']) + '\n没有执行生成；图片产物未验收。')
            current = self.store.get(item.id)
            if current == item:
                self.store.save(replace(item, verification=dict(item.verification, image_entry=dict(version=result['version'], login=result['logged_in'],
                    declared=result['image_tool_declared'], checked=now())), capability_status='图片入口已检测；产物未测试'))
        operation.signals.finished.connect(finish)
        QThreadPool.globalInstance().start(operation)

    def toggle(self):
        if not self.current_id:
            raise ValueError('请选择图片连接')
        item = self.store.get(self.current_id)
        self.store.save(replace(item, enabled=not item.enabled))
        self.refresh(item.id)

    def delete(self):
        if self.current_id and QMessageBox.question(self, '删除独立图片连接', '移除连接与该连接的凭据，已保存图片保留？') == QMessageBox.StandardButton.Yes:
            self.store.delete(self.current_id)
            self.new()
            self.refresh()
