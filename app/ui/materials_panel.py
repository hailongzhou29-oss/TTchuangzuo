import json
from datetime import datetime
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QTabWidget,QTextEdit,QComboBox,QLineEdit,QListWidget,QCheckBox,QFileDialog,QSpinBox
from app.ui.v2_widgets import label,button,QComboBox
from app.storage.project import new_id
from app.core.services import import_preview
from app.core.cases import CaseLibrary
from app.ui.chinese import readable

class MaterialsPanel(QWidget):
    def __init__(self,owner,page,standalone=False):
        super().__init__(); self.owner=owner; self.page=page; self.store=owner.work.store; self.setMinimumWidth(300)
        if not standalone: self.setMaximumWidth(360)
        col=QVBoxLayout(self); header=QHBoxLayout(); header.addWidget(label('资料与规则','heading'),1)
        if not standalone: header.addWidget(button('×',self.close_panel,quiet=True))
        col.addLayout(header)
        if standalone: col.addWidget(label('当前作品：'+self.store.metadata()['name'],'muted'))
        self.tabs=QTabWidget(); col.addWidget(self.tabs,1); self.settings_tab(); self.references_tab(); self.rules_tab()
    def close_panel(self): self.hide(); self.page.editor.setFocus()
    def settings_tab(self):
        w=QWidget(); col=QVBoxLayout(w); self.setting_key=QComboBox(); self.setting_key.addItems(['作品简介','人物与关系','世界与背景','故事规划','伏笔与进展']); col.addWidget(self.setting_key)
        self.setting_text=QTextEdit(); col.addWidget(self.setting_text,1); self.setting_key.currentTextChanged.connect(self.load_setting)
        col.addWidget(button('保存设定',lambda:self.owner.run(self.save_setting),True)); self.tabs.addTab(w,'创作设定'); self.load_setting()
    def load_setting(self):
        values=self.store.setting('v2_settings',{}); plan=self.store.setting('v2_plan',{})
        fallback={'作品简介':plan.get('synopsis',''),'人物与关系':plan.get('characters',''),'故事规划':plan.get('chapters',[])}.get(self.setting_key.currentText(),'')
        self.setting_text.setPlainText(values.get(self.setting_key.currentText(),{}).get('text',fallback if isinstance(fallback,str) else readable(fallback)))
    def save_setting(self):
        values=self.store.setting('v2_settings',{}); values[self.setting_key.currentText()]=dict(text=self.setting_text.toPlainText(),source='用户编辑',revision=self.owner.work.revision)
        self.store.set_setting('v2_settings',values); self.page.notify('已保存，下次生成或修改时生效')
    def references_tab(self):
        w=QWidget(); col=QVBoxLayout(w); actions=QHBoxLayout(); actions.addWidget(button('添加文本',lambda:self.edit_reference())); actions.addWidget(button('导入文件',lambda:self.owner.run(self.import_reference))); col.addLayout(actions)
        col.addWidget(button('影视案例',lambda:self.owner.run(self.cases),quiet=True)); self.references=QListWidget(); self.references.currentRowChanged.connect(self.select_reference); col.addWidget(self.references)
        self.ref_title=QLineEdit(); self.ref_title.setPlaceholderText('未命名资料'); col.addWidget(self.ref_title)
        self.ref_scope=QComboBox(); self.ref_scope.addItems(['整部作品','当前章节','当前请求']); col.addWidget(self.ref_scope)
        self.ref_text=QTextEdit(); self.ref_text.setPlaceholderText('粘贴需要AI参考的内容'); col.addWidget(self.ref_text,1)
        self.ref_enabled=QCheckBox('用于本次创作'); self.ref_enabled.setChecked(True); col.addWidget(self.ref_enabled)
        col.addWidget(button('保存资料',lambda:self.owner.run(self.save_reference),True)); col.addWidget(button('移除',lambda:self.owner.run(self.remove_reference),quiet=True)); self.tabs.addTab(w,'参考资料'); self.ref_id=None; self.refresh_references()
    def refresh_references(self):
        self.ref_rows=self.store.setting('v2_references',[]); self.references.clear()
        for row in self.ref_rows: self.references.addItem(row['title']+' · '+('已启用' if row.get('enabled',True) else '已停用'))
    def edit_reference(self): self.ref_id=None; self.ref_title.setText('未命名资料'); self.ref_text.clear(); self.ref_enabled.setChecked(True)
    def select_reference(self,index):
        if index<0 or index>=len(self.ref_rows): return
        r=self.ref_rows[index]; self.ref_id=r['id']; self.ref_title.setText(r['title']); self.ref_text.setPlainText(r['text']); self.ref_scope.setCurrentText(r.get('scope','整部作品')); self.ref_enabled.setChecked(r.get('enabled',True))
    def save_reference(self):
        row=dict(id=self.ref_id or new_id(),title=self.ref_title.text().strip() or '未命名资料',text=self.ref_text.toPlainText(),scope=self.ref_scope.currentText(),enabled=self.ref_enabled.isChecked(),document_id=self.owner.work.document_id,source_type='用户文本')
        rows=[r for r in self.store.setting('v2_references',[]) if r['id']!=row['id']]+[row]; self.store.set_setting('v2_references',rows); self.ref_id=row['id']; self.refresh_references(); self.page.notify('资料已保存')
    def remove_reference(self):
        if self.ref_id:
            old=self.store.setting('v2_references',[]); self.store.set_setting('v2_references',[r for r in old if r['id']!=self.ref_id]); self.refresh_references(); self.owner.offer_undo('已移除，可撤销',lambda:self.store.set_setting('v2_references',old))
    def import_reference(self):
        path,_=QFileDialog.getOpenFileName(self,'导入文件','','文本 (*.txt *.md *.json)')
        if path:
            data=import_preview(__import__('pathlib').Path(path)); self.edit_reference(); self.ref_title.setText(data.get('title') or __import__('pathlib').Path(path).stem); self.ref_text.setPlainText(data['text']); self.page.notify('预览导入内容，点击保存资料后用于创作')
    def rules_tab(self):
        w=QWidget(); col=QVBoxLayout(w); self.rules=QListWidget(); self.rules.currentRowChanged.connect(self.select_rule); col.addWidget(self.rules)
        self.rule_name=QLineEdit(); self.rule_name.setPlaceholderText('规则名称'); col.addWidget(self.rule_name); self.rule_scope=QComboBox(); self.rule_scope.addItems(['当前项目','所有新项目']); col.addWidget(self.rule_scope)
        self.rule_text=QTextEdit(); self.rule_text.setPlaceholderText('写明AI必须遵守或避免的要求'); col.addWidget(self.rule_text,1); self.rule_enabled=QCheckBox('启用'); self.rule_enabled.setChecked(True); col.addWidget(self.rule_enabled)
        actions=QHBoxLayout(); actions.addWidget(button('添加规则',self.new_rule)); actions.addWidget(button('导入规则',lambda:self.owner.run(self.import_rule))); col.addLayout(actions); col.addWidget(button('保存规则',lambda:self.owner.run(self.save_rule),True)); col.addWidget(button('更新本项目规则',lambda:self.owner.run(self.update_rules),quiet=True)); col.addWidget(button('移除',lambda:self.owner.run(self.remove_rule),quiet=True)); self.tabs.addTab(w,'创作规则'); self.rule_id=None; self.refresh_rules()
    def update_rules(self):
        pins=self.store.setting('v2_rule_pins',{}); changes=[r for rid,r in self.owner.registry.by_id.items() if rid in pins and r['body']!=pins[rid]['body']]
        if not changes: self.page.notify('当前内置规则已是最新版本'); return
        def apply():
            for r in changes: pins[r['id']]=r
            self.store.set_setting('v2_rule_pins',pins); self.refresh_rules(); self.page.notify('已保存，下次生成或修改时生效')
        self.owner.confirm_inline('将更新本项目规则：'+ '、'.join(r['label'] for r in changes),apply,parent=self)
    def refresh_rules(self):
        c=self.page.read_config()
        try: self.rule_rows=self.owner.registry.effective(c)
        except ValueError: self.rule_rows=[self.owner.registry.by_id['R01']]
        overrides=self.store.setting('v2_rule_overrides',{}); self.rule_rows=[dict(r,**overrides.get(r['id'],{})) for r in self.rule_rows]+self.store.setting('v2_user_rules',[])
        self.rules.clear()
        for r in self.rule_rows: self.rules.addItem(r['label']+' · '+('生效' if r.get('enabled',True) else '停用'))
    def new_rule(self): self.rule_id=None; self.rule_name.clear(); self.rule_text.clear(); self.rule_enabled.setChecked(True)
    def select_rule(self,index):
        if not 0<=index<len(self.rule_rows): return
        r=self.rule_rows[index]; self.rule_id=r['id']; self.rule_name.setText(r['label']); self.rule_text.setPlainText(r['body']); self.rule_enabled.setChecked(r.get('enabled',True))
    def import_rule(self):
        path,_=QFileDialog.getOpenFileName(self,'导入规则','','规则 (*.md)')
        if path: self.new_rule(); self.rule_name.setText(__import__('pathlib').Path(path).stem); self.rule_text.setPlainText(__import__('pathlib').Path(path).read_text(encoding='utf-8-sig'))
    def save_rule(self):
        if not self.rule_text.toPlainText().strip(): raise ValueError('规则内容不能为空')
        rid=self.rule_id or 'U_'+new_id(); row=dict(id=rid,label=self.rule_name.text().strip() or '我的规则',body=self.rule_text.toPlainText(),enabled=self.rule_enabled.isChecked(),version=1,source_type='用户规则',applies_to=['script','novel','rewrite'])
        if rid in self.owner.registry.by_id:
            values=self.store.setting('v2_rule_overrides',{}); old=values.get(rid,{}); row['version']=old.get('version',1)+1; values[rid]=row; self.store.set_setting('v2_rule_overrides',values)
        else:
            old=self.store.setting('v2_user_rules',[]); row['version']=next((r['version']+1 for r in old if r['id']==rid),1); self.store.set_setting('v2_user_rules',[r for r in old if r['id']!=rid]+[row])
        if self.rule_scope.currentText()=='所有新项目':
            rows=self.owner.options.get('new_project_rules',[]); self.owner.options['new_project_rules']=[r for r in rows if r['id']!=rid]+[row]; self.owner.save_options()
        self.rule_id=rid; self.refresh_rules(); self.page.notify('已保存，下次生成或修改时生效')
    def remove_rule(self):
        if not self.rule_id: return
        self.rule_enabled.setChecked(False); self.save_rule(); self.page.notify('已停用，下次调用生效')
    def cases(self):
        library=CaseLibrary(self.owner.workspace.root,self.owner.resources/'影视案例库_改编关系种子_V0.1.json')
        pane=QWidget(); col=QVBoxLayout(pane); filters=QHBoxLayout(); search=QLineEdit(); search.setPlaceholderText('搜索作品、原作或作者'); filters.addWidget(search,1); fmt=QComboBox(); fmt.addItem('全部类型',None)
        for name,value in [('电影','film'),('电视剧','tv_series'),('短剧','micro_drama')]: fmt.addItem(name,value)
        filters.addWidget(fmt); col.addLayout(filters); years=QHBoxLayout(); low=QSpinBox(); low.setRange(1980,datetime.now().year); low.setValue(1980); high=QSpinBox(); high.setRange(1980,datetime.now().year); high.setValue(datetime.now().year); years.addWidget(low); years.addWidget(high); col.addLayout(years)
        metric=QComboBox(); metric.addItems(['不限成绩','有获奖证据','有票房证据','有评分快照']); col.addWidget(metric)
        source=QComboBox(); source.addItem('全部改编来源',None)
        for name,value in [('小说','novel'),('非虚构','nonfiction'),('漫画','comic'),('戏剧','stage_play'),('原创','original_screenplay')]: source.addItem(name,value)
        col.addWidget(source); genres=QLineEdit(); genres.setPlaceholderText('题材关键词'); col.addWidget(genres)
        rows=QListWidget(); col.addWidget(rows); detail=QTextEdit(); detail.setReadOnly(True); col.addWidget(detail,1); values=[]
        def refresh():
            values.clear(); rows.clear(); values.extend(library.records(query=search.text(),screen_format=fmt.currentData(),year_min=low.value(),year_max=high.value(),source_type=source.currentData()))
            field={'有获奖证据':'award_records','有票房证据':'box_office_snapshots','有评分快照':'rating_snapshots'}.get(metric.currentText())
            if field: values[:]=[r for r in values if r.get(field)]
            if genres.text().strip(): values[:]=[r for r in values if genres.text().strip() in json.dumps(r,ensure_ascii=False)]
            for r in values: rows.addItem(r['title']+' · '+str(r.get('release_year') or '未核实'))
        def select(index):
            if not 0<=index<len(values): return
            r=values[index]; translations={'title':'作品','release_year':'年份','screen_format':'形态','adaptation_sources':'改编来源','award_records':'奖项','box_office_snapshots':'票房','rating_snapshots':'评分','evidence':'来源','notes':'分析依据与限制'}
            detail.setPlainText('\n\n'.join(name+'：'+readable(r.get(key)) for key,name in translations.items()))
        def use():
            if rows.currentRow()<0: return
            r=values[rows.currentRow()]; self.edit_reference(); self.ref_title.setText(r['title']); self.ref_text.setPlainText(detail.toPlainText()); self.save_reference()
            if self.page.kind=='rewrite': self.page.reference.setPlainText(detail.toPlainText())
            self.owner.close_inline()
        def import_cases():
            path,_=QFileDialog.getOpenFileName(pane,'导入案例','','案例 (*.json *.csv)')
            if not path: return
            imported=library.preview_import(path)
            def save():
                for r in imported:
                    old=next((row for row in library.records() if row['work_id']==r['work_id']),None)
                    library.save(r,old['_version'] if old else None)
                refresh()
            self.owner.confirm_inline('已识别'+str(len(imported))+'条案例，确认导入到本地资料库',save,parent=pane)
        search.textChanged.connect(refresh); fmt.currentIndexChanged.connect(refresh); low.valueChanged.connect(refresh); high.valueChanged.connect(refresh); source.currentIndexChanged.connect(refresh); metric.currentIndexChanged.connect(refresh); genres.textChanged.connect(refresh); rows.currentRowChanged.connect(select)
        col.addWidget(label('仅有简介时只按简介借鉴；未核实字段不作为事实','muted')); actions=QHBoxLayout(); actions.addWidget(button('导入案例',lambda:self.owner.run(import_cases))); actions.addWidget(button('用于当前作品',use,True)); col.addLayout(actions); refresh(); self.owner.show_inline('影视案例',pane)
