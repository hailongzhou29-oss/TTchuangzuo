"""All connection, CLI and appearance settings live inside the main page."""
import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from PySide6.QtCore import QThreadPool,QTimer
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QTabWidget,QComboBox,QLineEdit,QSpinBox,QCheckBox,QTextBrowser,QFileDialog,QScrollArea,QMenu)
from app.ui.v2_widgets import label,button,PALETTES,QComboBox
from app.ui.model_settings import Operation
from app.providers.contracts import Connection,CancelToken,PRESETS,redact
from app.providers.image_contracts import ImageConnection
from app.providers.codex_text import CodexTextProvider,command_prefix,HIDDEN
from app.providers.http_text import HttpTextProvider
from app.storage.project import new_id

class SettingsPage(QWidget):
    def __init__(self,owner):
        super().__init__(); self.owner=owner; self.operations=[]; self.pool=QThreadPool.globalInstance()
        layout=QVBoxLayout(self); layout.setContentsMargins(24,20,24,20); layout.addWidget(label('设置','heading'))
        self.tabs=QTabWidget(); layout.addWidget(self.tabs,1)
        self.text=self.connection_form(False); self.image=self.connection_form(True)
        self.build_cli(); self.build_appearance(); self.build_advanced()
        self.poll=QTimer(self); self.poll.setInterval(60); self.poll.timeout.connect(self.complete)
        self.refresh()
    def tab(self,title):
        area=QScrollArea(); area.setWidgetResizable(True); page=QWidget(); col=QVBoxLayout(page); col.setContentsMargins(20,20,20,20); col.setSpacing(12); area.setWidget(page); self.tabs.addTab(area,title); return page,col
    def connection_form(self,image):
        page,col=self.tab('通用生图' if image else '国内大模型'); fields={}; form=QFormLayout(); form.setHorizontalSpacing(16); form.setVerticalSpacing(10)
        if not image:
            provider=QComboBox()
            for pid,name in [('deepseek','DeepSeek'),('ark','火山方舟'),('qwen','通义千问'),('custom','第三方中转')]: provider.addItem(name,pid)
            fields['provider']=provider; form.addRow('渠道',provider); provider.currentIndexChanged.connect(lambda:self.refresh_connections(fields,False))
        chooser=QComboBox(); fields['connection']=chooser; row=QHBoxLayout(); row.addWidget(chooser,1); row.addWidget(button('新增',lambda:self.new(fields,image))); more=button('…',lambda:self.connection_menu(fields,image),quiet=True); row.addWidget(more); form.addRow('连接',row)
        chooser.currentIndexChanged.connect(lambda:self.load(fields,image))
        for key,title,placeholder in [('name','连接名称','给这个连接起个名字'),('base_url','接口地址','填写服务商提供的接口地址'),('key','接口密钥','空白会保留已保存的密钥'),('model','模型','手填实际模型或推理接入点标识')]:
            w=QLineEdit(); w.setPlaceholderText(placeholder); fields[key]=w
            if key=='key':
                w.setEchoMode(QLineEdit.EchoMode.Password); kr=QHBoxLayout(); kr.addWidget(w,1); eye=button('显示',lambda w=w:w.setEchoMode(QLineEdit.EchoMode.Normal if w.echoMode()==QLineEdit.EchoMode.Password else QLineEdit.EchoMode.Password),quiet=True); eye.setToolTip('显示密钥 / 隐藏密钥'); kr.addWidget(eye); form.addRow(title,kr)
            else: form.addRow(title,w)
        if image:
            fields['sizes']=QLineEdit('1024x1024'); form.addRow('支持的尺寸',fields['sizes'])
            fields['quality']=QLineEdit(); fields['quality'].setPlaceholderText('已知质量选项，逗号分隔；未知留空'); form.addRow('默认质量',fields['quality'])
            fields['edit']=QCheckBox('图生图（仅接口已支持时声明）'); form.addRow('能力',fields['edit'])
            fields['ratio']=QComboBox(); fields['ratio'].addItems(['3:4','2:3','1:1','16:9']); form.addRow('默认比例',fields['ratio'])
        else:
            protocol=QComboBox(); protocol.addItem('OpenAI 兼容'); form.addRow('协议',protocol)
            form.addRow('',button('读取模型',lambda:self.owner.run(lambda:self.read_models(fields))))
        fields['default']=QCheckBox('设为默认生图渠道' if image else '设为默认文本模型'); form.addRow('',fields['default'])
        col.addLayout(form)
        advanced=QWidget(); adv=QFormLayout(advanced); advanced.hide()
        fields['timeout']=QSpinBox(); fields['timeout'].setRange(10,1800); fields['timeout'].setValue(300); adv.addRow('超时 / 秒',fields['timeout'])
        if image:
            fields['generate_path']=QLineEdit('/images/generations'); adv.addRow('生成路径',fields['generate_path'])
            fields['edit_path']=QLineEdit('/images/edits'); adv.addRow('编辑路径',fields['edit_path'])
            fields['poll_path']=QLineEdit(); fields['poll_path'].setPlaceholderText('/tasks/{job_id}'); adv.addRow('任务查询路径',fields['poll_path'])
            fields['asset_hosts']=QLineEdit(); fields['asset_hosts'].setPlaceholderText('允许下载的资源域名，逗号分隔'); adv.addRow('资源域名',fields['asset_hosts'])
            adv.addRow('协议模板',label('OpenAI 兼容图片接口','muted'))
        else:
            fields['max_output']=QSpinBox(); fields['max_output'].setRange(128,65536); fields['max_output'].setValue(8192); adv.addRow('最大输出 token',fields['max_output'])
            fields['context_limit']=QSpinBox(); fields['context_limit'].setRange(1024,2000000); fields['context_limit'].setValue(65536); adv.addRow('上下文上限 token',fields['context_limit'])
        col.addWidget(button('高级接口选项',lambda:advanced.setVisible(not advanced.isVisible()),quiet=True)); col.addWidget(advanced)
        actions=QHBoxLayout(); actions.addWidget(button('测试生图' if image else '测试连接',lambda:self.owner.run(lambda:self.test_image(fields) if image else self.test_text(fields)),False)); actions.addWidget(button('保存配置',lambda:self.owner.run(lambda:self.save(fields,image)),True)); actions.addStretch(); col.addLayout(actions)
        col.addWidget(label('将生成1张测试图，费用由当前服务商收取' if image else '测试可能产生少量调用费用','muted')); fields['status']=label('','muted'); col.addWidget(fields['status']); col.addStretch(); return fields
    def store(self,image): return self.owner.image_connections if image else self.owner.connections
    def refresh(self): self.refresh_connections(self.text,False); self.refresh_connections(self.image,True)
    def refresh_connections(self,f,image):
        if not f.get('connection'): return
        cid=f['connection'].currentData(); f['connection'].blockSignals(True); f['connection'].clear(); f['connection'].addItem('新连接',None)
        for c in self.store(image).all():
            if c.provider==('image_http' if image else f['provider'].currentData()): f['connection'].addItem(c.name,c.id)
        index=f['connection'].findData(cid) if cid else 1 if f['connection'].count()>1 else 0
        f['connection'].setCurrentIndex(max(0,index)); f['connection'].blockSignals(False); self.load(f,image)
    def new(self,f,image): f['connection'].setCurrentIndex(0); self.load(f,image)
    def load(self,f,image):
        cid=f['connection'].currentData(); c=self.store(image).get(cid) if cid else None
        for key in ('name','base_url','model'): f[key].setText(getattr(c,key) if c else '新连接' if key=='name' else PRESETS[f['provider'].currentData()][1] if key=='base_url' and not image else '')
        f['key'].clear(); f['timeout'].setValue(c.timeout if c else 300)
        f['default'].setChecked(cid==self.owner.options.get('default_image' if image else 'default_connection'))
        if image:
            f['sizes'].setText(','.join(c.sizes) if c else '1024x1024'); f['quality'].setText(','.join(c.qualities) if c else ''); f['edit'].setChecked(c.supports_edit if c else False); f['poll_path'].setText(c.poll_path if c else ''); f['asset_hosts'].setText(','.join(c.asset_hosts) if c else '')
            f['generate_path'].setText(c.generate_path if c else '/images/generations'); f['edit_path'].setText(c.edit_path if c else '/images/edits')
        else: f['max_output'].setValue(c.max_output if c else 8192); f['context_limit'].setValue(c.context_limit if c else 65536)
    def candidate(self,f,image,allow_empty_model=False):
        cid=f['connection'].currentData() or new_id(); old=self.store(image).get(cid) if f['connection'].currentData() else None
        values=dict(id=cid,name=f['name'].text().strip(),base_url=f['base_url'].text().strip(),model=f['model'].text().strip(),timeout=f['timeout'].value())
        if image:
            values.update(provider='image_http',sizes=tuple(v.strip() for v in f['sizes'].text().split(',') if v.strip()),qualities=tuple(v.strip() for v in f['quality'].text().split(',') if v.strip()),supports_edit=f['edit'].isChecked(),poll_path=f['poll_path'].text().strip(),asset_hosts=tuple(v.strip() for v in f['asset_hosts'].text().split(',') if v.strip()))
            values.update(generate_path=f['generate_path'].text().strip(),edit_path=f['edit_path'].text().strip())
            c=replace(old,**values) if old else ImageConnection(**values)
        else:
            values.update(provider=f['provider'].currentData(),max_output=f['max_output'].value(),context_limit=f['context_limit'].value())
            c=replace(old,**values) if old else Connection(**values)
        c.validate(require_model=not allow_empty_model); return c
    def request_secret(self,f,c):
        entered=f['key'].text().strip()
        if entered: return entered
        if not f['connection'].currentData(): raise ValueError('请先填写密钥')
        old=self.owner.connections.get(c.id)
        from urllib.parse import urlparse
        if old.provider!=c.provider or urlparse(old.base_url).hostname!=urlparse(c.base_url).hostname:
            raise ValueError('接口地址改变后，请重新填写密钥')
        return self.owner.connections.secret_snapshot(old)
    def save(self,f,image):
        c=self.candidate(f,image); self.store(image).save(c,f['key'].text().strip() or None)
        if f['default'].isChecked(): self.owner.options['default_image' if image else 'default_connection']=c.id
        self.owner.save_options(); self.refresh_connections(f,image); f['connection'].setCurrentIndex(f['connection'].findData(c.id)); f['status'].setText('配置已保存'); self.owner.assistant.refresh_models()
    def read_models(self,f):
        c=self.candidate(f,False,True); secret=self.request_secret(f,c)
        def done(result):
            names=result.get('models',result) if isinstance(result,dict) else result
            menu=QMenu(self)
            for row in names:
                name=row.get('id') if isinstance(row,dict) else str(row); menu.addAction(name,lambda name=name:f['model'].setText(name))
            menu.exec(f['model'].mapToGlobal(f['model'].rect().bottomLeft()))
        # Model reading supports a blank hand-entered model.
        self.operation(lambda:HttpTextProvider().list_models(c,secret),done,f['status'])
    def test_text(self,f):
        c=replace(self.candidate(f,False),max_output=128,timeout=min(f['timeout'].value(),90))
        secret=self.request_secret(f,c)
        self.operation(lambda:HttpTextProvider().generate(c,secret,[dict(role='user',content='请回复连接成功')],CancelToken()),lambda r:f['status'].setText('连接成功' if r.status=='completed' else r.error or r.status),f['status'])
    def test_image(self,f):
        # Explicit button saves a temporary independent connection only after config is saved.
        if not f['connection'].currentData(): raise ValueError('先保存生图配置，再点击测试生图')
        self.owner.test_image_connection(self.store(True).get(f['connection'].currentData()),f['status'])
    def connection_menu(self,f,image):
        cid=f['connection'].currentData()
        if not cid: return
        menu=QMenu(self); menu.addAction('重命名',lambda:f['name'].setFocus()); menu.addAction('移除连接',lambda:self.owner.confirm_inline('移除连接会删除本软件保存的该连接配置，不会注销服务商账户',lambda:self.remove(f,image),parent=self)); menu.addAction('清除已保存密钥',lambda:self.owner.confirm_inline('清除后需要重新填写密钥才能调用',lambda:self.clear_key(f,image),parent=self)); menu.exec(f['connection'].mapToGlobal(f['connection'].rect().bottomLeft()))
    def remove(self,f,image): self.store(image).delete(f['connection'].currentData()); self.refresh_connections(f,image); self.owner.assistant.refresh_models()
    def clear_key(self,f,image):
        c=self.store(image).get(f['connection'].currentData()); self.store(image).save(c,''); f['status'].setText('已清除密钥')
    def operation(self,function,completed,status,on_error=None):
        if self.operations: status.setText('正在处理，请等待'); return
        op=Operation(function); self.operations.append((op,completed,status,on_error)); status.setText('正在处理…'); self.pool.start(op); self.poll.start()
    def complete(self):
        for item in list(self.operations):
            op,callback,status,on_error=item
            if op.completed.is_set():
                self.operations.remove(item)
                if op.error:
                    status.setText(redact(op.error))
                    if on_error: on_error()
                else: self.owner.run(lambda:callback(op.result))
        if not self.operations: self.poll.stop()
    def build_cli(self):
        page,col=self.tab('Codex CLI'); self.cli_status=label('未检测到 Codex CLI','muted'); col.addWidget(self.cli_status); form=QFormLayout()
        saved=next((c for c in self.owner.connections.all() if c.provider=='codex'),None); self.cli_text_id=saved.id if saved else 'codex_v2_text'
        image=next((c for c in self.owner.image_connections.all() if c.provider=='image_codex'),None); self.cli_image_id=image.id if image else 'codex_v2_image'
        self.cli_path=QLineEdit(saved.cli_path if saved else image.cli_path if image else shutil.which('codex.cmd') or shutil.which('codex.exe') or '')
        row=QHBoxLayout(); row.addWidget(self.cli_path,1); row.addWidget(button('重新检测',lambda:self.owner.run(self.detect_cli))); row.addWidget(button('选择程序',self.choose_cli)); form.addRow('程序位置',row)
        self.cli_version=label('未读取'); self.cli_login=label('未读取'); form.addRow('版本',self.cli_version); form.addRow('登录状态',self.cli_login); form.addRow('',button('登录',lambda:self.owner.run(self.login_cli)))
        self.cli_model=QLineEdit(saved.model if saved else image.model if image else ''); self.cli_model.setPlaceholderText('填写本机已支持的模型'); form.addRow('文本模型',self.cli_model)
        self.cli_image_status=label(image.capability_status if image else '当前生图未验证'); form.addRow('生图状态',self.cli_image_status); col.addLayout(form)
        actions=QHBoxLayout(); actions.addWidget(button('测试文本',lambda:self.owner.run(self.test_cli_text))); actions.addWidget(button('测试生图',lambda:self.owner.run(self.test_cli_image))); actions.addWidget(button('保存配置',lambda:self.owner.run(self.save_cli),True)); col.addLayout(actions)
        col.addWidget(label('使用当前 Codex 账户的额度；文本与生图分别验证','muted')); col.addStretch()
    def choose_cli(self):
        path,_=QFileDialog.getOpenFileName(self,'选择程序','','Codex (*.exe *.cmd *.ps1 *.js)')
        if path: self.cli_path.setText(path)
    def detect_cli(self):
        path=self.cli_path.text().strip()
        def done(r): self.cli_version.setText(r['version']); self.cli_login.setText('已登录' if r['logged_in'] else '需要登录'); self.cli_status.setText('可以使用' if r['logged_in'] else '需要登录')
        self.operation(lambda:CodexTextProvider().detect(path,login=True),done,self.cli_status)
    def login_cli(self):
        if self.cli_login.text()=='已登录': self.cli_status.setText('已登录'); return
        prefix=command_prefix(self.cli_path.text().strip())
        self.operation(lambda:subprocess.run(prefix+['login'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300,creationflags=HIDDEN).returncode,lambda rc:self.cli_status.setText('登录流程完成，请重新检测' if rc==0 else '登录未完成，请在本机完成登录后重新检测'),self.cli_status)
    def save_cli(self):
        model=self.cli_model.text().strip(); path=self.cli_path.text().strip()
        if not model: raise ValueError('填写本机可用模型名称')
        old=next((c for c in self.owner.connections.all() if c.id==self.cli_text_id),None)
        text=replace(old,model=model,cli_path=path) if old else Connection(self.cli_text_id,'Codex CLI','codex',model,cli_path=path,max_output=8192,timeout=300,context_limit=65536)
        self.owner.connections.save(text)
        old=next((c for c in self.owner.image_connections.all() if c.id==self.cli_image_id),None)
        image=replace(old,model=model,cli_path=path) if old else ImageConnection(self.cli_image_id,'Codex 生图','image_codex',model,cli_path=path,sizes=('1024x1024','1024x1536','1536x1024'))
        self.owner.image_connections.save(image); self.cli_status.setText('配置已保存'); self.owner.assistant.refresh_models()
    def test_cli_text(self):
        c=Connection(self.cli_text_id,'Codex CLI','codex',self.cli_model.text().strip(),cli_path=self.cli_path.text().strip(),timeout=90,max_output=128)
        self.operation(lambda:CodexTextProvider().generate(c,[dict(role='user',content='只回复连接成功')],CancelToken()),lambda r:self.cli_status.setText('文本测试成功' if r.status=='completed' else r.error or r.status),self.cli_status)
    def test_cli_image(self):
        self.owner.test_image_connection(self.owner.image_connections.get(self.cli_image_id),self.cli_image_status)
    def build_appearance(self):
        page,col=self.tab('外观与保存'); form=QFormLayout()
        theme=QComboBox(); theme.addItems(PALETTES); theme.setCurrentText(self.owner.theme); theme.currentTextChanged.connect(self.owner.set_theme); form.addRow('主题',theme)
        font=QComboBox(); font.addItems(['15','17','19','21']); font.setCurrentText(str(self.owner.options.get('editor_font_size',17))); font.currentTextChanged.connect(lambda value:self.owner.set_font(int(value))); form.addRow('正文字号',font)
        self.project_path=label(str(self.owner.workspace.root)); form.addRow('项目位置',self.project_path); row=QHBoxLayout(); row.addWidget(button('打开文件夹',lambda:os.startfile(self.owner.workspace.root))); row.addWidget(button('更改位置',lambda:self.owner.run(self.owner.migrate_workspace))); form.addRow('',row)
        auto=QCheckBox('停止输入约1秒后保存'); auto.setChecked(self.owner.options.get('autosave',True)); auto.toggled.connect(lambda v:self.preference('autosave',v)); form.addRow('自动保存',auto)
        retention=QComboBox(); retention.addItems(['5','10','20']); retention.setCurrentText(str(self.owner.options.get('backup_retention',10))); retention.currentTextChanged.connect(lambda v:self.preference('backup_retention',int(v))); form.addRow('备份保留',retention)
        restore=QCheckBox('启动时恢复上次作品'); restore.setChecked(self.owner.options.get('restore_last',True)); restore.toggled.connect(lambda v:self.preference('restore_last',v)); form.addRow('',restore); col.addLayout(form); col.addStretch()
    def preference(self,key,value): self.owner.options[key]=value; self.owner.save_options()
    def build_advanced(self):
        page,col=self.tab('高级')
        for name,callback in [('调用记录',self.show_usage),('费用控制',self.show_budget),('诊断',self.show_diagnostics),('数据备份',self.show_backups)]: col.addWidget(button(name,lambda callback=callback:self.owner.run(callback),quiet=True))
        self.details=QTextBrowser(); col.addWidget(self.details,1)
    def show_usage(self):
        if not self.owner.work: self.details.setPlainText('暂无调用记录'); return
        with self.owner.work.store.connection() as con: rows=con.execute('SELECT u.connection_name,u.model,u.usage,u.created,t.state FROM usage_ledger u JOIN tasks t ON t.id=u.task_id ORDER BY u.rowid DESC LIMIT 100').fetchall()
        lines=[]
        for r in rows:
            usage=json.loads(r['usage']); state={'completed':'完成','verified':'图片已验证','failed':'失败','cancelled':'已停止','invalid_output':'格式未完成','uncertain':'状态待确认'}.get(r['state'],'已记录')
            lines.append(r['created']+' · '+r['connection_name']+' · '+r['model']+'\n状态：'+state+'；输入数量：'+str(usage.get('input') if usage.get('input') is not None else '未知')+'；输出数量：'+str(usage.get('output') if usage.get('output') is not None else '未知')+'；实际费用：'+str(usage.get('actual_cost') if usage.get('actual_cost') is not None else '未知'))
        self.details.setPlainText('\n\n'.join(lines) or '暂无调用记录')
    def show_budget(self): self.owner.show_budget_panel()
    def show_diagnostics(self):
        menu=QMenu(self); menu.addAction('打开日志文件夹',lambda:self.owner.open_logs()); menu.addAction('导出诊断包',lambda:self.owner.run(self.owner.export_diagnostics)); menu.exec(self.mapToGlobal(self.rect().center()))
    def show_backups(self):
        menu=QMenu(self); menu.addAction('备份项目',lambda:self.owner.run(self.owner.backup_project)); menu.addAction('恢复项目',lambda:self.owner.run(self.owner.restore_project)); menu.exec(self.mapToGlobal(self.rect().center()))
