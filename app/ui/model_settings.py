from dataclasses import replace

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPushButton, QSpinBox, QTabWidget, QTextBrowser, QVBoxLayout, QWidget, QScrollArea)

from app.providers.codex_text import CodexTextProvider
from app.providers.contracts import Connection, PRESETS
from app.providers.http_text import HttpTextProvider
from app.storage.project import new_id, now


class OperationSignals(QObject):
    finished = Signal(object, object)


class Operation(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.setAutoDelete(False)
        import threading
        self.completed=threading.Event()
        self.result=None
        self.error=None
        self.function, self.signals = function, OperationSignals()

    @Slot()
    def run(self):
        try:
            result, error = self.function(), None
        except Exception as exc:
            result, error = None, str(exc)
        self.result,self.error=result,error
        self.completed.set()
        self.signals.finished.emit(result, error)


class SettingsDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.connections = owner.connections
        self.current_id = None
        self.operations = []
        self.busy = False
        self.setWindowTitle('模型与设置')
        self.resize(900, 680)
        self.setMinimumSize(760, 520)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        appearance = QWidget()
        appearance_layout = QFormLayout(appearance)
        self.font_size = QSpinBox()
        self.font_size.setRange(14, 28)
        self.font_size.setValue(owner.options.get('editor_font_size', 18))
        self.ui_size = QSpinBox()
        self.ui_size.setRange(12, 18)
        self.ui_size.setValue(owner.options.get('ui_font_size', 14))
        self.theme = QComboBox()
        self.theme.addItems(owner.theme_combo.itemText(i) for i in range(owner.theme_combo.count()))
        self.theme.setCurrentText(owner.theme)
        appearance_layout.addRow('应用主题', self.theme)
        appearance_layout.addRow('正文字号', self.font_size)
        appearance_layout.addRow('界面字号', self.ui_size)
        appearance_layout.addRow(owner.button('恢复默认字号与布局',owner.restore_layout_defaults))
        self.tabs.addTab(self.build_models(), '文字模型')
        from app.ui.image_settings import ImageSettingsPage
        self.tabs.addTab(ImageSettingsPage(owner), '图片模型')
        from app.ui.codex_settings import CodexSettingsPage
        self.tabs.addTab(CodexSettingsPage(owner),'Codex CLI')
        self.tabs.addTab(appearance,'外观')
        extra=QWidget()
        extra_layout=QVBoxLayout(extra)
        from app.ui.advanced import fold
        advanced,advanced_layout,advanced_toggle=fold(extra_layout,'显示预算、备份与诊断设置')
        extras=QTabWidget()
        advanced_layout.addWidget(extras)
        for title, content in [
            ('通用', '手动写作无需账号。发送任务时使用当前选择的连接、模型与作品范围。Enter 换行；Ctrl+Enter 发送。'),
            ('Codex CLI', '在文字模型页新建 Codex CLI 连接，选择已有可执行文件并填写模型 ID。检测只读取版本、参数和登录状态。文字任务使用隔离目录，关闭文件、应用与联网工具。'),
            ('上下文与预算', '预算档为节省 / 均衡 / 深入，最多调用数分别为 2 / 4 / 8。当前一次任务只做一次生成，不自动模型审稿或重发。费用未知时不声称人民币硬上限；CLI 输出限制为软限制。'),
            ('保存与备份', '停止输入约 1 秒自动保存，组字期间暂停。项目备份 / 恢复位于首页继续创作区的更多菜单。数据库升级前自动备份。\n数据目录：' + str(owner.workspace.root)),
            ('诊断', '任务历史保存上下文、规则正文、模型选择、结束状态和用量。应用连接只保存凭据引用；KEY 由 Windows DPAPI 加密，隔离于作品、备份和日志。')]:
            if title=='上下文与预算':
                from app.ui.budget_settings import BudgetSettingsPage
                extras.addTab(BudgetSettingsPage(owner),title)
                continue
            if title=='保存与备份':
                from app.ui.maintenance_settings import BackupSettingsPage
                extras.addTab(BackupSettingsPage(owner),title)
                continue
            page = QWidget()
            sublayout = QVBoxLayout(page)
            label = QLabel(content)
            label.setWordWrap(True)
            sublayout.addWidget(label)
            if title == '上下文与预算':
                sublayout.addWidget(owner.button('清理当前项目分析缓存', owner.clear_analysis_cache))
            sublayout.addStretch()
            if title!='Codex CLI':
                extras.addTab(page, title)
        extra_layout.addStretch()
        self.tabs.addTab(extra,'高级')
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('应用外观')
        buttons.button(QDialogButtonBox.StandardButton.Save).hide()
        self.tabs.currentChanged.connect(lambda index:buttons.button(QDialogButtonBox.StandardButton.Save).setVisible(self.tabs.tabText(index)=='外观'))
        buttons.button(QDialogButtonBox.StandardButton.Close).setText('关闭')
        buttons.accepted.connect(self.save_appearance)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh_list()

    def build_models(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.select_connection)
        left.addWidget(self.list, 1)
        left.addWidget(self.owner.button('新增连接', self.new_connection))
        left.addWidget(self.owner.button('停用 / 启用', self.toggle_enabled))
        left.addWidget(self.owner.button('删除连接', self.delete_connection))
        layout.addLayout(left, 1)
        right = QVBoxLayout()
        form = QFormLayout()
        self.name = QLineEdit()
        self.provider = QComboBox()
        for key, (title, _) in PRESETS.items():
            if key!='codex':
                self.provider.addItem(title, key)
        self.base_url = QLineEdit()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText('同服务留空保留；更换服务商或域名需重新输入')
        self.model = QLineEdit()
        self.model.setPlaceholderText('填写服务返回的实际模型 ID')
        self.cli_path = QLineEdit()
        self.cli_path.setPlaceholderText('留空从 PATH 检测；手动路径失效不会静默切换')
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 1800)
        self.timeout.setValue(120)
        self.max_output = QSpinBox()
        self.max_output.setRange(128, 65536)
        self.max_output.setValue(4096)
        self.context_limit = QSpinBox()
        self.context_limit.setRange(1024, 2_000_000)
        self.context_limit.setValue(32768)
        self.stream = QCheckBox('请求流式输出')
        self.stream.setChecked(True)
        self.json_mode = QCheckBox('该模型支持 JSON Object（手动声明，仍需本地检查）')
        self.tool_call = QCheckBox('该模型支持项目函数工具（手动声明，讨论模式使用）')
        self.reasoning = QLineEdit()
        self.reasoning.setPlaceholderText('支持的 reasoning_effort，用逗号分隔；未知留空')
        for title,control in [('连接名称',self.name),('服务商',self.provider),('接口地址',self.base_url),('API Key',self.key),('模型名称',self.model)]:
            form.addRow(title, control)
        self.pricing=QLineEdit()
        self.pricing.setPlaceholderText('可选用户价表JSON；每百万token单价/币种/版本/来源，未知留空')
        right.addLayout(form)
        from app.ui.advanced import fold
        self.advanced,advanced_layout,self.advanced_toggle=fold(right)
        advanced_form=QFormLayout()
        for title,control in [('等待秒数',self.timeout),('最多输出token',self.max_output),('上下文token',self.context_limit),('推理强度',self.reasoning),('估算价表',self.pricing)]:
            advanced_form.addRow(title,control)
        advanced_layout.addLayout(advanced_form)
        advanced_layout.addWidget(self.stream)
        advanced_layout.addWidget(self.json_mode)
        advanced_layout.addWidget(self.tool_call)
        row = QHBoxLayout()
        for text, function in [('保存连接', self.save_connection), ('读取模型 / 认证', self.check_auth), ('最小生成测试', self.generation_test)]:
            row.addWidget(self.owner.button(text, function))
        right.addLayout(row)
        cli_row = QHBoxLayout()
        cli_row.addWidget(self.owner.button('设为默认文字模型', self.set_default))
        right.addLayout(cli_row)
        self.status = QTextBrowser()
        self.status.setMaximumHeight(120)
        self.status.setPlainText('连接尚未实测。认证 / 模型列表检查不生成内容；最小生成测试可能收费。千问地址需与 KEY 地域一致，可使用业务空间专属域名。')
        right.addWidget(self.status)
        right_panel = QWidget()
        right_panel.setLayout(right)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(right_panel)
        scroll.setMinimumWidth(500)
        layout.addWidget(scroll, 3)
        self.provider.currentIndexChanged.connect(self.provider_changed)
        return page

    def provider_changed(self):
        provider = self.provider.currentData()
        self.base_url.setEnabled(provider != 'codex')
        self.key.setEnabled(provider != 'codex')
        self.cli_path.setEnabled(provider == 'codex')
        if not self.current_id:
            self.base_url.setText(PRESETS[provider][1])

    def refresh_list(self, selected=None):
        self.rows = [connection for connection in self.connections.all() if connection.provider!='codex']
        self.list.blockSignals(True)
        self.list.clear()
        for row in self.rows:
            self.list.addItem(row.name + ('（停用）' if not row.enabled else '') + '\n' + row.model)
        index = next((i for i,row in enumerate(self.rows) if row.id==(selected or self.current_id)),0 if self.rows else -1)
        self.list.setCurrentRow(index)
        self.list.blockSignals(False)
        if index >= 0:
            self.select_connection(index)

    def new_connection(self):
        self.current_id = None
        self.list.setCurrentRow(-1)
        self.name.clear()
        self.model.clear()
        self.key.clear()
        self.cli_path.clear()
        self.pricing.clear()
        self.provider.setCurrentIndex(0)
        self.provider_changed()
        self.status.setPlainText('新连接：能力为手动声明 / 未验证。凭据不会从旧软件读取。')

    def select_connection(self, index):
        if index < 0 or index >= len(self.rows):
            return
        connection = self.rows[index]
        self.current_id = connection.id
        self.name.setText(connection.name)
        self.provider.setCurrentIndex(self.provider.findData(connection.provider))
        self.base_url.setText(connection.base_url)
        self.model.setText(connection.model)
        self.cli_path.setText(connection.cli_path)
        self.key.clear()
        self.timeout.setValue(connection.timeout)
        self.max_output.setValue(connection.max_output)
        self.context_limit.setValue(connection.context_limit)
        self.stream.setChecked(connection.stream)
        self.json_mode.setChecked(connection.json_mode)
        self.tool_call.setChecked(connection.tool_call)
        self.reasoning.setText(','.join(connection.reasoning_levels))
        self.pricing.setText(json_text(connection.pricing) if connection.pricing else '')
        self.status.setPlainText('状态：' + connection.capability_status + '\n' + json_text(connection.verification))

    def save_connection(self, allow_empty_model=False):
        previous = self.connections.get(self.current_id) if self.current_id else None
        connection = Connection(id=self.current_id or new_id(), name=self.name.text().strip(), provider=self.provider.currentData(),
            model=self.model.text().strip(), base_url=self.base_url.text().strip(), cli_path=self.cli_path.text().strip(),
            timeout=self.timeout.value(), max_output=self.max_output.value(), context_limit=self.context_limit.value(),
            stream=self.stream.isChecked(), json_mode=self.json_mode.isChecked(),
            tool_call=self.tool_call.isChecked() and self.provider.currentData() != 'codex',
            reasoning_levels=tuple(s.strip() for s in self.reasoning.text().split(',') if s.strip()),
            pricing=__import__('json').loads(self.pricing.text()) if self.pricing.text().strip() else {},
            enabled=previous.enabled if previous else True,
            verification=previous.verification if previous else {}, capability_status=previous.capability_status if previous else '未验证')
        credential = self.key.text().strip() or None
        changed_identity = previous and (previous.provider, previous.model, previous.base_url, previous.cli_path) != (connection.provider, connection.model, connection.base_url, connection.cli_path)
        if changed_identity or credential:
            connection = replace(connection, verification={}, capability_status='未验证')
        connection.validate(require_model=not allow_empty_model)
        self.connections.save(connection, credential)
        connection = self.connections.get(connection.id)
        self.current_id = connection.id
        self.key.clear()
        self.refresh_list(connection.id)
        self.owner.refresh_models()
        self.status.setPlainText('连接已保存；KEY 未显示且不进入项目文件。状态：' + connection.capability_status)
        return connection

    def start_operation(self, function, completed):
        if self.busy:
            raise ValueError('当前连接检查尚未结束，请等待结果')
        self.busy = True
        operation = Operation(function)
        self.operations.append(operation)
        def finish(result, error):
            self.busy = False
            if error:
                self.status.setPlainText(error)
            else:
                completed(result)
            self.operations.remove(operation)
        operation.signals.finished.connect(finish)
        self.status.setPlainText('正在检查所选连接…')
        QThreadPool.globalInstance().start(operation)

    def check_auth(self):
        connection = self.save_connection(allow_empty_model=True)
        if connection.provider == 'codex':
            self.detect_cli()
            return
        secret = self.connections.secret_snapshot(connection)
        if not secret:
            raise ValueError('请先填写并保存该连接的 KEY')
        def finish(models):
            current = self.connections.get(connection.id)
            if current != connection:
                self.status.setPlainText('检查针对旧连接快照；配置已改变，没有覆盖新配置。')
                return
            verified = dict(connection.verification, auth_models=dict(status='已实测', checked=now(), model_count=len(models)))
            self.connections.save(replace(connection, verification=verified, capability_status='列表已检查；生成未测试'))
            self.status.setPlainText('模型列表返回：\n' + '\n'.join(models[:100]) + '\n\n认证检查不代表文字生成、工具或图片通过。')
            if models:
                from PySide6.QtWidgets import QInputDialog
                chosen, ok = QInputDialog.getItem(self, '选择实际模型 ID', '服务返回的模型', models, editable=True)
                if ok:
                    self.model.setText(chosen)
            self.owner.refresh_models()
        self.start_operation(lambda: HttpTextProvider().list_models(connection, secret), finish)

    def choose_cli(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择已有 Codex CLI', '', 'CLI (*.exe *.cmd *.ps1 *.js)')
        if path:
            self.cli_path.setText(path)

    def detect_cli(self):
        connection = self.save_connection(allow_empty_model=True)
        if connection.provider != 'codex':
            raise ValueError('请先选择 Codex CLI 服务商')
        def finish(result):
            current = self.connections.get(connection.id)
            if current != connection:
                self.status.setPlainText('检测针对旧连接快照；配置已改变，没有覆盖新配置。')
                return
            verification = dict(connection.verification, cli_probe=dict(version=result['version'], login=result['logged_in'], checked=now()))
            self.connections.save(replace(connection, verification=verification, capability_status='CLI 已检测；生成未测试'))
            self.status.setPlainText(result['version'] + '\n登录状态：' + ('已登录' if result['logged_in'] else '未登录') + '\n已确认隔离、JSONL 与工具禁用参数；文字和图片生成尚未测试。')
            self.owner.refresh_models()
        self.start_operation(lambda: CodexTextProvider().detect(connection.cli_path, login=True), finish)

    def generation_test(self):
        connection = self.save_connection()
        if QMessageBox.question(self, '最小生成测试可能收费', f'通道：{connection.name}\n模型：{connection.model}\n发送资料：仅测试指令，不发送作品。\n次数：1；输出：128 token（CLI 为软限制）。费用未知。\n执行本次测试？') == QMessageBox.StandardButton.Yes:
            self.owner.start_text_task(connection_override=replace(connection, max_output=128), test_request=True)
            self.accept()

    def set_default(self):
        connection = self.save_connection()
        self.owner.options['default_connection'] = connection.id
        self.owner.save_preferences()
        self.owner.refresh_models()
        self.status.setPlainText('默认文字模型已更新；运行中的任务保持原选择。')

    def toggle_enabled(self):
        if not self.current_id:
            raise ValueError('请先选择连接')
        connection = self.connections.get(self.current_id)
        self.connections.save(replace(connection, enabled=not connection.enabled))
        self.refresh_list(connection.id)
        self.owner.refresh_models()

    def delete_connection(self):
        if not self.current_id:
            raise ValueError('请先选择连接')
        connection = self.connections.get(self.current_id)
        if QMessageBox.question(self, '删除连接', '删除“' + connection.name + '”及其凭据？作品和旧用量记录保留。') == QMessageBox.StandardButton.Yes:
            self.connections.delete(connection.id)
            self.current_id = None
            self.refresh_list()
            self.new_connection()
            self.owner.refresh_models()

    def save_appearance(self):
        self.owner.options.update(editor_font_size=self.font_size.value(), ui_font_size=self.ui_size.value())
        self.owner.theme_combo.setCurrentText(self.theme.currentText())
        self.owner.save_preferences()
        self.owner.apply_theme()
        self.accept()

    def reject(self):
        if self.busy:
            self.status.setPlainText('连接检查正在运行，等待完成后可关闭设置。')
            return
        super().reject()


def json_text(value):
    import json
    return json.dumps(value, ensure_ascii=False, indent=2)
