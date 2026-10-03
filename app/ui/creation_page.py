"""Three creation pages share the same editor and controls, without approval gates."""
import json
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QTextEdit,QScrollArea,QTabWidget,QTabBar,QStackedWidget,QFrame,QMenu,QListWidget,QSplitter,QCheckBox,QSizePolicy)
from app.core.selection import selection,ADVANCED,Registry
from app.ui.v2_widgets import label,button,MultiChoice,QComboBox,font_controls,QMenu

class CreationPage(QWidget):
    def __init__(self,owner,kind):
        super().__init__(); self.owner=owner; self.kind=kind; self.config=selection(kind); self.loading=False; self.fields={}; self.advanced_fields={}; self.form_labels=[]; self.custom_inputs={}; self.advanced_custom={}
        layout=QVBoxLayout(self); layout.setContentsMargins(24,20,24,20); layout.setSpacing(8)
        title=QHBoxLayout(); self.title_row=title; self.title=QLineEdit('未命名'+self.type_name()); self.title.setObjectName('workTitle'); self.title.editingFinished.connect(self.rename)
        title.addWidget(self.title,1); self.saved=label('草稿' if kind=='script' else '已保存','muted'); title.addWidget(self.saved)
        layout.addLayout(title)
        self.form_scroll=QScrollArea(); self.form_scroll.setWidgetResizable(True); self.form_scroll.setMaximumHeight(230)
        self.form=QWidget(); self.grid=QGridLayout(self.form); self.grid.setContentsMargins(0,0,0,0); self.grid.setSpacing(8); self.grid.setAlignment(Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignLeft); self.form_scroll.setWidget(self.form); layout.addWidget(self.form_scroll)
        self.build_fields()
        self.selection_summary=label('','muted'); self.selection_summary.hide(); layout.addWidget(self.selection_summary)
        self.advanced_toggle=button('更多选择 ▾',self.toggle_advanced); self.advanced_toggle.setCheckable(True); self.advanced_toggle.setMaximumWidth(220); layout.addWidget(self.advanced_toggle,alignment=Qt.AlignmentFlag.AlignLeft)
        self.advanced=QTabWidget(); self.advanced.setMaximumHeight(220); self.build_advanced(); self.advanced.hide(); layout.addWidget(self.advanced)
        if kind=='rewrite':
            ref_grid=self.advanced.widget(5).widget().layout(); start_row=ref_grid.rowCount()
            extras=[(key,cell) for key,cell in self.form_labels if key in {'rewrite_level','keep','change','emphasis'}]
            for index,(_,cell) in enumerate(extras): self.grid.removeWidget(cell); ref_grid.addWidget(cell,start_row+index//2,index%2)
            self.form_labels=[(key,cell) for key,cell in self.form_labels if key not in {'rewrite_level','keep','change','emphasis'}]
        self.banner=label('','muted'); self.banner.hide(); layout.addWidget(self.banner)
        self.confirm_bar=QWidget(); confirm=QHBoxLayout(self.confirm_bar); confirm.setContentsMargins(0,0,0,0)
        confirm.addWidget(label('重新生成会创建一个新版本，当前内容将保留'),1); confirm.addWidget(button('重新生成',lambda:owner.run(lambda:owner.generate(self,True)),True)); confirm.addWidget(button('取消',self.confirm_bar.hide)); self.confirm_bar.hide(); layout.addWidget(self.confirm_bar)
        self.reference=QTextEdit(self); self.reference.setPlaceholderText('粘贴剧本、小说、人物台词，或视频反推后的分镜内容'); self.reference.setMaximumHeight(160); self.reference.textChanged.connect(self.config_changed)
        self.ref_actions=QWidget(self); ref_layout=QHBoxLayout(self.ref_actions); ref_layout.setContentsMargins(0,0,0,0)
        self.ref_fold=button('参考内容',self.fold_reference,quiet=True); ref_layout.addWidget(self.ref_fold,1)
        ref_layout.addWidget(button('导入文件',lambda:owner.run(lambda:owner.import_reference(self))))
        ref_layout.addWidget(button('已有作品',lambda:owner.run(lambda:owner.choose_reference(self))))
        self.ref_actions.setVisible(kind=='rewrite'); self.reference.setVisible(kind=='rewrite'); layout.addWidget(self.ref_actions); layout.addWidget(self.reference)
        ideas=QHBoxLayout(); self.idea=QTextEdit(); self.idea.setPlaceholderText('写一句想法，也可以留空，让 AI 自由构思'); self.idea.setFixedHeight(64); self.idea.textChanged.connect(self.config_changed); ideas.addWidget(self.idea,1)
        self.generate_button=button(self.generate_text(),lambda:owner.run(lambda:owner.generate(self)),True); self.generate_button.setMinimumHeight(40); ideas.addWidget(self.generate_button); layout.addLayout(ideas)
        tools=QHBoxLayout(); self.directory=button('目录',self.toggle_directory,quiet=True); self.directory.setParent(self); self.directory.setVisible(kind=='novel'); tools.addWidget(self.directory)
        self.location=QComboBox(); self.location.setMinimumWidth(100); self.location.currentIndexChanged.connect(self.change_document); tools.addWidget(self.location,1)
        self.cover_button=button('封面',lambda:owner.run(owner.open_cover)); self.export_button=button('导出',self.export_menu)
        self.font_controls=font_controls(owner); tools.addWidget(self.font_controls); tools.addWidget(self.cover_button); tools.addWidget(self.export_button); tools.addWidget(button('…',self.editor_menu,quiet=True)); layout.addLayout(tools)
        self.find_row=QWidget(); find_layout=QHBoxLayout(self.find_row); find_layout.setContentsMargins(0,0,0,0); self.find=QLineEdit(); self.find.setPlaceholderText('查找正文内容'); find_layout.addWidget(self.find,1)
        find_layout.addWidget(button('上一处',lambda:self.editor.find(self.find.text(),__import__('PySide6.QtGui',fromlist=['QTextDocument']).QTextDocument.FindFlag.FindBackward)))
        find_layout.addWidget(button('下一处',lambda:self.editor.find(self.find.text()))); find_layout.addWidget(button('×',self.find_row.hide)); self.find_row.hide(); layout.addWidget(self.find_row)
        self.content_split=QSplitter(); self.chapters=QListWidget(); self.chapters.setMaximumWidth(200); self.chapters.itemClicked.connect(lambda item:owner.run(lambda:owner.select_document(item.data(Qt.ItemDataRole.UserRole)))); self.chapters.hide(); self.content_split.addWidget(self.chapters)
        self.editor=QTextEdit(); self.editor.setObjectName('workEditor'); self.editor.setAcceptRichText(False); self.editor.setPlaceholderText('选择方向，点击生成，AI 会在这里完成作品'); self.editor.textChanged.connect(self.edited)
        self.editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.editor.customContextMenuRequested.connect(self.context_menu)
        self.content_split.addWidget(self.editor); layout.addWidget(self.content_split,1)
        self.next_button=button('生成下一章',lambda:owner.run(owner.next_chapter)); self.next_button.hide(); layout.addWidget(self.next_button)
        if kind=='script': self.build_script_layout(layout,tools)
        if kind=='script': self.refresh_empty_state()
        self.reflow()
    def build_script_layout(self,layout,tools):
        """Use the existing controls in two persistent views and one settings scroll."""
        while layout.count():
            item=layout.takeAt(0)
            if item.layout(): item.layout().setParent(None)
        layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)
        header=QWidget(); self.view_header=header; header.setObjectName('viewHeader'); row=QHBoxLayout(header); row.setContentsMargins(28,0,28,0); row.setSpacing(12)
        self.view_tabs=QTabBar(); self.view_tabs.setObjectName('creationViews'); self.view_tabs.addTab('创作设置'); self.view_tabs.addTab('作品正文'); self.view_tabs.setExpanding(False); self.view_tabs.setDrawBase(False)
        row.addWidget(self.view_tabs,1); self.title.setObjectName('workMetadataTitle'); self.title.setMaximumWidth(190); row.addWidget(self.title); row.addWidget(self.saved); layout.addWidget(header)
        layout.addWidget(self.banner); layout.addWidget(self.confirm_bar)
        self.views=QStackedWidget(); self.views.setObjectName('creationStack'); self.view_tabs.currentChanged.connect(self.set_view); layout.addWidget(self.views,1)
        self.settings_scroll=QScrollArea(); self.settings_scroll.setWidgetResizable(True); self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); self.settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        settings=QWidget(); settings.setObjectName('settingsContent'); self.settings_layout=QVBoxLayout(settings); self.settings_layout.setContentsMargins(24,16,24,18); self.settings_layout.setSpacing(16)
        self.settings_scroll.setWidget(settings); self.views.addWidget(self.settings_scroll)
        def card(title):
            frame=QFrame(); frame.setObjectName('card'); col=QVBoxLayout(frame); col.setContentsMargins(18,16,18,16); col.setSpacing(8); col.addWidget(label(title,'sectionHeading')); self.settings_layout.addWidget(frame); return frame,col
        self.form_scroll.hide(); self.advanced.hide(); self.advanced_toggle.hide()
        from app.ui.script_settings import ScriptSettings
        self.loading=True; self.script_form=ScriptSettings(self); self.loading=False; self.settings_layout.addWidget(self.script_form)
        self.basic_card=self.script_form.basic_card; self.presentation_card=self.script_form.presentation_card; self.details_card=self.script_form.details_card
        self.fields=self.script_form.fields; self.form_scroll=self.basic_card
        self.advanced=self.script_form.tabs; self.advanced_toggle=self.script_form.more_button
        self.idea_card,idea_layout=card('你的想法'); self.idea.setObjectName('ideaEditor'); self.idea.setPlaceholderText('写一句想法，也可以留空'); self.idea.setFixedHeight(80); idea_layout.addWidget(self.idea)
        self.settings_layout.addStretch()
        self.body_view=QWidget(); body=QVBoxLayout(self.body_view); body.setContentsMargins(28,16,28,18); body.setSpacing(10); body.addLayout(tools); body.addWidget(self.find_row); body.addWidget(self.content_split,1); self.views.addWidget(self.body_view)
        footer=QFrame(); footer.setObjectName('creationFooter'); actions=QHBoxLayout(footer); actions.setContentsMargins(28,12,28,12)
        self.model_summary=label('当前模型：未选择','muted'); self.model_summary.setWordWrap(False); self.model_summary.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed); actions.addWidget(self.model_summary,1); self.generate_button.setMinimumWidth(150); self.generate_button.setMinimumHeight(34); actions.addWidget(self.generate_button); layout.addWidget(footer)
        header.setFixedHeight(40); footer.setFixedHeight(56)
        self.draft_timer=QTimer(self); self.draft_timer.setSingleShot(True); self.draft_timer.timeout.connect(lambda:self.owner.run(self.flush_draft))
        self.ui_timer=QTimer(self); self.ui_timer.setSingleShot(True); self.ui_timer.timeout.connect(lambda:self.owner.run(self.save_ui_state)); self.restoring_ui=False; self.ui_restored_view=False
        self.settings_scroll.verticalScrollBar().valueChanged.connect(self.remember_ui)
        self.view_focus={}; self.ref_actions.hide(); self.selection_summary.hide(); self.next_button.hide(); self.set_view(0)
    def set_view(self,index):
        if self.kind!='script' or not hasattr(self,'views'): return
        if index==0 and getattr(self,'candidate_pane',None): self.owner.close_candidates(self)
        from PySide6.QtWidgets import QApplication
        previous=self.views.currentIndex(); focus=QApplication.focusWidget()
        if focus and self.views.currentWidget().isAncestorOf(focus): self.view_focus[previous]=focus
        self.views.setCurrentIndex(index); self.view_tabs.setCurrentIndex(index)
        restore=self.view_focus.get(index)
        if restore and restore.isVisible(): restore.setFocus()
        if index==0: self.reflow_script()
        self.remember_ui()
    def remember_ui(self,*_):
        if hasattr(self,'ui_timer') and not self.loading and not self.restoring_ui and not self.script_form.loading: self.ui_timer.start(900)
    def save_ui_state(self):
        self.ui_timer.stop(); form=self.script_form
        state=dict(view=self.views.currentIndex(),basic=form.basic_expanded,presentation=form.presentation_expanded,detail_tab=form.tabs.currentIndex(),presentation_tab=form.presentation_tabs.currentIndex(),settings_scroll=self.settings_scroll.verticalScrollBar().value())
        work=self.owner.works.get('script')
        if work: work.store.set_setting('v2_ui:'+work.document_id,state)
        else: self.owner.options['draft_ui:script']=state; self.owner.save_options()
    def restore_ui_state(self,state=None):
        if not hasattr(self,'ui_timer'): return
        if state is None:
            work=self.owner.works.get('script'); state=work.store.setting('v2_ui:'+work.document_id,{}) if work else self.owner.options.get('draft_ui:script',{})
        self.restoring_ui=True; self.ui_restored_view=bool(state); form=self.script_form
        form.basic_expanded=bool(state.get('basic',False)); form.presentation_expanded=bool(state.get('presentation',False)); form.tabs.setCurrentIndex(max(0,min(5,state.get('detail_tab',0)))); form.presentation_tabs.setCurrentIndex(max(0,min(2,state.get('presentation_tab',0)))); self.set_view(max(0,min(1,state.get('view',0)))); form.reflow()
        scroll=state.get('settings_scroll',0); QTimer.singleShot(0,self,lambda:self.settings_scroll.verticalScrollBar().setValue(scroll)); self.restoring_ui=False
    def update_model_label(self):
        if self.kind=='script' and hasattr(self,'model_summary') and hasattr(self.owner,'assistant'):
            model=self.owner.assistant.model; selected=model.currentData(); text='当前模型：'+(model.currentText() if selected and selected!='settings' else '未选择'); self.model_summary.setText(text); self.model_summary.setToolTip(text)
    def reflow_script(self,*_):
        if not hasattr(self,'views'): return
        if hasattr(self,'script_form'):
            edge=16 if self.width()<720 else 24; self.settings_layout.setContentsMargins(edge,16,edge,18); self.view_header.layout().setContentsMargins(edge,0,edge,0); self.body_view.layout().setContentsMargins(edge,16,edge,18)
            self.title.setVisible(self.width()>=600); self.title.setFixedWidth(160)
            self.view_header.setToolTip(self.title.text()+' · '+self.saved.text())
            self.script_form.reflow(); self.update_model_label(); return
    def type_name(self): return {'script':'剧本','novel':'小说','rewrite':'仿写'}[self.kind]
    def generate_text(self):
        work=self.owner.works.get(self.kind)
        return '重新生成改稿' if work and work.text.strip() else {'script':'生成剧本','novel':'生成小说','rewrite':'开始仿写'}[self.kind]
    def combo(self,key,title,values,editable=False):
        if key in {'language','perspective','format'} and '自定义…' not in values: values=values+['自定义…']
        w=QComboBox(); w.addItems(values); w.setEditable(editable); w.currentTextChanged.connect(self.config_changed)
        self.add_field(key,title,w)
        if '自定义…' in values:
            custom=QLineEdit(); custom.setPlaceholderText('输入你的要求'); custom.setMaxLength(500); custom.hide(); custom.textChanged.connect(self.config_changed); self.custom_inputs[key]=custom
            self.form_labels[-1][1].layout().addWidget(custom); w.currentTextChanged.connect(lambda text,custom=custom:custom.setVisible(text=='自定义…'))
        return w
    def spin(self,key,title,minimum,maximum,value):
        w=QSpinBox(); w.setRange(minimum,maximum); w.setValue(value); w.valueChanged.connect(self.config_changed); self.add_field(key,title,w); return w
    def add_field(self,key,title,w):
        cell=QWidget(self.form); cell.setObjectName('fieldCell'); cell.hide(); col=QVBoxLayout(cell); col.setContentsMargins(0,0,0,0); col.setSpacing(4); col.addWidget(label(title,'muted')); col.addWidget(w)
        cell.setMinimumWidth(130); cell.setMaximumWidth(220); w.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed); self.fields[key]=w; self.form_labels.append((key,cell))
    def build_fields(self):
        if self.kind=='script': return
        registry=self.owner.registry
        if self.kind=='rewrite':
            self.combo('output','输出类型',['剧本','小说']); self.combo('reference_method','参考方式',['粘贴文本','导入文件','已有作品','影视案例'])
        if self.kind!='novel': self.combo('format','形式',['短剧','短片','连续剧单集','电影片段','广告剧情','口播情景','舞台片段'])
        if self.kind!='script': self.combo('length','篇幅',['微小说','短篇小说','中篇小说','长篇连载'])
        genre=QComboBox(); genre.addItem('自由创作','auto')
        for r in registry.of('genre'): genre.addItem(r['label'],r['id'])
        genre.currentIndexChanged.connect(self.genre_changed); self.add_field('genre','赛道',genre)
        sub=MultiChoice(); sub.changed.connect(self.config_changed); self.add_field('subgenres','细分方向',sub)
        if self.kind!='novel':
            self.combo('duration_label','目标时长',['30秒','60秒','90秒','2分钟','3分钟','5分钟','10分钟','自定义'])
            self.spin('minutes','分钟',0,180,3); self.spin('seconds','秒',0,59,0)
            self.combo('mode','创作模式',['纯剧情','剧情带货','口播带货','同城探店','文旅宣传','品牌故事'])
            self.combo('density','台词密度',['少台词','均衡','高密度','台词主导','自定义']); self.spin('ratio','对白占比 %',10,90,50)
            obj=QLineEdit(); obj.setPlaceholderText('例如：保温杯'); obj.textChanged.connect(self.config_changed); self.add_field('object','对象名称',obj)
            extra=QLineEdit(); extra.setPlaceholderText('可填写卖点、受众或必须保留的话，不填也能生成'); extra.textChanged.connect(self.config_changed); self.add_field('supplemental','补充信息',extra)
            self.combo('commerce_style','带货方式',['自动','痛点解决','反差','误会','喜剧','情绪','悬疑','职场','家庭','场景种草','对比讲解','使用演示'])
            self.combo('marketing','营销结尾强度',['不引导','轻引导','明确引导'])
        if self.kind!='script':
            self.spin('words','目标字数',1,1000000,3000); self.spin('chapters','计划章节',1,1000,30); self.spin('chapter_words','每章字数',1,50000,2500)
            self.combo('perspective','叙事视角',['自动','第一人称','第三人称限知','第三人称全知','多视角'])
            self.combo('language','语言风格',[r['label'] for r in registry.of('language')]+['自定义…'])
        if self.kind=='rewrite':
            self.combo('rewrite_level','改写程度',['轻度调整','结构仿写','跨题材重构'])
            for key,title,values in [('keep','保留重点',['核心观点','事件因果','情绪曲线','节奏结构','人物关系','高潮机制','结局方向','台词含义']),('change','改变内容',['人物身份','时代背景','地点环境','核心事件','冲突成因','表达方式','结尾']),('emphasis','输出侧重',['更有冲突','更有反转','台词更自然','更高信息密度','更有画面','更短','更完整','更适合带货'])]:
                w=MultiChoice([(v,v) for v in values]); w.set_values(self.config[key]); w.changed.connect(self.config_changed); self.add_field(key,title,w)
    def build_advanced(self):
        if self.kind=='script':
            self.advanced_cells={}; self.advanced_extras={}; return
        registry=self.owner.registry; self.advanced_cells={}; self.advanced_extras={}
        for tab,fields in ADVANCED.items():
            area=QScrollArea(); area.setWidgetResizable(True); page=QWidget(); page.setObjectName('detailPage'); form=QGridLayout(page); form.setSpacing(10)
            if self.kind=='script': form.setContentsMargins(0,6,0,0); form.setHorizontalSpacing(16)
            for index,(name,values) in enumerate(fields.items()):
                rows=[(v,v) for v in values]
                if name=='融合赛道': rows=[(r['id'],r['label']) for r in registry.of('genre')]
                if name in {'结构公式','辅助机制'}: rows=[(r['id'],r['label']) for r in registry.of('formula')]
                if name=='情绪标签': rows=[(r['id'],r['label']) for r in registry.of('emotion')]
                if name=='台词风格': rows=[(r['id'],r['label']) for r in registry.of('dialogue')]
                cell=QWidget(); cell.setObjectName('fieldCell'); col=QVBoxLayout(cell); col.setContentsMargins(0,0,0,0); col.setSpacing(4); col.addWidget(label(name,'muted'))
                if name in {'必须保留','不要出现','参考作品'}:
                    w=QLineEdit(); w.setMaxLength(500); w.setPlaceholderText('输入你的要求'); w.textChanged.connect(self.config_changed)
                elif name in {'融合赛道','情绪标签','台词风格','反转','冲突','高潮机制','关系','爽点','内容边界','借鉴部分'}:
                    w=MultiChoice(rows,2 if name=='融合赛道' else None); w.changed.connect(self.config_changed)
                else:
                    w=QComboBox(); w.addItem('自动','auto')
                    for value,text in rows: w.addItem(text,value)
                    w.addItem('自定义…','custom'); custom=QLineEdit(); custom.setPlaceholderText('输入你的要求'); custom.setMaxLength(500); custom.hide(); custom.textChanged.connect(self.config_changed); self.advanced_custom[name]=custom
                    w.currentIndexChanged.connect(lambda _,w=w,custom=custom:custom.setVisible(w.currentData()=='custom'))
                    w.currentIndexChanged.connect(self.config_changed)
                col.addWidget(w)
                if name in self.advanced_custom: col.addWidget(self.advanced_custom[name])
                cell.setMaximumWidth(16777215 if self.kind=='script' else 320); cell.setMinimumWidth(130); w.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed); self.advanced_cells[name]=cell; self.advanced_fields[name]=w; form.addWidget(cell,index//2,index%2)
            if tab=='台词':
                self.speed=QDoubleSpinBox(); self.speed.setRange(2,7); self.speed.setValue(4.5); self.speed.setSingleStep(.5); self.speed.valueChanged.connect(self.config_changed); form.addWidget(label('自定义语速（字/秒）','muted')); form.addWidget(self.speed)
                self.line_min=QSpinBox(); self.line_min.setRange(1,1000); self.line_min.setValue(1); self.line_max=QSpinBox(); self.line_max.setRange(1,1000); self.line_max.setValue(30)
                self.line_min.valueChanged.connect(self.config_changed); self.line_max.valueChanged.connect(self.config_changed); form.addWidget(self.line_min); form.addWidget(self.line_max)
            if tab=='情绪':
                form.addWidget(button('调整情绪顺序',self.emotion_order,quiet=True))
            if self.kind=='script':
                self.advanced_extras[tab]=[form.itemAt(i).widget() for i in range(form.count()) if form.itemAt(i).widget() not in self.advanced_cells.values()]
                self.advanced.addTab(page,tab)
            else:
                form.addWidget(button('恢复自动',self.reset_advanced,quiet=True)); form.addWidget(button('收起',self.toggle_advanced,quiet=True)); area.setWidget(page); self.advanced.addTab(area,tab)
    def emotion_order(self):
        values=self.advanced_fields['情绪标签'].values
        if len(values)>1:
            # Popup reorders by selecting a chosen item to move it earlier.
            menu=QMenu(self)
            for rid in values: menu.addAction('移到最前：'+self.owner.registry.by_id[rid]['label'],lambda _checked=False,rid=rid:self.reorder_emotion(rid))
            menu.exec(self.advanced_toggle.mapToGlobal(self.advanced_toggle.rect().bottomLeft()))
    def reorder_emotion(self,rid):
        w=self.advanced_fields['情绪标签']; w.set_values([rid]+[v for v in w.values if v!=rid]); self.config_changed()
    def genre_changed(self):
        genre=self.fields['genre'].currentData(); self.fields['subgenres'].set_rows([(r['id'],r['label']) for r in self.owner.registry.of('subgenre') if r.get('parent')==genre]); self.config_changed()
    def read_config(self):
        if self.kind=='script' and hasattr(self,'script_form'): return self.script_form.read_config(self.config)
        c=json.loads(json.dumps(self.config,ensure_ascii=False))
        for key,w in self.fields.items():
            if isinstance(w,MultiChoice): c[key]=w.values.copy()
            elif isinstance(w,QComboBox): c[key]=self.custom_inputs[key].text() if w.currentText()=='自定义…' and key in self.custom_inputs else w.currentText()
            elif isinstance(w,QSpinBox): c[key]=w.value()
            else: c[key]=w.text()
        c['genre']=self.fields['genre'].currentData(); c['output']='novel' if self.kind=='novel' or self.kind=='rewrite' and self.fields['output'].currentText()=='小说' else 'script'
        if 'duration_label' in self.fields:
            c['duration']={'30秒':30,'60秒':60,'90秒':90,'2分钟':120,'3分钟':180,'5分钟':300,'10分钟':600}.get(c['duration_label'],c.get('minutes',3)*60+c.get('seconds',0))
            c['dialogue_ratio']={'少台词':.325,'均衡':.50,'高密度':.675,'台词主导':.8}.get(c['density'],c['ratio']/100)
        c['advanced']={}
        for name,w in self.advanced_fields.items():
            v=w.values.copy() if isinstance(w,MultiChoice) else w.currentData() if isinstance(w,QComboBox) else w.text()
            if v=='custom': v='custom:'+self.advanced_custom[name].text()
            if v and v!='auto': c['advanced'][name]=v
        speed=c['advanced'].get('台词速度'); c['speech_speed']={'舒缓':3,'自然':4.5,'快速':5.5}.get(speed,self.speed.value())
        if c['advanced'].get('台词数量')=='指定范围': c['advanced']['台词数量']=f'{self.line_min.value()}–{self.line_max.value()}句'
        c['idea']=self.idea.toPlainText(); c['reference']=self.reference.toPlainText(); return c
    def config_changed(self,*_,reflow=True):
        if self.loading or not hasattr(self,'idea'): return
        if self.kind=='script' and hasattr(self,'script_form') and self.script_form.loading: return
        old_length=self.config.get('length'); self.config=self.read_config()
        if self.config['length']!=old_length and self.config['length']!='长篇连载' and 'words' in self.fields:
            self.fields['words'].blockSignals(True); self.fields['words'].setValue({'微小说':800,'短篇小说':3000,'中篇小说':20000}.get(self.config['length'],3000)); self.fields['words'].blockSignals(False); self.config=self.read_config()
        if reflow and self.kind!='script': self.reflow()
        if self.kind=='script' and hasattr(self,'draft_timer'):
            self.owner.options['draft:'+self.kind]=self.config
            work=self.owner.works.get(self.kind)
            if work: work.config=self.config
            self.saved.setText('保存中'); self.draft_timer.start(250)
        else: self.owner.save_page_draft(self)
    def flush_draft(self):
        if hasattr(self,'draft_timer'): self.draft_timer.stop()
        try: self.owner.save_page_draft(self)
        except (OSError,RuntimeError,ValueError): self.saved.setText('保存失败'); raise
        self.saved.setText('已保存' if self.owner.works.get(self.kind) else '草稿已保存')
    def reflow(self):
        if self.kind=='script': self.reflow_script(); return
        output=self.config.get('output','script'); novel=output=='novel'; mode=self.config.get('mode','纯剧情'); duration=self.config.get('duration_label','3分钟'); density=self.config.get('density','均衡')
        expanded=not self.advanced.isHidden()
        self.form_scroll.setVisible(not expanded); self.selection_summary.setVisible(expanded)
        self.advanced.setFixedHeight(max(220,min(320,round(self.height()*.42))))
        columns=max(2,min(4,(self.width()-48)//180))
        visible=[]
        for key,cell in self.form_labels:
            show=True
            if key in {'format','duration_label','mode','density'}: show=not novel
            if key in {'length','words','chapters','chapter_words','perspective','language'}: show=novel and (key not in {'chapters','chapter_words'} or self.config.get('length')=='长篇连载') and (key!='words' or self.config.get('length')!='长篇连载')
            if key in {'object','supplemental','marketing'}: show=not novel and mode!='纯剧情'
            if key=='commerce_style': show=not novel and '带货' in mode
            if key in {'minutes','seconds'}: show=not novel and duration=='自定义'
            if key=='ratio': show=not novel and density=='自定义'
            self.grid.removeWidget(cell)
            if show: visible.append(cell)
            else: cell.hide()
        for i,cell in enumerate(visible): self.grid.addWidget(cell,i//columns,i%columns); cell.show()
        rows=(len(visible)+columns-1)//columns
        self.form_scroll.setFixedHeight(min(rows,3)*70+4)
        genre=self.owner.registry.by_id.get(self.config.get('genre'),{}).get('label','自由创作')
        self.selection_summary.setText('当前选择：'+genre+' · '+(str(self.config.get('words',3000))+'字' if novel else str(self.config.get('duration',180))+'秒')+' · 基础选择已保留')
        if hasattr(self,'directory'): self.directory.setVisible(novel); self.next_button.setVisible(novel and self.config.get('length')=='长篇连载'); self.generate_button.setText('生成本章' if novel and self.config.get('length')=='长篇连载' else self.generate_text())
    def resizeEvent(self,event): super().resizeEvent(event); self.reflow()
    def toggle_advanced(self):
        if self.kind=='script' and hasattr(self,'script_form'): self.script_form.toggle_more(); return
        opened=self.advanced.isHidden(); self.advanced.setVisible(opened); self.advanced_toggle.setChecked(opened); self.advanced_toggle.setText('返回基础选择 ▴' if opened else '更多选择 ▾')
        if opened and self.kind=='rewrite': self.reference.hide(); self.ref_fold.setText('展开参考内容')
        self.reflow()
    def reset_advanced(self):
        if self.kind=='script' and hasattr(self,'script_form'): self.script_form.reset_tab(); return
        old_config=self.read_config()
        for w in self.advanced_fields.values():
            w.blockSignals(True)
            if isinstance(w,MultiChoice): w.set_values([])
            elif isinstance(w,QComboBox): w.setCurrentIndex(0)
            else: w.clear()
            w.blockSignals(False)
        self.speed.setValue(4.5); self.config_changed(); self.notify('高级选择已恢复为自动')
        def restore(): self.load_config(old_config); self.config_changed(); self.notify('已撤销高级选择重置')
        self.owner.offer_undo('高级选择已恢复为自动',restore)
    def fold_reference(self):
        if self.reference.isHidden() and not self.advanced.isHidden():
            self.advanced.hide(); self.advanced_toggle.setChecked(False); self.advanced_toggle.setText('更多选择 ▾'); self.reflow()
        self.reference.setVisible(not self.reference.isVisible()); self.ref_fold.setText('参考内容' if self.reference.isVisible() else f'已导入参考 · 约{len(self.reference.toPlainText())}字')
    def load_config(self,c):
        if self.kind=='script' and hasattr(self,'script_form'):
            self.loading=True; self.script_form.load(c); self.loading=False; self.restore_ui_state(); self.reflow(); return
        self.loading=True; self.config=c
        for key,w in self.fields.items():
            if key=='genre': w.setCurrentIndex(max(0,w.findData(c.get(key,'auto'))))
            elif isinstance(w,MultiChoice): w.set_values(c.get(key,[]))
            elif isinstance(w,QComboBox):
                value='小说' if key=='output' and c.get('output')=='novel' else '剧本' if key=='output' else str(c.get(key,w.currentText()))
                if key in self.custom_inputs and w.findText(value)<0: w.setCurrentText('自定义…'); self.custom_inputs[key].setText(value)
                else: w.setCurrentText(value)
            elif isinstance(w,QSpinBox): w.setValue(c.get(key,w.value()))
            else: w.setText(c.get(key,''))
        self.fields['subgenres'].set_rows([(r['id'],r['label']) for r in self.owner.registry.of('subgenre') if r.get('parent')==c.get('genre')]); self.fields['subgenres'].set_values(c.get('subgenres',[]))
        for name,w in self.advanced_fields.items():
            value=c.get('advanced',{}).get(name,[] if isinstance(w,MultiChoice) else '')
            if isinstance(w,MultiChoice): w.set_values(value)
            elif isinstance(w,QComboBox):
                if isinstance(value,str) and value.startswith('custom:') and name in self.advanced_custom: w.setCurrentIndex(w.findData('custom')); self.advanced_custom[name].setText(value[7:])
                else: w.setCurrentIndex(max(0,w.findData(value)))
            else: w.setText(value)
        self.idea.setPlainText(c.get('idea','')); self.reference.setPlainText(c.get('reference','')); self.loading=False; self.reflow()
    def edited(self):
        if self.owner.loading: return
        self.owner.editor_changed(self)
        if self.kind=='script': self.refresh_empty_state()
    def rename(self):
        if self.owner.work and self.owner.current_page()==self: self.owner.work.store.update_project(name=self.title.text().strip() or '未命名'+self.type_name())
    def show_work(self,work):
        self.load_config(work.config); self.title.setText(work.store.metadata()['name']); self.owner.loading=True; self.editor.setPlainText(work.text)
        if self.kind=='script' and work.store.setting('v2_third_unsynced:'+work.document_id,False): self.notify('完整手改草稿已恢复，正文／台词尚未对应。作品菜单可选择保留草稿或明确重建台词。')
        from PySide6.QtGui import QTextBlockFormat
        cursor=self.editor.textCursor(); fmt=QTextBlockFormat(); fmt.setLineHeight(170,QTextBlockFormat.LineHeightTypes.ProportionalHeight.value); cursor.select(QTextCursor.SelectionType.Document); cursor.mergeBlockFormat(fmt); self.editor.document().clearUndoRedoStacks(); self.owner.loading=False
        self.refresh_documents(work); last=work.store.setting('v2_location:'+work.document_id,{})
        cursor=self.editor.textCursor(); cursor.setPosition(min(last.get('cursor',0),len(work.text))); self.editor.setTextCursor(cursor); self.editor.verticalScrollBar().setValue(last.get('scroll',0))
        if hasattr(self,'editor_toolbar'): self.editor_toolbar.refresh(); self.editor_footer.refresh()
    def refresh_documents(self,work):
        self.location.blockSignals(True); self.location.clear(); self.chapters.clear()
        documents=work.store.documents()
        documents.sort(key=lambda d:(d['kind']!='outline',d['position']))
        for d in documents:
            if d['kind']=='reference': continue
            self.location.addItem(d['title'],d['id']); self.chapters.addItem(d['title']+' · '+('已完成' if d['status']=='confirmed' else '草稿' if work.store.document(d['id'])['text'] else '未写')); self.chapters.item(self.chapters.count()-1).setData(Qt.ItemDataRole.UserRole,d['id'])
        selected=max(0,self.location.findData(work.document_id)); self.location.setCurrentIndex(selected); self.chapters.setCurrentRow(selected); self.location.blockSignals(False)
        if self.kind=='script': self.refresh_empty_state()
    def refresh_empty_state(self):
        content=bool(self.editor.toPlainText().strip()); self.cover_button.setEnabled(content); self.export_button.setEnabled(content)
        for w in (self.cover_button,self.export_button): w.setToolTip('' if content else '先生成或导入正文')
        if not content and not self.location.count(): self.location.blockSignals(True); self.location.addItem('暂无正文',None); self.location.blockSignals(False)
        elif not content and self.location.count()==1: self.location.setItemText(0,'暂无正文')
        self.location.setEnabled(content or self.location.count()>1)
    def change_document(self):
        if not self.owner.loading and self.location.currentData(): self.owner.run(lambda:self.owner.select_document(self.location.currentData()))
    def toggle_directory(self): self.chapters.setVisible(not self.chapters.isVisible())
    def notify(self,text):
        self.banner.setText(text)
        if hasattr(self.banner,'set_busy'): self.banner.set_busy(bool(self.owner.active_task and self.owner.active_task['page'] is self))
        if hasattr(self.banner,'sync_visibility'): self.banner.sync_visibility()
        else: self.banner.setVisible(bool(text))
    def editor_menu(self):
        menu=QMenu(self); menu.addAction('查找',self.show_find); undo=menu.addAction('撤销',self.editor.undo); undo.setEnabled(self.editor.document().isUndoAvailable()); redo=menu.addAction('重做',self.editor.redo); redo.setEnabled(self.editor.document().isRedoAvailable()); menu.exec(self.editor.mapToGlobal(self.editor.rect().topRight()))
    def show_find(self):
        if self.kind=='script': self.set_view(1)
        self.find_row.show(); self.find.setFocus()
    def export_menu(self):
        menu=QMenu(self); menu.addAction('Markdown',lambda:self.owner.run(lambda:self.owner.export_work('md'))); menu.addAction('纯文本',lambda:self.owner.run(lambda:self.owner.export_work('txt')))
        if self.config.get('output')=='novel': menu.addAction('整本小说 Markdown',lambda:self.owner.run(lambda:self.owner.export_work('md',whole_book=True)))
        menu.ensurePolished()
        anchor=self.export_button.mapToGlobal(self.export_button.rect().bottomRight())
        anchor.setX(anchor.x()-menu.sizeHint().width()+1); anchor.setY(anchor.y()+5)
        menu.exec(anchor)
    def context_menu(self,pos):
        menu=QMenu(self); menu.addAction('复制',self.editor.copy); menu.addAction('剪切',self.editor.cut); menu.addAction('粘贴',self.editor.paste)
        menu.addAction('让AI修改所选内容',self.bind_selection); menu.addAction('锁定所选内容',lambda:self.owner.run(self.owner.lock_selection)); menu.addAction('解除锁定',lambda:self.owner.run(self.owner.unlock_selection)); menu.exec(self.editor.mapToGlobal(pos))
    def bind_selection(self):
        from app.ui.v2_window import py_position
        cursor=self.editor.textCursor(); text=self.editor.toPlainText(); self.owner.bound_selection=(py_position(text,cursor.selectionStart()),py_position(text,cursor.selectionEnd())); self.owner.assistant.scope.setText(f'已选择{len(cursor.selectedText())}字 · 点击取消'); self.owner.assistant.scope.show()
        self.owner.options['assistant_collapsed']=False; self.owner.set_assistant_visible(True); self.owner.save_options(); self.owner.assistant.input.setFocus()
