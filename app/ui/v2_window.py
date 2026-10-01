"""V2 desktop: five pages, one work buffer, explicit versioned model operations."""
import json
import os
import re
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QThreadPool,QEvent,QLocale,QLibraryInfo,QTranslator,QSize
from PySide6.QtGui import QShortcut,QKeySequence,QTextCursor,QFont,QTextBlockFormat
from PySide6.QtWidgets import (QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFrame,QListWidget,QStackedWidget,QSplitter,QFileDialog,QTextBrowser,QTextEdit,QPlainTextEdit,QLineEdit,QComboBox,QMenu,QSpinBox,QDoubleSpinBox,QCheckBox,QApplication,QMessageBox)
from app.core.files import write_json,atomic_write,digest
from app.core.services import Workspace,import_preview
from app.core.selection import Registry,selection
from app.core.work_context import CurrentWork,intent,locate
from app.core.creation_flow import CreationFlow,parse_json,sync_dialogues
from app.storage.project import ProjectStore,ConflictError,LockedError,new_id
from app.storage.connections import ConnectionStore
from app.storage.image_connections import ImageConnectionStore
from app.ui.v2_widgets import label,button,style,PALETTES
from app.ui.creation_page import CreationPage
from app.ui.project_home import ProjectHome
from app.ui.assistant_panel import AssistantPanel
from app.ui.settings_page import SettingsPage
from app.ui.materials_panel import MaterialsPanel
from app.ui.cover_panel import CoverPanel
from app.ui.task_worker import TaskWorker
from app.providers.contracts import CancelToken,redact

APPLICATION_NAME='TT创作助手'
NAVIGATION=['首页','剧本','小说','仿写','设置']

def py_position(text,qt_position): return len(text.encode('utf-16-le')[:qt_position*2].decode('utf-16-le',errors='ignore'))
def qt_position(text,py_index): return len(text[:py_index].encode('utf-16-le'))//2

def install_chinese(app):
    QLocale.setDefault(QLocale(QLocale.Language.Chinese,QLocale.Country.China))
    translator=QTranslator(app)
    if translator.load('qtbase_zh_CN',QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)): app.installTranslator(translator)
    app._chinese_translator=translator

class MainWindow(QMainWindow):
    def __init__(self,workspace,resources,preferences):
        super().__init__(); self.workspace=workspace; self.resources=Path(resources); self.preferences=Path(preferences)
        self.options=json.loads(self.preferences.read_text(encoding='utf-8-sig')) if self.preferences.is_file() else {}
        configured=self.options.get('workspace_root')
        if configured and Path(configured).is_dir(): self.workspace=Workspace(Path(configured))
        self.registry=Registry(resources); self.connections=ConnectionStore(self.preferences.parent); self.image_connections=ImageConnectionStore(self.preferences.parent)
        # Only the known V1 connection-test profile used this 128-token limit.
        # Preserve endpoint, credential reference, model and capability records.
        from dataclasses import replace
        for c in self.connections.all():
            if c.id=='live_deepseek' and c.max_output==128 and c.timeout==60:
                backup=self.preferences.parent/'connections.before_v2.json'
                if not backup.exists(): atomic_write(backup,self.connections.path.read_bytes())
                self.connections.save(replace(c,max_output=8192,context_limit=max(c.context_limit,65536),timeout=300))
        self.work=None; self.works={}; self.loading=False; self.active_task=None; self.active_image_task=None; self.bound_selection=None; self.inline=None; self.inline_return=None; self.close_after_task=False; self.reading=False; self.backup_jobs=[]; self.segmented=None
        old_themes={'石墨深色':'石墨紫','雾白浅色':'清透白','暖纸写作':'暖纸色'}; self.theme=old_themes.get(self.options.get('theme'),self.options.get('theme','清透白'))
        if self.theme not in PALETTES: self.theme='清透白'
        available=self.screen().availableGeometry()
        self.setWindowTitle('TT创作助手 · 开发版'); self.setMinimumSize(min(1100,available.width()),min(720,available.height())); self.resize(min(1440,available.width()),min(900,available.height()))
        self.autosave=QTimer(self); self.autosave.setInterval(1000); self.autosave.setSingleShot(True); self.autosave.timeout.connect(lambda:self.run(self.save_work))
        self.task_poll=QTimer(self); self.task_poll.setInterval(50); self.task_poll.timeout.connect(self.poll_task)
        self.build_ui(); self.set_theme(self.theme); self.home.refresh(); self.navigate(0)
        install_chinese(QApplication.instance()); QApplication.instance().installEventFilter(self)
        if self.options.get('restore_last',True):
            last=self.options.get('last_project')
            if last and (Path(last)/'project.sqlite').is_file():
                import sqlite3
                try:
                    previous=ProjectStore(Path(last))
                    if previous.metadata()['status']=='active' and not previous.setting('system_test_project',False): self.run(lambda:self.open_project(Path(last)))
                except (OSError,ValueError,sqlite3.Error): self.statusBar().showMessage('上次作品暂时无法恢复，请从首页或备份打开',15000)
        screen=self.screen().availableGeometry(); self.resize(min(1440,screen.width()),min(900,screen.height()))
    def build_ui(self):
        root=QWidget(); layout=QHBoxLayout(root); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0); self.setCentralWidget(root)
        self.sidebar=QFrame(); self.sidebar.setObjectName('sidebar'); self.sidebar.setFixedWidth(168); left=QVBoxLayout(self.sidebar); left.setContentsMargins(12,0,12,16)
        brand=label(APPLICATION_NAME,'brand'); brand.setFixedHeight(64); left.addWidget(brand); self.navigation=QListWidget(); self.navigation.setIconSize(QSize(18,18)); self.navigation.addItems(NAVIGATION[:4])
        self.navigation.itemClicked.connect(lambda item:self.run(lambda:self.navigate(self.navigation.row(item))))
        self.navigation.itemActivated.connect(lambda item:self.run(lambda:self.navigate(self.navigation.row(item))))
        left.addWidget(self.navigation,1)
        self.materials_nav=button('资料与规则',lambda:self.run(self.open_materials_page),quiet=True); self.materials_nav.setCheckable(True); self.materials_nav.setObjectName('sidebarAction'); left.addWidget(self.materials_nav)
        self.settings_nav=button('设置',lambda:self.run(lambda:self.navigate(4)),quiet=True); self.settings_nav.setCheckable(True); self.settings_nav.setObjectName('sidebarAction'); left.addWidget(self.settings_nav); layout.addWidget(self.sidebar)
        self.splitter=QSplitter(); self.pages=QStackedWidget(); self.home=ProjectHome(self); self.pages.addWidget(self.home)
        self.creators={kind:CreationPage(self,kind) for kind in ('script','novel','rewrite')}
        for page in self.creators.values(): self.pages.addWidget(page)
        self.assistant=AssistantPanel(self); self.settings=SettingsPage(self); self.pages.addWidget(self.settings); self.splitter.addWidget(self.pages); self.splitter.addWidget(self.assistant); self.splitter.setStretchFactor(0,1); self.splitter.setSizes(self.options.get('splitter_sizes',[900,344])); self.splitter.splitterMoved.connect(self.save_layout); layout.addWidget(self.splitter,1)
        self.materials_page=QWidget(); materials_layout=QVBoxLayout(self.materials_page); materials_layout.setContentsMargins(24,20,24,20); self.pages.addWidget(self.materials_page)
        self.assistant_toggle=button('收起 AI 助手',self.toggle_assistant,quiet=True); self.statusBar().addPermanentWidget(self.assistant_toggle); self.statusBar().setVisible(True)
        QShortcut(QKeySequence('Ctrl+S'),self,activated=lambda:self.run(self.save_work)); QShortcut(QKeySequence('Ctrl+F'),self,activated=lambda:self.current_page().find_row.show() if isinstance(self.current_page(),CreationPage) else None); QShortcut(QKeySequence('Escape'),self,activated=self.escape)
        for page in self.creators.values():
            draft=self.options.get('draft:'+page.kind)
            page.load_config(draft or selection(page.kind))
    def current_page(self): return self.pages.currentWidget()
    def run(self,callback):
        try: return callback()
        except (ValueError,OSError,RuntimeError,KeyError,TypeError) as exc:
            text=redact(str(exc)); page=self.current_page()
            if isinstance(page,CreationPage): page.notify(text)
            else: self.statusBar().showMessage(text,15000)
            return None
    def save_options(self): write_json(self.preferences,self.options)
    def set_theme(self,name):
        self.theme=name; self.options['theme']=name; self.setStyleSheet(style(name,self.options.get('editor_font_size',17)))
        from app.ui.icons import icon
        color=PALETTES[name]['muted']
        for index,shape in enumerate(('folder','movie','book','arrows-exchange')): self.navigation.item(index).setIcon(icon(shape,color,18))
        self.settings_nav.setIcon(icon('settings',color,18)); self.settings_nav.setIconSize(QSize(18,18)); self.materials_nav.setIcon(icon('folder',color,18)); self.materials_nav.setIconSize(QSize(18,18)); self.save_options()
    def set_font(self,size): self.options['editor_font_size']=size; self.set_theme(self.theme)
    def save_layout(self,*_): self.options['splitter_sizes']=self.splitter.sizes(); self.save_options()
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'sidebar'): self.sidebar.setFixedWidth(136 if self.width()<1250 else 168)
    def navigate(self,index):
        if not hasattr(self,'pages') or index<0: return
        if self.inline: self.close_inline()
        self.save_work()
        self.bound_selection=None
        self.navigation.blockSignals(True); self.navigation.setCurrentRow(index if index<4 else -1); self.navigation.blockSignals(False)
        self.settings_nav.setChecked(index==4); self.materials_nav.setChecked(index==5)
        self.pages.setCurrentIndex(index); creative=1<=index<=3; self.assistant.setVisible(creative and not self.options.get('assistant_collapsed',False)); self.assistant_toggle.setVisible(creative)
        if creative:
            page=self.current_page(); self.work=self.works.get(page.kind)
            recent=self.options.get('recent:'+page.kind)
            if not self.work and recent and not getattr(self,'opening_blank',False) and (Path(recent)/'project.sqlite').exists():
                previous=ProjectStore(Path(recent))
                if previous.metadata()['status']=='active': self.open_project(Path(recent)); return
            if self.work: page.show_work(self.work); self.assistant.refresh()
            else: self.assistant.refresh()
        else:
            if index==0: self.home.refresh()
        self.assistant_toggle.setText('AI 助手' if not self.assistant.isVisible() else '收起 AI 助手')
    def toggle_assistant(self):
        self.options['assistant_collapsed']=self.assistant.isVisible(); self.assistant.setVisible(not self.assistant.isVisible()); self.assistant_toggle.setText('AI 助手' if not self.assistant.isVisible() else '收起 AI 助手'); self.save_options()
    def new_work(self,kind):
        self.save_work(); self.works[kind]=None; self.work=None; page=self.creators[kind]; page.load_config(selection(kind)); self.loading=True; page.editor.clear(); page.title.setText('未命名'+page.type_name()); page.location.clear(); page.chapters.clear(); self.loading=False; self.opening_blank=True
        try: self.navigate({'script':1,'novel':2,'rewrite':3}[kind])
        finally: self.opening_blank=False
    def save_page_draft(self,page):
        self.options['draft:'+page.kind]=page.config; self.save_options()
        work=self.works.get(page.kind)
        if work: work.config=page.config; work.store.set_setting('v2_selection',page.config)
    def ensure_work(self,page):
        work=self.works.get(page.kind)
        if work is None:
            config=page.read_config(); store=self.workspace.create(page.title.text().strip() or '未命名'+page.type_name(),page.type_name()); store.set_setting('v2_kind',page.kind); store.set_setting('v2_selection',config); store.set_setting('v2_user_rules',self.options.get('new_project_rules',[]))
            did=store.documents()[0]['id']; store.set_setting('v2_document:'+did,True); work=CurrentWork.load(store,did,config); self.works[page.kind]=work; self.work=work; page.refresh_documents(work); self.remember(work)
        self.work=work; work.config=page.read_config(); work.store.set_setting('v2_selection',work.config); return work
    def remember(self,work):
        self.options['last_project']=str(work.store.root); self.options['recent:'+work.config['kind']]=str(work.store.root); work.store.set_setting('v2_last_document',work.document_id); self.save_options()
    def open_project(self,root):
        self.save_work(); store=self.workspace.open(Path(root)); self.workspace.register(store)
        kind=store.setting('v2_kind',{'剧本':'script','小说':'novel','文案':'rewrite','仿写':'rewrite'}.get(store.metadata()['kind'],'novel'))
        config=store.setting('v2_selection')
        if config is None:
            config=selection(kind); legacy=store.setting('creation_constraints',{})
            config['idea']=legacy.get('topic',''); config['words']=legacy.get('target_length',config['words']) or config['words']
            duration=legacy.get('target_duration')
            if isinstance(duration,int) and 10<=duration<=10800:
                config.update(duration=duration,duration_label={30:'30秒',60:'60秒',90:'90秒',120:'2分钟',180:'3分钟',300:'5分钟',600:'10分钟'}.get(duration,'自定义'),minutes=duration//60,seconds=duration%60)
            genre=legacy.get('primary_genre','')
            config['genre']=next((r['id'] for r in self.registry.of('genre') if r['label'] in genre), 'auto')
            references=[]
            for ref_id in store.setting('pinned_documents',[]):
                ref=store.document(ref_id)
                if not ref['deleted']: references.append(dict(id=ref_id,title=ref['title'],text=ref['text'],scope='整部作品',enabled=True,source_type='旧项目已绑定参考',source_revision=ref['head']))
            store.set_setting('v2_references',references); store.set_setting('v2_selection',config); store.set_setting('v2_kind',kind)
        config=dict(selection(kind),**config)
        from app.core.tasks import TaskService
        TaskService(store,self.resources,self.connections).recover_unfinished()
        did=store.setting('v2_last_document'); docs=[d for d in store.documents() if d['kind']!='reference']
        if not docs: did=store.add_document('正文',kind=store.metadata()['kind'])
        elif did not in {d['id'] for d in docs}: did=docs[0]['id']
        store.set_setting('v2_document:'+did,True)
        work=CurrentWork.load(store,did,config); self.works[kind]=work; self.work=work; self.remember(work)
        # Recover received temporary work without ever declaring an interrupted call complete.
        draft=store.setting('v2_generation_draft')
        if draft and draft.get('document_id')==did:
            work.text=draft.get('text') or work.text; work.dirty=bool(draft.get('text')); work.draft=True
        self.navigate({'script':1,'novel':2,'rewrite':3}[kind]); self.assistant.refresh()
        if work.draft: self.creators[kind].notify('上次生成未完成，已恢复草稿；可保留草稿或重新生成')
    def select_document(self,did):
        if not self.work or self.work.document_id==did: return
        self.save_work(); work=CurrentWork.load(self.work.store,did,self.work.config); work.store.set_setting('v2_document:'+did,True); self.work=work; self.works[work.config['kind']]=work; self.remember(work); self.current_page().show_work(work); self.assistant.refresh()
        if work.store.setting('v2_stale:'+did,False): self.current_page().notify('前文已修改，续写前将检查关联')
    def save_work(self):
        if self.work:
            page=self.creators[self.work.config['kind']]
            previous_revision=self.work.revision
            try:
                if self.work.dirty and '第二部分｜完整剧本' in self.work.text:
                    original=self.work.store.document(self.work.document_id)['text']
                    from app.core.creation_flow import script_body
                    if script_body(original)!=script_body(self.work.text):
                        synced=sync_dialogues(self.work.text)
                        if synced!=self.work.text:
                            self.work.edit(synced)
                            if self.current_page() is page: self.replace_editor(page,synced)
                    elif original.split('第三部分｜完整人物台词')[-1]!=self.work.text.split('第三部分｜完整人物台词')[-1]:
                        page.notify('这句台词的对应位置需要确认，请在第二部分修改对白；第三部分将同步提取')
                self.work.save(); page.saved.setText('已保存')
                if self.work.revision!=previous_revision: self.automatic_backup(self.work)
            except OSError:
                page.saved.setText('保存失败'); page.notify('保存失败，请检查磁盘空间或目录权限')
                if not hasattr(page,'rescue'): page.rescue=button('另存作品',lambda:self.run(self.rescue_text)); page.layout().insertWidget(0,page.rescue)
                page.rescue.show(); raise
            if self.current_page() is page:
                cursor=page.editor.textCursor(); self.work.store.set_setting('v2_location:'+self.work.document_id,dict(cursor=py_position(self.work.text,cursor.position()),scroll=page.editor.verticalScrollBar().value()))
            self.work.store.set_setting('v2_selection',self.work.config)
    def editor_changed(self,page):
        work=self.works.get(page.kind)
        if work is None and page.editor.toPlainText().strip(): work=self.ensure_work(page)
        if not work: return
        text=page.editor.toPlainText(); work.edit(text)
        if '第二部分｜完整剧本' in text: page.notify('人物台词将在保存时同步；有歧义时需要确认')
        if self.active_task and self.active_task['work'] is work: self.active_task['manual']=True
        page.saved.setText('保存中…')
        if self.options.get('autosave',True): self.autosave.start()
    def selection_range(self,page):
        if self.bound_selection: return self.bound_selection
        c=page.editor.textCursor(); text=page.editor.toPlainText(); return py_position(text,c.selectionStart()),py_position(text,c.selectionEnd())
    def generate(self,page,confirmed=False):
        if self.active_task:
            if self.active_task['page'] is page: self.stop_task(); return
            raise ValueError('有内容正在生成，未重复提交')
        connection=self.assistant.connection(); config=page.read_config(); self.registry.effective(config)
        work=self.ensure_work(page)
        if work.text.strip() and not confirmed: page.confirm_bar.show(); return
        import math
        count=math.ceil(config['duration']/300) if config['output']=='script' and config['duration']>300 else math.ceil(config['words']/3500) if config['output']=='novel' and config['length']!='长篇连载' and config['words']>5000 else 1
        self.segmented=dict(work=work,page=page,connection=connection,index=0,count=count,instruction=config.get('idea','')) if count>1 else None
        page.confirm_bar.hide(); self.start_task(page,work,connection,'generate',config.get('idea',''))
        if page.kind=='rewrite' and page.reference.isVisible(): page.fold_reference()
    def chat_request(self,instruction):
        page=self.current_page()
        if not isinstance(page,CreationPage): return
        connection=self.assistant.connection(); work=self.ensure_work(page); task=intent(instruction)
        work.edit(page.editor.toPlainText())
        target_chapter=re.search(r'第([\d一二三四五六七八九十]+)章',instruction)
        if target_chapter and task in {'modify','inspect'} and work.config['output']=='novel':
            value=target_chapter[1]; number=int(value) if value.isdigit() else {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}.get(value,0)
            chapters=[d for d in work.store.documents() if d['kind']!='reference']
            if not 1<=number<=len(chapters): raise ValueError('没有找到指定章节，请先选择要修改的章节')
            self.select_document(chapters[number-1]['id']); work=self.work
        if not work.text.strip() and any(v in instruction for v in ('帮我写','生成','创作一','写一','写个')): task='generate'
        if task=='next': self.next_chapter(instruction); return
        selected=locate(work.text,instruction,self.selection_range(page)) if task=='modify' else (0,0)
        if task=='modify' and not work.text.strip(): raise ValueError('先生成或导入作品，再修改正文')
        self.start_task(page,work,connection,task,instruction,selected); self.loading=True; self.assistant.input.clear(); self.loading=False; work.store.set_setting('v2_chat_input','')
    def start_task(self,page,work,connection,task,instruction,selected=(0,0)):
        if getattr(self,'migrating',False): raise ValueError('正在迁移项目，完成后可继续生成')
        if self.active_task: raise ValueError('有内容正在生成，未重复提交')
        if task=='generate' and self.options.get('pending_batch'): raise ValueError('连续生成正在进行')
        work.store.set_setting('v2_call_limit',self.options.get('call_limit',4))
        segment=None
        if self.segmented and self.segmented['work'] is work:
            state=self.segmented; segment=dict(index=state['index'],count=state['count'],words=round(work.config['words']/state['count']),duration=round(work.config['duration']/state['count']))
        flow=CreationFlow(work,self.resources,self.connections); snapshot=flow.prepare(connection,task,instruction,selected,development_test=bool(getattr(self,'text_test_provider',None)),segment=segment)
        if task in {'generate','next'}: work.store.set_setting('v2_material_draft',False)
        cancel=CancelToken(); worker=TaskWorker(flow.service,snapshot,cancel,getattr(self,'text_test_provider',None))
        self.active_task=dict(flow=flow,snapshot=snapshot,worker=worker,cancel=cancel,page=page,work=work,manual=False,partial='',preview=False)
        worker.signals.text.connect(self.stream_text); QThreadPool.globalInstance().start(worker); self.task_poll.start(); page.generate_button.setText('停止生成'); page.notify('正在构思…' if task in {'generate','next'} else '正在处理…'); self.assistant.send_button.setText('■'); self.assistant.send_button.setToolTip('停止'); self.bound_selection=None; self.assistant.scope.hide()
    def stream_text(self,tid,text):
        active=self.active_task
        if not active or active['snapshot']['task_id']!=tid: return
        active['partial']+=text; task=active['snapshot']['v2_task']; page=active['page']; work=active['work']
        if task in {'generate','next'} and not active['manual']:
            # JSON string chunks are decoded before being exposed as a readable draft.
            matches=re.findall(r'"(?:text|outline|chapter_title)"\s*:\s*("(?:[^"\\]|\\.)*")',active['partial'])
            chunks=[]
            for raw in matches:
                try: chunks.append(json.loads(raw))
                except ValueError: pass
            draft='\n\n'.join(chunks)
            if draft:
                work.text=draft; work.dirty=False; work.draft=True; active['preview']=True
                work.store.set_setting('v2_generation_draft',dict(document_id=work.document_id,text=draft,request_id=tid))
                if self.work is work and self.current_page() is page: self.loading=True; page.editor.setPlainText(draft); self.loading=False
        page.notify('正在写作…' if task in {'generate','next'} else '正在处理…')
    def poll_task(self):
        active=self.active_task
        if active and active['worker'].completed.is_set(): self.finish_task(active,active['worker'].result)
    def finish_task(self,active,result):
        self.active_task=None; self.task_poll.stop(); page=active['page']; work=active['work']; snapshot=active['snapshot']; page.generate_button.setEnabled(True); page.generate_button.setText(page.generate_text()); self.assistant.send_button.setText('➤'); self.assistant.send_button.setToolTip('发送')
        if active['preview'] and not active['manual']:
            # Preview belongs to this request; restore its base only for the checked commit.
            if result['status']=='completed': work.text=snapshot['frozen']['text']; work.dirty=False
            else: work.dirty=True; work.draft=True
        try:
            if result['status']=='completed':
                segment=snapshot['constraints'].get('_segment')
                if segment and segment['index']>0:
                    from app.core.creation_flow import parse_output
                    prior=work.store.setting('v2_payload:'+work.document_id,{}).get('payload',{})
                    if work.config['output']=='script':
                        value=result['candidate']; merged=dict(title=prior.get('title',value['title']),outline=prior.get('outline',value['outline']),scenes=prior.get('scenes',[])+value['scenes'])
                        result['candidate']=parse_output(json.dumps(merged,ensure_ascii=False),'generate',work.config)
                    else:
                        result['candidate']['text']=snapshot['frozen']['text']+'\n\n'+result['candidate'].get('raw_text',result['candidate']['text'])
                old_plan=work.store.setting('v2_plan',{}); before=work.text; notice=active['flow'].apply(snapshot,result); after=work.text
                if snapshot['v2_task'] in {'inspect','discuss'}:
                    if self.work is work: self.assistant.append('助手',notice); page.notify('检查完成' if snapshot['v2_task']=='inspect' else '已回复')
                    else: self.statusBar().showMessage('《'+work.store.metadata()['name']+'》已完成回复',10000)
                else:
                    work.store.set_setting('v2_generation_draft',None); undos=work.store.setting('v2_undo',{}); undos[snapshot['task_id']]=dict(document_id=work.document_id,before=before,after_hash=digest(after)); work.store.set_setting('v2_undo',undos)
                    if snapshot['v2_task']=='planning':
                        undos[snapshot['task_id']].update(plan_before=old_plan,plan_after_hash=digest(json.dumps(work.store.setting('v2_plan'),ensure_ascii=False,sort_keys=True))); work.store.set_setting('v2_undo',undos)
                    self.automatic_backup(work)
                    if self.work is work and self.current_page() is page:
                        if after!=before: self.replace_editor(page,after)
                        page.title.setText(work.store.metadata()['name']); page.refresh_documents(work); self.assistant.append('助手',notice,undo=snapshot['task_id'])
                    else: self.statusBar().showMessage('《'+work.store.metadata()['name']+'》已完成修改',12000)
                    page.notify(notice); work.store.set_setting('v2_stale:'+work.document_id,False)
            else:
                page.notify('已停止，已生成内容已保留为草稿' if result['status']=='cancelled' else '内容尚未完成，已保留草稿；'+(result.get('error') or result['status']))
                if active['preview'] and not active['manual']: work.save('未完成草稿')
                elif not active['preview'] and not active['manual'] and self.work is work: self.replace_editor(page,work.text)
                if self.work is work: self.assistant.append('助手',page.banner.text())
        except (ValueError,RuntimeError,OSError,KeyError,TypeError) as exc:
            if self.work is work: page.notify(redact(str(exc))); self.assistant.append('助手',redact(str(exc)))
            else: self.statusBar().showMessage('《'+work.store.metadata()['name']+'》修改未应用，请回到该作品查看',10000)
            result['status']='application_failed'
        self.home.refresh()
        if self.close_after_task and not self.active_image_task: QTimer.singleShot(0,self.close)
        if self.segmented and self.segmented['work'] is work:
            state=self.segmented
            if result['status']=='completed' and self.work is work and self.current_page() is page and state['index']+1<state['count']:
                state['index']+=1; work.draft=True; page.notify(f'已保存第{state["index"]}段，继续创作；共{state["count"]}次请求，费用按服务商实际计费')
                QTimer.singleShot(0,lambda:self.run(lambda:self.start_task(page,work,state['connection'],'generate',state['instruction']+' 接续当前作品，生成下一段。')))
            else: self.segmented=None
        if result['status']!='completed' or self.current_page() is not page: self.options['batch_remaining']=0
        if self.options.get('batch_remaining') and result['status']=='completed': QTimer.singleShot(0,lambda:self.run(self.continue_batch))
    def replace_editor(self,page,text):
        self.loading=True
        cursor=page.editor.textCursor(); cursor.beginEditBlock(); cursor.select(QTextCursor.SelectionType.Document); cursor.insertText(text)
        fmt=QTextBlockFormat(); fmt.setLineHeight(170,QTextBlockFormat.LineHeightTypes.ProportionalHeight.value); cursor.select(QTextCursor.SelectionType.Document); cursor.mergeBlockFormat(fmt)
        cursor.endEditBlock()
        self.loading=False
    def automatic_backup(self,work):
        from app.ui.model_settings import Operation
        retention=self.options.get('backup_retention',10); store=work.store; revision=work.revision
        def backup():
            folder=(store.root/'backups').resolve(); folder.mkdir(exist_ok=True)
            store.backup_database(folder/('v2_auto_'+revision+'.sqlite'))
            files=sorted(folder.glob('v2_auto_*.sqlite'),key=lambda p:p.stat().st_mtime,reverse=True)
            for item in files[retention:]:
                if item.resolve().parent==folder and item.is_file(): item.unlink()
        op=Operation(backup); self.backup_jobs=[j for j in self.backup_jobs if not j.completed.is_set()]+[op]; QThreadPool.globalInstance().start(op)
    def rescue_text(self):
        if not self.work: return
        path,_=QFileDialog.getSaveFileName(self,'另存作品','恢复草稿.md','正文 (*.md)')
        if path: atomic_write(Path(path),self.work.text.encode('utf-8')); self.statusBar().showMessage('内存草稿已另存',10000)
    def stop_task(self):
        if self.active_task:
            self.segmented=None; self.options['batch_remaining']=0
            self.active_task['cancel'].cancel(); self.active_task['page'].notify('正在停止；本地停止接收后，远端可能继续计费'); self.active_task['page'].generate_button.setEnabled(False)
            QTimer.singleShot(250,lambda:self.active_task['page'].generate_button.setEnabled(True) if self.active_task else [p.generate_button.setEnabled(True) for p in self.creators.values()])
    def stop_image(self):
        if self.active_image_task: self.active_image_task[2].cancel()
    def undo_ai(self,tid):
        if not self.work: return
        work=self.work; record=work.store.setting('v2_undo',{}).get(tid)
        if not record or record['document_id']!=work.document_id: raise ValueError('先打开这次修改所属的正文')
        if 'plan_before' in record:
            if digest(json.dumps(work.store.setting('v2_plan'),ensure_ascii=False,sort_keys=True))!=record['plan_after_hash']: raise ConflictError('故事规划又发生了变化，请选择要保留的内容')
            work.store.set_setting('v2_plan',record['plan_before']); self.assistant.append('助手','已撤销这次规划修改'); return
        if digest(work.text)!=record['after_hash']: raise ConflictError('正文在处理期间发生了变化，请选择要保留的内容')
        work.edit(record['before']); work.save('撤销AI修改'); self.replace_editor(self.creators[work.config['kind']],work.text); self.assistant.append('助手','已撤销这次修改')
    def next_chapter(self,instruction='续写下一章'):
        if not self.work or self.work.config['output']!='novel': raise ValueError('先生成小说正文，再续写下一章')
        if self.active_task: raise ValueError('有内容正在生成，未重复提交')
        connection=self.assistant.connection(); self.save_work(); old=self.work; docs=[d for d in old.store.documents() if d['kind']!='reference']; current_index=next(i for i,d in enumerate(docs) if d['id']==old.document_id)
        if current_index+1<len(docs):
            did=docs[current_index+1]['id']
            if old.store.document(did)['text'].strip(): raise ValueError('下一章已有正文，请打开该章修改或从最后一章续写')
        else: did=old.store.add_document('第'+str(current_index+2)+'章',kind='小说')
        previous=dict(document_id=old.document_id,revision=old.revision,text=old.text)
        self.select_document(did); work=self.work; work.store.set_setting('v2_previous_chapter',previous)
        self.start_task(self.current_page(),work,connection,'next',instruction+'。上一章当前结尾：\n'+previous['text'][-3000:])
    def show_inline(self,title,content,return_widget=None):
        if self.inline: self.close_inline()
        self.inline_return=return_widget or self.current_page(); panel=QWidget(); col=QVBoxLayout(panel); col.setContentsMargins(24,20,24,20); head=QHBoxLayout(); head.addWidget(button('返回首页' if self.inline_return is self.home else '返回作品',self.close_inline,quiet=True)); head.addWidget(label(title,'heading'),1); col.addLayout(head); col.addWidget(content,1); self.inline=panel; self.pages.addWidget(panel); self.pages.setCurrentWidget(panel); self.assistant.hide(); self.assistant_toggle.hide(); return panel
    def close_inline(self):
        if not self.inline: return
        panel=self.inline; self.inline=None; target=self.inline_return; self.pages.setCurrentWidget(target); self.pages.removeWidget(panel); panel.hide()
        if self.active_image_task and self.active_image_task[0].parent() is panel:
            if not hasattr(self,'retired_panels'): self.retired_panels=[]
            self.retired_panels.append(panel)
        else: panel.deleteLater()
        creative=isinstance(target,CreationPage); self.assistant.setVisible(creative and not self.options.get('assistant_collapsed',False)); self.assistant_toggle.setVisible(creative)
    def confirm_inline(self,text,callback,parent=None):
        parent=parent or self.current_page(); bar=QWidget(); row=QHBoxLayout(bar); row.addWidget(label(text),1)
        def yes(): self.run(callback); bar.deleteLater()
        row.addWidget(button('确认',yes,True)); row.addWidget(button('取消',bar.deleteLater)); parent.layout().insertWidget(0,bar)
    def offer_undo(self,text,callback):
        self.statusBar().showMessage(text,10000); action=button('撤销',lambda:self.run(callback),quiet=True); self.statusBar().addWidget(action); QTimer.singleShot(10000,action.deleteLater)
    def open_materials_page(self):
        page=self.current_page() if isinstance(self.current_page(),CreationPage) else self.creators[self.work.config['kind']] if self.work else self.creators.get(getattr(self,'last_creator_kind','script'))
        self.show_materials(page)
    def show_materials(self,page):
        work=self.ensure_work(page)
        if not work.text.strip(): work.store.set_setting('v2_material_draft',True)
        layout=self.materials_page.layout()
        while layout.count():
            previous=layout.takeAt(0).widget()
            if previous: previous.hide(); previous.deleteLater()
        panel=MaterialsPanel(self,page,standalone=True); layout.addWidget(panel); self.navigate(5)
    def open_cover(self):
        self.save_work()
        if not self.work: raise ValueError('先生成或导入作品，再制作封面')
        self.show_inline('作品封面',CoverPanel(self,self.work))
    def open_home_cover(self,root):
        self.open_project(Path(root)); self.open_cover(); self.inline_return=self.home
    def export_home(self,root): self.open_project(Path(root)); self.export_work('md')
    def test_image_connection(self,connection,status):
        # Explicit test button uses its own archived test project, never a user's story.
        store=self.workspace.create('图片连接测试','剧本'); store.set_setting('system_test_project',True); store.update_project(status='archived'); did=store.documents()[0]['id']; work=CurrentWork.load(store,did,selection('script')); work.edit('清晨窗边的一本书，暖色光线，无文字。'); work.save('测试素材'); panel=CoverPanel(self,work,connection,status); self.show_inline('生图连接测试',panel); panel.mode.setCurrentText('无文字'); panel.generate()
    def show_versions(self):
        if not self.work: return
        store=self.work.store; did=self.work.document_id; pane=QWidget(); col=QVBoxLayout(pane); listing=QListWidget(); preview=QTextBrowser(); rows=store.revisions(did)
        for row in rows: listing.addItem(row['created']+' · '+row['reason'])
        col.addWidget(listing); col.addWidget(preview,1); listing.currentRowChanged.connect(lambda i:preview.setPlainText(rows[i]['text']) if i>=0 else None)
        def restore():
            if listing.currentRow()<0: return
            self.work.save(); self.work.revision=store.restore_revision(did,rows[listing.currentRow()]['id'],self.work.revision); self.work.text=store.document(did)['text']; self.work.invalidate_memory(); self.close_inline(); self.replace_editor(self.current_page(),self.work.text)
        col.addWidget(button('恢复此版本',lambda:self.run(restore),True)); self.show_inline('版本历史',pane)
    def copy_project(self):
        if self.work: self.save_work(); store=self.workspace.copy(self.work.store); self.open_project(store.root)
    def trash_current(self):
        if self.work: self.trash_project(self.work.store.root)
    def trash_project(self,root,restore=False):
        self.save_work(); store=self.workspace.open(Path(root)); store.update_project(status='active' if restore else 'archived')
        for kind,work in self.works.items():
            if work and work.store.root==store.root: self.works[kind]=None
        if self.work and self.work.store.root==store.root: self.work=None
        self.navigate(0); self.offer_undo('项目已移入回收站' if not restore else '项目已恢复',lambda:self.trash_project(root,not restore))
    def import_reference(self,page):
        path,_=QFileDialog.getOpenFileName(self,'导入参考','','文本 (*.txt *.md *.json)')
        if not path: return
        data=import_preview(Path(path)); pane=QTextBrowser(); pane.setPlainText(data['text']); panel=QWidget(); col=QVBoxLayout(panel); col.addWidget(label('预览识别到的参考内容','muted')); col.addWidget(pane,1)
        def use(): page.reference.setPlainText(data['text']); page.notify('已导入'+Path(path).name); self.close_inline()
        col.addWidget(button('使用参考',use,True)); self.show_inline('参考内容',panel)
    def choose_reference(self,page):
        pane=QWidget(); col=QVBoxLayout(pane); search=QLineEdit(); search.setPlaceholderText('搜索已有作品'); rows=QListWidget(); preview=QTextBrowser(); col.addWidget(search); col.addWidget(rows); col.addWidget(preview,1); values=[]
        def refresh():
            values.clear(); rows.clear()
            for r in self.workspace.projects():
                if search.text() in r['name'] and not ProjectStore(Path(r['root'])).setting('system_test_project',False): values.append(r); rows.addItem(r['name'])
        def pick(index):
            if index>=0:
                store=ProjectStore(Path(values[index]['root'])); preview.setPlainText('\n\n'.join(store.document(d['id'])['text'] for d in store.documents() if d['kind']!='reference'))
        def use(): page.reference.setPlainText(preview.toPlainText()); self.close_inline()
        rows.currentRowChanged.connect(pick); search.textChanged.connect(refresh); col.addWidget(button('使用参考',use,True)); refresh(); self.show_inline('已有作品',pane)
    def import_work(self):
        page=self.current_page()
        if not isinstance(page,CreationPage): return
        path,_=QFileDialog.getOpenFileName(self,'导入正文','','正文 (*.txt *.md)')
        if not path: return
        data=import_preview(Path(path)); pane=QWidget(); col=QVBoxLayout(pane); preview=QTextBrowser(); preview.setPlainText(data['text']); col.addWidget(preview,1)
        def use(append):
            work=self.ensure_work(page); work.edit(work.text+'\n\n'+data['text'] if append else data['text']); work.save('导入'); self.close_inline(); self.replace_editor(page,work.text)
        actions=QHBoxLayout(); actions.addWidget(button('替换为新版本',lambda:self.run(lambda:use(False)),True)); actions.addWidget(button('追加到末尾',lambda:self.run(lambda:use(True)))); col.addLayout(actions); self.show_inline('导入正文',pane)
    def export_work(self,extension):
        if not self.work: raise ValueError('先生成或导入作品')
        self.save_work(); work=self.work; name=re.sub(r'[<>:"/\\|?*]','_',work.store.metadata()['name']); output_type='剧本' if work.config['output']=='script' else '小说'
        path,_=QFileDialog.getSaveFileName(self,'导出作品',name+'_'+output_type+'.'+extension,'作品 (*.'+extension+')')
        if path: atomic_write(Path(path),work.text.encode('utf-8')); self.statusBar().showMessage('作品已导出',5000)
    def lock_selection(self):
        if not self.work: return
        self.save_work(); a,b=self.selection_range(self.current_page())
        if a==b: raise ValueError('先选中要锁定的内容')
        self.work.store.lock(self.work.document_id,self.work.text[a:b],a); self.current_page().notify('所选内容已锁定')
    def unlock_selection(self):
        if self.work: self.confirm_inline('这次修改涉及已锁定内容，是否解除锁定？',lambda:self.work.store.unlock(self.work.document_id))
    def read_mode(self,page):
        self.reading=not self.reading; self.sidebar.setVisible(not self.reading); self.assistant.setVisible(not self.reading and not self.options.get('assistant_collapsed',False)); page.form_scroll.setVisible(not self.reading); page.advanced_toggle.setVisible(not self.reading); page.idea.setVisible(not self.reading); page.generate_button.setVisible(not self.reading); page.advanced.hide(); self.statusBar().showMessage('阅读模式' if self.reading else '',0)
        if not hasattr(self,'exit_read'): self.exit_read=button('退出阅读',self.escape,quiet=True); self.statusBar().addWidget(self.exit_read)
        self.exit_read.setVisible(self.reading)
    def escape(self):
        if self.reading and isinstance(self.current_page(),CreationPage): self.read_mode(self.current_page())
        elif self.inline: self.close_inline()
    def batch_chapters(self):
        if not self.work or self.work.config['output']!='novel': return
        pane=QWidget(); col=QVBoxLayout(pane); start=QSpinBox(); end=QSpinBox(); count=len(self.work.store.documents()); start.setRange(count+1,1000); start.setValue(count+1); end.setRange(count+1,1000); end.setValue(count+1); col.addWidget(label('连续生成章节')); col.addWidget(start); col.addWidget(end); notice=label('','muted'); col.addWidget(notice)
        def update(): notice.setText(f'预计{max(0,end.value()-start.value()+1)}次请求；费用未知，按服务商实际计费')
        start.valueChanged.connect(update); end.valueChanged.connect(update); update()
        def begin():
            if start.value()!=count+1 or end.value()<start.value(): raise ValueError('从当前最后一章继续，起止章节须连续')
            self.options['batch_remaining']=end.value()-start.value()+1; self.close_inline(); self.continue_batch()
        col.addWidget(button('开始生成',lambda:self.run(begin),True)); self.show_inline('连续生成',pane)
    def continue_batch(self):
        n=self.options.get('batch_remaining',0)
        if n<=0: return
        self.options['batch_remaining']=n-1; self.next_chapter()
    def migrate_workspace(self):
        self.save_work()
        if self.active_task or self.active_image_task: raise ValueError('先停止生成或等待完成，再更改项目位置')
        target=QFileDialog.getExistingDirectory(self,'选择新的项目位置')
        if not target: return
        destination=Workspace(Path(target)); original=self.workspace
        if self.settings.operations: raise ValueError('设置操作正在进行，请等待完成')
        self.migrating=True
        for page in self.creators.values(): page.editor.setReadOnly(True)
        def unlock():
            self.migrating=False
            for page in self.creators.values(): page.editor.setReadOnly(False)
        def finished(mapping):
            for work in self.works.values():
                if work:
                    new_root=mapping.get(os.path.normcase(str(work.store.root.resolve())))
                    if new_root: work.store=destination.open(new_root)
            for key in ('last_project','recent:script','recent:novel','recent:rewrite'):
                old=self.options.get(key)
                if old and os.path.normcase(str(Path(old).resolve())) in mapping: self.options[key]=str(mapping[os.path.normcase(str(Path(old).resolve()))])
            self.workspace=destination; self.options['workspace_root']=str(destination.root); self.save_options(); self.settings.project_path.setText(str(destination.root)); self.home.refresh(); unlock()
        self.settings.operation(lambda:original.migrate_to(destination),finished,self.settings.project_path,unlock)
    def backup_project(self):
        if not self.work: raise ValueError('先打开作品再备份')
        self.save_work(); path,_=QFileDialog.getSaveFileName(self,'备份项目',self.work.store.metadata()['name']+'.ttbackup','项目备份 (*.ttbackup)')
        if path: self.workspace.backup(self.work.store,Path(path)); self.statusBar().showMessage('备份已保存',5000)
    def restore_project(self):
        path,_=QFileDialog.getOpenFileName(self,'恢复项目','','项目备份 (*.ttbackup)')
        if not path: return
        import zipfile
        with zipfile.ZipFile(path) as archive: manifest=json.loads(archive.read('manifest.json'))
        if manifest.get('format')!='tt-create-backup': raise ValueError('备份格式不受支持')
        self.confirm_inline('恢复备份为新项目，保留当前所有作品',lambda:self.open_project(self.workspace.restore(Path(path)).root),parent=self.settings)
    def open_logs(self):
        folder=self.resources.parent/'logs'; folder.mkdir(exist_ok=True); os.startfile(folder)
    def export_diagnostics(self):
        path,_=QFileDialog.getSaveFileName(self,'导出诊断包','TT创作助手_诊断.json','诊断 (*.json)')
        if path: write_json(Path(path),dict(version='2.0-dev',rules=len(self.registry.rows),text_connections=[dict(provider=c.provider,configured=bool(c.model)) for c in self.connections.all()],image_connections=[dict(provider=c.provider,status=c.capability_status) for c in self.image_connections.all()],notes='不包含正文、密钥、认证、完整请求或用户路径'))
    def show_budget_panel(self):
        pane=QWidget(); col=QVBoxLayout(pane); col.addWidget(label('费用未知时无法估算或保证金额；调用次数单独限制','muted')); limit=QSpinBox(); limit.setRange(1,16); limit.setValue(self.options.get('call_limit',4)); col.addWidget(label('每次请求最多调用次数')); col.addWidget(limit)
        def save(): self.options['call_limit']=limit.value(); self.save_options(); self.close_inline()
        col.addWidget(button('保存',save,True)); self.show_inline('费用控制',pane,return_widget=self.settings)
    def eventFilter(self,watched,event):
        # Qt builds without qtbase_zh_CN still have fully Chinese edit menus.
        if event.type()==QEvent.Type.ContextMenu and isinstance(watched,(QTextEdit,QPlainTextEdit,QLineEdit)) and not any(watched is p.editor for p in self.creators.values()):
            menu=QMenu(watched)
            for name,fn in [('撤销',watched.undo),('重做',watched.redo),('剪切',watched.cut),('复制',watched.copy),('粘贴',watched.paste),('全选',watched.selectAll)]: menu.addAction(name,fn)
            menu.exec(event.globalPos()); return True
        return super().eventFilter(watched,event)
    def closeEvent(self,event):
        if self.active_task or self.active_image_task:
            if not self.close_after_task:
                reply=QMessageBox.question(self,'有内容正在生成','停止并退出会保留已收到的草稿，远端可能继续计费。',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
                if reply==QMessageBox.StandardButton.Yes: self.close_after_task=True; self.options['batch_remaining']=0; self.stop_task(); self.stop_image()
            event.ignore(); return
        try: self.save_work(); self.save_layout()
        except (ValueError,OSError,RuntimeError): event.ignore(); return
        QApplication.instance().removeEventFilter(self); super().closeEvent(event)
