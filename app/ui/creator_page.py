"""Primary AI creation flow: choose a track, give a direction, generate and confirm."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox,QFormLayout,QHBoxLayout,QLabel,QLineEdit,QListWidget,QPushButton,
    QSpinBox,QSplitter,QTextBrowser,QVBoxLayout,QWidget)
from app.core.creator import tracks,select_track
from app.core.writing import WritingService
from app.core.knowledge import FactService
from app.core import stages

class CreatorPage(QWidget):
    def __init__(self,owner):
        super().__init__()
        self.owner=owner
        self.kind='小说'
        self.row=1
        layout=QVBoxLayout(self)
        self.heading=owner.label('AI 小说创作','heading')
        layout.addWidget(self.heading)
        layout.addWidget(owner.label('选择赛道，给一句方向；AI按规则完成方案、大纲和正文。','muted'))
        split=QSplitter()
        self.track_list=QListWidget()
        self.track_list.setObjectName('creatorTracks')
        self.track_list.setMinimumWidth(160)
        self.track_list.setMaximumWidth(260)
        self.track_list.currentRowChanged.connect(self.track_changed)
        split.addWidget(self.track_list)
        content=QWidget()
        form_layout=QVBoxLayout(content)
        form=QFormLayout()
        self.name=QLineEdit()
        self.name.setPlaceholderText('作品名称可选，AI方案确认后可修改')
        self.direction=QLineEdit()
        self.direction.setPlaceholderText('例如：一个普通人被卷入旧案；留空让AI构思')
        self.target=QSpinBox()
        self.target.setRange(15,20000)
        form.addRow('作品名称',self.name)
        form.addRow('创作方向',self.direction)
        model_row=QHBoxLayout()
        self.model_name=QLabel()
        model_row.addWidget(self.model_name,1)
        model_row.addWidget(owner.button('切换模型',self.choose_model))
        form.addRow('创作模型',model_row)
        self.target_label=QLabel('每章目标字数')
        form.addRow(self.target_label,self.target)
        form_layout.addLayout(form)
        self.core_rule=QTextBrowser()
        self.core_rule.setObjectName('creatorRuleText')
        self.core_rule.setMaximumHeight(210)
        form_layout.addWidget(owner.label('所选赛道规则','subheading'))
        form_layout.addWidget(self.core_rule)
        form_layout.addWidget(owner.label('AI创作','subheading'))
        actions=QHBoxLayout()
        for text,step in [('1 生成创作方案','idea_generate'),('2 生成大纲','outline_generate'),('3 生成正文','write')]:
            button=owner.button(text,lambda selected=step:self.generate(selected),step=='idea_generate')
            button.setProperty('creator_step',step)
            actions.addWidget(button)
        form_layout.addLayout(actions)
        self.progress=owner.label('先让AI生成方案；确认后继续大纲和正文。','muted')
        form_layout.addWidget(self.progress)
        self.result=QTextBrowser()
        self.result.setObjectName('creatorResult')
        self.result.setPlaceholderText('AI生成的内容会显示在这里。你不需要先手写正文。')
        form_layout.addWidget(self.result,1)
        result_actions=QHBoxLayout()
        self.confirm=owner.button('确认结果',self.confirm_result,True)
        self.confirm.setEnabled(False)
        result_actions.addWidget(self.confirm)
        result_actions.addWidget(owner.button('查看已生成正文',self.open_editor))
        result_actions.addWidget(owner.button('重新生成',self.regenerate))
        form_layout.addLayout(result_actions)
        split.addWidget(content)
        split.setStretchFactor(1,1)
        layout.addWidget(split,1)
        self.task=None
        self.set_channel(1)

    def set_channel(self,row):
        self.row=row
        self.kind={1:'小说',2:'剧本',3:'文案'}[row]
        self.heading.setText('AI '+self.kind+'创作')
        self.target_label.setText('当前集目标秒数' if self.kind=='剧本' else '每章目标字数' if self.kind=='小说' else '目标字数')
        self.target.setValue(60 if self.kind=='剧本' else 2000 if self.kind=='小说' else 800)
        self.rows=tracks(self.owner.resources,self.kind)
        self.track_list.blockSignals(True)
        self.track_list.clear()
        for track in self.rows:
            self.track_list.addItem(track['name'])
        self.track_list.blockSignals(False)
        selected=self.owner.store.setting('creation_constraints',{}).get('creator_track_id') if self.owner.store else None
        index=next((i for i,track in enumerate(self.rows) if track['id']==selected),0)
        self.track_list.setCurrentRow(index)
        self.track_changed(index)
        self.task=None
        self.confirm.setEnabled(False)
        self.result.clear()
        if self.owner.store and self.owner.store.metadata()['kind']==self.kind:
            self.name.setText(self.owner.store.metadata()['name'])
        else:
            self.name.clear()
        self.refresh_progress()
        self.model_name.setText(self.owner.model_combo.currentText() if hasattr(self.owner,'model_combo') else '在模型设置中接入文字模型')

    def choose_model(self):
        from PySide6.QtWidgets import QInputDialog
        rows=[c for c in self.owner.connections.all() if c.enabled and c.model]
        if not rows:
            self.owner.settings_dialog()
            return
        names=[c.name+' / '+c.model for c in rows]
        selected,ok=QInputDialog.getItem(self,'选择创作模型','模型',names,editable=False)
        if ok:
            item=rows[names.index(selected)]
            self.owner.model_combo.setCurrentIndex(self.owner.model_combo.findData(item.id))
            self.model_name.setText(selected)

    def track_changed(self,index):
        if index>=0:
            track=self.rows[index]
            self.core_rule.setPlainText(track['summary']+'\n\n'+track['body'])

    def ensure_project(self):
        owner=self.owner
        track=self.rows[self.track_list.currentRow()]
        if not owner.store or owner.store.metadata()['kind']!=self.kind or owner.store.setting('system_test_project',False):
            if not owner.save():
                raise ValueError('当前修改尚未保存，请先处理保存问题')
            store=owner.workspace.create(self.name.text().strip() or track['name']+'新作品',self.kind)
            owner.open_project(store.root,writing=False)
            owner.refresh_projects()
        select_track(owner.store,track)
        constraints=owner.store.setting('creation_constraints',{})
        constraints['topic']=self.direction.text().strip()
        constraints['target_duration' if self.kind=='剧本' else 'target_length']=self.target.value()
        owner.store.set_setting('creation_constraints',constraints)
        owner.pages.setCurrentWidget(self)
        return track

    def generate(self,step):
        owner=self.owner
        if owner.active_task:
            raise ValueError('AI正在创作，请等待完成或停止')
        track=self.ensure_project()
        plans=WritingService(owner.store).planning()
        wanted='idea_generate' if step=='outline_generate' else 'outline_generate'
        candidates=[plan for plan in plans if plan['kind']==wanted and plan['state']=='confirmed']
        selected=[candidates[0]['id']] if candidates else []
        if step!='idea_generate' and not selected:
            raise ValueError('请先确认AI生成的'+('创作方案' if step=='outline_generate' else '大纲')+'，无需手写')
        if step=='write':
            stage={'小说':'prose_generate','剧本':'screenplay_generate','文案':'copy_generate'}[self.kind]
            if self.kind=='剧本' and not FactService(owner.store).entities():
                raise ValueError('已确认方案还没有人物，请让AI重新生成包含人物的方案')
        else:
            stage=step
        direction=self.direction.text().strip() or '由AI按所选赛道原创构思具体人物、主题与冲突，不要求用户先写原稿。'
        instruction='按所选'+track['name']+'核心规则完成'+{'idea_generate':'原创创作方案','outline_generate':'大纲','prose_generate':'当前章正文','screenplay_generate':'当前集完整剧本','copy_generate':'完整文案'}[stage]+'。创作方向：'+direction
        if stage=='idea_generate':
            instruction+='方案应有具体故事、人物目标、阻力、转折、结局方向；characters返回name与description的主要人物列表。不要给用户填空表。'
        elif stage=='outline_generate':
            instruction+='基于已确认方案安排可执行节点，每个节点有具体事件、目的和前后依赖。'
        else:
            instruction+='使用已确认方案和大纲，直接输出完整作品内容，不输出给用户自行填空的提纲。目标'+str(self.target.value())+('秒，时长标为预计。' if self.kind=='剧本' else '字。')
        owner.start_text_task(stage_override=stage,instruction_override=instruction,planning_ids=selected)
        self.task=owner.last_task
        self.result.clear()
        self.confirm.setEnabled(False)
        self.progress.setText('AI正在按所选规则创作；结果完成后在这里确认。')

    def receive(self,service,task_id,result):
        if self.task is None or self.task[1]!=task_id:
            return
        task=service.get(task_id)
        if result['status']=='completed':
            self.result.setPlainText(stages.render(task['stage'],result['candidate'],WritingService(service.store).names()))
            self.confirm.setText('采用正文' if task['stage'] in stages.WRITING else '确认方案')
            self.confirm.setEnabled(True)
            self.progress.setText(('开发测试固定响应，未请求真实模型；' if result.get('development_test') else '')+'AI已生成，请确认结果后进入下一步。')
        else:
            self.result.setPlainText(result.get('text') or result.get('error') or '生成未完成')
            self.progress.setText('此次未完成，可检查提示；不会覆盖已确认内容。')

    def confirm_result(self):
        if not self.task:
            return
        service,task_id=self.task
        if self.owner.store.root!=service.store.root:
            raise ValueError('请先回到生成任务所属项目')
        task=service.get(task_id)
        if task['stage'] in stages.WRITING:
            did=service.adopt_work(task_id,new_document=True)
            self.owner.refresh_documents(did)
        else:
            service.adopt_plan(task_id)
        self.confirm.setEnabled(False)
        self.owner.review_candidate_button.setEnabled(False)
        self.refresh_progress()

    def refresh_progress(self):
        if not self.owner.store or self.owner.store.metadata()['kind']!=self.kind:
            self.progress.setText('先让AI生成方案；确认后继续大纲和正文。')
            return
        kinds={plan['kind'] for plan in WritingService(self.owner.store).planning()}
        self.progress.setText('大纲已确认，可生成正文。' if 'outline_generate' in kinds else '方案已确认，可生成大纲。' if 'idea_generate' in kinds else '先让AI生成方案；你不需要先手写内容。')

    def regenerate(self):
        if not self.task:
            self.generate('idea_generate')
        else:
            stage=self.task[0].get(self.task[1])['stage']
            self.generate('write' if stage in stages.WRITING else stage)

    def open_editor(self):
        if self.owner.store:
            self.owner.pages.setCurrentWidget(self.owner.writing)
