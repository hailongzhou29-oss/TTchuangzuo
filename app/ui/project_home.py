from datetime import datetime,timezone
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,Signal,QEvent
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QScrollArea,QLineEdit,QComboBox,QFrame,QMenu
from app.ui.v2_widgets import label,button,QComboBox,QMenu
from app.core.cover import render_cover,default_cover
from app.storage.project import ProjectStore

def relative_time(value):
    try:
        stamp=datetime.fromisoformat(value); seconds=(datetime.now(timezone.utc)-stamp).total_seconds()
        if seconds<60: return '刚刚'
        if seconds<3600: return f'{int(seconds//60)}分钟前'
        if seconds<86400: return f'{int(seconds//3600)}小时前'
        if seconds<172800: return '昨天'
        return stamp.strftime('%Y-%m-%d') if seconds>604800 else f'{int(seconds//86400)}天前'
    except (ValueError,TypeError): return ''

class ProjectCard(QFrame):
    open_requested=Signal(str)
    selected=Signal(str)
    def __init__(self,owner,row):
        super().__init__(); self.owner=owner; self.row=row; self.setObjectName('projectCard'); self.setProperty('selected',False); self.setFocusPolicy(Qt.FocusPolicy.StrongFocus); self.setToolTip('单击选择，双击继续创作'); self.setMinimumWidth(300); self.setMaximumWidth(320)
        col=QVBoxLayout(self); col.setContentsMargins(10,10,10,10); col.setSpacing(6)
        self.cover=label(''); self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter); col.addWidget(self.cover)
        self.title=label(row['name']); self.title.setFixedHeight(44); col.addWidget(self.title)
        self.rename=QLineEdit(row['name']); self.rename.hide(); self.rename.returnPressed.connect(self.save_name); col.addWidget(self.rename)
        desc=QHBoxLayout(); desc.addWidget(label(row.get('description',row['kind']),'muted'),1); desc.addWidget(label(relative_time(row['updated']),'muted')); col.addLayout(desc)
        self.actions={}; actions=QHBoxLayout(); actions.setSpacing(3)
        callbacks=[('重命名',self.start_rename),('生成封面',lambda:owner.run(lambda:owner.open_home_cover(row['root']))),('导出',lambda:owner.run(lambda:owner.export_home(row['root']))),('删除',lambda:owner.run(lambda:owner.trash_project(row['root'])))] if row['status']=='active' else [('恢复',lambda:owner.run(lambda:owner.trash_project(row['root'],True)))]
        for text,callback in callbacks:
            action=button(text,callback,quiet=True); action.setObjectName('projectAction'); action.setProperty('danger',text=='删除'); action.setToolTip('删除项目，移入回收站' if text=='删除' else text); action.setMinimumWidth(82 if text=='生成封面' else 52); actions.addWidget(action,2 if text=='生成封面' else 1); self.actions[text]=action
        col.addLayout(actions)
        for widget in (self.cover,self.title): widget.installEventFilter(self)
        self.cover_spec=default_cover(row['name'],row['kind']); self.cover_spec.update(ratio='3:4',font_size=60)
        try:
            store=ProjectStore(Path(row['root'])); active=store.setting('active_cover'); covers=store.covers()
            if active: self.cover_spec=next((r['spec'] for r in covers if r['id']==active),self.cover_spec)
        except (ValueError,OSError): pass
    def resizeEvent(self,event):
        super().resizeEvent(event); width=max(160,self.width()-20); self.cover.setFixedHeight(round(width*4/3)); self.setFixedHeight(round(width*4/3)+132)
        try: pix=QPixmap.fromImage(render_cover(self.cover_spec,Path(self.row['root']),width=width)); self.cover.setPixmap(pix.scaled(width,round(width*4/3),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        except (ValueError,OSError): self.cover.setText(self.row['name'][:1]+'\n'+self.row['kind'])
    def eventFilter(self,watched,event):
        if event.type()==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.LeftButton: self.select()
        if event.type()==QEvent.Type.MouseButtonDblClick and event.button()==Qt.MouseButton.LeftButton: self.open_requested.emit(self.row['root']); return True
        if watched is self.rename and event.type()==QEvent.Type.KeyPress and event.key()==Qt.Key.Key_Escape: self.rename.hide(); self.title.show(); return True
        return super().eventFilter(watched,event)
    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton: self.select(); self.open_requested.emit(self.row['root'])
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton: self.select()
        super().mousePressEvent(event)
    def focusInEvent(self,event):
        self.select(); super().focusInEvent(event)
    def select(self): self.selected.emit(self.row['root'])
    def set_selected(self,value):
        self.setProperty('selected',value); self.style().unpolish(self); self.style().polish(self); self.update()
    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter): self.open_requested.emit(self.row['root'])
        else: super().keyPressEvent(event)
    def menu(self):
        menu=QMenu(self)
        if self.row['status']=='active':
            menu.addAction('重命名',self.start_rename); menu.addAction('生成封面',lambda:self.owner.run(lambda:self.owner.open_home_cover(self.row['root']))); menu.addAction('导出作品',lambda:self.owner.run(lambda:self.owner.export_home(self.row['root']))); menu.addAction('移入回收站',lambda:self.owner.run(lambda:self.owner.trash_project(self.row['root'])))
        else: menu.addAction('恢复项目',lambda:self.owner.run(lambda:self.owner.trash_project(self.row['root'],True)))
        menu.exec(self.mapToGlobal(self.rect().bottomRight()))
    def start_rename(self): self.title.hide(); self.rename.show(); self.rename.installEventFilter(self); self.rename.setFocus(); self.rename.selectAll()
    def save_name(self):
        store=ProjectStore(Path(self.row['root'])); store.update_project(name=self.rename.text().strip() or '未命名'+self.row['kind']); self.owner.home.refresh()

class ProjectHome(QWidget):
    def __init__(self,owner):
        super().__init__(); self.owner=owner; self.cards=[]; self.columns=0; self.selected_root=None
        col=QVBoxLayout(self); col.setContentsMargins(24,24,24,24); col.setSpacing(16)
        head=QHBoxLayout(); titles=QVBoxLayout(); titles.addWidget(label('创作项目','heading')); titles.addWidget(label('继续创作，或开始一个新故事','muted')); head.addLayout(titles,1)
        self.new_buttons={}
        for text,kind in [('新建剧本','script'),('新建小说','novel'),('新建仿写','rewrite')]:
            entry=button(text,lambda _checked=False,kind=kind:owner.run(lambda:owner.new_work(kind)),True); head.addWidget(entry); self.new_buttons[kind]=entry
        col.addLayout(head)
        filters=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText('搜索项目名称或内容'); filters.addWidget(self.search,1)
        self.types=QComboBox(); self.types.addItems(['全部类型','剧本','小说','仿写','回收站']); filters.addWidget(self.types); self.sort=QComboBox(); self.sort.addItems(['最近修改','最近创建','名称']); filters.addWidget(self.sort); col.addLayout(filters)
        self.note=label('','muted'); self.note.hide(); col.addWidget(self.note)
        self.empty=QWidget(); el=QVBoxLayout(self.empty); el.addStretch(); self.empty_title=label('开始你的第一部作品','heading'); el.addWidget(self.empty_title); self.empty_detail=label('选择剧本、小说或仿写，AI 会根据你的选择完成创作','muted'); el.addWidget(self.empty_detail)
        self.empty_actions=QWidget(); ea=QHBoxLayout(self.empty_actions)
        self.create_buttons={}
        from app.ui.icons import icon
        for text,kind,shape in [('写剧本','script','movie'),('写小说','novel','book'),('开始仿写','rewrite','arrows-exchange')]:
            entry=button(text,lambda _checked=False,kind=kind:owner.run(lambda:owner.new_work(kind))); entry.setObjectName('createEntry'); entry.setIcon(icon(shape,'#737B91',24)); entry.setMinimumHeight(76); entry.setToolTip({'script':'选择题材、时长与表现形式，开始写剧本','novel':'从故事想法到章节正文','rewrite':'导入参考内容，创作新的作品'}[kind]); ea.addWidget(entry); self.create_buttons[kind]=entry
        el.addWidget(self.empty_actions); self.clear=button('清除搜索',self.search.clear,quiet=True); self.clear.hide(); el.addWidget(self.clear); el.addStretch(); col.addWidget(self.empty,1)
        self.scroll=QScrollArea(); self.scroll.setWidgetResizable(True); self.content=QWidget(); self.grid=QGridLayout(self.content); self.grid.setContentsMargins(0,0,0,0); self.grid.setSpacing(20); self.grid.setAlignment(Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignLeft); self.scroll.setWidget(self.content); col.addWidget(self.scroll,1)
        self.debounce=QTimer(self); self.debounce.setInterval(300); self.debounce.setSingleShot(True); self.debounce.timeout.connect(self.refresh); self.search.textChanged.connect(lambda:self.debounce.start()); self.types.currentTextChanged.connect(self.refresh); self.sort.currentTextChanged.connect(self.refresh)
    def refresh(self,*_):
        for card in self.cards: card.hide(); self.grid.removeWidget(card); card.deleteLater()
        self.cards=[]; query=self.search.text().strip().casefold(); filter_kind=self.types.currentText(); trash=filter_kind=='回收站'
        rows=self.owner.workspace.projects('archived' if trash else 'active')
        filtered=[]
        for row in rows:
            store=ProjectStore(Path(row['root']))
            if store.setting('system_test_project',False) or store.setting('v2_material_draft',False): continue
            kind=store.setting('v2_kind',{'剧本':'script','小说':'novel','文案':'rewrite'}.get(row['kind'],'rewrite'))
            name={'script':'剧本','novel':'小说','rewrite':'仿写'}[kind]
            if filter_kind not in {'全部类型','回收站',name}: continue
            if query not in row['name'].casefold():
                if not query: pass
                else:
                    with store.connection() as con: found=con.execute('SELECT 1 FROM documents d JOIN revisions r ON r.id=d.head WHERE d.deleted=0 AND instr(lower(r.text),?)>0 LIMIT 1',(query,)).fetchone()
                    if not found: continue
            config=store.setting('v2_selection',{}); row['kind']=name
            row['description']=name+(' · '+str(config.get('duration',180)//60)+'分钟' if config.get('output')=='script' and config.get('duration',180)%60==0 else ' · '+str(config['duration'])+'秒' if config.get('output')=='script' else ' · '+str(len([d for d in store.documents() if d['kind']!='reference']))+'章' if config.get('length')=='长篇连载' else '')
            filtered.append(row)
        key=self.sort.currentText(); filtered.sort(key=lambda r:r['name'] if key=='名称' else r['created'] if key=='最近创建' else r['updated'],reverse=key!='名称')
        for row in filtered:
            card=ProjectCard(self.owner,row); card.selected.connect(self.select_card); card.set_selected(row['root']==self.selected_root); card.open_requested.connect(lambda root:self.owner.run(lambda:self.owner.open_project(Path(root)))); self.cards.append(card)
        self.empty.setVisible(not filtered); self.scroll.setVisible(bool(filtered)); self.empty_title.setText('没有找到相关项目' if query or trash else '开始你的第一部作品'); self.empty_detail.setText('换个关键词试试' if query else '回收站暂时没有项目' if trash else '选择剧本、小说或仿写，AI 会根据你的选择完成创作'); self.empty_actions.setVisible(not query and not trash); self.clear.setVisible(bool(query)); self.reflow()
    def reflow(self):
        columns=max(1,(self.scroll.viewport().width()+self.grid.spacing())//(300+self.grid.spacing())); self.columns=columns
        for i,card in enumerate(self.cards): self.grid.addWidget(card,i//columns,i%columns)
    def select_card(self,root):
        self.selected_root=root
        for card in self.cards: card.set_selected(card.row['root']==root)
    def resizeEvent(self,event): super().resizeEvent(event); self.reflow()
