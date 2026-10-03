"""Novel settings: existing catalogues in stable cards and current-content tabs."""
import copy
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QWidget,QFrame,QVBoxLayout,QHBoxLayout,QGridLayout,QLineEdit,QSpinBox,QSizePolicy
from app.ui.v2_widgets import label,button,QComboBox,MultiChoice
from app.ui.script_settings import CurrentTabs,ScriptSettings
from app.core.selection import ADVANCED
from app.core.writing_views import normalize_budget,is_long

class NovelSettings(QWidget):
    def __init__(self,page):
        super().__init__(page); self.page=page; self.loading=True; self.fields={}; self.cells={}; self.custom={}; self.custom_cells={}; self.signatures={}; self.columns=3; self.previous_genre='auto'; self.genre_drafts={}; self.config={}
        self.timer=QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self.reflow)
        col=QVBoxLayout(self); col.setContentsMargins(0,0,0,0); col.setSpacing(16)
        self.basic_card,basic=self.card('基本方向'); col.addWidget(self.basic_card); self.basic_grid=self.grid(); basic.addLayout(self.basic_grid)
        if page.kind=='rewrite': self.combo('output','输出类型',[('script','剧本'),('novel','小说')])
        self.combo('length','篇幅',[(x,x) for x in ['微小说','短篇小说','中篇小说','长篇小说','长篇连载']])
        self.combo('genre','主赛道',[('auto','自由创作')]+[(r['id'],r['label']) for r in page.owner.registry.of('genre')],custom=False)
        self.multi('subgenres','细分方向',[])
        self.spin('words','目标字数',1,1000000,3000)
        self.combo('perspective','叙事视角',[(x,x) for x in ['自动','第一人称','第三人称限知','第三人称全知','多视角']])
        self.combo('language','语言风格',[('自动','自动')]+[(r['label'],r['label']) for r in page.owner.registry.of('language')])
        self.planning_card,planning=self.card('章节规划'); col.addWidget(self.planning_card)
        self.total_summary=label('','muted'); planning.addWidget(self.total_summary); self.planning_grid=self.grid(); planning.addLayout(self.planning_grid)
        self.spin('chapters','计划章节数',1,1000,30); self.spin('chapter_words','每章目标字数',1,50000,2500)
        self.plan_note=label('修改预算只调整后续创作要求，不改写已有大纲或章节。','muted'); planning.addWidget(self.plan_note)
        self.details_card,details=self.card('创作细节'); col.addWidget(self.details_card); self.tabs=CurrentTabs(); details.addWidget(self.tabs); self.groups={}; self.detail_grids={}
        groups={'故事':dict(ADVANCED['故事']),'人物':dict(ADVANCED['人物']),'世界设定':{'时代背景':[],'世界规则':[],'地点环境':[],'画面表达':ADVANCED['风格']['画面表达']},'情绪':dict(ADVANCED['情绪']),'语言':dict(ADVANCED['台词'],**{k:v for k,v in ADVANCED['风格'].items() if k!='画面表达'}),'参考':dict(ADVANCED['参考'])}
        for title,items in groups.items():
            body=QWidget(); body.setObjectName('detailPage'); layout=QVBoxLayout(body); layout.setContentsMargins(0,0,0,0); grid=self.grid(); layout.addLayout(grid); self.detail_grids[title]=grid; self.groups[title]=list(items)
            for key,values in items.items():
                rows=[('人生','人生') if key=='叙事对象' and v=='人物一生' else (v,v) for v in values]
                catalogue={'融合赛道':'genre','结构公式':'formula','辅助机制':'formula','情绪标签':'emotion','台词风格':'dialogue'}.get(key)
                if catalogue: rows=[(r['id'],r['label']) for r in page.owner.registry.of(catalogue)]
                if key in ['时代背景','世界规则','地点环境','必须保留','不要出现','参考作品']: self.text(key,key)
                elif key in ['融合赛道','情绪标签','台词风格','反转','冲突','高潮机制','关系','爽点','内容边界','借鉴部分']: self.multi(key,key,rows,2 if key=='融合赛道' else None)
                else: self.combo(key,key,[('auto','自动')]+rows)
            self.tabs.addTab(body,title)
        self.tabs.currentChanged.connect(lambda _:self.changed('tab',structural=True))
        self.legacy_notice=label('','muted'); col.addWidget(self.legacy_notice); self.retain_legacy=button('将未映射旧要求保留为补充',self.retain_unmapped,quiet=True); col.addWidget(self.retain_legacy); self.retain_legacy.hide(); self.loading=False
    @staticmethod
    def grid():
        grid=QGridLayout(); grid.setHorizontalSpacing(16); grid.setVerticalSpacing(12); grid.setContentsMargins(0,0,0,0); return grid
    def card(self,title):
        frame=QFrame(self); frame.setObjectName('card'); frame.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed); layout=QVBoxLayout(frame); layout.setContentsMargins(16,16,16,16); layout.setSpacing(12); layout.addWidget(label(title,'sectionHeading')); return frame,layout
    def cell(self,key,title,widget):
        cell=QWidget(self); cell.setObjectName('fieldCell'); cell.hide(); layout=QVBoxLayout(cell); layout.setContentsMargins(0,0,0,0); layout.setSpacing(6); caption=label(title,'muted'); caption.setFixedHeight(22); caption.setWordWrap(False); layout.addWidget(caption); layout.addWidget(widget)
        widget.setFixedHeight(44); widget.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed); self.cells[key]=cell; self.fields[key]=widget
    def combo(self,key,title,rows,custom=True):
        widget=QComboBox(); [widget.addItem(text,value) for value,text in rows]; self.cell(key,title,widget)
        if custom:
            widget.addItem('自定义…','custom'); edit=QLineEdit(self); edit.setMaxLength(1000000); edit.setPlaceholderText('输入具体要求'); edit.textChanged.connect(lambda _,k=key:self.changed(k,False)); edit.setFixedHeight(44); cell=QWidget(self); cell.setObjectName('fieldCell'); cell.hide(); layout=QVBoxLayout(cell); layout.setContentsMargins(0,0,0,0); layout.setSpacing(6); caption=label(title+' · 自定义','muted'); caption.setFixedHeight(22); layout.addWidget(caption); layout.addWidget(edit); self.custom[key]=edit; self.custom_cells[key]=cell
        widget.currentIndexChanged.connect(lambda _,k=key:self.changed(k))
    def multi(self,key,title,rows,maximum=None):
        widget=MultiChoice(rows,maximum); self.cell(key,title,widget); widget.changed.connect(lambda k=key:self.changed(k,False))
    def spin(self,key,title,minimum,maximum,value):
        widget=QSpinBox(); widget.setRange(minimum,maximum); widget.setValue(value); self.cell(key,title,widget); widget.valueChanged.connect(lambda _,k=key:self.changed(k,False))
    def text(self,key,title):
        widget=QLineEdit(); widget.setMaxLength(1000000); widget.setPlaceholderText('可留空，按需填写'); self.cell(key,title,widget); widget.textChanged.connect(lambda _,k=key:self.changed(k,False))
    def value(self,key):
        w=self.fields[key]
        if isinstance(w,MultiChoice): return w.values.copy()
        if isinstance(w,QComboBox): return self.custom[key].text() if w.currentData()=='custom' else w.currentData()
        return w.value() if isinstance(w,QSpinBox) else w.text()
    def set_value(self,key,value):
        if key=='叙事对象' and value=='人物一生': value='人生'
        w=self.fields[key]
        if isinstance(w,MultiChoice): w.set_values(value or [])
        elif isinstance(w,QComboBox):
            i=w.findData(value)
            if i<0 and key in self.custom: w.setCurrentIndex(w.findData('custom')); self.custom[key].setText(str(value or '').removeprefix('custom:'))
            elif i>=0: w.setCurrentIndex(i)
        elif isinstance(w,QSpinBox): w.setValue(int(value or 1))
        else: w.setText(str(value or ''))
    def changed(self,key,structural=True):
        if self.loading or self.page.loading: return
        if key=='output': self.page.switch_output(self.value('output')); return
        if key=='genre':
            old=self.previous_genre; new=self.value('genre'); self.genre_drafts[old]=self.value('subgenres'); self.loading=True
            self.fields['subgenres'].set_rows([(r['id'],r['label']) for r in self.page.owner.registry.of('subgenre') if r.get('parent')==new]); self.fields['subgenres'].set_values(self.genre_drafts.get(new,[])); self.loading=False; self.previous_genre=new
        if key=='length':
            self.loading=True
            self.fields['words'].setValue({'微小说':800,'短篇小说':3000,'中篇小说':20000,'长篇小说':75000,'长篇连载':75000}.get(self.value('length'),3000)); self.loading=False
        if key in ['words','chapters','chapter_words','length'] and self.value('length') in ['长篇连载','长篇小说']:
            budget=normalize_budget(dict(words=self.value('words'),chapters=self.value('chapters'),chapter_words=self.value('chapter_words')),key)
            self.loading=True
            for k in ['words','chapters','chapter_words']: self.set_value(k,budget[k])
            self.loading=False
        self.update_summary()
        if structural: self.timer.start(0)
        self.page.config_changed(reflow=False)
        if key=='tab': self.page.remember_ui()
    def read_config(self,base):
        c=copy.deepcopy(base)
        for key in ['length','genre','subgenres','words','chapters','chapter_words','perspective','language']: c[key]=self.value(key)
        c['novel_genre_drafts']=copy.deepcopy(self.genre_drafts)
        advanced=copy.deepcopy(c.get('advanced',{}))
        for keys in self.groups.values():
            for key in keys:
                value=self.value(key)
                if key in self.custom and self.fields[key].currentData()=='custom': value='custom:'+value
                if value and value!='auto': advanced[key]=value
                else: advanced.pop(key,None)
        c.update(output='novel',advanced=advanced)
        return c
    def load(self,config):
        if config.get('output')=='novel':
            unknown=config.setdefault('writing_unmapped',{})
            genre=config.get('genre','auto')
            known={'auto'}|{r['id'] for r in self.page.owner.registry.of('genre')}
            if genre not in known:
                found=next((r['id'] for r in self.page.owner.registry.of('genre') if r['label']==genre),None)
                if found: config['genre']=found
                else: unknown['主赛道']=str(genre); config['genre']='auto'
            known_advanced={key for keys in self.groups.values() for key in keys}|{'旧设置补充'}
            for key,value in config.get('advanced',{}).items():
                if key not in known_advanced and value: unknown[key]=copy.deepcopy(value)
        self.loading=True; self.config=copy.deepcopy(config); self.genre_drafts=copy.deepcopy(config.get('novel_genre_drafts',{}))
        try:
            for key in ['output','length','genre','words','chapters','chapter_words','perspective','language']:
                if key in self.fields: self.set_value(key,'novel' if key=='output' else config.get(key))
            self.previous_genre=self.value('genre'); self.fields['subgenres'].set_rows([(r['id'],r['label']) for r in self.page.owner.registry.of('subgenre') if r.get('parent')==self.previous_genre]); self.set_value('subgenres',config.get('subgenres',[]))
            for keys in self.groups.values():
                for key in keys: self.set_value(key,config.get('advanced',{}).get(key,[] if isinstance(self.fields[key],MultiChoice) else 'auto' if isinstance(self.fields[key],QComboBox) else ''))
        finally: self.loading=False
        unknown=config.get('writing_unmapped',{}) if config.get('output')=='novel' else {}
        text='；'.join(config.get('writing_notes',[]))
        if unknown: text+='\n未映射的旧要求（原值已保留）：'+ '；'.join(key+'：'+('、'.join(map(str,value)) if isinstance(value,list) else str(value)) for key,value in unknown.items())+'。处理前不会自动忽略这些要求。'
        self.legacy_notice.setText(text.strip()); self.legacy_notice.setVisible(bool(self.legacy_notice.text())); self.retain_legacy.setVisible(bool(unknown)); self.update_summary(); self.reflow()
    def retain_unmapped(self):
        config=self.page.config; unknown=config.get('writing_unmapped',{})
        text='；'.join(key+'：'+('、'.join(map(str,value)) if isinstance(value,list) else str(value)) for key,value in unknown.items())
        advanced=config.setdefault('advanced',{}); advanced['旧设置补充']='；'.join(filter(None,[advanced.get('旧设置补充',''),text]))
        for key in unknown: advanced.pop(key,None)
        config['writing_unmapped']={}; self.legacy_notice.setText('未映射旧要求已按你的选择保留为补充，原始记录仍保留。'); self.retain_legacy.hide(); self.page.config_changed(reflow=False)
    def update_summary(self):
        total=self.value('words'); chapters=self.value('chapters'); each=self.value('chapter_words'); self.total_summary.setText(f'计划总字数：{total:,} 字（与基本目标字数共用）。约 {chapters} 章，每章预算 {each:,} 字，末章按剩余字数安排。')
    def layout_fields(self,grid,keys):
        custom=tuple(k for k in keys if k in self.custom and self.fields[k].currentData()=='custom'); signature=(tuple(keys),custom,self.columns)
        self.wanted.update(keys); self.wanted_custom.update(custom)
        if self.signatures.get(grid)==signature: return
        while grid.count(): grid.takeAt(0)
        row=0; column=0; pending=[]
        def custom_rows():
            nonlocal row,pending
            for k in pending: grid.addWidget(self.custom_cells[k],row,0,1,self.columns,Qt.AlignmentFlag.AlignTop); row+=1
            pending=[]
        full={'时代背景','世界规则','地点环境','必须保留','不要出现','参考作品'}
        for key in keys:
            span=self.columns if key in full else 1
            if span==self.columns and column: row+=1; column=0; custom_rows()
            grid.addWidget(self.cells[key],row,column,1,span,Qt.AlignmentFlag.AlignTop); column+=span
            if key in custom: pending.append(key)
            if column>=self.columns: row+=1; column=0; custom_rows()
        if column: row+=1; custom_rows()
        for i in range(3): grid.setColumnStretch(i,1 if i<self.columns else 0)
        self.signatures[grid]=signature
    def reflow(self):
        if not hasattr(self.page,'settings_scroll'): return
        width=self.page.settings_scroll.viewport().width()-80
        if self.columns==3 and width<696: self.columns=2 if width>=456 else 1
        elif self.columns==2 and width>=720: self.columns=3
        elif self.columns==2 and width<456: self.columns=1
        elif self.columns==1 and width>=480: self.columns=3 if width>=720 else 2
        self.wanted=set(); self.wanted_custom=set(); keys=['length','genre','subgenres','words','perspective','language']
        if self.page.kind=='rewrite': keys=['output','genre','subgenres','length','words','perspective','language']
        self.layout_fields(self.basic_grid,keys)
        long=self.value('length') in ['长篇连载','长篇小说']; self.planning_card.setVisible(long); self.layout_fields(self.planning_grid,['chapters','chapter_words'] if long else [])
        current=list(self.groups)[self.tabs.currentIndex()]
        for title,grid in self.detail_grids.items(): self.layout_fields(grid,self.groups[title] if current==title else [])
        for key,cell in self.cells.items(): cell.setVisible(key in self.wanted)
        for key,cell in self.custom_cells.items(): cell.setVisible(key in self.wanted_custom)
        auto=self.value('genre')=='auto'; sub=self.fields['subgenres']; sub.setEnabled(not auto)
        if auto: sub.setText('由 AI 自动选择'); sub.setToolTip('自由创作时自动选择细分方向；选择主赛道后可多选。')
        self.tabs.fit()
        for card in [self.basic_card,self.planning_card,self.details_card]: card.layout().invalidate(); card.setFixedHeight(card.sizeHint().height())

class RewriteScriptSettings(ScriptSettings):
    """Same script fields/rules; prepend the functional output selector."""
    def make(self,key):
        if key!='reference_content': return super().make(key)
        if key in self.cells: return
        cell=QWidget(self); cell.setObjectName('fieldCell'); layout=QVBoxLayout(cell); layout.setContentsMargins(0,0,0,0); layout.setSpacing(6)
        caption=label('参考内容','muted'); caption.setFixedHeight(22); layout.addWidget(caption)
        control=button('查看上方参考内容',lambda:self.page.settings_scroll.ensureWidgetVisible(self.page.reference_card)); control.setFixedHeight(44); layout.addWidget(control)
        self.cells[key]=cell; self.fields[key]=control; cell.hide()
    def __init__(self,page):
        super().__init__(page)
        cell=QWidget(self); cell.setObjectName('fieldCell'); layout=QVBoxLayout(cell); layout.setContentsMargins(0,0,0,0); layout.setSpacing(6); caption=label('输出类型','muted'); caption.setFixedHeight(22); layout.addWidget(caption)
        output=QComboBox(); output.addItem('剧本','script'); output.addItem('小说','novel'); output.setFixedHeight(44); output.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed); layout.addWidget(output); self.cells['output']=cell; self.fields['output']=output; output.currentIndexChanged.connect(lambda _:page.switch_output(output.currentData()) if not page.loading else None); self.reflow()
    def layout_cells(self,grid,keys,columns):
        if grid is self.basic_grid and 'output' in self.cells: keys=['output','genre','subgenres','form','duration_label','mode','language']
        return super().layout_cells(grid,keys,columns)
