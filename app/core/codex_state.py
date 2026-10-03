"""Persist CLI capability/login receipts without copying any login credentials."""
import hashlib
import json
import threading
from pathlib import Path
from app.core.files import write_json
from app.storage.project import now

_lock=threading.RLock()


def _records(root):
    path=Path(root)/'codex_state.json'
    try: return json.loads(path.read_text(encoding='utf-8')).get('records',{})
    except (OSError,ValueError): return {}


def _key(prefix): return hashlib.sha256(json.dumps(prefix,ensure_ascii=False).encode()).hexdigest()


def cached_probe(root,prefix):
    if root is None: return None
    record=_records(root).get(_key(prefix))
    if record and record.get('probe_verified'):
        return {name:record[name] for name in ('prefix','version','features','logged_in')}
    return None


def remember(root,configured_path,probe=None,authenticated=None):
    if root is None: return
    from app.providers.codex_text import command_prefix
    prefix=probe['prefix'] if probe else command_prefix(configured_path)
    with _lock:
        records=_records(root); key=_key(prefix); record=dict(records.get(key,{}))
        record.update(configured_path=configured_path,prefix=prefix,checked_at=now())
        if probe:
            record.update(version=probe['version'],features=probe['features'],probe_verified=True)
            record.setdefault('logged_in',None)
            if probe.get('logged_in') is not None: record['logged_in']=probe['logged_in']
        if authenticated is not None:
            record['logged_in']=bool(authenticated)
            if authenticated: record['last_success_at']=now()
        records[key]=record; write_json(Path(root)/'codex_state.json',dict(version=1,records=records))


def status(root,configured_path):
    for record in reversed(list(_records(root).values())):
        if record.get('configured_path')==configured_path:
            import subprocess
            return dict(available=bool(record.get('probe_verified') or record.get('last_success_at')),authenticated=bool(record.get('logged_in')),version=record.get('version','未记录版本'),command=subprocess.list2cmdline(record['prefix']),source='manual_override' if configured_path else 'merged_path',features=record.get('features',[]),checked_at=record.get('checked_at',''),cached=True)
    return None
