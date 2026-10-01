import shutil
from dataclasses import replace
from PySide6.QtCore import QThreadPool,QTimer
from PySide6.QtWidgets import QCheckBox,QFileDialog,QFormLayout,QHBoxLayout,QLineEdit,QTextBrowser,QVBoxLayout,QWidget
from app.providers.codex_text import CodexTextProvider
from app.providers.contracts import Connection
from app.providers.image_contracts import ImageConnection

class CodexSettingsPage(QWidget):
    def __init__(self,owner):
        super().__init__()
        self.owner=owner
        layout=QVBoxLayout(self)
        layout.addWidget(owner.label('Codex CLI','subheading'))
        layout.addWidget(owner.label('使用本机Codex登录，支持AI文字创作与内置生图，不需要另填API Key。','muted'))
        text=next((c for c in owner.connections.all() if c.provider=='codex'),None)
        image=next((c for c in owner.image_connections.all() if c.provider=='image_codex'),None)
        self.text_id=text.id if text else 'codex_creator_text'
        self.image_id=image.id if image else 'codex_creator_image'
        current=image or text
        form=QFormLayout()
        self.path=QLineEdit(current.cli_path if current else shutil.which('codex.cmd') or shutil.which('codex') or '')
        path_row=QHBoxLayout()
        path_row.addWidget(self.path,1)
        path_row.addWidget(owner.button('选择程序',self.choose))
        form.addRow('Codex程序',path_row)
        self.model=QLineEdit(current.model if current else '')
        self.model.setPlaceholderText('填写本机可用的宿主模型')
        form.addRow('宿主模型',self.model)
        layout.addLayout(form)
        self.text_on=QCheckBox('启用文字创作')
        self.image_on=QCheckBox('启用生图')
        self.text_on.setChecked(text.enabled if text else True)
        self.image_on.setChecked(image.enabled if image else True)
        layout.addWidget(self.text_on)
        layout.addWidget(self.image_on)
        row=QHBoxLayout()
        row.addWidget(owner.button('保存Codex接入',self.save,True))
        row.addWidget(owner.button('检测登录',self.detect))
        layout.addLayout(row)
        self.status=QTextBrowser()
        self.status.setMaximumHeight(170)
        self.status.setPlainText('已保存生图连接：'+image.capability_status if image else '选择已有Codex程序并检测登录；检测不会生成内容。')
        layout.addWidget(self.status)
        layout.addStretch()
        self.operation=None
        self.poll=QTimer(self)
        self.poll.setInterval(50)
        self.poll.timeout.connect(self.complete)
    def choose(self):
        path,_=QFileDialog.getOpenFileName(self,'选择Codex程序','','Codex (*.exe *.cmd *.js)')
        if path:
            self.path.setText(path)
    def save(self):
        path,model=self.path.text().strip(),self.model.text().strip()
        if not model:
            raise ValueError('请填写宿主模型名称')
        old=next((c for c in self.owner.connections.all() if c.id==self.text_id),None)
        text=replace(old,cli_path=path,model=model,enabled=self.text_on.isChecked()) if old else Connection(self.text_id,'Codex文字创作','codex',model,cli_path=path,enabled=self.text_on.isChecked())
        if old and (old.model,old.cli_path)!=(model,path):
            text=replace(text,verification={},capability_status='未验证')
        self.owner.connections.save(text)
        old=next((c for c in self.owner.image_connections.all() if c.id==self.image_id),None)
        image=replace(old,cli_path=path,model=model,enabled=self.image_on.isChecked()) if old else ImageConnection(self.image_id,'Codex生图','image_codex',model,cli_path=path,enabled=self.image_on.isChecked(),sizes=('1024x1024','1024x1536','1536x1024'))
        if old and (old.model,old.cli_path)!=(model,path):
            image=replace(image,verification={},capability_status='未验证')
        self.owner.image_connections.save(image)
        self.owner.refresh_models()
        self.status.setPlainText('Codex文字与生图接入已保存；只有你点击生成时才提交任务。')
    def detect(self):
        if self.operation:
            return
        from app.ui.model_settings import Operation
        self.operation=Operation(lambda:CodexTextProvider().detect(self.path.text().strip(),login=True))
        self.status.setPlainText('正在检测本机Codex…')
        self.poll.start()
        QThreadPool.globalInstance().start(self.operation)
    def complete(self):
        if self.operation and self.operation.completed.is_set():
            operation=self.operation
            self.operation=None
            self.poll.stop()
            self.status.setPlainText(operation.error or operation.result['version']+'\n'+('登录有效' if operation.result['logged_in'] else '尚未登录，请先在本机完成Codex登录'))
