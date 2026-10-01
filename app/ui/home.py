from pathlib import Path
import sqlite3

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPushButton, QScrollArea, QStackedWidget, QToolButton,
    QVBoxLayout, QWidget)

from app.core.cover import default_cover, render_cover
from app.ui.icons import icon
from app.ui.project_list import PREVIEW_ROLE, ProjectListDelegate
from app.ui.elided_button import ElidedButton


class ProjectThumbnail(QLabel):
    def minimumSizeHint(self):
        return QSize(100, 190)

    def sizeHint(self):
        return QSize(190, 190)

    def set_source(self, image):
        self.source = QPixmap.fromImage(image)
        self.update_image()

    def update_image(self):
        if not hasattr(self, 'source') or self.width() < 1:
            return
        # A book preview must retain the whole cover, including its title.
        resized = self.source.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(resized)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_image()


class HomePage(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.columns = 0
        self.reflow = QTimer(self)
        self.reflow.setSingleShot(True)
        self.reflow.setInterval(50)
        self.reflow.timeout.connect(self.render_projects)
        self.setObjectName('homePage')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 24, 26, 20)
        layout.setSpacing(20)
        top = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(owner.label('我的创作', 'heading'))
        titles.addWidget(owner.label('让灵感成为作品', 'muted'))
        top.addLayout(titles)
        top.addStretch()
        top.addWidget(owner.button('新建项目', owner.new_project, True))
        top.addWidget(owner.button('导入作品', owner.import_file))
        layout.addLayout(top)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.viewport().setObjectName('homeViewport')
        content = QWidget()
        content.setObjectName('homeContent')
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(24)
        self.hero = QFrame()
        self.hero.setObjectName('featuredProject')
        hero_layout = QVBoxLayout(self.hero)
        hero_layout.setContentsMargins(16, 16, 16, 16)
        row = QHBoxLayout()
        row.setSpacing(24)
        owner.home_cover = QLabel()
        owner.home_cover.setFixedSize(244, 324)
        owner.home_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(owner.home_cover)
        details = QVBoxLayout()
        details.setContentsMargins(0, 12, 0, 12)
        details.setSpacing(12)
        title_line = QHBoxLayout()
        self.featured_title = owner.label('从一个想法开始', 'projectTitle')
        title_line.addWidget(self.featured_title)
        self.featured_kind = owner.label('本地写作', 'chip')
        title_line.addWidget(self.featured_kind)
        title_line.addStretch()
        details.addLayout(title_line)
        self.featured_pitch = owner.label('新建一个项目，写下第一段文字。', 'projectPitch')
        details.addWidget(self.featured_pitch)
        self.featured_summary = owner.label('新建一个项目，写下第一段文字。也可以导入已有作品，从原稿继续。', 'muted')
        self.featured_summary.setAlignment(Qt.AlignmentFlag.AlignTop)
        details.addWidget(self.featured_summary)
        details.addStretch()
        self.featured_meta = owner.label('正文、版本与封面保存在本机', 'muted')
        details.addWidget(self.featured_meta)
        hero_actions = QHBoxLayout()
        self.continue_button = owner.button('继续创作', owner.continue_project, True)
        hero_actions.addWidget(self.continue_button)
        self.more = QToolButton()
        self.more.setIcon(icon('dots'))
        self.more.setToolTip('项目操作')
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self.more)
        for text, callback in [('打开项目目录', owner.open_folder), ('重命名', owner.rename_project), ('复制项目', owner.copy_project), ('归档 / 取消归档', owner.archive_project), ('移入回收区 / 恢复', owner.trash_project), ('备份项目', owner.backup_project), ('恢复备份为新项目', owner.restore_backup)]:
            action = menu.addAction(text)
            action.triggered.connect(lambda checked=False, fn=callback: owner.run(fn))
        self.more.setMenu(menu)
        hero_actions.addWidget(self.more)
        hero_actions.addStretch()
        details.addLayout(hero_actions)
        row.addLayout(details, 1)
        hero_layout.addLayout(row)
        content_layout.addWidget(self.hero)
        section = QHBoxLayout()
        section.addWidget(owner.label('最近项目', 'subheading'))
        section.addStretch()
        self.search_toggle = owner.button('搜索', self.toggle_filters)
        section.addWidget(self.search_toggle)
        owner.view_toggle = owner.button('列表视图', owner.toggle_project_view)
        section.addWidget(owner.view_toggle)
        content_layout.addLayout(section)
        self.filters = QWidget()
        filters = QHBoxLayout(self.filters)
        filters.setContentsMargins(0, 0, 0, 0)
        owner.project_search = QLineEdit()
        owner.project_search.setPlaceholderText('搜索作品名称或类型')
        owner.project_search.textChanged.connect(owner.refresh_projects)
        filters.addWidget(owner.project_search, 1)
        owner.project_filter = QComboBox()
        owner.project_filter.addItems(['活跃项目', '已归档', '回收区'])
        owner.project_filter.currentIndexChanged.connect(owner.refresh_projects)
        filters.addWidget(owner.project_filter)
        content_layout.addWidget(self.filters)
        self.filters.hide()
        self.views = QStackedWidget()
        self.cards = QWidget()
        self.cards.setObjectName('projectCards')
        self.card_layout = QGridLayout(self.cards)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(16)
        owner.project_list = QListWidget()
        owner.project_list.setObjectName('projectList')
        owner.project_list.setMinimumHeight(260)
        owner.project_list.setItemDelegate(ProjectListDelegate(owner, owner.project_list))
        owner.project_list.setMouseTracking(True)
        owner.project_list.itemDoubleClicked.connect(lambda item: owner.run(lambda: owner.open_project(Path(item.data(Qt.ItemDataRole.UserRole)))))
        owner.project_list.currentItemChanged.connect(owner.project_selected)
        self.views.addWidget(self.cards)
        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)
        self.list_header = QFrame()
        self.list_header.setObjectName('projectListHeader')
        header_layout = QHBoxLayout(self.list_header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        for name, stretch in [('作品', 56), ('类型', 20), ('进度', 24)]:
            header_layout.addWidget(owner.label(name, 'muted'), stretch)
        list_layout.addWidget(self.list_header)
        list_layout.addWidget(owner.project_list)
        self.views.addWidget(list_page)
        self.views.setCurrentIndex(owner.options.get('project_view', 0))
        content_layout.addWidget(self.views)
        content_layout.addStretch()
        self.scroll.setWidget(content)
        layout.addWidget(self.scroll, 1)

    def select_project(self, root, open_it=False):
        for index in range(self.owner.project_list.count()):
            item = self.owner.project_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == root:
                self.owner.project_list.setCurrentItem(item)
                if open_it:
                    self.owner.run(lambda: self.owner.open_project(Path(root)))
                break

    def show_featured(self, store):
        metadata = store.metadata()
        self.featured_title.setText(metadata['name'])
        self.featured_kind.setText(store.setting('creation_constraints',{}).get('primary_genre') or metadata['kind'])
        summary = store.setting('summary', '')
        if not summary:
            docs = [d for d in store.documents() if d['kind'] != 'reference']
            summary = store.document(docs[0]['id'])['text'].strip()[:130] if docs else ''
        pitch, _, description = (summary or '故事从这里开始。打开项目，继续你的创作。').partition('\n')
        self.featured_pitch.setText(pitch)
        self.featured_summary.setText(description)
        self.featured_summary.setVisible(bool(description))
        self.featured_meta.setText('已保存在本地 · ' + str(len(store.documents())) + ' 个文档')

    def render_projects(self):
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        owner = self.owner
        count = owner.project_list.count()
        self.continue_button.setEnabled(count > 0)
        if not count:
            filtered = bool(owner.project_search.text()) or owner.project_filter.currentIndex() != 0
            empty = owner.label('没有符合条件的作品' if filtered else '还没有作品\n\n创建一个项目，开始你的第一个故事。', 'emptyState')
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(200)
            self.card_layout.addWidget(empty)
            if filtered:
                clear = owner.button('清除筛选', self.clear_filters)
                clear.setObjectName('clearProjectFilters')
                self.card_layout.addWidget(clear)
                self.filters.show()
                self.search_toggle.setText('收起搜索')
            owner.home_cover.clear()
            owner.home_cover.setText('你的\n第一部作品')
            self.featured_title.setText('从一个想法开始')
            self.featured_kind.setText('本地写作')
            self.featured_pitch.setText('新建一个项目，写下第一段文字。')
            self.featured_summary.setText('新建一个项目，写下第一段文字。也可以导入已有作品，从原稿继续。')
            return
        columns = 3 if self.width() >= 650 else (2 if self.width() >= 470 else 1)
        self.columns = columns
        for column in range(3):
            self.card_layout.setColumnStretch(column, 1 if column < columns else 0)
        selected = owner.project_list.currentItem()
        featured = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        shown = 0
        readable=[]
        for index in range(count):
            item = owner.project_list.item(index)
            root = item.data(Qt.ItemDataRole.UserRole)
            try:
                store = owner.workspace.open(Path(root))
                metadata = store.metadata()
                docs = [d for d in store.documents() if d['kind'] != 'reference']
                summary = store.setting('summary', '')
                cid = store.setting('active_cover')
                spec = next((c['spec'] for c in store.covers() if c['id'] == cid), None) or default_cover(metadata['name'], metadata['kind'])
            except (sqlite3.Error,OSError,ValueError,TypeError) as exc:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
                item.setData(PREVIEW_ROLE,dict(name=item.text().split('\n')[0],kind='不可读',summary='文件保留，可从备份恢复',status='不可读',thumbnail=QPixmap()))
                item.setToolTip(str(root)+'\n'+str(exc))
                card=QFrame()
                card.setObjectName('projectCard')
                warning=QVBoxLayout(card)
                warning.addWidget(owner.label('项目暂不可读','subheading'))
                warning.addWidget(owner.label('该项目未能加载，文件保留。其他项目仍可使用；可从更多菜单恢复备份。','muted'))
                self.card_layout.addWidget(card,shown//columns,shown%columns)
                shown+=1
                continue
            readable.append(item)
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable)
            image = None
            try:
                image = render_cover(spec, store.root, width=360)
            except (ValueError,OSError,KeyError,TypeError):
                pass
            item.setData(PREVIEW_ROLE, dict(name=metadata['name'], kind=metadata['kind'], summary=summary,
                         status='已定稿' if docs and all(d['status'] == 'confirmed' for d in docs) else '草稿',
                         thumbnail=QPixmap.fromImage(image) if image is not None else QPixmap()))
            if count > 1 and root == featured:
                continue
            card = QFrame()
            card.setObjectName('projectCard')
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 10, 16, 14)
            card_layout.setSpacing(10)
            cover = ProjectThumbnail()
            cover.setAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter)
            cover.setFixedHeight(253)
            cover.setMinimumWidth(100)
            if image is not None:
                cover.set_source(image)
            else:
                cover.setText('封面素材缺失\n可在项目中修复')
            card_layout.addWidget(cover)
            title = ElidedButton(metadata['name'])
            title.setObjectName('cardTitle')
            title.setToolTip(metadata['name']+' · 打开项目')
            title.clicked.connect(lambda checked=False, path=root: self.select_project(path, open_it=True))
            card_layout.addWidget(title)
            chip = owner.label(store.setting('creation_constraints',{}).get('primary_genre') or metadata['kind'], 'chip')
            chip.setMaximumWidth(110)
            card_layout.addWidget(chip)
            if not summary and docs:
                summary = store.document(docs[0]['id'])['text'].strip()[:50]
            description = owner.label(summary or '写下你的下一段故事。', 'muted')
            description.setMaximumHeight(58)
            card_layout.addWidget(description)
            card_layout.addStretch()
            self.card_layout.addWidget(card, shown // columns, shown % columns)
            shown += 1
        self.continue_button.setEnabled(bool(readable))
        if readable and owner.project_list.currentItem() not in readable:
            owner.project_list.setCurrentItem(readable[0])
        elif not readable:
            owner.project_list.setCurrentItem(None)
            owner.home_cover.clear()
            self.featured_title.setText('项目暂不可读')
            self.featured_pitch.setText('可以创建新项目，或从备份恢复。')
            self.featured_summary.setText('已有项目文件保留。')

    def toggle_view(self):
        next_index = 1 - self.views.currentIndex()
        self.views.setCurrentIndex(next_index)
        self.owner.view_toggle.setText('卡片视图' if next_index else '列表视图')
        self.owner.options['project_view'] = next_index
        self.owner.save_preferences()

    def toggle_filters(self):
        self.filters.setVisible(self.filters.isHidden())
        if self.filters.isVisible():
            self.owner.project_search.setFocus()
        self.search_toggle.setText('收起搜索' if self.filters.isVisible() else '搜索')

    def clear_filters(self):
        self.owner.project_search.blockSignals(True)
        self.owner.project_filter.blockSignals(True)
        self.owner.project_search.clear()
        self.owner.project_filter.setCurrentIndex(0)
        self.owner.project_search.blockSignals(False)
        self.owner.project_filter.blockSignals(False)
        self.owner.refresh_projects()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        columns = 3 if self.width() >= 650 else (2 if self.width() >= 470 else 1)
        if columns != self.columns and hasattr(self.owner, 'project_list'):
            self.reflow.start()
