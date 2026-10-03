"""The approved script form: one owner per semantic field and current-tab height."""
import copy
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import QWidget,QFrame,QVBoxLayout,QHBoxLayout,QGridLayout,QLineEdit,QTabBar,QStackedWidget,QSizePolicy,QMenu,QTextEdit,QCompleter
from app.ui.v2_widgets import label,button,QComboBox,MultiChoice,QMenu
from app.core.script_settings import CATALOG,DETAILS,TITLES,BY_ID,CATALOG_STATE,reload_catalog,LANGUAGE_SOURCES,migrate,adapt,validate_script,budget,carrier_fields,label as option_label

class ChipChoice(QWidget):
    changed=Signal()
    def __init__(self, rows):
        super().__init__(); self.control=MultiChoice(rows); self.expanded=False
        col=QVBoxLayout(self); col.setContentsMargins(0,0,0,0); col.setSpacing(3); col.addWidget(self.control)
        self.chips=QWidget(); self.chip_row=QHBoxLayout(self.chips); self.chip_row.setContentsMargins(0,0,0,0); self.chip_row.setSpacing(3); col.addWidget(self.chips)
        self.control.changed.connect(self.update_chips); self.control.changed.connect(self.changed)
    @property
    def values(self): return self.control.values
    @property
    def rows(self): return self.control.rows
    def set_rows(self, rows): self.control.set_rows(rows); self.update_chips()
    def set_values(self, values): self.control.set_values(values); self.update_chips()
    def remove(self, value): self.set_values([v for v in self.values if v!=value]); self.changed.emit()
    def expand_selected(self):
        menu=QMenu(self)
        for value in self.values: menu.addAction('移除：'+dict(self.rows).get(value,value),lambda _checked=False,v=value:self.remove(v))
        menu.popup(self.control.mapToGlobal(self.control.rect().bottomLeft()))
    def update_chips(self):
        # The summary stays one line; removal/order actions are opened explicitly.
        self.chips.hide()
    def resizeEvent(self,event): super().resizeEvent(event); self.update_chips()

class StableTabBar(QTabBar):
    def wheelEvent(self,event):
        # Tabs are explicit navigation; scrolling never changes their selection.
        event.accept()

class CurrentTabs(QWidget):
    currentChanged=Signal(int)
    def __init__(self):
        super().__init__(); self.setObjectName('detailPage'); col=QVBoxLayout(self); col.setContentsMargins(0,0,0,0); col.setSpacing(8)
        self.bar=StableTabBar(); self.bar.setExpanding(True); self.bar.setUsesScrollButtons(False); self.stack=QStackedWidget(); self.stack.setObjectName('detailPage'); col.addWidget(self.bar); col.addWidget(self.stack)
        self.bar.currentChanged.connect(self.change); self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
    def addTab(self,page,title): self.stack.addWidget(page); self.bar.addTab(title)
    def change(self,index): self.stack.setCurrentIndex(index); self.currentChanged.emit(index)
    def currentIndex(self): return self.bar.currentIndex()
    def setCurrentIndex(self,index): self.bar.setCurrentIndex(index)
    def currentWidget(self): return self.stack.currentWidget()
    def widget(self,index): return self.stack.widget(index)
    def count(self): return self.stack.count()
    def tabBar(self): return self.bar
    def fit(self):
        page=self.currentWidget()
        if page:
            page.layout().invalidate(); page.layout().activate(); height=page.layout().sizeHint().height()
            if self.stack.height()!=height: self.stack.setFixedHeight(height)
            target=height+self.bar.sizeHint().height()+8
            if self.height()!=target: self.setFixedHeight(target)

class ScriptSettings(QWidget):
    def __init__(self,page):
        super().__init__(page); self.page=page; self.loading=True; self.state=migrate(page.config,new=True)['script_settings']; self.fields={}; self.cells={}; self.custom={}; self.custom_cells={}; self.parent_previous={}; self.grids=[]; self.available_roles=[]; self.grid_signatures={}; self.columns=3; self._reflowing=False; self._visible_cells=set(); self._visible_custom=set()
        self.field_errors={}; self.layout_timer=QTimer(self); self.layout_timer.setSingleShot(True); self.layout_timer.timeout.connect(self.reflow)
        self.fit_timer=QTimer(self); self.fit_timer.setSingleShot(True); self.fit_timer.timeout.connect(self.fit_cards)
        col=QVBoxLayout(self); col.setContentsMargins(0,0,0,0); col.setSpacing(16)
        self.catalog_error=QWidget(); error_col=QVBoxLayout(self.catalog_error); error_col.setContentsMargins(0,0,0,0)
        self.catalog_message=label('','muted'); error_col.addWidget(self.catalog_message)
        self.catalog_retry=button('重试读取规则目录',self.retry_catalog); error_col.addWidget(self.catalog_retry); col.addWidget(self.catalog_error)
        self.basic_card,basic=self.card('基本方向'); col.addWidget(self.basic_card)
        self.basic_grid=QGridLayout(); self.basic_grid.setHorizontalSpacing(16); self.basic_grid.setVerticalSpacing(12); basic.addLayout(self.basic_grid)
        for key in ['form','genre','subgenres','duration_label','mode','language','custom_seconds','form_detail','object','supplemental','strategy','cta','sources','delivery']:
            self.make(key)
        self.basic_more=button('补充设置 ▾',self.toggle_basic_more,quiet=True); self.basic_card.header.addWidget(self.basic_more); self.basic_more.setFixedHeight(30); self.basic_expanded=False
        self.basic_required_grid=QGridLayout(); self.basic_required_grid.setHorizontalSpacing(16); self.basic_required_grid.setVerticalSpacing(12); basic.addLayout(self.basic_required_grid)
        self.basic_details=QWidget(); self.basic_details.setObjectName('fieldGrid'); self.basic_details_grid=QGridLayout(self.basic_details); self.basic_details_grid.setContentsMargins(0,0,0,0); self.basic_details_grid.setHorizontalSpacing(16); self.basic_details_grid.setVerticalSpacing(12); basic.addWidget(self.basic_details)
        self.presentation_card,pres=self.card('表现形式'); col.addWidget(self.presentation_card)
        self.presentation_grid=QGridLayout(); self.presentation_grid.setHorizontalSpacing(16); self.presentation_grid.setVerticalSpacing(12); pres.addLayout(self.presentation_grid)
        for key in ['view','carrier','narrative','role','role_detail','role_name','viewer_role','address_role','carrier_item','mixed_sources','recorder','reason','position','switching','call_relation','anchor']:
            self.make(key)
        self.presentation_more=button('细节 ▾',self.toggle_presentation,quiet=True); self.presentation_more.setFixedHeight(30); self.presentation_card.header.addWidget(self.presentation_more); self.presentation_expanded=False
        self.presentation_tabs=CurrentTabs(); self.presentation_grids={}
        for title in ['视角','载体','叙事']:
            body=QWidget(); body.setObjectName('detailPage'); layout=QVBoxLayout(body); layout.setContentsMargins(0,0,0,0); grid=QGridLayout(); grid.setHorizontalSpacing(16); grid.setVerticalSpacing(12); layout.addLayout(grid); self.presentation_grids[title]=grid; self.presentation_tabs.addTab(body,title)
        self.narrative_panel=self.presentation_tabs.widget(2); self.narrative_layout=self.presentation_grids['叙事']
        for key in ['time','info','thread','suspense','reversal','rhetoric']: self.make(key)
        pres.addWidget(self.presentation_tabs); self.presentation_tabs.hide(); self.presentation_tabs.currentChanged.connect(self.presentation_tab_changed)
        self.details_card,details=self.card('剧情细节'); col.addWidget(self.details_card)
        self.tabs=CurrentTabs(); self.tabs.setObjectName('storyDetails'); details.addWidget(self.tabs)
        self.detail_grids={}; self.common={}; self.more={}
        for title,(common,more) in DETAILS.items():
            body=QWidget(); body.setObjectName('detailPage'); layout=QVBoxLayout(body); layout.setContentsMargins(0,0,0,0); layout.setSpacing(8)
            grid=QGridLayout(); grid.setSpacing(12); layout.addLayout(grid)
            for key in common+more: self.make(key)
            self.detail_grids[title]=grid
            if title=='情绪':
                self.order_button=button('调整情绪顺序',self.emotion_order,quiet=True); layout.addWidget(self.order_button)
            if title=='台词':
                self.language_summary=button('语言模式 · 在基本方向修改',self.locate_language,quiet=True); layout.addWidget(self.language_summary)
                self.lock_summary=label('新作品可填写必须保留句子；已有正文可右键锁定实际片段。','muted'); layout.addWidget(self.lock_summary)
            if title=='参考':
                actions=QHBoxLayout(); actions.addWidget(button('导入文件',lambda:page.owner.run(lambda:page.owner.import_reference(page)))); actions.addWidget(button('已有作品',lambda:page.owner.run(lambda:page.owner.choose_reference(page)))); actions.addWidget(button('添加来源',self.add_reference)); actions.addWidget(button('管理来源',self.manage_references,quiet=True)); layout.addLayout(actions)
                self.reference_summary=label('未提供参考也可原创','muted'); layout.addWidget(self.reference_summary)
            self.tabs.addTab(body,title)
        self.more_button=button('更多细节 ▾',self.toggle_more,quiet=True); self.more_button.setFixedHeight(30); self.details_card.header.addWidget(self.more_button)
        self.reset_button=button('恢复本页自动',self.reset_tab,quiet=True); self.reset_button.setFixedHeight(30); self.details_card.header.addWidget(self.reset_button)
        self.notice=label('','muted'); self.notice.hide(); col.addWidget(self.notice)
        self.history_button=button('处理旧设置',self.show_history,quiet=True); self.page.view_header.layout().insertWidget(1,self.history_button); self.history_button.setFixedHeight(28); self.history_button.hide()
        self.tabs.currentChanged.connect(self.tab_changed)
        self.loading=False; self.load(page.config,new=True)
    def card(self,title):
        frame=QFrame(); frame.setObjectName('card'); frame.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        layout=QVBoxLayout(frame); layout.setContentsMargins(16,16,16,16); layout.setSpacing(12)
        header=QHBoxLayout(); heading=label(title,'sectionHeading'); heading.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Fixed); header.addWidget(heading,1); layout.addLayout(header); frame.header=header
        return frame,layout
    def make(self,key):
        if key in self.cells: return
        cell=QWidget(self); cell.setObjectName('fieldCell'); layout=QVBoxLayout(cell); layout.setContentsMargins(0,0,0,0); layout.setSpacing(6); layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        title=CATALOG[key]['title'] if key in CATALOG else TITLES.get(key,dict(duration_label='目标时长',custom_seconds='自定义时长（秒）',object='对象名称／类别／目的',supplemental='补充要求（可选）',narrative='叙事手法').get(key,key))
        caption=label(title,'muted'); caption.setWordWrap(False); caption.setFixedHeight(22); layout.addWidget(caption)
        if key in CATALOG:
            data=CATALOG[key]
            if data['multi']:
                widget=ChipChoice([(r['id'],r['label']) for r in data['rows']]); widget.changed.connect(lambda k=key:self.changed(k))
            else:
                widget=QComboBox(); widget.addItem('自由创作' if key=='genre' else '自动','auto')
                for row in data['rows']:
                    if row['id']=='view.auto': continue
                    widget.addItem(row['label'],row['id']); widget.setItemData(widget.count()-1,row['body'],Qt.ItemDataRole.ToolTipRole)
                widget.addItem('自定义…','custom')
                custom=QLineEdit(); custom.setPlaceholderText('输入具体要求'); custom.setMaxLength(1000000); self.custom[key]=custom; custom.hide(); custom.textChanged.connect(lambda _,k=key:self.text_changed(k)); custom.editingFinished.connect(self.revalidate_after_edit)
                widget.currentIndexChanged.connect(lambda _,k=key:self.changed(k))
        elif key=='duration_label':
            widget=QComboBox(); widget.addItems(['30秒','60秒','90秒','2分钟','3分钟','5分钟','10分钟','自定义']); widget.currentIndexChanged.connect(lambda _:self.changed(key))
        elif key=='narrative': widget=button('自动 · 选择叙事手法 ▾',self.toggle_narrative); widget.setObjectName('narrativeChoice')
        elif key=='reference_content':
            widget=self.page.reference; widget.setFixedHeight(84); widget.show()
        elif key=='form_detail':
            widget=QTextEdit(); widget.setPlaceholderText('系列、集数或前情（可留空）'); widget.setFixedHeight(80); widget.textChanged.connect(lambda k=key:self.text_changed(k))
        else:
            widget=QLineEdit(); widget.setPlaceholderText('自动／可留空'); widget.setMaxLength(1000000); widget.textChanged.connect(lambda _,k=key:self.text_changed(k))
        if key in CATALOG or isinstance(widget,QLineEdit) or key in ('duration_label','narrative'): widget.setFixedHeight(44)
        widget.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed); layout.addWidget(widget)
        if key in self.custom:
            custom_cell=QWidget(self); custom_cell.setObjectName('fieldCell'); custom_cell.hide(); custom_layout=QVBoxLayout(custom_cell); custom_layout.setContentsMargins(0,0,0,0); custom_layout.setSpacing(6); custom_layout.addWidget(label(title+' · 自定义','muted')); self.custom[key].setFixedHeight(44); custom_layout.addWidget(self.custom[key]); self.custom_cells[key]=custom_cell
        self.fields[key]=widget; self.cells[key]=cell; cell.setMinimumWidth(120); cell.hide()
        error_label=label('','error'); error_label.hide(); layout.addWidget(error_label); self.field_errors[key]=error_label
        if isinstance(widget,QLineEdit): widget.editingFinished.connect(self.revalidate_after_edit)
    def value(self,key):
        w=self.fields[key]
        if isinstance(w,ChipChoice): return w.values.copy()
        if isinstance(w,QComboBox):
            if key=='duration_label': return w.currentText()
            return 'custom:'+self.custom[key].text() if w.currentData()=='custom' else w.currentData()
        if isinstance(w,QLineEdit): return w.text()
        if isinstance(w,QTextEdit): return w.toPlainText()
        return None
    def set_value(self,key,value):
        w=self.fields[key]
        if isinstance(w,ChipChoice): w.set_values(value if isinstance(value,list) else [])
        elif isinstance(w,QComboBox):
            if key=='duration_label': w.setCurrentText(str(value or '3分钟'))
            elif str(value).startswith('custom:'): w.setCurrentIndex(w.findData('custom')); self.custom[key].setText(value[7:])
            else: w.setCurrentIndex(max(0,w.findData(value)))
        elif isinstance(w,QLineEdit): w.setText(str(value or ''))
        elif isinstance(w,QTextEdit): w.setPlainText(str(value or ''))
        if key in self.custom: self.custom[key].setVisible(w.currentData()=='custom')
    def parent_change(self,key,child):
        value=self.value(key); old=self.parent_previous.get(key,'auto')
        if old!=value:
            self.state['drafts'].setdefault(child,{})[old]=self.value(child)
            rows=[r for r in CATALOG[child]['rows'] if r.get('parent')==value]
            w=self.fields[child]
            if isinstance(w,ChipChoice): w.set_rows([(r['id'],r['label']) for r in rows])
            else:
                w.blockSignals(True); w.clear(); w.addItem('自动','auto')
                for r in rows: w.addItem(r['label'],r['id'])
                w.addItem('自定义…','custom'); w.blockSignals(False)
            self.loading=True; self.set_value(child,self.state['drafts'].get(child,{}).get(value,[] if isinstance(w,ChipChoice) else 'auto')); self.loading=False
        self.parent_previous[key]=value
    def profile_change(self,key,children):
        old=self.parent_previous.get(key,self.value(key)); new=self.value(key)
        if old!=new:
            drafts=self.state['drafts'].setdefault(key+'_profile',{}); drafts[old]={c:self.value(c) for c in children}
            self.loading=True
            for c in children: self.set_value(c,drafts.get(new,{}).get(c,[] if c in CATALOG and CATALOG[c]['multi'] else 'auto' if c in CATALOG else ''))
            self.loading=False
        self.parent_previous[key]=new
    def changed(self,key,structural=True):
        if self.loading or CATALOG_STATE['kind']: return
        if structural and key in ('genre','carrier','role'): self.parent_change(key,{'genre':'subgenres','carrier':'carrier_item','role':'role_detail'}[key])
        if key=='mode': self.profile_change('mode',['object','supplemental','strategy','cta'])
        if key in ('sources','delivery'):
            self.loading=True; self.set_value('language','language.09'); self.loading=False
        if key=='language':
            self.profile_change('language',['sources','delivery'])
            v=self.value(key)
            if v in LANGUAGE_SOURCES:
                self.loading=True; self.set_value('sources',LANGUAGE_SOURCES[v]); self.loading=False
        self.state['values'].update({k:self.value(k) for k in self.fields if k in CATALOG or k in TITLES and k!='reference_content'})
        if structural and (key in CATALOG or key in ('duration_label','reset','reference')): self.request_layout()
        self.page.config_changed(reflow=False)
    def read_config(self,config):
        c=copy.deepcopy(config); s=copy.deepcopy(self.state)
        if CATALOG_STATE['kind']:
            c['script_settings']=s; c['idea']=self.page.idea.toPlainText(); c['reference']=self.page.reference.toPlainText()
            return c
        s['values'].update({k:self.value(k) for k in self.fields if k in CATALOG or k in TITLES and k!='reference_content'})
        s['role_bindings']={k:[r for r in self.available_roles if r['name'] in [n.strip() for n in __import__('re').split('[、,，\n]',str(s['values'].get(k,'')))]] for k in ['role_name','address_role','anchor','bindings']}
        c['script_settings']=s; c['kind']='script'; c['output']='script'; c['duration_label']=self.value('duration_label'); c['duration_custom_draft']=self.value('custom_seconds')
        try: custom_seconds=float(self.value('custom_seconds') or 180)
        except ValueError: custom_seconds=0
        c['duration']={'30秒':30,'60秒':60,'90秒':90,'2分钟':120,'3分钟':180,'5分钟':300,'10分钟':600}.get(c['duration_label'],custom_seconds)
        c['object']=self.value('object'); c['supplemental']=self.value('supplemental'); c['idea']=self.page.idea.toPlainText(); c['reference']=self.page.reference.toPlainText()
        try: return adapt(c)
        except (ValueError,OverflowError): return c  # Keep an unfinished numeric draft; submission validates it.
    def load(self,config,new=False):
        self.setUpdatesEnabled(False)
        try:
            self.loading=True; c=migrate(config,new=new,legacy_registry=self.page.owner.registry); self.state=c['script_settings']; v=self.state['values']; self.parent_previous={}
            for key in self.fields:
                value=c.get(key,'') if key in ('object','supplemental','duration_label') else c.get('duration_custom_draft',str(c.get('duration',180))) if key=='custom_seconds' else v.get(key,[] if key in CATALOG and CATALOG[key]['multi'] else 'auto' if key in CATALOG else '')
                self.set_value(key,value)
            for key,child in [('genre','subgenres'),('carrier','carrier_item'),('role','role_detail')]:
                rows=[r for r in CATALOG[child]['rows'] if r.get('parent')==self.value(key)]
                w=self.fields[child]
                if isinstance(w,ChipChoice): w.set_rows([(r['id'],r['label']) for r in rows]); self.set_value(child,v.get(child,[]))
                else:
                    w.blockSignals(True); w.clear(); w.addItem('自动','auto')
                    for r in rows: w.addItem(r['label'],r['id'])
                    w.addItem('自定义…','custom'); self.set_value(child,v.get(child,'auto')); w.blockSignals(False)
                self.parent_previous[key]=self.value(key)
            self.parent_previous['mode']=self.value('mode'); self.parent_previous['language']=self.value('language')
            self.available_roles=[]; work=getattr(self.page.owner,'work',None)
            if work and work.config.get('kind')=='script':
                with work.store.connection() as con: roles=[dict(id=r['id'],name=r['name'],source='项目人物') for r in con.execute('SELECT id,name FROM entities WHERE kind IN (\'character\',\'人物\',\'角色\')')]
                speakers=work.store.setting('v2_payload:'+work.document_id,{}).get('payload',{}).get('speakers',{})
                roles += [dict(id=rid,name=name,source='当前剧本人物') for name,rid in speakers.items() if name not in [r['name'] for r in roles]]
                self.available_roles=roles
                for key in ['role_name','address_role','anchor','bindings']:
                    completer=QCompleter([r['name'] for r in roles],self.fields[key]); completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive); self.fields[key].setCompleter(completer)
            self.page.reference.setPlainText(c.get('reference','')); self.page.idea.setPlainText(c.get('idea','')); self.loading=False; self.page.config=c; self.reflow()
        finally:
            self.setUpdatesEnabled(True)
            self.loading=False
    def layout_cells(self,grid,keys,columns):
        full=set('form_detail object supplemental position reason switching call_relation anchor emotion_beats required_lines banned_lines reference_name retain alter exclude reference_custom style_custom immutable reference_content'.split())
        custom=tuple(k for k in keys if k in self.custom and self.fields[k].currentData()=='custom')
        signature=(tuple(keys),columns,custom)
        self._wanted_cells.update(keys); self._wanted_custom.update(custom)
        if self.grid_signatures.get(grid)==signature: return False
        while grid.count(): grid.takeAt(0)
        row=0; column=0; row_custom=[]
        def custom_rows():
            nonlocal row,row_custom
            for key in row_custom:
                grid.addWidget(self.custom_cells[key],row,0,1,columns,Qt.AlignmentFlag.AlignTop); row+=1
            row_custom=[]
        for key in keys:
            span=columns if key in full else 1
            if span==columns and column:
                row+=1; column=0; custom_rows()
            # Reparent into the layout before ever showing a field.
            grid.addWidget(self.cells[key],row,column,1,span,Qt.AlignmentFlag.AlignTop)
            if key in custom: row_custom.append(key)
            column+=span
            if column>=columns: row+=1; column=0; custom_rows()
        if column: row+=1; custom_rows()
        for i in range(3): grid.setColumnStretch(i,1 if i<columns else 0)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop); self.grid_signatures[grid]=signature
        return True

    def request_layout(self):
        if not self.loading and not self.layout_timer.isActive(): self.layout_timer.start(0)

    def text_changed(self,key): self.changed(key,structural=False)
    def revalidate_after_edit(self):
        if not self.loading and any(not message.isHidden() for message in self.field_errors.values()): self.validate_fields(locate=False)
    def validate_fields(self,locate=True):
        for message in self.field_errors.values(): message.hide()
        for widget in self.fields.values(): widget.setProperty('error',False); widget.style().unpolish(widget); widget.style().polish(widget)
        try: warnings=validate_script(self.page.read_config())
        except (ValueError,OverflowError) as exc:
            message=str(exc); self.notice.setObjectName('error'); self.notice.setText(message); self.notice.show()
            keys=[]
            if '时长' in message: keys.append('custom_seconds' if self.value('duration_label')=='自定义' else 'duration_label')
            if '对象' in message: keys.append('object')
            for key,widget in self.fields.items():
                if key in CATALOG and CATALOG[key]['title'] in message: keys.append(key)
            for key in keys:
                widget=self.fields[key]; widget.setProperty('error',True); widget.style().unpolish(widget); widget.style().polish(widget)
                self.field_errors[key].setText(message); self.field_errors[key].show()
            if keys: self.notice.hide()
            self.fit_cards()
            if keys and locate:
                key=keys[0]
                if key not in self._visible_cells:
                    for i,(common,more) in enumerate(DETAILS.values()):
                        if key in common+more: self.tabs.setCurrentIndex(i); self.state['expanded'][list(DETAILS)[i]]=key in more
                    if key in ['density_custom','speed_custom']: self.tabs.setCurrentIndex(3); self.state['expanded']['台词']=True
                    self.reflow()
                self.page.settings_scroll.ensureWidgetVisible(self.cells[key]); self.fields[key].setFocus()
            return False
        self.notice.setObjectName('muted'); self.notice.setText('；'.join(warnings)); self.notice.setVisible(bool(warnings)); self.fit_cards(); return True

    def reflow(self):
        if self._reflowing: return
        self._reflowing=True
        try:
            margins=self.page.settings_layout.contentsMargins()
            width=self.page.settings_scroll.viewport().width()-margins.left()-margins.right()-32
            if self.columns==3 and width<696: self.columns=2 if width>=456 else 1
            elif self.columns==2:
                if width>=720: self.columns=3
                elif width<456: self.columns=1
            elif self.columns==1 and width>=480: self.columns=3 if width>=720 else 2
            columns=self.columns; self._wanted_cells=set(); self._wanted_custom=set()
            scroll=self.page.settings_scroll.verticalScrollBar(); old_scroll=scroll.value()
            focus=__import__('PySide6.QtWidgets',fromlist=['QApplication']).QApplication.focusWidget()
            anchor=focus if focus and self.isAncestorOf(focus) and focus.window() is self.window() and focus.isVisible() else None
            old_y=anchor.mapTo(self.page.settings_scroll.widget(),anchor.rect().topLeft()).y() if anchor else None
            changed=self.layout_cells(self.basic_grid,['form','genre','subgenres','duration_label','mode','language'],columns)
            required=[]
            if self.value('duration_label')=='自定义': required.append('custom_seconds')
            if self.value('mode') not in ('auto','mode.01'): required.append('object')
            changed|=self.layout_cells(self.basic_required_grid,required,columns)
            basic=[]
            if self.basic_expanded:
                if self.value('form') in ('form.01','form.03'): basic.append('form_detail')
                if self.value('mode') not in ('auto','mode.01'): basic+=['supplemental','strategy']+([] if self.tabs.currentIndex()==0 and self.value('ending')=='ending.06' else ['cta'])
                if self.value('language')=='language.09': basic+=['sources','delivery']
            changed|=self.layout_cells(self.basic_details_grid,basic,columns); self.basic_details.setVisible(bool(basic))
            count=sum(bool(self.state['values'].get(k)) for k in ['form_detail','supplemental','strategy','cta'])
            self.basic_more.setText(('收起补充 ▴' if self.basic_expanded else '补充设置 ▾')+(f' · 已设{count}项' if count and not self.basic_expanded else ''))
            automatic=self.value('genre')=='auto'; sub=self.fields['subgenres']; sub.control.refresh()
            if automatic: sub.control.setText('由 AI 自动选择')
            sub.setToolTip('自由创作由 AI 选择题材；选择主赛道后可多选细分' if automatic else '')
            changed|=self.layout_cells(self.presentation_grid,['view','carrier','narrative'],columns)
            pres_title=['视角','载体','叙事'][self.presentation_tabs.currentIndex()]; view=self.value('view'); pres=[]
            if self.presentation_expanded:
                if pres_title=='视角':
                    if view in ('view.subjective','view.follow','view.observer','view.multiple'): pres+=['role','role_detail','role_name']
                    if view=='view.address' or self.value('language')=='language.06': pres+=['viewer_role','address_role']
                elif pres_title=='载体': pres=carrier_fields({k:self.value(k) for k in ['carrier','carrier_item','mixed_sources']})
                else: pres=['time','info','thread','suspense','reversal','rhetoric','anchor']
            for title,grid in self.presentation_grids.items(): changed|=self.layout_cells(grid,pres if title==pres_title else [],columns)
            self.presentation_tabs.setVisible(self.presentation_expanded)
            self.presentation_more.setText('收起细节 ▴' if self.presentation_expanded else '细节 ▾')
            narrative=[option_label(v) for k in ['time','info','thread','suspense','reversal','rhetoric'] for v in self.value(k)]
            self.fields['narrative'].setText((' · '.join(narrative[:2])+(' …' if len(narrative)>2 else '')) if narrative else '自动 · 选择叙事手法')
            self.fields['narrative'].setToolTip(' → '.join(narrative))
            title=list(DETAILS)[self.tabs.currentIndex()]; common,more=DETAILS[title]; expanded=self.state['expanded'].get(title,False)
            keys=common+more if expanded else common[:]
            if title=='故事' and self.value('ending')=='ending.06': keys+=['cta']
            if title=='台词':
                if self.value('language')=='language.08': keys=[k for k in keys if k in ('required_lines','banned_lines')]
                if not str(self.value('density')).startswith('custom:'): keys=[k for k in keys if k!='density_custom']
                if not str(self.value('speed')).startswith('custom:'): keys=[k for k in keys if k!='speed_custom']
                if not set(LANGUAGE_SOURCES.get(self.value('language'),self.value('sources'))) >= {'sources.01','sources.02'}: keys=[k for k in keys if k!='narration_ratio']
                self.language_summary.setText('语言模式：'+option_label(self.value('language'))+' · 在基本方向修改')
            for tab,grid in self.detail_grids.items(): changed|=self.layout_cells(grid,keys if tab==title else [],columns)
            for key in self._visible_cells-self._wanted_cells: self.cells[key].hide()
            for key in self._wanted_cells-self._visible_cells: self.cells[key].show()
            for key in self._visible_custom-self._wanted_custom: self.custom_cells[key].hide()
            for key in self._wanted_custom-self._visible_custom: self.custom[key].show(); self.custom_cells[key].show()
            self._visible_cells=self._wanted_cells; self._visible_custom=self._wanted_custom
            self.order_button.setVisible(title=='情绪' and expanded); self.more_button.setText('收起细节 ▴' if expanded else '更多细节 ▾')
            refs=self.state.get('references',[]); self.reference_summary.setText(' · '.join(('主参考：' if r.get('primary') else '')+r['name']+'（'+r['status']+'）' for r in refs) or '未提供参考也可原创')
            unresolved=self.state.get('unresolved',[]); notes=self.state.get('migration_notes',[])
            self.history_button.setText(f'{len(unresolved)}项旧设置待处理' if unresolved else '旧设置说明'); self.history_button.hide()
            failed=bool(CATALOG_STATE['kind']); self.catalog_error.setVisible(failed); self.catalog_message.setText(CATALOG_STATE['message']+'；原设置与正文保留，修复后可安全重试。'); self.catalog_message.setToolTip(CATALOG_STATE['path'])
            self.page.generate_button.setEnabled(not failed)
            for key,w in self.fields.items(): w.setEnabled(not failed and (key!='subgenres' or not automatic))
            for w in self.custom.values(): w.setEnabled(not failed)
            self.order_button.setEnabled(not failed)
            if failed:
                self.fields['narrative'].setText('规则目录不可用')
                for key in CATALOG:
                    w=self.fields.get(key)
                    if isinstance(w,ChipChoice): w.control.setText('规则目录不可用')
                    elif isinstance(w,QComboBox): w.setItemText(0,'规则目录不可用')
            try:
                plan=budget(self.read_config(self.page.config)); self.fields['density'].setToolTip(plan['strategy']); self.fields['speed'].setToolTip(plan['note'])
            except (ValueError,OverflowError): pass
            if changed:
                self.restore_epoch=getattr(self,'restore_epoch',0)+1; restore_epoch=self.restore_epoch
                self.fit_cards(); self.fit_timer.start(0)
                def restore():
                    if self.restore_epoch!=restore_epoch: return
                    if anchor and anchor.isVisible():
                        y=anchor.mapTo(self.page.settings_scroll.widget(),anchor.rect().topLeft()).y(); scroll.setValue(old_scroll+y-old_y)
                    else: scroll.setValue(min(old_scroll,scroll.maximum()))
                QTimer.singleShot(0,self,restore)
        finally: self._reflowing=False

    def retry_catalog(self):
        config=self.read_config(self.page.config)
        if not reload_catalog(): self.reflow(); return
        self.loading=True
        for key,g in CATALOG.items():
            w=self.fields.get(key)
            if isinstance(w,ChipChoice): w.set_rows([(r['id'],r['label']) for r in g['rows']])
            elif isinstance(w,QComboBox):
                w.blockSignals(True); w.clear(); w.addItem('自由创作' if key=='genre' else '自动','auto')
                for r in g['rows']:
                    if r['id']!='view.auto': w.addItem(r['label'],r['id']); w.setItemData(w.count()-1,r['body'],Qt.ItemDataRole.ToolTipRole)
                w.addItem('自定义…','custom'); w.blockSignals(False)
        self.load(config); self.page.config_changed()
    def fit_cards(self):
        self.tabs.fit()
        if self.presentation_expanded: self.presentation_tabs.fit()
        for card in (self.basic_card,self.presentation_card,self.details_card):
            if card.property('animatingHeight'): continue
            card.layout().invalidate(); card.layout().activate()
            # The frame adds its own top/bottom border outside the layout hint.
            # Omitting it squeezes field wrappers while their controls stay fixed.
            height=card.sizeHint().height()
            if card.height()!=height: card.setFixedHeight(height)
    def animate(self,widget,duration=160):
        motion=getattr(self.page.owner,'motion',None)
        if motion and widget.isVisible(): motion.fade(widget,duration)
    def tab_changed(self,index):
        if self.loading: return
        self.reflow(); self.animate(self.tabs.currentWidget(),100); self.page.remember_ui()
    def presentation_tab_changed(self,index):
        if self.loading: return
        self.reflow(); self.animate(self.presentation_tabs.currentWidget(),100); self.page.remember_ui()
    def toggle_presentation(self):
        self.presentation_expanded=not self.presentation_expanded; self.reflow(); self.animate(self.presentation_tabs); self.page.remember_ui()
    def toggle_more(self):
        title=list(DETAILS)[self.tabs.currentIndex()]; self.state['expanded'][title]=not self.state['expanded'].get(title,False); self.reflow(); self.page.config_changed(reflow=False); self.animate(self.tabs.currentWidget())
    def toggle_narrative(self):
        self.presentation_expanded=True; self.presentation_tabs.setCurrentIndex(2); self.reflow(); self.animate(self.presentation_tabs)
    def toggle_basic_more(self):
        motion=self.page.owner.motion; motion.stop(self.basic_card); previous=self.basic_card.height(); self.basic_expanded=not self.basic_expanded; self.reflow(); motion.resize_height(self.basic_card,previous,self.basic_card.height()); self.page.remember_ui()
    def locate_language(self): self.page.settings_scroll.ensureWidgetVisible(self.cells['language']); self.fields['language'].setFocus()
    def reset_tab(self):
        if CATALOG_STATE['kind']: self.page.notify('规则目录不可用，原选择保留；请先重试读取目录'); return
        title=list(DETAILS)[self.tabs.currentIndex()]
        before={k:copy.deepcopy(self.value(k)) for k in sum((list(x) for x in DETAILS[title]),[])}
        self.loading=True
        for key in sum((list(x) for x in DETAILS[title]),[]): self.set_value(key,[] if key in CATALOG and CATALOG[key]['multi'] else 'auto' if key in CATALOG else '')
        self.loading=False
        self.changed('reset')
        def restore():
            self.loading=True
            for key,value in before.items(): self.set_value(key,value)
            self.loading=False; self.changed('reset')
        self.page.owner.offer_undo(title+'已恢复自动',restore)
    def emotion_order(self):
        w=self.fields['emotion']; menu=QMenu(self)
        for index,rid in enumerate(w.values):
            if index:
                def move(v=rid):
                    values=w.values.copy(); i=values.index(v); values[i-1],values[i]=values[i],values[i-1]; w.set_values(values); self.changed('emotion')
                menu.addAction('上移：'+option_label(rid),move)
        menu.popup(self.order_button.mapToGlobal(self.order_button.rect().bottomLeft()))
    def add_reference(self):
        text=self.page.reference.toPlainText().strip(); name=self.value('reference_name').strip()
        if not text and not name: self.page.notify('先粘贴参考内容或填写作品名称／具体片段'); return
        import uuid
        refs=self.state['references']; refs.append(dict(id=uuid.uuid4().hex,name=name or f'参考 {len(refs)+1}',text=text,status='已读取文字' if text else '仅名称参考',primary=not refs)); self.changed('reference')
    def manage_references(self):
        menu=QMenu(self)
        for ref in self.state['references']:
            def primary(rid=ref['id']):
                for r in self.state['references']: r['primary']=r['id']==rid
                self.changed('reference')
            def remove(rid=ref['id']): self.state['references']=[r for r in self.state['references'] if r['id']!=rid]; self.changed('reference')
            menu.addAction('设为主参考：'+ref['name'],primary); menu.addAction('移除：'+ref['name'],remove)
        menu.popup(self.reference_summary.mapToGlobal(self.reference_summary.rect().bottomLeft()))
    def show_history(self):
        import json
        pane=QWidget(); col=QVBoxLayout(pane)
        col.addWidget(label('尚未处理的旧要求没有进入 AI 创作上下文。保留为补充要求后会生效。','muted'))
        for note in self.state.get('migration_notes',[]): col.addWidget(label(note))
        for record in self.state.get('unresolved',[]):
            value=record.get('value',''); source=record.get('source','').removeprefix('advanced.')
            row=QWidget(); layout=QVBoxLayout(row); layout.addWidget(label('旧设置：'+source+' · '+str(value)))
            target=next((key for key,data in CATALOG.items() if data['title']==source),None)
            from app.core.script_settings import ids_for
            choices=ids_for(target,value) if target else []
            if target=='subject': choices=ids_for(target,[{'人物一生':'人生','人生传记':'人生'}.get(v,v) for v in (value if isinstance(value,list) else [value])])
            if choices: layout.addWidget(label('建议对应：'+CATALOG[target]['title']+' → '+'、'.join(option_label(v) for v in choices)))
            def resolve(keep=False,r=record,t=target,selected=choices,widget=row):
                if keep:
                    text='旧设置 '+r.get('source','').removeprefix('advanced.')+'：'+str(r.get('value',''))
                    current=self.state['values'].get('retained_requirements',''); self.state['values']['retained_requirements']=(current+'；' if current else '')+text
                elif t and selected: self.set_value(t,selected if CATALOG[t]['multi'] else selected[0])
                else: return
                self.state['unresolved']=[item for item in self.state['unresolved'] if item is not r]; self.changed('reset'); widget.hide()
            actions=QHBoxLayout()
            if choices: actions.addWidget(button('采用对应设置',lambda _,fn=resolve:fn(False)))
            actions.addWidget(button('保留为补充要求',lambda _,fn=resolve:fn(True))); actions.addWidget(button('暂不处理',self.page.owner.close_inline,quiet=True)); layout.addLayout(actions); col.addWidget(row)
        def diagnostic():
            view=QTextEdit(); view.setReadOnly(True); view.setPlainText(json.dumps(dict(待处理要求=self.state.get('unresolved',[]),迁移说明=self.state.get('migration_notes',[]),迁移前原值=self.state.get('migration_original',{})),ensure_ascii=False,indent=2))
            self.page.owner.show_inline('诊断记录',view,self.page)
        col.addStretch(); col.addWidget(button('查看诊断原始记录',diagnostic,quiet=True)); self.page.owner.show_inline('处理旧设置',pane,self.page)
