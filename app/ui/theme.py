THEMES = {
    '石墨深色': dict(window='#15171C', panel='#1D2027', editor='#20242C', text='#E8ECF4', muted='#A9B2C4', border='#414957', accent='#B1A6FF', button='#171326', soft='#35324E', card='#242730'),
    '雾白浅色': dict(window='#F3F5F8', panel='#FFFFFF', editor='#FFFFFF', text='#202735', muted='#596579', border='#C6CEDB', accent='#315EFF', button='#FFFFFF', soft='#E9EFFF', card='#F8FAFE'),
    '暖纸写作': dict(window='#EFE9DF', panel='#F7F1E7', editor='#FFF9EF', text='#352E27', muted='#706252', border='#C5B8A6', accent='#80522B', button='#FFFFFF', soft='#EADAC6', card='#FAF5ED'),
}


def stylesheet(name: str, font_size=14, editor_font_size=18):
    c = THEMES[name]
    home_background = c['window'] if name == '石墨深色' else c['editor']
    heading_font = 'Noto Serif SC' if name == '暖纸写作' else 'Microsoft YaHei UI'
    return f'''
        QWidget {{ color:{c['text']}; background:{c['window']}; font-family:"Microsoft YaHei"; font-size:{font_size}px; }}
        QMainWindow, QDialog {{ background:{c['window']}; }}
        QFrame#panel, QWidget#panel, QFrame#assistant {{ background:{c['panel']}; border:1px solid {c['border']}; border-radius:8px; }}
        QLabel {{ background:transparent; }}
        QLabel#heading {{ font-family:"{heading_font}"; font-size:30px; font-weight:700; }}
        QWidget#homePage QLabel#heading {{ font-size:38px; }}
        QLabel#subheading {{ font-size:20px; font-weight:600; }}
        QLabel#projectTitle {{ font-family:"{heading_font}"; font-size:30px; font-weight:700; }}
        QLabel#projectPitch {{ font-size:{max(font_size, 18)}px; }}
        QFrame#featuredProject QPushButton#primary {{ font-size:{max(font_size, 16)}px; min-height:28px; }}
        QWidget#homePage, QWidget#homeContent, QWidget#homeViewport, QWidget#projectCards {{ background:{home_background}; }}
        QWidget#homePage QLabel#muted {{ font-size:{max(font_size, 16)}px; }}
        QFrame#sidebar QListWidget#navigation, QPushButton#sidebarAction {{ font-size:{max(font_size, 16)}px; }}
        QFrame#projectListHeader {{ background:{c['card']}; border-radius:8px; }}
        QListWidget#projectList {{ border:0; }}
        QLabel#chip {{ color:{c['accent']}; background:{c['soft']}; padding:4px 10px; border-radius:6px; font-size:12px; }}
        QLabel#emptyState {{ color:{c['muted']}; font-size:16px; }}
        QFrame#sidebar {{ background:{c['panel']}; border-right:1px solid {c['border']}; }}
        QPushButton#sidebarAction {{ background:transparent; border:0; text-align:left; padding:8px; min-height:30px; }}
        QPushButton#sidebarAction:hover {{ background:{c['soft']}; }}
        QFrame#featuredProject {{ background:{c['card']}; border:1px solid {c['border']}; border-radius:12px; }}
        QFrame#projectCard {{ background:{c['panel']}; border:1px solid {c['border']}; border-radius:12px; }}
        QFrame#projectCard:hover {{ border-color:{c['accent']}; }}
        QPushButton#cardTitle {{ background:transparent; border:0; padding:0; text-align:left; font-size:17px; font-weight:600; }}
        QFrame#messageCard {{ background:{c['card']}; border:1px solid {c['border']}; border-radius:12px; }}
        QFrame#composer {{ background:{c['panel']}; border:1px solid {c['border']}; border-radius:12px; }}
        QWidget#assistantMessages {{ background:transparent; }}
        QFrame#assistant {{ background:{c['panel']}; border:0; border-left:1px solid {c['border']}; border-radius:0; }}
        QFrame#assistant QLabel, QFrame#assistant QTabBar::tab {{ font-size:{max(font_size,16)}px; }}
        QFrame#assistant QLabel#subheading {{ font-size:22px; }}
        QComboBox::drop-down {{ subcontrol-origin:padding; subcontrol-position:top right; width:20px; border:0; background:transparent; }}
        QToolButton::menu-indicator {{ image:none; }}
        QTextEdit#assistantInput {{ border:0; background:transparent; padding:2px; }}
        QTextBrowser#chatOutput {{ border:0; background:transparent; padding:4px; }}
        QTextBrowser#creatorRuleText, QTextBrowser#creatorResult {{ background:{c['panel']}; border:1px solid {c['border']}; border-radius:10px; padding:16px; }}
        QListWidget#creatorTracks::item {{ min-height:32px; margin:3px; padding:8px 12px; }}
        QDialog QLabel#muted {{ font-size:13px; }}
        QScrollArea {{ border:0; background:transparent; }}
        QLabel#muted {{ color:{c['muted']}; }}
        QPushButton, QToolButton {{ background:{c['panel']}; border:1px solid {c['border']}; padding:7px 12px; border-radius:8px; min-height:20px; }}
        QPushButton:hover, QToolButton:hover {{ border-color:{c['accent']}; }}
        QPushButton:pressed, QPushButton:checked {{ border-color:{c['accent']}; color:{c['accent']}; }}
        QPushButton#primary {{ background:{c['accent']}; color:{c['button']}; border-color:{c['accent']}; font-weight:600; }}
        QPushButton:disabled, QComboBox:disabled {{ color:{c['muted']}; background:{c['window']}; }}
        QPushButton:focus, QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QListWidget:focus {{ border:2px solid {c['accent']}; }}
        QLineEdit, QComboBox, QSpinBox, QFontComboBox {{ background:{c['panel']}; border:1px solid {c['border']}; border-radius:6px; padding:6px; min-height:20px; selection-background-color:{c['accent']}; selection-color:{c['button']}; }}
        QTextEdit, QPlainTextEdit, QTextBrowser {{ background:{c['editor']}; border:1px solid {c['border']}; border-radius:8px; padding:12px; selection-background-color:{c['accent']}; selection-color:{c['button']}; }}
        QTextEdit#editor {{ border:0; padding:22px; font-family:"Microsoft YaHei"; font-size:{editor_font_size}px; }}
        QListWidget, QTreeWidget, QTableWidget {{ background:{c['panel']}; border:1px solid {c['border']}; border-radius:8px; outline:0; }}
        QListWidget::item {{ padding:9px 8px; border-radius:6px; }}
        QListWidget::item:selected {{ color:{c['button']}; background:{c['accent']}; }}
        QListWidget#navigation {{ background:transparent; border:0; }}
        QListWidget#navigation::item {{ padding:8px; margin:3px 0; }}
        QListWidget#navigation::item:selected {{ color:{c['accent']}; background:{c['soft']}; }}
        QListWidget#navigation::item:hover {{ background:{c['soft']}; }}
        QHeaderView::section {{ background:{c['window']}; border:0; padding:8px; }}
        QSplitter::handle {{ background:{c['border']}; width:2px; }}
        QMenu {{ background:{c['panel']}; border:1px solid {c['border']}; padding:5px; }}
        QMenu::item {{ padding:8px 20px; }}
        QMenu::item:selected {{ background:{c['accent']}; color:{c['button']}; }}
        QTabWidget::pane {{ border:1px solid {c['border']}; }}
        QTabBar {{ background:transparent; }}
        QTabBar::tab {{ background:transparent; padding:8px 16px; border-bottom:2px solid transparent; }}
        QTabBar::tab:selected {{ color:{c['accent']}; border-bottom-color:{c['accent']}; }}
        QScrollBar:vertical {{ background:{c['window']}; width:10px; margin:0; }}
        QScrollBar::handle:vertical {{ background:{c['border']}; min-height:28px; border-radius:4px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        QStatusBar {{ border-top:1px solid {c['border']}; color:{c['muted']}; }}
        QToolTip {{ color:{c['text']}; background:{c['panel']}; border:1px solid {c['accent']}; padding:6px; }}
    ''' + (f'''
        QFrame#featuredProject, QFrame#projectCard {{ background:transparent; border:0; }}
        QLabel#subheading, QPushButton#cardTitle {{ font-family:"{heading_font}"; }}
        QFrame#assistant {{ background:{c['editor']}; }}
        QFrame#messageCard {{ border:0; }}
    ''' if name == '暖纸写作' else '')
