import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMessageBox, QSpinBox, QSplitter,
    QTabWidget, QTextBrowser, QTextEdit, QVBoxLayout, QWidget)

from app.core.cases import CaseLibrary, FORMATS, SOURCE_TYPES
from app.core.rules import ProjectRules
from app.storage.project import new_id

FORMAT_NAMES = {'film': '电影', 'series': '电视剧', 'tv_series': '电视剧', 'television_series': '电视剧', 'micro_drama': '微短剧', 'animation': '动画',
                'documentary': '纪录片', 'short_film': '短片', 'unknown': '未知'}


class CasePage(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.library = CaseLibrary(owner.preferences.parent, owner.resources / '影视案例库_改编关系种子_V0.1.json')
        self.selected_method = None
        layout = QVBoxLayout(self)
        layout.addWidget(owner.label('影视案例库', 'heading'))
        layout.addWidget(owner.label('查看参考作品与故事方法，选择合适的方法用于AI创作。当前内容来自示例库与用户导入。','muted'))
        search = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText('搜索作品、原作或作者')
        self.query.textChanged.connect(self.refresh)
        self.format = QComboBox()
        self.format.addItem('全部作品形式', None)
        for key, label in FORMAT_NAMES.items():
            self.format.addItem(label, key)
        self.format.currentIndexChanged.connect(self.refresh)
        self.favorites = QCheckBox('只看收藏')
        self.favorites.toggled.connect(self.refresh)
        search.addWidget(self.query, 1)
        search.addWidget(self.format)
        search.addWidget(self.favorites)
        layout.addLayout(search)
        from app.ui.advanced import fold
        advanced,advanced_layout,_=fold(layout,'更多筛选与案例管理')
        filters = QHBoxLayout()
        self.year_min, self.year_max = QSpinBox(), QSpinBox()
        for widget in (self.year_min, self.year_max):
            widget.setRange(0, 2100)
            widget.setSpecialValueText('不限年份')
            widget.valueChanged.connect(self.refresh)
            filters.addWidget(widget)
        self.source_type = QComboBox()
        self.source_type.addItem('全部原作类型', None)
        for key in sorted(SOURCE_TYPES):
            self.source_type.addItem({'novel': '小说', 'essay_collection': '散文集', 'online_novel': '网络小说', 'unknown': '未知'}.get(key, key), key)
        self.source_type.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.source_type)
        filters.addWidget(owner.button('评分筛选', self.rating_filter))
        filters.addWidget(owner.button('清除筛选', self.clear_filters))
        self.rating_options = {}
        advanced_layout.addLayout(filters)
        row = QHBoxLayout()
        for title, function in [('新建', self.new_record), ('编辑 / 单字段核实', self.edit), ('导入', self.import_records),
            ('收藏', self.favorite), ('数据覆盖', self.coverage), ('导出', self.export)]:
            row.addWidget(owner.button(title, function))
        advanced_layout.addLayout(row)
        split = QSplitter()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.show_record)
        self.details = QTabWidget()
        self.pages = []
        for title in ('概况', '成绩与来源', '改编关系', '结构研究', '关联方法'):
            editor = QTextBrowser()
            editor.setOpenExternalLinks(False)
            self.details.addTab(editor, title)
            self.pages.append(editor)
        split.addWidget(self.list)
        split.addWidget(self.details)
        split.setSizes([250, 600])
        layout.addWidget(split, 1)
        actions = QHBoxLayout()
        for title, function in [('新增指标快照', self.add_metric), ('加入比较', self.compare), ('方法候选', self.propose_method),
            ('审核方法', self.approve_method), ('用于当前项目', self.use_method), ('回收 / 恢复', self.recycle)]:
            actions.addWidget(owner.button(title, function))
        advanced_layout.addLayout(actions)
        self.refresh()

    def selected(self):
        index = self.list.currentRow()
        if index < 0:
            raise ValueError('请先选择案例')
        return self.rows[index]

    def refresh(self, *_):
        self.rows = self.library.records(self.query.text().strip(), self.format.currentData(), self.year_min.value() or None,
            self.year_max.value() or None, self.source_type.currentData(), self.favorites.isChecked(), **self.rating_options)
        self.list.clear()
        for row in self.rows:
            self.list.addItem(f"{row['title']}\n{row.get('release_year') or '年份未知'} · {FORMAT_NAMES[row['screen_format']]}")
        if self.rows:
            self.list.setCurrentRow(0)
        else:
            for page in self.pages:
                page.setPlainText('无匹配案例；可清除筛选')

    def show_record(self, index):
        if index < 0 or index >= len(self.rows):
            return
        row = self.rows[index]
        self.pages[0].setPlainText(f"{row['title']}\n{row.get('release_year') or '年份待核实'} · {FORMAT_NAMES[row['screen_format']]}\n\n"+'\n'.join(row.get('notes',[])))
        self.pages[1].setPlainText('评分、票房、奖项各保留自己的平台/币种/日期口径，未知不当成0。\n\n' + json.dumps({key: row.get(key, []) for key in ('rating_snapshots','box_office_snapshots','award_records','short_drama_metrics','evidence')}, ensure_ascii=False, indent=2))
        types = {'novel': '小说', 'essay_collection': '散文集', 'online_novel': '网络小说', 'book': '图书'}
        sources = [f"{source['relation_type']}：{source['title']} · {source.get('author') or '作者未知'} · {types.get(source['source_type'], source['source_type'])}\n方向：{'影视作品 → 出版物' if source['relation_type'] == 'screen_to_book' else '来源作品 → 影视作品'}\n状态：{source.get('verification_status', '待核实')}" for source in row.get('adaptation_sources', [])]
        self.pages[2].setPlainText('\n\n'.join(sources) or '尚未登记来源关系；同名不等于改编')
        self.pages[3].setPlainText('结构研究：'+('尚未拆解' if row.get('analysis_status','not_analyzed')=='not_analyzed' else row['analysis_status'])+'\n可在参考与仿写栏目导入资料，再由AI拆解故事结构。')
        self.pages[4].setPlainText('方法先作为候选，审核后才可加入当前项目。项目引用保存版本快照，案例以后更新不会悄悄修改文稿。')

    def edit_dialog(self, record):
        dialog = QDialog(self)
        dialog.setWindowTitle('案例身份与字段来源 · 保留未知值')
        dialog.resize(780, 630)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        title = QLineEdit(record['title'])
        year = QSpinBox()
        year.setRange(0, 2100)
        year.setSpecialValueText('未知')
        year.setValue(record.get('release_year') or 0)
        fmt = QComboBox()
        for key, label in FORMAT_NAMES.items():
            fmt.addItem(label, key)
        fmt.setCurrentIndex(fmt.findData(record['screen_format']))
        form.addRow('片名', title)
        form.addRow('影视年份', year)
        form.addRow('作品形式', fmt)
        layout.addLayout(form)
        details = QTextEdit()
        value = {key: val for key, val in record.items() if not key.startswith('_') and key not in {'title', 'release_year', 'screen_format'}}
        details.setPlainText(json.dumps(value, ensure_ascii=False, indent=2))
        layout.addWidget(QLabel('关系、各项指标与来源的结构预览；字段核实只写 verified_fields，不自动核实整条。'))
        layout.addWidget(details, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('校验并保存新版本')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            value = json.loads(details.toPlainText())
            value.update(title=title.text(), release_year=year.value() or None, screen_format=fmt.currentData())
            self.library.save(value, record.get('_version'))
            self.refresh()

    def new_record(self):
        self.edit_dialog(self.library.blank('新案例'))

    def edit(self):
        self.edit_dialog(self.selected())

    def import_records(self):
        path, _ = QFileDialog.getOpenFileName(self, '案例字段映射导入', '', '案例数据 (*.json *.csv)')
        if not path:
            return
        rows = self.library.preview_import(path)
        dialog = QDialog(self)
        dialog.setWindowTitle('导入预览 · 同名作品按ID/年份独立保存')
        dialog.resize(720, 520)
        layout = QVBoxLayout(dialog)
        preview = QTextBrowser()
        preview.setPlainText(json.dumps(rows, ensure_ascii=False, indent=2))
        layout.addWidget(preview)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.library.import_records(rows)
            self.refresh()

    def favorite(self):
        row = self.selected()
        self.library.favorite(row['work_id'], not row['_favorite'])
        self.refresh()

    def coverage(self):
        self.owner.text_dialog('数据覆盖 · 未核查不等于零作品', json.dumps(self.library.coverage(), ensure_ascii=False, indent=2))

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出案例事实/来源/原创笔记', '', 'JSON (*.json)')
        if path:
            self.library.export(path)

    def clear_filters(self):
        self.query.clear()
        self.format.setCurrentIndex(0)
        self.source_type.setCurrentIndex(0)
        self.favorites.setChecked(False)
        self.year_min.setValue(0)
        self.year_max.setValue(0)
        self.rating_options = {}
        self.refresh()

    def rating_filter(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('评分口径筛选 · 不混合平台满分')
        layout = QFormLayout(dialog)
        platform, score, count, date = (QLineEdit() for _ in range(4))
        platform.setPlaceholderText('必须选择一个平台口径，例如 IMDb')
        score.setPlaceholderText('最低评分，按该平台原始满分')
        count.setPlaceholderText('最低人数；未知不算满足')
        date.setPlaceholderText('采集时间不早于 YYYY-MM-DD')
        for title, widget in [('平台', platform), ('评分', score), ('人数', count), ('采集时间', date)]:
            layout.addRow(title, widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if not platform.text().strip():
                raise ValueError('请选择评分平台，不能把不同平台分数直接平均或混筛')
            self.rating_options = dict(rating_platform=platform.text().strip(), min_rating=float(score.text()) if score.text() else None,
                min_count=int(count.text()) if count.text() else None, rating_after=date.text().strip() or None)
            self.refresh()

    def add_metric(self):
        row = self.selected()
        fields = ['rating_snapshots', 'box_office_snapshots', 'award_records', 'short_drama_metrics']
        titles = ['评分', '票房', '奖项', '微短剧指标']
        title, ok = QInputDialog.getItem(self, '新增历史快照，不覆盖原值', '指标类型', titles, editable=False)
        if not ok:
            return
        field = fields[titles.index(title)]
        samples = {
            'rating_snapshots': dict(platform='', platform_id='', score=None, scale=10, count=None, collected_at='', source='', status='unverified'),
            'box_office_snapshots': dict(amount=None, currency='', region='', period='', as_of='', release_batch='', includes_rerelease=None, nominal=None, source='', status='unverified'),
            'award_records': dict(organization='', year=None, category='', status='nominated', subject_type='screen_work', subject_id=row['work_id'], source=''),
            'short_drama_metrics': dict(platform='', metric='', value=None, unit='', interval='', definition='', source='', status='unverified')}
        content, ok = QInputDialog.getMultiLineText(self, '指标字段与口径', '未知留null，来源和采集时间需明确。', json.dumps(samples[field], ensure_ascii=False, indent=2))
        if ok:
            self.library.append_metric(row['work_id'], field, json.loads(content))
            self.refresh()

    def compare(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('选择2—4部案例，指标口径独立显示')
        layout = QVBoxLayout(dialog)
        items = QListWidget()
        for row in self.rows:
            from PySide6.QtWidgets import QListWidgetItem
            item = QListWidgetItem(row['title'] + ' · ' + str(row.get('release_year')))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            items.addItem(item)
        layout.addWidget(items)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = [self.rows[i] for i in range(items.count()) if items.item(i).checkState() == Qt.CheckState.Checked]
            if not 2 <= len(selected) <= 4:
                raise ValueError('请选择2—4部作品')
            self.owner.text_dialog('比较资料，不计算跨口径总榜', json.dumps(selected, ensure_ascii=False, indent=2))

    def propose_method(self):
        record = self.selected()
        payload = dict(title='', body='', stages=['draft_patch'], applies_to=[], applicable_when='', not_applicable_when='',
                       evidence_boundary='当前仅提供元数据，不能断言完整剧作或剪辑规律。', counterexamples=[])
        content, ok = QInputDialog.getMultiLineText(self, '案例方法候选，先记录再审核', '必须写明适用与不适用条件；不自动变成创作规则。', json.dumps(payload, ensure_ascii=False, indent=2))
        if ok:
            self.selected_method = self.library.propose_method([record['work_id']], json.loads(content))
            self.pages[4].setPlainText('方法候选已保存，尚未审核：\n' + content)

    def approve_method(self):
        if not self.selected_method:
            raise ValueError('请先创建或选择方法候选')
        method = self.library.get_method(self.selected_method)
        if QMessageBox.question(self, '审核方法', '确认其证据边界、适用/不适用条件与反例后，批准这条方法？\n' + method['payload']['title']) == QMessageBox.StandardButton.Yes:
            self.library.approve_method(self.selected_method)
            self.pages[4].setPlainText('方法已由用户审核；加入项目时仍冻结版本。')

    def use_method(self):
        if not self.owner.store or not self.selected_method:
            raise ValueError('请先打开创作项目并选择已审核方法')
        rid = self.library.use_method(self.selected_method, ProjectRules(self.owner.store, self.owner.resources))
        method = self.library.get_method(self.selected_method)
        records = [self.library.get(work_id) for work_id in method['record_ids']]
        self.owner.store.set_setting('case_method:' + self.selected_method, dict(method=method, cases=records))
        active = self.owner.store.setting('active_rule_ids', [])
        if rid not in active:
            self.owner.store.set_setting('active_rule_ids', active + [rid])
        self.owner.refresh_rules()
        self.owner.status.setText('已将所选审核方法和必要案例快照加入当前项目，不发送整库')

    def recycle(self):
        titles = ['回收选中', '恢复回收区']
        choice, ok = QInputDialog.getItem(self, '案例回收区', '不会删除项目已经引用的快照', titles, editable=False)
        if not ok:
            return
        if choice == titles[0]:
            self.library.trash(self.selected()['work_id'])
        else:
            rows = self.library.records(deleted=True)
            if not rows:
                raise ValueError('案例回收区为空')
            labels = [row['title'] + ' · ' + str(row.get('release_year')) for row in rows]
            selected, ok = QInputDialog.getItem(self, '恢复案例', '案例', labels, editable=False)
            if ok:
                self.library.trash(rows[labels.index(selected)]['work_id'], restore=True)
        self.refresh()
