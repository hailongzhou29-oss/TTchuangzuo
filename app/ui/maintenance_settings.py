from PySide6.QtWidgets import QCheckBox,QFormLayout,QLabel,QSpinBox,QVBoxLayout,QWidget

class BackupSettingsPage(QWidget):
    def __init__(self,owner):
        super().__init__()
        self.owner=owner
        layout=QVBoxLayout(self)
        old=owner.options.get('auto_backup',{})
        self.enabled=QCheckBox('启用当前打开项目的定时一致性备份')
        self.enabled.setChecked(old.get('enabled',False))
        self.interval,self.keep=QSpinBox(),QSpinBox()
        self.interval.setRange(1,120)
        self.interval.setValue(old.get('interval_minutes',10))
        self.keep.setRange(1,50)
        self.keep.setValue(old.get('keep',5))
        form=QFormLayout()
        form.addRow('间隔 / 分钟',self.interval)
        form.addRow('保留最近自动备份',self.keep)
        layout.addWidget(self.enabled)
        layout.addLayout(form)
        note=QLabel('后台使用一致性快照和登记素材。仅清理本项目 auto_ 自动备份；保留手动备份、正文和素材。未落盘内存稿不假报已备份。')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(owner.button('保存备份设置',self.save))
        layout.addWidget(owner.button('立即执行一致性备份',lambda:owner.start_automatic_backup(force=True)))
        layout.addWidget(owner.button('导出脱敏诊断（先预览）',owner.export_diagnostics))
        layout.addStretch()
    def save(self):
        self.owner.options['auto_backup']=dict(enabled=self.enabled.isChecked(),interval_minutes=self.interval.value(),keep=self.keep.value())
        self.owner.save_preferences()
        self.owner.configure_backup_timer()
        self.owner.status.setText('自动备份设置已保存，作用于当前打开的项目')
