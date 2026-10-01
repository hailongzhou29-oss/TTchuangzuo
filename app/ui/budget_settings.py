from PySide6.QtWidgets import QCheckBox,QComboBox,QFormLayout,QInputDialog,QLabel,QLineEdit,QSpinBox,QVBoxLayout,QWidget

from app.core.budget import number


class BudgetSettingsPage(QWidget):
    def __init__(self,owner):
        super().__init__()
        self.owner=owner
        layout=QVBoxLayout(self)
        note=QLabel('作用范围：当前项目。金额基于用户价表与用量估算，不是服务账单保证；没有价表时只能限制调用数/输出。CLI套餐不能换算人民币。')
        note.setWordWrap(True)
        layout.addWidget(note)
        old=owner.store.setting('budget_settings',{}) if owner.store else {}
        form=QFormLayout()
        self.calls={}
        for label,default in [('节省',2),('均衡',4),('深入',8)]:
            spin=QSpinBox()
            spin.setRange(1,16)
            spin.setValue(old.get('call_limits',{}).get(label,default))
            self.calls[label]=spin
            form.addRow(label+'最多调用',spin)
        limits=old.get('monetary_limits',{})
        self.enabled=QCheckBox('启用当前项目金额估算与并发预留')
        self.enabled.setChecked(bool(limits))
        self.currency=QComboBox()
        self.currency.addItems(['CNY','USD','EUR','JPY'])
        self.currency.setCurrentText(limits.get('currency','CNY'))
        self.task_amount=QLineEdit(str(limits.get('task_amount','')))
        self.project_amount=QLineEdit(str(limits.get('project_amount','')))
        form.addRow('预算币种',self.currency)
        form.addRow('单次任务估算上限',self.task_amount)
        form.addRow('当前项目累计估算上限',self.project_amount)
        layout.addWidget(self.enabled)
        layout.addLayout(form)
        layout.addWidget(owner.button('保存项目预算',self.save))
        layout.addWidget(owner.button('查看预留与用量账本',self.show_book))
        layout.addWidget(owner.button('对照账单核对未确认预留',self.reconcile))
        layout.addWidget(owner.button('清理当前项目分析缓存',owner.clear_analysis_cache))
        layout.addStretch()

    def save(self):
        if not self.owner.store:
            raise ValueError('请先打开项目，预算不会无范围生效')
        limits={}
        if self.enabled.isChecked():
            limits['currency']=self.currency.currentText()
            for key,field in [('task_amount',self.task_amount),('project_amount',self.project_amount)]:
                if field.text().strip():
                    if number(field.text())<=0:
                        raise ValueError('金额上限须为正数')
                    limits[key]=str(number(field.text()))
            if len(limits)==1:
                raise ValueError('启用金额控制时至少填写一项上限')
        self.owner.store.set_setting('budget_settings',dict(call_limits={label:spin.value() for label,spin in self.calls.items()},monetary_limits=limits))
        self.owner.status.setText('预算设置已保存，下一任务生效；已有请求与账单不会撤销')

    def show_book(self):
        if not self.owner.store:
            raise ValueError('请先打开项目')
        from app.core.budget import BudgetBook
        import json
        rows=BudgetBook(self.owner.preferences.parent).rows(self.owner.store.metadata()['id'])
        self.owner.text_dialog('本地估算预留 · 未确认项保留上界',json.dumps(rows,ensure_ascii=False,indent=2))

    def reconcile(self):
        if not self.owner.store:
            raise ValueError('请先打开项目')
        from app.core.budget import BudgetBook
        book=BudgetBook(self.owner.preferences.parent)
        project_id=self.owner.store.metadata()['id']
        rows=[row for row in book.rows(project_id) if row['state'] in {'reserved','unconfirmed'}]
        if not rows:
            raise ValueError('当前项目没有待核对预留')
        labels=[row['id']+' · '+row['amount']+' '+row['currency'] for row in rows]
        selected,ok=QInputDialog.getItem(self,'选择待确认调用','核对不会撤销服务端账单',labels,editable=False)
        if not ok:return
        amount,ok=QInputDialog.getText(self,'核对金额','请输入已对照账单金额，币种保持原记录：')
        if not ok:return
        note,ok=QInputDialog.getText(self,'核对来源说明','记录账单日期/依据，不输入KEY：')
        if ok:
            book.reconcile(rows[labels.index(selected)]['id'],amount,note,project_id)
            self.owner.status.setText('预留已按用户账单核对记录，不自动声称服务回执已验证')
