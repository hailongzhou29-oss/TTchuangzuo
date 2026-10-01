from PySide6.QtWidgets import QCheckBox,QVBoxLayout,QWidget

def fold(parent_layout,title='高级设置'):
    toggle=QCheckBox(title)
    panel=QWidget()
    layout=QVBoxLayout(panel)
    layout.setContentsMargins(0,4,0,4)
    parent_layout.addWidget(toggle)
    parent_layout.addWidget(panel)
    panel.hide()
    toggle.toggled.connect(panel.setVisible)
    return panel,layout,toggle
