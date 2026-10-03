"""Shared manuscript/candidate comparison with durable identity and no model calls."""
import difflib
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QTextCursor,QTextCharFormat,QColor
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QTabBar,QSplitter,QTextEdit,QCheckBox
from app.ui.v2_widgets import button,label,QComboBox
from app.ui.interaction import ui_font,tokens
from app.core.agent_candidates import AgentCandidates,readonly_fragment_text

class CandidateView(QWidget):
    def __init__(self,owner,page,cid=None):
        super().__init__(); self.owner=owner; self.page=page; self.work=owner.work; self.service=AgentCandidates(self.work.store); self.syncing=False
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        row=QHBoxLayout(); self.pick=QComboBox(); self.pick.setObjectName('candidatePicker'); row.addWidget(self.pick,1); row.addWidget(button('返回正文',lambda:owner.close_candidates(page),quiet=True)); layout.addLayout(row)
        self.entries=self.service.history(self.work)
        names={'pending':'待应用','partial':'未完成片段·不可应用','stale':'已失效·不可应用','applied':'已应用','undone':'已撤销','discarded':'已放弃'}
        for entry in self.entries:
            data=self.service.row(entry['id']); self.pick.addItem(names.get(entry['state'],entry['state'])+' · '+data.get('created','')[:19]+' · '+(data.get('snapshot') or {}).get('instruction',data.get('reason',''))[:24],entry['id'])
        self.notice=label('','muted'); self.notice.setWordWrap(True); layout.addWidget(self.notice)
        nav=QHBoxLayout(); self.modes=QTabBar(); self.modes.addTab('原稿'); self.modes.addTab('改稿'); self.modes.addTab('对比'); self.modes.setExpanding(False); nav.addWidget(self.modes); nav.addStretch(); self.previous=button('上一处',lambda:self.jump(-1),quiet=True); self.next=button('下一处',lambda:self.jump(1),quiet=True); nav.addWidget(self.previous); nav.addWidget(self.next); layout.addLayout(nav)
        self.split=QSplitter(); self.left=QTextEdit(); self.right=QTextEdit(); self.left.setReadOnly(True); self.right.setReadOnly(True); self.left.setAcceptRichText(False); self.right.setAcceptRichText(False); self.split.addWidget(self.left); self.split.addWidget(self.right); self.split.setChildrenCollapsible(False); layout.addWidget(self.split,1)
        font=ui_font(); font.setPixelSize(owner.options.get('editor_font_size',18))
        for editor in (self.left,self.right): editor.setObjectName('candidateEditor'); editor.setFont(font); editor.document().setDefaultFont(font)
        self.confirm=QCheckBox('我已核对替换正文和作用范围'); self.confirm.hide(); layout.addWidget(self.confirm)
        self.adopt_button=button('应用到正文并保存',lambda:owner.run(self.adopt),True); self.adopt_button.setAccessibleName('应用到正文并保存'); layout.addWidget(self.adopt_button)
        self.confirm.toggled.connect(self.update_enabled); self.pick.currentIndexChanged.connect(self.load); self.modes.currentChanged.connect(self.mode)
        self.right.textChanged.connect(self.edited_review)
        self.left.verticalScrollBar().valueChanged.connect(lambda v:self.scroll(self.left,self.right)); self.right.verticalScrollBar().valueChanged.connect(lambda v:self.scroll(self.right,self.left))
        if cid: self.pick.setCurrentIndex(max(0,self.pick.findData(cid)))
        elif self.entries: self.pick.setCurrentIndex(len(self.entries)-1)
        self.modes.setCurrentIndex(2); self.load()
    def load(self,*_):
        self._loading=True;self.constraint_conflicts=[]
        self.cid=self.pick.currentData(); self.changes=[]; self.change_index=-1; self.confirm.setChecked(False); self.state='empty'
        if not self.cid:
            self.notice.setText('当前文档没有改稿或已收到的片段'); self.left.setPlainText(self.work.text); self.right.clear(); self.adopt_button.setEnabled(False); self.previous.setEnabled(False); self.next.setEnabled(False);self._loading=False; return
        entry=next(e for e in self.service.history(self.work) if e['id']==self.cid); data=self.service.row(self.cid); snapshot=data.get('snapshot') or {}; payload=data['result'].get('candidate') or {}; self.state=entry['state']; self.review=bool(payload.get('needs_review'))
        proposed=self.service.preview(self.cid) if payload else readonly_fragment_text(data['result'].get('text',''))
        self.left.setPlainText(self.work.text); self.right.setPlainText(payload.get('text','') if self.review else proposed); self.right.setReadOnly(not self.review); self.confirm.setVisible(self.review)
        span=f'第{snapshot.get("target_start",0)+1}—{snapshot.get("target_end",0)}字' if snapshot.get('v2_task')=='modify' else '故事规划；正文保留' if snapshot.get('v2_task')=='planning' else '当前文档全文'
        self.notice.setText({'pending':'改稿待应用，原稿未改变','stale':'来源正文或创作设置已变化；仅可查看','partial':'未完成片段，仅供查看，不能应用','applied':'已应用并保存','undone':'已撤销并保存','discarded':'已放弃改稿，原稿保留'}.get(self.state,self.state)+' · '+span+('；请核对右侧替换正文' if self.review else ''))
        review_result=self.service.review(self.cid,payload.get('text') if self.review else None) if payload else {}
        self.constraint_conflicts=review_result.get('conflicts',[])
        goal=review_result.get('length')
        from app.core.quality_checks import reminder
        review_note=reminder(snapshot,proposed)
        if review_note:self.notice.setText(self.notice.text()+'\n'+review_note)
        stages=data['result'].get('postprocessing') or {}
        if stages.get('primary_status')=='completed' and stages.get('summary_status')!='completed':self.notice.setText(self.notice.text()+'\n正文完整，附属摘要未完成；摘要状态不影响正文审阅，仍需明确采用。')
        self.review_base_notice=self.notice.text()
        self.show_review_result(review_result)
        self.highlight(); self.update_enabled();self._loading=False
    def show_review_result(self,result):
        self.constraint_conflicts=result.get('conflicts',[]);goal=result.get('length');self.notice.setText(self.review_base_notice)
        if goal:
            from app.core.writing_progress import goal_status
            self.notice.setText(self.notice.text()+f'\n改稿正文{goal["actual_chars"]:,}非空白字符（汉字{goal["chinese_chars"]:,}）；'+goal_status(goal))
        for note in result.get('timeline',[]):self.notice.setText(self.notice.text()+'\n'+note['message'])
    def edited_review(self):
        if getattr(self,'_loading',True) or not getattr(self,'review',False) or not self.cid:return
        self.show_review_result(self.service.review(self.cid,self.right.toPlainText()));self.update_enabled()
    def update_enabled(self,*_):
        conflicts=getattr(self,'constraint_conflicts',[])
        self.adopt_button.setEnabled(bool(self.cid) and getattr(self,'state','')=='pending' and (not getattr(self,'review',False) or self.confirm.isChecked()) and not conflicts and not self.owner.active_task)
        reason={'stale':'来源正文或设置已改变，此改稿已失效，不能采用','partial':'未完成片段仅供查看，不能采用','applied':'此改稿已采用，不能重复采用','undone':'此改稿已撤销，不能再次采用','empty':'没有可采用的改稿'}.get(getattr(self,'state',''),'请先核对替换内容和范围')
        if self.owner.active_task: reason='请等待当前任务结束，再核对改稿'
        elif conflicts:reason=conflicts[0]['message']
        self.adopt_button.setToolTip('' if self.adopt_button.isEnabled() else reason)
    def highlight(self):
        a=self.left.toPlainText(); b=self.right.toPlainText(); selected=[[],[]]; self.changes=[]
        if max(len(a),len(b))>20000:
            first=a.splitlines(keepends=True); second=b.splitlines(keepends=True); aa=[0]; bb=[0]
            for value in first: aa.append(aa[-1]+len(value))
            for value in second: bb.append(bb[-1]+len(value))
            operations=[(tag,aa[i],aa[j],bb[k],bb[l]) for tag,i,j,k,l in difflib.SequenceMatcher(None,first,second).get_opcodes()]
        else: operations=difflib.SequenceMatcher(None,a,b,autojunk=True).get_opcodes()
        for tag,i,j,k,l in operations:
            if tag=='equal': continue
            self.changes.append((i,k))
            c=tokens(self)
            for index,start,end,color in [(0,i,j,c['diff_removed']),(1,k,l,c['diff_added'])]:
                if start==end: continue
                edit=(self.left,self.right)[index]; choice=QTextEdit.ExtraSelection(); cursor=edit.textCursor(); text=(a,b)[index]; cursor.setPosition(len(text[:start].encode('utf-16-le'))//2); cursor.setPosition(len(text[:end].encode('utf-16-le'))//2,QTextCursor.MoveMode.KeepAnchor); choice.cursor=cursor; choice.format=QTextCharFormat(); choice.format.setBackground(QColor(color)); choice.format.setForeground(QColor(c['text'])); selected[index].append(choice)
        self.left.setExtraSelections(selected[0]); self.right.setExtraSelections(selected[1]); self.previous.setEnabled(bool(self.changes)); self.next.setEnabled(bool(self.changes))
    def view_state(self):
        return [(editor.textCursor().anchor(),editor.textCursor().position(),editor.verticalScrollBar().value(),editor.horizontalScrollBar().value()) for editor in (self.left,self.right)]
    def refresh_theme(self,state=None):
        state=state or self.view_state()
        font=ui_font(); font.setPixelSize(self.owner.options.get('editor_font_size',18))
        for editor in (self.left,self.right):
            blocked=editor.blockSignals(True); editor.setFont(font); editor.document().setDefaultFont(font); editor.blockSignals(blocked)
        self.highlight()
        def restore():
            for editor,(anchor,position,vertical,horizontal) in zip((self.left,self.right),state):
                cursor=editor.textCursor(); limit=editor.document().characterCount()-1; cursor.setPosition(min(anchor,limit)); cursor.setPosition(min(position,limit),QTextCursor.MoveMode.KeepAnchor); editor.setTextCursor(cursor)
                scrollbar=editor.verticalScrollBar(); blocked=scrollbar.blockSignals(True); scrollbar.setValue(vertical); scrollbar.blockSignals(blocked); editor.horizontalScrollBar().setValue(horizontal)
        restore(); QTimer.singleShot(0,self,restore)
    def jump(self,step):
        if not self.changes:return
        self.change_index=(self.change_index+step)%len(self.changes)
        for edit,offset in zip((self.left,self.right),self.changes[self.change_index]):
            cursor=edit.textCursor(); cursor.setPosition(len(edit.toPlainText()[:offset].encode('utf-16-le'))//2); edit.setTextCursor(cursor); edit.ensureCursorVisible()
    def scroll(self,source,target):
        if self.syncing:return
        self.syncing=True; first=source.verticalScrollBar(); second=target.verticalScrollBar(); second.setValue(round(first.value()/max(1,first.maximum())*second.maximum())); self.syncing=False
    def mode(self,index): self.left.setVisible(index!=1); self.right.setVisible(index!=0)
    def resizeEvent(self,event):
        super().resizeEvent(event); self.split.setOrientation(Qt.Orientation.Vertical if self.width()<680 else Qt.Orientation.Horizontal)
    def adopt(self):
        if self.owner.work is not self.work or self.owner.active_task: raise ValueError('请回到改稿所属作品，等待当前任务结束后核对')
        if self.review and not self.confirm.isChecked(): raise ValueError('请先核对替换正文与范围，并勾选确认')
        receipt=self.service.adopt(self.cid,self.work,self.right.toPlainText() if self.review else None)
        self.owner.finish_candidate_application(self.page,self.work)
