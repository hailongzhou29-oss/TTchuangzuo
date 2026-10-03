"""Selected TT-YingXu 8f80b197 widgets; original build functions with a local adapter."""
from PySide6.QtCore import Qt,QSize,QTimer,QUrl,QEvent
from PySide6.QtGui import QStandardItem,QStandardItemModel,QDesktopServices
from PySide6.QtWidgets import *
from app.ui.v2_widgets import QComboBox
from app.ui.interaction import AnimatedButton as QPushButton
from app.core.settings_controller import MODEL_CHANNEL_KEYS,MODEL_CHANNEL_LABELS,MODEL_DEFAULT_BASE,MODEL_KEY_URLS,MODEL_PRESETS
def set_status_tone(widget,tone): widget.setProperty('statusTone',tone); widget.style().unpolish(widget); widget.style().polish(widget)
class SearchableModelCombo(QComboBox):
    """Editable model selector whose own first line is the live search field."""
    def __init__(self, parent=None):
        super().__init__(parent); self.setEditable(True); self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMaxVisibleItems(24); self.setMinimumWidth(360); self.setToolTip("输入关键词搜索；点击右侧箭头展开全部已读取模型。")
        self._catalog = []; self._updating = False; self._selected_value = ""
        self._source_model = QStandardItemModel(self); self.setModel(self._source_model)
        self._completer = QCompleter(self._source_model, self); self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive); self._completer.setFilterMode(Qt.MatchFlag.MatchContains); self.setCompleter(self._completer)
        popup=self._completer.popup(); popup.setWindowFlags(popup.windowFlags()|Qt.WindowType.FramelessWindowHint|Qt.WindowType.NoDropShadowWindowHint); popup.setFrameShape(QFrame.Shape.NoFrame); popup.installEventFilter(self)
        self.lineEdit().setPlaceholderText("输入关键词过滤模型，或手动填写模型ID"); self.lineEdit().setClearButtonEnabled(True)
        self.activated.connect(self._on_activated)

    def set_catalog(self, rows, selected=""):
        unique = []
        for label, value in rows:
            item = (str(label or value), str(value or label))
            if item[1] and item[1] not in {row[1] for row in unique}: unique.append(item)
        self._catalog = unique; self._selected_value = str(selected or self._selected_value or "")
        self._updating = True; self._source_model.clear()
        for label, value in self._catalog:
            item = QStandardItem(label); item.setData(value, Qt.ItemDataRole.UserRole); self._source_model.appendRow(item)
        index = self.findData(self._selected_value)
        if index >= 0: self.setCurrentIndex(index); self.lineEdit().setText(self.itemText(index))
        else: self.setCurrentIndex(-1); self.lineEdit().setText(self._selected_value)
        self._updating = False
    def eventFilter(self,watched,event):
        if hasattr(self,'_completer') and watched is self._completer.popup() and event.type()==QEvent.Type.Show:
            from app.ui.interaction import tokens
            c=tokens(self); watched.setPalette(self.palette()); watched.setStyleSheet(f'QAbstractItemView {{background:{c["panel"]};color:{c["text"]};border:1px solid {c["border"]};padding:4px;}} QAbstractItemView::item {{padding:6px 10px;}} QAbstractItemView::item:selected {{background:{c["selected"]};color:{c["selected_text"]};}}')
        return super().eventFilter(watched,event)

    def model_value(self):
        text = self.lineEdit().text().strip()
        for label, value in self._catalog:
            if text == label or text == value: return value
        return text or self._selected_value

    def filter_text(self, text):
        value = str(text or ""); self.lineEdit().setText(value); self.lineEdit().setCursorPosition(len(value))
        self._completer.setCompletionPrefix(value)
        if value: self._completer.complete()

    def _on_activated(self, index):
        if index < 0: return
        selected_value = str(self.itemData(index) or self.itemText(index)); selected_label = self.itemText(index)
        self._updating = True; self._selected_value = selected_value
        resolved = self.findData(selected_value); self.setCurrentIndex(resolved if resolved >= 0 else -1); self.lineEdit().setText(selected_label); self._updating = False
        QTimer.singleShot(0, self.lineEdit().selectAll)

    def showPopup(self):
        current = self.model_value(); self._selected_value = current; self._updating = True
        index = self.findData(current)
        if index >= 0: self.setCurrentIndex(index); self.lineEdit().setText(self.itemText(index))
        self._updating = False
        if index >= 0: self.lineEdit().selectAll()
        QComboBox.showPopup(self)

class TTSettingsWidgets:
    def _build_codex_tab(self):
        self.codex_tab = QWidget(); root = QVBoxLayout(self.codex_tab); root.setContentsMargins(16, 16, 16, 16); root.setSpacing(12)
        grid = QGridLayout(); grid.setHorizontalSpacing(16); grid.setVerticalSpacing(12); grid.setColumnStretch(0, 1); grid.setColumnStretch(1, 1)
        def card(title: str) -> tuple[QGroupBox, QVBoxLayout]:
            box = QGroupBox(title); box.setMinimumHeight(164)
            body = QVBoxLayout(box); body.setContentsMargins(16, 14, 16, 14); body.setSpacing(7)
            return box, body
        status_card, status_body = card("Codex 状态")
        self.codex_status = QLabel("尚未检测"); self.codex_status.setProperty("muted", True)
        self.codex_version = QLabel("—"); self.codex_version.setProperty("muted", True)
        self.codex_auth = QLabel("—"); self.codex_auth.setProperty("muted", True)
        status_body.addWidget(self.codex_status); status_body.addWidget(self.codex_auth); status_body.addWidget(self.codex_version)
        detect = QPushButton("重新检测"); detect.clicked.connect(self.detect_codex_ui)
        login = QPushButton("登录 / 重新登录"); login.clicked.connect(self.start_codex_login_ui)
        status_actions = QHBoxLayout(); status_actions.addWidget(detect); status_actions.addWidget(login); status_actions.addStretch(1)
        status_body.addStretch(1); status_body.addLayout(status_actions); grid.addWidget(status_card, 0, 0)

        image_card, image_body = card("图片生成渠道")
        image_body.addWidget(QLabel("Codex Image · imagegen"))
        self.codex_image_capability_label = QLabel("图片生成：等待检测"); self.codex_image_capability_label.setProperty("muted", True)
        self.codex_image_current = QLabel("当前渠道：—"); self.codex_image_current.setProperty("muted", True)
        image_body.addWidget(self.codex_image_capability_label); image_body.addWidget(self.codex_image_current)
        self.codex_image_set_current = QPushButton("设为当前图片生成渠道"); self.codex_image_set_current.setProperty("success", True)
        self.codex_image_set_current.setEnabled(False); self.codex_image_set_current.clicked.connect(lambda: self.set_active_image_provider_ui("codex_image"))
        image_actions = QHBoxLayout(); image_actions.addWidget(self.codex_image_set_current); image_actions.addStretch(1)
        image_body.addStretch(1); image_body.addLayout(image_actions)
        grid.addWidget(image_card, 0, 1)

        runtime_card, runtime_body = card("本地运行")
        self.codex_local_program = QLabel("程序：等待检测"); self.codex_local_program.setProperty("muted", True)
        self.codex_local_model = QLabel("模型：跟随 Codex" if not self.c.channel_configs["codex_local"].model else "模型：使用高级设置中的覆盖值")
        self.codex_local_model.setProperty("muted", True)
        runtime_body.addWidget(self.codex_local_program); runtime_body.addWidget(self.codex_local_model); runtime_body.addWidget(QLabel("运行方式：本机 · 独立临时会话"))
        reload_environment = QPushButton("重新读取环境"); reload_environment.clicked.connect(self.detect_codex_ui)
        runtime_actions = QHBoxLayout(); runtime_actions.addWidget(reload_environment); runtime_actions.addStretch(1)
        runtime_body.addStretch(1); runtime_body.addLayout(runtime_actions); grid.addWidget(runtime_card, 1, 0)

        capability_card, capability_body = card("能力检测")
        self.codex_exec_capability = QLabel("○ Codex Exec：等待检测")
        self.codex_auth_capability = QLabel("○ 登录授权：等待检测")
        self.codex_skill_capability = QLabel("○ imagegen：等待检测")
        self.codex_generation_capability = QLabel("○ 实际生图：尚未由本软件验证")
        for label in (self.codex_exec_capability, self.codex_auth_capability, self.codex_skill_capability, self.codex_generation_capability):
            label.setProperty("muted", True); capability_body.addWidget(label)
        capability_body.addStretch(1); grid.addWidget(capability_card, 1, 1)
        root.addLayout(grid)

        self.codex_advanced_toggle = QPushButton("高级设置 ▸"); self.codex_advanced_toggle.clicked.connect(self.toggle_codex_advanced)
        root.addWidget(self.codex_advanced_toggle)
        self.codex_advanced_panel = QGroupBox("高级设置"); advanced = QFormLayout(self.codex_advanced_panel)
        self.codex_command = QLineEdit(); self.codex_command.setReadOnly(True)
        self.codex_command.setPlaceholderText("检测后显示本机Codex启动命令")
        self.codex_source = QLabel("—"); self.codex_source.setProperty("muted", True)
        self.codex_override = QLineEdit(str(self.c.codex_local_settings().get("commandPath") or "")); self.codex_override.setPlaceholderText("留空自动读取当前、用户级和机器级环境")
        choose_command = QPushButton("选择程序"); choose_command.clicked.connect(self.choose_codex_command)
        save_command = QPushButton("保存路径"); save_command.clicked.connect(self.save_codex_command)
        auto_command = QPushButton("恢复自动检测"); auto_command.clicked.connect(self.clear_codex_command)
        override_row = QHBoxLayout(); override_row.addWidget(self.codex_override, 1); override_row.addWidget(choose_command); override_row.addWidget(save_command); override_row.addWidget(auto_command)
        self.codex_model = QLineEdit(self.c.channel_configs["codex_local"].model)
        self.codex_model.setPlaceholderText("留空使用Codex当前默认模型")
        save_codex_model = QPushButton("保存模型设置"); save_codex_model.clicked.connect(self.save_codex_model_settings)
        codex_model_row = QHBoxLayout(); codex_model_row.addWidget(self.codex_model, 1); codex_model_row.addWidget(save_codex_model)
        note = QLabel("文本任务使用只读独立会话和结构化输出；图片任务使用内置 imagegen，自动带上画幅与质量目标。图片按实际像素回填，不缩放。")
        note.setWordWrap(True); note.setProperty("muted", True)
        docs = QPushButton("Codex登录与使用说明"); docs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://learn.chatgpt.com/docs/non-interactive-mode")))
        advanced.addRow("本机启动命令", self.codex_command); advanced.addRow("检测来源", self.codex_source)
        advanced.addRow("手动程序路径（可选）", override_row); advanced.addRow("语言模型覆盖（可选）", codex_model_row)
        advanced.addRow(note); advanced.addRow(docs)
        self.codex_advanced_panel.setVisible(False); root.addWidget(self.codex_advanced_panel); root.addStretch(1)
        self._codex_image_ready = False
        self.update_active_image_provider_ui()
        self.tabs.addTab(self.codex_tab, MODEL_CHANNEL_LABELS["codex_local"])

    def toggle_codex_advanced(self):
        visible = not self.codex_advanced_panel.isVisible()
        self.codex_advanced_panel.setVisible(visible)
        self.codex_advanced_toggle.setText("高级设置 ▾" if visible else "高级设置 ▸")

    def detect_codex_ui(self):
        if self._codex_detecting: return
        self._codex_detecting = True; self.codex_status.setText("● 检测中…"); set_status_tone(self.codex_status, "orange")
        def done(value):
            self.render_codex_status(value)
        def failed(text):
            self._codex_detecting = False; self._codex_detected = True
            cached=self.c.cached_codex_status()
            if cached and cached.get('authenticated'):
                self.render_codex_status(cached); self.codex_status.setText('● 已登录 · 本次检测未完成'); self.codex_status.setToolTip(str(text)); return
            self.codex_status.setText("● 检测失败"); set_status_tone(self.codex_status, "red")
            self.codex_auth.setText(str(text)); self.codex_version.setText("—"); self.codex_command.clear(); self.codex_source.setText("—")
            self._codex_image_ready = False; self.codex_local_program.setText("程序：检测失败")
            self.codex_image_capability_label.setText("图片生成：检测失败")
            self.codex_exec_capability.setText("! Codex Exec 检测失败"); self.codex_auth_capability.setText("! 登录状态未知")
            self.codex_skill_capability.setText("○ imagegen 未检测"); self.codex_generation_capability.setText("○ 实际生图：未检测")
            self.update_active_image_provider_ui()
        self.host.run_async("检测Codex本地代理", self.c.detect_codex, done, on_failure=failed,
                            count_as_project=False, play_completion_sound=False, quiet_background=True)

    def refresh_cached_codex_ui(self):
        value=self.c.cached_codex_status()
        if value: self.render_codex_status(value)

    def render_codex_status(self,value):
        self._codex_detecting=False; self._codex_detected=True; ready=bool(value.get('available') and value.get('authenticated'))
        self.codex_status.setText('● 已就绪 · 已保存验证' if ready and value.get('cached') else '● 已就绪' if ready else '● 尚未登录')
        set_status_tone(self.codex_status,'green' if ready else 'orange'); self.codex_status.setToolTip('验证时间：'+str(value.get('checked_at') or '本次检测'))
        self.codex_version.setText('版本：'+str(value.get('version') or '未检测到')); self.codex_auth.setText('账号：已登录，可复用本机授权' if value.get('authenticated') else '账号：尚未登录')
        self.codex_command.setText(str(value.get('command') or '')); self.codex_source.setText('手动程序路径' if value.get('source')=='manual_override' else '合并后的 Windows PATH')
        self.codex_local_program.setText('程序：'+('手动路径 ✓' if value.get('source')=='manual_override' else '自动检测 ✓' if value.get('available') else '未找到'))
        capability=self.c.codex_image_capability(value); self._codex_image_ready=bool(capability['ready'])
        self.codex_exec_capability.setText('✓ Codex Exec' if capability['available'] else '○ Codex Exec 未验证')
        self.codex_auth_capability.setText('✓ 登录授权' if capability['authenticated'] else '○ 尚未登录')
        self.codex_skill_capability.setText('✓ imagegen Skill 已发现' if capability['skillPresent'] else '○ imagegen Skill 尚未验证')
        success=bool(capability['lastSuccessAt']); self.codex_generation_capability.setText('✓ 本软件成功记录：'+capability['lastActualSize'] if success else '○ 实际生图：尚未由本软件验证')
        self.codex_image_capability_label.setText('图片生成：已有成功记录' if success and capability['ready'] else '图片生成：可尝试 · 尚未由本软件验证' if capability['ready'] else '图片生成：尚未就绪')
        self.update_active_image_provider_ui()

    def choose_codex_command(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择Codex本地启动文件", self.codex_override.text(), "Codex启动文件 (*.exe *.cmd *.bat *.js);;所有文件 (*)")
        if path: self.codex_override.setText(path)

    def save_codex_command(self):
        try:
            value = self.c.save_codex_command_path(self.codex_override.text()); self.codex_override.setText(str(value.get("commandPath") or "")); self._codex_detected = False; self.detect_codex_ui()
        except Exception as exc: self.error("保存Codex路径失败", str(exc))

    def clear_codex_command(self):
        try:
            self.c.save_codex_command_path(""); self.codex_override.clear(); self._codex_detected = False; self.detect_codex_ui()
        except Exception as exc: self.error("恢复自动检测失败", str(exc))

    def save_current_channel(self, key: str):
        if key not in self.forms: return
        try:
            value = self.c.save_model_channel(key, self.configs()[key]); self.forms[key][1].clear()
            self.update_all_key_statuses(); self.update_provider_tab_labels()
            state = "，当前仍为生产模型" if value.get("active") else "，尚未启用"
            secret_state="密钥已使用 Windows 加密保存。" if self.c.model_key_status(key)['saved'] else "尚未保存接口密钥。"
            self.info("设置已保存", f"{MODEL_CHANNEL_LABELS[key]}接口设置已独立保存{state}；{secret_state}")
        except Exception as exc: self.error("保存失败", str(exc))

    def save_codex_model_settings(self):
        try:
            value = self.c.save_model_channel("codex_local", self.configs()["codex_local"])
            self.codex_local_model.setText("模型：使用高级设置中的覆盖值" if self.codex_model.text().strip() else "模型：跟随 Codex")
            self.info("设置已保存", "Codex本地模型设置已保存" + ("，当前仍为生产模型。" if value.get("active") else "，尚未启用。"))
        except Exception as exc: self.error("保存失败", str(exc))

    def channel_form_is_dirty(self, key: str) -> bool:
        saved = self.c.channel_configs[key]
        if key == "codex_local":
            return self.codex_model.text().strip() != str(saved.model or "") or self.codex_override.text().strip() != self.c.codex_local_settings()['commandPath']
        base, key_edit, model = self.forms[key]; current_model = model.model_value() if isinstance(model, SearchableModelCombo) else str(model.currentData() or model.currentText())
        current_base = base.text().strip() or MODEL_DEFAULT_BASE[key]
        output_dirty=False
        if key in getattr(self,'output_controls',{}):
            mode,tokens,structured,_=self.output_controls[key]
            output_dirty=mode.currentData()!=saved.output_mode or tokens.value()!=saved.max_output or structured.isChecked()!=saved.json_mode or self.format_controls[key].currentData()!=saved.format_mode
        return bool(output_dirty or key_edit.text().strip() or current_base.rstrip("/") != str(saved.base_url or "").rstrip("/") or str(current_model or "").strip() != str(saved.model or ""))

    def activate_current_model(self):
        key = self.current_provider()
        if not key: return
        if self.channel_form_is_dirty(key):
            self.info("存在未保存设置", "当前页面有未保存修改，请先保存当前接口设置，再启用该模型。")
            return
        try:
            self.c.activate_model_channel(key); self.update_all_key_statuses(); self.update_provider_tab_labels()
            self.update_settings_actions(self.tabs.currentIndex())
            if key == "codex_local": self.refresh_cached_codex_ui()
            self.info("已启用", f"{MODEL_CHANNEL_LABELS[key]}已设为当前生产模型；本次操作没有保存或修改其他接口设置。")
        except Exception as exc: self.error("启用失败", str(exc))

    def current_provider(self) -> str:
        current = self.tabs.currentWidget()
        if current is self.codex_tab: return "codex_local"
        if current is self.language_model_tab:
            item = self.provider_list.currentItem()
            return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""
        return ""

    def provider_changed(self, index: int):
        if index < 0: return
        self.provider_stack.setCurrentIndex(index); self.update_settings_actions(self.tabs.currentIndex())

    def update_provider_tab_labels(self):
        language_index = self.tabs.indexOf(self.language_model_tab); codex_index = self.tabs.indexOf(self.codex_tab)
        if language_index >= 0: self.tabs.setTabText(language_index, "国内模型" + (" · 当前启用" if self.c.active_provider in self.api_provider_keys else ""))
        if codex_index >= 0: self.tabs.setTabText(codex_index, "Codex 本地" + (" · 当前启用" if self.c.active_provider == "codex_local" else ""))
        for index in range(self.provider_list.count()):
            item = self.provider_list.item(index); key = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if key == self.c.active_provider: status = "● 当前启用"
            elif self.c.model_key_status(key).get("saved"): status = "● 已配置"
            else: status = "○ 未配置"
            item.setText(f"{MODEL_CHANNEL_LABELS[key]}　{status}")

    def _build_openai_image_settings_tab(self):
        settings = self.c.openai_image_settings(); page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(10, 10, 10, 10); layout.setSpacing(10)
        self._openai_image_catalog_source = (settings["protocol"], settings["baseUrl"])
        self._openai_image_catalog_updated_at = float(settings.get("modelCatalogUpdatedAt") or 0)
        self._openai_image_model_settings = dict(settings.get("modelSettings") or {})
        self._openai_image_model_settings_source = (settings["protocol"], settings["baseUrl"])
        site_row = QHBoxLayout(); site_row.addWidget(QLabel("已保存网站"))
        self.openai_image_site_selector = QComboBox(); self.openai_image_site_selector.setMinimumWidth(260)
        self.openai_image_site_selector.setToolTip("选择已保存网站，立即恢复该网站的协议、地址、模型、价格设置和独立保存的Key，并切换生图渠道。")
        site_row.addWidget(self.openai_image_site_selector, 2)
        site_hint = QLabel("选择后直接切换；点击“保存设置”可记录当前网站"); site_hint.setProperty("muted", True); site_hint.setWordWrap(True); site_row.addWidget(site_hint, 1)
        connection_box = QGroupBox("服务连接与模型（国内／海外接口）"); connection_box.setObjectName("SettingsCard"); form = QGridLayout(connection_box); form.setHorizontalSpacing(10); form.setVerticalSpacing(8)
        self.openai_image_base = QLineEdit(settings["baseUrl"]); self.openai_image_base.setPlaceholderText("https://api.example.com 或 https://api.example.com/v1")
        self.openai_image_key = QLineEdit(); self.openai_image_key.setEchoMode(QLineEdit.EchoMode.Password); self.openai_image_key.setPlaceholderText("留空继续使用已加密保存的Key")
        self.openai_image_model = SearchableModelCombo(); self.openai_image_model.set_catalog([(value, value) for value in settings.get("modelCatalog") or [settings["modelId"]]], settings["modelId"])
        self.openai_image_protocol = QComboBox(); self.openai_image_protocol.addItem("自动兼容（同步／异步／中转站）", "openai_images_v1"); self.openai_image_protocol.addItem("Seedance.NZ 专用协议", "seedance_nz_async_image"); self.openai_image_protocol.setCurrentIndex(max(0, self.openai_image_protocol.findData(settings["protocol"])))
        self.openai_image_strategy = QComboBox(); self.openai_image_strategy.addItem("精确像素（默认）", "exact_pixels"); self.openai_image_strategy.addItem("固定兼容尺寸", "openai_fixed"); self.openai_image_strategy.setCurrentIndex(max(0, self.openai_image_strategy.findData(settings["sizeStrategy"])))
        self.openai_image_strategy.setEnabled(settings["protocol"] != "seedance_nz_async_image")
        self.openai_image_strategy_note = QLabel(); self.openai_image_strategy_note.setWordWrap(True); self.openai_image_strategy_note.setProperty("muted", True)
        self.openai_image_strategy.currentIndexChanged.connect(self.update_openai_image_strategy_note); self.update_openai_image_strategy_note()
        self.openai_image_key_status = QLabel(); self.openai_image_key_status.setProperty("muted", True)
        active = str(self.c.image_provider_settings().get("activeImageProvider") or "image_api"); selected_provider = "seedance_nz" if settings["protocol"] == "seedance_nz_async_image" else "openai_compatible"
        self.openai_image_provider_status = QLabel("● 当前图片生成渠道" if active == selected_provider else "○ 已配置 · 当前未启用"); self.openai_image_provider_status.setProperty("muted", True)
        self.openai_image_connection_status = QLabel("连接状态：未测试"); self.openai_image_connection_status.setWordWrap(True); self.openai_image_connection_status.setProperty("muted", True)
        self.openai_image_save_model = QPushButton("保存模型"); self.openai_image_save_model.clicked.connect(self.save_openai_image_model_ui)
        refresh = QPushButton("读取模型列表"); refresh.clicked.connect(self.refresh_openai_image_models_ui)
        form.addWidget(QLabel("兼容模式"), 0, 0); form.addWidget(self.openai_image_protocol, 0, 1)
        form.addWidget(QLabel("Base URL"), 0, 2); form.addWidget(self.openai_image_base, 0, 3, 1, 3)
        form.addWidget(QLabel("API Key"), 1, 0); form.addWidget(self.openai_image_key, 1, 1, 1, 3)
        form.addWidget(QLabel("Key状态"), 1, 4); form.addWidget(self.openai_image_key_status, 1, 5)
        form.addWidget(QLabel("模型"), 2, 0); form.addWidget(self.openai_image_model, 2, 1, 1, 3); form.addWidget(refresh, 2, 4); form.addWidget(self.openai_image_save_model, 2, 5)
        form.addWidget(self.openai_image_connection_status, 3, 0, 1, 5); form.addWidget(self.openai_image_provider_status, 3, 5)
        form.setColumnStretch(1, 1); form.setColumnStretch(3, 2)

        capability_box = QGroupBox("按平台文档填写画幅、尺寸与质量"); capability_box.setObjectName("SettingsCard"); capability_layout = QVBoxLayout(capability_box)
        size_row = QHBoxLayout(); size_row.addWidget(QLabel("尺寸策略")); size_row.addWidget(self.openai_image_strategy)
        size_row.addWidget(QLabel("默认档位")); self.openai_image_tier = QComboBox(); self.openai_image_tier.addItems(["1K", "2K", "4K"])
        self.openai_image_tier.setCurrentText(settings["defaultSizeTier"]); size_row.addWidget(self.openai_image_tier)
        size_row.addWidget(QLabel("手填size")); self.openai_image_manual_size = QLineEdit(str(settings.get("manualSize") or ""))
        self.openai_image_manual_size.setPlaceholderText("可选：照文档填1024x1024、auto等")
        self.openai_image_manual_size.setToolTip("留空按资产画幅和档位换算；填写后直接作为平台size参数，所有使用此网站的生图任务均发送此值。")
        size_row.addWidget(self.openai_image_manual_size, 2)
        size_row.addWidget(QLabel("质量")); self.openai_image_quality = QComboBox()
        self.openai_image_quality.setEditable(True)
        self.openai_image_quality.addItem("模型默认", "model_default")
        for option in ("auto", "low", "medium", "high"): self.openai_image_quality.addItem(option, option)
        self.openai_image_quality.setCurrentIndex(max(0, self.openai_image_quality.findData(settings["quality"])))
        size_row.addWidget(self.openai_image_quality)
        ratio_row = QHBoxLayout(); ratio_row.addWidget(QLabel("支持画幅")); self.openai_image_ratio_checks = {}
        for value in ("16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"):
            check_ratio = QCheckBox(value); check_ratio.setChecked(value in (settings.get("supportedRatios") or []))
            self.openai_image_ratio_checks[value] = check_ratio; ratio_row.addWidget(check_ratio)
        self.openai_image_extra_ratios = QLineEdit(",".join(value for value in settings.get("supportedRatios") or [] if value not in self.openai_image_ratio_checks))
        self.openai_image_extra_ratios.setPlaceholderText("其他画幅，逗号分隔"); ratio_row.addWidget(self.openai_image_extra_ratios, 1)
        self._openai_image_capability = dict(settings.get("modelCapabilities") or {})
        self._openai_image_capability_source = (settings["protocol"], settings["baseUrl"])
        self.openai_image_capability_status = QLabel("画幅、尺寸和质量按平台文档手填；接口未提供时也可以直接保存。")
        self.openai_image_capability_status.setProperty("muted", True); self.openai_image_capability_status.setWordWrap(True)
        self._set_openai_image_size_choices(list(self._openai_image_capability.get("sizeTiers") or []), settings["defaultSizeTier"])
        self._set_openai_image_quality_choices(list(self._openai_image_capability.get("qualities") or []), settings["quality"])
        self._render_openai_image_capability()
        capability_layout.addLayout(size_row); capability_layout.addLayout(ratio_row); capability_layout.addWidget(self.openai_image_capability_status)
        capability_layout.addWidget(self.openai_image_strategy_note)

        pricing_box = QGroupBox("费用读取与估算"); pricing_box.setObjectName("SettingsCard"); pricing_layout = QVBoxLayout(pricing_box); pricing = QHBoxLayout()
        self.openai_image_pricing_enabled = QCheckBox("启用费用估算"); self.openai_image_pricing_enabled.setChecked(bool(settings["pricingEnabled"])); pricing.addWidget(self.openai_image_pricing_enabled)
        read_price = QPushButton("读取费用"); read_price.clicked.connect(self.read_openai_image_price_ui); pricing.addWidget(read_price)
        self.openai_image_apply_prices = QPushButton("确认并应用读取价格"); self.openai_image_apply_prices.setEnabled(False); self.openai_image_apply_prices.clicked.connect(self.apply_openai_image_read_prices_ui); pricing.addWidget(self.openai_image_apply_prices)
        self.openai_image_price_status = QLabel("当前为手工估算价；服务商未返回价格时不会自动改写。")
        self.openai_image_price_status.setProperty("muted", True); self.openai_image_price_status.setWordWrap(True)
        self._openai_image_price_source = str(settings.get("pricingSource") or "manual")
        self._openai_image_price_identity = (settings["protocol"], settings["baseUrl"], settings["modelId"])
        if self._openai_image_price_source == "provider_metadata": self.openai_image_price_status.setText("当前估算价来自上次读取的服务商模型信息；重新读取可检查变化。")
        self.openai_image_price_spins = {}
        for tier in ("1K", "2K", "4K"):
            spin = QDoubleSpinBox(); spin.setRange(0, 999999); spin.setDecimals(4); spin.setPrefix("¥ "); spin.setSuffix(" / 张"); spin.setValue(float(settings["unitPrices"].get(tier) or 0)); self.openai_image_price_spins[tier] = spin
            spin.valueChanged.connect(self.mark_openai_image_price_manual)
            pricing.addWidget(QLabel(tier)); pricing.addWidget(spin)
        pricing.addStretch(1); pricing_layout.addLayout(pricing); pricing_layout.addWidget(self.openai_image_price_status)

        save = QPushButton("保存设置"); save.setProperty("success", True); check = QPushButton("检查本地配置"); test = QPushButton("测试连接")
        self.openai_image_set_current = QPushButton("设为当前图片生成渠道"); self.openai_image_set_current.setEnabled(active != selected_provider)
        delete = QPushButton("删除已保存Key"); save.clicked.connect(self.save_openai_image_ui); check.clicked.connect(self.check_openai_image_ui); test.clicked.connect(self.test_openai_image_ui)
        self.openai_image_set_current.clicked.connect(lambda: self.set_active_image_provider_ui(self.current_general_image_provider_id())); delete.clicked.connect(self.delete_openai_image_key_ui)
        actions = QHBoxLayout(); actions.addWidget(check); actions.addWidget(test); actions.addWidget(save); actions.addWidget(self.openai_image_set_current); actions.addStretch(1); actions.addWidget(delete)
        layout.addLayout(site_row); layout.addWidget(connection_box); layout.addWidget(capability_box); layout.addWidget(pricing_box); layout.addLayout(actions); layout.addStretch(1)
        for editor in (self.openai_image_base, self.openai_image_key): editor.textChanged.connect(self.invalidate_openai_image_connection)
        self.openai_image_base.textChanged.connect(self.openai_image_base_changed)
        self.openai_image_base.editingFinished.connect(self.update_openai_image_key_status)
        self.openai_image_model.currentTextChanged.connect(self.openai_image_model_changed); self.openai_image_strategy.currentIndexChanged.connect(self.openai_image_size_strategy_changed)
        self.openai_image_tier.currentTextChanged.connect(self.refresh_openai_image_manual_summary); self.openai_image_protocol.currentIndexChanged.connect(self.openai_image_protocol_changed)
        self.openai_image_manual_size.textChanged.connect(self.openai_image_size_strategy_changed)
        self.openai_image_quality.currentTextChanged.connect(self.mark_openai_image_price_manual)
        self.openai_image_quality.currentTextChanged.connect(self._render_openai_image_capability)
        for check_ratio in self.openai_image_ratio_checks.values(): check_ratio.toggled.connect(self._render_openai_image_capability)
        self.openai_image_extra_ratios.textChanged.connect(self._render_openai_image_capability)
        self.tabs.addTab(page, "通用图片API"); self.openai_image_settings_tab = page; self.update_openai_image_key_status()
        self.openai_image_site_selector.activated.connect(self.activate_openai_image_site_ui)
        self.refresh_openai_image_sites_ui()

    def _set_openai_image_size_choices(self, available: list[str], selected: str):
        tiers = [tier for tier in ("1K", "2K", "4K") if self.openai_image_protocol.currentData() != "seedance_nz_async_image" or not available or tier in available]
        if not tiers: tiers = ["1K", "2K", "4K"]
        self.openai_image_tier.blockSignals(True); self.openai_image_tier.clear(); self.openai_image_tier.addItems(tiers)
        self.openai_image_tier.setCurrentText(selected if selected in tiers else tiers[0]); self.openai_image_tier.blockSignals(False)

    def _set_openai_image_ratios(self, selected: list[str]):
        for ratio, checkbox in self.openai_image_ratio_checks.items():
            checkbox.blockSignals(True); checkbox.setChecked(ratio in selected); checkbox.blockSignals(False)
        self.openai_image_extra_ratios.blockSignals(True)
        self.openai_image_extra_ratios.setText(",".join(ratio for ratio in selected if ratio not in self.openai_image_ratio_checks))
        self.openai_image_extra_ratios.blockSignals(False)

    def _set_openai_image_quality_choices(self, available: list[str], selected: str):
        seedance = self.openai_image_protocol.currentData() == "seedance_nz_async_image"
        options = ["model_default"] if seedance else ["model_default", "auto", "low", "medium", "high"]
        if not seedance and selected and selected not in options: options.append(selected)
        self.openai_image_quality.blockSignals(True); self.openai_image_quality.clear()
        for option in options: self.openai_image_quality.addItem("模型默认" if option == "model_default" else option, option)
        self.openai_image_quality.setCurrentIndex(max(0, self.openai_image_quality.findData(selected))); self.openai_image_quality.blockSignals(False)
        self.openai_image_quality.setEditable(not seedance); self.openai_image_quality.setEnabled(not seedance)

    def _render_openai_image_capability(self, *_):
        chosen = [value for value, checkbox in self.openai_image_ratio_checks.items() if checkbox.isChecked()]
        chosen.extend(value.strip() for value in self.openai_image_extra_ratios.text().replace("，", ",").split(",") if value.strip())
        size = self.openai_image_manual_size.text().strip() or "按资产画幅和档位换算"
        quality = self.openai_image_quality.currentText().strip() or "模型默认"
        self.openai_image_capability_status.setText(f"手填画幅：{'、'.join(chosen) or '未限定'}｜size：{size}｜质量：{quality}。按平台文档填写后直接保存。")

    def refresh_openai_image_manual_summary(self, *_):
        self._render_openai_image_capability()
