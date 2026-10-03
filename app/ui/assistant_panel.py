import html
import re
from PySide6.QtCore import Qt,QTimer,QPoint
from PySide6.QtGui import QTextCursor,QTextBlockFormat
from PySide6.QtWidgets import QFrame,QVBoxLayout,QHBoxLayout,QComboBox,QTextBrowser,QMenu
from app.ui.v2_widgets import label,button,ChatInput,QComboBox,PALETTES,QMenu
from app.core.context import ChatService
from app.ui.interaction import ui_font

def message_html(text,font_size=16):
    paragraphs=[]
    for line in str(text).splitlines():
        safe=html.escape(line); safe=re.sub(r'\*\*(.+?)\*\*',r'<b>\1</b>',safe)
        if line.startswith(('# ','## ','### ')): paragraphs.append(f'<p style="font-size:{font_size+2}px;font-weight:600;margin-top:12px;margin-bottom:6px;">'+safe.lstrip('# ')+'</p>')
        elif line.startswith(('- ','* ')): paragraphs.append(f'<p style="font-size:{font_size}px;margin-top:4px;margin-bottom:6px;margin-left:10px;">• '+safe[2:]+'</p>')
        elif not line.strip(): paragraphs.append('<p style="margin-top:8px;"></p>')
        else: paragraphs.append(f'<p style="font-size:{font_size}px;margin-top:4px;margin-bottom:6px;">'+safe+'</p>')
    return ''.join(paragraphs)

def display_reply(text):
    """Unwrap stored protocol separately from the user-facing output contract."""
    import json
    for _ in range(3):
        try: value=json.loads(text)
        except (ValueError,TypeError): return text
        if not isinstance(value,dict): return text
        if value.get('format')=='tt-chat-message-1': text=value.get('text',''); continue
        if isinstance(value.get('explanation'),str) and value['explanation'].strip(): return value['explanation']
        if 'scenes' in value: return '作品候选已保存，请比较后采用。'
        if isinstance(value.get('text'),str): return value['text']
        return text
    return text

class AssistantPanel(QFrame):
    def __init__(self,owner):
        super().__init__(); self.owner=owner; self.setObjectName('assistant'); self.setMinimumWidth(300); self.message_rows=[]; self.rendered_rows=[]
        try: self.font_size=max(14,min(24,int(owner.options.get('assistant_font_size',16))))
        except (TypeError,ValueError): self.font_size=16
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)
        header=QFrame(); header.setObjectName('assistantHeader'); head=QHBoxLayout(header); head.setContentsMargins(22,24,18,20); head.addWidget(label('AI 助手','sectionHeading'),1)
        self.font_controls=QFrame(); self.font_controls.setObjectName('assistantFontControls'); controls=QHBoxLayout(self.font_controls); controls.setContentsMargins(0,0,0,0); controls.setSpacing(3); self.font_controls.setFixedWidth(96)
        self.font_less=button('−',lambda:self.set_font_size(self.font_size-1)); self.font_value=button(str(self.font_size),lambda:self.set_font_size(16)); self.font_more=button('+',lambda:self.set_font_size(self.font_size+1))
        for control,width,name in [(self.font_less,28,'缩小助手字号'),(self.font_value,34,'恢复助手默认字号'),(self.font_more,28,'放大助手字号')]: control.setFixedSize(width,30); control.setAccessibleName(name); control.setToolTip(name); controls.addWidget(control)
        head.addWidget(self.font_controls)
        more=button('…',self.menu,quiet=True); more.setToolTip('对话'); head.addWidget(more); layout.addWidget(header)
        context=label('当前作品 · 自动读取最新内容','muted'); self.context_label=context; context.setContentsMargins(22,18,22,10); layout.addWidget(context)
        self.scope=button('',self.clear_scope,quiet=True); self.scope.hide(); layout.addWidget(self.scope)
        self.chat=QTextBrowser(); self.chat.setObjectName('chat'); self.chat.setOpenLinks(False); self.chat.anchorClicked.connect(self.action); self.chat.setContentsMargins(16,8,16,8); layout.addWidget(self.chat,1)
        self.new_content=button('查看新消息',self.jump_to_latest,quiet=True); layout.addWidget(self.new_content); self.new_content.hide()
        self.candidate_box=QFrame(); self.candidate_box.setObjectName('candidateActions'); candidate_layout=QVBoxLayout(self.candidate_box); candidate_layout.setContentsMargins(22,8,22,8); candidate_layout.setSpacing(6)
        self.candidate_status=label('','candidateStatus'); candidate_layout.addWidget(self.candidate_status)
        actions=QHBoxLayout(); actions.setSpacing(6)
        self.apply_button=button('应用到正文',lambda:owner.run(lambda:owner.apply_agent_candidate(self.candidate_id)),True); actions.addWidget(self.apply_button)
        self.candidate_button=button('查看差异',lambda:owner.run(lambda:owner.show_agent_candidate(self.candidate_id))); actions.addWidget(self.candidate_button)
        self.discard_button=button('放弃',lambda:owner.run(lambda:owner.discard_agent_candidate(self.candidate_id)),quiet=True); actions.addWidget(self.discard_button); candidate_layout.addLayout(actions); layout.addWidget(self.candidate_box); self.candidate_box.hide(); self.candidate_id=None
        self.hint=label('讨论不会改变正文；修改先保存改稿','muted'); self.hint.setWordWrap(True); self.hint.setContentsMargins(22,8,22,12); layout.addWidget(self.hint)
        footer=QFrame(); footer.setObjectName('assistantFooter'); compose=QVBoxLayout(footer); compose.setContentsMargins(22,16,22,14); compose.setSpacing(12); layout.addWidget(footer)
        self.model=QComboBox(); self.model.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon); self.model.setMinimumContentsLength(12)
        self.model.currentIndexChanged.connect(self.model_changed); compose.addWidget(self.model)
        composer=QFrame(); composer.setObjectName('composer'); entry=QVBoxLayout(composer); entry.setContentsMargins(12,10,10,10); entry.setSpacing(4); compose.addWidget(composer)
        self.input=ChatInput(); self.input.setPlaceholderText('告诉我想修改哪里，也可以直接讨论'); self.input.setFixedHeight(64); self.input.send.connect(self.send)
        self.input.textChanged.connect(self.save_input); entry.addWidget(self.input)
        actions=QHBoxLayout(); actions.addStretch()
        self.send_button=button('',self.send,True); self.send_button.setAccessibleName('发送'); self.send_button.setFixedSize(32,32); self.send_button.setStyleSheet('padding:0;min-height:0;'); self.send_button.setToolTip('发送'); actions.addWidget(self.send_button); entry.addLayout(actions)
        self.footer_note=label('Enter 发送 · Shift+Enter 换行','muted'); compose.addWidget(self.footer_note)
        self.header=header; self.compose_layout=compose; self.entry_layout=entry; self.compact=False
        self.chat.setMinimumHeight(56); self._history_views={}; self.refresh_models(); self.apply_fonts()
    def apply_fonts(self):
        font=ui_font(); font.setPixelSize(self.font_size)
        for edit in (self.chat,self.input): edit.setStyleSheet(f'font-size:{self.font_size}px;'); edit.setFont(font); edit.document().setDefaultFont(font)
        self.font_value.setText(str(self.font_size)); self.font_value.setToolTip(f'助手字号 {self.font_size} · 点击恢复16'); self.font_less.setEnabled(self.font_size>14); self.font_more.setEnabled(self.font_size<24)
    def chat_view_state(self):
        scrollbar=self.chat.verticalScrollBar(); cursor=self.chat.textCursor(); reading=self.chat.cursorForPosition(QPoint(8,8))
        return dict(scroll=scrollbar.value(),bottom=scrollbar.value()>=scrollbar.maximum()-8,anchor=cursor.anchor(),position=cursor.position(),reading=reading.position(),reading_y=self.chat.cursorRect(reading).top())
    def set_font_size(self,size):
        size=max(14,min(24,int(size)))
        if size==self.font_size: return
        state=self.chat_view_state(); self.font_size=size; self.owner.options['assistant_font_size']=size; self.owner.save_options(); self.apply_fonts(); self.apply_theme(reuse_text=True,view_state=state)
    def set_compact(self,compact):
        if self.compact==compact: return
        self.compact=compact; self.header.setVisible(not compact); self.hint.setVisible(not compact); self.footer_note.setVisible(not compact)
        self.context_label.setContentsMargins(12,6,12,4) if compact else self.context_label.setContentsMargins(22,18,22,10)
        self.compose_layout.setContentsMargins(12,6,12,6) if compact else self.compose_layout.setContentsMargins(22,16,22,14); self.compose_layout.setSpacing(4 if compact else 12)
        self.entry_layout.setContentsMargins(8,4,8,4) if compact else self.entry_layout.setContentsMargins(12,10,10,10); self.input.setFixedHeight(40 if compact else 64)
        self.refresh_candidates()
    def refresh_models(self):
        current=self.owner.options.get('default_connection'); self.model.blockSignals(True); self.model.clear(); self.model.addItem('选择模型',None)
        for c in self.owner.connections.all():
            fixture=c.verification.get('development_test') or any(x in (c.name+' '+c.model+' '+c.id).casefold() for x in ('fixture','固定响应'))
            if c.enabled and (c.model or c.provider=='codex') and (not fixture or getattr(self.owner,'allow_test_connections',False)):
                self.model.addItem(c.name+' · '+(c.model or '跟随 Codex 默认模型'),c.id)
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
    def clear_scope(self): self.owner.bound_selection=None; self.scope.hide(); self.refresh_scope()
    def send(self):
        if self.owner.active_task: self.owner.stop_task(); return
        instruction=self.input.toPlainText().strip()
        if not instruction: return
        self.owner.run(lambda:self.owner.chat_request(instruction))
    def save_input(self):
        if self.owner.work and not self.owner.loading:
            self.owner.work.store.set_setting('v2_chat_input',self.input.toPlainText())
        self.refresh_scope()
    def refresh_scope(self):
        from app.core.work_context import intent
        action=intent(self.input.toPlainText().strip())
        span=self.owner.bound_selection
        scope=f'已选{span[1]-span[0]}字' if span and span[1]>span[0] else '当前文档／指明范围'
        self.hint.setText(('将修改 · '+scope+' · 先保存改稿' if action=='modify' else '将调整规划 · 先保存候选' if action=='planning' else '将检查 · 当前文档，正文不变' if action=='inspect' else '将讨论 · 当前作品，正文不变'))
    def refresh(self):
        previous_scope=getattr(self,'history_scope',None); previous_scroll=self.chat.verticalScrollBar().value(); previous_bottom=previous_scroll>=self.chat.verticalScrollBar().maximum()-8
        cursor=self.chat.textCursor()
        if previous_scope: self._history_views[previous_scope]=dict(scroll=previous_scroll,bottom=previous_bottom,anchor=cursor.anchor(),position=cursor.position(),selection=cursor.selectedText())
        self.chat.clear(); self.message_rows=[]; self.rendered_rows=[]; self.new_content.hide(); self._intro=False
        if not self.owner.work:
            self.candidate_box.hide(); self.history_scope=None
            self.context_label.setText('新作品 · 尚未创建正文'); self.scope.hide(); self.owner.bound_selection=None
            self.owner.loading=True; self.input.clear(); self.owner.loading=False
            self.chat.setPlainText('可以先生成作品，也可以告诉我你的想法'); self._intro=True; return
        store=self.owner.work.store; thread=ChatService(store).current()
        from app.core.agent_candidates import AgentCandidates
        candidates=AgentCandidates(store).history(self.owner.work); candidate_ids={row['id'] for row in candidates}
        self.history_scope=(store.metadata()['id'],thread,self.owner.work.document_id)
        self.context_label.setText('当前项目：'+store.metadata()['name']+' · '+store.document(self.owner.work.document_id)['title'])
        with store.connection() as con:
            messages=con.execute('SELECT * FROM messages WHERE thread_id=? ORDER BY rowid',(thread,)).fetchall()
        for row in messages:
            if row['role']=='assistant' and row['task_id'] in candidate_ids and row['state']=='completed': continue
            text=row['content']
            if row['role']=='assistant':
                if row['state']=='completed': text=display_reply(text)
                else:
                    from app.core.task_messages import failure_message
                    with store.connection() as con: task=con.execute('SELECT result FROM tasks WHERE id=?',(row['task_id'],)).fetchone()
                    import json
                    data=json.loads(task['result']) if task and task['result'] else dict(status=row['state'])
                    text=failure_message(data)
            self.append('你' if row['role']=='user' else '助手',text)
        if not messages: self.chat.setPlainText('告诉我你想怎样调整这部作品'); self._intro=True
        for candidate in candidates:
            if candidate['state']=='pending': self.append('助手','有一项尚未采用的修改候选，原稿保留。',candidate=candidate['id'])
            elif candidate['state']=='applied':
                if candidate.get('can_undo'): self.append('助手','这项修改已采用并保存正文新版本，原版本仍在。',candidate=candidate['id'],agent_undo=candidate['id'])
                else: self.append('助手','这项修改曾采用；当前正文已有后续版本，可在版本历史查看。',candidate=candidate['id'])
            elif candidate['state']=='undone': self.append('助手','这项修改已撤销并保存恢复版本，原候选不可再次采用。')
            elif candidate['state']=='stale': self.append('助手','这项改稿的来源正文或设定已变化，仅可查看。',candidate=candidate['id'])
            elif candidate['state']=='partial': self.append('助手','收到的片段已保存，仅可查看，不能采用。',candidate=candidate['id'])
        from app.core.full_book_review import FullBookReview
        for review in FullBookReview(store,self.owner.resources,self.owner.connections).pending(): self.append('助手','有一项尚未完成的整本检查。',review=review['id'])
        self.owner.loading=True; self.input.setPlainText(store.setting('v2_chat_input','')); self.owner.loading=False
        chosen=store.setting('v2_model',self.owner.options.get('default_connection'))
        self.model.blockSignals(True); self.model.setCurrentIndex(max(0,self.model.findData(chosen))); self.model.blockSignals(False)
        self.refresh_candidates()
        saved=self._history_views.get(self.history_scope)
        if saved:
            scope=self.history_scope
            def restore():
                if self.history_scope!=scope: return
                from PySide6.QtGui import QTextCursor
                limit=self.chat.document().characterCount()-1; cursor=self.chat.textCursor(); cursor.setPosition(min(saved['anchor'],limit)); cursor.setPosition(min(saved['position'],limit),QTextCursor.MoveMode.KeepAnchor)
                if cursor.selectedText()!=saved['selection']: cursor.clearSelection()
                self.chat.setTextCursor(cursor); self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum() if saved['bottom'] else min(saved['scroll'],self.chat.verticalScrollBar().maximum()))
            restore(); QTimer.singleShot(0,self,restore)
    def refresh_candidates(self):
        if not self.owner.work: self.candidate_box.hide(); return
        from app.core.agent_candidates import AgentCandidates
        work=self.owner.work; entries=AgentCandidates(work.store).history(work); pending=[row for row in entries if row['state']=='pending']
        pane=getattr(self.owner.creators[work.config['kind']],'candidate_pane',None); viewable=[row for row in entries if row['state'] in {'pending','partial','stale'}]
        selected=next((row for row in entries if pane and row['id']==pane.cid),None) or ((pending or viewable)[-1] if pending or viewable else None)
        self.candidate_id=None
        self.candidate_box.setVisible(bool(selected) and not self.compact)
        if selected:
            self.candidate_id=selected['id']; self.candidate_status.setText(f'改稿待应用 · {len(pending)}项\n应用后更新正文，原版本保留' if selected['state']=='pending' else {'partial':'未完成片段 · 仅供查看','stale':'来源已变化 · 仅供查看','applied':'已应用并保存','undone':'已撤销','discarded':'已放弃'}.get(selected['state'],'候选仅供查看'))
        can_apply=bool(selected and selected['state']=='pending') and not self.owner.active_task
        self.apply_button.setEnabled(can_apply); self.discard_button.setEnabled(can_apply); self.candidate_button.setEnabled(bool(selected))
    def candidate_message(self,cid,summary):
        from app.core.agent_candidates import AgentCandidates,readonly_fragment_text
        service=AgentCandidates(self.owner.work.store); row=service.row(cid); payload=row['result'].get('candidate') or {}
        text=service.preview(cid) if payload else readonly_fragment_text(row['result'].get('text',''))
        explanation=payload.get('explanation','').strip()
        caption='完整规划候选' if (row.get('snapshot') or {}).get('v2_task')=='planning' else '完整改稿' if payload else '已收到的片段'
        state={'pending':'待应用，原稿未改变','applied':'已应用并保存','undone':'已撤销','discarded':'已放弃'}.get(row['state'],'仅供查看')
        detail=explanation or summary
        return f'## {caption} · {state}\n{text}\n\n## 修改说明\n{detail}' if text else summary
    def append(self,who,text,undo=None,candidate=None,agent_undo=None,review=None,rendered_text=None):
        scrollbar=self.chat.verticalScrollBar(); position=scrollbar.value(); at_bottom=position>=scrollbar.maximum()-8; cursor=self.chat.textCursor()
        if getattr(self,'_intro',False): self.chat.clear(); self._intro=False
        rendered_text=rendered_text if rendered_text is not None else self.candidate_message(candidate,text) if candidate and self.owner.work else text
        self.message_rows.append((who,text,undo,candidate,agent_undo,review)); self.rendered_rows.append(rendered_text); body=message_html(rendered_text,self.font_size); start=self.chat.document().characterCount()-1
        extra=f'<br><a href="undo:{undo}">撤销本次 AI 改稿</a>' if undo else ''
        if agent_undo: extra+=f'<br><a href="agentundo:{agent_undo}">撤销本次 AI 改稿</a>'
        if review: extra+=f'<br><a href="review:{review}">继续整本检查</a>'
        c=PALETTES[self.owner.theme]
        background=c['soft'] if who=='你' else c['panel']; caption='你' if who=='你' else 'AI 助手'; extra=extra.replace('<a href=',f'<a style="color:{c["accent"]};font-weight:600;" href=')
        content=f'<p style="font-size:14px;color:{c["muted"]};margin-top:8px;margin-bottom:6px;"><b>{caption}</b></p>{body}'+(f'<p style="font-size:15px;margin-top:8px;">{extra}</p>' if extra else '')
        self.chat.append(f'<table width="100%" cellpadding="8" cellspacing="0"><tr><td bgcolor="{background}">{content}</td></tr></table>' if who=='你' else content)
        paragraph=QTextCursor(self.chat.document()); paragraph.setPosition(start); paragraph.movePosition(QTextCursor.MoveOperation.End,QTextCursor.MoveMode.KeepAnchor); spacing=QTextBlockFormat(); spacing.setLineHeight(150,QTextBlockFormat.LineHeightTypes.ProportionalHeight.value); paragraph.mergeBlockFormat(spacing)
        if not at_bottom: self.chat.setTextCursor(cursor); scrollbar.setValue(position); self.new_content.show(); QTimer.singleShot(0,self,lambda:scrollbar.setValue(position))
    def jump_to_latest(self): self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum()); self.new_content.hide()
    def apply_theme(self,reuse_text=False,view_state=None):
        rows=list(self.message_rows)
        if not rows: return
        rendered=list(self.rendered_rows); state=view_state or self.chat_view_state(); scrollbar=self.chat.verticalScrollBar(); self.chat.clear(); self.message_rows=[]; self.rendered_rows=[]
        for index,row in enumerate(rows): self.append(*row,rendered_text=rendered[index] if reuse_text else None)
        def restore():
            cursor=self.chat.textCursor(); limit=self.chat.document().characterCount()-1; cursor.setPosition(min(state['anchor'],limit)); cursor.setPosition(min(state['position'],limit),QTextCursor.MoveMode.KeepAnchor); self.chat.setTextCursor(cursor)
            if state['bottom']: self.jump_to_latest()
            else:
                scrollbar.setValue(state['scroll']); reading=QTextCursor(self.chat.document()); reading.setPosition(min(state['reading'],limit)); scrollbar.setValue(scrollbar.value()+self.chat.cursorRect(reading).top()-state['reading_y'])
        restore(); QTimer.singleShot(0,self,restore)
    def action(self,url):
        if url.scheme()=='undo': self.owner.run(lambda:self.owner.undo_ai(url.path()))
        elif url.scheme()=='candidate': self.owner.run(lambda:self.owner.show_agent_candidate(url.path()))
        elif url.scheme()=='agentundo': self.owner.run(lambda:self.owner.undo_agent_candidate(url.path()))
        elif url.scheme()=='review': self.owner.run(lambda:self.owner.resume_full_review(url.path()))
    def menu(self):
        menu=QMenu(self)
        menu.addAction('新对话',lambda:self.owner.run(self.new_chat)); menu.addAction('历史对话',lambda:self.owner.run(self.history)); menu.addAction('中断任务与恢复',lambda:self.owner.run(self.owner.show_recovery)); menu.exec(self.mapToGlobal(self.rect().topRight()))
    def new_chat(self):
        if self.owner.work: ChatService(self.owner.work.store).new(); self.refresh()
    def history(self):
        if not self.owner.work: return
        store=self.owner.work.store; menu=QMenu(self)
        with store.connection() as con: rows=con.execute('SELECT * FROM chat_threads ORDER BY rowid DESC').fetchall()
        for row in rows: menu.addAction(row['title']+' · '+row['created'][:10],lambda _checked=False,rid=row['id']:self.pick_thread(rid))
        menu.exec(self.mapToGlobal(self.rect().topLeft()))
    def pick_thread(self,rid): self.owner.work.store.set_setting('chat_thread',rid); self.refresh()
