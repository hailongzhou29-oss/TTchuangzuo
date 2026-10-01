import html
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame,QVBoxLayout,QHBoxLayout,QComboBox,QTextBrowser,QMenu
from app.ui.v2_widgets import label,button,ChatInput,QComboBox
from app.core.context import ChatService

class AssistantPanel(QFrame):
    def __init__(self,owner):
        super().__init__(); self.owner=owner; self.setObjectName('assistant'); self.setMinimumWidth(300); self.setMaximumWidth(460)
        layout=QVBoxLayout(self); layout.setContentsMargins(16,20,16,16); layout.setSpacing(12)
        head=QHBoxLayout(); head.addWidget(label('AI 助手','heading'),1)
        more=button('…',self.menu,quiet=True); more.setToolTip('对话'); head.addWidget(more); layout.addLayout(head)
        self.chat=QTextBrowser(); self.chat.setObjectName('chat'); self.chat.setOpenLinks(False); self.chat.anchorClicked.connect(self.action); layout.addWidget(self.chat,1)
        self.model=QComboBox(); self.model.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon); self.model.setMinimumContentsLength(12)
        self.model.currentIndexChanged.connect(self.model_changed); layout.addWidget(self.model)
        self.input=ChatInput(); self.input.setPlaceholderText('例如：保留情节，让第二场冲突更强'); self.input.setFixedHeight(104); self.input.send.connect(self.send)
        self.input.textChanged.connect(self.save_input); layout.addWidget(self.input)
        actions=QHBoxLayout(); actions.addWidget(label('回车发送 · 按住上档键换行','muted'),1)
        self.send_button=button('➤',self.send,True); self.send_button.setToolTip('发送'); actions.addWidget(self.send_button); layout.addLayout(actions)
        self.scope=button('',self.clear_scope,quiet=True); self.scope.hide(); layout.insertWidget(3,self.scope)
        self.refresh_models()
    def refresh_models(self):
        current=self.owner.options.get('default_connection'); self.model.blockSignals(True); self.model.clear(); self.model.addItem('选择模型',None)
        for c in self.owner.connections.all():
            fixture=c.verification.get('development_test') or any(x in (c.name+' '+c.model+' '+c.id).casefold() for x in ('fixture','固定响应'))
            if c.enabled and c.model and (not fixture or getattr(self.owner,'allow_test_connections',False)):
                self.model.addItem(c.name+' · '+c.model,c.id)
        if not current and self.model.count()>1: current=self.model.itemData(1); self.owner.options['default_connection']=current
        self.model.addItem('配置模型','settings'); self.model.setCurrentIndex(max(0,self.model.findData(current))); self.model.blockSignals(False)
    def model_changed(self):
        selected=self.model.currentData()
        if selected=='settings': self.owner.navigate(4); return
        if selected:
            self.owner.options['default_connection']=selected; self.owner.save_options()
            if self.owner.work: self.owner.work.store.set_setting('v2_model',selected)
    def connection(self):
        cid=self.model.currentData()
        if not cid or cid=='settings': raise ValueError('先选择或配置一个文本模型')
        return self.owner.connections.get(cid)
    def clear_scope(self): self.owner.bound_selection=None; self.scope.hide()
    def send(self):
        if self.owner.active_task: self.owner.stop_task(); return
        instruction=self.input.toPlainText().strip()
        if not instruction: return
        self.owner.run(lambda:self.owner.chat_request(instruction))
    def save_input(self):
        if self.owner.work and not self.owner.loading:
            self.owner.work.store.set_setting('v2_chat_input',self.input.toPlainText())
    def refresh(self):
        self.chat.clear()
        if not self.owner.work:
            self.chat.setPlainText('可以先生成作品，也可以告诉我你的想法'); return
        store=self.owner.work.store; thread=ChatService(store).current()
        with store.connection() as con:
            messages=con.execute('SELECT * FROM messages WHERE thread_id=? ORDER BY rowid',(thread,)).fetchall()
        for row in messages:
            text=row['content']
            if row['role']=='assistant':
                try:
                    value=__import__('json').loads(text)
                    if value.get('format')=='tt-chat-message-1': text=value['text']
                    elif isinstance(value,dict): text=value.get('explanation') or ('作品内容已显示在正文中' if 'scenes' in value or 'text' in value else text)
                except (ValueError,AttributeError): pass
            self.append('你' if row['role']=='user' else '助手',text)
        if not messages: self.chat.setPlainText('告诉我你想怎样调整这部作品')
        self.owner.loading=True; self.input.setPlainText(store.setting('v2_chat_input','')); self.owner.loading=False
        chosen=store.setting('v2_model',self.owner.options.get('default_connection'))
        self.model.blockSignals(True); self.model.setCurrentIndex(max(0,self.model.findData(chosen))); self.model.blockSignals(False)
    def append(self,who,text,undo=None):
        body=html.escape(text).replace('\n','<br>')
        extra=f'<br><a href="undo:{undo}">撤销</a>' if undo else ''
        self.chat.append(f'<p><b>{html.escape(who)}</b><br>{body}{extra}</p>')
    def action(self,url):
        if url.scheme()=='undo': self.owner.run(lambda:self.owner.undo_ai(url.path()))
    def menu(self):
        menu=QMenu(self)
        menu.addAction('新对话',lambda:self.owner.run(self.new_chat)); menu.addAction('历史对话',lambda:self.owner.run(self.history)); menu.exec(self.mapToGlobal(self.rect().topRight()))
    def new_chat(self):
        if self.owner.work: ChatService(self.owner.work.store).new(); self.refresh()
    def history(self):
        if not self.owner.work: return
        store=self.owner.work.store; menu=QMenu(self)
        with store.connection() as con: rows=con.execute('SELECT * FROM chat_threads ORDER BY rowid DESC').fetchall()
        for row in rows: menu.addAction(row['title']+' · '+row['created'][:10],lambda rid=row['id']:self.pick_thread(rid))
        menu.exec(self.mapToGlobal(self.rect().topLeft()))
    def pick_thread(self,rid): self.owner.work.store.set_setting('chat_thread',rid); self.refresh()
