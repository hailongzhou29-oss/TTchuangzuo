from __future__ import annotations

import json

from app.core.files import digest
from app.core.knowledge import FactService
from app.core.rules import ProjectRules


def schema(name, description, properties, required=()):
    return dict(type='function', function=dict(name=name, description=description,
        parameters=dict(type='object', properties=properties, required=list(required), additionalProperties=False)))


TOOL_SCHEMAS = [
    schema('search_project', '只在当前项目允许的剧情范围检索文字，返回来源 ID。', {'query': {'type': 'string'}}, ['query']),
    schema('read_document', '分页读取允许范围的文档版本，has_more为真时用next_cursor继续。', {'document_id': {'type': 'string'},'block_start':{'type':'integer'},'block_limit':{'type':'integer'}}, ['document_id']),
    schema('read_facts', '只读取当前剧情位置的已确认事实，争议项单独列出。', {'entity_id': {'type': 'string'}}),
    schema('read_rules', '读取当前任务已加载的规则快照。', {'rule_id': {'type': 'string'}}, ['rule_id']),
    schema('propose_patch', '只生成原文当前范围的修改提案，不写入正文。', {
        'block_id': {'type': 'string'}, 'expected_text_hash': {'type': 'string'}, 'replacement': {'type': 'string'},
        'start': {'type': 'integer'}, 'end': {'type': 'integer'}}, ['block_id', 'expected_text_hash', 'replacement', 'start', 'end']),
    schema('propose_fact', '保存有原文证据的候选事实，不能确认为正式设定。', {
        'entity_id': {'type': 'string'}, 'content': {'type': 'string'}, 'block_id': {'type': 'string'},
        'evidence': {'type': 'string'}, 'valid_from': {'type': ['integer', 'null']}, 'valid_to': {'type': ['integer', 'null']}},
        ['entity_id', 'content', 'block_id', 'evidence', 'valid_from', 'valid_to']),
    schema('validate_draft', '确定性检查本次原文和文字锁，不自动改写。', {}),
]


def check_arguments(spec, arguments):
    if not isinstance(arguments, dict):
        raise ValueError('工具参数必须是 JSON 对象')
    properties = spec['properties']
    if set(arguments) - set(properties) or set(spec['required']) - set(arguments):
        raise ValueError('工具含未知参数或缺少必需字段')
    for key, value in arguments.items():
        types = properties[key]['type']
        if isinstance(types, str):
            types = [types]
        matches = ((value is None and 'null' in types) or (isinstance(value, str) and 'string' in types) or
                   (isinstance(value, int) and not isinstance(value, bool) and 'integer' in types))
        if not matches:
            raise ValueError('工具参数类型无效：' + key)


class ProjectTools:
    def __init__(self, store, resources, snapshot):
        self.store, self.resources, self.snapshot = store, resources, snapshot
        self.facts = FactService(store)
        self.allowed = {snapshot['target_id']}
        self.allowed.update(snapshot.get('reference_ids', []))
        at = snapshot.get('timeline_position', self.facts.timeline(snapshot['target_id']))
        self.manifest = {entry['document_id']: entry['revision'] for entry in snapshot.get('document_manifest', [])}
        self.allowed.update(self.manifest)
        self.proposals = []
        self.fact_ids = []

    def schemas(self):
        if self.snapshot.get('v2_task'):
            allowed={'read_document','search_project','read_facts','read_rules','validate_draft'}
            if self.snapshot['v2_task']=='modify': allowed.add('propose_patch')
            return [s for s in TOOL_SCHEMAS if s['function']['name'] in allowed]
        return TOOL_SCHEMAS

    def execute(self, name, arguments):
        spec = next((item for item in self.schemas() if item['function']['name'] == name), None)
        if not spec:
            raise ValueError('该工具未授权：' + str(name))
        check_arguments(spec['function']['parameters'], arguments)
        method = getattr(self, name)
        value = method(**arguments)
        return dict(material_only=True, tool=name, project_id=self.snapshot['project_id'], result=value)

    def _document(self, document_id):
        if document_id not in self.allowed:
            raise ValueError('文档不在当前项目/剧情位置/已固定资料范围内')
        document = self.store.document(document_id)
        if document['deleted']:
            raise ValueError('文档已进入回收区')
        revision = self.snapshot['base_revision'] if document_id == self.snapshot['target_id'] else self.manifest.get(document_id)
        if revision:
            with self.store.connection() as con:
                row = con.execute('SELECT text,blocks FROM revisions WHERE id=? AND document_id=?',
                    (revision, document_id)).fetchone()
            if not row:
                raise ValueError('冻结的来源版本不可读取')
            document.update(text=row['text'], blocks=json.loads(row['blocks']), head=revision)
        return document

    def read_document(self, document_id, block_start=0, block_limit=30):
        document = self._document(document_id)
        if not 0 <= block_start <= len(document['blocks']) or not 1 <= block_limit <= 100:
            raise ValueError('读取分页范围无效')
        blocks = []
        offset = 0
        total = 0
        for index, block in enumerate(document['blocks']):
            if index < block_start:
                offset += len(block['text']) + 1
                continue
            if len(blocks) == block_limit or blocks and total + len(block['text']) > 12000:
                break
            blocks.append(dict(block, start=offset, end=offset + len(block['text']), hash=digest(block['text'])))
            total += len(block['text'])
            offset += len(block['text']) + 1
        if sum(len(b['text']) for b in blocks) > 12000:
            raise ValueError('资料超过单次工具读取上限，请缩小文档或使用选区')
        cursor=block_start+len(blocks)
        return dict(document_id=document_id, revision=document['head'], title=document['title'], blocks=blocks,
                    truncated=cursor < len(document['blocks']),has_more=cursor < len(document['blocks']),next_cursor=cursor,total_blocks=len(document['blocks']))

    def search_project(self, query):
        if not query.strip() or len(query) > 128:
            raise ValueError('检索文字为空或过长')
        results = []
        # IDs map to authoritative project objects; never interpret query as a path or SQL.
        for did in sorted(self.allowed):
            document = self._document(did)
            found = document['text'].find(query)
            if found >= 0:
                results.append(dict(document_id=did, revision=document['head'], offset=found,
                                    text=document['text'][max(0, found - 100):found + len(query) + 150]))
                if len(results) == 8:
                    break
        return results

    def read_facts(self, entity_id=None):
        at = self.snapshot.get('timeline_position', self.facts.timeline(self.snapshot['target_id']))
        if entity_id and entity_id not in {e['id'] for e in self.facts.entities()}:
            raise ValueError('对象不属于当前项目')
        confirmed = [fact for fact in self.snapshot.get('confirmed_facts', []) if not entity_id or fact['entity_id'] == entity_id]
        disputed = [fact for fact in self.snapshot.get('disputed_facts', []) if not entity_id or fact['entity_id'] == entity_id]
        return dict(at=at, confirmed=confirmed, disputed=disputed)

    def read_rules(self, rule_id):
        rule = next((r for r in self.snapshot['rule_snapshot'] if r['rule_id'] == rule_id), None)
        if not rule:
            raise ValueError('规则不在本次冻结上下文中')
        return rule

    def propose_patch(self, block_id, expected_text_hash, replacement, start, end):
        document = self._document(self.snapshot['target_id'])
        if not isinstance(replacement, str) or not replacement.strip() or len(replacement) > 100_000:
            raise ValueError('替换文字为空或过长')
        if not 0 <= start <= end <= len(document['text']):
            raise ValueError('目标范围无效')
        block_offset = 0
        match = None
        for block in document['blocks']:
            if block['block_id'] == block_id:
                match = (block_offset, block_offset + len(block['text']))
                break
            block_offset += len(block['text']) + 1
        if match is None or not match[0] <= start <= end <= match[1]:
            raise ValueError('目标不在指定段落内')
        selected_start, selected_end = self.snapshot['target_start'], self.snapshot['target_end']
        if selected_start != selected_end and not selected_start <= start <= end <= selected_end:
            raise ValueError('提案超出用户选区')
        if digest(document['text'][start:end]) != expected_text_hash:
            raise ValueError('提案目标哈希不符')
        proposal = dict(block_id=block_id, start=start, end=end, expected_text_hash=expected_text_hash,
                        replacement=replacement, base_revision=self.snapshot['base_revision'], source_task_id=self.snapshot['task_id'])
        if len(self.proposals) >= 20:
            raise ValueError('单次任务修改提案超过 20 条')
        if any(start < p['end'] and end > p['start'] for p in self.proposals):
            raise ValueError('修改提案互相重叠')
        self.proposals.append(proposal)
        return dict(state='proposal_only', proposal=proposal)

    def propose_fact(self, entity_id, content, block_id, evidence, valid_from, valid_to):
        document = self._document(self.snapshot['target_id'])
        scope = self.snapshot['selected_text'] or document['text']
        if evidence not in scope:
            raise ValueError('事实证据超出用户选定的资料范围')
        fid = self.facts.propose(entity_id, content, source_document_id=document['id'], source_revision=document['head'],
            source_block_id=block_id, evidence=evidence, valid_from=valid_from, valid_to=valid_to)
        self.fact_ids.append(fid)
        return dict(fact_id=fid, state='candidate', confirmation_required=True)

    def validate_draft(self):
        document = self._document(self.snapshot['target_id'])
        ids = [b['block_id'] for b in document['blocks']]
        errors = []
        if len(ids) != len(set(ids)):
            errors.append('段落 ID 重复')
        if not document['text'].strip():
            errors.append('正文为空')
        for locked in self.snapshot['locked_content']:
            if locked not in document['text']:
                errors.append('锁定文字缺失')
        return dict(errors=errors, passed=not errors, source_revision=document['head'])
