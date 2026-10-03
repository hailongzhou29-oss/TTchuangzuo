"""Novel and rewrite views reuse the shared editor, task flow and stable controls."""
import copy
from PySide6.QtCore import Qt,QTimer,QPoint
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QWidget,QFrame,QVBoxLayout,QHBoxLayout,QLineEdit,QTextEdit,QTextBrowser,QScrollArea,QStackedWidget,QTabBar,QListWidget,QSplitter,QSizePolicy,QMenu,QApplication
from app.ui.creation_page import CreationPage
from app.ui.v2_widgets import label,button,QComboBox,MultiChoice,QMenu
from app.ui.novel_settings import NovelSettings,RewriteScriptSettings
from app.core.selection import selection
from app.core.writing_views import writing_config,is_long,source_snapshot

class WritingPage(CreationPage):
    def __init__(self,owner,kind):
        QWidget.__init__(self); self.owner=owner; self.kind=kind; self.config=writing_config(selection(kind),kind); self.loading=True; self.view_focus={}; self.restoring_ui=False; self.ui_restored_view=False; self.reference_expanded=False; self.branch_configs={}
        root=QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        header=QWidget(self); header.setObjectName('viewHeader'); header.setFixedHeight(40); self.view_header=header; self.title_row=QHBoxLayout(header); self.title_row.setContentsMargins(24,0,24,0)
        self.view_tabs=QTabBar(); self.view_tabs.setObjectName('creationViews'); self.view_tabs.setExpanding(False); self.view_tabs.setDrawBase(False)
        for text in ['创作设置','作品正文']: self.view_tabs.addTab(text)
        self.title_row.addWidget(self.view_tabs,1); self.title=QLineEdit('未命名'+self.type_name()); self.title.setObjectName('workMetadataTitle'); self.title.setMaximumWidth(180); self.title.editingFinished.connect(self.rename); self.title_row.addWidget(self.title); self.saved=label('草稿','muted'); self.title_row.addWidget(self.saved); root.addWidget(header)
        self.banner=label('','muted'); self.banner.hide(); root.addWidget(self.banner)
        self.confirm_bar=QWidget(self); confirm=QHBoxLayout(self.confirm_bar); confirm.addWidget(label('重新生成会保留当前版本，结果可比较后采用。'),1); confirm.addWidget(button('重新生成',lambda:owner.run(lambda:owner.generate(self,True)),True)); confirm.addWidget(button('取消',self.confirm_bar.hide)); self.confirm_bar.hide(); root.addWidget(self.confirm_bar)
        self.views=QStackedWidget(); root.addWidget(self.views,1); self.settings_scroll=QScrollArea(); self.settings_scroll.setWidgetResizable(True); self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); self.settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn); self.views.addWidget(self.settings_scroll)
        settings=QWidget(); settings.setObjectName('settingsContent'); self.settings_layout=QVBoxLayout(settings); self.settings_layout.setContentsMargins(24,16,24,18); self.settings_layout.setSpacing(16); self.settings_scroll.setWidget(settings)
        self.reference=QTextEdit(self); self.reference.setAcceptRichText(False); self.reference.setPlaceholderText('粘贴参考原文，或已取得的反推分镜文字。视频与链接不会在这里假装读取。'); self.reference.setFixedHeight(180); self.reference.textChanged.connect(self.reference_changed)
        self.ref_actions=QWidget(self); self.reference_description=QLineEdit(self); self.reference_description.setMaxLength(1000000); self.reference_description.setPlaceholderText('没有原文时，可明确描述要借鉴的结构与节奏'); self.reference_description.textChanged.connect(lambda:self.config_changed(reflow=False))
        if kind=='rewrite':
            self.reference_card,reference_layout=self.card('参考内容'); self.settings_layout.addWidget(self.reference_card); self.source_status=label('未提供参考','muted'); reference_layout.addWidget(self.source_status)
            ref_layout=QHBoxLayout(self.ref_actions); ref_layout.setContentsMargins(0,0,0,0); ref_layout.addWidget(button('导入文件',lambda:owner.run(lambda:owner.import_reference(self)))); ref_layout.addWidget(button('选择已有作品',lambda:owner.run(lambda:owner.choose_reference(self)))); self.ref_fold=button('展开预览 ▾',self.fold_reference,quiet=True); ref_layout.addWidget(self.ref_fold); ref_layout.addStretch(); ref_layout.addWidget(button('清空参考',lambda:self.use_reference('',dict(name='粘贴文本',type='粘贴文本')))); reference_layout.addWidget(self.ref_actions); reference_layout.addWidget(self.reference); reference_layout.addWidget(label('或明确的结构描述','muted')); reference_layout.addWidget(self.reference_description)
        else: self.reference.hide(); self.ref_actions.hide(); self.reference_description.hide()
        self.idea=QTextEdit(self)
        self.generate_button=button(self.generate_text(),lambda:owner.run(lambda:owner.generate(self)),True)
        self.branch_stack=QStackedWidget(); self.settings_layout.addWidget(self.branch_stack)
        self.novel_form=NovelSettings(self); self.branch_stack.addWidget(self.novel_form)
        if kind=='rewrite':
            from app.core.script_settings import migrate
            self.config['script_settings']=migrate(selection('script'),new=True)['script_settings']; self.script_form=RewriteScriptSettings(self); self.branch_stack.addWidget(self.script_form)
            self.strategy_card,strategy=self.card('仿写策略'); self.settings_layout.addWidget(self.strategy_card); strategy_row=QHBoxLayout(); strategy.addLayout(strategy_row); self.rewrite_method=QComboBox(); self.rewrite_method.addItems(['结构借鉴','风格借鉴','用户提供内容改写']); strategy_row.addWidget(self.rewrite_method); self.rewrite_level=QComboBox(); self.rewrite_level.addItems(['轻度调整','结构仿写','深度重构']); strategy_row.addWidget(self.rewrite_level)
            self.strategy_fields={}
            for key,title,values in [('keep','借鉴／保留',['核心观点','事件骨架','情绪走向','节奏结构','人物关系','高潮机制','结尾方式','台词含义']),('change','改变方向',['人物身份','时代背景','地点环境','核心事件','冲突机制','表达方式','结尾']),('emphasis','强化方向',['更强冲突','更多反转','台词更自然','提高信息密度','更有画面','情绪','爽点','更适合传播'])]:
                strategy.addWidget(label(title,'muted')); field=MultiChoice([(v,v) for v in values]); field.changed.connect(lambda:self.config_changed(reflow=False)); strategy.addWidget(field); self.strategy_fields[key]=field
            self.requirements_toggle=button('具体要求 ▾',self.toggle_requirements,quiet=True); strategy.addWidget(self.requirements_toggle); self.requirements=QWidget(); require=QVBoxLayout(self.requirements); require.setContentsMargins(0,0,0,0)
            self.must_keep=QLineEdit(); self.must_change=QLineEdit(); self.must_avoid=QLineEdit()
            for name,field in [('必须保留',self.must_keep),('必须改变',self.must_change),('不要出现',self.must_avoid)]: field.setMaxLength(1000000); field.setPlaceholderText('按需填写，可留空'); require.addWidget(label(name,'muted')); require.addWidget(field); field.textChanged.connect(lambda:self.config_changed(reflow=False))
            self.requirements.hide(); strategy.addWidget(self.requirements); self.rewrite_method.currentIndexChanged.connect(lambda:self.config_changed(reflow=False)); self.rewrite_level.currentIndexChanged.connect(lambda:self.config_changed(reflow=False))
        self.idea_card,ideas=self.card('你的想法'); self.settings_layout.addWidget(self.idea_card); self.idea.setObjectName('ideaEditor'); self.idea.setAcceptRichText(False); self.idea.setPlaceholderText('写一句想法，也可以留空'); self.idea.setFixedHeight(80); self.idea.textChanged.connect(lambda:self.config_changed(reflow=False)); ideas.addWidget(self.idea); self.settings_layout.addStretch()
        self.body_view=QWidget(); body=QVBoxLayout(self.body_view); body.setContentsMargins(24,16,24,18); body.setSpacing(10); self.views.addWidget(self.body_view)
        tools=QHBoxLayout(); self.directory=button('章节目录',self.toggle_directory,quiet=True); tools.addWidget(self.directory); self.location=QComboBox(); self.location.currentIndexChanged.connect(self.change_document); tools.addWidget(self.location,1); self.cover_button=button('封面',lambda:owner.run(owner.open_cover)); self.export_button=button('导出',self.export_menu); tools.addWidget(self.cover_button); tools.addWidget(self.export_button)
        from app.ui.v2_widgets import font_controls
        self.font_controls=font_controls(owner); tools.insertWidget(2,self.font_controls)
        self.compare_button=button('参考原文对照',self.toggle_compare,quiet=True); self.compare_button.setCheckable(True); self.compare_button.setVisible(kind=='rewrite'); tools.addWidget(self.compare_button); tools.addWidget(button('…',self.editor_menu,quiet=True)); body.addLayout(tools)
        self.find_row=QWidget(); finder=QHBoxLayout(self.find_row); finder.setContentsMargins(0,0,0,0); self.find=QLineEdit(); self.find.setPlaceholderText('搜索当前正文'); finder.addWidget(self.find,1); finder.addWidget(button('上一处',lambda:self.editor.find(self.find.text(),__import__('PySide6.QtGui',fromlist=['QTextDocument']).QTextDocument.FindFlag.FindBackward))); finder.addWidget(button('下一处',lambda:self.editor.find(self.find.text()))); finder.addWidget(button('关闭',self.find_row.hide)); self.find_row.hide(); body.addWidget(self.find_row)
        self.completion_summary=label('','muted'); self.completion_summary.setWordWrap(True); body.addWidget(self.completion_summary)
        self.content_split=QSplitter(); self.content_split.setChildrenCollapsible(False); self.chapters=QListWidget(); self.chapters.setMaximumWidth(210); self.chapters.itemClicked.connect(lambda item:owner.run(lambda:owner.select_document(item.data(Qt.ItemDataRole.UserRole)))); self.content_split.addWidget(self.chapters)
        self.editor=QTextEdit(); self.editor.setObjectName('workEditor'); self.editor.setAcceptRichText(False); self.editor.setPlaceholderText('暂无正文。可先生成作品，也可通过作品菜单导入正文。'); self.editor.textChanged.connect(self.edited); self.editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.editor.customContextMenuRequested.connect(self.context_menu); self.content_split.addWidget(self.editor)
        self.compare=QTextBrowser(); self.compare.setObjectName('referenceCompare'); self.compare.setReadOnly(True); self.compare.setMaximumWidth(420); self.compare.setMinimumWidth(180); self.compare.hide(); self.content_split.addWidget(self.compare); self.content_split.setStretchFactor(1,1); body.addWidget(self.content_split,1)
        self.next_button=button('续写下一章',lambda:owner.run(owner.next_chapter)); self.next_button.hide()
        footer=QFrame(); footer.setObjectName('creationFooter'); footer.setFixedHeight(56); actions=QHBoxLayout(footer); actions.setContentsMargins(24,10,24,10); self.model_summary=label('当前模型：未选择','muted'); self.model_summary.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed); actions.addWidget(self.model_summary,1); self.generate_button.setMinimumWidth(150); actions.addWidget(self.generate_button); root.addWidget(footer)
        self.selection_summary=label('','muted'); self.selection_summary.hide(); self.advanced_toggle=button('创作细节',lambda:self.settings_scroll.ensureWidgetVisible(self.novel_form.details_card)); self.advanced_toggle.hide()
        self.draft_timer=QTimer(self); self.draft_timer.setSingleShot(True); self.draft_timer.timeout.connect(lambda:owner.run(self.flush_draft)); self.ui_timer=QTimer(self); self.ui_timer.setSingleShot(True); self.ui_timer.timeout.connect(lambda:owner.run(self.save_ui_state)); self.settings_scroll.verticalScrollBar().valueChanged.connect(self.remember_ui)
        self.loading=False; self.load_config(self.config); self.view_tabs.currentChanged.connect(self.set_view); self.set_view(0)
    @staticmethod
    def card(title):
        frame=QFrame(); frame.setObjectName('card'); layout=QVBoxLayout(frame); layout.setContentsMargins(16,16,16,16); layout.setSpacing(12); layout.addWidget(label(title,'sectionHeading')); return frame,layout
    def read_config(self):
        if not hasattr(self,'novel_form'): return copy.deepcopy(self.config)
        output=self.config.get('output','novel'); c=self.novel_form.read_config(self.config) if output=='novel' else self.script_form.read_config(self.config)
        c.update(kind=self.kind,output=output,idea=self.idea.toPlainText(),reference=self.reference.toPlainText(),reference_description=self.reference_description.text())
        if output=='novel': c.pop('script_settings',None)
        if self.kind=='rewrite':
            c.update(rewrite_method=self.rewrite_method.currentText(),rewrite_level=self.rewrite_level.currentText(),must_change=self.must_change.text(),**{key:field.values.copy() for key,field in self.strategy_fields.items()})
            c.setdefault('advanced',{}).update({'必须保留':self.must_keep.text(),'不要出现':self.must_avoid.text()})
            c['rewrite_branches']=copy.deepcopy(self.branch_configs)
        return c
    def load_config(self,config):
        c=writing_config(config,self.kind); self.loading=True
        try:
            self.config=c; self.branch_configs=copy.deepcopy(c.get('rewrite_branches',{})); self.novel_form.load(c)
            if self.kind=='rewrite':
                script_config=copy.deepcopy(self.branch_configs.get('script',c)); script_config.update(reference=c.get('reference',''),idea=c.get('idea',''),kind='rewrite',output='script')
                self.script_form.load(script_config); self.script_form.fields['output'].setCurrentIndex(0)
                # ScriptSettings loads its page config; keep the writing page's selected branch.
                self.config=c
                for key,field in self.strategy_fields.items(): field.set_values(c.get(key,[]))
                self.rewrite_method.setCurrentText(c.get('rewrite_method','结构借鉴')); self.rewrite_level.setCurrentText(c.get('rewrite_level','结构仿写')); self.must_keep.setText(str(c.get('advanced',{}).get('必须保留',''))); self.must_avoid.setText(str(c.get('advanced',{}).get('不要出现',''))); self.must_change.setText(c.get('must_change',''))
            self.idea.setPlainText(c.get('idea','')); self.reference.setPlainText(c.get('reference','')); self.reference_description.setText(c.get('reference_description','')); self.branch_stack.setCurrentWidget(self.novel_form if c['output']=='novel' else self.script_form)
            self.fields=self.novel_form.fields if c['output']=='novel' else self.script_form.fields; self.advanced_fields={k:w for k,w in self.novel_form.fields.items() if k not in ['length','genre','subgenres','words','chapters','chapter_words','perspective','language','output']}; self.advanced=self.novel_form.tabs
        finally: self.loading=False
        self.update_reference_status(); self.reflow(); self.refresh_empty_state()
    def switch_output(self,output):
        if self.loading or self.config.get('output')==output: return
        current=self.read_config(); self.branch_configs[current['output']]=copy.deepcopy({k:v for k,v in current.items() if k not in ['rewrite_branches','reference','reference_source','idea']})
        target=dict(selection('rewrite'),**copy.deepcopy(self.branch_configs.get(output,{}))); target.update(kind='rewrite',output=output,reference=current.get('reference',''),reference_source=current.get('reference_source',{}),reference_description=current.get('reference_description',''),idea=current.get('idea',''),rewrite_branches=self.branch_configs)
        for key in ['keep','change','emphasis','rewrite_method','rewrite_level','must_change']: target[key]=current.get(key,target.get(key))
        target.setdefault('advanced',{}).update({k:current.get('advanced',{}).get(k,'') for k in ['必须保留','不要出现']})
        self.load_config(target); self.config_changed(reflow=False); self.remember_ui()
    def config_changed(self,*_,reflow=True):
        if self.loading or not hasattr(self,'draft_timer'): return
        self.config=self.read_config(); self.owner.options['draft:'+self.kind]=copy.deepcopy(self.config)
        work=self.owner.works.get(self.kind)
        if work: work.config=copy.deepcopy(self.config)
        self.saved.setText('保存中…'); self.draft_timer.start(250)
        if reflow: self.reflow()
        self.update_model_label(); self.refresh_generate_label()
    def flush_draft(self):
        self.draft_timer.stop()
        try: self.owner.save_page_draft(self); self.saved.setText('已保存' if self.owner.works.get(self.kind) else '草稿已保存')
        except OSError: self.saved.setText('保存失败'); self.notify('设置保存失败，输入仍保留，可重试。'); raise
    def set_view(self,index):
        if not hasattr(self,'views'): return
        if index==0 and getattr(self,'candidate_pane',None): self.owner.close_candidates(self)
        previous=self.views.currentIndex(); focus=QApplication.focusWidget()
        if focus and self.views.currentWidget().isAncestorOf(focus): self.view_focus[previous]=focus
        self.views.setCurrentIndex(index); self.view_tabs.setCurrentIndex(index)
        restore=self.view_focus.get(index)
        if restore and restore.isVisible(): restore.setFocus()
        self.remember_ui()
    def reflow(self):
        if not hasattr(self,'novel_form'): return
        edge=16 if self.width()<720 else 24; self.settings_layout.setContentsMargins(edge,16,edge,18); self.body_view.layout().setContentsMargins(edge,16,edge,18); self.view_header.layout().setContentsMargins(edge,0,edge,0); self.title.setVisible(self.width()>=620); self.view_header.setToolTip(self.title.text()+' · '+self.saved.text())
        if self.config.get('output')=='novel': self.novel_form.reflow()
        else: self.script_form.reflow()
        self.update_model_label()
    def resizeEvent(self,event): super(CreationPage,self).resizeEvent(event); self.reflow()
    def generate_text(self):
        if self.kind=='rewrite':
            work=self.owner.works.get(self.kind)
            return '重新生成改稿' if work and work.text.strip() else '开始仿写'
        if is_long(getattr(self,'config',{})):
            work=self.owner.works.get(self.kind)
            if work and work.text.strip():
                from app.core.writing_progress import chapter_status,book_progress
                status=chapter_status(work.store,work.document_id,work.config)
                if status['state']=='target_not_met':return '精简当前章' if status.get('range_state')=='above_range' else '扩写当前章'
                if book_progress(work.store,work.config)['state']=='plan_met':return '计划已完成'
            if work and any(work.store.document(d['id'])['text'].strip() for d in work.store.documents() if d['kind'] not in ['reference','outline']): return '续写下一章'
            return '生成开篇'
        work=self.owner.works.get(self.kind)
        return '重新生成改稿' if work and work.text.strip() else '生成小说'
    def refresh_generate_label(self):
        if hasattr(self,'generate_button') and not (self.owner.active_task and self.owner.active_task['page'] is self): self.generate_button.setText(self.generate_text())
    def update_model_label(self):
        if hasattr(self,'model_summary') and hasattr(self.owner,'assistant'):
            model=self.owner.assistant.model; self.model_summary.setText('当前模型：'+(model.currentText() if model.currentData() not in [None,'settings'] else '未选择'))
    def edited(self):
        if self.owner.loading: return
        self.owner.editor_changed(self); self.refresh_empty_state(); self.refresh_generate_label()
    def show_work(self,work):
        super().show_work(work); self.restore_ui_state(); self.refresh_empty_state(); self.refresh_generate_label()
    def refresh_documents(self,work):
        super().refresh_documents(work)
        self.refresh_progress(work)
        outline=work.store.setting('v2_outline_id')
        if outline:
            i=self.location.findData(outline)
            if i>=0: self.location.setItemText(i,'故事大纲')
        directory_open=work.store.setting('v2_directory_open')
        if directory_open is None:
            directory_open=not self.owner.narrow_layout()
            work.store.set_setting('v2_directory_open',directory_open)
        self.chapters.setVisible(work.config.get('output')=='novel' and directory_open); self.directory.setVisible(work.config.get('output')=='novel'); self.refresh_empty_state(); self.refresh_generate_label()
    def refresh_progress(self,work):
        if work.config.get('output')=='novel':
            from app.core.writing_progress import book_progress,chapter_status
            progress=book_progress(work.store,work.config); status=chapter_status(work.store,work.document_id,work.config)
            message=f'正文{status["actual_chars"]:,}非空白字符（汉字{status["chinese_chars"]:,}）／目标{status["target_chars"]:,}{status["target_unit"]}；90%最低阈值{status["minimum_chars"]:,}'
            if is_long(work.config):message+=f' · 已保存{progress["saved_chapters"]}/{progress["planned_chapters"]}章 · 全书{progress["actual_chars"]:,}非空白字符／目标{progress["target_chars"]:,}{status["target_unit"]}'
            from app.core.writing_progress import goal_status
            if status['state'] in {'target_not_met','target_met'}:message+=' · '+goal_status(status)
            self.completion_summary.setText(message);self.completion_summary.show()
        else:self.completion_summary.hide()
    def toggle_directory(self):
        visible=self.chapters.isHidden(); self.chapters.setVisible(visible)
        work=self.owner.works.get(self.kind)
        if work: work.store.set_setting('v2_directory_open',visible)
    def refresh_empty_state(self):
        if not hasattr(self,'editor'): return
        super().refresh_empty_state(); work=self.owner.works.get(self.kind); snapshot=work.store.setting('v2_rewrite_source:'+work.document_id,{}) if work and self.kind=='rewrite' else {}
        self.compare_button.setEnabled(bool(self.editor.toPlainText().strip()) and bool(snapshot)); self.compare_button.setToolTip('' if self.compare_button.isEnabled() else '暂无可确认的来源快照；新仿写完成后可对照冻结原文')
    def reference_changed(self):
        if self.loading: return
        from app.core.files import digest
        source=copy.deepcopy(self.config.get('reference_source',{})); source.setdefault('name','粘贴文本'); source.setdefault('type','粘贴文本'); source.setdefault('origin_revision',source.get('revision')); source['revision']=digest(self.reference.toPlainText()); source['status']='已读取文字' if self.reference.toPlainText().strip() else '未提供参考'; source['edited']=True; self.config['reference_source']=source; self.update_reference_status(); self.config_changed(reflow=False)
    def update_reference_status(self):
        if self.kind!='rewrite': return
        source=self.config.get('reference_source',{}); text=self.reference.toPlainText(); self.source_status.setText((source.get('name') or '粘贴文本')+' · '+('已读取文字' if text.strip() else '未提供可读原文')+f' · {len(text):,} 字'+(' · 已手动编辑' if source.get('edited') else ''))
    def use_reference(self,text,source):
        self.loading=True; self.config['reference_source']=copy.deepcopy(source); self.reference.setPlainText(text); self.loading=False; self.update_reference_status(); self.config_changed(reflow=False)
    def fold_reference(self):
        self.reference_expanded=not self.reference_expanded; self.reference.setFixedHeight(360 if self.reference_expanded else 180); self.ref_fold.setText('收起预览 ▴' if self.reference_expanded else '展开预览 ▾'); self.remember_ui()
    def toggle_requirements(self): self.requirements.setVisible(self.requirements.isHidden()); self.requirements_toggle.setText('收起具体要求 ▴' if self.requirements.isVisible() else '具体要求 ▾'); self.remember_ui()
    def toggle_compare(self):
        visible=not self.compare.isVisible()
        if visible:
            work=self.owner.works.get(self.kind); snapshot=work.store.setting('v2_rewrite_source:'+work.document_id,{}) if work else {}
            if not snapshot: self.notify('当前结果没有可确认的来源快照，不能把当前参考冒充生成时原文。'); self.compare_button.setChecked(False); return
            self.compare.setPlainText(snapshot.get('name','参考原文')+' · 生成时使用的参考\n\n'+snapshot.get('text','')); self.result_scroll=self.editor.verticalScrollBar().value(); self.compare_directory_open=not self.chapters.isHidden(); self.chapters.hide()
        self.compare.setVisible(visible); self.compare_button.setChecked(visible)
        if not visible:
            self.chapters.setVisible(self.config.get('output')=='novel' and getattr(self,'compare_directory_open',False)); QTimer.singleShot(0,self,lambda:self.editor.verticalScrollBar().setValue(getattr(self,'result_scroll',0)))
    def remember_ui(self,*_):
        if hasattr(self,'ui_timer') and not self.loading and not self.restoring_ui: self.ui_timer.start(900)
    def save_ui_state(self):
        self.ui_timer.stop(); state=dict(view=self.views.currentIndex(),settings_scroll=self.settings_scroll.verticalScrollBar().value(),detail_tab=self.novel_form.tabs.currentIndex(),reference_expanded=self.reference_expanded,requirements=not self.requirements.isHidden() if self.kind=='rewrite' else False)
        if self.kind=='rewrite': state.update(script_basic=self.script_form.basic_expanded,script_presentation=self.script_form.presentation_expanded,script_detail_tab=self.script_form.tabs.currentIndex(),script_presentation_tab=self.script_form.presentation_tabs.currentIndex())
        work=self.owner.works.get(self.kind)
        if work: work.store.set_setting('v2_ui:'+work.document_id,state)
        else: self.owner.options['draft_ui:'+self.kind]=state; self.owner.save_options()
    def restore_ui_state(self,state=None):
        work=self.owner.works.get(self.kind)
        if state is None: state=work.store.setting('v2_ui:'+work.document_id,{}) if work else self.owner.options.get('draft_ui:'+self.kind,{})
        self.restoring_ui=True; self.ui_restored_view=bool(state); self.novel_form.tabs.setCurrentIndex(max(0,min(5,state.get('detail_tab',0)))); self.set_view(max(0,min(1,state.get('view',0))))
        if self.kind=='rewrite':
            self.reference_expanded=bool(state.get('reference_expanded',False)); self.reference.setFixedHeight(360 if self.reference_expanded else 180); self.ref_fold.setText('收起预览 ▴' if self.reference_expanded else '展开预览 ▾'); self.requirements.setVisible(bool(state.get('requirements',False))); self.script_form.basic_expanded=bool(state.get('script_basic',False)); self.script_form.presentation_expanded=bool(state.get('script_presentation',False)); self.script_form.tabs.setCurrentIndex(max(0,min(5,state.get('script_detail_tab',0)))); self.script_form.presentation_tabs.setCurrentIndex(max(0,min(2,state.get('script_presentation_tab',0))))
        scroll=state.get('settings_scroll',0); self.reflow(); QTimer.singleShot(0,self,lambda:self.settings_scroll.verticalScrollBar().setValue(scroll)); self.restoring_ui=False
    def show_find(self): self.set_view(1); self.find_row.show(); self.find.setFocus()
