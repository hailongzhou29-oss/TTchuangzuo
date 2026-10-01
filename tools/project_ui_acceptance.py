"""Project-page contract checks using real isolated Qt dialogs, no model calls."""
import json
import sys
import subprocess
import tempfile
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QTimer,Qt
from PySide6.QtGui import QColor,QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QCheckBox,QComboBox,QDialogButtonBox,QFileDialog,QInputDialog,QLabel,QLineEdit,QMessageBox,QPushButton,QTextEdit
from app.core.cover import default_cover,import_image
from app.core.services import Workspace
from app.ui.window import MainWindow
from app.storage.project import new_id,now
from app.core.processes import process_started

app=QApplication([])
checks=[]
def check(name,passed):
    checks.append(dict(check=name,passed=bool(passed)))

with tempfile.TemporaryDirectory(prefix='TT 项目合同隔离验收 ') as temporary:
    root=Path(temporary)
    workspace=Workspace(root/'data')
    project=workspace.create('完整交接本地验证项目','小说')
    project.set_setting('summary','海边的灯塔守护者')
    project.set_setting('creation_constraints',dict(tags=['近未来侦探']))
    did=project.add_document('第二章','第一章🙂\n第二段')
    prefs=root/'settings'/'preferences.json'
    broken=workspace.projects_root/'isolated_corrupt_project'
    broken.mkdir()
    broken_bytes=b'ISOLATED_INVALID_SQLITE_TEST_ONLY'
    (broken/'project.sqlite').write_bytes(broken_bytes)
    window=MainWindow(workspace,ROOT/'resources',prefs)
    window.show()
    check('损坏项目不会阻断工作区启动或改写损坏文件',window.isVisible() and
          (broken/'project.sqlite').read_bytes()==broken_bytes and window.home.continue_button.isEnabled())
    check('损坏项目在列表中不可误选',all(
          not bool(window.project_list.item(i).flags()&Qt.ItemFlag.ItemIsEnabled)
          for i in range(window.project_list.count()) if window.project_list.item(i).data(Qt.ItemDataRole.UserRole)==str(broken.resolve())))

    def fill_new(name,close_on_rejection=False,directory_root=None):
        def drive():
            dialog=app.activeModalWidget()
            field=dialog.findChild(QLineEdit,'newProjectName')
            buttons=dialog.findChild(QDialogButtonBox)
            check('新建对话框空名称禁止提交',not buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())
            kind=dialog.findChild(QComboBox)
            check('新建内容形式包含小说剧本文案',[kind.itemText(i) for i in range(kind.count())]==['小说','剧本','文案'])
            if directory_root:
                chooser=next(button for button in dialog.findChildren(QPushButton) if button.text()=='选择目录')
                with patch.object(QFileDialog,'getExistingDirectory',return_value=str(directory_root)):
                    chooser.click()
                check('新建目录选择器更新本次存放位置',dialog.findChild(QLineEdit,'newProjectDirectory').text()==str(directory_root))
            field.setText(name)
            buttons.button(QDialogButtonBox.StandardButton.Ok).click()
            if close_on_rejection:
                check('拒绝同名创建保留对话框',dialog.isVisible())
                dialog.reject()
        QTimer.singleShot(30,drive)

    fill_new('同名演示')
    window.new_project()
    before=workspace.projects('all')
    with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No) as question:
        fill_new('同名演示',True)
        window.new_project()
        check('同名提示拒绝后未创建额外项目',question.call_count==1 and len(workspace.projects('all'))==len(before))
    with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes) as question:
        fill_new('同名演示')
        window.new_project()
        named=[p for p in workspace.projects('all') if p['name']=='同名演示']
        check('同名确认允许独立目录与新ID',question.call_count==1 and len(named)==2 and
              len({p['id'] for p in named})==2 and len({p['root'] for p in named})==2)
    custom_parent=root/'自选 项目目录'
    custom_parent.mkdir()
    fill_new('自选位置的界面项目',directory_root=custom_parent)
    window.new_project()
    custom=window.store
    check('自选目录创建独立文件夹且默认目录不变',custom.root.parent==custom_parent.resolve() and
          window.workspace.projects_root==workspace.root/'projects' and (custom.root/'project.sqlite').is_file())
    reloaded=Workspace(workspace.root)
    check('工作区重开仍发现自选目录项目',sum(p['id']==custom.metadata()['id'] for p in reloaded.projects('all'))==1)

    window.open_project(project.root)
    window.refresh_documents(did)
    cursor=window.editor.textCursor()
    cursor.setPosition(7)
    window.editor.setTextCursor(cursor)
    window.view_combo.setCurrentIndex(1)
    window.save()
    window.close()
    window=MainWindow(workspace,ROOT/'resources',prefs)
    window.show()
    window.continue_project()
    check('重开继续创作恢复文档视图与UTF16光标',window.document_id==did and
          window.view_combo.currentIndex()==1 and window.editor.textCursor().position()==7 and
          window.editor.toPlainText()=='第一章🙂\n第二段')
    for term in ('完整交接','近未来侦探','灯塔守护者'):
        window.project_search.setText(term)
        check('项目搜索实际名称标签摘要：'+term,window.project_list.count()==1 and
              window.project_list.item(0).data(Qt.ItemDataRole.UserRole)==str(project.root))
    marker='isolated-vault-test-search-marker'
    window.connections.vault.set('isolated-test',marker)
    window.project_search.setText(marker)
    check('项目搜索不读取独立凭据库',window.project_list.count()==0)
    window.home.clear_filters()
    window.home.select_project(str(project.root))

    image=QImage(20,30,QImage.Format.Format_RGB32)
    image.fill(QColor('#b5bdda'))
    source=root/'cover.png'
    image.save(str(source))
    relative,_=import_image(project,source)
    spec=default_cover('创作验证','小说')
    spec['image']=relative
    project.set_setting('active_cover',project.save_cover(spec))
    def drive_copy(include_assets=False):
        dialog=app.activeModalWidget()
        assets=dialog.findChild(QCheckBox,'copyProjectAssets')
        check('复制对话框提供素材选择且默认复制',assets is not None and assets.isChecked())
        assets.setChecked(include_assets)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
    existing={p['id'] for p in workspace.projects('all')}
    QTimer.singleShot(30,drive_copy)
    window.copy_project()
    created=[p for p in workspace.projects('all') if p['id'] not in existing]
    copied=workspace.open(Path(created[0]['root']))
    check('界面选择不复制素材保留正文',len(created)==1 and copied.document(did)['text']=='第一章🙂\n第二段' and
          not copied.setting('copied_assets') and list((copied.root/'assets').iterdir())==[])
    existing={p['id'] for p in workspace.projects('all')}
    QTimer.singleShot(30,lambda:drive_copy(True))
    window.copy_project()
    created=[p for p in workspace.projects('all') if p['id'] not in existing]
    copied=workspace.open(Path(created[0]['root']))
    check('界面选择复制素材保留登记图片和封面绑定',len(created)==1 and copied.setting('copied_assets') and
          (copied.root/relative).read_bytes()==(project.root/relative).read_bytes() and copied.covers()[0]['spec']['image']==relative)

    window.home.select_project(str(project.root))
    for field,label in [('active_task','文字'),('active_image_task','图片')]:
        setattr(window,field,dict(service=SimpleNamespace(store=project)))
        blocked=False
        try:
            window.trash_project()
        except ValueError:
            blocked=True
        setattr(window,field,None)
        check(label+'任务未结束阻止项目回收',blocked and project.metadata()['status']=='active')
    window.backup_operation=SimpleNamespace(project_root=project.root,completed=Event())
    blocked=False
    try:
        window.trash_project()
    except ValueError:
        blocked=True
    window.backup_operation=None
    check('一致性备份未结束阻止项目回收',blocked and project.metadata()['status']=='active')
    child=subprocess.Popen([sys.executable,'-c',"import sys,os,json; print(json.dumps(dict(ready=True,pid=os.getpid())),flush=True); sys.stdin.read()"],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        worker=json.loads(child.stdout.readline())
        ready=worker['ready'] and child.poll() is None
        task_id=new_id()
        with project.connection(write=True) as con:
            con.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?)',
                (task_id,project.metadata()['id'],did,'discussion',json.dumps(dict(owner_pid=0,development_test=True)),
                 'waiting',json.dumps(dict(text='跨进程范围测试的部分记录')),now(),now()))
            con.execute('INSERT INTO task_leases VALUES(?,?,?,?,?,?,?)',
                (task_id,new_id(),worker['pid'],process_started(worker['pid']),'fixture',1,now()))
        with patch.object(QMessageBox,'question') as question:
            blocked=False
            try:
                window.trash_project()
            except ValueError:
                blocked=True
            check('实际存活辅助进程的任务记录阻止回收',ready and blocked and question.call_count==0 and project.metadata()['status']=='active')
        with project.connection(write=True) as con:
            con.execute("UPDATE tasks SET state='completed' WHERE id=?",(task_id,))
        with patch.object(QMessageBox,'question') as question:
            blocked=False
            try:
                window.trash_project()
            except ValueError:
                blocked=True
            check('执行记录激活时保护已完成状态的任务',blocked and question.call_count==0 and project.metadata()['status']=='active')
        with project.connection(write=True) as con:
            con.execute("UPDATE tasks SET state='waiting' WHERE id=?",(task_id,))
        child.stdin.close()
        child.wait(timeout=5)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No) as question:
            window.trash_project()
            with project.connection() as con:
                task=con.execute('SELECT state,result FROM tasks WHERE id=?',(task_id,)).fetchone()
            check('所属进程结束后保留结果待确认且不自动重发',child.poll()==0 and task['state']=='uncertain' and
                  json.loads(task['result'])['text']=='跨进程范围测试的部分记录' and question.call_count==1 and
                  '结果待确认' in question.call_args.args[2] and project.metadata()['status']=='active')
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
    with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
        window.trash_project()
        check('确认回收只改变状态并保留文件',project.metadata()['status']=='trash' and (project.root/'project.sqlite').is_file())
        window.project_filter.setCurrentIndex(2)
        window.home.select_project(str(project.root))
        window.trash_project()
        check('回收区项目能恢复活跃列表',project.metadata()['status']=='active' and project.document(did)['text']=='第一章🙂\n第二段')
    window.home.clear_filters()
    window.home.select_project(str(project.root))
    before_project_id=project.metadata()['id']
    before_document_ids=[d['id'] for d in project.documents()]
    with patch.object(QInputDialog,'getText',return_value=('重命名后的验证项目',True)):
        window.rename_project()
    check('重命名保持项目及内部文档稳定ID',project.metadata()['name']=='重命名后的验证项目' and
          project.metadata()['id']==before_project_id and [d['id'] for d in project.documents()]==before_document_ids)
    with patch.object(QInputDialog,'getText',return_value=('   ',True)), patch.object(QMessageBox,'warning') as warning:
        result=window.run(window.rename_project)
        check('空名称重命名提示错误且原项目不变',result is False and warning.call_count==1 and
              project.metadata()['name']=='重命名后的验证项目' and project.metadata()['id']==before_project_id)
    window.archive_project()
    check('归档从活跃列表隐藏',project.metadata()['status']=='archived' and
          all(window.project_list.item(i).data(Qt.ItemDataRole.UserRole)!=str(project.root) for i in range(window.project_list.count())))
    window.project_filter.setCurrentIndex(1)
    window.home.select_project(str(project.root))
    window.archive_project()
    check('取消归档保留原始项目和文档ID',project.metadata()['status']=='active' and project.document(did)['id']==did)
    window.home.clear_filters()
    window.home.select_project(str(project.root))
    def import_fixture(path,readonly=False,cancel=False):
        text=path.read_bytes().decode('utf-8-sig')
        before=len(project.documents())
        def drive():
            dialog=app.activeModalWidget()
            body=dialog.findChild(QTextEdit)
            check('导入预览展示原文且不能编辑：'+path.suffix,body.isReadOnly() and body.toPlainText()==text.replace('\r\n','\n'))
            labels='\n'.join(label.text() for label in dialog.findChildren(QLabel))
            check('导入预览显示编码与结构说明：'+path.suffix,'编码：utf-8-sig' in labels and
                  ('JSON 原结构保留' in labels if path.suffix=='.json' else '保留原始文本' in labels))
            if cancel:
                dialog.reject()
            else:
                dialog.findChild(QComboBox).setCurrentIndex(1 if readonly else 0)
                dialog.accept()
        with patch.object(QFileDialog,'getOpenFileName',return_value=(str(path),'')) as picker:
            QTimer.singleShot(30,drive)
            window.import_file()
            check('导入选择器未启用未验收DOCX','*.docx' not in picker.call_args.args[3])
        if cancel:
            check('取消导入不创建文档',len(project.documents())==before)
        else:
            document=project.document(window.document_id)
            check('确认导入保留未知内容和来源类型：'+path.suffix,document['text']==text and
                  (document['kind']=='reference')==readonly and project.setting('import:'+document['id'])['source_name']==path.name)
    markdown=root/'本地导入.md'
    markdown.write_text('# 原文\n\n保留 🙂 与换行。',encoding='utf-8')
    import_fixture(markdown,cancel=True)
    import_fixture(markdown)
    unknown=root/'未识别结构.json'
    unknown.write_text('{"unknown": {"items": ["保留字段"]}}',encoding='utf-8')
    import_fixture(unknown,readonly=True)
    backup=root/'界面备份.ttbackup'
    with patch.object(QFileDialog,'getSaveFileName',return_value=(str(backup),'')):
        window.backup_project()
    check('界面备份实际写入一致性文件',backup.is_file() and backup.stat().st_size>0)
    original_id=project.metadata()['id']
    original_docs=[(d['id'],project.document(d['id'])['text']) for d in project.documents()]
    with patch.object(QFileDialog,'getOpenFileName',return_value=(str(backup),'')):
        window.restore_backup()
    restored=window.store
    check('界面恢复选择文件后写入新项目而不覆盖原项目',restored.root!=project.root and
          restored.metadata()['id']!=original_id and project.metadata()['id']==original_id and
          [(d['id'],restored.document(d['id'])['text']) for d in restored.documents()]==original_docs and
          (restored.root/relative).read_bytes()==(project.root/relative).read_bytes())
    before={p['id'] for p in workspace.projects('all')}
    with patch.object(QFileDialog,'getOpenFileName',return_value=('','')):
        window.restore_backup()
    check('取消恢复不创建额外目录或切换项目',{p['id'] for p in workspace.projects('all')}==before and window.store.root==restored.root)
    window.close()
    only_bad=Workspace(root/'only_bad_data')
    unreadable=only_bad.projects_root/'bad'
    unreadable.mkdir()
    (unreadable/'project.sqlite').write_bytes(broken_bytes)
    bad_window=MainWindow(only_bad,ROOT/'resources',root/'only_bad_settings'/'preferences.json')
    bad_window.show()
    check('仅有损坏项目时仍可启动且继续按钮禁用',bad_window.isVisible() and not bad_window.home.continue_button.isEnabled())
    bad_window.close()

evidence=ROOT/'docs'/'evidence'/'project_ui_results.json'
evidence.write_text(json.dumps(dict(mode='真实本地Qt与文件操作；文件选择和确认使用固定测试输入，任务检查使用范围桩，没有供应商调用',checks=checks),ensure_ascii=False,indent=2),encoding='utf-8')
for item in checks:
    print(('PASS ' if item['passed'] else 'FAIL ')+item['check'])
if not all(item['passed'] for item in checks):
    raise SystemExit(1)
