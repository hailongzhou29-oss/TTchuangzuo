from pathlib import Path
from PySide6.QtCore import Qt,QRectF,QThreadPool,QTimer
from PySide6.QtGui import QImage,QPainter,QFont,QFontMetrics,QColor,QPixmap
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QFormLayout,QComboBox,QLineEdit,QCheckBox,QTextEdit
from app.core.cover import default_cover,validate_image,RATIOS
from app.core.files import atomic_write,digest,inside
from app.core.image_service import ImageService
from app.providers.contracts import CancelToken
from app.ui.image_worker import ImageWorker
from app.ui.v2_widgets import label,button,QComboBox

def cover_image(source,title,ratio,text_mode):
    """Contain the decoded background; put type in its reserved area without cropping."""
    width,height=RATIOS[ratio]; image=QImage(width,height,QImage.Format.Format_ARGB32); image.fill(QColor('#1D2027'))
    painter=QPainter(image); painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform); painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    try:
        base=validate_image(source); scaled=base.scaled(width,height,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        painter.drawImage((width-scaled.width())//2,(height-scaled.height())//2,scaled)
        if text_mode=='后期排字':
            top=QRectF(width*.08,height*.02,width*.84,height*.18); font=QFont('Microsoft YaHei UI'); font.setBold(True)
            flags=Qt.AlignmentFlag.AlignCenter|Qt.TextFlag.TextWrapAnywhere
            size=round(width*.075)
            while size>=24:
                font.setPixelSize(size); metrics=QFontMetrics(font); needed=metrics.boundingRect(top.toRect(),int(flags),title)
                if needed.height()<=top.height() and needed.height()<=metrics.lineSpacing()*3: break
                size-=2
            if size<24: raise ValueError('标题过长，请缩短标题或改为无文字封面')
            painter.fillRect(QRectF(0,0,width,height*.23),QColor(15,17,22,170)); painter.setFont(font); painter.setPen(QColor('#FFFFFF')); painter.drawText(top,int(flags),title)
    finally: painter.end()
    return image

class CoverPanel(QWidget):
    def __init__(self,owner,work,connection=None,status_callback=None):
        super().__init__(); self.owner=owner; self.work=work; self.store=work.store; self.fixed_connection=connection; self.status_callback=status_callback; self.candidate=None; self.snapshot=None; self.worker=None
        row=QHBoxLayout(self); self.preview=label(''); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.preview.setMinimumSize(220,300); row.addWidget(self.preview,1)
        options=QWidget(); options.setMaximumWidth(400); col=QVBoxLayout(options); form=QFormLayout(); self.style=QComboBox(); self.style.addItems(['自动匹配','电影海报','插画书封','极简设计','摄影质感','水墨意境','漫画风格']); self.style.setEditable(True); form.addRow('封面风格',self.style)
        self.ratio=QComboBox(); self.ratio.addItems(['3:4','2:3','1:1','16:9']); form.addRow('比例',self.ratio); self.title=QLineEdit(self.store.metadata()['name']); form.addRow('标题',self.title)
        self.sync=QCheckBox('同步为作品名'); form.addRow('',self.sync); self.mode=QComboBox(); self.mode.addItems(['后期排字','模型生成文字','无文字']); form.addRow('文字方式',self.mode)
        self.connection=QComboBox(); self.connection.setMinimumContentsLength(10); self.connection.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        for c in owner.image_connections.all():
            if c.enabled: self.connection.addItem(c.name,c.id)
        if connection: self.connection.setCurrentIndex(max(0,self.connection.findData(connection.id)))
        else: self.connection.setCurrentIndex(max(0,self.connection.findData(owner.options.get('default_image'))))
        form.addRow('生图渠道',self.connection); col.addLayout(form)
        self.prompt=QTextEdit(); self.prompt.hide(); self.prompt.setMaximumHeight(200); col.addWidget(button('查看提示词',lambda:self.prompt.setVisible(not self.prompt.isVisible()),quiet=True)); col.addWidget(self.prompt)
        self.status=label('','muted'); col.addWidget(self.status); self.generate_button=button('生成封面',lambda:owner.run(self.generate),True); col.addWidget(self.generate_button); self.adopt_button=button('采用封面',lambda:owner.run(self.adopt),True); self.adopt_button.hide(); col.addWidget(self.adopt_button); self.regenerate=button('重新生成',lambda:owner.run(self.generate)); self.regenerate.hide(); col.addWidget(self.regenerate)
        col.addWidget(button('去设置',lambda:owner.navigate(4),quiet=True)); col.addStretch(); row.addWidget(options)
        for w in (self.style,self.ratio,self.mode): w.currentTextChanged.connect(self.auto_prompt)
        self.title.textChanged.connect(self.auto_prompt); self.auto_prompt()
        for w in (self.ratio,self.mode): w.currentTextChanged.connect(lambda _:self.render_candidate())
        self.title.textChanged.connect(lambda _:self.render_candidate())
        if not work.text.strip(): self.generate_button.setEnabled(False); self.status.setText('先生成或导入作品，再制作封面')
        elif self.connection.count()==0: self.generate_button.setEnabled(False); self.status.setText('先在设置中配置生图渠道')
        service=ImageService(self.store,self.owner.resources,self.owner.image_connections)
        history=service.history()
        if history and not status_callback:
            previous=service.get(history[0]['id']); result=previous.get('result') or {}
            if result.get('images'):
                self.service=service; self.snapshot=previous['snapshot']; self.finished(previous['id'],result)
            elif previous.get('job_id') and previous['state'] in {'accepted','generating','uncertain'}:
                self.service=service; self.snapshot=previous['snapshot']; self.generate_button.setEnabled(False); self.status.setText('上次任务状态待确认，请先查询原任务'); col.insertWidget(0,button('查询原任务',lambda:self.owner.run(lambda:self.query(previous['id']))))
    def auto_prompt(self):
        body=self.work.text
        # Current actual text is authoritative, even when an old outline is stale.
        evidence=body[:2400]
        rule=self.owner.registry.by_id['R09']['body']
        text=('只生成一张作品封面底图，不生成界面。\n'+rule+'\n作品标题：'+self.title.text()+'\n作品类型：'+self.store.metadata()['kind']+'\n当前作品依据：\n'+evidence+'\n封面风格：'+self.style.currentText()+'\n画幅：'+self.ratio.currentText())
        text+='\n'+('背景不出现文字、水印或字母。顶部18%留出标题区，关键面部远离标题区，底部10%留安全区。' if self.mode.currentText()=='后期排字' else '画面不含任何文字。' if self.mode.currentText()=='无文字' else '图中只出现精确中文标题：'+self.title.text())
        self.prompt.setPlainText(text)
    def generate(self):
        if self.worker:
            self.owner.stop_image(); return
        if self.owner.active_image_task: raise ValueError('有封面正在生成，请先停止或等待完成')
        c=self.fixed_connection or self.owner.image_connections.get(self.connection.currentData())
        spec=default_cover(self.title.text(),self.store.metadata()['kind']); spec.update(ratio=self.ratio.currentText(),include_local_text=False,text_mode=self.mode.currentText())
        target_ratio=float(self.ratio.currentText().split(':')[0])/float(self.ratio.currentText().split(':')[1])
        def distance(size):
            if size=='auto': return 0
            a,b=map(int,size.split('x')); return abs(a/b-target_ratio)
        size=min(c.sizes,key=distance) if c.sizes else None
        service=ImageService(self.store,self.owner.resources,self.owner.image_connections); snapshot=service.prepare(c,self.prompt.toPlainText(),spec,size=size,count=1)
        self.snapshot=snapshot; self.service=service; cancel=CancelToken(); worker=ImageWorker(service,snapshot['task_id'],cancel,snapshot=snapshot,provider=getattr(self.owner,'image_test_provider',None)); self.worker=worker; self.cancel=cancel
        self.owner.active_image_task=(self,worker,cancel); worker.signals.state.connect(self.state); worker.signals.finished.connect(self.finished); self.generate_button.setText('停止'); self.status.setText('正在生成图片…'); QThreadPool.globalInstance().start(worker)
    def state(self,tid,state): self.status.setText({'downloading':'正在排版…','submitting':'正在生成图片…','generating':'正在生成图片…'}.get(state,'正在生成图片…'))
    def finished(self,tid,result):
        if self.owner.active_image_task and self.owner.active_image_task[0] is self: self.owner.active_image_task=None
        self.worker=None; self.generate_button.setText('生成封面')
        images=result.get('images',[])
        if result['status'] not in {'verified','partial'} or not images:
            self.status.setText('封面生成失败，作品内容不受影响；'+(result.get('error') or '；'.join(result.get('errors',[]))))
            if result['status'] in {'uncertain','accepted','generating'}:
                self.generate_button.setEnabled(False); self.status.setText('暂时无法确认任务状态，重新提交可能重复计费。请先查询原任务。')
                if self.service.get(tid).get('job_id'):
                    self.layout().itemAt(1).widget().layout().insertWidget(0,button('查询原任务',lambda:self.owner.run(lambda:self.query(tid))))
            if self.status_callback: self.status_callback.setText(self.status.text())
            if self.owner.close_after_task and not self.owner.active_task: QTimer.singleShot(0,self.owner.close)
            return
        self.candidate=images[0]; source=inside(self.store.root,self.candidate['relative']); self.composed=cover_image(source,self.title.text(),self.ratio.currentText(),self.mode.currentText())
        self.preview.setPixmap(QPixmap.fromImage(self.composed).scaled(self.preview.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)); self.generate_button.hide(); self.adopt_button.show(); self.regenerate.show(); self.status.setText('封面候选已生成，采用后更新作品'+('；请检查模型生成的中文文字' if self.mode.currentText()=='模型生成文字' else ''))
        if self.status_callback: self.status_callback.setText('测试成功')
        if self.owner.close_after_task and not self.owner.active_task: QTimer.singleShot(0,self.owner.close)
    def render_candidate(self):
        if not self.candidate: return
        original_mode=(self.snapshot or {}).get('cover_spec',{}).get('text_mode','后期排字')
        if original_mode=='模型生成文字' and self.mode.currentText()!='模型生成文字' or original_mode!='模型生成文字' and self.mode.currentText()=='模型生成文字':
            self.adopt_button.setEnabled(False); self.status.setText('模型文字属于图片内容，请重新生成；无字底图支持直接调整后期排字'); return
        try:
            self.composed=cover_image(inside(self.store.root,self.candidate['relative']),self.title.text(),self.ratio.currentText(),self.mode.currentText()); self.adopt_button.setEnabled(True); self.preview.setPixmap(QPixmap.fromImage(self.composed).scaled(self.preview.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        except ValueError as exc: self.status.setText(str(exc)); self.adopt_button.setEnabled(False)
    def query(self,tid):
        cancel=CancelToken(); worker=ImageWorker(self.service,tid,cancel,operation='query',provider=getattr(self.owner,'image_test_provider',None)); self.worker=worker; self.owner.active_image_task=(self,worker,cancel); worker.signals.finished.connect(self.finished); QThreadPool.globalInstance().start(worker)
    def adopt(self):
        if not self.candidate: return
        from PySide6.QtCore import QBuffer,QIODevice
        buffer=QBuffer(); buffer.open(QIODevice.OpenModeFlag.WriteOnly); self.composed.save(buffer,'PNG'); data=bytes(buffer.data()); relative='assets/'+digest(data)+'.png'; atomic_write(inside(self.store.root,relative),data); self.store.register_asset(relative,digest(data),'image/png')
        spec=default_cover(self.title.text(),self.store.metadata()['kind']); spec.update(ratio=self.ratio.currentText(),image=relative,include_local_text=False)
        cover_id=self.store.save_cover(spec); self.store.set_setting('active_cover',cover_id)
        if self.sync.isChecked(): self.store.update_project(name=self.title.text())
        self.status.setText('封面已更新'); self.owner.home.refresh(); self.owner.close_inline()
