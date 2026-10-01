from __future__ import annotations

import json

from app.core.files import digest
from app.storage.project import new_id, now


class ChatService:
    def __init__(self, store):
        self.store = store

    def current(self):
        thread = self.store.setting('chat_thread')
        with self.store.connection() as con:
            exists = con.execute('SELECT id FROM chat_threads WHERE id=?', (thread,)).fetchone() if thread else None
        return thread if exists else self.new()

    def new(self, title='创作讨论'):
        thread = new_id()
        with self.store.connection(write=True) as con:
            con.execute('INSERT INTO chat_threads VALUES(?,?,?)', (thread, title, now()))
            con.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('chat_thread', json.dumps(thread)))
        return thread

    def append(self, thread, document_id, stage, role, content, task_id, state, protocol=None):
        if role not in {'user', 'assistant'} or not isinstance(content, str):
            raise ValueError('会话消息格式无效')
        if protocol:
            content = json.dumps(dict(format='tt-chat-message-1', text=content, protocol=protocol), ensure_ascii=False)
        with self.store.connection(write=True) as con:
            con.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?)', (new_id(), thread, document_id, stage, role, content, task_id, state, now()))

    def recent(self, thread, document_id, stage, limit=6):
        with self.store.connection() as con:
            rows = con.execute('SELECT * FROM messages WHERE thread_id=? AND document_id=? AND stage=? ORDER BY rowid DESC LIMIT ?',
                               (thread, document_id, stage, limit)).fetchall()
        result = []
        for row in reversed(rows):
            value = dict(row)
            if value['role'] == 'assistant':
                try:
                    data = json.loads(value['content'])
                    if isinstance(data, dict) and data.get('format') == 'tt-chat-message-1':
                        value['content'], value['protocol'] = data['text'], data['protocol']
                except (ValueError, KeyError):
                    pass
            result.append(value)
        return result


class CacheService:
    """Explicit opt-in reuse for derived analyses; never cache a new creative variant."""
    REUSABLE = {'chapter_summary', 'reference_analyze'}

    def __init__(self, store):
        self.store = store

    def key(self, snapshot):
        fields = ('project_id', 'stage', 'target_id', 'base_revision', 'instruction', 'selected_text',
                  'confirmed_facts', 'rule_snapshot_id', 'model_selection', 'constraints', 'messages', 'development_test')
        return digest(json.dumps({key: snapshot.get(key) for key in fields}, ensure_ascii=False, sort_keys=True))

    def get(self, snapshot):
        if snapshot['stage'] not in self.REUSABLE or not snapshot.get('allow_reuse') or snapshot.get('variant_id'):
            return None
        with self.store.connection() as con:
            row = con.execute('SELECT result FROM cache_entries WHERE cache_key=? AND stale=0', (self.key(snapshot),)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, snapshot, result):
        if snapshot['stage'] not in self.REUSABLE or not snapshot.get('allow_reuse') or snapshot.get('variant_id'):
            return
        dependencies = ['document:' + snapshot['target_id']] + ['fact:' + f['id'] for f in snapshot.get('confirmed_facts', [])]
        dependencies += ['document:' + entry['document_id'] for entry in snapshot.get('reference_snapshot', [])]
        dependencies += ['rule:' + r['rule_id'] for r in snapshot['rule_snapshot']]
        with self.store.connection(write=True) as con:
            con.execute('INSERT OR REPLACE INTO cache_entries VALUES(?,?,?,?,?,?,?)',
                (new_id(), self.key(snapshot), snapshot['stage'], json.dumps(dependencies), json.dumps(result, ensure_ascii=False), 0, now()))

    def invalidate_document(self, did, con):
        for row in con.execute('SELECT id,dependencies FROM cache_entries WHERE stale=0').fetchall():
            if 'document:' + did in json.loads(row['dependencies']):
                con.execute('UPDATE cache_entries SET stale=1 WHERE id=?', (row['id'],))

    def clear(self):
        with self.store.connection(write=True) as con:
            count = con.execute('SELECT COUNT(*) FROM cache_entries').fetchone()[0]
            con.execute('DELETE FROM cache_entries')
        return count
