from __future__ import annotations

import difflib
import json
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QThreadPool
from PySide6.QtGui import QAction, QFont, QKeySequence, QPixmap, QTextCursor, QTextOption
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTextBrowser, QTextEdit, QToolButton, QVBoxLayout, QWidget)

from app.core.cover import default_cover, render_cover
from app.core.files import write_json
from app.core.services import RuleService, Workspace, export_document, import_preview
from app.storage.project import LockedError, ConflictError
from app.ui.cover_dialog import CoverDialog
from app.ui.editor import WritingEditor
from app.ui.theme import THEMES, stylesheet
from app.ui.home import HomePage
from app.ui.icons import BUTTON_ICONS, NAV_ICONS, icon
from app.storage.connections import ConnectionStore
from app.storage.image_connections import ImageConnectionStore
from app.core.tasks import TaskService
from app.providers.contracts import CancelToken
from app.ui.task_worker import TaskWorker
from app.ui.model_settings import SettingsDialog
from app.ui.knowledge_dialog import KnowledgeDialog
from app.core.rules import ProjectRules
from app.core.knowledge import FactService
from app.core.context import ChatService, CacheService
from app.core import stages
from app.core.writing import WritingService
from app.ui.case_page import CasePage
from app.ui.workflow_dialog import configure_creation, generate_workflow, planning_dialog
from app.ui.work_views import WorkViews
from app.ui.rule_editor import edit_rule, load_package, preview_and_import

NAVIGATION = ['创作项目', '小说创作', '剧本创作', '文案创作', '参考与仿写', '内容改编', '影视案例库', '灵感与研究', '资料与规则', '模型与设置']
APPLICATION_NAME = 'TT 创作助手'


class MainWindow(QMainWindow):
    def __init__(self, workspace: Workspace, resources: Path, preferences: Path):
        super().__init__()
        self.workspace, self.resources, self.preferences = workspace, resources, preferences
        self.store = None
        self.document_id = None
        self.base_revision = None
        self.loading = False
        self.dirty = False
        self.focus_mode = False
        self._focus_visibility = None
        self.options = self.load_preferences()
        self.connections = ConnectionStore(preferences.parent)
        self.image_connections = ImageConnectionStore(preferences.parent)
        self.active_task = None
        self.active_image_task = None
        self.last_task = None
        self.close_after_task = False
        self.backup_operation=None
        self.backup_timer=QTimer(self)
        self.backup_timer.timeout.connect(lambda:self.run(self.start_automatic_backup))
        self.backup_poll=QTimer(self)
        self.backup_poll.setInterval(50)
        self.backup_poll.timeout.connect(self.poll_backup_completion)
        self.close_after_backup=False
        self.text_completion_poll=QTimer(self)
        self.text_completion_poll.setInterval(50)
        self.text_completion_poll.timeout.connect(self.poll_text_completion)
        self.theme = self.options.get('theme', '雾白浅色')
        self.setWindowTitle(APPLICATION_NAME)
        self.resize(1440, 900)
        self.setMinimumSize(1024, 640)
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.setInterval(1000)
        self.autosave.timeout.connect(lambda: self.save(show_error=False))
        self.build_ui()
        self.apply_theme()
        self.run(self.refresh_models)
        self.configure_backup_timer()
        self.apply_saved_layout()
        self.refresh_projects()
        self.navigation.setCurrentRow(0)
        last = self.options.get('last_project')
        if last and (Path(last) / 'project.sqlite').is_file():
            self.run(lambda: self.open_project(Path(last), writing=False))

    def load_preferences(self):
        if self.preferences.is_file():
            try:
                value = json.loads(self.preferences.read_text(encoding='utf-8'))
                if isinstance(value, dict):
                    return value
            except (ValueError, OSError):
                pass
        return {}

    def save_preferences(self):
        self.options['theme'] = self.theme
        if hasattr(self,'outer') and not self.focus_mode and self.isVisible():
            self.options['layout']=dict(outer_sizes=self.outer.sizes(),editor_sizes=self.editor_splitter.sizes(),
                sidebar_visible=not self.sidebar.isHidden(),directory_visible=not self.directory.isHidden(),assistant_visible=not self.assistant.isHidden())
        write_json(self.preferences, self.options)

    def apply_saved_layout(self):
        saved=self.options.get('layout',{})
        for widget,key,count in [(self.outer,'outer_sizes',3),(self.editor_splitter,'editor_sizes',2)]:
            values=saved.get(key)
            if isinstance(values,list) and len(values)==count and all(isinstance(v,int) and 0<=v<=10000 for v in values):
                widget.setSizes(values)
        for widget,key in [(self.sidebar,'sidebar_visible'),(self.directory,'directory_visible'),(self.assistant,'assistant_visible')]:
            if isinstance(saved.get(key),bool):
                widget.setVisible(saved[key])
        if self.width()<1120:
            self.assistant.hide()

    def restore_layout_defaults(self):
        self.exit_focus()
        self.sidebar.show()
        self.directory.show()
        self.assistant.setVisible(self.width()>=1120)
        self.outer.setSizes([232,764,444])
        self.editor_splitter.setSizes([220,640])
        self.view_combo.setCurrentIndex(0)
        self.options['editor_font_size']=18
        self.options['ui_font_size']=14
        self.apply_theme()
        self.save_preferences()

    def run(self, function):
        try:
            return function()
        except Exception as exc:
            QMessageBox.warning(self, '操作未完成', str(exc))
            return False

    def button(self, text, callback, primary=False, tooltip=None):
        button = QPushButton(text)
        from app.core.actions import action_id
        identifier=action_id(callback)
        if identifier:
            button.setProperty('action_id',identifier)
        if text in BUTTON_ICONS:
            button.setProperty('icon_name', BUTTON_ICONS[text])
            button.setIcon(icon(BUTTON_ICONS[text]))
            button.setIconSize(QSize(20, 20))
        if primary:
            button.setObjectName('primary')
        if tooltip:
            button.setToolTip(tooltip)
        button.clicked.connect(lambda checked=False: self.run_action(callback,identifier,text) if identifier else self.run(callback))
        return button

    def run_action(self,function,identifier,label):
        from app.core.actions import freeze,record
        before=self.store
        target=before
        snapshot=None
        try:
            if getattr(function,'__name__','') in {'new_project','restore_backup','toggle_project_view'}:
                target=None
            elif identifier in {'P03','P06','P07','P08','P09','P10'}:
                target=self.selected_project()
            snapshot=freeze(self,identifier,label,store=target)
            result=function()
        except Exception as exc:
            if snapshot:
                try:
                    record(self,snapshot,'failed',type(exc).__name__,store=target)
                except Exception:
                    pass
            QMessageBox.warning(self,'操作未完成',str(exc))
            return False
        destination=target if target else (self.store if self.store is not before else None)
        try:
            record(self,snapshot,'handler_returned',store=destination)
        except Exception:
            self.status.setText('操作已返回，但审计记录未能写入；请检查项目目录权限。')
        return result

    def label(self, text, name=None):
        label = QLabel(text)
        if name:
            label.setObjectName(name)
        label.setWordWrap(True)
        return label

    def shortcut(self, key, function):
        action = QAction(self)
        action.setShortcut(QKeySequence(key))
        action.triggered.connect(lambda: None if self.editor.composing or self.assistant_input.composing else self.run(function))
        self.addAction(action)

    def build_ui(self):
        shell = QWidget()
        vertical = QVBoxLayout(shell)
        vertical.setContentsMargins(0, 0, 0, 0)
        vertical.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(24, 4, 20, 4)
        header.addWidget(self.label(APPLICATION_NAME, 'subheading'))
        header.addSpacing(12)
        self.workspace_label = self.label(self.theme + '工作室', 'muted')
        header.addWidget(self.workspace_label)
        header.addStretch()
        header.addWidget(self.button('导航', self.toggle_navigation))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(THEMES)
        self.theme_combo.setCurrentText(self.theme)
        self.theme_combo.currentTextChanged.connect(self.change_theme)
        header.addWidget(self.theme_combo)
        self.assistant_toggle = self.button('收起助手', self.toggle_assistant)
        header.addWidget(self.assistant_toggle)
        header_widget = QWidget()
        header_widget.setObjectName('appHeader')
        header_widget.setLayout(header)
        header_widget.setFixedHeight(52)
        vertical.addWidget(header_widget)
        self.outer = QSplitter(Qt.Orientation.Horizontal)
        self.navigation = QListWidget()
        self.navigation.setObjectName('navigation')
        self.navigation.setMinimumWidth(56)
        self.navigation.setMaximumWidth(224)
        self.navigation.addItems(NAVIGATION)
        self.navigation.currentRowChanged.connect(lambda row: self.run(lambda: self.navigate(row)))
        self.sidebar = QFrame()
        self.sidebar.setObjectName('sidebar')
        self.sidebar.setMinimumWidth(56)
        self.sidebar.setMaximumWidth(250)
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(12, 22, 12, 18)
        side_layout.setSpacing(12)
        side_layout.addWidget(self.navigation, 1)
        for index in (8, 9):
            self.navigation.item(index).setHidden(True)
        for name, row in [('资料与规则', 8), ('模型与设置', 9)]:
            action = self.button(name, lambda index=row: self.navigation.setCurrentRow(index))
            action.setObjectName('sidebarAction')
            side_layout.addWidget(action)
        self.outer.addWidget(self.sidebar)
        self.pages = QStackedWidget()
        self.pages.setMinimumWidth(420)
        self.home = self.build_home()
        self.writing = self.build_writing()
        self.rules_page = self.build_rules()
        self.cases_page = self.build_cases()
        from app.ui.creator_page import CreatorPage
        self.creator_page=CreatorPage(self)
        for page in (self.home, self.writing, self.rules_page, self.cases_page,self.creator_page):
            self.pages.addWidget(page)
        self.outer.addWidget(self.pages)
        self.assistant = self.build_assistant()
        self.assistant.setMinimumWidth(320)
        self.assistant.setMaximumWidth(520)
        self.outer.addWidget(self.assistant)
        self.outer.setStretchFactor(1, 1)
        self.outer.setSizes([232, 764, 444])
        vertical.addWidget(self.outer, 1)
        self.setCentralWidget(shell)
        self.status = self.label('本地就绪 · 无需 KEY')
        self.word_count = self.label('0 字')
        self.project_status = self.label('未打开项目')
        self.statusBar().addWidget(self.status, 1)
        self.statusBar().addPermanentWidget(self.project_status)
        self.statusBar().addPermanentWidget(self.word_count)
        self.statusBar().setFixedHeight(28)
        self.shortcut('Ctrl+N', self.new_project)
        self.shortcut('Ctrl+O', self.import_file)
        self.shortcut('Ctrl+S', self.save)
        self.shortcut('Ctrl+F', self.find_dialog)
        self.shortcut('Ctrl+H', lambda: self.find_dialog(replace=True))
        self.shortcut('Ctrl+Shift+Z', self.editor.redo)
        self.shortcut('Ctrl+Return', self.start_text_task)
        self.shortcut('Escape', self.exit_focus)

    def build_home(self):
        return HomePage(self)

    def build_writing(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.mode_label = self.label('小说创作', 'subheading')
        view_header=QHBoxLayout()
        view_header.addWidget(self.mode_label,1)
        self.view_combo=QComboBox()
        self.view_combo.addItems(['写作','大纲','对照','审稿','专注'])
        view_header.addWidget(self.view_combo)
        layout.addLayout(view_header)
        toolbar = QHBoxLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText('文档标题')
        self.title.editingFinished.connect(lambda: self.run(self.rename_document))
        toolbar.addWidget(self.title, 1)
        toolbar.addWidget(self.button('保存', self.save, True, 'Ctrl+S'))
        toolbar.addWidget(self.button('封面', self.open_cover))
        toolbar.addWidget(self.button('创作阶段', lambda: generate_workflow(self)))
        operations = QToolButton()
        operations.setText('更多')
        operations.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(operations)
        for text, fn in [('确认定稿', self.confirm_draft), ('创作设定', lambda: configure_creation(self)),
            ('已确认规划 / 大纲', lambda: planning_dialog(self)), ('锁定 / 解锁当前大纲节点', self.toggle_outline_lock),
            ('锁定人物对白', self.lock_typed_dialogue), ('解除人物对白锁', self.unlock_typed_dialogue),
            ('来源信息', self.reference_info), ('读取用户指定公开资料', self.research_public), ('新建灵感笔记', self.new_inspiration),
            ('相似表达检查', self.similarity_check), ('人物与设定', self.open_knowledge),
            ('提取设定候选', lambda: self.start_text_task(stage_override='fact_extract')),
            ('生成章节摘要', lambda: self.start_text_task(stage_override='chapter_summary')),
            ('导出全文', self.export), ('导出选区', lambda: self.export(selection=True)), ('版本与恢复', self.versions), ('查找 / 替换', lambda: self.find_dialog(replace=True)), ('锁定选区', self.lock_selection), ('明确解锁当前文档', self.unlock), ('添加批注', self.annotation), ('查看批注', self.show_annotations), ('本地格式检查', self.validate), ('从来源建新稿', self.branch), ('对照来源', self.compare_source), ('专注写作', self.enter_focus), ('收起 / 展开目录', self.toggle_directory)]:
            action = menu.addAction(text)
            action.triggered.connect(lambda checked=False, callback=fn: self.run(callback))
        operations.setMenu(menu)
        toolbar.addWidget(operations)
        layout.addLayout(toolbar)
        self.editor_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.directory = QWidget()
        self.directory.setMinimumWidth(180)
        self.directory.setMaximumWidth(320)
        tree_layout = QVBoxLayout(self.directory)
        tree_layout.setContentsMargins(0, 0, 6, 0)
        self.documents = QListWidget()
        self.documents.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.documents.model().rowsMoved.connect(lambda: QTimer.singleShot(0, lambda: self.run(self.reorder_documents)))
        self.documents.currentItemChanged.connect(lambda current, previous: self.run(lambda: self.choose_document(current, previous)))
        tree_layout.addWidget(self.label('项目目录 · 拖动排序', 'muted'))
        tree_layout.addWidget(self.documents, 1)
        tree_layout.addWidget(self.button('新增章 / 场 / 文档', self.new_document))
        bottom = QHBoxLayout()
        bottom.addWidget(self.button('回收', self.trash_document))
        bottom.addWidget(self.button('恢复', self.restore_document))
        tree_layout.addLayout(bottom)
        self.editor_splitter.addWidget(self.directory)
        self.editor = WritingEditor()
        self.editor.textChanged.connect(self.text_changed)
        self.editor.composition_changed.connect(self.composition_changed)
        self.editor_splitter.addWidget(self.editor)
        self.editor_splitter.setStretchFactor(1, 1)
        self.editor_splitter.setSizes([220, 640])
        self.work_views=WorkViews(self,self.editor_splitter)
        self.view_combo.currentIndexChanged.connect(self.work_views.show_view)
        layout.addWidget(self.work_views,1)
        self.document_note = self.label('当前稿：草稿 · 自动保存至本机', 'muted')
        layout.addWidget(self.document_note)
        return page

    def build_assistant(self):
        panel = QFrame()
        panel.setObjectName('assistant')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 24, 20, 20)
        layout.setSpacing(16)
        heading = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(icon('sparkles', THEMES[self.theme]['accent'], 32).pixmap(32, 32))
        heading.addWidget(mark)
        heading.addWidget(self.label('AI 创作助手', 'subheading'), 1)
        heading.addWidget(self.button('收起', self.toggle_assistant))
        layout.addLayout(heading)
        layout.addWidget(self.label('陪你把灵感，变成好作品。', 'muted'))
        from PySide6.QtWidgets import QTabBar
        self.assistant_mode = QTabBar()
        for name in ['讨论', '写作', '审稿']:
            self.assistant_mode.addTab(name)
        self.assistant_mode.setExpanding(False)
        layout.addWidget(self.assistant_mode)
        messages = QWidget()
        messages.setObjectName('assistantMessages')
        message_layout = QVBoxLayout(messages)
        message_layout.setContentsMargins(0, 12, 0, 0)
        self.assistant_info = QFrame()
        self.assistant_info.setObjectName('messageCard')
        notice_layout = QVBoxLayout(self.assistant_info)
        notice_layout.setContentsMargins(16, 16, 16, 16)
        notice_layout.addWidget(self.label('从你的创作想法开始', 'subheading'))
        notice_layout.addWidget(self.label('先写下人物、冲突，或你想修改的片段。你的正文和创作备忘会保存在当前项目。', 'muted'))
        message_layout.addWidget(self.assistant_info)
        self.connection_notice = self.label('配置一个文字模型后即可生成；手动写作不受影响。', 'muted')
        message_layout.addWidget(self.connection_notice)
        self.chat_output = QTextBrowser()
        self.chat_output.setObjectName('chatOutput')
        self.chat_output.setPlaceholderText('生成结果会显示在这里，审核后再采纳到正文。')
        message_layout.addWidget(self.chat_output, 1)
        assistant_actions = QHBoxLayout()
        assistant_actions.addWidget(self.button('上下文', self.view_context))
        assistant_actions.addWidget(self.button('历史 / 用量', self.task_history))
        self.review_candidate_button = self.button('查看修改', self.review_candidate)
        self.review_candidate_button.setEnabled(False)
        extra = QToolButton()
        extra.setText('更多')
        extra.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(extra)
        for title, callback in [('新会话', self.new_chat), ('固定资料', self.pin_documents),
            ('引用到正文（本地）', self.quote_to_document), ('继续未完成（可能计费）', self.continue_unfinished),
            ('再生成（新请求）', self.regenerate_task)]:
            action = menu.addAction(title)
            action.triggered.connect(lambda checked=False, fn=callback: self.run(fn))
        extra.setMenu(menu)
        assistant_actions.addWidget(extra)
        message_layout.addLayout(assistant_actions)
        message_layout.addWidget(self.review_candidate_button)
        layout.addWidget(messages, 1)
        self.context_label = self.label('当前项目：未选择', 'muted')
        layout.addWidget(self.context_label)
        composer = QFrame()
        composer.setObjectName('composer')
        input_layout = QVBoxLayout(composer)
        input_layout.setContentsMargins(12, 8, 12, 10)
        self.assistant_input = WritingEditor()
        self.assistant_input.setObjectName('assistantInput')
        self.assistant_input.setPlaceholderText('描述你的想法，或选中内容让我修改…')
        self.assistant_input.setMinimumHeight(90)
        self.assistant_input.setMaximumHeight(130)
        self.assistant_input.textChanged.connect(self.save_assistant_note)
        input_layout.addWidget(self.assistant_input)
        self.model_combo = QComboBox()
        self.model_combo.addItems(['DeepSeek', 'Codex CLI', '火山方舟', '千问'])
        self.model_combo.setEnabled(False)
        self.model_combo.setToolTip('连接 / 实际模型 ID；能力状态分别记录')
        self.model_combo.setMinimumWidth(100)
        self.model_combo.currentIndexChanged.connect(self.model_changed)
        row = QHBoxLayout()
        row.addWidget(self.model_combo, 1)
        self.budget_combo = QComboBox()
        self.budget_combo.addItems(['节省', '均衡', '深入'])
        self.budget_combo.setMaximumWidth(85)
        row.addWidget(self.budget_combo)
        send = QPushButton()
        send.setIcon(icon('send', THEMES[self.theme]['button']))
        send.setObjectName('primary')
        send.setProperty('icon_name', 'send')
        send.setFixedSize(40, 40)
        send.setEnabled(False)
        send.setToolTip('发送本次任务 · Ctrl+Enter · 可能计费')
        send.clicked.connect(lambda: self.run(self.start_text_task))
        self.send_button = send
        row.addWidget(send)
        self.stop_button = self.button('停止', self.stop_text_task)
        self.stop_button.hide()
        row.addWidget(self.stop_button)
        input_layout.addLayout(row)
        self.reasoning_combo = QComboBox()
        self.reasoning_combo.addItem('推理：模型默认', None)
        self.reasoning_combo.setEnabled(False)
        self.reasoning_combo.hide()
        input_layout.addWidget(self.reasoning_combo)
        self.configure_model_button = self.button('配置文字模型', self.settings_dialog)
        input_layout.addWidget(self.configure_model_button)
        layout.addWidget(composer)
        return panel

    def build_rules(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self.label('资料与规则', 'heading'))
        layout.addWidget(self.label('选择赛道后，核心规则会自动进入AI创作请求。这里可以查看和管理规则。','muted'))
        operations = QHBoxLayout()
        for label, function in [('新增规则', lambda: edit_rule(self)), ('编辑选中', self.edit_selected_rule),
            ('导入规则包', self.import_rule_package), ('恢复内置', self.restore_rule_base), ('选择项目规则', self.choose_project_rules)]:
            operations.addWidget(self.button(label, function))
        layout.addLayout(operations)
        splitter = QSplitter()
        self.rule_list = QListWidget()
        self.rule_body = QTextBrowser()
        splitter.addWidget(self.rule_list)
        splitter.addWidget(self.rule_body)
        splitter.setSizes([240, 600])
        self.rule_data = ProjectRules(None, self.resources).base()
        for rule in self.rule_data:
            self.rule_list.addItem(rule['rule_id'] + ' ' + rule['title'])
        self.rule_list.currentRowChanged.connect(self.show_rule)
        layout.addWidget(splitter, 1)
        self.rule_list.setCurrentRow(0)
        return page

    def show_rule(self, index):
        if index >= 0:
            rule = self.rule_data[index]
            enabled = '已启用' if rule.get('enabled', True) else '已停用'
            self.rule_body.setPlainText(rule['title']+'\n'+enabled+'\n\n'+rule['body'])

    def build_cases(self):
        try:
            return CasePage(self)
        except (ValueError, OSError, __import__('sqlite3').Error) as exc:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.addWidget(self.label('案例库未能读取；手动写作与项目保存仍可使用。', 'subheading'))
            layout.addWidget(self.label(str(exc), 'muted'))
            layout.addStretch()
            return page

    def filter_cases(self):
        self.cases_page.refresh()

    def show_case(self, index):
        self.cases_page.show_record(index)

    def apply_theme(self):
        if self.theme not in THEMES:
            self.theme = '雾白浅色'
        self.setStyleSheet(stylesheet(self.theme, self.options.get('ui_font_size', 14), self.options.get('editor_font_size', 18)))
        for index, name in enumerate(NAV_ICONS):
            self.navigation.item(index).setIcon(icon(name, THEMES[self.theme]['text']))
            self.navigation.item(index).setSizeHint(QSize(180, 52))
        self.navigation.setIconSize(QSize(22, 22))
        for button in self.findChildren(QPushButton):
            name = button.property('icon_name')
            if name:
                color = THEMES[self.theme]['button'] if button.objectName() == 'primary' else THEMES[self.theme]['text']
                button.setIcon(icon(name, color))
        if hasattr(self, 'workspace_label'):
            self.workspace_label.setText({'石墨深色': '石墨工作室', '雾白浅色': '雾白工作室', '暖纸写作': '暖纸工作室'}[self.theme])
        font = QFont('Microsoft YaHei')
        font.setPixelSize(self.options.get('editor_font_size', 18))
        self.editor.setFont(font)
        option = self.editor.document().defaultTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.editor.document().setDefaultTextOption(option)

    def change_theme(self, value):
        self.theme = value
        self.apply_theme()
        self.run(self.save_preferences)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'assistant'):
            if self.width() < 1120:
                self.assistant.hide()
                self.assistant_toggle.setText('打开助手')
                self.sidebar.setMaximumWidth(180)
            else:
                self.sidebar.setMaximumWidth(250)

    def toggle_navigation(self):
        self.sidebar.setVisible(not self.sidebar.isVisible())

    def toggle_assistant(self):
        if self.width() < 1120 and not self.assistant.isVisible():
            dialog = QDialog(self)
            dialog.setWindowTitle('AI 创作助手')
            dialog.resize(460, 610)
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self.assistant)
            self.assistant.show()
            from PySide6.QtGui import QShortcut
            shortcut = QShortcut(QKeySequence('Ctrl+Return'), dialog)
            shortcut.activated.connect(lambda: self.run(self.start_text_task))
            try:
                dialog.exec()
            finally:
                self.outer.insertWidget(2, self.assistant)
                self.assistant.hide()
            return
        self.assistant.setVisible(not self.assistant.isVisible())
        self.assistant_toggle.setText('收起助手' if self.assistant.isVisible() else '打开助手')

    def navigate(self, row):
        if row < 0:
            return
        if row == 0:
            if not self.save():
                return
            self.refresh_projects()
            self.pages.setCurrentWidget(self.home)
            QTimer.singleShot(0,lambda:self.home.scroll.verticalScrollBar().setValue(0))
        elif row == 6:
            self.pages.setCurrentWidget(self.cases_page)
        elif row == 8:
            self.pages.setCurrentWidget(self.rules_page)
        elif row == 9:
            self.settings_dialog()
        elif row in {1,2,3}:
            if not self.save():
                return
            self.creator_page.set_channel(row)
            self.pages.setCurrentWidget(self.creator_page)
        else:
            self.mode_label.setText(NAVIGATION[row])
            self.pages.setCurrentWidget(self.writing)
            if row in {4, 5}:
                self.document_note.setText('来源稿只读保留；可从来源建新稿，并在“创作阶段”选择拆解或改编映射。')
            elif row == 7:
                self.document_note.setText('可新建研究笔记、导入本地资料；“更多”可读取你指定的公开网址。')

    def refresh_projects(self, *_):
        if not hasattr(self, 'project_list'):
            return
        previous = self.project_list.currentItem()
        previous_root = previous.data(Qt.ItemDataRole.UserRole) if previous else None
        preferred_root=getattr(self,'_preferred_project_root',None) or previous_root or (str(self.store.root) if self.store else None)
        self.project_list.clear()
        query = self.project_search.text().casefold()
        status = ['active', 'archived', 'trash'][self.project_filter.currentIndex()]
        for record in self.workspace.projects(status):
            if query not in record.get('search_text',record['name']+record['kind']).casefold():
                continue
            item = QListWidgetItem(f"{record['name']}\n{record['kind']} · {record['updated'][:19].replace('T', ' ')}")
            item.setData(Qt.ItemDataRole.UserRole, record['root'])
            item.setToolTip(record['root'])
            self.project_list.addItem(item)
            if record['root'] == preferred_root:
                self.project_list.setCurrentItem(item)
        if self.project_list.count() == 0:
            self.home_cover.setText('没有项目。点击“新建项目”开始本地写作。')
        self.home.render_projects()

    def toggle_project_view(self):
        self.home.toggle_view()

    def project_selected(self, current, _):
        if current is None:
            return
        self._preferred_project_root=current.data(Qt.ItemDataRole.UserRole)
        try:
            store = self.workspace.open(Path(current.data(Qt.ItemDataRole.UserRole)))
            metadata = store.metadata()
            cid = store.setting('active_cover')
            versions = store.covers()
            selected = next((v['spec'] for v in versions if v['id'] == cid), None)
            spec = selected or default_cover(metadata['name'], metadata['kind'])
            image = render_cover(spec, store.root, width=488)
            self.home_cover.setPixmap(QPixmap.fromImage(image).scaled(self.home_cover.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.home.show_featured(store)
        except Exception as exc:
            self.home_cover.setText('封面暂不可用：' + str(exc))

    def selected_project(self):
        item = self.project_list.currentItem()
        if item:
            return self.workspace.open(Path(item.data(Qt.ItemDataRole.UserRole)))
        if self.store:
            return self.store
        raise ValueError('请先选择项目')

    def new_project(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('新建项目 · 本地操作')
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        name = QLineEdit()
        name.setObjectName('newProjectName')
        kind = QComboBox()
        kind.addItems(['小说', '剧本', '文案'])
        form.addRow('项目名称', name)
        form.addRow('内容形式', kind)
        directory=QLineEdit(str(self.workspace.projects_root))
        directory.setObjectName('newProjectDirectory')
        directory.setReadOnly(True)
        directory_row=QHBoxLayout()
        directory_row.addWidget(directory,1)
        def select_directory():
            chosen=QFileDialog.getExistingDirectory(dialog,'选择项目存放目录',directory.text())
            if chosen:
                directory.setText(chosen)
        directory_row.addWidget(self.button('选择目录',select_directory))
        form.addRow('存放目录',directory_row)
        layout.addLayout(form)
        layout.addWidget(self.label('会在所选位置创建独立项目文件夹；目录变更只影响本次新建项目。','muted'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        name.textChanged.connect(lambda value: buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(value.strip())))
        def accept_project():
            matching=[p for p in self.workspace.projects('all') if p['name'].casefold()==name.text().strip().casefold()]
            if matching and QMessageBox.question(dialog,'同名项目',
                '已有同名项目。仍创建一个独立目录和新 ID 的项目？') != QMessageBox.StandardButton.Yes:
                return
            dialog.accept()
        buttons.accepted.connect(accept_project)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if not self.save():
                return
            store = self.workspace.create(name.text(), kind.currentText(),parent=Path(directory.text()))
            self.open_project(store.root)
            self.refresh_projects()

    def open_folder(self):
        path = QFileDialog.getExistingDirectory(self, '打开含 project.sqlite 的项目目录', str(self.workspace.projects_root))
        if path:
            self.open_project(Path(path))

    def continue_project(self):
        self.open_project(self.selected_project().root)

    def open_project(self, root: Path, writing=True):
        if not self.save():
            return False
        store = self.workspace.open(root)
        self.workspace.register(store)
        self.store = store
        self.document_id, self.base_revision = None, None
        self.loading = True
        self.editor.clear()
        self.dirty = False
        self.loading = False
        metadata = store.metadata()
        self.context_label.setText('当前项目：' + metadata['name'])
        self.project_status.setText(metadata['name'])
        self.options['last_project'] = str(root)
        self.save_preferences()
        self.loading = True
        self.assistant_input.setPlainText(store.setting('assistant_note', ''))
        self.loading = False
        self.last_task = None
        self.chat_output.clear()
        self.review_candidate_button.setEnabled(False)
        recovered = TaskService(store, self.resources, self.connections).recover_unfinished()
        if recovered:
            self.connection_notice.setText(f'检测到 {len(recovered)} 个上次中断任务，部分结果已保留；在历史中查看，未自动重发。')
        self.refresh_documents(store.setting('last_document'))
        self.view_combo.setCurrentIndex(store.setting('last_view',0))
        self.refresh_rules()
        self.home.select_project(str(store.root))
        self._preferred_project_root=str(store.root)
        if writing:
            kind = metadata['kind']
            self.navigation.setCurrentRow({'小说': 1, '剧本': 2, '文案': 3}[kind])
            self.pages.setCurrentWidget(self.creator_page if store.setting('creator_flow')=='ai_first' else self.writing)
        return True

    def refresh_documents(self, selected=None):
        if not self.store:
            return
        self.loading = True
        self.documents.clear()
        for document in self.store.documents():
            title = ('来源 · ' if document['kind'] == 'reference' else '') + document['title']
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, document['id'])
            # Flat list: moving rows never changes ownership or IDs.
            self.documents.addItem(item)
            if document['id'] == selected:
                self.documents.setCurrentItem(item)
        if not self.documents.currentItem() and self.documents.count():
            self.documents.setCurrentRow(0)
        self.loading = False
        self.choose_document(self.documents.currentItem(), None)

    def choose_document(self, current, previous):
        if self.loading or not self.store:
            return
        if not self.save():
            if previous:
                self.documents.blockSignals(True)
                self.documents.setCurrentItem(previous)
                self.documents.blockSignals(False)
            return
        self.loading = True
        try:
            self.document_id = current.data(Qt.ItemDataRole.UserRole) if current else None
            if self.document_id:
                document = self.store.document(self.document_id)
                self.base_revision = document['head']
                self.title.setText(document['title'])
                self.editor.setPlainText(document['text'])
                self.editor.setReadOnly(document['kind'] == 'reference')
                self.title.setReadOnly(document['kind'] == 'reference')
                self.editor.setEnabled(True)
                status_name = {'draft': '草稿', 'confirmed': '已确认'}.get(document['status'], document['status'])
                self.document_note.setText('来源稿 · 只读保存' if document['kind'] == 'reference' else f"当前稿：{status_name} · 版本 {self.base_revision[:8]}")
                cursor = self.editor.textCursor()
                cursor.setPosition(min(self.store.setting('cursor:' + self.document_id, 0), self.editor.document().characterCount() - 1))
                self.editor.setTextCursor(cursor)
                self.store.set_setting('last_document', self.document_id)
            else:
                self.editor.clear()
                self.title.clear()
                self.editor.setEnabled(False)
            self.dirty = False
            self.update_count()
            self.work_views.refresh()
        finally:
            self.loading = False

    def text_changed(self):
        self.update_count()
        if self.loading or not self.store or not self.document_id:
            return
        self.dirty = True
        self.status.setText('尚未保存 · 自动保存准备中')
        if not self.editor.composing:
            self.autosave.start()

    def composition_changed(self, active):
        if active:
            self.autosave.stop()
        elif self.dirty:
            self.autosave.start()

    def update_count(self):
        if hasattr(self, 'word_count'):
            self.word_count.setText(f"{sum(not ch.isspace() for ch in self.editor.toPlainText())} 字")

    def save(self, show_error=True):
        if self.editor.composing:
            return False
        if not self.store or not self.document_id:
            return True
        self.autosave.stop()
        try:
            if self.dirty:
                self.base_revision = self.store.save_document(self.document_id, self.base_revision, self.editor.toPlainText())
                self.dirty = False
            self.store.set_setting('cursor:' + self.document_id, self.editor.textCursor().position())
            self.status.setText('已保存到本地')
            return True
        except Exception as exc:
            self.status.setText('尚未保存到磁盘 · ' + str(exc))
            if show_error:
                box = QMessageBox(self)
                box.setWindowTitle('保存未完成')
                box.setText(str(exc) + '\n内存草稿已保留；可以撤销修改，或另存当前草稿。')
                separate = box.addButton('另存草稿', QMessageBox.ButtonRole.ActionRole)
                box.addButton('保留并返回', QMessageBox.ButtonRole.RejectRole)
                box.exec()
                if box.clickedButton() == separate:
                    path, _ = QFileDialog.getSaveFileName(self, '另存内存草稿', '', '文本 (*.txt)')
                    if path:
                        from app.core.files import atomic_write
                        atomic_write(Path(path), self.editor.toPlainText().encode('utf-8'))
            return False

    def require_document(self):
        if not self.store or not self.document_id:
            raise ValueError('请先创建或打开项目，并选择文档')
        return self.store.document(self.document_id)

    def rename_document(self):
        if self.loading or not self.store or not self.document_id:
            return
        document = self.require_document()
        if document['kind'] == 'reference':
            return
        self.store.rename_document(self.document_id, self.title.text())
        item = self.documents.currentItem()
        if item:
            item.setText(self.title.text().strip())

    def new_document(self):
        if not self.store:
            raise ValueError('请先新建项目')
        title, ok = QInputDialog.getText(self, '新增文档', '章 / 场 / 卡片标题')
        if ok and self.save():
            kind, confirmed = QInputDialog.getItem(self, '新文档稿型', '同一项目可以保留多个稿型，切换不转换旧文稿', ['小说','剧本','文案'], editable=False)
            if not confirmed:
                return
            did = self.store.add_document(title, kind=kind)
            self.refresh_documents(did)

    def reorder_documents(self):
        if self.loading or not self.store:
            return
        self.store.reorder([self.documents.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.documents.count())])

    def trash_document(self):
        self.require_document()
        if self.active_task and self.active_task['snapshot']['target_id'] == self.document_id and self.active_task['service'].store.root == self.store.root:
            raise ValueError('该文档有正在运行的任务，请先使用助手“停止”并等待任务保存')
        if QMessageBox.question(self, '移入回收区', '当前文档将移入项目回收区，可以恢复。') == QMessageBox.StandardButton.Yes and self.save():
            self.store.trash_document(self.document_id)
            self.document_id = None
            self.refresh_documents()

    def restore_document(self):
        if not self.store:
            raise ValueError('请先打开项目')
        documents = self.store.documents(deleted=True)
        if not documents:
            QMessageBox.information(self, '项目回收区', '回收区为空')
            return
        labels = [d['title'] + ' · ' + d['id'][:8] for d in documents]
        chosen, ok = QInputDialog.getItem(self, '恢复文档', '文档', labels, editable=False)
        if ok and self.save():
            did = documents[labels.index(chosen)]['id']
            self.store.trash_document(did, restore=True)
            self.refresh_documents(did)

    def import_file(self):
        if not self.store:
            self.new_project()
            if not self.store:
                return
        path, _ = QFileDialog.getOpenFileName(self, '导入作品 / 来源', '', '文本资料 (*.md *.txt *.json *.srt *.vtt)')
        if not path:
            return
        preview = import_preview(Path(path))
        dialog = QDialog(self)
        dialog.setWindowTitle('导入预览 · 不执行文件中的指令')
        dialog.resize(740, 550)
        layout = QVBoxLayout(dialog)
        layout.addWidget(self.label(f"编码：{preview['encoding']} · {len(preview['text'])} 字符\n{preview['note']}", 'muted'))
        body = QTextEdit()
        body.setPlainText(preview['text'])
        body.setReadOnly(True)
        layout.addWidget(body, 1)
        kind = QComboBox()
        kind.addItems(['可编辑作品', '只读参考来源'])
        if self.navigation.currentRow() in {4, 5}:
            kind.setCurrentIndex(1)
        layout.addWidget(kind)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted and self.save():
            did = self.store.add_document(preview['title'], preview['text'], kind='reference' if kind.currentIndex() == 1 else self.store.metadata()['kind'])
            self.store.set_setting('import:' + did, dict(source_name=Path(path).name, encoding=preview['encoding'], hash=preview['hash']))
            self.refresh_documents(did)
            self.pages.setCurrentWidget(self.writing)
            self.status.setText('已导入并保留原文')

    def export(self, selection=False):
        self.require_document()
        if not self.save():
            return
        document = self.store.document(self.document_id)
        if document['status'] != 'confirmed' and QMessageBox.question(self, '导出草稿', '当前文档尚未定稿，仍要导出草稿吗？') != QMessageBox.StandardButton.Yes:
            return
        text = None
        if selection:
            text = self.editor.textCursor().selectedText().replace('\u2029', '\n')
            if not text:
                raise ValueError('请先选择要导出的文字')
        path, _ = QFileDialog.getSaveFileName(self, '导出作品', str(self.store.root / 'exports' / '作品.md'), 'Markdown (*.md);;文本 (*.txt);;JSON (*.json)')
        if path:
            export_document(self.store, self.document_id, Path(path), selected_text=text)
            self.status.setText('已导出：' + path)

    def confirm_draft(self):
        self.require_document()
        if self.save():
            self.base_revision = self.store.save_document(self.document_id, self.base_revision, self.editor.toPlainText(), '用户确认定稿', status='confirmed')
            self.document_note.setText('当前稿：已确认 · 继续编辑后重新成为草稿')

    def open_cover(self):
        if not self.store:
            raise ValueError('请先打开项目')
        CoverDialog(self.store, self).exec()
        self.project_selected(self.project_list.currentItem(), None)

    def versions(self):
        self.require_document()
        if not self.save():
            return
        history = self.store.revisions(self.document_id)
        dialog = QDialog(self)
        dialog.setWindowTitle('不可变版本 · 恢复会创建新版本')
        dialog.resize(820, 560)
        layout = QVBoxLayout(dialog)
        versions = QComboBox()
        versions.addItems([f"{r['created']} · {r['reason']} · {r['id'][:8]}" for r in history])
        layout.addWidget(versions)
        preview = QTextEdit()
        preview.setReadOnly(True)
        layout.addWidget(preview, 1)
        def changed(index):
            current = self.editor.toPlainText().splitlines()
            selected = history[index]['text'].splitlines()
            diff = '\n'.join(difflib.unified_diff(current, selected, fromfile='当前版本', tofile='选中版本', lineterm=''))
            preview.setPlainText(diff or '与当前版本内容相同')
        versions.currentIndexChanged.connect(changed)
        changed(0)
        def restore():
            self.base_revision = self.store.restore_revision(self.document_id, history[versions.currentIndex()]['id'], self.base_revision)
            self.refresh_documents(self.document_id)
            dialog.accept()
        layout.addWidget(self.button('恢复选中版本', restore))
        dialog.exec()

    def find_dialog(self, replace=False):
        document = self.require_document()
        dialog = QDialog(self)
        dialog.setWindowTitle('当前文档 · 查找 / 替换')
        layout = QVBoxLayout(dialog)
        search = QLineEdit()
        search.setPlaceholderText('查找文字（逐字匹配）')
        substitute = QLineEdit()
        substitute.setPlaceholderText('替换为')
        layout.addWidget(search)
        if replace and document['kind'] != 'reference':
            layout.addWidget(substitute)
        status = self.label('范围：当前文档；替换先预览数量，锁定段落跳过')
        layout.addWidget(status)
        def find_next():
            if not search.text():
                return
            if not self.editor.find(search.text()):
                cursor = self.editor.textCursor()
                cursor.setPosition(0)
                self.editor.setTextCursor(cursor)
                if not self.editor.find(search.text()):
                    status.setText('没有匹配文字')
        layout.addWidget(self.button('查找下一个', find_next))
        def replace_all():
            needle = search.text()
            if not needle:
                raise ValueError('查找文字不能为空')
            current = self.editor.toPlainText()
            locked = self.store.locks(self.document_id)
            # Conservatively skip each complete paragraph containing any locked fragment.
            lines = current.split('\n')
            changed_lines, count, skipped = [], 0, 0
            for line in lines:
                occurrences = line.count(needle)
                if any(lock['text'] in line or line in lock['text'] for lock in locked if line):
                    changed_lines.append(line)
                    skipped += occurrences
                else:
                    changed_lines.append(line.replace(needle, substitute.text()))
                    count += occurrences
            status.setText(f'可替换 {count} 处；跳过锁定段落 {skipped} 处')
            if count and QMessageBox.question(dialog, '确认当前文档替换', status.text()) == QMessageBox.StandardButton.Yes:
                cursor = self.editor.textCursor()
                cursor.beginEditBlock()
                cursor.select(QTextCursor.SelectionType.Document)
                cursor.insertText('\n'.join(changed_lines))
                cursor.endEditBlock()
        if replace and document['kind'] != 'reference':
            layout.addWidget(self.button('预览并替换全部', replace_all))
        dialog.exec()

    def lock_selection(self):
        self.require_document()
        if not self.save():
            return
        cursor = self.editor.textCursor()
        text = cursor.selectedText().replace('\u2029', '\n')
        # Qt cursor positions are UTF-16 units; use Python text length for persisted offsets.
        start = len(self.editor.toPlainText().encode('utf-16-le')[:cursor.selectionStart() * 2].decode('utf-16-le'))
        self.store.lock(self.document_id, text, start)
        self.status.setText('选区已锁定；修改它会阻止保存')

    def unlock(self):
        self.require_document()
        if QMessageBox.question(self, '明确解锁', '解除当前文档全部文字锁？正文不会改变。') == QMessageBox.StandardButton.Yes:
            self.store.unlock(self.document_id)
            self.status.setText('已解除当前文档文字锁')

    def annotation(self):
        self.require_document()
        if not self.save():
            return
        block_index = self.editor.textCursor().blockNumber()
        blocks = self.store.document(self.document_id)['blocks']
        text, ok = QInputDialog.getMultiLineText(self, '添加段落批注', '批注内容')
        if ok and text.strip():
            self.store.annotate(self.document_id, blocks[block_index]['block_id'], text)
            self.status.setText('批注已关联稳定段落 ID')

    def show_annotations(self):
        document = self.require_document()
        notes = self.store.annotations(self.document_id)
        blocks = {b['block_id']: b for b in document['blocks']}
        lines = []
        for note in notes:
            block = blocks.get(note['block_id'])
            lines.append(('原文：' + block['text'] if block else '目标段落已删除，批注保留') + '\n批注：' + note['text'])
        self.text_dialog('当前文档批注', '\n\n'.join(lines) or '尚无批注')

    def validate(self):
        document = self.require_document()
        ids = [b['block_id'] for b in document['blocks']]
        problems = []
        if len(ids) != len(set(ids)):
            problems.append('段落 ID 重复')
        if not self.editor.toPlainText().strip():
            problems.append('正文为空')
        for lock in self.store.locks(self.document_id):
            if lock['text'] not in self.editor.toPlainText():
                problems.append('锁定文字发生变化')
        self.text_dialog('本地格式检查', '\n'.join(problems) if problems else '未发现段落 ID、空正文或文字锁问题。\n本检查不代表剧情质量或 TT 导入验收。')

    def branch(self):
        document = self.require_document()
        if not self.save():
            return
        title, ok = QInputDialog.getText(self, '从来源建新稿', '新稿标题', text=document['title'] + ' · 新稿')
        if ok:
            did = self.store.add_document(title, '', kind=self.store.metadata()['kind'], source_id=self.document_id)
            self.store.set_setting('source_revision:' + did, document['head'])
            self.refresh_documents(did)

    def compare_source(self):
        document = self.require_document()
        if not document.get('source_id'):
            raise ValueError('当前文档尚未关联来源；从来源文档选择“从来源建新稿”')
        source = self.store.document(document['source_id'])
        source_revision = self.store.setting('source_revision:' + document['id'])
        if source_revision:
            with self.store.connection() as con:
                frozen = con.execute('SELECT text FROM revisions WHERE id=? AND document_id=?', (source_revision,source['id'])).fetchone()
            if frozen:
                source = dict(source, text=frozen['text'], title=source['title'] + (' · 原来源版本（当前来源已更新）' if source['head']!=source_revision else ' · 原来源版本'))
        dialog = QDialog(self)
        dialog.setWindowTitle('来源与新稿 · 独立滚动')
        dialog.resize(960, 600)
        layout = QHBoxLayout(dialog)
        for title, text in [(source['title'], source['text']), (document['title'], self.editor.toPlainText())]:
            column = QVBoxLayout()
            column.addWidget(self.label(title, 'subheading'))
            editor = QTextEdit()
            editor.setReadOnly(True)
            editor.setPlainText(text)
            column.addWidget(editor)
            layout.addLayout(column)
        dialog.exec()

    def text_dialog(self, title, text):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(700, 500)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setPlainText(text)
        layout.addWidget(browser)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def toggle_directory(self):
        self.directory.setVisible(not self.directory.isVisible())

    def enter_focus(self):
        self._focus_visibility = (self.sidebar.isVisible(), self.directory.isVisible(), self.assistant.isVisible())
        self.focus_mode = True
        for widget in (self.sidebar, self.directory, self.assistant):
            widget.hide()
        self.status.setText('专注写作 · Esc 恢复原布局')

    def exit_focus(self):
        if self.focus_mode:
            self.focus_mode = False
            for widget, visible in zip((self.sidebar, self.directory, self.assistant), self._focus_visibility):
                widget.setVisible(visible)
            if self.view_combo.currentIndex()==4:
                self.view_combo.blockSignals(True)
                self.view_combo.setCurrentIndex(0)
                self.view_combo.blockSignals(False)

    def save_assistant_note(self):
        if not self.loading and self.store:
            self.run(lambda: self.store.set_setting('assistant_note', self.assistant_input.toPlainText()))

    def rename_project(self):
        store = self.selected_project()
        name, ok = QInputDialog.getText(self, '重命名项目', '项目名称', text=store.metadata()['name'])
        if ok:
            store.update_project(name=name)
            if self.store and store.root == self.store.root:
                self.context_label.setText('当前项目：' + name)
                self.project_status.setText(name)
            self.refresh_projects()

    def copy_project(self):
        store = self.selected_project()
        dialog=QDialog(self)
        dialog.setWindowTitle('复制为独立项目')
        layout=QVBoxLayout(dialog)
        layout.addWidget(self.label('正文、版本和创作设定会复制；模型会话与凭据不会复制。'))
        assets=QCheckBox('复制已登记素材（图片、封面底图）')
        assets.setObjectName('copyProjectAssets')
        assets.setChecked(True)
        layout.addWidget(assets)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec()!=QDialog.DialogCode.Accepted:
            return
        if self.store and store.root == self.store.root and not self.save():
            return
        self.workspace.copy(store,include_assets=assets.isChecked())
        self.refresh_projects()
        self.status.setText('已复制为独立项目；未携带应用设置或凭据')

    def archive_project(self):
        store = self.selected_project()
        store.update_project(status='active' if store.metadata()['status'] == 'archived' else 'archived')
        self.refresh_projects()

    def trash_project(self):
        store = self.selected_project()
        if self.active_task and self.active_task['service'].store.root == store.root:
            raise ValueError('该项目有正在运行的任务，请先停止任务')
        if self.active_image_task and self.active_image_task['service'].store.root == store.root:
            raise ValueError('该项目有正在运行的图片任务，请先停止本地等待或等待完成')
        if self.backup_operation and getattr(self.backup_operation,'project_root',None)==store.root and not self.backup_operation.completed.is_set():
            raise ValueError('该项目正在进行一致性备份，请等待完成后再回收')
        from app.core.tasks import process_alive
        from app.core.task_runtime import execution_owner,owner_alive
        with store.connection() as con:
            pending=[dict(row) for row in con.execute("SELECT t.id,t.snapshot FROM tasks t LEFT JOIN task_leases l ON l.task_id=t.id WHERE t.state IN ('ready','waiting','generating','submitting','accepted','downloading') OR l.active=1")]
        if any(owner_alive(json.loads(task['snapshot']),execution_owner(store,task['id']),fallback=process_alive) for task in pending):
            raise ValueError('该项目仍有未结束的任务记录，请先在所属窗口处理任务后再回收')
        TaskService(store,self.resources,self.connections).recover_unfinished()
        from app.core.image_service import ImageService
        ImageService(store,self.resources,self.image_connections).recover()
        with store.connection() as con:
            uncertain=con.execute("SELECT COUNT(*) FROM tasks WHERE state='uncertain'").fetchone()[0]
        metadata = store.metadata()
        note=f'仍有 {uncertain} 条结果待确认任务。本次只改变本地分类，任务信息会保留；不代表远端已停止。\n' if uncertain else ''
        if QMessageBox.question(self, '项目回收区', note+f"确认处理项目“{metadata['name']}”？不会永久删除文件。") != QMessageBox.StandardButton.Yes:
            return
        if self.store and store.root == self.store.root and not self.save():
            return
        store.update_project(status='active' if metadata['status'] == 'trash' else 'trash')
        self.refresh_projects()

    def backup_project(self):
        store = self.selected_project()
        if self.store and store.root == self.store.root and not self.save():
            return
        path, _ = QFileDialog.getSaveFileName(self, '一致性备份项目', str(store.root / 'backups' / '项目备份.ttbackup'), '项目备份 (*.ttbackup)')
        if path:
            self.workspace.backup(store, Path(path))
            self.status.setText('备份已完成：' + path)

    def restore_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, '恢复为新项目', '', '项目备份 (*.ttbackup)')
        if path:
            restored = self.workspace.restore(Path(path))
            self.open_project(restored.root)
            self.refresh_projects()

    def settings_dialog(self):
        SettingsDialog(self).exec()

    def configure_backup_timer(self):
        config=self.options.get('auto_backup',{})
        self.backup_timer.stop()
        if config.get('enabled'):
            interval=config.get('interval_minutes',10)
            if isinstance(interval,int) and 1<=interval<=120:
                self.backup_timer.start(interval*60000)

    def start_automatic_backup(self,force=False):
        if not self.store or self.backup_operation or self.editor.composing:
            return
        config=self.options.get('auto_backup',{})
        if not force and not config.get('enabled'):
            return
        if not self.save():
            self.status.setText('内存稿未落盘，自动备份未声称保存该草稿')
            return
        from app.core.maintenance import automatic_backup
        from app.ui.model_settings import Operation
        store=self.store
        operation=Operation(lambda:str(automatic_backup(self.workspace,store,config.get('keep',5))))
        operation.project_root=store.root
        self.backup_operation=operation
        self.backup_poll.start()
        QThreadPool.globalInstance().start(operation)

    def poll_backup_completion(self):
        operation=self.backup_operation
        if operation and operation.completed.is_set():
            self.backup_finished(operation.result,operation.error)

    def backup_finished(self,path,error):
        self.backup_poll.stop()
        self.backup_operation=None
        self.status.setText('自动备份未完成：'+error if error else '一致性备份已完成（原项目）：'+str(path))
        if self.close_after_backup:
            self.close_after_backup=False
            QTimer.singleShot(0,self.close)

    def export_diagnostics(self):
        from app.core.maintenance import diagnostics
        result=diagnostics(self)
        dialog=QDialog(self)
        dialog.setWindowTitle('脱敏诊断预览 · 不含KEY或作品全文')
        dialog.resize(760,560)
        layout=QVBoxLayout(dialog)
        preview=QTextBrowser()
        preview.setPlainText(__import__('json').dumps(result,ensure_ascii=False,indent=2))
        layout.addWidget(preview)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('选择文件保存诊断')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            path,_=QFileDialog.getSaveFileName(self,'保存脱敏诊断','','JSON (*.json)')
            if path:
                write_json(Path(path),result)

    def refresh_models(self):
        selected = self.model_combo.currentData() or self.options.get('default_connection')
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        enabled = [connection for connection in self.connections.all() if connection.enabled and connection.model.strip()]
        for connection in enabled:
            self.model_combo.addItem(connection.name + ' / ' + connection.model, connection.id)
        if not enabled:
            self.model_combo.addItem('配置文字模型', None)
        index = self.model_combo.findData(selected)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)
        self.model_combo.setEnabled(bool(enabled))
        self.send_button.setEnabled(bool(enabled) and self.active_task is None)
        self.configure_model_button.setVisible(not enabled)
        self.model_combo.blockSignals(False)
        self.model_changed()

    def model_changed(self, *_):
        connection_id = self.model_combo.currentData()
        self.reasoning_combo.clear()
        self.reasoning_combo.addItem('推理：模型默认', None)
        if connection_id:
            connection = self.connections.get(connection_id)
            for level in connection.reasoning_levels:
                self.reasoning_combo.addItem(level, level)
            self.reasoning_combo.setEnabled(bool(connection.reasoning_levels))
            self.reasoning_combo.setVisible(bool(connection.reasoning_levels))
            self.connection_notice.setText('当前模型：'+connection.name+'；点击生成后才提交请求。')
        else:
            self.reasoning_combo.setEnabled(False)
            self.reasoning_combo.hide()
            self.connection_notice.setText('配置一个文字模型后即可生成；手动写作不受影响。')
        if self.active_task:
            self.status.setText('模型选择将在下次任务生效；正在运行的任务保持原快照')

    def task_service(self):
        if not self.store:
            raise ValueError('请先创建或打开项目，任务和用量保存在所属项目')
        return TaskService(self.store, self.resources, self.connections)

    def start_text_task(self, connection_override=None, test_request=False, provider=None, stage_override=None, instruction_override=None, allow_reuse=False, variant_id=None, continuation_task_id=None, planning_ids=()):
        self.require_document()
        if self.editor.composing or self.assistant_input.composing:
            return
        if self.active_task:
            raise ValueError('当前任务尚未结束，请等待或停止；没有重复提交')
        if not self.save():
            return
        connection_id = self.model_combo.currentData()
        connection = connection_override or (self.connections.get(connection_id) if connection_id else None)
        if not connection:
            self.settings_dialog()
            return
        if connection.provider != 'codex' and not self.connections.secret_snapshot(connection):
            raise ValueError('该连接未保存 KEY，请在本机设置中配置')
        instruction = '请仅回复：连接测试通过' if test_request else (instruction_override or self.assistant_input.toPlainText().strip())
        mode = 0 if test_request else self.assistant_mode.currentIndex()
        stage = stage_override or ['discussion', 'draft_patch', 'review_draft'][mode]
        if not instruction and stage in {'fact_extract', 'chapter_summary'}:
            instruction = '按原文证据提取绑定对象的事实候选，不自行确认。' if stage == 'fact_extract' else '总结已确认正文的事件、人物变化与伏笔，附逐字证据。'
        if stage == 'chapter_summary' and variant_id is None and provider is None:
            allow_reuse = QMessageBox.question(self, '复用分析结果', '允许本次复用未变化的章节分析吗？依据、规则、模型或参数变化会失效；“再生成”会强制新请求。') == QMessageBox.StandardButton.Yes
        if self.last_task:
            previous_service, previous_id = self.last_task
            previous = previous_service.get(previous_id)
            if previous['state'] == 'uncertain' and previous['snapshot']['instruction'] == instruction:
                if QMessageBox.question(self, '上次结果待确认', '上次请求可能已被服务接受。重新提交可能再次计费，仍要发新任务吗？') != QMessageBox.StandardButton.Yes:
                    return
        cursor = self.editor.textCursor()
        text = self.editor.toPlainText()
        start = len(text.encode('utf-16-le')[:cursor.selectionStart() * 2].decode('utf-16-le'))
        end = len(text.encode('utf-16-le')[:cursor.selectionEnd() * 2].decode('utf-16-le'))
        service = self.task_service()
        reasoning=self.reasoning_combo.currentData() if not test_request else ('none' if connection.provider=='deepseek' and 'none' in connection.reasoning_levels else None)
        snapshot = service.prepare(self.document_id, instruction, connection, stage, start, end,
            self.budget_combo.currentText(), reasoning,
            test_request=test_request, development_test=provider is not None, allow_reuse=allow_reuse, variant_id=variant_id, continuation_task_id=continuation_task_id, planning_ids=planning_ids)
        cancel = CancelToken()
        worker = TaskWorker(service, snapshot, cancel, provider)
        self.active_task = dict(service=service, snapshot=snapshot, cancel=cancel, worker=worker)
        self.last_task = (service, snapshot['task_id'])
        self.chat_output.clear()
        self.assistant_info.hide()
        self.review_candidate_button.setEnabled(False)
        self.send_button.hide()
        self.stop_button.show()
        self.status.setText('正在等待模型 · ' + connection.name)
        worker.signals.text.connect(self.task_text)
        worker.signals.finished.connect(self.task_finished)
        self.text_completion_poll.start()
        QThreadPool.globalInstance().start(worker)

    def poll_text_completion(self):
        active=self.active_task
        if not active:
            self.text_completion_poll.stop()
        elif active['worker'].completed.is_set():
            self.task_finished(active['snapshot']['task_id'],active['worker'].result)

    def task_text(self, task_id, delta):
        if not self.active_task or self.active_task['snapshot']['task_id'] != task_id:
            return
        if not self.store or self.store.root != self.active_task['service'].store.root:
            return
        cursor = self.chat_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(delta)
        self.chat_output.setTextCursor(cursor)

    def task_finished(self, task_id, result):
        if not self.active_task or self.active_task['snapshot']['task_id'] != task_id:
            return
        service = self.active_task['service']
        snapshot = self.active_task['snapshot']
        self.active_task = None
        self.text_completion_poll.stop()
        self.creator_page.receive(service,task_id,result)
        self.stop_button.hide()
        self.send_button.show()
        self.send_button.setEnabled(bool(self.model_combo.currentData()))
        if self.store and self.store.root == service.store.root:
            candidate = result.get('candidate') or {}
            display = candidate.get('text') or candidate.get('summary') or result.get('text') or result.get('error', '')
            if result['status']=='completed' and snapshot['stage'] in stages.SCHEMAS:
                display=stages.render(snapshot['stage'],candidate,WritingService(service.store).names())
            if snapshot['stage'] == 'fact_extract' and result['status'] == 'completed':
                display = f"已保存 {len(result.get('fact_ids', []))} 条设定候选，尚未确认为正式事实。\n\n" + display
            self.chat_output.setPlainText(display)
            status = {'completed': '候选已生成，原稿尚未改变', 'cancelled': '已停止；部分候选保留，服务端可能仍计费',
                      'uncertain': '结果待确认，未自动重发', 'incomplete': '输出未完成，不能采纳',
                      'invalid_output': '输出合同未通过，原响应保留', 'budget_paused': '达到调用/范围/循环限制，已暂停并保留结果'}.get(result['status'], '任务失败，原稿未改变')
            if result.get('local_reuse'):
                status = '已复用未变化的章节分析，本次没有请求模型'
            self.status.setText(status)
            self.connection_notice.setText(status + ('\n' + result['error'] if result.get('error') else ''))
            tool_errors = [entry['outcome']['error'] for entry in result.get('tool_trace', []) if entry['outcome'].get('error')]
            if tool_errors:
                self.connection_notice.setText(status + '\n工具未完成：' + '；'.join(tool_errors))
            if result.get('development_test'):
                self.connection_notice.setText('开发测试固定响应 · 没有请求真实模型\n' + status)
            self.review_candidate_button.setEnabled(result['status'] == 'completed' and (snapshot['stage'] == 'draft_patch' or bool(result.get('proposals'))))
            if result['status'] == 'completed' and snapshot['stage'] in {'review_draft', 'fact_extract', 'chapter_summary'}:
                self.review_candidate_button.setEnabled(True)
                self.review_candidate_button.setText({'review_draft': '查看审稿', 'fact_extract': '设定候选', 'chapter_summary': '查看摘要'}[snapshot['stage']])
            else:
                self.review_candidate_button.setText('查看修改')
            if result['status'] == 'completed' and snapshot['stage'] in stages.SCHEMAS:
                self.review_candidate_button.setEnabled(True)
                self.review_candidate_button.setText('审核作品' if snapshot['stage'] in stages.WRITING else '审核方案')
        else:
            self.status.setText('任务结果已保存到原项目，当前项目未改变')
        if result['status'] == 'completed' and not result.get('development_test') and not result.get('local_reuse'):
            try:
                connection = self.connections.get(snapshot['model_selection']['id'])
                frozen = snapshot['model_selection']
                if all(getattr(connection, key) == frozen[key] for key in ('provider', 'model', 'base_url', 'cli_path', 'credential_version')):
                    from app.storage.project import now
                    checks = dict(connection.verification, text_generation=dict(status='已实测', checked=now(),
                        stream_requested=frozen['stream'], usage_returned=result.get('raw_usage') is not None))
                    self.connections.save(replace(connection, verification=checks, capability_status='文字生成已实测；其他能力分别测试'))
            except ValueError:
                pass
        if self.close_after_task:
            self.close_after_task = False
            QTimer.singleShot(0, self.close)

    def stop_text_task(self):
        if self.active_task:
            self.active_task['cancel'].cancel()
            self.status.setText('正在停止本地等待；已有候选将保存，服务端费用可能仍会结算')

    def image_task_finished(self, task_id, result):
        active = self.active_image_task
        if active and active['task_id'] == task_id:
            self.active_image_task = None
            project = active['service'].store.metadata()['name']
            self.status.setText(project + ' · 图片任务 ' + result['status'] + ' · 已校验结果保存在原项目')
        if self.close_after_task and not self.active_task and not self.active_image_task:
            self.close_after_task = False
            QTimer.singleShot(0, self.close)

    def view_context(self):
        if self.last_task:
            service, task_id = self.last_task
            task = service.get(task_id)
            self.text_dialog('冻结上下文 · 不包含 KEY', json.dumps(task['snapshot'], ensure_ascii=False, indent=2))
        else:
            self.text_dialog('上下文范围', '本次任务默认使用当前选区；没有选区时读取当前文档。\n锁定文字和所需规则必须保留。\n提交后上下文、规则和模型冻结；历史结果不作为自动采纳的设定。')

    def task_history(self):
        service = self.task_service()
        rows = [row for row in service.history() if row['stage'] != 'image_generate']
        if not rows:
            self.text_dialog('任务历史 / 用量', '当前项目没有生成任务。未知费用不会记为 0。')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('当前项目任务历史 / 用量')
        dialog.resize(800, 580)
        layout = QVBoxLayout(dialog)
        choices = QComboBox()
        choices.addItems([r['created'] + ' · ' + r['stage'] + ' · ' + r['state'] + ' · ' + r['id'][:8] for r in rows])
        layout.addWidget(choices)
        preview = QTextBrowser()
        layout.addWidget(preview, 1)
        def selected(index):
            task = service.get(rows[index]['id'])
            result = task['result'] or {}
            preview.setPlainText(json.dumps(dict(state=task['state'], result=result, model=task['snapshot']['model_selection'],
                estimated_input_tokens=task['snapshot']['estimated_input_tokens']), ensure_ascii=False, indent=2))
        choices.currentIndexChanged.connect(selected)
        selected(0)
        def view_result():
            self.last_task = service, rows[choices.currentIndex()]['id']
            task = service.get(self.last_task[1])
            result = task['result'] or {}
            candidate = result.get('candidate') or {}
            self.chat_output.setPlainText(candidate.get('text') or result.get('text') or result.get('error', '尚未收到结果'))
            self.review_candidate_button.setEnabled(task['state'] == 'completed' and (task['stage'] == 'draft_patch' or bool(result.get('proposals'))))
            if task['state'] == 'completed' and task['stage'] in {'review_draft', 'fact_extract', 'chapter_summary'}:
                self.review_candidate_button.setEnabled(True)
                self.review_candidate_button.setText({'review_draft': '查看审稿', 'fact_extract': '设定候选', 'chapter_summary': '查看摘要'}[task['stage']])
            if task['state'] == 'completed' and task['stage'] in stages.SCHEMAS:
                self.review_candidate_button.setEnabled(True)
                self.review_candidate_button.setText('审核作品' if task['stage'] in stages.WRITING else '审核方案')
            dialog.accept()
        layout.addWidget(self.button('查看所选候选', view_result))
        dialog.exec()

    def review_candidate(self):
        if not self.last_task:
            raise ValueError('尚无写作候选')
        service, task_id = self.last_task
        task = service.get(task_id)
        if task['state'] == 'completed' and task['stage'] in stages.SCHEMAS:
            return self.review_workflow(service, task)
        if task['state'] == 'completed' and task['stage'] == 'review_draft':
            return self.show_review(task)
        if task['state'] == 'completed' and task['stage'] == 'fact_extract':
            return self.open_knowledge()
        if task['state'] == 'completed' and task['stage'] == 'chapter_summary':
            return self.show_summary(service, task)
        if (task['stage'] != 'draft_patch' and not task['result'].get('proposals')) or task['state'] != 'completed':
            raise ValueError('当前候选不是可采纳的写作修改')
        replacement = task['result']['candidate']['text'] if task['stage'] == 'draft_patch' else '\n\n'.join(
            f"段落 {item['block_id']}，范围 {item['start']}—{item['end']}\n{item['replacement']}" for item in task['result']['proposals'])
        dialog = QDialog(self)
        dialog.setWindowTitle('修改建议 · 原稿尚未改变')
        dialog.resize(800, 580)
        layout = QVBoxLayout(dialog)
        preview = QTextBrowser()
        if task['stage'] == 'draft_patch':
            diff = '\n'.join(difflib.unified_diff(task['snapshot']['selected_text'].splitlines(), replacement.splitlines(), fromfile='原选区 / 光标插入位置', tofile='建议文字', lineterm=''))
        else:
            with service.store.connection() as con:
                frozen = con.execute('SELECT text FROM revisions WHERE id=?', (task['snapshot']['base_revision'],)).fetchone()[0]
            segments = []
            for proposal in task['result']['proposals']:
                old = frozen[proposal['start']:proposal['end']]
                segments.append('\n'.join(difflib.unified_diff(old.splitlines(), proposal['replacement'].splitlines(),
                    fromfile='原段落 ' + proposal['block_id'], tofile='建议替换', lineterm='')))
            diff = '\n\n'.join(segments)
        preview.setPlainText(diff or replacement)
        layout.addWidget(preview, 1)
        layout.addWidget(self.label('采纳时检查文档版本、目标哈希及锁定文字；原稿变化时禁止自动覆盖。', 'muted'))
        def adopt():
            if not self.store or self.store.root != service.store.root or self.document_id != task['document_id']:
                raise ValueError('请先打开任务所属的原文档再采纳')
            if not self.save():
                return
            accepted = service.adopt(task_id)
            cursor = self.editor.textCursor()
            current_text = self.editor.toPlainText()
            self.loading = True
            try:
                cursor.beginEditBlock()
                for edit in reversed(accepted['edits']):
                    start = len(current_text[:edit['start']].encode('utf-16-le')) // 2
                    end = len(current_text[:edit['end']].encode('utf-16-le')) // 2
                    cursor.setPosition(start)
                    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                    cursor.insertText(edit['replacement'])
                cursor.endEditBlock()
                self.editor.setTextCursor(cursor)
                self.base_revision = accepted['revision']
                self.dirty = False
            finally:
                self.loading = False
            self.review_candidate_button.setEnabled(False)
            self.status.setText('修改已采纳并保存；Ctrl+Z 可撤销为新版本')
            dialog.accept()
        row = QHBoxLayout()
        row.addWidget(self.button('接受修改', adopt, True))
        def reject():
            service.reject(task_id)
            self.review_candidate_button.setEnabled(False)
            dialog.reject()
        row.addWidget(self.button('拒绝修改', reject))
        layout.addLayout(row)
        dialog.exec()

    def show_review(self, task):
        dialog = QDialog(self)
        dialog.setWindowTitle('审稿问题 · 仅审查，不自动改稿')
        dialog.resize(820, 590)
        layout = QVBoxLayout(dialog)
        issues = task['result']['candidate']['issues']
        items = QListWidget()
        for issue in issues:
            kind = '缺失项' if issue.get('kind') == 'missing' else '原文证据'
            items.addItem(kind + ' · ' + issue['issue'])
        layout.addWidget(items, 1)
        details = QTextBrowser()
        layout.addWidget(details, 1)
        def selected(index):
            if index >= 0:
                issue = issues[index]
                details.setPlainText('证据：' + (issue['evidence'] or issue.get('missing_item', '')) + '\n\n影响：' + issue['issue'] + '\n\n建议：' + issue['suggestion'])
        items.currentRowChanged.connect(selected)
        if issues:
            items.setCurrentRow(0)
        else:
            details.setPlainText('本次审稿没有返回可定位问题；这不代表作品不存在其他问题。')
        def locate():
            index = items.currentRow()
            if index < 0 or not issues[index]['evidence']:
                raise ValueError('缺失项没有具体原句，可查看该条说明')
            if not self.store or self.document_id != task['document_id'] or self.store.document(self.document_id)['head'] != task['snapshot']['base_revision']:
                raise ValueError('请打开该审稿版本；当前原稿已改变时不使用旧位置')
            cursor = self.editor.textCursor()
            cursor.setPosition(0)
            self.editor.setTextCursor(cursor)
            if self.editor.find(issues[index]['evidence']):
                dialog.accept()
            else:
                raise ValueError('当前内存稿与冻结证据不一致，请保存或撤销修改后定位')
        layout.addWidget(self.button('定位原文证据', locate))
        dialog.exec()

    def show_summary(self, service, task):
        dialog = QDialog(self)
        dialog.setWindowTitle('章节摘要候选 · 不反向覆盖正文')
        dialog.resize(720, 520)
        layout = QVBoxLayout(dialog)
        summary = task['result']['candidate']
        preview = QTextBrowser()
        preview.setPlainText(summary['summary'] + '\n\n原文证据：\n' + '\n'.join(summary['evidence']))
        layout.addWidget(preview)
        def adopt():
            service.adopt_summary(task['id'])
            self.review_candidate_button.setEnabled(False)
            self.status.setText('章节摘要已采用；正文保留为唯一真源')
            dialog.accept()
        layout.addWidget(self.button('采用章节摘要', adopt, True))
        dialog.exec()

    def open_knowledge(self):
        self.require_document()
        KnowledgeDialog(self).exec()

    def review_workflow(self, service, task):
        dialog = QDialog(self)
        dialog.setWindowTitle('作品/方案候选 · 来源稿与旧版本保留')
        dialog.resize(820, 600)
        layout = QVBoxLayout(dialog)
        preview = QTextBrowser()
        candidate = task['result']['candidate']
        preview.setPlainText(stages.render(task['stage'], candidate, WritingService(service.store).names()))
        layout.addWidget(preview, 1)
        if task['stage']=='screenplay_generate':
            total=sum(scene['estimated_seconds'] for scene in candidate['scenes'])
            target=task['snapshot']['constraints'].get('target_duration')
            layout.addWidget(self.label(f'预计 {total:g} 秒；目标 {target if target is not None else "未指定"} 秒。未音频实测；可调整目标、压缩非锁定内容或拆分场次。','muted'))
        as_new = QCheckBox('作为当前项目的新文档采用（保留原稿）')
        as_new.setChecked(True)
        if task['stage'] in stages.WRITING:
            layout.addWidget(as_new)
        def accept():
            if not self.store or self.store.root != service.store.root:
                raise ValueError('请先打开任务所属项目')
            if not self.save():
                return
            if task['stage'] in stages.WRITING:
                did = service.adopt_work(task['id'], new_document=as_new.isChecked())
                self.refresh_documents(did)
                self.pages.setCurrentWidget(self.writing)
                self.status.setText('作品候选已作为草稿采用；结构和来源已保存，定稿需另确认')
            else:
                service.adopt_plan(task['id'])
                self.status.setText('创作方案已确认保存，未覆盖正文')
            self.review_candidate_button.setEnabled(False)
            dialog.accept()
        layout.addWidget(self.button('采用作品' if task['stage'] in stages.WRITING else '确认方案', accept, True))
        layout.addWidget(self.button('拒绝候选', lambda: (service.reject(task['id']), dialog.reject())))
        dialog.exec()

    def toggle_outline_lock(self):
        self.require_document()
        node = self.store.setting('node:' + self.document_id)
        if not node:
            raise ValueError('当前文档未绑定大纲节点，先将已确认大纲落实为目录')
        node['locked'] = not node.get('locked')
        self.store.set_setting('node:' + self.document_id, node)
        self.status.setText('大纲节点已锁定' if node['locked'] else '大纲节点已明确解锁')

    def lock_typed_dialogue(self):
        self.require_document()
        if not self.save():
            return
        service = WritingService(self.store)
        payload = service.payload(self.document_id)
        if not payload or payload['stage'] != 'screenplay_generate':
            raise ValueError('先采用结构化剧本并绑定人物，再锁定逐句对白')
        lines = [b for scene in payload['data']['scenes'] for b in scene['blocks'] if b['kind'] == 'dialogue']
        labels = [service.names().get(b['speaker_id'], b['speaker_id']) + '：' + b['text'] for b in lines]
        if not labels:
            raise ValueError('当前剧本没有对白')
        choice, ok = QInputDialog.getItem(self, '锁定人物对白', '同时锁定说话人和顺序', labels, editable=False)
        if ok:
            service.lock_dialogue(self.document_id, lines[labels.index(choice)]['block_id'])
            self.status.setText('对白与人物绑定、顺序已锁定；动作仍可手改')

    def unlock_typed_dialogue(self):
        self.require_document()
        if QMessageBox.question(self, '明确解除当前人物对白锁', '解除当前文档所有逐句对白锁？') == QMessageBox.StandardButton.Yes:
            WritingService(self.store).unlock_dialogue(self.document_id)

    def reference_info(self):
        self.require_document()
        old = self.store.setting('reference_info:' + self.document_id, {})
        text, ok = QInputDialog.getMultiLineText(self, '当前来源稿信息', '未知字段留空；不根据文件名推断版权或作者。',
            json.dumps(dict(link=old.get('link',''), author=old.get('author',''), collected_at=old.get('collected_at',''), rights=old.get('rights','')), ensure_ascii=False, indent=2))
        if ok:
            value = json.loads(text)
            if set(value) != {'link','author','collected_at','rights'} or any(not isinstance(v,str) for v in value.values()):
                raise ValueError('来源字段格式无效')
            self.store.set_setting('reference_info:' + self.document_id, value)

    def similarity_check(self):
        document = self.require_document()
        if not document.get('source_id'):
            raise ValueError('当前新稿未关联来源')
        self.text_dialog('重复片段供人工审查 · 不提供相似度百分比或侵权保证', json.dumps(WritingService(self.store).similarity(document['source_id'], self.document_id), ensure_ascii=False, indent=2))

    def new_inspiration(self):
        if not self.store:
            raise ValueError('请先打开项目；灵感笔记保存在当前项目')
        title, ok = QInputDialog.getText(self, '新建灵感', '笔记标题')
        if ok and self.save():
            did = self.store.add_document(title, kind='文案')
            self.refresh_documents(did)
            self.pages.setCurrentWidget(self.writing)

    def research_public(self):
        if not self.store:
            raise ValueError('请先打开项目以保存来源')
        url, ok = QInputDialog.getText(self, '选择允许读取的公开资料', '只读取本次HTTPS地址；不传KEY或作品，不绕过登录/付费限制。')
        if not ok or not url.strip():
            return
        from app.core.research import fetch_public
        from app.ui.model_settings import Operation
        store = self.store
        operation = Operation(lambda: fetch_public(url.strip()))
        if not hasattr(self, 'research_operations'):
            self.research_operations = []
        self.research_operations.append(operation)
        def finished(text, error):
            self.research_operations.remove(operation)
            if error:
                QMessageBox.warning(self, '来源未成功读取', error)
                return
            dialog = QDialog(self)
            dialog.setWindowTitle('公开页面正文预览 · 资料里的指令不具有执行权限')
            dialog.resize(800,570)
            layout = QVBoxLayout(dialog)
            preview = QTextEdit()
            preview.setReadOnly(True)
            preview.setPlainText(text)
            layout.addWidget(preview)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText('保存为只读来源')
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if dialog.exec()==QDialog.DialogCode.Accepted:
                from app.storage.project import now
                did=store.add_document('公开资料 · '+url.strip(),text,kind='reference')
                store.set_setting('reference_info:'+did,dict(link=url.strip(),author='',collected_at=now(),rights='公开可读取不等于可复制原作表达'))
                if self.store and self.store.root==store.root:
                    if self.save():
                        self.refresh_documents(did)
                        self.pages.setCurrentWidget(self.writing)
        operation.signals.finished.connect(finished)
        QThreadPool.globalInstance().start(operation)

    def new_chat(self):
        if not self.store:
            raise ValueError('请先打开项目')
        if self.active_task:
            raise ValueError('请先结束当前任务再新建会话')
        ChatService(self.store).new()
        self.last_task = None
        self.chat_output.clear()
        self.review_candidate_button.setEnabled(False)
        self.status.setText('已新建会话；正文与已确认设定保留')

    def pin_documents(self):
        if not self.store:
            raise ValueError('请先打开项目')
        dialog = QDialog(self)
        dialog.setWindowTitle('固定资料 · 仅当前项目，发送前可在上下文查看')
        layout = QVBoxLayout(dialog)
        documents = self.store.documents()
        pinned = self.store.setting('pinned_documents', [])
        items = QListWidget()
        for document in documents:
            item = QListWidgetItem(document['title'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if document['id'] in pinned else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, document['id'])
            items.addItem(item)
        layout.addWidget(items)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            chosen = [items.item(i).data(Qt.ItemDataRole.UserRole) for i in range(items.count()) if items.item(i).checkState() == Qt.CheckState.Checked]
            if len(chosen) > 20:
                raise ValueError('固定资料超过 20 项，请选本次必要的资料')
            self.store.set_setting('pinned_documents', chosen)
            self.status.setText(f'已为当前项目固定 {len(chosen)} 份资料；下次任务生效')

    def regenerate_task(self):
        if not self.last_task:
            raise ValueError('请先选择历史任务')
        service, task_id = self.last_task
        task = service.get(task_id)
        if not self.store or self.store.root != service.store.root:
            raise ValueError('请先打开原任务项目')
        if self.document_id != task['document_id']:
            raise ValueError('请先打开原任务文档；不会把旧任务发到当前其他章节')
        if self.editor.toPlainText() != self.store.document(self.document_id)['text'] or self.base_revision != task['snapshot']['base_revision']:
            raise ValueError('原稿已更新，请重新选择范围并发送新任务；不使用旧偏移量')
        if QMessageBox.question(self, '生成新候选可能再次计费', '会使用当前版本和模型发新请求，不复用旧候选。确认再生成？') == QMessageBox.StandardButton.Yes:
            from app.storage.project import new_id
            text = self.editor.toPlainText()
            cursor = self.editor.textCursor()
            start = len(text[:task['snapshot']['target_start']].encode('utf-16-le')) // 2
            end = len(text[:task['snapshot']['target_end']].encode('utf-16-le')) // 2
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            self.editor.setTextCursor(cursor)
            self.start_text_task(stage_override=task['stage'], instruction_override=task['snapshot']['instruction'], variant_id=new_id())

    def quote_to_document(self):
        self.require_document()
        if not self.last_task:
            raise ValueError('请先选择候选')
        service, task_id = self.last_task
        if service.store.root != self.store.root:
            raise ValueError('候选不属于当前项目')
        if not self.save():
            return
        cursor = self.editor.textCursor()
        content = self.chat_output.textCursor().selectedText().replace('\u2029', '\n') or None
        text = self.editor.toPlainText()
        position = len(text.encode('utf-16-le')[:cursor.position() * 2].decode('utf-16-le'))
        local = service.quote(task_id, self.document_id, position, content)
        self.last_task = service, local
        self.status.setText('已形成本地引用提案，原稿未改变；本次不调用模型')
        self.review_candidate()

    def continue_unfinished(self):
        if not self.last_task:
            raise ValueError('请先选择未完成任务')
        service, task_id = self.last_task
        task = service.get(task_id)
        if task['state'] not in {'incomplete', 'cancelled', 'uncertain', 'budget_paused'} or not task['result'].get('text'):
            raise ValueError('该任务没有可继续的未完成片段')
        if not self.store or self.store.root != service.store.root or self.document_id != task['document_id']:
            raise ValueError('请先打开原任务文档')
        if self.base_revision != task['snapshot']['base_revision'] or self.editor.toPlainText() != self.store.document(self.document_id)['text']:
            raise ValueError('原稿已变化，请把旧片段另存并重新指定范围')
        if QMessageBox.question(self, '继续未完成内容可能再次计费', '会保留已收到片段，并向当前模型发一个新任务。旧结果未知时，服务端可能仍在结算。继续？') == QMessageBox.StandardButton.Yes:
            instruction = task['snapshot']['instruction'] + '\n本次接续资料区的未完成候选。保留已收到的有效内容，按当前输出合同返回完整目标候选，避免重复段落，不扩大修改范围。'
            from app.storage.project import new_id
            text = self.editor.toPlainText()
            cursor = self.editor.textCursor()
            cursor.setPosition(len(text[:task['snapshot']['target_start']].encode('utf-16-le')) // 2)
            cursor.setPosition(len(text[:task['snapshot']['target_end']].encode('utf-16-le')) // 2, QTextCursor.MoveMode.KeepAnchor)
            self.editor.setTextCursor(cursor)
            self.start_text_task(stage_override=task['stage'], instruction_override=instruction, variant_id=new_id(), continuation_task_id=task_id)

    def refresh_rules(self):
        selected = self.rule_list.currentRow()
        self.rule_data = ProjectRules(self.store, self.resources).rules() if self.store else ProjectRules(None, self.resources).base()
        self.rule_list.clear()
        for rule in self.rule_data:
            self.rule_list.addItem(rule['rule_id'] + ' ' + rule['title'])
        self.rule_list.setCurrentRow(max(0, min(selected, len(self.rule_data) - 1)))

    def selected_rule(self):
        row = self.rule_list.currentRow()
        if row < 0:
            raise ValueError('请选择规则')
        return self.rule_data[row]

    def edit_selected_rule(self):
        edit_rule(self, self.selected_rule())

    def import_rule_package(self):
        if not self.store:
            raise ValueError('请先打开项目')
        path, _ = QFileDialog.getOpenFileName(self, '导入规则，先预览元数据和覆盖范围', '', '规则文件 (*.json *.md *.txt)')
        if path:
            source = Path(path)
            if source.suffix.lower() in {'.md', '.txt'}:
                if source.stat().st_size > 2 * 1024**2:
                    raise ValueError('规则文件超过 2MB')
                body = source.read_text(encoding='utf-8-sig')
                from app.core.files import digest
                from app.storage.project import new_id
                supplied = dict(rule_id='CUSTOM_' + new_id()[:8].upper(), title=source.stem, body=body,
                    version='file-' + new_id()[:8], stages=['draft_patch'], applies_to=[], enabled=True,
                    priority=50, source=source.name + ' · SHA256 ' + digest(body))
                edit_rule(self, supplied)
            else:
                preview_and_import(self, ProjectRules(self.store, self.resources), load_package(path))

    def restore_rule_base(self):
        if not self.store:
            raise ValueError('请先打开项目')
        rule = self.selected_rule()
        if QMessageBox.question(self, '恢复内置规则为新版本', '已有任务快照保留，是否恢复“' + rule['title'] + '”？') == QMessageBox.StandardButton.Yes:
            ProjectRules(self.store, self.resources).restore_base(rule['rule_id'])
            self.refresh_rules()

    def choose_project_rules(self):
        if not self.store:
            raise ValueError('请先打开项目')
        dialog = QDialog(self)
        dialog.setWindowTitle('选用项目规则 · 相关核心规则仍按任务自动加载')
        dialog.resize(640, 570)
        layout = QVBoxLayout(dialog)
        items = QListWidget()
        active = self.store.setting('active_rule_ids', [])
        for rule in self.rule_data:
            item = QListWidgetItem(rule['rule_id'] + ' ' + rule['title'])
            item.setData(Qt.ItemDataRole.UserRole, rule['rule_id'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if rule['rule_id'] in active else Qt.CheckState.Unchecked)
            items.addItem(item)
        layout.addWidget(items)
        layout.addWidget(self.label('选择本次确实相关的少量方法；基础建议不能冒充完整细分规则。', 'muted'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            chosen = [items.item(i).data(Qt.ItemDataRole.UserRole) for i in range(items.count()) if items.item(i).checkState() == Qt.CheckState.Checked]
            self.store.set_setting('active_rule_ids', chosen)
            self.status.setText('项目规则选择已保存；已有任务仍用原快照')

    def clear_analysis_cache(self):
        if not self.store:
            raise ValueError('请先打开项目')
        with self.store.connection() as con:
            count = con.execute('SELECT COUNT(*) FROM cache_entries').fetchone()[0]
        if QMessageBox.question(self, '清理当前项目分析缓存', f'将清理 {count} 个可重建分析缓存。正文、事实、素材、封面和任务历史保留。') == QMessageBox.StandardButton.Yes:
            CacheService(self.store).clear()
            self.status.setText('分析缓存已清理，创作资料保留')

    def closeEvent(self, event):
        if self.backup_operation and not self.backup_operation.completed.is_set():
            self.close_after_backup=True
            self.status.setText('正在完成一致性备份，完成后关闭，不丢中间结果')
            event.ignore()
            return
        if self.active_image_task:
            self.close_after_task = True
            self.active_image_task['cancel'].cancel()
            self.status.setText('正在停止图片本地等待，远端仍可能计费；任务信息会保留')
            event.ignore()
            return
        if self.active_task:
            self.close_after_task = True
            self.stop_text_task()
            event.ignore()
            return
        if not self.save():
            event.ignore()
            return
        try:
            self.save_preferences()
        except OSError as exc:
            self.status.setText('偏好未保存：' + str(exc))
        event.accept()
