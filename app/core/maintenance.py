import platform
from datetime import datetime,timezone
from app.core.files import inside
from app.storage.project import new_id

def automatic_backup(workspace,store,keep=5):
    if not isinstance(keep,int) or isinstance(keep,bool) or not 1<=keep<=50:
        raise ValueError('自动备份保留数量须为1—50')
    directory=inside(store.root,'backups')
    if not directory.is_dir():
        raise ValueError('项目备份目录缺失')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target=directory/('auto_'+stamp+'_'+new_id()[:8]+'.ttbackup')
    workspace.backup(store,target)
    files=sorted(directory.glob('auto_*.ttbackup'),key=lambda path:path.stat().st_mtime,reverse=True)
    for path in files[keep:]:
        if path.resolve().parent!=directory.resolve() or not path.resolve().is_relative_to(store.root.resolve()):
            raise ValueError('备份清理目标超出项目范围，未删除')
        path.unlink()
    return target

def diagnostics(owner):
    import PySide6
    project=None
    if owner.store:
        metadata=owner.store.metadata()
        with owner.store.connection() as con:
            tasks=[dict(row) for row in con.execute('SELECT id,stage,state,created,updated FROM tasks ORDER BY rowid DESC LIMIT 30')]
            version=con.execute('PRAGMA user_version').fetchone()[0]
        project=dict(id=metadata['id'],kind=metadata['kind'],database_version=version,document_count=len(owner.store.documents()),tasks=tasks)
    return dict(format='tt-creation-diagnostic',version=1,python=platform.python_version(),pyside=PySide6.__version__,system=platform.system(),theme=owner.theme,
        ui_font_size=owner.options.get('ui_font_size',14),editor_font_size=owner.options.get('editor_font_size',18),project=project,
        text_connections=[dict(id=c.id,provider=c.provider,model=c.model,enabled=c.enabled,status=c.capability_status,verification=c.verification) for c in owner.connections.all()],
        image_connections=[dict(id=c.id,provider=c.provider,model=c.model,enabled=c.enabled,status=c.capability_status) for c in owner.image_connections.all()],
        privacy='不含KEY、认证文件、作品正文、提示词或签名链接；用户预览后导出')
