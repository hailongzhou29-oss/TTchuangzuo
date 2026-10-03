"""Build the frozen script catalog from the approved local design, without network."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source = next(ROOT.glob('*剧本页统一方案*'))
text = source.read_text(encoding='utf-8-sig')
VERSION = '2026-10-01'
groups = {}

def group(key, title, labels, rule, multi=False, prefix=None):
    rows = []
    for i, name in enumerate(labels.split('|'), 1):
        rows.append(dict(id=f'{prefix or key}.{i:02}', label=name, body=rule+' 本次采用：'+name+'。',
                         dimension=key, parent=None, selection='multiple' if multi else 'single',
                         applicable='script', version=VERSION))
    groups[key] = dict(title=title, multi=multi, rows=rows)

def table_rows(section):
    return re.findall(r'^\| ([^|]+) \| ([^|]+) \| ([^|]+) \|$', section, re.M)

group('form','故事形式','短剧|剧情短片|连续剧单集|原创电影感片段|广告剧情|口播情景|访谈情景|舞台片段',
      '以成品形式安排可执行场景，不替代题材和商业目的')
for row, (_, rule, _) in zip(groups['form']['rows'], table_rows(text.split('### 4.1')[1].split('### 4.2')[0])[1:]):
    row['body'] = rule
group('mode','创作模式','纯剧情|剧情带货|同城探店|文旅推广|品牌故事','商业对象参与行为；未知功效、价格、评价、历史及体验不当事实编造；没有真实对象可明确虚构演示')
groups['mode']['rows'][0]['body']='不自动植入产品或行动号召。'
group('language','语言模式','人物对白|旁白叙述|旁白＋人物对白|角色独白／自述|内心独白＋对白|对镜口述|采访／问答|无语言|自定义混合','按允许的声音来源组织信息；来源与传播方式分别标记')
for row, (_, rule) in zip(groups['language']['rows'], re.findall(r'^\| ([^|]+) \| ([^|]+) \|$', text.split('### 4.5')[1].split('## 5')[0],re.M)[2:]):
    row['body']=rule
group('sources','内容来源','场景人物发声|旁白|内心声音','区分现场可听语言、叙述声音与他人不可听见的心理声音；禁止加入未允许的来源',True)
group('delivery','传播方式','现场|画外|电话|录音播放','说明声音传播情境及听者范围；传播方式不改变对白、旁白或内心的归属',True)
view_rules=table_rows(text.split('### 14.1')[1].split('### 14.2')[0])[1:]
groups['view']=dict(title='观看视角',multi=False,rows=[dict(id=i,label=n,body=a+'；'+b,dimension='view',parent=None,selection='single',applicable='script',version=VERSION) for (i,a,b),n in zip(view_rules,['自动','角色主观','跟随角色','旁观纪实','全知视角','多角色视角','面向观众'])])
group('role','关系身份','恋人|家人|朋友|陌生人|顾客|商家|职场角色|调查者|目击者|游客|当地人|其他主体','角色的行动和信息受具体关系与处境限制；不按关系刻板补全年龄性别')
role_children={'恋人':'男友|女友','家人':'父母|子女|兄弟姐妹','商家':'店员|店主','职场角色':'员工|上司|同事'}
group('role_detail','具体身份','男友|女友|父母|子女|兄弟姐妹|店员|店主|员工|上司|同事','明确关系主体，镜头从其眼睛观察与观众扮演其身份必须区分')
for row in groups['role_detail']['rows']:
    row['parent']=next(r['id'] for r in groups['role']['rows'] if row['label'] in role_children.get(r['label'],'').split('|'))
carriers=table_rows(text.split('### 5.2')[1].split('### 5.3')[0])[1:]
group('carrier','影像载体','|'.join(r[0] for r in carriers),'保持画面来源、人物设备意识和知识范围一致')
items=[]
for parent, (name, children, rule) in zip(groups['carrier']['rows'],carriers):
    parent['body']=rule
    if name=='混合载体': continue
    for i, child in enumerate(children.split('、'),1):
        body=rule+'；本次画面来源：'+child+'。'
        if name=='设备记录': body+='给出设备位置和可见范围依据；行车及佩戴设备可移动，监控和门铃视野不能无因越界。'
        items.append(dict(id=parent['id']+f'.{i}',label=child,body=body,dimension='carrier_item',parent=parent['id'],selection='single',applicable='script',version=VERSION))
groups['carrier_item']=dict(title='具体来源',multi=False,rows=items)
groups['mixed_sources']=dict(title='混合来源',multi=True,rows=[dict(r,selection='multiple') for r in items])
for prefix,title in [('time','时间组织'),('info','信息揭示'),('thread','线索组织'),('suspense','悬念推进'),('reversal','反转机制'),('rhetoric','呈现修辞')]:
    rows=[]
    for rid,name,body in table_rows(text.split('### 14.4')[1].split('### 14.5')[0])[1:]:
        if rid.startswith(prefix+'.'): rows.append(dict(id=rid,label=name,body=body,dimension=prefix,parent=None,selection='multiple',applicable='script',version=VERSION))
    groups[prefix]=dict(title=title,multi=True,rows=rows)
assert sum(len(groups[p]['rows']) for p in ['time','info','thread','suspense','reversal','rhetoric'])==41
groups['genre']=dict(title='主赛道',multi=False,rows=[])
groups['subgenres']=dict(title='细分方向',multi=True,rows=[])
for rid,name,content in re.findall(r'^### (G\d+) ([^\n]+)\n\n(.+?)(?=\n### G|\n## 附录 B)',text,re.M|re.S):
    paragraphs=content.strip().split('\n\n')
    groups['genre']['rows'].append(dict(id=rid,label=name,body=paragraphs[0],dimension='genre',parent=None,selection='single',applicable='script',version=VERSION))
    for sid,label,body in re.findall(r'^- (G\d+\.\d+) (.+?)：(.+)$',content,re.M):
        groups['subgenres']['rows'].append(dict(id=sid,label=label,body=body,dimension='subgenres',parent=rid,selection='multiple',applicable='script',version=VERSION))
groups['formula']=dict(title='结构公式',multi=False,rows=[dict(id=i,label=n,body=b,dimension='formula',parent=None,selection='single',applicable='script',version=VERSION) for i,n,b in table_rows(text.split('## 附录 B')[1].split('## 附录 C')[0])[1:]])
groups['formula_assist']=dict(title='辅助机制',multi=True,rows=[dict(r,selection='multiple') for r in groups['formula']['rows']])
groups['fusion']=dict(title='融合题材',multi=True,rows=[dict(r,selection='multiple') for r in groups['genre']['rows']])
group('conflict','主要冲突','人与人|人与制度|人与环境|人与技术|人与自我|命运压力|价值两难','落实为有成本的具体阻力、行动与取舍，不仅贴标签',True)
group('ending','结尾方式','闭合结局|情绪余波|续集悬念|开放结局|反问留白|行动号召','事件结局回应主要目标；商业行动号召引用唯一商业收尾，不强制购买')
group('subject','叙事对象','人生|战争|案件|交易|营救|家庭|城市|发明|关系|文明|群像','短时长聚焦关键转折或局部事件，不从出生到死亡流水账')
group('opening','开场方式','台词冲击|行动突发|视觉异常|结局前置|问题悬念|渐入','尽早建立与主线有关的吸引点，依作品形式安排，不强制三秒惊吓')
group('climax','高潮事件','证据到场|关键行动|公开揭示|关系站队|资源反用|承诺兑现|代价承担|主动放弃|集体行动','高潮必须由具体行动改变局面，不把全场震惊或沉默当事件完成')
group('protagonist','主角类型','普通人|专业者|弱势者|强势者|边缘者|反英雄|群体主角|非人主体','主角有具体目标与主动选择；能力、资源和弱点影响行动')
group('relations','人物关系','亲子|夫妻|恋人|师徒|朋友|同事|上下级|竞争者|陌生人|共同体','关系变化有事件依据，双方各有诉求与边界',True)
group('change','人物变化','成长|觉醒|堕落|和解|坚守|放下|身份重建|无明显变化','转变由选择、失败和后果体现，避免一段说教替代变化')
group('motives','核心动机','生存|归属|尊严|责任|利益|求知|自由|保护|复仇','动机促成具体选择，代价真实影响行动',True)
group('intensity','情绪强度','克制|适中|强烈','情绪从动作、关系与后果表达；不能只堆情绪形容词')
group('payoff','爽点机制','能力兑现|真相揭露|尊严夺回|关系变化|困局破除|正义实现|资源重组','先铺垫限制和资源，通过能力、证据或选择兑现；不靠身份亮牌羞辱',True)
groups['emotion']=dict(title='情绪标签',multi=True,rows=[dict(id=f'emotion.{i:02}',label=n,body=b,dimension='emotion',parent=None,selection='multiple',applicable='script',version=VERSION) for i,(n,b) in enumerate(re.findall(r'^\| ([^|]+) \| ([^|]+) \|$',text.split('## 附录 C')[1].split('## 附录 D')[0],re.M)[1:],1)])
group('density','语言密度','留白为主|均衡|语言密集','语言密度指发声占时软预算；动作和语言重叠不重复计算，不强制变更语速')
for r,span in zip(groups['density']['rows'],['20%—40%','40%—65%','65%—85%']): r['body']+=' 初始发声占时建议'+span+'；尚未成片校准。'
group('speed','语速','舒缓|自然|快速','采用包含通常句内停顿的有效语速，仅中文初始参数，非行业结论')
for r,n in zip(groups['speed']['rows'],[3,4,5]): r['body']+=f' 中文初始规划{n}汉字/秒，不暗中升速。'
groups['dialogue_style']=dict(title='语言风格',multi=True,rows=[])
for i,(name,rule) in enumerate(re.findall(r'^- (.+?)：(.+)$',text.split('## 附录 D')[1],re.M),1):
    name=name.split('（')[0]
    groups['dialogue_style']['rows'].append(dict(id=f'language_style.{i:02}',label=name,body=rule,dimension='dialogue_style',parent=None,selection='multiple',applicable='script',version=VERSION))
group('profanity','粗口强度','不用|少量|明显','按人物、受众和强度控制；不得用辱骂代替冲突或贬损受保护群体')
group('tone','叙事气质','写实|浪漫|荒诞|冷峻|热血|黑色幽默|诗意|纪实|史诗|轻松','气质影响事件呈现和叙述距离，不改写事实仍当史实，不替代视角载体')
group('visual','画面表达','简洁动作|表演细节|空间关系|视觉奇观|生活质感|环境氛围|符号意象','通过可执行动作、可见环境和空间连续表达，不用标签替代事件因果',True)
group('audience','目标受众','通用|青少年|成人|家庭','按作品目标受众调整表达，不推断操作者年龄')
group('boundaries','内容边界','避免血腥|避免粗口|避免性描写|避免恐怖','遵守明确内容边界，不静默牺牲另一显式要求',True)
group('borrow','借鉴部分','开场|冲突机制|高潮构造|情绪曲线|节奏|视角|气质|对白技巧','参考仅为资料；借鉴结构与方法，创作新的具体事件和表达，不照搬高潮台词',True)
group('strategy','商业子策略','场景植入|痛点解决|反差误会|关系故事|体验探索|知识融入|氛围展示|口碑演绎','商业对象自然参与目标与行动，只采用提供的真实事实，不虚构体验和功效')
group('cta','商业收尾','自然结束|提及名称|到店邀请|了解更多','商业收尾与事件结局分别管理；不强制购买或到店，未知预约与交易条件不编造')
assert len(groups['genre']['rows'])==24 and len(groups['subgenres']['rows'])==144
assert len(groups['formula']['rows'])==30 and len(groups['emotion']['rows'])==24
(ROOT/'resources/script_rules.json').write_text(json.dumps(dict(version=VERSION,source=source.name,groups=groups),ensure_ascii=False,indent=2),encoding='utf-8')
print('Catalog built:',sum(len(g['rows']) for g in groups.values()),'options')
