"""Shared popup, pointer/keyboard states and interruptible local motion."""
import ctypes
import os
from PySide6.QtCore import Qt,QEvent,QObject,QPoint,QTimer,QVariantAnimation,QEasingCurve,Signal,QRectF
from PySide6.QtGui import QColor,QPainter,QPen,QFont,QFontDatabase,QKeyEvent
from PySide6.QtWidgets import QWidget,QFrame,QVBoxLayout,QHBoxLayout,QListWidget,QListWidgetItem,QStyledItemDelegate,QLineEdit,QPushButton,QApplication,QGraphicsOpacityEffect,QAbstractItemView,QLabel

TOKENS={
 '清透白':dict(window='#F6F7FB',panel='#FFFFFF',text='#202534',muted='#5F6677',input_border='#8A90A0',border='#E1E4EC',accent='#5941D7',button='#FFFFFF',soft='#F0EDFC',selected='#E6DFFD',error='#B42318'),
 '石墨紫':dict(window='#141821',panel='#1B202C',text='#F1F3F9',muted='#ABB3C5',input_border='#68758B',border='#343C4E',accent='#B5A4FF',button='#171328',soft='#2A3043',selected='#393352',error='#FFB4AB'),
 '暖纸色':dict(window='#F5F0E8',panel='#FFFDF8',text='#302B25',muted='#706456',input_border='#93816B',border='#DED4C5',accent='#765632',button='#FFFFFF',soft='#F0E7DB',selected='#E8D8C3',error='#A82820')}

# Restore the original three theme colors while retaining shared state tokens.
from app.ui.theme import THEMES
for _name,_original in [('清透白','雾白浅色'),('石墨紫','石墨深色'),('暖纸色','暖纸写作')]:
    _base=THEMES[_original]
    TOKENS[_name].update({key:_base[key] for key in ('window','panel','text','muted','border','accent','button','soft')})
TOKENS['清透白']['selected']='#DEE7FF'
TOKENS['清透白'].update(window='#F5F7FB',panel='#FFFFFF',text='#202939',muted='#526174',input_border='#B8C3D1',border='#DCE3ED',soft='#EFF4FF')
TOKENS['暖纸色'].update(window='#F5F1E9',panel='#FFFCF6',text='#292724',muted='#625C54',input_border='#BFB4A5',border='#D9D0C2',soft='#EFE6D8',selected='#E9DCC8')

def system_high_contrast():
    if os.name!='nt': return False
    class HighContrast(ctypes.Structure): _fields_=[('size',ctypes.c_uint),('flags',ctypes.c_uint),('scheme',ctypes.c_wchar_p)]
    state=HighContrast(); state.size=ctypes.sizeof(state)
    return bool(ctypes.windll.user32.SystemParametersInfoW(0x42,state.size,ctypes.byref(state),0) and state.flags & 1)

def theme_tokens(theme):
    color=dict(TOKENS[theme]); color['selected_text']=color['accent']; color['item_selected_text']=color['text']
    color.update(dict(zip(('diff_removed','diff_added'),{'清透白':('#FBE9E7','#E3F3E9'),'石墨紫':('#432D35','#203D36'),'暖纸色':('#F2E1D6','#E2EBD9')}[theme])))
    color.update(success='#86D9B4' if theme=='石墨紫' else '#18794E',warning='#F4C06A' if theme=='石墨紫' else '#946200',info='#A5C8FF' if theme=='石墨紫' else '#2456A6')
    if system_high_contrast():
        def system_color(index):
            value=ctypes.windll.user32.GetSysColor(index); return '#%02X%02X%02X'%(value & 255,(value>>8)&255,(value>>16)&255)
        color.update(window=system_color(5),panel=system_color(5),text=system_color(8),muted=system_color(17),input_border=system_color(8),border=system_color(8),accent=system_color(13),button=system_color(14),soft=system_color(15),selected=system_color(13),selected_text=system_color(14),item_selected_text=system_color(14),error=system_color(8))
    return color

def tokens(widget):
    current=widget
    while current:
        if getattr(current,'theme',None) in TOKENS: return theme_tokens(current.theme)
        current=current.parentWidget()
    return theme_tokens('清透白')

def ui_font():
    global _font_family
    if '_font_family' in globals():
        font=QFont(_font_family); font.setPixelSize(16); font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferQuality); font.setHintingPreference(QFont.HintingPreference.PreferFullHinting); return font
    families=set(QFontDatabase.families())
    candidates=['Microsoft YaHei UI','微软雅黑 UI','Microsoft YaHei','微软雅黑','Noto Sans SC','Noto Sans CJK SC','Source Han Sans CN','思源黑体 CN','DengXian','SimHei']
    # Offscreen Qt lacks the Windows font database; load the same installed font.
    if os.name=='nt' and not any(f in families for f in candidates):
        from pathlib import Path
        for filename in ['msyh.ttc','msyhbd.ttc']:
            path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/filename
            if path.is_file(): QFontDatabase.addApplicationFont(str(path))
        families=set(QFontDatabase.families())
    family=next((f for f in candidates if f in families),QApplication.font().family())
    _font_family=family
    font=QFont(family); font.setPixelSize(16); font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferQuality); font.setHintingPreference(QFont.HintingPreference.PreferFullHinting); return font

class AnimatedButton(QPushButton):
    """Stable hit target; interruptible color feedback never moves the layout."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs); self.hover_progress=0.0; self.hover_animation=QVariantAnimation(self); self.hover_animation.setStartValue(0.0); self.hover_animation.setEndValue(0.0); self.hover_animation.setDuration(120); self.hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic); self.hover_animation.valueChanged.connect(self._progress)
    def _progress(self,value):
        if value is None: return
        self.hover_progress=max(0.0,min(1.0,float(value))); self.update()
    def _hover(self,value):
        self.hover_animation.stop(); motion=getattr(self.window(),'motion',None)
        if motion and motion.reduced(): self._progress(value); return
        self.hover_animation.setStartValue(self.hover_progress); self.hover_animation.setEndValue(value); self.hover_animation.start()
    def enterEvent(self,event): self._hover(1.0); super().enterEvent(event)
    def leaveEvent(self,event): self._hover(0.0); super().leaveEvent(event)
    def hideEvent(self,event): self.hover_animation.stop(); self.hover_progress=0; super().hideEvent(event)
    def paintEvent(self,event):
        c=tokens(self); role=self.objectName(); active=bool(self.property('activeProvider')); primary=role=='primary' and not active; quiet=role in {'quiet','sidebarAction','projectAction','toolAction'}
        base=QColor(c['accent'] if primary else c['panel']); target=QColor(c['accent']).lighter(112) if primary else QColor(c['soft'])
        if quiet: base=QColor(c['panel']); base.setAlpha(0)
        if self.isChecked(): base=QColor(c['selected']); target=base
        if active: base=QColor(c['soft']); target=base
        amount=1.0 if self.isDown() else self.hover_progress
        background=QColor.fromRgbF(*[base.getRgbF()[i]+(target.getRgbF()[i]-base.getRgbF()[i])*amount for i in range(4)])
        foreground=QColor(c['success'] if active else c['button'] if primary else c['error'] if self.property('danger') else c['accent'] if self.isChecked() or role=='projectAction' else c['text'])
        border=QColor(c['accent'] if primary or self.hasFocus() else c['border']); border.setAlpha(0 if quiet and not self.hasFocus() and role!='projectAction' else 255)
        if not self.isEnabled() and not active: background=QColor(c['window']); foreground=QColor(c['muted']); border=QColor(c['border'])
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing); painter.setBrush(background); painter.setPen(QPen(border,1.5 if self.hasFocus() else 1)); painter.drawRoundedRect(QRectF(self.rect()).adjusted(1,1,-1,-1),8,8)
        painter.setFont(self.font()); painter.setPen(foreground); has_icon=not self.icon().isNull(); icon_size=min(18,self.height()-12); text=self.fontMetrics().elidedText(self.text(),Qt.TextElideMode.ElideRight,max(0,self.width()-12-(icon_size+6 if has_icon else 0)))
        text_width=self.fontMetrics().horizontalAdvance(text); total=text_width+(icon_size+6 if has_icon and text else icon_size if has_icon else 0); left=max(6,(self.width()-total)//2)
        if has_icon:
            self.icon().paint(painter,left,(self.height()-icon_size)//2,icon_size,icon_size); left+=icon_size+6
        painter.drawText(self.rect().adjusted(left,0,-6,0),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,text)

def system_reduced_motion():
    if os.name=='nt':
        enabled=ctypes.c_int(1)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042,0,ctypes.byref(enabled),0): return not enabled.value
    return False

class Motion(QObject):
    def __init__(self,owner): super().__init__(owner); self.owner=owner; self.running={}; self.close_ghost=None
    def reduced(self): return self.owner.options.get('reduce_motion',system_reduced_motion())
    def fade(self,widget,duration=100,finish=None,closing=False):
        self.stop(widget)
        if self.reduced():
            if finish: finish()
            return
        effect=None
        if not widget.isWindow(): effect=QGraphicsOpacityEffect(widget); widget.setGraphicsEffect(effect)
        animation=QVariantAnimation(self); animation.setDuration(duration); animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(1.0 if closing else .35); animation.setEndValue(0.0 if closing else 1.0)
        animation.valueChanged.connect(effect.setOpacity if effect else widget.setWindowOpacity)
        def done():
            if self.running.get(widget) is not animation: return
            self.running.pop(widget,None); widget.removeEventFilter(self); widget.setGraphicsEffect(None); animation.deleteLater()
            if finish: finish()
        animation.finished.connect(done); self.running[widget]=animation; widget.installEventFilter(self); animation.start()
    def stop(self,widget):
        animation=self.running.pop(widget,None)
        if animation: animation.stop(); animation.deleteLater()
        widget.setProperty('animatingHeight',False)
        if widget.graphicsEffect(): widget.setGraphicsEffect(None)
        if widget.isWindow(): widget.setWindowOpacity(1.0)
        widget.removeEventFilter(self)
    def resize_height(self,widget,start,end,duration=200):
        self.stop(widget)
        if self.reduced() or start==end: widget.setFixedHeight(end); return
        widget.setProperty('animatingHeight',True); widget.setFixedHeight(start); animation=QVariantAnimation(self); animation.setStartValue(start); animation.setEndValue(end); animation.setDuration(duration); animation.setEasingCurve(QEasingCurve.Type.OutCubic); animation.valueChanged.connect(lambda value:widget.setFixedHeight(round(value)))
        def finish():
            if self.running.get(widget) is not animation: return
            self.running.pop(widget,None); widget.setProperty('animatingHeight',False); widget.setFixedHeight(end); animation.deleteLater()
        animation.finished.connect(finish); self.running[widget]=animation; animation.start()
    def eventFilter(self,widget,event):
        if event.type()==QEvent.Type.Hide: self.stop(widget)
        return False
    def stop_all(self):
        for widget in list(self.running): self.stop(widget)
        self.clear_close_ghost()
        tracker=getattr(self.owner,'focus_tracker',None)
        if tracker:
            for widget,layer in tracker.hover_layers.items():
                layer.animation.stop()
                layer.update_color(QColor(tokens(widget)['accent']) if widget.underMouse() else QColor(0,0,0,0))
    def clear_close_ghost(self):
        if self.close_ghost:
            self.stop(self.close_ghost); self.close_ghost.hide(); self.close_ghost.deleteLater(); self.close_ghost=None
    def dismiss_popup(self,popup):
        self.clear_close_ghost()
        if self.reduced() or not popup.isVisible(): return
        # The real popup closes immediately; a noninteractive child snapshot fades.
        ghost=QLabel(self.owner); ghost.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents); ghost.setPixmap(popup.grab()); ghost.setGeometry(self.owner.mapFromGlobal(popup.pos()).x(),self.owner.mapFromGlobal(popup.pos()).y(),popup.width(),popup.height()); self.close_ghost=ghost; ghost.show(); ghost.raise_()
        def finish():
            if self.close_ghost is ghost: self.close_ghost=None
            ghost.hide(); ghost.deleteLater()
        self.fade(ghost,80,finish,closing=True)

class HoverBoundary(QWidget):
    def __init__(self,owner,tracker):
        super().__init__(owner); self.owner=owner; self.tracker=tracker; self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents); self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground); self.setGeometry(owner.rect()); self.color=QColor(0,0,0,0); self.animation=QVariantAnimation(self); self.animation.setEasingCurve(QEasingCurve.Type.OutCubic); self.animation.valueChanged.connect(self.update_color); self.hide()
    def update_color(self,color): self.color=color; self.update()
    def target(self,hovered):
        self.animation.stop(); color=QColor(tokens(self.owner)['accent']) if hovered else QColor(0,0,0,0)
        self.show(); self.raise_()
        focus=self.tracker.layers.get(self.owner)
        if focus: focus.raise_()
        if self.tracker.owner.motion.reduced(): self.update_color(color); return
        self.animation.setDuration(80 if hovered else 100); self.animation.setStartValue(self.color); self.animation.setEndValue(color); self.animation.start()
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setPen(QPen(self.color,1)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRoundedRect(self.rect().adjusted(1,1,-2,-2),6,6)

class FocusLayer(QWidget):
    def __init__(self,owner):
        super().__init__(owner); self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents); self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.owner=owner; self.setGeometry(owner.rect()); self.hide()
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setPen(QPen(QColor(tokens(self.owner)['accent']),2)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRoundedRect(self.rect().adjusted(1,1,-2,-2),6,6)

class FocusTracker(QObject):
    def __init__(self,owner): super().__init__(owner); self.layers={}; self.hover_layers={}; self.owner=owner
    def watch(self,widget): pass
    def eventFilter(self,widget,event):
        # Each control paints one focus boundary through its own style.
        # Layering another border caused the heavy double outlines.
        return False
        kind=event.type()
        if kind==QEvent.Type.Enter and widget.isEnabled() and not widget.inherits('QTextEdit'):
            hover=self.hover_layers.get(widget)
            if hover is None: hover=HoverBoundary(widget,self); self.hover_layers[widget]=hover; widget.destroyed.connect(lambda _,w=widget:self.hover_layers.pop(w,None))
            hover.target(True)
        elif kind==QEvent.Type.Leave and widget in self.hover_layers: self.hover_layers[widget].target(False)
        elif kind==QEvent.Type.Hide and widget in self.hover_layers: self.hover_layers[widget].animation.stop(); self.hover_layers[widget].hide()
        if kind==QEvent.Type.FocusIn:
            layer=self.layers.get(widget)
            if layer is None: layer=FocusLayer(widget); self.layers[widget]=layer; widget.destroyed.connect(lambda _,w=widget:self.layers.pop(w,None))
            layer.setGeometry(widget.rect()); layer.show(); layer.raise_()
        elif kind in (QEvent.Type.FocusOut,QEvent.Type.Hide):
            if widget in self.layers: self.layers[widget].hide()
        elif kind==QEvent.Type.Resize:
            if widget in self.layers: self.layers[widget].setGeometry(widget.rect())
            if widget in self.hover_layers: self.hover_layers[widget].setGeometry(widget.rect())
        return False

class IMELineEdit(QLineEdit):
    submitted=Signal(); cancelled=Signal()
    def __init__(self,parent=None): super().__init__(parent); self.composing=False
    def inputMethodEvent(self,event):
        self.composing=bool(event.preeditString()); super().inputMethodEvent(event)
    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Enter,Qt.Key.Key_Return) and not self.composing: self.submitted.emit(); event.accept()
        elif event.key()==Qt.Key.Key_Escape and not self.composing: self.cancelled.emit(); event.accept()
        else: super().keyPressEvent(event)

class RowDelegate(QStyledItemDelegate):
    def sizeHint(self,option,index):
        size=super().sizeHint(option,index); size.setHeight(38); return size
    def paint(self,painter,option,index):
        popup=self.parent().popup; c=tokens(popup.owner); enabled=bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
        chosen=popup.is_chosen(index.data(Qt.ItemDataRole.UserRole)); hovered=index.row()==self.parent().hovered
        active=self.parent().hasFocus() and index.row()==self.parent().currentRow()
        painter.save(); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect=option.rect.adjusted(2,1,-2,-1)
        if chosen or (hovered and enabled): painter.fillRect(rect,QColor(c['selected'] if chosen else c['soft']))
        if active and enabled: painter.setPen(QPen(QColor(c['accent']),2)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawRoundedRect(rect.adjusted(1,1,-1,-1),4,4)
        mark=rect.adjusted(8,9,8,9); x=rect.left()+12; y=rect.center().y()
        if popup.multi:
            painter.setPen(QPen(QColor(c['accent'] if chosen else c['input_border']),1)); painter.setBrush(QColor(c['accent']) if chosen else Qt.BrushStyle.NoBrush); painter.drawRoundedRect(x-5,y-7,14,14,3,3)
        if chosen:
            painter.setPen(QPen(QColor(c['button'] if popup.multi else c['accent']),2)); painter.drawLine(x-2,y,x+1,y+3); painter.drawLine(x+1,y+3,x+7,y-4)
        painter.setPen(QColor(c['item_selected_text'] if chosen else c['text'] if enabled else c['muted'])); text_rect=rect.adjusted(32,0,-8,0)
        painter.drawText(text_rect,Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,painter.fontMetrics().elidedText(index.data(),Qt.TextElideMode.ElideRight,text_rect.width())); painter.restore()

class PopupList(QListWidget):
    def __init__(self,popup):
        super().__init__(popup); self.popup=popup; self.hovered=-1; self.setMouseTracking(True); self.viewport().setMouseTracking(True)
        self.setItemDelegate(RowDelegate(self)); self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.itemClicked.connect(lambda item:popup.commit(item)); self.setCursor(Qt.CursorShape.ArrowCursor)
    def mouseMoveEvent(self,event):
        index=self.indexAt(event.position().toPoint()); row=index.row() if index.isValid() and index.flags() & Qt.ItemFlag.ItemIsEnabled else -1
        if row!=self.hovered: self.hovered=row; self.viewport().update()
        event.accept()
    def leaveEvent(self,event): self.hovered=-1; self.viewport().update(); super().leaveEvent(event)
    def event(self,event):
        if event.type()==QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Tab,Qt.Key.Key_Backtab):
            owner=self.popup.owner; self.popup.close(); owner.focusNextPrevChild(event.key()==Qt.Key.Key_Tab); event.accept(); return True
        return super().event(event)
    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter,Qt.Key.Key_Space): self.popup.commit(self.currentItem()); event.accept()
        elif event.key()==Qt.Key.Key_Escape: self.popup.close(); event.accept()
        elif event.key() in (Qt.Key.Key_Tab,Qt.Key.Key_Backtab): self.popup.close(); self.popup.owner.focusNextPrevChild(event.key()==Qt.Key.Key_Tab); event.accept()
        else: self.hovered=-1; super().keyPressEvent(event)

class ChoicePopup(QFrame):
    def __init__(self,owner,rows,multi=False):
        super().__init__(owner,Qt.WindowType.Popup|Qt.WindowType.FramelessWindowHint|Qt.WindowType.NoDropShadowWindowHint); self.owner=owner; self.multi=multi; self.rows=rows; self.setObjectName('choicePopup'); self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose); self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if QApplication.instance().property('native_hidden_test'): self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.setFont(ui_font()); col=QVBoxLayout(self); col.setContentsMargins(8,8,8,8); col.setSpacing(6)
        self.search=IMELineEdit(self); self.search.setPlaceholderText('搜索选项'); self.search.setClearButtonEnabled(True); self.search.setFixedHeight(38); self.search.setVisible(multi or len(rows)>10); col.addWidget(self.search)
        self.list=PopupList(self); col.addWidget(self.list,1)
        for value,text,enabled,tooltip in rows:
            item=QListWidgetItem(text,self.list); item.setData(Qt.ItemDataRole.UserRole,value); item.setToolTip(tooltip)
            if not enabled: item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        self.empty=QLineEdit('没有匹配项'); self.empty.setReadOnly(True); self.empty.setFocusPolicy(Qt.FocusPolicy.NoFocus); self.empty.hide(); col.addWidget(self.empty)
        self.custom=IMELineEdit(self); self.custom.setPlaceholderText('自定义要求：Enter添加，Esc取消'); self.custom.setMaxLength(500); self.custom.setFixedHeight(38); self.custom.hide(); col.addWidget(self.custom)
        if multi:
            actions=QHBoxLayout(); self.custom_button=QPushButton('自定义…'); self.custom_button.setObjectName('quiet'); self.clear_button=QPushButton('清空已选'); self.clear_button.setObjectName('quiet'); actions.addWidget(self.custom_button); actions.addWidget(self.clear_button); col.addLayout(actions)
            self.custom_button.clicked.connect(self.open_custom); self.clear_button.clicked.connect(self.clear_values)
            self.custom.submitted.connect(self.add_custom); self.custom.cancelled.connect(self.cancel_custom)
        tracker=getattr(owner.window(),'focus_tracker',None)
        if tracker:
            for control in [self.search,self.custom]+([self.custom_button,self.clear_button] if multi else []): tracker.watch(control)
        self.search.textChanged.connect(self.filter); self.search.submitted.connect(lambda:self.commit(self.list.currentItem())); self.search.cancelled.connect(self.close)
        owner.window().installEventFilter(self); owner.installEventFilter(self)
    def paintEvent(self,event):
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing); c=tokens(self.owner); painter.setBrush(QColor(c['panel'])); painter.setPen(QPen(QColor(c['border']),1)); painter.drawRoundedRect(QRectF(self.rect()).adjusted(1,1,-1,-1),10,10)
    def is_chosen(self,value): return value in self.owner.values if self.multi else value==self.owner.currentIndex()
    def commit(self,item):
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsEnabled: return
        value=item.data(Qt.ItemDataRole.UserRole)
        if self.multi:
            values=[v for v in self.owner.values if v!=value] if value in self.owner.values else self.owner.values+[value]
            if self.owner.maximum and len(values)>self.owner.maximum: self.search.setPlaceholderText(f'最多选择{self.owner.maximum}项'); return
            self.owner.set_values(values); self.owner.changed.emit(); self.list.viewport().update()
        else:
            self.owner.setCurrentIndex(value); self.owner.activated.emit(value); self.close()
    def filter(self,query):
        if self.search.composing: return
        for i in range(self.list.count()): self.list.item(i).setHidden(query.casefold() not in self.list.item(i).text().casefold())
        visible=[i for i in range(self.list.count()) if not self.list.item(i).isHidden()]; self.empty.setVisible(not visible)
        if visible: self.list.setCurrentRow(visible[0])
        self.position()
    def clear_values(self): self.owner.set_values([]); self.owner.changed.emit(); self.list.viewport().update()
    def open_custom(self): self.custom.show(); self.position(); self.custom.setFocus()
    def cancel_custom(self): self.custom.clear(); self.custom.hide(); self.position(); self.list.setFocus()
    def add_custom(self):
        text=self.custom.text().strip()
        if not text: return
        value='custom:'+text
        if self.owner.maximum and value not in self.owner.values and len(self.owner.values)>=self.owner.maximum: self.custom.setPlaceholderText(f'最多选择{self.owner.maximum}项'); return
        if value not in dict(self.owner.rows): self.owner.rows.append((value,text)); item=QListWidgetItem(text,self.list); item.setData(Qt.ItemDataRole.UserRole,value)
        if value not in self.owner.values: self.owner.set_values(self.owner.values+[value]); self.owner.changed.emit()
        self.cancel_custom(); self.filter(self.search.text())
    def position(self):
        screen=self.owner.screen().availableGeometry(); count=sum(not self.list.item(i).isHidden() for i in range(self.list.count()))
        extra=16+self.list.frameWidth()*2+(44 if not self.search.isHidden() else 0)+(44 if self.multi else 0)+(44 if not self.custom.isHidden() else 0)+(38 if not count else 0)
        height=min(320,screen.height()-8,extra+max(38,min(8,count)*38)); width=min(screen.width()-8,max(self.owner.width(),280 if self.multi else 180))
        self.resize(width,max(80,height)); bottom=self.owner.mapToGlobal(QPoint(0,self.owner.height())); top=self.owner.mapToGlobal(QPoint())
        x=max(screen.left()+4,min(bottom.x(),screen.right()-width-3)); y=bottom.y() if bottom.y()+self.height()<=screen.bottom()-4 else top.y()-self.height()
        self.move(x,max(screen.top()+4,min(y,screen.bottom()-self.height()-3)))
    def showEvent(self,event):
        super().showEvent(event); self.position(); index=next((i for i in range(self.list.count()) if self.is_chosen(self.list.item(i).data(Qt.ItemDataRole.UserRole))),0)
        self.layout().activate(); self.list.doItemsLayout(); self.list.setCurrentRow(index)
        visible=[self.list.item(i) for i in range(self.list.count()) if not self.list.item(i).isHidden()]
        if sum(self.list.sizeHintForIndex(self.list.indexFromItem(item)).height() for item in visible)<=self.list.viewport().height(): self.list.verticalScrollBar().setValue(0)
        else: self.list.scrollToItem(self.list.item(index))
        self.list.setFocus()
        motion=getattr(self.owner.window(),'motion',None)
        if motion: motion.clear_close_ghost(); motion.fade(self,120)
    def eventFilter(self,watched,event):
        if event.type() in (QEvent.Type.Move,QEvent.Type.Resize,QEvent.Type.Hide) and self.isVisible(): self.close()
        return False
    def closeEvent(self,event):
        self._closing=True
        self.owner.window().removeEventFilter(self); self.owner.removeEventFilter(self)
        motion=getattr(self.owner.window(),'motion',None)
        if motion: motion.stop(self); motion.dismiss_popup(self)
        self.owner.setProperty('expanded',False); self.owner.style().unpolish(self.owner); self.owner.style().polish(self.owner); self.owner.setFocus(Qt.FocusReason.PopupFocusReason)
        if not self.multi: self.owner.hidePopup()
        super().closeEvent(event)
