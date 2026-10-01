"""Shared controls and theme for all V2 pages, including inline panels."""
import html
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (QWidget,QPushButton,QLabel,QVBoxLayout,QLineEdit,QCheckBox,QMenu,QWidgetAction,QHBoxLayout,QTextEdit,QScrollArea,QComboBox as QtComboBox)

PALETTES={
 '石墨紫':dict(window='#15171C',panel='#1D2027',text='#E8ECF4',muted='#A8B0BF',accent='#B1A6FF',border='#353B47',soft='#302C49',button='#15171C'),
 '清透白':dict(window='#F3F5F8',panel='#FFFFFF',text='#202735',muted='#626D7E',accent='#5140C8',border='#D8DEE8',soft='#EEEAFE',button='#FFFFFF'),
 '暖纸色':dict(window='#EFE9DF',panel='#F7F1E7',text='#352E27',muted='#706355',accent='#80522B',border='#D6CBBE',soft='#E8D9C7',button='#FFFFFF')}

def style(theme='清透白',font_size=17):
    c=PALETTES[theme]
    variant={'清透白':'light','石墨紫':'dark','暖纸色':'paper'}[theme]
    arrow=(Path(__file__).resolve().parents[2]/'resources'/'icons'/('v2-down-'+variant+'.svg')).as_posix()
    return f'''
 QWidget {{background:{c['window']};color:{c['text']};font-family:"Microsoft YaHei UI";font-size:14px;}}
 QLabel {{background:transparent;}} QLabel#muted {{color:{c['muted']};font-size:12px;}}
 QLabel#heading {{font-size:22px;font-weight:600;}} QLabel#brand {{font-size:18px;font-weight:600;}}
 QFrame#card, QWidget#card {{background:{c['panel']};border:1px solid {c['border']};border-radius:12px;}}
 QFrame#sidebar {{background:{c['panel']};border-right:1px solid {c['border']};}}
 QFrame#assistant {{background:{c['panel']};border-left:1px solid {c['border']};}}
 QPushButton, QToolButton {{background:{c['panel']};border:1px solid {c['border']};border-radius:8px;padding:5px 12px;min-height:24px;}}
 QPushButton:hover, QToolButton:hover {{background:{c['soft']};border-color:{c['accent']};}} QPushButton:pressed,QToolButton:pressed {{background:{c['soft']};border-color:{c['accent']};}} QPushButton:focus,QToolButton:focus {{border-color:{c['accent']};}} QPushButton#primary {{background:{c['accent']};color:{c['button']};font-weight:600;border-color:{c['accent']};}}
 QPushButton#primary:hover {{background:{c['accent']};color:{c['button']};border-color:{c['text']};}}
 QPushButton#quiet {{background:transparent;border:0;color:{c['muted']};}} QPushButton:disabled {{color:{c['muted']};background:{c['window']};}}
 QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox {{background:{c['panel']};border:1px solid {c['border']};border-radius:8px;min-height:26px;padding:4px 8px;selection-background-color:{c['accent']};}}
 QLineEdit:hover,QComboBox:hover,QSpinBox:hover,QDoubleSpinBox:hover {{border-color:{c['muted']};}}
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
 QTextEdit#workEditor {{font-size:{font_size}px;padding:16px;}}
 QTextBrowser#chat {{border:0;padding:6px;}} QTextEdit#chatInput {{font-size:14px;}}
 QScrollArea {{border:0;}} QScrollBar:vertical {{width:8px;background:{c['window']};}} QScrollBar::handle:vertical {{background:{c['border']};min-height:28px;border-radius:4px;}}
 QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
 QListWidget {{background:transparent;border:0;outline:0;}} QListWidget::item {{padding:12px 14px;border-radius:8px;min-height:20px;}}
 QListWidget::item:selected {{background:{c['soft']};color:{c['accent']};border-left:3px solid {c['accent']};}}
 QListWidget::item:hover {{background:{c['soft']};}}
 QPushButton#sidebarAction {{text-align:left;border:0;background:transparent;padding:10px 14px;}}
 QPushButton#sidebarAction:hover,QPushButton#sidebarAction:checked {{background:{c['soft']};color:{c['accent']};}}
 QTabWidget::pane {{border:1px solid {c['border']};border-radius:8px;}} QTabBar::tab {{background:transparent;padding:8px 12px;border-bottom:2px solid transparent;}}
 QTabBar::tab:selected {{border-bottom-color:{c['accent']};color:{c['accent']};}}
 QTabBar::tab:hover {{background:{c['soft']};}}
 QMenu {{background:{c['panel']};border:1px solid {c['border']};padding:4px;}} QMenu::item {{padding:8px 18px;}} QMenu::item:selected {{background:{c['soft']};}}
 QCheckBox {{background:transparent;spacing:6px;}} QSplitter::handle {{background:{c['border']};width:2px;}}
 QToolTip {{background:{c['panel']};color:{c['text']};border:1px solid {c['border']};padding:6px;}}
 '''

def label(text,role=''):
    w=QLabel(text); w.setObjectName(role); w.setWordWrap(True); return w

def button(text,callback,primary=False,quiet=False):
    w=QPushButton(text); w.setObjectName('primary' if primary else 'quiet' if quiet else '')
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    w.clicked.connect(callback); return w

class QComboBox(QtComboBox):
    """One popup treatment across creation, settings and inline panels."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs); self.setCursor(Qt.CursorShape.PointingHandCursor); self.setMaxVisibleItems(8)
        self.view().setMouseTracking(True); self.view().setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view().setTextElideMode(Qt.TextElideMode.ElideRight)
    def showPopup(self):
        self.view().window().setWindowFlag(Qt.WindowType.NoDropShadowWindowHint,True)
        super().showPopup()
        popup=self.view().window(); popup.setFixedWidth(min(340,max(180,self.width())))


class MultiChoice(QPushButton):
    changed=Signal()
    def __init__(self,rows=(),maximum=None):
        super().__init__('自动'); self.rows=list(rows); self.values=[]; self.maximum=maximum
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(100); self.setMaximumWidth(220); self.clicked.connect(self.open_menu)
    def set_rows(self,rows):
        self.rows=list(rows); self.values=[v for v in self.values if v in dict(self.rows)]; self.refresh()
    def set_values(self,values):
        for value in values:
            if value.startswith('custom:') and value not in dict(self.rows): self.rows.append((value,value[7:]))
        self.values=list(values); self.refresh()
    def refresh(self):
        names=dict(self.rows); self.setText('自动' if not self.values else f'已选{len(self.values)}项'); self.setToolTip(' → '.join(names.get(v,v) for v in self.values))
    def open_menu(self):
        menu=QMenu(self); page=QWidget(); layout=QVBoxLayout(page); search=QLineEdit(); search.setPlaceholderText('搜索选项'); layout.addWidget(search)
        area=QScrollArea(); area.setWidgetResizable(True); contents=QWidget(); lines=QVBoxLayout(contents); boxes=[]
        for value,name in self.rows:
            check=QCheckBox(name); check.setChecked(value in self.values); lines.addWidget(check); boxes.append((value,check))
        lines.addStretch(); area.setWidget(contents); area.setMinimumSize(230,260); layout.addWidget(area)
        custom_row=QHBoxLayout(); custom=QLineEdit(); custom.setMaxLength(500); custom.setPlaceholderText('输入你的要求'); custom_row.addWidget(custom,1)
        def add_custom():
            text=custom.text().strip()
            if not text: return
            value='custom:'+text
            if value not in dict(self.rows):
                self.rows.append((value,text)); check=QCheckBox(text); check.setChecked(True); lines.insertWidget(lines.count()-1,check); boxes.append((value,check))
            custom.clear()
        custom_row.addWidget(button('添加',add_custom)); layout.addLayout(custom_row)
        def filter_rows(query):
            for _,check in boxes: check.setVisible(query.casefold() in check.text().casefold())
        search.textChanged.connect(filter_rows)
        actions=QHBoxLayout()
        def finish():
            checked=[v for v,box in boxes if box.isChecked()]
            if self.maximum and len(checked)>self.maximum:
                search.setPlaceholderText(f'最多选择{self.maximum}项'); search.clear(); return
            # Existing emotion order survives reopening; newly selected values append.
            self.values=[v for v in self.values if v in checked]+[v for v in checked if v not in self.values]
            self.refresh(); self.changed.emit(); menu.close()
        actions.addWidget(button('清空',lambda:[box.setChecked(False) for _,box in boxes]))
        actions.addWidget(button('完成',finish,True)); layout.addLayout(actions)
        action=QWidgetAction(menu); action.setDefaultWidget(page); menu.addAction(action); menu.popup(self.mapToGlobal(self.rect().bottomLeft()))

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
