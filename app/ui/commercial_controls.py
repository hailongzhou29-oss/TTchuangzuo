"""Shared desktop chrome, editor actions and truthful task feedback."""
from PySide6.QtCore import Qt,QTimer,QSize,QEvent,QRectF,QRect,QElapsedTimer
from PySide6.QtGui import QPainter,QColor,QPen,QTextCursor,QTransform,QIcon
from PySide6.QtWidgets import QWidget,QFrame,QHBoxLayout,QVBoxLayout,QToolButton,QStyle,QSizePolicy,QApplication,QDialog,QMenu,QLabel
from app.ui.v2_widgets import label,button
from app.ui.interaction import tokens,ui_font
from app.ui.icons import icon

RESIZE_EDGE_WIDTH=12
RESIZE_CORNER_WIDTH=28

class ResizeGrip(QWidget):
    """Continuous edge hit areas with native resizing and a local fallback."""
    def __init__(self,owner,edge):
        super().__init__(owner); self.owner=owner; self.edge=edge; self.dragging=False; self.setMouseTracking(True); self.setStyleSheet('background:transparent;border:0;'); self.setAccessibleName('窗口拉伸边缘')
        self.setCursor(Qt.CursorShape.SizeVerCursor if edge in (Qt.Edge.TopEdge,Qt.Edge.BottomEdge) else Qt.CursorShape.SizeHorCursor); owner.installEventFilter(self)
    def edges_at(self,point):
        edges=self.edge; position=self.owner.mapFromGlobal(point); corner=RESIZE_CORNER_WIDTH
        if self.edge in (Qt.Edge.TopEdge,Qt.Edge.BottomEdge):
            if position.x()<corner: edges|=Qt.Edge.LeftEdge
            elif position.x()>self.owner.width()-corner: edges|=Qt.Edge.RightEdge
        else:
            if position.y()<corner: edges|=Qt.Edge.TopEdge
            elif position.y()>self.owner.height()-corner: edges|=Qt.Edge.BottomEdge
        return edges
    def update_cursor(self,edges):
        horizontal=bool(edges & (Qt.Edge.LeftEdge|Qt.Edge.RightEdge)); vertical=bool(edges & (Qt.Edge.TopEdge|Qt.Edge.BottomEdge)); diagonal=bool(edges & Qt.Edge.LeftEdge)==bool(edges & Qt.Edge.TopEdge)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor if horizontal and vertical and diagonal else Qt.CursorShape.SizeBDiagCursor if horizontal and vertical else Qt.CursorShape.SizeHorCursor if horizontal else Qt.CursorShape.SizeVerCursor)
    def enterEvent(self,event):
        self.update_cursor(self.edges_at(event.globalPosition().toPoint())); super().enterEvent(event)
    def eventFilter(self,watched,event):
        if watched is self.owner and event.type() in (QEvent.Type.WindowStateChange,QEvent.Type.Show):
            self.setVisible(not self.owner.isMaximized() and not self.owner.isFullScreen()); self.raise_()
        return False
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and not self.owner.isMaximized() and not self.owner.isFullScreen():
            self.origin=event.globalPosition().toPoint(); self.drag_edges=self.edges_at(self.origin); self.update_cursor(self.drag_edges)
            handle=self.owner.windowHandle()
            if handle and not QApplication.instance().property('native_hidden_test') and handle.startSystemResize(self.drag_edges): event.accept(); return
            self.dragging=True; self.start_rect=QRect(self.owner.geometry()); self.grabMouse(); event.accept()
        else: super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        point=event.globalPosition().toPoint(); edges=self.drag_edges if self.dragging else self.edges_at(point); self.update_cursor(edges)
        if self.dragging:
            delta=point-self.origin; rect=QRect(self.start_rect)
            if edges & Qt.Edge.LeftEdge: rect.setLeft(min(self.start_rect.left()+delta.x(),self.start_rect.right()+1-self.owner.minimumWidth()))
            if edges & Qt.Edge.RightEdge: rect.setRight(max(self.start_rect.right()+delta.x(),self.start_rect.left()+self.owner.minimumWidth()-1))
            if edges & Qt.Edge.TopEdge: rect.setTop(min(self.start_rect.top()+delta.y(),self.start_rect.bottom()+1-self.owner.minimumHeight()))
            if edges & Qt.Edge.BottomEdge: rect.setBottom(max(self.start_rect.bottom()+delta.y(),self.start_rect.top()+self.owner.minimumHeight()-1))
            self.owner.setGeometry(rect); event.accept()
    def mouseReleaseEvent(self,event):
        if self.dragging: self.dragging=False; self.releaseMouse(); event.accept()

def position_resize_grips(owner):
    size=RESIZE_EDGE_WIDTH; width=owner.width(); height=owner.height()
    rectangles=[QRect(0,0,width,size),QRect(0,height-size,width,size),QRect(0,0,size,height),QRect(width-size,0,size,height)]
    for grip,rect in zip(owner.resize_grips,rectangles): grip.setGeometry(rect); grip.setVisible(not owner.isMaximized() and not owner.isFullScreen()); grip.raise_()

class SaveState(QLabel):
    def __init__(self,text,parent=None): super().__init__(parent); self.setObjectName('saveState'); self.setWordWrap(False); self.setText(text)
    def setText(self,text):
        self.setProperty('saved',any(word in str(text) for word in ('已保存','已应用','已采用','已恢复'))); super().setText(text); self.setToolTip(text); self.style().unpolish(self); self.style().polish(self)


class TitleBar(QFrame):
    def __init__(self,owner):
        super().__init__(owner); self.owner=owner; self.setObjectName('titleBar'); self.setFixedHeight(48)
        row=QHBoxLayout(self); row.setContentsMargins(16,6,8,6); row.setSpacing(10)
        mark=label(''); mark.setPixmap(owner.windowIcon().pixmap(26,26)); mark.setFixedSize(28,28); row.addWidget(mark)
        row.addWidget(label('TT创作助手','titleBrand')); row.addWidget(label('创作工作台','muted')); row.addStretch()
        self.controls=[]
        for caption,standard,action in [('最小化',QStyle.StandardPixmap.SP_TitleBarMinButton,owner.showMinimized),('最大化 / 还原',QStyle.StandardPixmap.SP_TitleBarMaxButton,self.toggle_maximized),('关闭',QStyle.StandardPixmap.SP_TitleBarCloseButton,owner.close)]:
            control=QToolButton(self); control.setObjectName('windowClose' if caption=='关闭' else 'windowControl'); control.setFixedSize(40,34); control.setIconSize(QSize(18,18)); control.setIcon(self.style().standardIcon(standard)); control.setToolTip(caption); control.setAccessibleName(caption); control.clicked.connect(action); row.addWidget(control); self.controls.append(control)
        self.refresh_icons()
    def refresh_icons(self):
        color=tokens(self)['text']
        standards=(QStyle.StandardPixmap.SP_TitleBarMinButton,QStyle.StandardPixmap.SP_TitleBarNormalButton if self.owner.isMaximized() else QStyle.StandardPixmap.SP_TitleBarMaxButton)
        for control,standard in zip(self.controls,standards):
            pixmap=self.style().standardIcon(standard).pixmap(18,18); painter=QPainter(pixmap); painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn); painter.fillRect(pixmap.rect(),QColor(color)); painter.end(); control.setIcon(QIcon(pixmap))
        self.controls[2].setIcon(icon('x',color,18))
    def toggle_maximized(self):
        self.owner.showNormal() if self.owner.isMaximized() else self.owner.showMaximized()
        self.refresh_icons(); self.controls[1].setToolTip('还原' if self.owner.isMaximized() else '最大化')
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            handle=self.owner.windowHandle()
            if handle and handle.startSystemMove(): return
            self.drag_offset=event.globalPosition().toPoint()-self.owner.frameGeometry().topLeft()
        super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(self,'drag_offset') and not self.owner.isMaximized(): self.owner.move(event.globalPosition().toPoint()-self.drag_offset)
        super().mouseMoveEvent(event)
    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton: self.toggle_maximized(); event.accept()


class BusyIndicator(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent); self.setFixedSize(20,20); self.angle=0; self.timer=QTimer(self); self.timer.setInterval(40); self.timer.timeout.connect(self.tick)
    def tick(self): self.angle=(self.angle+16)%360; self.update()
    def set_running(self,running):
        self.timer.start() if running else self.timer.stop(); self.setVisible(running)
    def paintEvent(self,event):
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing); color=tokens(self)['accent']; painter.setPen(QPen(QColor(color),2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap)); painter.drawArc(QRectF(3,3,14,14),self.angle*16,260*16)


class TaskStatus(QFrame):
    def __init__(self,page):
        super().__init__(page); self.page=page; self.in_header=False; self.setObjectName('taskStatus'); self.setFixedHeight(40); self.setMinimumWidth(270); row=QHBoxLayout(self); row.setContentsMargins(12,3,12,3); row.setSpacing(8)
        self.spinner=BusyIndicator(self); self.spinner.hide(); row.addWidget(self.spinner)
        words=QVBoxLayout(); words.setContentsMargins(0,0,0,0); words.setSpacing(0); self.caption=label('','taskStatusText'); self.caption.setFixedHeight(19); self.caption.setMinimumWidth(180); self.caption.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed); words.addWidget(self.caption)
        self.detail=label('','taskStatusDetail'); self.detail.setFixedHeight(15); self.detail.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed); words.addWidget(self.detail); row.addLayout(words,1)
        self.message=''; self.busy=False; self.elapsed=QElapsedTimer(); self.hide(); self.clear_timer=QTimer(self); self.clear_timer.setSingleShot(True); self.clear_timer.timeout.connect(lambda:self.setText('')); self.feedback_timer=QTimer(self); self.feedback_timer.setInterval(1000); self.feedback_timer.timeout.connect(self.render_feedback)
    def text(self): return self.message
    def setText(self,text):
        self.clear_timer.stop(); self.message=str(text or '').strip(); tone='error' if any(x in self.message for x in ('失败','异常')) else 'warning' if any(x in self.message for x in ('冲突','变化','待确认','待应用','不同步','未完成')) else 'success' if any(x in self.message for x in ('已保存','已完成','已复制','已更新','已应用')) else 'normal'
        self.caption.setProperty('tone',tone); self.caption.style().unpolish(self.caption); self.caption.style().polish(self.caption); self.render_feedback(); self.setToolTip(self.message); self.sync_visibility()
        if tone=='success' and self.in_header and not self.busy: self.clear_timer.start(2200)
    def sync_visibility(self):
        visible=bool(self.message) or self.busy
        if self.in_header: visible=visible and self.page.owner.current_page() is self.page
        self.setVisible(visible)
        stack=getattr(self.page,'status_stack',None)
        if stack and stack.currentWidget() is self: stack.setVisible(visible)
    def set_busy(self,busy):
        busy=bool(busy)
        if busy and not self.busy: self.elapsed.start(); self.feedback_timer.start(); self.clear_timer.stop()
        elif not busy: self.feedback_timer.stop()
        self.busy=busy; self.spinner.set_running(busy); self.render_feedback(); self.sync_visibility()
    def render_feedback(self):
        message=self.message
        if self.busy:
            seconds=max(0,self.elapsed.elapsed()//1000); stage='正在停止' if '停止' in message else '正在保存' if '保存' in message else '正在读取模型' if '读取模型' in message else '正在检测连接' if '检测' in message or '测试' in message else '正在整理改稿' if '整理' in message else '正在生成改稿' if '生成改稿' in message else '正在生成正文' if '生成正文' in message else '正在接收结果' if '接收' in message or '生成回复' in message else '正在检查' if '检查' in message else '正在构思改稿' if '改稿' in message else '正在处理任务' if '处理任务' in message else '正在构思'
            phrases={'正在构思':('正在整理你的想法','人物正在酝酿台词','给故事找个好开场'),'正在构思改稿':('正在理解修改要求','先理清思路，再动笔'),'正在生成正文':('故事正在落到纸上','给角色一点发挥空间'),'正在生成改稿':('按你的要求重新打磨','正在收拾剧情里的线头'),'正在检查':('正在逐项核对内容',),'正在接收结果':('正在接收完整回复',),'正在整理改稿':('整理候选，原稿先保留',),'正在保存':('新版本正在归档',),'正在停止':('正在等待本地任务结束',)}
            phrases.update({'正在读取模型':('正在获取可选模型列表',),'正在检测连接':('正在核对连接结果',),'正在处理任务':('完成后会更新状态',)})
            choices=phrases[stage]; caption=f'{stage} · {seconds//60:02d}:{seconds%60:02d}'; detail=choices[(seconds//8)%len(choices)]
        else:
            caption='改稿待应用' if '待应用' in message else '正文已保存 · 摘要未完成' if '摘要未完成' in message and '已保存' in message else '已应用并保存' if '已应用' in message else '已保存' if '已保存' in message else message
            detail='原稿未改变，核对后再应用' if '待应用' in message else '正文完整，摘要可稍后补齐' if '摘要未完成' in message and '已保存' in message else '新版本已归档，原版本保留' if '已应用' in message else '内容已落盘' if '已保存' in message else ''
        self.caption.setText(self.caption.fontMetrics().elidedText(caption,Qt.TextElideMode.ElideRight,max(180,self.caption.width()))); self.caption.setToolTip(message); self.detail.setText(detail); self.detail.setVisible(bool(detail))
    def resizeEvent(self,event): super().resizeEvent(event); self.render_feedback()


class EditorToolbar(QFrame):
    def __init__(self,page):
        super().__init__(page); self.page=page; self.setObjectName('editorToolbar'); self.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        self.outer=QVBoxLayout(self); self.outer.setContentsMargins(8,6,8,6); self.outer.setSpacing(4); self.main=QHBoxLayout(); self.main.setSpacing(4); self.secondary=QHBoxLayout(); self.secondary.setSpacing(4); self.outer.addLayout(self.main); self.outer.addLayout(self.secondary)
        self.main.addWidget(page.directory); page.location.setMinimumWidth(100); page.location.setMaximumWidth(240); page.location.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed); self.main.addWidget(page.location,1); page.location.show()
        self.actions={}
        for name,shape,callback in [('撤销','arrow-right',page.editor.undo),('重做','arrow-right',page.editor.redo),('查找','search',page.show_find),('版本历史','history',lambda:page.owner.run(page.owner.show_versions)),('阅读模式','book',lambda:page.owner.read_mode(page))]:
            action=button('' if name in {'撤销','重做','查找'} else name,callback,quiet=True); action.setObjectName('toolAction'); action.setToolTip({'撤销':'撤销编辑 · Ctrl+Z','重做':'重做编辑 · Ctrl+Y','查找':'查找正文 · Ctrl+F'}.get(name,name)); action.setAccessibleName(name); action.setFixedHeight(34)
            if name in {'撤销','重做','查找'}: action.setFixedWidth(34)
            self.main.addWidget(action); self.actions[name]=action
        self.actions['阅读模式'].setCheckable(True)
        self.main.addStretch(1)
        self.movable=[page.font_controls,page.cover_button,page.export_button]
        for widget in self.movable: self.main.addWidget(widget); widget.show()
        page.editor.undoAvailable.connect(self.actions['撤销'].setEnabled); page.editor.redoAvailable.connect(self.actions['重做'].setEnabled); page.editor.textChanged.connect(self.refresh)
        self.secondary.addStretch(1); self.secondary_host=None; self.compact=False; self.refresh_icons(); self.refresh()
    def refresh_icons(self):
        color=tokens(self)['muted']
        for name,shape in [('撤销','arrow-right'),('重做','arrow-right'),('查找','search'),('版本历史','history'),('阅读模式','book')]:
            image_icon=icon(shape,color,18)
            if name=='撤销': image_icon=QIcon(image_icon.pixmap(36,36).transformed(QTransform().rotate(180)))
            self.actions[name].setIcon(image_icon); self.actions[name].setIconSize(QSize(18,18))
    def refresh(self):
        comparing=bool(getattr(self.page,'candidate_pane',None)); self.actions['撤销'].setEnabled(not comparing and self.page.editor.document().isUndoAvailable()); self.actions['重做'].setEnabled(not comparing and self.page.editor.document().isRedoAvailable())
        work=self.page.owner.works.get(self.page.kind); self.actions['版本历史'].setEnabled(bool(work)); self.page.cover_button.setEnabled(bool(work)); self.page.export_button.setEnabled(bool(self.page.editor.toPlainText().strip()))
        self.refresh_read_state()
    def refresh_read_state(self):
        reading=bool(self.page.owner.reading and getattr(self.page.owner,'read_page',None) is self.page); action=self.actions['阅读模式']; action.setChecked(reading); action.setText('' if self.width()<590 else '退出阅读' if reading else '阅读模式'); action.setToolTip('退出阅读 · Esc' if reading else '阅读模式')
    def resizeEvent(self,event):
        super().resizeEvent(event); compact=self.width()<800
        if compact!=self.compact:
            self.compact=compact
            for widget in self.movable:
                self.main.removeWidget(widget); self.secondary.removeWidget(widget)
                if compact: self.secondary.insertWidget(self.secondary.count()-1,widget)
                else: self.main.addWidget(widget)
            for name in ('版本历史','阅读模式'): self.actions[name].setText('' if self.width()<590 else name)
        self.refresh_read_state()
        self.setFixedHeight(92 if compact else 52)


class EditorFooter(QFrame):
    def __init__(self,page):
        super().__init__(page); self.page=page; self.setObjectName('creationFooter'); self.setFixedHeight(64); row=QHBoxLayout(self); row.setContentsMargins(24,10,24,10); row.setSpacing(8)
        page.model_summary.setWordWrap(False); page.model_summary.setMinimumWidth(0); row.addWidget(page.model_summary,1)
        self.word_count=label('0 字','wordCount'); self.word_count.setWordWrap(False); row.addWidget(self.word_count)
        self.copy_button=button('复制完整正文',self.copy_all); self.copy_button.setToolTip('复制当前正文的全部内容，不受选区影响'); row.addWidget(self.copy_button)
        self.book_copy=button('复制整本',lambda:page.owner.run(self.copy_book),quiet=True); self.book_copy.setToolTip('按章节顺序复制整本小说正文'); self.book_copy.hide(); row.addWidget(self.book_copy)
        page.generate_button.setMinimumWidth(144); row.addWidget(page.generate_button); self.reset=QTimer(self); self.reset.setSingleShot(True); self.reset.timeout.connect(lambda:self.copy_button.setText('复制完整正文'))
        page.editor.textChanged.connect(self.refresh); self.refresh()
    def refresh(self):
        text=self.page.editor.toPlainText(); count=sum(not ch.isspace() for ch in text); self.word_count.setText(f'{count:,} 字'); self.copy_button.setEnabled(bool(text.strip()))
        work=self.page.owner.works.get(self.page.kind); novel=bool(work and work.config.get('output')=='novel'); self.book_copy.setVisible(novel and (work.config.get('length')=='长篇连载' or self.page.chapters.count()>2))
        self.page.model_summary.setToolTip(self.page.model_summary.text())
    def copy_all(self):
        text=self.page.editor.toPlainText()
        if not text.strip(): return
        QApplication.clipboard().setText(text); self.copy_button.setText('已复制'); self.reset.start(1600)
    def copy_book(self):
        work=self.page.owner.works.get(self.page.kind)
        if not work: return
        self.page.owner.save_work()
        from app.core.writing_views import chapter_documents
        texts=[work.store.document(row['id'])['text'] for row in chapter_documents(work.store)]; text='\n\n'.join(text for text in texts if text.strip())
        if text.strip(): QApplication.clipboard().setText(text); self.page.notify('整本小说正文已复制')
    def resizeEvent(self,event):
        super().resizeEvent(event); self.word_count.setVisible(self.width()>=650); self.page.model_summary.setVisible(self.width()>=560); self.copy_button.setText('复制全文' if self.width()<560 else '复制完整正文')


def install_editor_chrome(page):
    old_tools=page.body_view.layout().takeAt(0).layout()
    while old_tools.count():
        item=old_tools.takeAt(0)
        if item.widget(): item.widget().hide()
    old_tools.deleteLater()
    page.editor_toolbar=EditorToolbar(page); page.body_view.layout().insertWidget(0,page.editor_toolbar)
    old_footer=page.findChild(QFrame,'creationFooter'); root=page.layout(); position=root.indexOf(old_footer); root.removeWidget(old_footer)
    page.editor_footer=EditorFooter(page); root.insertWidget(position,page.editor_footer); old_footer.deleteLater()
    old_banner=page.banner; position=root.indexOf(old_banner); root.removeWidget(old_banner); page.banner=TaskStatus(page); root.insertWidget(position,page.banner); old_banner.deleteLater()
    old_saved=page.saved; header=page.view_header.layout(); position=header.indexOf(old_saved); header.removeWidget(old_saved); page.saved=SaveState(old_saved.text()); header.insertWidget(position,page.saved); old_saved.deleteLater()
    page.view_header.setFixedHeight(48)


class CoverDialog(QDialog):
    def __init__(self,owner,panel):
        super().__init__(owner); self.owner=owner; self.panel=panel; self.setWindowTitle('作品封面 · '+panel.title.text()); self.setWindowIcon(owner.windowIcon()); self.setWindowModality(Qt.WindowModality.WindowModal)
        if QApplication.instance().property('native_hidden_test'): self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.setMinimumSize(720,570); self.resize(1000,740); col=QVBoxLayout(self); col.setContentsMargins(24,20,24,20); head=QHBoxLayout(); head.addWidget(label('作品封面','heading'),1); head.addWidget(button('关闭',self.close,quiet=True)); col.addLayout(head); col.addWidget(panel,1)
        self.return_focus=QApplication.focusWidget(); self.home_scroll=owner.home.scroll.verticalScrollBar().value()
    def closeEvent(self,event):
        active=self.owner.active_image_task
        if active and active[0] is self.panel:
            if not hasattr(self.owner,'retired_cover_dialogs'): self.owner.retired_cover_dialogs=[]
            self.owner.retired_cover_dialogs.append(self)
        else: self.deleteLater()
        if getattr(self.owner,'cover_dialog',None) is self: self.owner.cover_dialog=None
        self.owner.home.scroll.verticalScrollBar().setValue(self.home_scroll)
        if self.return_focus:
            from shiboken6 import isValid
            if isValid(self.return_focus): self.return_focus.setFocus()
        super().closeEvent(event)
