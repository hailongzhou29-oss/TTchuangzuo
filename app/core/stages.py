"""Shared semantic contracts for HTTP/CLI writing, planning and source analysis."""
import math

STRING = {'type': 'string', 'minLength': 1}
TEXT = {'type': 'string'}
STRINGS = {'type': 'array', 'items': STRING, 'maxItems': 100}


def obj(properties, required=None):
    return dict(type='object', properties=properties, required=list(properties if required is None else required), additionalProperties=False)


def array(item, minimum=0, maximum=200):
    return dict(type='array', items=item, minItems=minimum, maxItems=maximum)


NODE = obj(dict(node_id=STRING, title=STRING, purpose=STRING, events=STRINGS, dependencies=STRINGS))
PROSE_BLOCK = obj(dict(block_id=STRING, text=STRING))
ACTION = obj(dict(block_id=STRING, kind={'type': 'string', 'enum': ['action']}, text=STRING, order={'type': 'integer', 'minimum': 0}))
DIALOGUE = obj(dict(block_id=STRING, kind={'type': 'string', 'enum': ['dialogue']}, speaker_id=STRING, text=STRING,
                    order={'type': 'integer', 'minimum': 0}))
SCENE = obj(dict(scene_id=STRING, location=STRING, time_of_day=STRING,
                 interior_exterior={'type': 'string', 'enum': ['内', '外', '未知']},
                 blocks=array({'oneOf': [ACTION, DIALOGUE]}, 1), estimated_seconds={'type': 'number', 'minimum': 0},
                 duration_status={'type': 'string', 'enum': ['estimated']}))
CARD = obj(dict(card_id=STRING, mechanism={'type': 'string', 'enum': ['hook', 'goal', 'conflict', 'change', 'commercial', 'ending', 'other']},
                observation=STRING, evidence=STRING, source_block_id=STRING))
MAPPING = obj(dict(source_event_id={'type': ['string', 'null']}, target_node_id=STRING,
                   treatment={'type': 'string', 'enum': ['保留', '合并', '新增', '遗漏']}, explanation=TEXT))

SCHEMAS = {
    'idea_generate': obj(dict(premise=STRING, protagonist_goal=STRING, obstacle=STRING, turn=STRING, ending_direction=STRING,
                             characters=array(obj(dict(name=STRING,description=STRING)),0,12)),
                         ['premise','protagonist_goal','obstacle','turn','ending_direction']),
    'outline_generate': obj(dict(nodes=array(NODE, 1))),
    'prose_generate': obj(dict(title=STRING, blocks=array(PROSE_BLOCK, 1))),
    'screenplay_generate': obj(dict(title=STRING, outline=TEXT, scenes=array(SCENE, 1))),
    'copy_generate': obj(dict(title=TEXT, text=STRING, publication_intro=TEXT, source_notes=STRINGS)),
    'reference_analyze': obj(dict(material_basis={'type': 'string', 'enum': ['text_only']}, cards=array(CARD, 1), unknowns=STRINGS)),
    'rewrite_plan': obj(dict(premise=STRING, nodes=array(NODE, 1), difference_notes=STRINGS)),
    'adaptation_plan': obj(dict(target_form={'type': 'string', 'enum': ['小说', '剧本', '文案']}, nodes=array(NODE, 1), mappings=array(MAPPING), warnings=STRINGS)),
}

PLANNING = {'idea_generate', 'outline_generate', 'reference_analyze', 'rewrite_plan', 'adaptation_plan'}
WRITING = {'prose_generate', 'screenplay_generate', 'copy_generate'}


def validate_shape(value, schema, path='result'):
    if 'oneOf' in schema:
        successes = 0
        for option in schema['oneOf']:
            try:
                validate_shape(value, option, path)
                successes += 1
            except ValueError:
                pass
        if successes != 1:
            raise ValueError(path + ' 不符合唯一块类型')
        return
    types = schema.get('type', [])
    if isinstance(types, str):
        types = [types]
    good = ((value is None and 'null' in types) or (isinstance(value, str) and 'string' in types) or
            (isinstance(value, list) and 'array' in types) or (isinstance(value, dict) and 'object' in types) or
            (isinstance(value, int) and not isinstance(value, bool) and 'integer' in types) or
            (isinstance(value, (int, float)) and not isinstance(value, bool) and 'number' in types and math.isfinite(value)))
    if not good:
        raise ValueError(path + ' 字段类型无效')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(path + ' 枚举无效')
    if isinstance(value, str):
        if len(value.strip()) < schema.get('minLength', 0) or len(value) > 200000:
            raise ValueError(path + ' 文字为空或过长')
    elif isinstance(value, dict):
        fields = schema['properties']
        if set(value) - set(fields) or set(schema['required']) - set(value):
            raise ValueError(path + ' 缺字段或含未知字段')
        for key, item in value.items():
            validate_shape(item, fields[key], path + '.' + key)
    elif isinstance(value, list):
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 200):
            raise ValueError(path + ' 列表数量无效')
        for index, item in enumerate(value):
            validate_shape(item, schema['items'], path + f'[{index}]')
    elif value is not None and 'minimum' in schema and value < schema['minimum']:
        raise ValueError(path + ' 数值范围无效')


def validate_nodes(nodes):
    ids = [node['node_id'] for node in nodes]
    if len(ids) != len(set(ids)):
        raise ValueError('大纲节点 ID 重复')
    graph = {node['node_id']: node['dependencies'] for node in nodes}
    visiting, visited = set(), set()
    def visit(node):
        if node in visiting:
            raise ValueError('大纲依赖成环')
        if node in visited:
            return
        visiting.add(node)
        for parent in graph[node]:
            if parent not in graph:
                raise ValueError('大纲依赖引用不存在')
            visit(parent)
        visiting.remove(node)
        visited.add(node)
    for node in ids:
        visit(node)


def validate(stage, value, context, source):
    validate_shape(value, SCHEMAS[stage])
    if 'nodes' in value:
        validate_nodes(value['nodes'])
    if stage == 'prose_generate':
        ids = [block['block_id'] for block in value['blocks']]
        if len(ids) != len(set(ids)):
            raise ValueError('正文块 ID 重复')
    if stage == 'screenplay_generate':
        entity_ids = {e['id'] for e in context.get('entities', []) if e['kind'] == 'character'}
        scene_ids, block_ids = [], []
        for scene in value['scenes']:
            scene_ids.append(scene['scene_id'])
            if [b['order'] for b in scene['blocks']] != list(range(len(scene['blocks']))):
                raise ValueError('场次内块顺序不连续')
            for block in scene['blocks']:
                block_ids.append(block['block_id'])
                if block['kind'] == 'dialogue' and block['speaker_id'] not in entity_ids:
                    raise ValueError('对白引用未知人物 ID')
        if len(scene_ids) != len(set(scene_ids)) or len(block_ids) != len(set(block_ids)):
            raise ValueError('场次或对白/动作块 ID 重复')
        frozen = context.get('dialogue_locks', [])
        generated = [b for scene in value['scenes'] for b in scene['blocks'] if b['kind'] == 'dialogue']
        ordered = [b for b in generated if any(lock['block_id'] == b['block_id'] for lock in frozen)]
        for lock in frozen:
            match = next((b for b in generated if b['block_id'] == lock['block_id']), None)
            if not match or (match['text'], match['speaker_id']) != (lock['text'], lock['speaker_id']):
                raise ValueError('锁定对白或人物绑定被改变')
        expected_order = [lock['block_id'] for lock in frozen if lock['order_locked']]
        if [b['block_id'] for b in ordered if b['block_id'] in expected_order] != expected_order:
            raise ValueError('锁定对白顺序改变')
    if stage == 'reference_analyze':
        ids = [card['card_id'] for card in value['cards']]
        if len(ids) != len(set(ids)):
            raise ValueError('拆解卡 ID 重复')
        blocks = {b['block_id']: b['text'] for b in context.get('analysis_blocks', [])}
        for card in value['cards']:
            if card['source_block_id'] not in blocks or card['evidence'] not in blocks[card['source_block_id']] or card['evidence'] not in source:
                raise ValueError('参考拆解缺少本次文字范围的证据位置')
    if stage == 'adaptation_plan':
        preserved = {event['event_id'] for event in context.get('constraints', {}).get('preserve_events', [])}
        nodes = {node['node_id'] for node in value['nodes']}
        mapped = set()
        for mapping in value['mappings']:
            if mapping['target_node_id'] not in nodes:
                raise ValueError('改编映射指向未知目标节点')
            source_id = mapping['source_event_id']
            if source_id is not None and source_id not in preserved:
                raise ValueError('改编映射引用未知保留事件')
            if source_id in preserved and mapping['treatment'] == '遗漏':
                raise ValueError('必须保留事件被标成遗漏')
            if source_id:
                mapped.add(source_id)
        if preserved - mapped:
            raise ValueError('保留事件没有明确去向')
    return value


def render(stage, value, names=None, dialogue_only=False):
    names = names or {}
    if stage=='idea_generate':
        labels={'premise':'故事方向','protagonist_goal':'主角目标','obstacle':'核心阻力','turn':'关键变化','ending_direction':'结局方向'}
        sections=[labels[key]+'\n'+value[key] for key in labels]
        if value.get('characters'):
            sections.append('主要人物\n'+'\n'.join(character['name']+'：'+character['description'] for character in value['characters']))
        return '\n\n'.join(sections)
    if stage=='outline_generate':
        return '\n\n'.join(str(i)+'、'+node['title']+'\n'+node['purpose']+'\n'+'\n'.join('· '+event for event in node['events']) for i,node in enumerate(value['nodes'],1))
    if stage == 'prose_generate':
        return '\n\n'.join(block['text'] for block in value['blocks'])
    if stage == 'copy_generate':
        return value['text']
    if stage == 'screenplay_generate':
        lines = []
        for index, scene in enumerate(value['scenes'], 1):
            if not dialogue_only:
                lines += [f"## 场{index}｜{scene['location']}｜{scene['time_of_day']}｜{scene['interior_exterior']}"]
            for block in scene['blocks']:
                if block['kind'] == 'dialogue':
                    lines.append(names.get(block['speaker_id'], block['speaker_id']) + '：' + block['text'])
                elif not dialogue_only:
                    lines.append('[动作] ' + block['text'])
            if not dialogue_only:
                lines.append('')
        return '\n'.join(lines).rstrip()
    return json_dump(value)


def json_dump(value):
    import json
    return json.dumps(value, ensure_ascii=False, indent=2)
