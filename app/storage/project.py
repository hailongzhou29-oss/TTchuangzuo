from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from app.core.files import digest

SCHEMA_VERSION = 6

TASK_DDL = (
    '''CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, document_id TEXT,
        stage TEXT NOT NULL, snapshot TEXT NOT NULL, state TEXT NOT NULL, result TEXT,
        created TEXT NOT NULL, updated TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS usage_ledger(id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
        connection_name TEXT NOT NULL, model TEXT NOT NULL, usage TEXT NOT NULL, raw_usage TEXT, created TEXT NOT NULL)''',
)

CONTEXT_DDL = (
    '''CREATE TABLE entities(id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, created TEXT NOT NULL)''',
    '''CREATE TABLE facts(id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entities(id), content TEXT NOT NULL,
        state TEXT NOT NULL, source_document_id TEXT, source_revision TEXT, source_block_id TEXT, evidence TEXT,
        valid_from INTEGER, valid_to INTEGER, version INTEGER NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL)''',
    '''CREATE TABLE fact_versions(id TEXT PRIMARY KEY, fact_id TEXT NOT NULL REFERENCES facts(id),
        version INTEGER NOT NULL, snapshot TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(fact_id,version))''',
    '''CREATE TABLE rule_versions(id TEXT PRIMARY KEY, rule_id TEXT NOT NULL, version TEXT NOT NULL,
        stages TEXT NOT NULL, applies_to TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
        priority INTEGER NOT NULL, enabled INTEGER NOT NULL, source TEXT NOT NULL, hash TEXT NOT NULL,
        created TEXT NOT NULL, UNIQUE(rule_id,version))''',
    '''CREATE TABLE chat_threads(id TEXT PRIMARY KEY, title TEXT NOT NULL, created TEXT NOT NULL)''',
    '''CREATE TABLE messages(id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES chat_threads(id),
        document_id TEXT, stage TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
        task_id TEXT, state TEXT NOT NULL, created TEXT NOT NULL)''',
    '''CREATE TABLE context_manifests(id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
        content TEXT NOT NULL, hash TEXT NOT NULL, created TEXT NOT NULL)''',
    '''CREATE TABLE cache_entries(id TEXT PRIMARY KEY, cache_key TEXT NOT NULL UNIQUE, stage TEXT NOT NULL,
        dependencies TEXT NOT NULL, result TEXT NOT NULL, stale INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL)''',
)


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class ConflictError(RuntimeError):
    pass


class LockedError(RuntimeError):
    pass


class ProjectStore:
    """Short-lived connections: every write is one transaction with version checks."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / 'project.sqlite'

    @contextmanager
    def connection(self, write=False):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            if write:
                connection.execute('BEGIN IMMEDIATE')
            yield connection
            if write:
                connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @classmethod
    def create(cls, root: Path, name: str, kind: str):
        if not name.strip() or kind not in {'小说', '剧本', '文案'}:
            raise ValueError('请填写项目名称并选择作品类型')
        root.mkdir(parents=True, exist_ok=False)
        for folder in ('assets', 'exports', 'backups'):
            (root / folder).mkdir()
        store = cls(root)
        with store.connection(write=True) as con:
            con.executescript('''
                CREATE TABLE project(id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active', created TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE documents(id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL,
                    position INTEGER NOT NULL, head TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
                    deleted INTEGER NOT NULL DEFAULT 0, source_id TEXT);
                CREATE TABLE revisions(id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
                    text TEXT NOT NULL, blocks TEXT NOT NULL, reason TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE locks(id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
                    text TEXT NOT NULL, hash TEXT NOT NULL, ordinal INTEGER NOT NULL);
                CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE assets(id TEXT PRIMARY KEY, relative TEXT NOT NULL UNIQUE, hash TEXT NOT NULL,
                    media_type TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE covers(id TEXT PRIMARY KEY, spec TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE annotations(id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
                    block_id TEXT NOT NULL, text TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE patches(id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
                    base_revision TEXT NOT NULL, expected_hash TEXT NOT NULL, replacement TEXT NOT NULL,
                    state TEXT NOT NULL, source_task_id TEXT, created TEXT NOT NULL);
                PRAGMA user_version=1;
            ''')
            con.execute('INSERT INTO project VALUES(?,?,?,?,?,?)', (new_id(), name.strip(), kind, 'active', now(), now()))
        store.add_document('第一章' if kind == '小说' else '正文', kind=kind)
        store._upgrade()
        return store

    def _upgrade(self):
        with self.connection() as con:
            version = con.execute('PRAGMA user_version').fetchone()[0]
        if version == 1:
            backup = self.root / 'backups' / ('升级前_v1_' + new_id() + '.sqlite')
            self.backup_database(backup)
            with self.connection(write=True) as con:
                for statement in TASK_DDL:
                    con.execute(statement)
                con.execute('ALTER TABLE patches ADD COLUMN block_id TEXT')
                con.execute('ALTER TABLE patches ADD COLUMN checks TEXT')
                con.execute('PRAGMA user_version=2')
            version = 2
        if version == 2:
            backup = self.root / 'backups' / ('升级前_v2_' + new_id() + '.sqlite')
            self.backup_database(backup)
            with self.connection(write=True) as con:
                for statement in CONTEXT_DDL:
                    con.execute(statement)
                for did, position in con.execute('SELECT id,position FROM documents').fetchall():
                    con.execute('INSERT OR IGNORE INTO settings VALUES(?,?)', ('timeline:' + did, json.dumps(position + 1)))
                con.execute('PRAGMA user_version=3')
            version = 3
        if version == 3:
            backup = self.root / 'backups' / ('升级前_v3_' + new_id() + '.sqlite')
            self.backup_database(backup)
            with self.connection(write=True) as con:
                con.execute('''CREATE TABLE image_jobs(task_id TEXT PRIMARY KEY REFERENCES tasks(id), job_id TEXT,
                    state TEXT NOT NULL, private_result TEXT, asset_ids TEXT NOT NULL, updated TEXT NOT NULL)''')
                con.execute('PRAGMA user_version=4')
            version = 4
        if version == 4:
            backup = self.root / 'backups' / ('升级前_v4_' + new_id() + '.sqlite')
            self.backup_database(backup)
            with self.connection(write=True) as con:
                con.execute('''CREATE TABLE document_payloads(revision_id TEXT PRIMARY KEY REFERENCES revisions(id),
                    stage TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL)''')
                con.execute('''CREATE TABLE planning_items(id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
                    payload TEXT NOT NULL, state TEXT NOT NULL, source_document_id TEXT, source_revision TEXT,
                    source_task_id TEXT, created TEXT NOT NULL, updated TEXT NOT NULL)''')
                con.execute('''CREATE TABLE dialogue_locks(id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
                    block_id TEXT NOT NULL, speaker_id TEXT NOT NULL, text TEXT NOT NULL, ordinal INTEGER NOT NULL,
                    order_locked INTEGER NOT NULL, created TEXT NOT NULL, UNIQUE(document_id,block_id))''')
                con.execute('PRAGMA user_version=5')
            version=5
        if version == 5:
            backup=self.root/'backups'/('升级前_v5_'+new_id()+'.sqlite')
            self.backup_database(backup)
            with self.connection(write=True) as con:
                con.execute('''CREATE TABLE task_leases(task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
                    token TEXT NOT NULL,pid INTEGER NOT NULL,process_started TEXT,operation TEXT NOT NULL,
                    active INTEGER NOT NULL,started TEXT NOT NULL)''')
                con.execute('PRAGMA user_version=6')

    def check(self):
        if not self.path.is_file():
            raise ValueError('目录中没有项目数据库')
        self._upgrade()
        with self.connection() as con:
            version = con.execute('PRAGMA user_version').fetchone()[0]
            if version != SCHEMA_VERSION:
                raise ValueError(f'项目数据版本 {version} 不受当前开发版支持')
            if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('项目数据库完整性检查失败')
            if con.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('项目数据引用损坏')
            if con.execute('SELECT COUNT(*) FROM project').fetchone()[0] != 1:
                raise ValueError('项目身份信息损坏')

    def metadata(self) -> dict:
        with self.connection() as con:
            return dict(con.execute('SELECT * FROM project').fetchone())

    def documents(self, deleted=False) -> list[dict]:
        with self.connection() as con:
            return [dict(row) for row in con.execute('SELECT * FROM documents WHERE deleted=? ORDER BY position,id', (int(deleted),))]

    def document(self, document_id: str) -> dict:
        with self.connection() as con:
            row = con.execute('SELECT d.*,r.text,r.blocks FROM documents d JOIN revisions r ON r.id=d.head WHERE d.id=?', (document_id,)).fetchone()
            if row is None:
                raise ValueError('文档不存在')
            result = dict(row)
            result['blocks'] = json.loads(result['blocks'])
            return result

    @staticmethod
    def _blocks(text: str, previous: list[dict]) -> list[dict]:
        lines = text.split('\n')
        old = [item['text'] for item in previous]
        identities = {}
        for tag, a, b, c, d in SequenceMatcher(None, old, lines, autojunk=False).get_opcodes():
            if tag in {'equal', 'replace'}:
                for x, y in zip(range(a, b), range(c, d)):
                    identities[y] = previous[x]['block_id']
        return [dict(block_id=identities.get(i, new_id()), order=i, text=line, kind='paragraph') for i, line in enumerate(lines)]

    def add_document(self, title: str, text='', kind='小说', source_id=None) -> str:
        if not title.strip():
            raise ValueError('文档标题不能为空')
        did, rid = new_id(), new_id()
        with self.connection(write=True) as con:
            position = con.execute('SELECT COALESCE(MAX(position),-1)+1 FROM documents').fetchone()[0]
            con.execute('INSERT INTO documents(id,title,kind,position,head,source_id) VALUES(?,?,?,?,?,?)', (did, title.strip(), kind, position, rid, source_id))
            con.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)', (rid, did, text, json.dumps(self._blocks(text, []), ensure_ascii=False), '新建或导入', now()))
            con.execute('UPDATE project SET updated=?', (now(),))
            version = con.execute('PRAGMA user_version').fetchone()[0]
            if version >= 3:
                con.execute('INSERT INTO settings VALUES(?,?)', ('timeline:' + did, json.dumps(position + 1)))
        return did

    def save_document(self, did: str, base: str, text: str, reason='编辑保存', *, status=None, _connection=None, _structured=None) -> str:
        with (nullcontext(_connection) if _connection is not None else self.connection(write=True)) as con:
            row = con.execute('SELECT d.*,r.text,r.blocks FROM documents d JOIN revisions r ON r.id=d.head WHERE d.id=?', (did,)).fetchone()
            if row is None or row['head'] != base:
                raise ConflictError('原稿已被另一个窗口修改，未覆盖磁盘版本；请另存草稿后重新打开')
            if row['kind'] == 'reference':
                raise LockedError('来源稿只读，请创建新稿')
            locks = list(con.execute('SELECT id,text,ordinal FROM locks WHERE document_id=? ORDER BY ordinal', (did,)))
            opcodes = SequenceMatcher(None, row['text'], text, autojunk=False).get_opcodes() if locks else []
            remapped = []
            for lock in locks:
                start, end = lock['ordinal'], lock['ordinal'] + len(lock['text'])
                match = next(((a, c) for tag, a, b, c, d in opcodes if tag == 'equal' and a <= start and b >= end), None)
                if match is None:
                    raise LockedError('锁定文字被修改或移除，尚未写入；请撤销修改或明确解锁')
                remapped.append((match[1] + start - match[0], lock['id']))
            if text == row['text'] and (status is None or status == row['status']):
                return base
            payload = None
            if con.execute('PRAGMA user_version').fetchone()[0] >= 5:
                prior = con.execute('SELECT stage,payload FROM document_payloads WHERE revision_id=?', (base,)).fetchone()
                if _structured:
                    payload = _structured
                elif prior:
                    from app.core.writing import WritingService
                    service = WritingService(self)
                    old = dict(stage=prior['stage'], data=json.loads(prior['payload']))
                    payload = (old['stage'], old['data'] if text == row['text'] else service.parse_manual(did, text, old))
                if payload and payload[0] == 'screenplay_generate':
                    from app.core import stages
                    from app.core.knowledge import FactService
                    from app.core.writing import WritingService
                    stages.validate('screenplay_generate', payload[1], dict(entities=FactService(self).entities(),
                        dialogue_locks=WritingService(self).dialogue_locks(did)), text)
            rid = new_id()
            blocks = self._blocks(text, json.loads(row['blocks']))
            con.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)', (rid, did, text, json.dumps(blocks, ensure_ascii=False), reason, now()))
            con.execute('UPDATE documents SET head=?,status=? WHERE id=?', (rid, status or 'draft', did))
            if con.execute('PRAGMA user_version').fetchone()[0] >= 3:
                from app.core.context import CacheService
                CacheService(self).invalidate_document(did, con)
            for offset, lock_id in remapped:
                con.execute('UPDATE locks SET ordinal=? WHERE id=?', (offset, lock_id))
            con.execute('UPDATE project SET updated=?', (now(),))
            if payload:
                from app.core.writing import WritingService
                WritingService(self).store_payload(did, rid, payload[0], payload[1], con)
            return rid

    def revisions(self, did: str) -> list[dict]:
        with self.connection() as con:
            return [dict(row) for row in con.execute('SELECT * FROM revisions WHERE document_id=? ORDER BY rowid DESC', (did,))]

    def restore_revision(self, did: str, rid: str, base: str) -> str:
        with self.connection() as con:
            row = con.execute('SELECT text FROM revisions WHERE id=? AND document_id=?', (rid, did)).fetchone()
        if not row:
            raise ValueError('版本不存在')
        payload = None
        with self.connection() as con:
            if con.execute('PRAGMA user_version').fetchone()[0] >= 5:
                structured = con.execute('SELECT stage,payload FROM document_payloads WHERE revision_id=?', (rid,)).fetchone()
                if structured:
                    payload = structured['stage'], json.loads(structured['payload'])
        return self.save_document(did, base, row['text'], '恢复历史版本', _structured=payload)

    def rename_document(self, did: str, title: str):
        if not title.strip():
            raise ValueError('标题不能为空')
        with self.connection(write=True) as con:
            con.execute('UPDATE documents SET title=? WHERE id=?', (title.strip(), did))

    def reorder(self, ids: list[str]):
        with self.connection(write=True) as con:
            current = {row[0] for row in con.execute('SELECT id FROM documents WHERE deleted=0')}
            if len(ids) != len(set(ids)) or set(ids) != current:
                raise ValueError('目录排序包含重复或无效节点')
            for position, did in enumerate(ids):
                con.execute('UPDATE documents SET position=? WHERE id=?', (position, did))

    def trash_document(self, did: str, restore=False):
        with self.connection(write=True) as con:
            con.execute('UPDATE documents SET deleted=? WHERE id=?', (0 if restore else 1, did))

    def update_project(self, *, name=None, status=None):
        with self.connection(write=True) as con:
            if name is not None:
                if not name.strip():
                    raise ValueError('项目名不能为空')
                con.execute('UPDATE project SET name=?,updated=?', (name.strip(), now()))
            if status is not None:
                if status not in {'active', 'archived', 'trash'}:
                    raise ValueError('无效项目状态')
                con.execute('UPDATE project SET status=?,updated=?', (status, now()))

    def setting(self, key: str, default=None):
        with self.connection() as con:
            row = con.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value):
        with self.connection(write=True) as con:
            con.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, json.dumps(value, ensure_ascii=False)))

    def lock(self, did: str, text: str, start: int):
        document = self.document(did)
        if not text or document['text'][start:start + len(text)] != text:
            raise ValueError('请先保存，再选择需要锁定的文字')
        with self.connection(write=True) as con:
            con.execute('INSERT INTO locks VALUES(?,?,?,?,?)', (new_id(), did, text, digest(text), start))

    def locks(self, did: str) -> list[dict]:
        with self.connection() as con:
            return [dict(row) for row in con.execute('SELECT * FROM locks WHERE document_id=? ORDER BY ordinal', (did,))]

    def unlock(self, did: str):
        with self.connection(write=True) as con:
            con.execute('DELETE FROM locks WHERE document_id=?', (did,))

    def annotate(self, did: str, block_id: str, text: str):
        if block_id not in {b['block_id'] for b in self.document(did)['blocks']}:
            raise ValueError('批注目标段落不存在')
        with self.connection(write=True) as con:
            con.execute('INSERT INTO annotations VALUES(?,?,?,?,?)', (new_id(), did, block_id, text, now()))

    def annotations(self, did):
        with self.connection() as con:
            return [dict(row) for row in con.execute('SELECT * FROM annotations WHERE document_id=?', (did,))]

    def backup_database(self, destination: Path):
        with self.connection() as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()

    def register_asset(self, relative: str, content_hash: str, media_type='image'):
        with self.connection(write=True) as con:
            row = con.execute('SELECT id FROM assets WHERE hash=?', (content_hash,)).fetchone()
            if row:
                return row[0]
            aid = new_id()
            con.execute('INSERT INTO assets VALUES(?,?,?,?,?)', (aid, relative, content_hash, media_type, now()))
            return aid

    def save_cover(self, spec: dict):
        cid = new_id()
        with self.connection(write=True) as con:
            con.execute('INSERT INTO covers VALUES(?,?,?)', (cid, json.dumps(spec, ensure_ascii=False), now()))
        return cid

    def covers(self):
        with self.connection() as con:
            return [dict(id=row['id'], spec=json.loads(row['spec']), created=row['created']) for row in con.execute('SELECT * FROM covers ORDER BY rowid DESC')]
