from __future__ import annotations

import json
from contextlib import nullcontext

from app.storage.project import new_id, now

STATES = {'candidate', 'confirmed', 'disputed', 'invalid'}
ENTITY_KINDS = {'character', 'location', 'product', 'other'}


class FactService:
    def __init__(self, store):
        self.store = store

    def entities(self):
        with self.store.connection() as con:
            return [dict(row) for row in con.execute('SELECT * FROM entities ORDER BY name,id')]

    def add_entity(self, name, kind='character'):
        if not isinstance(name, str) or not name.strip() or len(name) > 100 or kind not in ENTITY_KINDS:
            raise ValueError('对象名称或类型无效')
        eid = new_id()
        with self.store.connection(write=True) as con:
            con.execute('INSERT INTO entities VALUES(?,?,?,?)', (eid, name.strip(), kind, now()))
        return eid

    def facts(self, state=None, entity_id=None, at=None):
        parameters = []
        clauses = []
        if state:
            if state not in STATES:
                raise ValueError('未知事实状态')
            clauses.append('f.state=?')
            parameters.append(state)
        if entity_id:
            clauses.append('f.entity_id=?')
            parameters.append(entity_id)
        if at is not None:
            if not isinstance(at, int) or isinstance(at, bool) or at < 1:
                raise ValueError('剧情位置必须是正整数')
            clauses.append('(f.valid_from IS NULL OR f.valid_from<=?) AND (f.valid_to IS NULL OR f.valid_to>=?)')
            parameters += [at, at]
        where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
        with self.store.connection() as con:
            return [dict(row) for row in con.execute('SELECT f.*,e.name AS entity_name,e.kind AS entity_kind FROM facts f JOIN entities e ON e.id=f.entity_id' + where + ' ORDER BY f.created,f.id', parameters)]

    def get(self, fact_id):
        with self.store.connection() as con:
            row = con.execute('SELECT * FROM facts WHERE id=?', (fact_id,)).fetchone()
        if not row:
            raise ValueError('事实不属于当前项目')
        return dict(row)

    @staticmethod
    def check_interval(valid_from, valid_to):
        for value in (valid_from, valid_to):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
                raise ValueError('有效区间只能是正整数或空值')
        if valid_from is not None and valid_to is not None and valid_from > valid_to:
            raise ValueError('有效区间起点不能大于终点')

    def propose(self, entity_id, content, *, source_document_id=None, source_revision=None, source_block_id=None,
                evidence=None, valid_from=None, valid_to=None, _connection=None):
        self.check_interval(valid_from, valid_to)
        if entity_id not in {e['id'] for e in self.entities()}:
            raise ValueError('对象不属于当前项目')
        if not isinstance(content, str) or not content.strip() or len(content) > 4000:
            raise ValueError('事实内容为空或过长')
        if source_document_id:
            self._validate_source(source_document_id, source_revision, source_block_id, evidence, current=False)
        elif any(value is not None for value in (source_revision, source_block_id, evidence)):
            raise ValueError('来源字段不完整')
        fid = new_id()
        stamp = now()
        row = dict(id=fid, entity_id=entity_id, content=content.strip(), state='candidate',
                   source_document_id=source_document_id, source_revision=source_revision,
                   source_block_id=source_block_id, evidence=evidence, valid_from=valid_from, valid_to=valid_to,
                   version=1, created=stamp, updated=stamp)
        with (nullcontext(_connection) if _connection is not None else self.store.connection(write=True)) as con:
            con.execute('INSERT INTO facts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', tuple(row.values()))
            self._version(con, row)
        return fid

    def _validate_source(self, did, revision, block_id, evidence, current):
        document = self.store.document(did)
        if document['deleted']:
            raise ValueError('事实来源已进入回收区')
        if not revision or not block_id or not isinstance(evidence, str) or not evidence:
            raise ValueError('模型事实必须附原文版本、段落 ID 和逐字证据')
        if current and document['head'] != revision:
            raise ValueError('事实来源版本已变化，请重新核对依据再确认')
        with self.store.connection() as con:
            row = con.execute('SELECT blocks FROM revisions WHERE id=? AND document_id=?', (revision, did)).fetchone()
        if not row:
            raise ValueError('来源版本不属于当前文档')
        block = next((b for b in json.loads(row['blocks']) if b['block_id'] == block_id), None)
        if not block or evidence not in block['text']:
            raise ValueError('事实证据不能定位到来源段落')

    @staticmethod
    def _version(con, row):
        con.execute('INSERT INTO fact_versions VALUES(?,?,?,?,?)', (new_id(), row['id'], row['version'], json.dumps(row, ensure_ascii=False), now()))

    def set_state(self, fact_id, state):
        if state not in STATES:
            raise ValueError('未知事实状态')
        old = self.get(fact_id)
        if state == 'confirmed' and old['source_document_id']:
            self._validate_source(old['source_document_id'], old['source_revision'], old['source_block_id'], old['evidence'], current=True)
        if state == old['state']:
            return
        row = dict(old, state=state, version=old['version'] + 1, updated=now())
        with self.store.connection(write=True) as con:
            current = con.execute('SELECT version FROM facts WHERE id=?', (fact_id,)).fetchone()
            if not current or current[0] != old['version']:
                raise ValueError('事实已被另一操作修改，请重新打开')
            con.execute('UPDATE facts SET state=?,version=?,updated=? WHERE id=?', (state, row['version'], row['updated'], fact_id))
            self._version(con, row)
            # Derived results are marked stale locally; no automatic model rebuild.
            for cached in con.execute('SELECT id,dependencies FROM cache_entries WHERE stale=0').fetchall():
                dependencies = json.loads(cached['dependencies'])
                if 'fact:' + fact_id in dependencies:
                    con.execute('UPDATE cache_entries SET stale=1 WHERE id=?', (cached['id'],))

    def revise(self, fact_id, content, valid_from=None, valid_to=None):
        self.check_interval(valid_from, valid_to)
        if not isinstance(content, str) or not content.strip() or len(content) > 4000:
            raise ValueError('事实内容为空或过长')
        old = self.get(fact_id)
        row = dict(old, content=content.strip(), state='candidate', valid_from=valid_from, valid_to=valid_to,
                   source_document_id=None, source_revision=None, source_block_id=None, evidence=None,
                   version=old['version'] + 1, updated=now())
        with self.store.connection(write=True) as con:
            version = con.execute('SELECT version FROM facts WHERE id=?', (fact_id,)).fetchone()[0]
            if version != old['version']:
                raise ValueError('事实已被其他操作修改，请重新打开')
            con.execute('UPDATE facts SET content=?,state=?,valid_from=?,valid_to=?,source_document_id=NULL,source_revision=NULL,source_block_id=NULL,evidence=NULL,version=?,updated=? WHERE id=?',
                (row['content'], 'candidate', valid_from, valid_to, row['version'], row['updated'], fact_id))
            self._version(con, row)
            for cached in con.execute('SELECT id,dependencies FROM cache_entries WHERE stale=0').fetchall():
                if 'fact:' + fact_id in json.loads(cached['dependencies']):
                    con.execute('UPDATE cache_entries SET stale=1 WHERE id=?', (cached['id'],))

    def timeline(self, document_id):
        document = self.store.document(document_id)
        return self.store.setting('timeline:' + document_id, document['position'] + 1)

    def set_timeline(self, document_id, position):
        self.store.document(document_id)
        if not isinstance(position, int) or isinstance(position, bool) or position < 1:
            raise ValueError('剧情位置必须是正整数')
        self.store.set_setting('timeline:' + document_id, position)

    def active(self, document_id):
        return self.facts('confirmed', at=self.timeline(document_id))

    def versions(self, fact_id):
        self.get(fact_id)
        with self.store.connection() as con:
            return [json.loads(row[0]) for row in con.execute('SELECT snapshot FROM fact_versions WHERE fact_id=? ORDER BY version', (fact_id,))]
