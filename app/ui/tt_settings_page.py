"""TT's three settings pages in the main window, with isolated local services."""
import copy,subprocess
from app import __version__
from types import SimpleNamespace
from PySide6.QtCore import QTimer,QThreadPool,Qt,QSize,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import *
from app.core.settings_controller import *
from app.ui.tt_settings_widgets import SearchableModelCombo,TTSettingsWidgets
from app.ui.settings_page import SettingsPage as LegacySettingsPage
from app.ui.v2_widgets import label,button,QComboBox
from app.ui.interaction import AnimatedButton as QPushButton
from app.ui.commercial_controls import TaskStatus
from app.core.output_files import CATEGORIES,OutputFiles
from pathlib import Path
from app.providers.codex_text import HIDDEN

class SettingsHost:
    def __init__(self,page): self.page=page
    def run_async(self,title,function,completed,on_failure=None,**kwargs): self.page.operation(function,completed,self.page.status,on_failure,title=title)
    def on_project_changed(self,**kwargs): self.page.owner.assistant.refresh_models()

class SettingsPage(QWidget,TTSettingsWidgets):
    def operation(self,function,completed,status,on_error=None,title='处理任务'):
        if self.operations: status.setText('任务正在进行，请等待完成'); return
        from app.ui.model_settings import Operation
        op=Operation(function); op.title=title; self.operations.append((op,completed,status,on_error)); status.set_busy(True); status.setText('正在'+title+'…'); self.pool.start(op); self.poll.start()
    def complete(self):
        from app.providers.contracts import redact
        for item in list(self.operations):
            op,callback,status,on_error=item
            if not op.completed.is_set(): continue
            self.operations.remove(item)
            self._callback_status=status
            try:
                if op.error:
                    message=redact(op.error); status.setText(message)
                    if on_error: self.owner.run(lambda:on_error(message))
                else:
                    callback(op.result)
                    if status.text().startswith(('正在','任务正在')): status.setText(op.title+'完成')
                    state=op.result.get('status') if isinstance(op.result,dict) else getattr(op.result,'status',None)
                    if state in {None,'completed','verified','ready','success'}: self.owner.play_task_sound()
            except (ValueError,OSError,RuntimeError,TypeError,KeyError) as exc:
                status.setText('任务失败：'+redact(str(exc)))
                if on_error: self.owner.run(lambda:on_error(redact(str(exc))))
            finally: status.set_busy(False); self._callback_status=None
        if not self.operations: self.poll.stop()
    def __init__(self,owner):
        QWidget.__init__(self); self.owner=owner; self.c=SettingsController(owner); self.host=SettingsHost(self); self.operations=[]; self.pool=QThreadPool.globalInstance(); self.loading_image=True; self._codex_detecting=False; self._codex_detected=False
        root=QVBoxLayout(self); root.setContentsMargins(24,20,24,20); root.setSpacing(12); heading=QHBoxLayout(); heading.addWidget(label('设置','heading'),1); root.addLayout(heading); self.setObjectName('TTSettingsRoot')
        self.tabs=QTabWidget(); self.tabs.setObjectName('SettingsSectionTabs'); self.tabs.tabBar().setObjectName('SettingsSectionTabBar'); self.tabs.tabBar().setExpanding(False); root.addWidget(self.tabs,1)
        self.forms={}; self.output_controls={}; self.format_controls={}; self.legacy_controls={}; self.key_status_labels={}; self.model_status_labels={}; self.model_catalog={}; self.channel_save_buttons={}; self.api_provider_keys=MODEL_CHANNEL_KEYS[:-1]
        self.language_model_tab=QWidget(); language_layout=QVBoxLayout(self.language_model_tab); language_layout.setContentsMargins(12,12,12,12); language_layout.setSpacing(11)
        self.provider_list=QListWidget(); self.provider_list.setObjectName('DomesticProviderList'); self.provider_list.setFlow(QListView.Flow.LeftToRight); self.provider_list.setWrapping(False); self.provider_list.setMovement(QListView.Movement.Static); self.provider_list.setSpacing(8); self.provider_list.setFixedHeight(76); self.provider_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); self.provider_stack=QStackedWidget(); self.provider_stack.setObjectName('DomesticProviderStack'); language_layout.addWidget(self.provider_list); language_layout.addWidget(self.provider_stack,1)
        for key in self.api_provider_keys:
            cfg=self.c.channel_configs[key]; page=QWidget(); form=QFormLayout(page); base=QLineEdit(cfg.base_url); key_edit=QLineEdit(); key_edit.setEchoMode(QLineEdit.EchoMode.Password); key_edit.setPlaceholderText('留空则继续使用已安全保存的密钥'); model=SearchableModelCombo(); model.set_catalog([(cfg.model,cfg.model)] if cfg.model else [],cfg.model)
            key_status=QLabel(); key_status.setProperty('muted',True); delete_key=QPushButton('删除已保存密钥'); key_row=QHBoxLayout(); key_row.addWidget(key_edit,1); key_row.addWidget(key_status); key_row.addWidget(delete_key)
            model_status=QLabel('模型能力尚未验证'); model_status.setProperty('muted',True); model_row=QHBoxLayout(); model_row.addWidget(model,1); model_row.addWidget(model_status)
            load=QPushButton('刷新模型列表'); test=QPushButton('测试连接'); save=QPushButton('保存当前接口设置'); save.setProperty('success',True); row=QHBoxLayout(); row.addWidget(load); row.addWidget(test); row.addWidget(save)
            if key in MODEL_KEY_URLS:
                official=QPushButton('申请/管理官方 API Key'); official.clicked.connect(lambda _=False,url=MODEL_KEY_URLS[key]:QDesktopServices.openUrl(QUrl(url))); row.addWidget(official)
            form.addRow('接口地址',base); form.addRow('接口密钥',key_row); form.addRow('模型（可搜索／可展开）',model_row)
            mode=QComboBox(); mode.addItem('手动上限（保留已保存值）','manual'); mode.addItem('自动按本次作品目标（推荐）','auto'); mode.setCurrentIndex(max(0,mode.findData(cfg.output_mode)))
            tokens=QSpinBox(); tokens.setRange(128,min(65536,cfg.context_limit)); tokens.setSingleStep(128); tokens.setSuffix(' token'); tokens.setValue(cfg.max_output); tokens.setVisible(cfg.output_mode=='manual')
            length_row=QHBoxLayout(); length_row.addWidget(mode,1); length_row.addWidget(tokens); form.addRow('输出长度',length_row)
            advanced=QWidget(); advanced_form=QFormLayout(advanced); advanced_form.setContentsMargins(0,0,0,0)
            format_mode=QComboBox(); format_mode.addItem('软件自动适配（推荐）','auto'); format_mode.addItem('使用我的手动结果格式','manual'); format_mode.setCurrentIndex(max(0,format_mode.findData(cfg.format_mode)))
            structured=QCheckBox('模型支持 JSON 输出'); structured.setChecked(cfg.json_mode); structured.setEnabled(cfg.format_mode=='manual'); advanced_form.addRow('结果格式',format_mode); advanced_form.addRow(structured)
            format_mode.currentIndexChanged.connect(lambda _,w=structured,m=format_mode:w.setEnabled(m.currentData()=='manual'))
            toggle=QPushButton('高级模型设置 ▾'); toggle.setCheckable(True); toggle.toggled.connect(advanced.setVisible); form.addRow(toggle); form.addRow(advanced); advanced.hide(); self.format_controls[key]=format_mode
            note=QLabel(''); note.setWordWrap(True); note.setProperty('muted',True); form.addRow(note)
            self.output_controls[key]=(mode,tokens,structured,note); self.forms[key]=(base,key_edit,model)
            mode.currentIndexChanged.connect(lambda _,k=key:self.update_output_hint(k)); tokens.valueChanged.connect(lambda _,k=key:self.update_output_hint(k)); base.textChanged.connect(lambda _,k=key:self.update_output_hint(k)); model.currentTextChanged.connect(lambda _,k=key:self.update_output_hint(k))
            self.update_output_hint(key); form.addRow(row)
            from app.core.test_isolation import legacy_test_profile
            if legacy_test_profile(cfg) and not self.owner.options.get('legacy_test_128_ack:'+cfg.id):
                warning=QWidget(); warning_layout=QVBoxLayout(warning); warning_layout.setContentsMargins(0,0,0,0); text=QLabel('发现与旧软件通道测试完全匹配的128 token连接。完整作品可能被截断。可改用推荐自动模式；原手动数值和凭据保留，也可明确保留现值。'); text.setWordWrap(True); warning_layout.addWidget(text)
                fix=QPushButton('使用推荐自动模式'); keep=QPushButton('保留我的手动设置'); choices=QHBoxLayout(); choices.addWidget(fix); choices.addWidget(keep); warning_layout.addLayout(choices); form.addRow(warning); self.legacy_controls[key]=(warning,fix,keep)
                fix.clicked.connect(lambda _,k=key:self.resolve_legacy_limit(k,True)); keep.clicked.connect(lambda _,k=key:self.resolve_legacy_limit(k,False))
            item=QListWidgetItem(MODEL_CHANNEL_LABELS[key]); item.setData(Qt.ItemDataRole.UserRole,key); item.setSizeHint(QSize(240,54)); self.provider_list.addItem(item); self.provider_stack.addWidget(page); self.forms[key]=(base,key_edit,model); self.key_status_labels[key]=key_status; self.model_status_labels[key]=model_status; self.channel_save_buttons[key]=save
            load.clicked.connect(lambda _,k=key:self.load_models(k)); test.clicked.connect(lambda _,k=key:self.test(k)); save.clicked.connect(lambda _,k=key:self.save_current_channel(k)); delete_key.clicked.connect(lambda _,k=key:self.delete_model_key(k))
        self.tabs.addTab(self.language_model_tab,'国内模型'); self._build_codex_tab(); self._build_openai_image_settings_tab(); self.openai_image_protocol.model().item(1).setEnabled(False); self.openai_image_protocol.setItemText(0,'OpenAI 兼容（已实现协议）'); self.openai_image_protocol.setItemText(1,'Seedance.NZ 专用协议（尚未接入）'); self.loading_image=False
        # Preserve each original form and tab identity; allow access at smaller widths.
        for index in range(self.tabs.count()):
            page=self.tabs.widget(index)
            if isinstance(page,QScrollArea): continue
            inner=QWidget(); inner.setLayout(page.layout()); scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(inner)
            outer=QVBoxLayout(page); outer.setContentsMargins(0,0,0,0); outer.addWidget(scroll)
        self._build_advanced_tab()
        self.channel_save=QPushButton('启用当前模型'); self.channel_save.setProperty('success',True); self.channel_save.clicked.connect(self.activate_current_model); self.clear_keys_button=QPushButton('清除本机保存的全部密钥'); self.clear_keys_button.clicked.connect(self.clear_all_keys); bottom=QHBoxLayout(); bottom.addWidget(self.clear_keys_button); bottom.addStretch(); bottom.addWidget(self.channel_save); root.addLayout(bottom)
        self.status_stack=QStackedWidget(); self.status_labels={}; self._callback_status=None
        for key in MODEL_CHANNEL_KEYS+['images','advanced']:
            status=TaskStatus(self); self.status_labels[key]=status; self.status_stack.addWidget(status)
        self.status_stack.setFixedWidth(420); self.status_stack.setFixedHeight(40); heading.addWidget(self.status_stack); self.status_stack.hide(); self.poll=QTimer(self); self.poll.setInterval(60); self.poll.timeout.connect(self.complete)
        self.provider_list.currentRowChanged.connect(self.provider_changed); self.tabs.currentChanged.connect(self.update_settings_actions); self.provider_list.setCurrentRow(self.api_provider_keys.index(self.c.active_provider) if self.c.active_provider in self.api_provider_keys else 1); self.update_all_key_statuses(); self.update_settings_actions(0)
        for control in self.findChildren(QPushButton):
            if control.property('success') or control.text() in {'保存模型设置','保存路径'}: control.setObjectName('primary')
        self.codex_model.textChanged.connect(lambda _:self.update_settings_actions(self.tabs.currentIndex())); self.codex_override.textChanged.connect(lambda _:self.update_settings_actions(self.tabs.currentIndex()))
        for _,secret,_ in self.forms.values(): secret.textChanged.connect(lambda _:self.update_settings_actions(self.tabs.currentIndex()))
        self.refresh_cached_codex_ui()
    @property
    def status(self):
        if self._callback_status is not None: return self._callback_status
        return self.status_labels[self.status_key()]
    def status_key(self):
        return self.current_provider() or ('images' if self.tabs.currentIndex()==2 else 'advanced')
    def _build_advanced_tab(self):
        self.advanced_tab=QWidget(); outer=QVBoxLayout(self.advanced_tab); outer.setContentsMargins(0,0,0,0); scroll=QScrollArea(); scroll.setWidgetResizable(True); content=QWidget(); layout=QVBoxLayout(content); layout.setContentsMargins(20,20,20,20); layout.setSpacing(16); scroll.setWidget(content); outer.addWidget(scroll)
        layout.addWidget(label('源码开发版 · '+__version__,'muted'))
        layout.addWidget(label('界面主题','sectionHeading')); theme_row=QHBoxLayout(); theme_row.addWidget(label('主题'))
        self.theme_selector=QComboBox()
        for title,name in [('雾白浅色','清透白'),('石墨深色','石墨紫'),('暖纸写作','暖纸色')]: self.theme_selector.addItem(title,name)
        self.theme_selector.setCurrentIndex(self.theme_selector.findData(self.owner.theme)); self.theme_selector.currentIndexChanged.connect(lambda _:self.owner.set_theme(self.theme_selector.currentData())); theme_row.addWidget(self.theme_selector,1); layout.addLayout(theme_row)
        motion_row=QHBoxLayout(); motion_row.addWidget(label('界面动态')); self.motion_selector=QComboBox(); self.motion_selector.addItem('标准动态',False); self.motion_selector.addItem('减少动态',True); self.motion_selector.setCurrentIndex(1 if self.owner.motion.reduced() else 0); motion_row.addWidget(self.motion_selector,1); layout.addLayout(motion_row); self.motion_selector.currentIndexChanged.connect(self.set_motion_preference)
        sound_row=QHBoxLayout(); sound_row.addWidget(label('任务提示音')); self.sound_toggle=QCheckBox('任务完成时播放'); self.sound_toggle.setChecked(self.owner.options.get('task_completion_sound',True)); sound_row.addWidget(self.sound_toggle,1); self.sound_preview=button('试听',lambda:self.owner.play_task_sound(force=True)); sound_row.addWidget(self.sound_preview); layout.addLayout(sound_row); self.sound_toggle.toggled.connect(self.set_sound_preference)
        layout.addWidget(label('模型列表读取、连接检测和写作任务完成时提示；关闭后不播放。','muted'))
        layout.addWidget(label('文件与存储','sectionHeading')); form=QFormLayout(); layout.addLayout(form); self.path_fields={}
        paths={'internal':('内部数据目录',self.owner.preferences.parent),'database':('项目数据库目录',self.owner.workspace.root),'logs':('日志目录',self.owner.preferences.parent/'logs'),'output':('作品总目录',self.owner.output_files.root)}
        paths.update({name:(name+'输出目录',path) for name,path in self.owner.output_files.paths().items()})
        for key,(caption,path) in paths.items():
            field=QLineEdit(str(path)); field.setReadOnly(True); self.path_fields[key]=field; row=QHBoxLayout(); row.addWidget(field,1)
            if key=='output': row.addWidget(button('选择作品总目录',lambda:self.owner.run(self.choose_output_root),True))
            row.addWidget(button('打开文件夹',lambda _,k=key:self.owner.run(lambda:self.open_path(k)))); form.addRow(caption,row)
        note=label('本软件的项目、正文、图片、设置、日志和缓存全部保存在作品总目录。请选择 C 盘以外的文件夹；更换为空目录后自动迁移全部数据，迁移成功后清理旧目录。','muted'); layout.addWidget(note)
        layout.addStretch(); self.tabs.addTab(self.advanced_tab,'高级设置')
    def open_folder(self,path):
        if not path: return
        folder=Path(path)
        if not folder.is_dir(): raise ValueError('目录尚未创建；保存作品后会自动创建输出目录')
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve()))): raise ValueError('无法打开文件夹')
    def set_motion_preference(self,*_):
        self.owner.options['reduce_motion']=self.motion_selector.currentData(); self.owner.motion.stop_all(); self.owner.save_options()
    def open_path(self,key): self.open_folder(self.path_fields[key].text())
    def choose_output_root(self):
        path=QFileDialog.getExistingDirectory(self,'选择作品总目录',str(self.owner.output_files.root))
        if path: self.set_output_root(path)
    def set_output_root(self,path):
        if Path(path).resolve()==self.owner.data_root: return
        message=self.owner.migrate_data_root(path)
        self.refresh_storage_paths(); self.info('作品总目录已切换',message)
    def refresh_storage_paths(self):
        paths={'internal':self.owner.preferences.parent,'database':self.owner.workspace.root,'logs':self.owner.data_root/'logs','output':self.owner.output_files.root,**self.owner.output_files.paths()}
        for key,path in paths.items(): self.path_fields[key].setText(str(path))
    def configs(self):
        values={key:SimpleNamespace(provider=key,base_url=base.text().strip(),api_key=secret.text().strip(),model=model.model_value()) for key,(base,secret,model) in self.forms.items()}
        for key,(mode,tokens,structured,_) in self.output_controls.items():
            values[key].output_mode=mode.currentData(); values[key].max_output=tokens.value(); values[key].json_mode=structured.isChecked()
            values[key].format_mode=self.format_controls[key].currentData()
        values['codex_local']=SimpleNamespace(provider='codex_local',base_url='',api_key='',model=self.codex_model.text().strip()); return values
    def update_output_hint(self,key):
        from dataclasses import replace
        from app.core.output_budget import provider_output_cap,AUTO_LIMIT
        mode,tokens,_,note=self.output_controls[key]; tokens.setVisible(mode.currentData()=='manual')
        base,_,model=self.forms[key]; c=replace(self.c.channel_configs[key],base_url=base.text().strip(),model=model.model_value()); cap=provider_output_cap(c)
        capability=f'官方模型输出上限 {cap["tokens"]:,} token（核对于 {cap["reviewed"]}）。' if cap else '当前模型输出能力未核实，自动使用保守应用额度，并保留已声明上限；不会猜测更大能力。'
        note.setText(capability+f'自动模式按当前章节、段或修改范围估算，应用单次最多 {AUTO_LIMIT:,} token，并受上下文和费用预算限制。token不等于汉字数；思考也可能占用额度。手动值不会被自动改写。')
        if hasattr(self,'channel_save'): self.update_settings_actions(self.tabs.currentIndex())
    def resolve_legacy_limit(self,key,use_auto):
        c=self.c.channel_configs[key]
        if use_auto:
            mode,_,_,_=self.output_controls[key]; mode.setCurrentIndex(mode.findData('auto')); self.format_controls[key].setCurrentIndex(self.format_controls[key].findData('auto')); self.save_current_channel(key)
            if self.c.channel_configs[key].output_mode!='auto':return
        self.owner.options['legacy_test_128_ack:'+c.id]='auto' if use_auto else 'keep_manual'; self.owner.save_options(); self.legacy_controls[key][0].hide()
        self.info('选择已保存','推荐自动模式已保存；原手动值与凭据保留。' if use_auto else '保留手动输出设置，今后仍可在本页明确调整。')
    def set_sound_preference(self,enabled): self.owner.options['task_completion_sound']=bool(enabled); self.owner.save_options()
    def info(self,title,text): self.status.setText(title+'：'+text); self.owner.assistant.refresh_models()
    def error(self,title,text):
        from app.providers.contracts import redact
        self.status.setText(title+'：'+redact(text)); self.owner.statusBar().showMessage(title,10000)
    def update_all_key_statuses(self):
        for key,widget in self.key_status_labels.items(): widget.setText('已安全保存：••••••••' if self.c.model_key_status(key)['saved'] else '尚未保存')
        self.update_provider_tab_labels()
    def update_settings_actions(self,index):
        active=self.tabs.currentWidget() in {self.language_model_tab,self.codex_tab}; self.channel_save.setVisible(active); self.clear_keys_button.setVisible(active)
        key=self.current_provider(); current=bool(key and key==self.c.active_provider); dirty=bool(key and self.channel_form_is_dirty(key))
        self.channel_save.setText('请先保存修改' if dirty else '当前使用中' if current else '启用当前模型'); self.channel_save.setEnabled(bool(key) and not current and not dirty); self.channel_save.setProperty('activeProvider',current); self.channel_save.style().unpolish(self.channel_save); self.channel_save.style().polish(self.channel_save)
        if hasattr(self,'status_stack'): self.status_stack.setCurrentWidget(self.status_labels[self.status_key()]); self.status.sync_visibility()
    def load_models(self,key):
        value=self.configs()[key]
        def done(rows):
            rows=rows.get('models',[]) if isinstance(rows,dict) else rows; names=[str(r.get('id','')) if isinstance(r,dict) else str(r) for r in rows]; chosen=self.forms[key][2].model_value(); self.forms[key][2].set_catalog([(n,n) for n in names if n],chosen); self.model_status_labels[key].setText(f'已读取 {len(names)} 个模型；生成能力未验证'); self.status.setText(f'模型读取完成 · {len(names)}个模型')
        self.host.run_async('读取模型',lambda:self.c.list_models(value),done,on_failure=lambda message:self.error('模型读取失败，可继续手填',message))
    def test(self,key):
        value=self.configs()[key]
        self.owner.confirm_inline('这是小额文本测试，可能产生调用费用；不保存配置或切换默认模型。',lambda:self.host.run_async('测试连接',lambda:self.c.test_model_connection(value),lambda r:self.info('测试结果','连接成功' if r.status=='completed' else r.error or r.status)),parent=self)
    def delete_model_key(self,key): self.owner.confirm_inline('仅删除 TT创作助手 的'+MODEL_CHANNEL_LABELS[key]+'密钥，TT影序不受影响。',lambda:[self.c.delete_model_key(key),self.update_all_key_statuses()],parent=self)
    def clear_all_keys(self): self.owner.confirm_inline('仅清除 TT创作助手 密钥库中的全部文本和图片密钥；不清理 TT影序配置或密钥。',lambda:[self.c.clear_all_keys(),self.update_all_key_statuses(),self.update_openai_image_key_status()],parent=self)
    def start_codex_login_ui(self):
        def login():
            try:
                subprocess.Popen([*self.c.codex.command_prefix(),'login'],creationflags=subprocess.CREATE_NEW_CONSOLE)
                self.info('官方登录已打开','请在 Codex 官方窗口完成登录，然后点击重新检测。本软件不收集账号密码。')
            except Exception as error: self.error('登录启动失败',str(error))
        self.owner.confirm_inline('使用 Codex 官方登录流程，完成后重新检测。本软件不收集账号密码。',login,parent=self)
    def set_active_image_provider_ui(self,provider):
        try:
            if provider!='codex_image':
                value=self.values_image(); saved=self.c.openai_image_site(site_id(value['protocol'],value['baseUrl']))
                fields=['modelId','sizeStrategy','defaultSizeTier','manualSize','supportedRatios','quality','pricingEnabled','modelSettings']
                dirty=not saved or bool(self.openai_image_key.text()) or any(value.get(k)!=saved.get(k) for k in fields) or any(value['unitPrices'].get(k,0)!=saved.get('unitPrices',{}).get(k,0) for k in value['unitPrices'])
                if dirty: raise ValueError('当前网站存在未保存设置，请先保存设置，再设为当前图片渠道')
            self.c.set_active_image_provider(provider); self.update_active_image_provider_ui(); self.info('已启用','后续封面任务使用当前图片渠道')
        except Exception as e: self.error('启用失败',str(e))
    def update_active_image_provider_ui(self):
        active=self.c.image_provider_settings()['activeImageProvider']
        if hasattr(self,'codex_image_current'): self.codex_image_current.setText('当前渠道：'+('Codex Image' if active=='codex_image' else '未启用')); self.codex_image_set_current.setEnabled(bool(self._codex_image_ready) and active!='codex_image')
        if hasattr(self,'openai_image_provider_status'): self.openai_image_provider_status.setText('● 当前图片生成渠道' if active=='openai_compatible' else '○ 当前未启用')
    def current_general_image_provider_id(self): return 'openai_compatible'
    def values_image(self):
        ratios=[v for v,c in self.openai_image_ratio_checks.items() if c.isChecked()]; ratios+= [v.strip() for v in self.openai_image_extra_ratios.text().replace('，',',').split(',') if v.strip()]
        return dict(protocol=self.openai_image_protocol.currentData(),baseUrl=self.openai_image_base.text().strip().rstrip('/'),modelId=self.openai_image_model.model_value(),modelCatalog=[v for _,v in self.openai_image_model._catalog],sizeStrategy=self.openai_image_strategy.currentData(),defaultSizeTier=self.openai_image_tier.currentText(),manualSize=self.openai_image_manual_size.text().strip(),supportedRatios=ratios,quality=self.openai_image_quality.currentData() if self.openai_image_quality.currentData()=='model_default' else self.openai_image_quality.currentText(),pricingEnabled=self.openai_image_pricing_enabled.isChecked(),unitPrices={k:w.value() for k,w in self.openai_image_price_spins.items()},currency='CNY',pricingSource=self._openai_image_price_source,modelSettings=copy.deepcopy(self._openai_image_model_settings))
    def refresh_openai_image_sites_ui(self):
        selected=self.owner.options.get('settings_image_site'); w=self.openai_image_site_selector; w.blockSignals(True); w.clear(); w.addItem('选择已保存网站','')
        for v in self.c.list_openai_image_sites(): w.addItem(v['baseUrl']+' · '+v['modelId'],v['siteId'])
        w.setCurrentIndex(max(0,w.findData(selected))); w.blockSignals(False)
    def activate_openai_image_site_ui(self,index):
        sid=self.openai_image_site_selector.itemData(index)
        if not sid: return
        v=self.c.activate_openai_image_site(sid); self.loading_image=True
        try:
            self.openai_image_base.setText(v['baseUrl']); self.openai_image_key.clear(); self.openai_image_model.set_catalog([(n,n) for n in v.get('modelCatalog',[])],v['modelId']); self.openai_image_manual_size.setText(v.get('manualSize','')); self.openai_image_tier.setCurrentText(v.get('defaultSizeTier','1K')); self.openai_image_strategy.setCurrentIndex(max(0,self.openai_image_strategy.findData(v['sizeStrategy']))); self._set_openai_image_ratios(v.get('supportedRatios',[])); self._set_openai_image_quality_choices([],v.get('quality','model_default')); self._openai_image_model_settings=copy.deepcopy(v.get('modelSettings',{})); self.openai_image_pricing_enabled.setChecked(v.get('pricingEnabled',False)); self._openai_image_price_source=v.get('pricingSource','manual')
            for k,w in self.openai_image_price_spins.items(): w.setValue(v.get('unitPrices',{}).get(k,0))
        finally: self.loading_image=False
        self.update_openai_image_key_status(); self.update_active_image_provider_ui(); self.openai_image_connection_status.setText('已载入当前网站；生图能力尚未验证')
    def save_openai_image_ui(self):
        try: self.c.save_openai_image_settings(self.values_image(),self.openai_image_key.text()); self.openai_image_key.clear(); self.refresh_openai_image_sites_ui(); self.update_openai_image_key_status(); self.info('设置已保存','当前网站独立保存，未切换图片渠道')
        except Exception as e: self.error('保存失败',str(e))
    def save_openai_image_model_ui(self):
        model=self.openai_image_model.model_value(); self._openai_image_model_settings[model]=dict(sizeStrategy=self.openai_image_strategy.currentData(),defaultSizeTier=self.openai_image_tier.currentText(),manualSize=self.openai_image_manual_size.text(),quality=self.openai_image_quality.currentText(),unitPrices={k:w.value() for k,w in self.openai_image_price_spins.items()}); self.save_openai_image_ui()
    def check_openai_image_ui(self):
        try: self.c.check_openai_image_settings(self.values_image()); self.info('本地配置有效','参数按用户声明保存；不代表平台已支持或生图成功')
        except Exception as e: self.error('配置有误',str(e))
    def update_openai_image_key_status(self):
        v=self.c.openai_image_key_status(self.openai_image_protocol.currentData(),self.openai_image_base.text()); self.openai_image_key_status.setText('已安全保存' if v.get('saved') else '尚未保存')
    def update_openai_image_strategy_note(self):
        if hasattr(self,'openai_image_strategy_note'): self.openai_image_strategy_note.setText('画幅与像素由用户按平台文档配置；实际生图成功后按真实像素记录。')
    def invalidate_openai_image_connection(self,*args):
        if not self.loading_image and hasattr(self,'openai_image_connection_status'): self.openai_image_connection_status.setText('配置已变化，连接状态未验证')
    def openai_image_base_changed(self,*args):
        if self.loading_image or not hasattr(self,'openai_image_price_spins'): return
        self._openai_image_model_settings={}; self.openai_image_model.set_catalog([],''); self.openai_image_key.clear(); self.openai_image_pricing_enabled.setChecked(False)
        for w in self.openai_image_price_spins.values(): w.setValue(0)
        self.openai_image_price_status.setText('网站已变化；暂无法估算，请重新读取或填写价格'); self.update_openai_image_key_status()
    def openai_image_protocol_changed(self,*args): self.openai_image_base_changed()
    def openai_image_model_changed(self,*args):
        if self.loading_image or not hasattr(self,'openai_image_price_spins'): return
        model=self.openai_image_model.model_value(); value=self._openai_image_model_settings.get(model,{})
        self.openai_image_pricing_enabled.setChecked(False)
        for k,w in self.openai_image_price_spins.items(): w.setValue(value.get('unitPrices',{}).get(k,0))
        if value: self.openai_image_manual_size.setText(value.get('manualSize','')); self.openai_image_tier.setCurrentText(value.get('defaultSizeTier','1K'))
        self.openai_image_price_status.setText('模型已变化，暂无法估算；请核实该模型价格')
    def openai_image_size_strategy_changed(self,*args): self._render_openai_image_capability()
    def mark_openai_image_price_manual(self,*args):
        if not self.loading_image: self._openai_image_price_source='manual'
    def refresh_openai_image_models_ui(self):
        v=self.values_image(); key=self.openai_image_key.text()
        self.host.run_async('读取图片模型',lambda:self.c.list_openai_image_models(v,key),lambda rows:self.openai_image_model.set_catalog([(n,n) for n in rows],v['modelId']),on_failure=lambda message:self.error('读取模型失败，可手填',message))
    def test_openai_image_ui(self):
        v=self.values_image(); key=self.openai_image_key.text()
        self.host.run_async('检查图片连接',lambda:self.c.list_openai_image_models(v,key),lambda rows:self.info('接口可读取','模型列表读取成功；实际生图尚未验证'),on_failure=lambda message:self.error('连接检查失败',message))
    def read_openai_image_price_ui(self):
        v=self.values_image(); key=self.openai_image_key.text()
        def done(result):
            self.read_prices=result; ok=result.get('currency') in {'CNY','RMB'} and bool(result.get('unitPrices')); self.openai_image_apply_prices.setEnabled(ok); self.openai_image_price_status.setText('读取到人民币价格，请确认后应用' if ok else '暂无法估算：未返回可确认的人民币价格')
        self.host.run_async('读取费用',lambda:self.c.inspect_openai_image_model(v,key),done,on_failure=lambda message:self.error('费用读取失败，暂无法估算',message))
    def apply_openai_image_read_prices_ui(self):
        value=getattr(self,'read_prices',{});
        if value.get('currency') not in {'CNY','RMB'}: return
        for k,w in self.openai_image_price_spins.items(): w.setValue(value.get('unitPrices',{}).get(k,0))
        self._openai_image_price_source='provider_metadata'; self.openai_image_price_status.setText('已确认应用读取价格；保存设置后生效')
    def delete_openai_image_key_ui(self): self.owner.confirm_inline('仅删除 TT创作助手 当前网站保存的 Key。',lambda:[self.c.delete_openai_image_key(self.openai_image_protocol.currentData(),self.openai_image_base.text()),self.update_openai_image_key_status()],parent=self)
