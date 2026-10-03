"""Shared controls and theme for all V2 pages, including inline panels."""
import html
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QPoint, QTimer
from PySide6.QtGui import QKeyEvent,QPainter,QPen,QColor
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import (QWidget,QPushButton,QLabel,QVBoxLayout,QLineEdit,QCheckBox,QMenu as QtMenu,QWidgetAction,QHBoxLayout,QTextEdit,QScrollArea,QSizePolicy,QComboBox as QtComboBox)
from app.ui.interaction import TOKENS,ChoicePopup,tokens,theme_tokens,ui_font,AnimatedButton

PALETTES=TOKENS
TYPE_SIZES=dict(title=28,section=20,control=16,label=14,caption=14,status=15,body=18)

def style(theme='清透白',font_size=18):
    c=theme_tokens(theme)
    variant={'清透白':'light','石墨紫':'dark','暖纸色':'paper'}[theme]
    arrow=(Path(__file__).resolve().parents[2]/'resources'/'icons'/('v2-down-'+variant+'.svg')).as_posix()
    check=(Path(__file__).resolve().parents[2]/'resources'/'icons'/('checkbox-check-'+variant+'.svg')).as_posix()
    return f'''
 QWidget {{background:{c['window']};color:{c['text']};font-family:"{ui_font().family()}";font-size:{TYPE_SIZES['control']}px;}}
 QLabel {{background:transparent;}} QLabel#muted {{color:{c['muted']};font-size:{TYPE_SIZES['caption']}px;}}
 QLabel#heading {{font-size:{TYPE_SIZES['title']}px;font-weight:600;}} QLabel#brand {{font-size:16px;font-weight:600;}}
 QLabel#sectionHeading,QLabel#subheading {{font-size:{TYPE_SIZES['section']}px;font-weight:600;}}
 QLabel#fieldLabel {{font-size:14px;color:{c['muted']};}}
 QLabel#brandBadge {{background:{c['accent']};color:{c['button']};font-size:20px;font-weight:600;border-radius:7px;}}
 QWidget#brandRow {{background:transparent;}}
 QWidget#fieldCell,QWidget#fieldGrid,QWidget#detailPage {{background:transparent;}}
 QFrame#topbar,QWidget#settingsContent,QWidget#viewHeader {{background:{c['window']};}}
 QWidget#viewHeader {{border-bottom:1px solid {c['border']};}}
 QLineEdit#workMetadataTitle {{border:0;background:transparent;font-size:14px;color:{c['text']};}}
 QFrame#creationFooter,QFrame#assistantFooter {{background:{c['panel']};border-top:1px solid {c['border']};}}
 QFrame#assistantHeader {{background:{c['panel']};border-bottom:1px solid {c['border']};}}
 QFrame#composer {{background:{c['panel']};border:1px solid {c['border']};border-radius:10px;}}
 QTextEdit#ideaEditor,QTextEdit#chatInput {{background:{c['panel']};border:0;border-radius:0;padding:0;}}
 QTabBar#creationViews::tab {{padding:12px 2px;margin-right:26px;min-width:76px;}}
 QTabWidget#storyDetails::pane {{border:0;background:transparent;}}
 QTabWidget#storyDetails QTabBar::tab {{padding:5px 8px;}}
  QFrame#card, QWidget#card {{background:{c['panel']};border:1px solid {c['border']};border-radius:8px;}}
 QFrame#projectCard {{background:{c['panel']};border:2px solid {c['border']};border-radius:8px;}}
 QFrame#projectCard:hover {{background:{c['soft']};border-color:{c['input_border']};}}
 QFrame#projectCard[selected="true"] {{background:{c['selected']};border-color:{c['accent']};}}
 QPushButton#projectAction {{background:transparent;color:{c['accent']};font-size:13px;border:1px solid {c['border']};padding:2px 3px;min-height:26px;}}
 QPushButton#projectAction:hover {{background:{c['soft']};border-color:{c['accent']};}}
 QPushButton#projectAction[danger="true"] {{color:{c['error']};}}
 QPushButton#projectAction[danger="true"]:hover {{border-color:{c['error']};}}
 QWidget#fontControls,QWidget#assistantFontControls {{background:transparent;}}
 QWidget#fontControls QPushButton {{padding:2px 4px;min-height:28px;}}
 QWidget#assistantFontControls QPushButton {{padding:2px 4px;min-height:24px;}}
  QWidget#TTSettingsRoot QGroupBox {{background:{c['panel']};border:1px solid {c['border']};border-radius:8px;margin-top:14px;padding:14px;}}
  QWidget#TTSettingsRoot QGroupBox::title {{subcontrol-origin:margin;left:14px;padding:0 5px;}}
  QWidget#TTSettingsRoot QLineEdit,QWidget#TTSettingsRoot QComboBox {{min-width:0;}}
  QLabel[muted="true"] {{color:{c['muted']};background:transparent;}}
  QLabel[statusTone="green"] {{color:{c['success']};}} QLabel[statusTone="red"] {{color:{c['error']};}} QLabel[statusTone="orange"] {{color:{c['warning']};}}
  QTabWidget#SettingsSectionTabs::pane {{background:{c['panel']};border:1px solid {c['border']};}}
  QFrame#choicePopup {{background:{c['panel']};border:1px solid {c['input_border']};border-radius:8px;}}
  QFrame#choicePopup QListWidget {{background:{c['panel']};padding:0;}}
  QFrame#choicePopup QListWidget::item {{padding:0;border:0;margin:0;}}
 QFrame#sidebar {{background:{c['panel']};border-right:1px solid {c['border']};}}
 QFrame#assistant {{background:{c['panel']};border-left:1px solid {c['border']};}}
  QPushButton, QToolButton {{background:{c['panel']};border:1px solid {c['input_border']};border-radius:7px;padding:4px 12px;min-height:28px;}}
 QPushButton:hover, QToolButton:hover {{background:{c['soft']};border-color:{c['accent']};}} QPushButton:pressed,QToolButton:pressed {{background:{c['soft']};border-color:{c['accent']};}} QPushButton:focus,QToolButton:focus {{border-color:{c['accent']};}} QPushButton#primary {{background:{c['accent']};color:{c['button']};font-weight:600;border-color:{c['accent']};}}
 QPushButton#primary:hover {{background:{c['accent']};color:{c['button']};border-color:{c['text']};}}
 QPushButton#primary:disabled {{background:{c['window']};color:{c['muted']};border-color:{c['border']};}}
  QPushButton#quiet {{background:transparent;border:1px solid transparent;color:{c['muted']};}} QPushButton#quiet:hover {{background:{c['soft']};color:{c['text']};}} QPushButton:disabled {{color:{c['muted']};background:{c['window']};}}
 QPushButton#multiChoice,QPushButton#narrativeChoice {{text-align:left;padding-right:30px;}}
 QPushButton[disclosure="true"] {{padding-right:24px;}}
  QPushButton[expanded="true"] {{background:{c['selected']};}}
  QWidget[error="true"] {{border-color:{c['error']};}} QLabel#error {{color:{c['error']};}}
 QPushButton#assistantToggle {{background:{c['soft']};color:{c['accent']};border-color:{c['border']};}}
  QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox {{background:{c['panel']};border:1px solid {c['input_border']};border-radius:7px;min-height:28px;padding:4px 10px;selection-background-color:{c['accent']};}}
 QLineEdit:hover,QComboBox:hover,QSpinBox:hover,QDoubleSpinBox:hover {{border-color:{c['muted']};}}
 QComboBox[choiceSet="true"] {{background:{c['panel']};color:{c['text']};}}
 QLineEdit:focus,QComboBox:focus,QSpinBox:focus,QDoubleSpinBox:focus,QTextEdit:focus {{border-color:{c['accent']};}}
 QComboBox {{padding-right:30px;}} QComboBox::drop-down {{subcontrol-origin:padding;subcontrol-position:top right;width:28px;border:0;background:transparent;}}
 QComboBox::down-arrow {{image:url("{arrow}");width:14px;height:14px;}}
 QComboBox QAbstractItemView {{background:{c['panel']};color:{c['text']};border:1px solid {c['border']};padding:4px;outline:0;selection-background-color:{c['soft']};selection-color:{c['accent']};}}
 QComboBox QAbstractItemView::item {{min-height:28px;padding:4px 10px;border:0;}}
 QComboBox QAbstractItemView::item:hover,QComboBox QAbstractItemView::item:selected {{background:{c['soft']};color:{c['accent']};}}
 QSpinBox::up-button,QDoubleSpinBox::up-button {{subcontrol-origin:border;subcontrol-position:top right;width:24px;border:0;background:transparent;margin:2px;}}
 QSpinBox::down-button,QDoubleSpinBox::down-button {{subcontrol-origin:border;subcontrol-position:bottom right;width:24px;border:0;background:transparent;margin:2px;}}
 QSpinBox::up-button:hover,QSpinBox::down-button:hover,QDoubleSpinBox::up-button:hover,QDoubleSpinBox::down-button:hover {{background:{c['soft']};}}
 QLineEdit#workTitle {{border:0;background:transparent;font-size:22px;font-weight:600;}}
 QTextEdit,QTextBrowser,QPlainTextEdit {{background:{c['panel']};border:1px solid {c['border']};border-radius:12px;padding:10px;selection-background-color:{c['accent']};}}
 QTextEdit#workEditor,QTextBrowser#referenceCompare {{font-size:{font_size}px;font-weight:400;padding:16px;}}
 QTextEdit#referenceEditor,QTextEdit#ideaEditor {{font-size:16px;}}
 QTextBrowser#chat {{border:0;padding:6px;font-size:16px;}} QTextEdit#chatInput {{font-size:16px;}}
 QScrollArea {{border:0;}} QScrollBar:vertical {{width:8px;background:{c['window']};}} QScrollBar::handle:vertical {{background:{c['border']};min-height:28px;border-radius:4px;}}
 QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
 QListWidget {{background:transparent;border:0;outline:0;}} QListWidget::item {{padding:12px 14px;border-radius:8px;min-height:20px;}}
  QListWidget::item:selected {{background:{c['selected']};color:{c['selected_text']};border-left:3px solid {c['accent']};}}
 QListWidget#primaryNavigation::item {{padding:10px 8px;min-height:20px;}}
 QListWidget::item:hover {{background:{c['soft']};}}
 QListWidget::item:selected:hover {{background:{c['selected']};color:{c['selected_text']};}}
 QPushButton#sidebarAction {{text-align:left;border:0;background:transparent;padding:10px 14px;}}
 QPushButton#sidebarAction:hover,QPushButton#sidebarAction:checked {{background:{c['soft']};color:{c['accent']};}}
 QPushButton#sidebarAction:checked {{background:{c['selected']};color:{c['selected_text']};}}
 QTabBar {{background:transparent;border:0;}} QTabWidget::pane {{border:1px solid {c['border']};border-radius:8px;}} QTabBar::tab {{background:transparent;padding:8px 12px;border-bottom:2px solid transparent;}}
 QTabBar::tab:selected {{background:{c['soft']};border-bottom-color:{c['accent']};color:{c['accent']};font-weight:600;}}
 QTabBar::tab:hover {{background:{c['soft']};}}
 QMenu {{background:{c['panel']};border:1px solid {c['border']};padding:4px;}} QMenu::item {{padding:8px 18px;}} QMenu::item:selected {{background:{c['soft']};}}
 QCheckBox {{background:transparent;spacing:8px;}}
 QCheckBox::indicator {{width:18px;height:18px;border:1px solid {c['muted']};border-radius:4px;background:{c['panel']};}}
 QCheckBox::indicator:unchecked:hover {{border-color:{c['accent']};background:{c['soft']};}}
 QCheckBox::indicator:checked {{border-color:{c['accent']};background:{c['accent']};image:url("{check}");}}
 QCheckBox::indicator:checked:hover {{border-color:{c['text']};}}
 QCheckBox::indicator:unchecked:disabled {{background:{c['window']};border-color:{c['border']};}}
 QCheckBox::indicator:checked:disabled {{background:{c['muted']};border-color:{c['muted']};}}
 QCheckBox:focus {{color:{c['accent']};}}
 QSplitter::handle {{background:{c['border']};width:10px;}} QSplitter::handle:hover {{background:{c['soft']};}}
 QToolTip {{background:{c['panel']};color:{c['text']};border:1px solid {c['border']};padding:6px;}}
 QFrame#choicePopup {{background:transparent;border:0;}}
 QFrame#titleBar {{background:{c['panel']};border-bottom:1px solid {c['border']};}}
 QFrame#titleBar QLabel {{background:transparent;}} QLabel#titleBrand {{font-size:16px;font-weight:600;}}
 QToolButton#windowControl,QToolButton#windowClose {{border:0;border-radius:6px;padding:6px;background:transparent;}}
 QToolButton#windowControl:hover {{background:{c['soft']};}}
 QToolButton#windowClose:hover {{background:{c['error']};}}
 QFrame#editorToolbar {{background:{c['panel']};border:1px solid {c['border']};border-radius:10px;}}
 QFrame#taskStatus {{background:transparent;border:0;}} QFrame#taskStatus QLabel {{background:transparent;font-size:15px;}}
 QLabel#taskStatusDetail {{font-size:13px;color:{c['muted']};}}
 QLabel#saveState {{font-size:15px;font-weight:500;color:{c['muted']};}} QLabel#saveState[saved="true"] {{color:{c['success']};}}
 QLabel#candidateStatus {{font-size:16px;font-weight:600;color:{c['warning']};}}
 QLabel#taskStatusText[tone="warning"] {{color:{c['warning']};}} QLabel#taskStatusText[tone="error"] {{color:{c['error']};}}
 QLabel#taskStatusText[tone="success"] {{color:{c['success']};}}
 QLabel#wordCount {{color:{c['muted']};font-size:13px;}}
 QFrame#card,QWidget#card {{border-radius:12px;}}
 QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox {{min-height:30px;border-color:{c['border']};padding:4px 10px;}}
 QLineEdit:focus,QComboBox:focus,QTextEdit:focus,QPlainTextEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus {{border:1px solid {c['accent']};}}
 QFrame#assistantHeader {{background:{c['panel']};}} QTextBrowser#chat {{font-size:16px;}}
 QTextEdit#candidateEditor {{font-size:{font_size}px;}}
 QWidget#viewHeader {{background:{c['panel']};}}
 QFrame#coverPreview {{background:{c['soft']};border:1px solid {c['border']};border-radius:12px;}}
 QDialog {{background:{c['window']};}}
 QPushButton#toolAction {{padding:3px 6px;min-height:28px;}}
 QPushButton#primary {{min-height:30px;}} QPushButton[activeProvider="true"] {{background:{c['soft']};color:{c['success']};}}
 QPushButton#createEntry {{font-size:17px;font-weight:600;min-height:60px;padding:12px 16px;}}
 QMenu {{background:transparent;border:0;padding:6px;}} QMenu::item {{padding:8px 14px;border-radius:6px;}}
 '''

class QMenu(QtMenu):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs); self.setWindowFlags(self.windowFlags()|Qt.WindowType.FramelessWindowHint|Qt.WindowType.NoDropShadowWindowHint); self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        from PySide6.QtWidgets import QApplication
        if QApplication.instance().property('native_hidden_test'): self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    def paintEvent(self,event):
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing); c=tokens(self); painter.setBrush(QColor(c['panel'])); painter.setPen(QPen(QColor(c['border']),1)); painter.drawRoundedRect(QRectF(self.rect()).adjusted(1,1,-1,-1),10,10); painter.end(); super().paintEvent(event)

def label(text,role=''):
    w=QLabel(text); w.setObjectName(role); w.setWordWrap(True); return w

def button(text,callback,primary=False,quiet=False):
    w=DisclosureButton(text) if text.endswith(('▾','▴')) else AnimatedButton(text); w.setObjectName('primary' if primary else 'quiet' if quiet else '')
    w.setCursor(Qt.CursorShape.ArrowCursor)
    w.clicked.connect(callback); return w

def font_controls(owner):
    controls=QWidget(); controls.setObjectName('fontControls'); row=QHBoxLayout(controls); row.setContentsMargins(0,0,0,0); row.setSpacing(3)
    controls.setFixedWidth(100); controls.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Fixed)
    less=button('−',lambda:owner.set_font(owner.options.get('editor_font_size',18)-1)); less.setFixedWidth(28); less.setAccessibleName('缩小正文字号')
    size=button(str(owner.options.get('editor_font_size',18)),lambda:owner.set_font(18)); size.setObjectName('fontSizeValue'); size.setFixedWidth(34); size.setToolTip('当前正文字号；点击恢复 18'); size.setAccessibleName('恢复默认正文字号')
    more=button('+',lambda:owner.set_font(owner.options.get('editor_font_size',18)+1)); more.setFixedWidth(28); more.setAccessibleName('放大正文字号')
    row.addWidget(less); row.addWidget(size); row.addWidget(more); controls.size_value=size; controls.less=less; controls.more=more; return controls

class DisclosureButton(AnimatedButton):
    def __init__(self,text):
        super().__init__(); self.setProperty('disclosure',True); self.setText(text)
    def setText(self,text):
        self.setProperty('expanded',text.endswith('▴')); super().setText(text.removesuffix('▾').removesuffix('▴').rstrip())
    def paintEvent(self,event):
        super().paintEvent(event); painter=QPainter(self); painter.setPen(QPen(QColor(tokens(self)['muted']),1.5)); x=self.width()-12; y=self.height()//2; direction=-1 if self.property('expanded') else 1
        painter.drawLine(x-3,y-direction*2,x,y+direction); painter.drawLine(x,y+direction,x+3,y-direction*2)

class QComboBox(QtComboBox):
    """One popup treatment across creation, settings and inline panels."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs); self.setCursor(Qt.CursorShape.ArrowCursor); self.setMaxVisibleItems(8); self.choice_popup=None
        self.view().setMouseTracking(True); self.view().setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view().setTextElideMode(Qt.TextElideMode.ElideRight)
        self.currentIndexChanged.connect(self.update_choice_tone)
    def update_choice_tone(self,*_):
        value=str(self.currentData() or self.currentText()); automatic=value in {'','auto','自动','自由创作','由 AI 自动选择'} or value.endswith('.auto') or value.startswith('自动')
        self.setProperty('choiceSet',not automatic); self.style().unpolish(self); self.style().polish(self); self.update()
    def showPopup(self):
        if self.choice_popup: return
        rows=[(i,self.itemText(i),bool(self.model().index(i,0).flags() & Qt.ItemFlag.ItemIsEnabled),self.itemData(i,Qt.ItemDataRole.ToolTipRole) or '') for i in range(self.count())]
        popup=ChoicePopup(self,rows); self.choice_popup=popup; self.setProperty('expanded',True); self.style().unpolish(self); self.style().polish(self)
        popup.destroyed.connect(lambda _,p=popup:self._popup_destroyed(p)); popup.show()
    def _popup_destroyed(self,popup):
        if self.choice_popup is popup: self.choice_popup=None
    def hidePopup(self):
        popup=self.choice_popup; self.choice_popup=None
        if popup and not getattr(popup,'_closing',False): popup.close()
        super().hidePopup()
    def wheelEvent(self,event): event.ignore()
    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Down,Qt.Key.Key_Up,Qt.Key.Key_Space,Qt.Key.Key_Return,Qt.Key.Key_Enter): self.showPopup(); event.accept()
        else: super().keyPressEvent(event)


class MultiChoice(QPushButton):
    changed=Signal()
    def __init__(self,rows=(),maximum=None):
        super().__init__('自动'); self.rows=list(rows); self.values=[]; self.maximum=maximum
        self.setCursor(Qt.CursorShape.ArrowCursor); self.setObjectName('multiChoice')
        self.setMinimumWidth(100); self.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed); self.clicked.connect(self.open_menu)
    def set_rows(self,rows):
        self.rows=list(rows); self.values=[v for v in self.values if v in dict(self.rows)]; self.refresh()
    def set_values(self,values):
        for value in values:
            if value.startswith('custom:') and value not in dict(self.rows): self.rows.append((value,value[7:]))
        self.values=list(values); self.refresh()
    def refresh(self):
        names=dict(self.rows); caption='自动' if not self.values else ' · '.join(names.get(v,v) for v in self.values)
        if len(self.values)>2: caption=' · '.join(names.get(v,v) for v in self.values[:2])+f' · 另{len(self.values)-2}项'
        self.setText(self.fontMetrics().elidedText(caption,Qt.TextElideMode.ElideRight,max(60,self.width()-40))); self.setToolTip(' → '.join(names.get(v,v) for v in self.values))
    def resizeEvent(self,event):
        super().resizeEvent(event); self.refresh()
    def open_menu(self):
        if not self.isEnabled(): return
        from app.core.script_settings import BY_ID
        if getattr(self,'last_menu',None) and self.last_menu.isVisible(): self.last_menu.close(); return
        rows=[(value,name,True,BY_ID.get(value,{}).get('body','')) for value,name in self.rows]
        popup=ChoicePopup(self,rows,multi=True); self.last_menu=popup; self.last_search=popup.search; self.empty_label=popup.empty
        popup.destroyed.connect(lambda _,p=popup:self._popup_destroyed(p))
        self.setProperty('expanded',True); self.style().unpolish(self); self.style().polish(self); popup.show()
    def _popup_destroyed(self,popup):
        if getattr(self,'last_menu',None) is popup: self.last_menu=None
    def paintEvent(self,event):
        super().paintEvent(event)
        painter=QPainter(self); painter.setPen(QPen(QColor(tokens(self)['muted']),1.5)); x=self.width()-18; y=self.height()//2
        offset=-3 if self.property('expanded') else 3
        painter.drawLine(x-4,y-offset//2,x,y+offset//2); painter.drawLine(x,y+offset//2,x+4,y-offset//2)

class ChatInput(QTextEdit):
    send=Signal()
    def __init__(self):
        super().__init__(); self.composing=False; self.setObjectName('chatInput')
    def inputMethodEvent(self,event):
        self.composing=bool(event.preeditString()); super().inputMethodEvent(event)
    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter) and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if self.composing: super().keyPressEvent(event)
            else: self.send.emit()
        else: super().keyPressEvent(event)
