import json
from difflib import SequenceMatcher

from app.core import stages
from app.core.files import digest
from app.core.knowledge import FactService
from app.storage.project import ConflictError, LockedError, new_id, now


class WritingService:
    def __init__(self, store):
        self.store = store

    def payload(self, did, revision=None):
        document = self.store.document(did)
        with self.store.connection() as con:
            row = con.execute('SELECT * FROM document_payloads WHERE revision_id=?', (revision or document['head'],)).fetchone()
        return dict(stage=row['stage'], data=json.loads(row['payload'])) if row else None

    def names(self):
        return {entity['id']: entity['name'] for entity in FactService(self.store).entities()}

    def dialogue_locks(self, did):
        with self.store.connection() as con:
            return [dict(row) for row in con.execute('SELECT * FROM dialogue_locks WHERE document_id=? ORDER BY ordinal', (did,))]

    def lock_dialogue(self, did, block_id, lock_order=True):
        payload = self.payload(did)
        if not payload or payload['stage'] != 'screenplay_generate':
            raise ValueError('当前文档没有已绑定人物的结构化剧本')
        dialogues = [block for scene in payload['data']['scenes'] for block in scene['blocks'] if block['kind'] == 'dialogue']
        block = next((block for block in dialogues if block['block_id'] == block_id), None)
        if not block:
            raise ValueError('台词 ID 不存在')
        with self.store.connection(write=True) as con:
            con.execute('INSERT OR REPLACE INTO dialogue_locks VALUES(?,?,?,?,?,?,?,?)',
                (new_id(), did, block_id, block['speaker_id'], block['text'], dialogues.index(block), int(lock_order), now()))

    def unlock_dialogue(self, did, block_id=None):
        with self.store.connection(write=True) as con:
            if block_id:
                con.execute('DELETE FROM dialogue_locks WHERE document_id=? AND block_id=?', (did, block_id))
            else:
                con.execute('DELETE FROM dialogue_locks WHERE document_id=?', (did,))

    def store_payload(self, did, revision, stage, data, con):
        con.execute('INSERT OR REPLACE INTO document_payloads VALUES(?,?,?,?)', (revision, stage, json.dumps(data, ensure_ascii=False), now()))
        if stage == 'screenplay_generate':
            blocks = []
            for scene in data['scenes']:
                for block in scene['blocks']:
                    blocks.append(dict(block, scene_id=scene['scene_id']))
            con.execute('UPDATE revisions SET blocks=? WHERE id=? AND document_id=?', (json.dumps(blocks, ensure_ascii=False), revision, did))

    def adopt(self, task, new_document=True, title=None):
        if task['state'] != 'completed' or task['stage'] not in stages.WRITING:
            raise ValueError('当前任务不是已完成的作品候选')
        source = self.store.document(task['document_id'])
        snapshot, candidate = task['snapshot'], task['result']['candidate']
        if source['head'] != snapshot['base_revision']:
            raise ConflictError('来源或原稿已变化，请对照后重新生成')
        context = json.loads(snapshot['messages'][1]['content'].split('\n', 1)[1])
        context['entities'] = FactService(self.store).entities()
        context['dialogue_locks'] = self.dialogue_locks(source['id'])
        stages.validate(task['stage'], candidate, context, context['target_text'])
        text = stages.render(task['stage'], candidate, self.names())
        kind = {'prose_generate': '小说', 'screenplay_generate': '剧本', 'copy_generate': '文案'}[task['stage']]
        name = title or candidate.get('title') or source['title'] + ' · 新稿'
        with self.store.connection(write=True) as con:
            current = con.execute('SELECT head FROM documents WHERE id=?', (source['id'],)).fetchone()
            if current['head'] != source['head']:
                raise ConflictError('采纳期间原稿改变，未写入')
            if new_document:
                did, revision = new_id(), new_id()
                position = con.execute('SELECT COALESCE(MAX(position),-1)+1 FROM documents').fetchone()[0]
                con.execute('INSERT INTO documents(id,title,kind,position,head,source_id) VALUES(?,?,?,?,?,?)', (did, name, kind, position, revision, source['id']))
                con.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)', (revision, did, text, json.dumps(self.store._blocks(text, []), ensure_ascii=False), '采用作品候选', now()))
                con.execute('INSERT INTO settings VALUES(?,?)', ('timeline:' + did, json.dumps(FactService(self.store).timeline(source['id']))))
                con.execute('INSERT INTO settings VALUES(?,?)', ('source_revision:' + did, json.dumps(source['head'])))
            else:
                if source['kind'] == 'reference':
                    raise LockedError('来源稿只读，必须作为新文档采用')
                if source['kind'] != kind:
                    raise ValueError('目标稿型不同，请作为新文档，不改原稿类型')
                did = source['id']
                revision = self.store.save_document(did, source['head'], text, '采用结构化作品候选', _connection=con, _structured=(task['stage'], candidate))
            self.store_payload(did, revision, task['stage'], candidate, con)
            if new_document and task['stage'] == 'screenplay_generate':
                dialogues = [b for scene in candidate['scenes'] for b in scene['blocks'] if b['kind'] == 'dialogue']
                for lock in context['dialogue_locks']:
                    ordinal = next(i for i, b in enumerate(dialogues) if b['block_id'] == lock['block_id'])
                    con.execute('INSERT INTO dialogue_locks VALUES(?,?,?,?,?,?,?,?)',
                        (new_id(), did, lock['block_id'], lock['speaker_id'], lock['text'], ordinal, lock['order_locked'], now()))
            con.execute('UPDATE tasks SET state=?,updated=? WHERE id=?', ('accepted', now(), task['id']))
            con.execute('UPDATE project SET updated=?', (now(),))
        return did

    def parse_manual(self, did, text, previous):
        stage, value = previous['stage'], previous['data']
        if stage != 'screenplay_generate':
            if stage == 'copy_generate':
                return dict(value, text=text)
            lines = [line for line in text.split('\n\n') if line.strip()]
            old = value['blocks']
            identities = {}
            for tag, a, b, c, d in SequenceMatcher(None, [v['text'] for v in old], lines, autojunk=False).get_opcodes():
                if tag in {'equal', 'replace'}:
                    for x, y in zip(range(a, b), range(c, d)):
                        identities[y] = old[x]['block_id']
            return dict(value, blocks=[dict(block_id=identities.get(i, new_id()), text=line) for i, line in enumerate(lines)])
        names = self.names()
        reverse = {}
        for eid, name in names.items():
            reverse.setdefault(name, []).append(eid)
        scenes = []
        prior_scenes = value['scenes']
        for line in text.splitlines():
            if not line.strip():
                continue
            if line.startswith('## 场'):
                fields = line.split('｜')
                if len(fields) != 4 or fields[3] not in {'内', '外', '未知'}:
                    raise ValueError('剧本场次标题格式：## 场N｜地点｜时段｜内/外/未知')
                index = len(scenes)
                prior = prior_scenes[index] if index < len(prior_scenes) else None
                scenes.append(dict(scene_id=prior['scene_id'] if prior else new_id(), location=fields[1], time_of_day=fields[2],
                    interior_exterior=fields[3], blocks=[], estimated_seconds=prior['estimated_seconds'] if prior else 0,
                    duration_status='estimated'))
            elif not scenes:
                raise ValueError('结构化剧本的内容应在场次标题之后；原文草稿保留')
            else:
                scene = scenes[-1]
                index = len(scene['blocks'])
                prior_index = len(scenes) - 1
                previous_blocks = prior_scenes[prior_index]['blocks'] if prior_index < len(prior_scenes) else []
                prior = previous_blocks[index] if index < len(previous_blocks) else None
                if line.startswith('[动作] '):
                    block = dict(kind='action', text=line[5:])
                elif '：' in line:
                    speaker, dialogue = line.split('：', 1)
                    if len(reverse.get(speaker, [])) != 1:
                        raise ValueError('对白人物未绑定或同名歧义，请在人物设定中核对：' + speaker)
                    block = dict(kind='dialogue', speaker_id=reverse[speaker][0], text=dialogue)
                else:
                    raise ValueError('动作使用 [动作] 前缀；对白使用已绑定人物：台词。未悄悄丢弃内容')
                block.update(block_id=prior['block_id'] if prior and prior['kind'] == block['kind'] else new_id(), order=index)
                scene['blocks'].append(block)
        config = self.store.setting('duration_estimation', dict(dialogue_chars_per_second=3.5, pause_per_line=.5, action_min_seconds=1.5, scene_change_seconds=1))
        for scene in scenes:
            scene['estimated_seconds'] = estimate_scene(scene, config)
        candidate = dict(value, scenes=scenes)
        stages.validate('screenplay_generate', candidate, dict(entities=FactService(self.store).entities(), dialogue_locks=self.dialogue_locks(did)), text)
        return candidate

    def planning(self, kind=None):
        with self.store.connection() as con:
            rows = con.execute('SELECT * FROM planning_items' + (' WHERE kind=?' if kind else '') + ' ORDER BY rowid DESC', (kind,) if kind else ()).fetchall()
        return [dict(row, payload=json.loads(row['payload'])) for row in rows]

    def adopt_plan(self, task):
        if task['state'] != 'completed' or task['stage'] not in stages.PLANNING:
            raise ValueError('当前不是可确认的规划候选')
        source = self.store.document(task['document_id'])
        if source['head'] != task['snapshot']['base_revision']:
            raise ConflictError('来源已更新，旧规划不能作为当前确认方案')
        pid = new_id()
        title = task['stage'] + ' · ' + source['title']
        with self.store.connection(write=True) as con:
            current = con.execute('SELECT head FROM documents WHERE id=?', (source['id'],)).fetchone()
            if not current or current[0] != source['head']:
                raise ConflictError('确认期间来源已改变，未保存旧规划')
            con.execute('INSERT INTO planning_items VALUES(?,?,?,?,?,?,?,?,?,?)', (pid, task['stage'], title,
                json.dumps(task['result']['candidate'], ensure_ascii=False), 'confirmed', source['id'], source['head'], task['id'], now(), now()))
            if task['stage']=='idea_generate':
                for character in task['result']['candidate'].get('characters',[]):
                    name=character['name'].strip()
                    if not con.execute("SELECT 1 FROM entities WHERE name=? AND kind='character'",(name,)).fetchone():
                        con.execute('INSERT INTO entities VALUES(?,?,?,?)',(new_id(),name,'character',now()))
            con.execute('UPDATE tasks SET state=?,updated=? WHERE id=?', ('accepted', now(), task['id']))
        return pid

    def import_outline_nodes(self, plan_id):
        plan = next((p for p in self.planning() if p['id'] == plan_id), None)
        if not plan or 'nodes' not in plan['payload']:
            raise ValueError('所选方案没有可落实目录的节点')
        stages.validate_nodes(plan['payload']['nodes'])
        mapping = self.store.setting('outline_document_map', {})
        for node in plan['payload']['nodes']:
            key = plan_id + ':' + node['node_id']
            if key not in mapping:
                mapping[key] = self.store.add_document(node['title'], kind=self.store.metadata()['kind'])
                self.store.set_setting('node:' + mapping[key], dict(plan_id=plan_id, node_id=node['node_id'], locked=False,
                    purpose=node['purpose'], events=node['events']))
        self.store.set_setting('outline_document_map', mapping)
        return mapping

    def export_screenplay(self, did, three_parts=True):
        document = self.store.document(did)
        payload = self.payload(did)
        if not payload or payload['stage'] != 'screenplay_generate' or document['status'] != 'confirmed':
            raise ValueError('人物台词本只从已确认的结构化剧本提取')
        data = payload['data']
        body = stages.render('screenplay_generate', data, self.names())
        if not three_parts:
            return body
        duration = sum(scene['estimated_seconds'] for scene in data['scenes'])
        return ('# ' + data['title'] + '\n\n## 一、故事大纲与建议时长\n\n' + data['outline'] +
                f'\n\n预计 {duration:g} 秒（未音频实测）\n\n## 二、完整剧本\n\n' + body +
                '\n\n## 三、完整人物台词\n\n' + stages.render('screenplay_generate', data, self.names(), dialogue_only=True))

    def similarity(self, source_id, target_id):
        source, target = self.store.document(source_id), self.store.document(target_id)
        matches = []
        for block in SequenceMatcher(None, source['text'], target['text'], autojunk=False).get_matching_blocks():
            if block.size >= 12:
                matches.append(dict(source_offset=block.a, target_offset=block.b, text=source['text'][block.a:block.a + min(block.size, 200)]))
        return matches[:50]


def estimate_scene(scene, config):
    import math
    keys = ('dialogue_chars_per_second', 'pause_per_line', 'action_min_seconds', 'scene_change_seconds')
    if any(not isinstance(config.get(k), (int, float)) or isinstance(config[k], bool) or not math.isfinite(config[k]) or config[k] < 0 for k in keys) or config['dialogue_chars_per_second'] <= 0:
        raise ValueError('时长估算参数无效；不使用固定语速伪装音频实测')
    result = config['scene_change_seconds']
    for block in scene['blocks']:
        chars = sum(not c.isspace() for c in block['text'])
        if block['kind'] == 'dialogue':
            result += chars / config['dialogue_chars_per_second'] + config['pause_per_line']
        else:
            result += max(config['action_min_seconds'], chars / (config['dialogue_chars_per_second'] * 2))
    return round(result, 2)
