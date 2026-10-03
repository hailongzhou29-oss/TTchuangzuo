from pathlib import Path
from PySide6.QtCore import Qt,QRectF,QThreadPool,QTimer
from PySide6.QtGui import QImage,QPainter,QFont,QFontMetrics,QColor,QPixmap
from PySide6.QtWidgets import QWidget,QFrame,QHBoxLayout,QVBoxLayout,QFormLayout,QComboBox,QLineEdit,QCheckBox,QTextEdit,QScrollArea
from app.core.cover import default_cover,validate_image,RATIOS
from app.core.files import atomic_write,digest,inside
from app.core.image_service import ImageService
from app.providers.contracts import CancelToken
from app.ui.image_worker import ImageWorker
from app.ui.v2_widgets import label,button,QComboBox
from app.ui.commercial_controls import TaskStatus

def story_outline(work):
    """Only an explicit outline, never prose excerpts or project memory."""
    import re
    plan=work.store.setting('v2_plan',{})
    if plan and not plan.get('source_stale'):
        outline='\n\n'.join(str(plan.get(key) or '').strip() for key in ('synopsis','outline_text')).strip()
        if outline: return outline
    if work.config.get('output')=='script':
        text=work.text
        if re.match(r'^\s*第一部分\s*[｜|:：].*(大纲|梗概)',text):
            return re.split(r'(?m)^\s*第二部分\s*[｜|:：]',text,maxsplit=1)[0].strip()
    for document in work.store.documents():
        if document['kind']=='outline': return work.store.document(document['id'])['text'].strip()
    return ''

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
        shell=QVBoxLayout(self); shell.setContentsMargins(0,0,0,0); shell.setSpacing(12); row=QHBoxLayout(); shell.addLayout(row,1); row.setContentsMargins(0,0,0,0); row.setSpacing(24); self.preview=label('封面预览\n\n选择画幅与风格，生成后在这里查看\n采用后更新作品卡片'); self.preview.setObjectName('coverPreview'); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.preview.setMinimumSize(260,300); row.addWidget(self.preview,1)
        options=QWidget(); options.setMaximumWidth(400); col=QVBoxLayout(options); self.options_layout=col; col.setContentsMargins(0,0,0,0); col.setSpacing(10); form=QFormLayout(); form.setSpacing(8); self.style=QComboBox(); self.style.addItems(['自动匹配','电影海报','插画书封','极简设计','摄影质感','水墨意境','漫画风格']); self.style.setEditable(True); form.addRow('封面风格',self.style)
        self.ratio=QComboBox(); self.ratio.addItems(['3:4','16:9','9:16','4:3','1:1','2:3']); form.addRow('比例',self.ratio); self.title=QLineEdit(self.store.metadata()['name']); form.addRow('标题',self.title)
        self.sync=QCheckBox('同步为作品名'); form.addRow('',self.sync); self.mode=QComboBox(); self.mode.addItems(['后期排字','模型生成文字','无文字']); form.addRow('文字方式',self.mode)
        self.connection=QComboBox(); self.connection.setMinimumContentsLength(10); self.connection.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.connection.addItem('选择图片渠道',None)
        for c in owner.image_connections.all():
            if c.enabled: self.connection.addItem(c.name,c.id)
        if connection: self.connection.setCurrentIndex(max(0,self.connection.findData(connection.id)))
        else: self.connection.setCurrentIndex(max(0,self.connection.findData(owner.options.get('default_image'))))
        form.addRow('生图渠道',self.connection); col.addLayout(form)
        self.outline=QTextEdit(); self.outline.setAcceptRichText(False); self.outline.setFixedHeight(96); self.outline.setPlaceholderText('补充故事大纲；不会自动发送完整正文'); self.outline.setPlainText(story_outline(work)); col.addWidget(label('故事大纲','fieldLabel')); col.addWidget(self.outline)
        self.prompt=QTextEdit(); self.prompt.setAcceptRichText(False); self.prompt_dirty=False; self._updating_prompt=False; self.prompt.textChanged.connect(self.prompt_edited); self.prompt.setFixedHeight(150); col.addWidget(label('封面提示词（可编辑）','fieldLabel')); col.addWidget(self.prompt); col.addWidget(button('按名称与大纲重新填入',self.confirm_refill,quiet=True))
        self.ratio_hint=label('请求画幅 · 实际像素生成后显示','muted'); col.addWidget(self.ratio_hint)
        self.status=TaskStatus(self); col.addWidget(self.status); self.generate_button=button('生成封面',lambda:owner.run(self.generate),True); col.addWidget(self.generate_button); self.adopt_button=button('采用封面',lambda:owner.run(self.adopt),True); self.adopt_button.hide(); col.addWidget(self.adopt_button); self.regenerate=button('重新生成',lambda:owner.run(self.generate)); self.regenerate.hide(); col.addWidget(self.regenerate)
        col.addStretch(); options_scroll=QScrollArea(); options_scroll.setWidgetResizable(True); options_scroll.setMinimumWidth(340); options_scroll.setMaximumWidth(420); options_scroll.setWidget(options); row.addWidget(options_scroll)
        footer=QFrame(); footer.setObjectName('creationFooter'); actions=QHBoxLayout(footer); actions.setContentsMargins(8,10,8,10); actions.setSpacing(8)
        for control in (self.status,self.generate_button,self.adopt_button,self.regenerate): col.removeWidget(control)
        actions.addWidget(self.status,1); actions.addWidget(button('渠道设置',self.open_settings,quiet=True)); actions.addWidget(self.regenerate); actions.addWidget(self.generate_button); actions.addWidget(self.adopt_button); shell.addWidget(footer)
        for w in (self.style,self.ratio,self.mode): w.currentTextChanged.connect(self.refresh_auto_prompt)
        self.title.textChanged.connect(self.refresh_auto_prompt); self.auto_prompt()
        self.outline.textChanged.connect(self.refresh_auto_prompt); self.ratio.currentTextChanged.connect(self.update_ratio_hint); self.update_ratio_hint()
        for w in (self.ratio,self.mode): w.currentTextChanged.connect(lambda _:self.render_candidate())
        self.title.textChanged.connect(lambda _:self.render_candidate())
        if self.connection.count()==1: self.generate_button.setEnabled(False); self.status.setText('先在设置中配置生图渠道')
        service=ImageService(self.store,self.owner.resources,self.owner.image_connections)
        history=service.history()
        if history and not status_callback:
            previous=service.get(history[0]['id']); result=previous.get('result') or {}
            if result.get('images'):
                self.service=service; self.snapshot=previous['snapshot']; self.restore_previous(); self.finished(previous['id'],result)
                if getattr(self,'restored_adopted',False): self.adopt_button.hide(); self.status.setText('已采用封面，提示词、画幅与图片已保存')
            elif previous.get('job_id') and previous['state'] in {'accepted','generating','uncertain'}:
                self.service=service; self.snapshot=previous['snapshot']; self.generate_button.setEnabled(False); self.status.setText('上次任务状态待确认，请先查询原任务'); col.insertWidget(0,button('查询原任务',lambda:self.owner.run(lambda:self.query(previous['id']))))
    def restore_previous(self):
        spec=dict(self.snapshot.get('cover_spec',{})); active=self.store.setting('active_cover'); saved=next((c['spec'] for c in self.store.covers() if c['id']==active),{})
        self.restored_adopted=saved.get('task_id')==self.snapshot.get('task_id')
        if self.restored_adopted: spec.update(saved)
        widgets=(self.ratio,self.mode,self.style,self.title,self.prompt,self.connection)
        for widget in widgets: widget.blockSignals(True)
        try:
            self.ratio.setCurrentText(spec.get('ratio','3:4')); self.mode.setCurrentText(spec.get('text_mode','后期排字')); self.style.setCurrentText(spec.get('style',self.style.currentText())); self.title.setText(spec.get('title',self.title.text())); self.prompt.setPlainText(self.snapshot['prompt']); self.prompt_dirty=True
            self.connection.setCurrentIndex(max(0,self.connection.findData(self.snapshot['model_selection']['id'])))
        finally:
            for widget in widgets: widget.blockSignals(False)
    def prompt_edited(self):
        if not self._updating_prompt: self.prompt_dirty=True
    def refresh_auto_prompt(self,*_):
        if not self.prompt_dirty: self.auto_prompt()
    def auto_prompt(self):
        evidence=self.outline.toPlainText().strip()
        settings=self.work.config; idea=settings.get('idea',''); genre=settings.get('genre',''); style=self.style.currentText()
        genre=next((row['label'] for row in self.owner.registry.of('genre') if row['id']==genre),'')
        text=('为《'+self.title.text()+'》设计一张作品封面。\n'+('题材：'+genre+'。\n' if genre else '')+'故事大纲：\n'+(evidence or '尚未提供，请补充故事大纲。')+'\n构图：选择大纲中的核心人物或关键物件，主体清晰，背景交代主要环境。\n情绪、光线与配色：根据大纲中的冲突与氛围匹配，保留明暗层次。\n视觉风格：'+(style if style!='自动匹配' else '与故事大纲匹配')+'。\n画幅：'+self.ratio.currentText()+'。')
        text+='\n'+('背景不出现文字、水印或字母。顶部18%留出标题区，关键面部远离标题区，底部10%留安全区。' if self.mode.currentText()=='后期排字' else '画面不含任何文字。' if self.mode.currentText()=='无文字' else '图中只出现精确中文标题：'+self.title.text())
        self._updating_prompt=True
        try: self.prompt.setPlainText(text); self.prompt_dirty=False
        finally: self._updating_prompt=False
    def confirm_refill(self):
        if self.prompt_dirty: self.owner.confirm_inline('重新填入会替换手动编辑的封面提示词。',self.auto_prompt,parent=self)
        else: self.auto_prompt()
    def update_ratio_hint(self,*_):
        pixels=(self.candidate or {}).get('width'); height=(self.candidate or {}).get('height'); self.ratio_hint.setText('请求画幅 '+self.ratio.currentText()+(' · 原图 '+str(pixels)+' × '+str(height) if pixels and height else ' · 实际像素生成后显示'))
    def open_settings(self): self.owner.close_cover_panel(self); self.owner.navigate(4)
    def generate(self):
        if not self.status_callback and not self.prompt_dirty and not self.outline.toPlainText().strip(): raise ValueError('请补充故事大纲或手动编写封面提示词')
        if self.worker:
            self.owner.stop_image(); return
        if self.owner.active_image_task: raise ValueError('有封面正在生成，请先停止或等待完成')
        if not self.fixed_connection and not self.connection.currentData(): raise ValueError('请先选择或启用图片渠道')
        c=self.fixed_connection or self.owner.image_connections.get(self.connection.currentData())
        spec=default_cover(self.title.text(),self.store.metadata()['kind']); spec.update(ratio=self.ratio.currentText(),include_local_text=False,text_mode=self.mode.currentText(),style=self.style.currentText())
        target_ratio=float(self.ratio.currentText().split(':')[0])/float(self.ratio.currentText().split(':')[1])
        def distance(size):
            if size=='auto': return 0
            a,b=map(int,size.split('x')); return abs(a/b-target_ratio)
        size=min(c.sizes,key=distance) if c.sizes else None
        service=ImageService(self.store,self.owner.resources,self.owner.image_connections); snapshot=service.prepare(c,self.prompt.toPlainText(),spec,size=size,count=1,development_test=bool(getattr(self.owner,'image_test_provider',None)))
        self.snapshot=snapshot; self.service=service; cancel=CancelToken(); worker=ImageWorker(service,snapshot['task_id'],cancel,snapshot=snapshot,provider=getattr(self.owner,'image_test_provider',None)); self.worker=worker; self.cancel=cancel
        self.owner.active_image_task=(self,worker,cancel); worker.signals.state.connect(self.state); worker.signals.finished.connect(self.finished); self.generate_button.setText('停止'); self.status.setText('正在生成图片…'); QThreadPool.globalInstance().start(worker)
        self.status.set_busy(True)
    def state(self,tid,state): self.status.setText({'downloading':'正在排版…','submitting':'正在生成图片…','generating':'正在生成图片…'}.get(state,'正在生成图片…'))
    def finished(self,tid,result):
        if self.owner.active_image_task and self.owner.active_image_task[0] is self: self.owner.active_image_task=None
        self.worker=None; self.generate_button.setText('生成封面')
        self.status.set_busy(False)
        self.owner.release_cover_panel(self)
        images=result.get('images',[])
        if self.snapshot and self.snapshot.get('model_selection',{}).get('provider')=='image_codex' and not getattr(self.owner,'image_test_provider',None):
            self.owner.record_codex_result(self.snapshot['model_selection'].get('cli_path',''),result)
        if result['status'] not in {'verified','partial'} or not images:
            self.status.setText('封面生成失败，作品内容不受影响；'+(result.get('error') or '；'.join(result.get('errors',[]))))
            if result['status'] in {'uncertain','accepted','generating'}:
                self.generate_button.setEnabled(False); self.status.setText('暂时无法确认任务状态，重新提交可能重复计费。请先查询原任务。')
                if self.service.get(tid).get('job_id'):
                    self.options_layout.insertWidget(0,button('查询原任务',lambda:self.owner.run(lambda:self.query(tid))))
            if self.status_callback: self.status_callback.setText(self.status.text())
            if self.owner.close_after_task and not self.owner.active_task: QTimer.singleShot(0,self.owner.close)
            return
        self.candidate=images[0]; source=inside(self.store.root,self.candidate['relative']); self.composed=cover_image(source,self.title.text(),self.ratio.currentText(),self.mode.currentText())
        self.preview.setPixmap(QPixmap.fromImage(self.composed).scaled(self.preview.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)); self.generate_button.hide(); self.adopt_button.show(); self.regenerate.show(); self.status.setText('封面候选已生成，采用后更新作品'+('；请检查模型生成的中文文字' if self.mode.currentText()=='模型生成文字' else ''))
        self.update_ratio_hint()
        if self.status_callback: self.status_callback.setText('测试成功')
        self.owner.play_task_sound()
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
        spec=default_cover(self.title.text(),self.store.metadata()['kind']); spec.update(ratio=self.ratio.currentText(),image=relative,include_local_text=False,text_mode=self.mode.currentText(),style=self.style.currentText())
        spec.update(prompt=(self.snapshot or {}).get('prompt',self.prompt.toPlainText()),task_id=(self.snapshot or {}).get('task_id'),source_asset=self.candidate.get('relative'),source_hash=self.candidate.get('sha256'),actual_pixels=[self.candidate.get('width'),self.candidate.get('height')],model=(self.snapshot or {}).get('model_selection',{}).get('model'),channel=(self.snapshot or {}).get('model_selection',{}).get('name'),created_at=__import__('app.storage.project',fromlist=['now']).now(),file_hash=digest(data))
        validate_image(inside(self.store.root,relative))
        try:
            from app.core.output_files import safe_name
            output=self.owner.output_files.write('图片',safe_name(self.title.text())+'_封面',data,'png',cover=True)
            spec['output_file']=str(output)
        except (OSError,ValueError) as exc: spec['output_error']=str(exc)
        cover_id=self.store.save_cover(spec); self.store.set_setting('active_cover',cover_id)
        if self.sync.isChecked(): self.store.update_project(name=self.title.text())
        self.status.setText('封面已更新'+('；作品图片输出失败，请检查高级设置目录' if spec.get('output_error') else '')); position=self.owner.home.scroll.verticalScrollBar().value(); self.owner.home.refresh(); QTimer.singleShot(0,self.owner,lambda:self.owner.home.scroll.verticalScrollBar().setValue(position)); self.owner.close_cover_panel(self)
