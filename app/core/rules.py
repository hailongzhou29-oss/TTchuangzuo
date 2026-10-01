from __future__ import annotations

import json
import re

from app.core.files import digest
from app.core.services import RuleService
from app.storage.project import new_id, now

STAGES = {'discussion', 'idea_generate', 'outline_generate', 'prose_generate', 'screenplay_generate', 'copy_generate',
          'reference_analyze', 'rewrite_plan', 'adaptation_plan', 'draft_patch', 'fact_extract', 'chapter_summary',
          'review_draft', 'cover_plan', 'image_generate'}
KINDS = {'小说', '剧本', '文案', 'reference'}


class ProjectRules:
    def __init__(self, store, resources):
        self.store, self.resources = store, resources

    def base(self):
        base = RuleService(self.resources).rules()
        from app.core.creator import track_rules
        base.extend(track_rules(self.resources))
        path = self.resources / 'track_rules.json'
        if path.is_file():
            for rule in json.loads(path.read_text(encoding='utf-8')):
                if digest(rule['body']) != rule['hash']:
                    raise ValueError('细分规则正文哈希不符')
                base.append(rule)
        path = self.resources / 'track_catalogue.json'
        if path.is_file():
            for index, entry in enumerate(json.loads(path.read_text(encoding='utf-8')), 1):
                body = '基础创作建议：' + entry['constraint'] + '\n完整细分规则尚未配置，不把本条当作完整规则库或统计结论。'
                base.append(dict(rule_id=f'CAT_{index:02}', title=entry['name'] + '（基础建议）', version='1.1', body=body,
                                 hash=digest(body), source='交接书第45章；完整细分待补', status=entry['status']))
        return base

    def rules(self):
        records = {r['rule_id']: dict(r, stages=r.get('stages',[]), applies_to=r.get('applies_to',[]), priority=r.get('priority',50), enabled=True) for r in self.base()}
        with self.store.connection() as con:
            overrides = con.execute('SELECT * FROM rule_versions ORDER BY rowid').fetchall()
        for row in overrides:
            value = dict(row)
            value['stages'], value['applies_to'] = json.loads(value['stages']), json.loads(value['applies_to'])
            value['enabled'] = bool(value['enabled'])
            records[value['rule_id']] = value
        return sorted(records.values(), key=lambda r: (r['priority'], r['rule_id']))

    @staticmethod
    def validate(rule):
        keys = {'rule_id', 'version', 'stages', 'applies_to', 'title', 'body', 'priority', 'enabled', 'source'}
        if not isinstance(rule, dict) or set(rule) != keys:
            raise ValueError('规则字段不完整或含未知/脚本字段')
        for key in ('rule_id', 'version', 'title', 'body', 'source'):
            if not isinstance(rule[key], str) or not rule[key].strip():
                raise ValueError('规则文字字段不能为空')
        if not re.fullmatch(r'[A-Z][A-Z0-9_]{1,63}', rule['rule_id']):
            raise ValueError('规则 ID 格式无效')
        if len(rule['body']) > 100_000 or len(rule['version']) > 100 or len(rule['title']) > 200:
            raise ValueError('规则内容过长')
        if not isinstance(rule['priority'], int) or isinstance(rule['priority'], bool) or not 1 <= rule['priority'] <= 100:
            raise ValueError('规则优先级应为 1—100')
        if not isinstance(rule['enabled'], bool):
            raise ValueError('规则启用状态应为布尔值')
        for key, allowed in [('stages', STAGES), ('applies_to', KINDS)]:
            if not isinstance(rule[key], list) or len(rule[key]) != len(set(rule[key])) or any(item not in allowed for item in rule[key]):
                raise ValueError('规则阶段或形式声明无效')
        return dict(rule, hash=digest(rule['body']))

    def preview_package(self, data):
        if not isinstance(data, dict) or set(data) != {'schema_version', 'rules'} or data['schema_version'] != 1:
            raise ValueError('规则包只接受 schema_version=1 和 rules 列表')
        if not isinstance(data['rules'], list) or not 1 <= len(data['rules']) <= 200:
            raise ValueError('规则包应含 1—200 条规则')
        parsed = [self.validate(rule) for rule in data['rules']]
        if len({r['rule_id'] for r in parsed}) != len(parsed):
            raise ValueError('规则包含重复 ID')
        current = {r['rule_id']: r for r in self.rules()}
        return [dict(rule=rule, previous=current.get(rule['rule_id']), change='覆盖' if rule['rule_id'] in current else '新增') for rule in parsed]

    def import_package(self, data):
        preview = self.preview_package(data)
        with self.store.connection(write=True) as con:
            for item in preview:
                rule = item['rule']
                existing = con.execute('SELECT * FROM rule_versions WHERE rule_id=? AND version=?', (rule['rule_id'], rule['version'])).fetchone()
                if existing:
                    comparable = {key: existing[key] for key in rule if key in existing.keys()}
                    comparable['stages'] = json.loads(existing['stages'])
                    comparable['applies_to'] = json.loads(existing['applies_to'])
                    comparable['enabled'] = bool(existing['enabled'])
                    if comparable != rule:
                        raise ValueError('同一规则版本内容不一致，请使用新版本号')
                    continue
                con.execute('INSERT INTO rule_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (new_id(), rule['rule_id'], rule['version'], json.dumps(rule['stages']), json.dumps(rule['applies_to'], ensure_ascii=False),
                     rule['title'], rule['body'], rule['priority'], int(rule['enabled']), rule['source'], rule['hash'], now()))
                for cached in con.execute('SELECT id,dependencies FROM cache_entries WHERE stale=0').fetchall():
                    if 'rule:' + rule['rule_id'] in json.loads(cached['dependencies']):
                        con.execute('UPDATE cache_entries SET stale=1 WHERE id=?', (cached['id'],))
        return len(preview)

    def restore_base(self, rule_id):
        base = next((rule for rule in self.base() if rule['rule_id'] == rule_id), None)
        if not base:
            raise ValueError('自定义规则没有内置版本，请禁用或导入旧版本')
        rule = {key: base[key] for key in ('rule_id', 'title', 'body', 'source')}
        rule.update(version='restore-' + new_id()[:12], stages=[], applies_to=[], priority=50, enabled=True)
        self.import_package(dict(schema_version=1, rules=[rule]))

    def selected(self, stage, kind):
        ids = {'G01'}
        if stage in {'draft_patch', 'prose_generate', 'screenplay_generate', 'copy_generate'}:
            effective = {'screenplay_generate': '剧本', 'prose_generate': '小说', 'copy_generate': '文案'}.get(stage, kind)
            ids.add({'小说': 'G02', '剧本': 'G03', '文案': 'G04'}.get(effective, 'G02'))
        if stage in {'idea_generate', 'outline_generate'}:
            ids.add({'小说': 'G02', '剧本': 'G03', '文案': 'G04'}.get(kind, 'G02'))
        if stage in {'reference_analyze', 'rewrite_plan'}:
            ids.add('G05')
        if stage == 'adaptation_plan':
            ids.add('G06')
        if stage == 'draft_patch':
            ids.add('G09')
        if stage == 'review_draft':
            ids.add('G07')
        if stage in {'fact_extract', 'chapter_summary'}:
            ids.add('G08')
        if stage in {'cover_plan', 'image_generate'}:
            ids |= {'G10', {'小说': 'G11', '剧本': 'G12', '文案': 'G13'}.get(kind, 'G10')}
        active = self.store.setting('active_rule_ids', [])
        if not isinstance(active, list) or any(not isinstance(item, str) for item in active):
            raise ValueError('项目选用规则清单无效')
        ids.update(active)
        return [rule for rule in self.rules() if rule['enabled'] and (rule['rule_id'] in ids or
                (rule['stages'] and stage in rule['stages'])) and (not rule['applies_to'] or kind in rule['applies_to'])]
