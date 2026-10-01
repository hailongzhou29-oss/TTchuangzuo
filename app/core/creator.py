"""Creator-facing channels and rules; no model calls happen during selection."""
import json
from app.core.files import digest

def tracks(resources,kind=None):
    rows=json.loads((resources/'creator_tracks.json').read_text(encoding='utf-8'))
    return [row for row in rows if kind is None or row['kind']==kind]

def select_track(store,track):
    constraints=store.setting('creation_constraints',{})
    constraints.update(primary_genre=track['name'],creator_track_id=track['id'])
    store.set_setting('creation_constraints',constraints)
    active=[rid for rid in store.setting('active_rule_ids',[]) if not rid.startswith('CR_')]
    store.set_setting('active_rule_ids',active+[track['id']])
    store.set_setting('creator_flow','ai_first')

def track_rules(resources):
    return [dict(rule_id=row['id'],title=row['name']+'核心创作规则',version='1.2',body=row['body'],
                 hash=digest(row['body']),source='TT创作助手核心赛道规则',status='核心创作规则',
                 stages=[],applies_to=[row['kind']],priority=60,enabled=True) for row in tracks(resources)]
