from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path

from app.core.files import atomic_write, digest, inside, write_json
from app.storage.project import ProjectStore, new_id, now


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.projects_root = self.root / 'projects'
        self.projects_root.mkdir(parents=True, exist_ok=True)

    def projects(self, status='active'):
        result = []
        folders=list(self.projects_root.iterdir())+self.external_project_roots()
        seen=set()
        for folder in folders:
            folder=folder.resolve()
            identity=os.path.normcase(str(folder))
            if identity in seen:
                continue
            seen.add(identity)
            if not folder.is_dir() or not (folder / 'project.sqlite').is_file():
                continue
            try:
                metadata = ProjectStore(folder).metadata()
                store=ProjectStore(folder)
                metadata['search_text']=metadata['name']+' '+metadata['kind']+' '+str(store.setting('summary',''))+' '+json.dumps(store.setting('creation_constraints',{}),ensure_ascii=False)
                if status == 'all' or metadata['status'] == status:
                    result.append(dict(metadata, root=str(folder)))
            except (sqlite3.Error,TypeError,ValueError,KeyError,OSError):
                result.append(dict(id=folder.name, name=folder.name + '（数据损坏）', kind='未知', status='error', updated='', root=str(folder)))
        return sorted(result, key=lambda item: item['updated'], reverse=True)

    def external_project_roots(self):
        registry=self.root/'project_locations.sqlite'
        if not registry.is_file():
            return []
        with closing(sqlite3.connect(registry)) as con:
            return [Path(row[0]) for row in con.execute('SELECT root FROM project_locations ORDER BY root')]

    def register(self, store: ProjectStore):
        """Remember an explicitly opened external project; never scan its parent."""
        root=store.root.resolve()
        if root.parent==self.projects_root.resolve():
            return
        store.check()
        with closing(sqlite3.connect(self.root/'project_locations.sqlite')) as con:
            con.execute('CREATE TABLE IF NOT EXISTS project_locations(root TEXT PRIMARY KEY)')
            con.execute('INSERT OR IGNORE INTO project_locations VALUES(?)',(str(root),))
            con.commit()

    def create(self, name, kind, *, parent=None):
        directory=Path(parent).resolve() if parent is not None else self.projects_root
        if not directory.is_dir():
            raise ValueError('请选择一个存在的项目存放目录')
        store=ProjectStore.create(directory / new_id(), name, kind)
        try:
            self.register(store)
        except (sqlite3.Error,OSError) as exc:
            raise ValueError('项目已创建在 '+str(store.root)+'，但目录登记失败；可通过打开项目目录恢复。') from exc
        return store

    def open(self, folder: Path):
        store = ProjectStore(folder)
        store.check()
        return store

    def backup(self, store: ProjectStore, destination: Path, *, include_assets=True):
        """Only DB + registered local assets; never settings, credentials or logs."""
        with tempfile.TemporaryDirectory(prefix='tt-create-backup-') as work:
            database = Path(work) / 'project.sqlite'
            store.backup_database(database)
            files = {'project.sqlite': database}
            with closing(sqlite3.connect(database)) as con:
                for relative, in con.execute('SELECT relative FROM assets'):
                    if not include_assets:
                        continue
                    path = inside(store.root, relative)
                    if not path.is_file() or not relative.startswith('assets/'):
                        raise ValueError('已登记素材缺失，请修复后备份：' + relative)
                    files[relative] = path
            manifest = dict(format='tt-create-backup', schema_version=1, created=now(),
                            files={name: digest(path.read_bytes()) for name, path in files.items()})
            output = Path(work) / 'backup.ttbackup'
            with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as package:
                for name, path in files.items():
                    package.write(path, name)
                package.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
            atomic_write(destination, output.read_bytes())

    def restore(self, source: Path):
        """Validate before publishing; always restore to a new project directory."""
        with tempfile.TemporaryDirectory(prefix='tt-create-restore-') as work:
            temporary = Path(work)
            with zipfile.ZipFile(source) as package:
                members = package.infolist()
                names = [item.filename for item in members]
                if len(names) != len(set(names)) or len(names) > 5000 or sum(item.file_size for item in members) > 512 * 1024**2:
                    raise ValueError('备份存在重复文件或超过大小限制')
                manifest = json.loads(package.read('manifest.json'))
                if manifest.get('format') != 'tt-create-backup' or manifest.get('schema_version') != 1:
                    raise ValueError('备份格式或版本不受支持')
                files = manifest.get('files')
                if not isinstance(files, dict) or 'project.sqlite' not in files or set(names) != set(files) | {'manifest.json'}:
                    raise ValueError('备份文件清单不完整')
                for name, expected in files.items():
                    if name != 'project.sqlite' and not name.startswith('assets/'):
                        raise ValueError('备份包含非项目内容')
                    target = inside(temporary, name)
                    if (package.getinfo(name).external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError('备份不接受符号链接')
                    data = package.read(name)
                    if digest(data) != expected:
                        raise ValueError('备份文件校验失败：' + name)
                    atomic_write(target, data)
            checked = ProjectStore(temporary)
            checked.check()
            with checked.connection(write=True) as con:
                original = dict(con.execute('SELECT * FROM project').fetchone())
                con.execute('UPDATE project SET id=?,name=name || ?,status=?,updated=?', (new_id(), '（恢复）', 'active', now()))
                con.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('restored_from_project', json.dumps(dict(id=original['id'], name=original['name']), ensure_ascii=False)))
                con.execute('DELETE FROM task_leases')
                for task in con.execute("SELECT id,result FROM tasks WHERE state IN ('ready','waiting','generating')").fetchall():
                    result = json.loads(task['result']) if task['result'] else {}
                    result.update(status='uncertain', error='恢复的是任务快照，不是在此目录运行的任务；结果待确认，未自动重发')
                    con.execute('UPDATE tasks SET state=?,result=?,updated=? WHERE id=?', ('uncertain', json.dumps(result, ensure_ascii=False), now(), task['id']))
                for task in con.execute("SELECT t.id,t.result FROM tasks t JOIN image_jobs i ON t.id=i.task_id WHERE i.state IN ('ready','submitting','accepted','generating','downloading')").fetchall():
                    result = json.loads(task['result']) if task['result'] else {}
                    result.update(status='uncertain', error='恢复的图片任务快照需要先查询原任务或重试下载，未重新生成')
                    con.execute('UPDATE image_jobs SET state=?,updated=? WHERE task_id=?', ('uncertain', now(), task['id']))
                    con.execute('UPDATE tasks SET state=?,result=?,updated=? WHERE id=?', ('uncertain', json.dumps(result, ensure_ascii=False), now(), task['id']))
            for directory in ('assets', 'exports', 'backups'):
                (temporary / directory).mkdir(exist_ok=True)
            destination = self.projects_root / new_id()
            shutil.copytree(temporary, destination)
            return ProjectStore(destination)

    def copy(self, store: ProjectStore, *, include_assets=True):
        with tempfile.TemporaryDirectory() as work:
            archive = Path(work) / 'copy.ttbackup'
            self.backup(store, archive, include_assets=include_assets)
            result = self.restore(archive)
            result.update_project(name=store.metadata()['name'] + '（副本）')
            with result.connection(write=True) as con:
                # Copy authoritative creation materials, not model conversations or bills.
                for table in ('image_jobs', 'context_manifests', 'usage_ledger', 'messages', 'chat_threads', 'tasks', 'cache_entries', 'patches'):
                    con.execute('DELETE FROM ' + table)
                con.execute("DELETE FROM settings WHERE key IN ('chat_thread','assistant_note')")
                if con.execute("SELECT 1 FROM sqlite_master WHERE name='action_operations'").fetchone():
                    con.execute('DELETE FROM action_operations')
                if not include_assets:
                    con.execute('DELETE FROM assets')
                    for row in con.execute('SELECT id,spec FROM covers').fetchall():
                        spec=json.loads(row['spec'])
                        if spec.get('image'):
                            spec.update(image=None,include_local_text=True,origin='副本未复制图片素材；保留本地排版')
                            spec['title']=spec.get('title') or store.metadata()['name']
                            con.execute('UPDATE covers SET spec=? WHERE id=?',(json.dumps(spec,ensure_ascii=False),row['id']))
                    row=con.execute("SELECT value FROM settings WHERE key='cover_draft'").fetchone()
                    if row:
                        spec=json.loads(row['value'])
                        if spec.get('image'):
                            spec.update(image=None,include_local_text=True,origin='副本未复制图片素材；保留本地排版')
                            spec['title']=spec.get('title') or store.metadata()['name']
                            con.execute("UPDATE settings SET value=? WHERE key='cover_draft'",(json.dumps(spec,ensure_ascii=False),))
                con.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('copied_assets', json.dumps(bool(include_assets))))
                con.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('copied_from_project', json.dumps(dict(id=store.metadata()['id'], name=store.metadata()['name']), ensure_ascii=False)))
            return result


def import_preview(path: Path, encoding=None) -> dict:
    if path.suffix.lower() not in {'.md', '.txt', '.json', '.srt', '.vtt'}:
        raise ValueError('当前支持 MD/TXT/JSON/SRT/VTT；DOCX 尚未验收')
    if path.stat().st_size > 10 * 1024**2:
        raise ValueError('本阶段单文件导入限制为 10MB，请分章导入')
    raw = path.read_bytes()
    encodings = [encoding] if encoding else ['utf-8-sig', 'gb18030', 'utf-16']
    for name in encodings:
        try:
            text = raw.decode(name)
            if '\x00' in text:
                continue
            break
        except (UnicodeError, LookupError):
            continue
    else:
        raise ValueError('未能识别编码，请转为 UTF-8 后重试')
    note = '保留原始文本；章节标题不自动拆分，可导入后手动整理'
    if path.suffix.lower() == '.json':
        parsed = json.loads(text)
        if not isinstance(parsed, (dict, list)):
            raise ValueError('JSON 顶层必须是对象或数组')
        note = 'JSON 原结构保留为来源文本；未知字段未自动转换为作品数据'
    if path.suffix.lower() in {'.srt', '.vtt'}:
        note = '保留字幕时间码；不把时间码认定为镜头切点'
    return dict(title=path.stem, text=text, encoding=name, note=note, hash=digest(raw))


def export_document(store: ProjectStore, did: str, path: Path, selected_text=None):
    document = store.document(did)
    text = selected_text if selected_text is not None else document['text']
    structured = None
    if selected_text is None:
        from app.core.writing import WritingService
        structured = WritingService(store).payload(did)
        if structured and structured['stage'] == 'screenplay_generate' and document['status'] == 'confirmed':
            text = WritingService(store).export_screenplay(did)
    if path.suffix.lower() == '.json':
        payload = dict(schema_version=1, format='tt-create-document', project_id=store.metadata()['id'],
                       document_id=did, title=document['title'], kind=document['kind'],
                       revision=document['head'], status=document['status'], scope='selection' if selected_text is not None else 'document',
                       text=text, blocks=document['blocks'] if selected_text is None else [])
        if structured:
            payload['structured'] = structured
        write_json(path, payload)
    elif path.suffix.lower() in {'.md', '.txt'}:
        heading = f"# {document['title']}\n\n" if path.suffix.lower() == '.md' else ''
        atomic_write(path, (heading + text).encode('utf-8'))
    else:
        raise ValueError('导出格式应为 MD/TXT/JSON')


class RuleService:
    def __init__(self, resources: Path):
        self.resources = resources

    def rules(self):
        data = json.loads((self.resources / 'rules.json').read_text(encoding='utf-8'))
        ids = set()
        for rule in data:
            if not all(isinstance(rule.get(key), str) and rule[key] for key in ('rule_id', 'version', 'title', 'body')):
                raise ValueError('规则字段缺失')
            if rule['rule_id'] in ids or digest(rule['body']) != rule['hash']:
                raise ValueError('规则 ID 重复或正文哈希不符')
            ids.add(rule['rule_id'])
        return data
