from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout,QLabel,QListWidget,QListWidgetItem,QPushButton,QSplitter,
    QStackedWidget,QTextBrowser,QVBoxLayout,QWidget,QAbstractItemView)

from app.core.writing import WritingService


class WorkViews(QStackedWidget):
    def __init__(self,owner,editor):
        super().__init__()
        self.owner=owner
        self.addWidget(editor)
        self.outline_page=QWidget()
        outline=QVBoxLayout(self.outline_page)
        controls=QHBoxLayout()
        controls.addWidget(QLabel('同一目录节点 · 拖动同步顺序，正文保留'))
        controls.addWidget(owner.button('卡片 / 列表',self.toggle_cards))
        outline.addLayout(controls)
        self.outline=QListWidget()
        self.outline.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.outline.itemDoubleClicked.connect(self.open_node)
        self.outline.model().rowsMoved.connect(self.save_order)
        outline.addWidget(self.outline)
        self.addWidget(self.outline_page)
        self.compare=QSplitter()
        self.source,self.target=QTextBrowser(),QTextBrowser()
        self.compare.addWidget(self.source)
        self.compare.addWidget(self.target)
        self.addWidget(self.compare)
        self.review=QSplitter()
        self.review_text=QTextBrowser()
        self.review_issues=QListWidget()
        self.review.addWidget(self.review_text)
        self.review.addWidget(self.review_issues)
        self.review_issues.currentRowChanged.connect(self.locate_issue)
        self.addWidget(self.review)
        self.loading=False
        self.issues=[]

    def show_view(self,index):
        if index==4:
            self.setCurrentIndex(0)
            self.owner.enter_focus()
            return
        self.owner.exit_focus()
        self.setCurrentIndex(index)
        self.refresh()
        if self.owner.store and not self.owner.loading:
            self.owner.store.set_setting('last_view',index)

    def refresh(self):
        owner=self.owner
        if not owner.store:
            return
        self.loading=True
        self.outline.clear()
        for doc in owner.store.documents():
            node=owner.store.setting('node:'+doc['id'],{})
            item=QListWidgetItem(doc['title']+'\n'+node.get('purpose','未设置节点目的')+(' · 已锁定' if node.get('locked') else ''))
            item.setData(Qt.ItemDataRole.UserRole,doc['id'])
            self.outline.addItem(item)
        self.loading=False
        if owner.document_id:
            doc=owner.store.document(owner.document_id)
            self.target.setPlainText(owner.editor.toPlainText())
            self.review_text.setPlainText(owner.editor.toPlainText())
            if doc.get('source_id'):
                source=owner.store.document(doc['source_id'])
                frozen=owner.store.setting('source_revision:'+doc['id'])
                if frozen:
                    with owner.store.connection() as con:
                        row=con.execute('SELECT text FROM revisions WHERE id=? AND document_id=?',(frozen,source['id'])).fetchone()
                    text=row[0] if row else source['text']
                else:
                    text=source['text']
                self.source.setPlainText(source['title']+'\n来源版本：'+str(frozen or source['head'])+'\n\n'+text)
            else:
                self.source.setPlainText('当前文档没有来源映射。可从来源稿创建新稿；不会猜对应关系。')
        self.issues=[]
        self.review_issues.clear()
        if owner.last_task:
            service,tid=owner.last_task
            task=service.get(tid)
            if service.store.root==owner.store.root and task['document_id']==owner.document_id and task['stage']=='review_draft' and task['state']=='completed':
                self.issues=task['result']['candidate']['issues']
                for issue in self.issues:
                    self.review_issues.addItem(issue['issue']+'\n'+(issue['evidence'] or issue.get('missing_item',''))+'\n建议：'+issue['suggestion'])
        if not self.issues:
            self.review_issues.addItem('尚无当前范围的审稿问题；在右侧选择审稿并发送，不自动改正文。')

    def open_node(self,item):
        did=item.data(Qt.ItemDataRole.UserRole)
        for index in range(self.owner.documents.count()):
            document=self.owner.documents.item(index)
            if document.data(Qt.ItemDataRole.UserRole)==did:
                self.owner.documents.setCurrentItem(document)
                self.owner.view_combo.setCurrentIndex(0)
                break

    def save_order(self,*args):
        if self.loading or not self.owner.store:
            return
        ids=[self.outline.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.outline.count())]
        self.owner.run(lambda:self.owner.store.reorder(ids))
        self.owner.refresh_documents(self.owner.document_id)

    def toggle_cards(self):
        mode=QListWidget.ViewMode.IconMode if self.outline.viewMode()==QListWidget.ViewMode.ListMode else QListWidget.ViewMode.ListMode
        self.outline.setViewMode(mode)
        self.outline.setResizeMode(QListWidget.ResizeMode.Adjust)

    def locate_issue(self,index):
        if index<0 or index>=len(self.issues):
            return
        issue=self.issues[index]
        if not issue['evidence']:
            return
        cursor=self.review_text.textCursor()
        cursor.setPosition(0)
        self.review_text.setTextCursor(cursor)
        self.review_text.find(issue['evidence'])
