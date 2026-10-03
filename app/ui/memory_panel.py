"""Current-project, source-bound memory and explicitly reviewed fact corrections."""
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QTabWidget,QListWidget,QTextEdit,QComboBox
from app.ui.v2_widgets import label,button,QComboBox
from app.ui.script_settings import StableTabBar
from app.core.project_memory import ProjectMemory
from app.core.knowledge import FactService

KINDS={'character':'人物','relationship':'关系','event':'事件','foreshadow':'伏笔'}
STATES={'candidate':'候选，待确认','confirmed':'已确认','disputed':'争议','invalid':'失效'}

class MemoryPanel(QWidget):
    def __init__(self,owner,work):
        super().__init__(); self.owner,self.work=owner,work; self.memory=ProjectMemory(work.store); self.facts=FactService(work.store)
        col=QVBoxLayout(self); col.addWidget(label('当前作品：'+work.store.metadata()['name']+'。语义记忆有原文证据，但不等于已确认事实；修正先保存为候选。','muted'))
        self.tabs=QTabWidget(); self.tabs.setTabBar(StableTabBar()); col.addWidget(self.tabs,1)
        view=QWidget(); layout=QVBoxLayout(view); self.documents=QComboBox(); layout.addWidget(self.documents); self.summary=QTextEdit(); self.summary.setReadOnly(True); layout.addWidget(self.summary,1); self.model_facts=QListWidget(); layout.addWidget(self.model_facts,1); self.propose_button=button('将所选记忆保存为事实候选',lambda:owner.run(self.propose),True); layout.addWidget(self.propose_button); self.tabs.addTab(view,'语义记忆与来源')
        self.refresh_button=button('更新当前正文语义记忆（1次请求）',lambda:owner.run(lambda:owner.refresh_project_memory(work,self))); layout.addWidget(self.refresh_button)
        edit=QWidget(); layout=QVBoxLayout(edit); self.fact_list=QListWidget(); layout.addWidget(self.fact_list,1); self.fact_source=label('选择事实后查看来源。','muted'); layout.addWidget(self.fact_source); self.fact_text=QTextEdit(); self.fact_text.setPlaceholderText('核对或修正所选事实，保存后重新成为候选。'); layout.addWidget(self.fact_text,1)
        actions=QHBoxLayout(); self.revise_button=button('保存修正为候选',lambda:owner.run(self.revise),True); actions.addWidget(self.revise_button); self.confirm_button=button('确认事实',lambda:owner.run(self.confirm)); actions.addWidget(self.confirm_button); actions.addWidget(button('标为争议',lambda:owner.run(lambda:self.set_state('disputed')))); actions.addWidget(button('版本与来源',lambda:owner.run(self.history))); layout.addLayout(actions); self.tabs.addTab(edit,'事实查看与修正')
        self.documents.currentIndexChanged.connect(self.show_memory); self.fact_list.currentRowChanged.connect(self.show_fact); self.refresh()
    def bound(self):
        if self.owner.work is not self.work: raise ValueError('作品已切换，请重新打开当前作品的记忆')
    def refresh(self):
        self.bound(); selected=self.documents.currentData() or self.work.document_id; self.records=self.memory.refresh(); self.documents.blockSignals(True); self.documents.clear()
        for did,record in self.records.items(): self.documents.addItem(record['title'],did)
        self.documents.setCurrentIndex(max(0,self.documents.findData(selected))); self.documents.blockSignals(False); self.show_memory(); self.refresh_facts()
    def show_memory(self):
        record=self.records.get(self.documents.currentData(),{}); self.model_facts.clear(); self.propose_button.setEnabled(False)
        if not record: self.summary.setPlainText('当前作品没有可用正文记忆。'); return
        lines=[record['title']+' · '+record['method'],'来源版本：'+record['source_revision'][:12]+' · 原文校验：'+record['source_hash'][:12],record['summary']]
        for key,title in [('characters','人物'),('relationships','关系'),('events','事件'),('foreshadow','伏笔'),('unresolved','未解问题')]:
            if record.get(key): lines.append(title+'：'+'；'.join(record[key]))
        if record.get('evidence'): lines.append('原文证据：\n'+'\n'.join(record['evidence']))
        self.summary.setPlainText('\n\n'.join(lines))
        for fact in record.get('facts',[]): self.model_facts.addItem(KINDS[fact['category']]+'：'+fact['content']+'\n证据：'+fact['evidence'])
        self.propose_button.setEnabled(bool(record.get('facts')))
    def propose(self):
        self.bound(); index=self.model_facts.currentRow()
        if index<0: raise ValueError('先选择一条带原文证据的语义事实')
        fid=self.memory.propose_fact(self.documents.currentData(),index); self.refresh_facts(fid); self.tabs.setCurrentIndex(1)
    def refresh_facts(self,fid=None):
        if fid is None and hasattr(self,'fact_rows') and self.fact_list.currentRow()>=0: fid=self.fact_rows[self.fact_list.currentRow()]['id']
        self.fact_rows=self.facts.facts(); self.fact_list.blockSignals(True); self.fact_list.clear(); categories=self.work.store.setting('v2_fact_categories',{})
        for fact in self.fact_rows:
            state=STATES[fact['state']]+(' · 来源已过期' if not self.facts.source_current(fact) else '')
            self.fact_list.addItem(KINDS.get(categories.get(fact['id']),'设定')+' · '+fact['entity_name']+' · '+state+f' · v{fact["version"]}\n'+fact['content'])
        index=next((i for i,f in enumerate(self.fact_rows) if f['id']==fid),-1); self.fact_list.setCurrentRow(index); self.fact_list.blockSignals(False); self.show_fact(index)
    def selected(self):
        self.bound(); index=self.fact_list.currentRow()
        if index<0: raise ValueError('先选择当前项目的一条事实')
        return self.fact_rows[index]
    def show_fact(self,index):
        self.revise_button.setEnabled(index>=0); self.confirm_button.setEnabled(index>=0)
        if index<0: self.fact_text.clear(); self.fact_source.setText('选择事实后查看来源。'); return
        fact=self.fact_rows[index]; self.fact_text.setPlainText(fact['content'])
        if fact['source_document_id']:
            title=self.work.store.document(fact['source_document_id'])['title']; self.fact_source.setText('来源：'+title+' · 版本'+fact['source_revision'][:12]+'\n原文证据：'+fact['evidence']+('（来源已过期，不作为当前事实使用）' if not self.facts.source_current(fact) else ''))
        else: self.fact_source.setText('来源：用户手工设定；原来源保留在不可变历史中。')
        self.confirm_button.setEnabled(fact['state']!='confirmed' and self.facts.source_current(fact))
    def revise(self):
        fact=self.selected(); self.facts.revise(fact['id'],self.fact_text.toPlainText(),fact['valid_from'],fact['valid_to'],expected_version=fact['version']); self.refresh_facts(fact['id'])
    def confirm(self):
        fact=self.selected()
        def apply():
            self.bound(); self.facts.set_state(fact['id'],'confirmed',expected_version=fact['version']); self.refresh_facts(fact['id'])
        self.owner.confirm_inline('确认把此候选作为当前项目事实：'+fact['content'],apply,parent=self)
    def set_state(self,state):
        fact=self.selected(); self.facts.set_state(fact['id'],state,expected_version=fact['version']); self.refresh_facts(fact['id'])
    def history(self):
        fact=self.selected(); values=self.facts.versions(fact['id']); pane=QWidget(); col=QVBoxLayout(pane); text=QTextEdit(); text.setReadOnly(True); text.setPlainText('\n\n'.join(f'v{v["version"]} · {STATES[v["state"]]}\n'+v['content']+'\n来源：'+(v['source_document_id'] or '用户手工设定')+'\n证据：'+(v['evidence'] or '无原文证据') for v in values)); col.addWidget(text); col.addWidget(button('返回记忆',lambda:self.owner.run(self.owner.open_memory))); self.owner.show_inline('事实版本与来源',pane)
