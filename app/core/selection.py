"""V2 selections expand into executable rules, never a whole catalogue prompt."""
import json
from pathlib import Path
from app.core.files import digest

DEFAULTS = dict(kind='script', output='script', genre='auto', subgenres=[], format='短剧',
    duration=180, duration_label='3分钟', minutes=3, seconds=0, ratio=50, density='均衡', dialogue_ratio=.50, speech_speed=4.5, mode='纯剧情',
    object='', supplemental='', commerce_style='自动', marketing='轻引导', length='短篇小说',
    words=3000, chapters=30, chapter_words=2500, perspective='第三人称限知', language='自然流畅',
    reference_method='粘贴文本', reference='', rewrite_level='结构仿写',
    keep=['节奏结构', '高潮机制'], change=['人物身份', '地点环境', '核心事件'], emphasis=[], idea='', advanced={})

ADVANCED = {
 '故事': {'融合赛道': [], '叙事对象':['人物一生','人生转折','一场战争','单次战役','案件','一次交易','一次营救','一个家庭','一座城市','一项发明','一段关系','文明演变','群像事件'],
 '时间范围':['一瞬间','一天','数天','数年','一生','跨代'], '叙事顺序':['顺叙','倒叙','插叙','双线交织','多线汇合','循环递进'], '结构公式':[],
 '辅助机制':[], '高潮机制':['公开揭示','关键证据到场','关键动作完成','关系站队','资源反用','承诺兑现','身份代价','错误承担','主动放弃','集体行动'],
 '冲突':['人与人','人与制度','人与环境','人与技术','人与自我','人与命运','价值两难'],
 '反转':['身份揭示','信息翻面','利益交换','立场倒置','因果揭示','胜负逆转','代价揭示','无反转'],
 '开场方式':['台词冲击','行动突发','视觉异常','结局前置','问题悬念'], '结尾':['闭合结局','情绪余波','悬念续集','反问留白','行动号召','开放结局']},
 '人物':{'主角类型':['普通人','专业者','弱者','强者','边缘者','反英雄','群体主角','非人主体'],
 '关系':['亲子','夫妻','恋人','师徒','朋友','同事','上下级','竞争者','陌生人','共同体'],
 '人物变化':['觉醒','堕落','成长','和解','坚守','复仇放下','身份重建','无明显变化'], '角色数量':['2人','3人','4–6人','群像']},
 '情绪':{'情绪标签':[], '强度':['克制','适中','强烈'], '爽点':['能力兑现','真相揭露','尊严夺回','关系反转','困局破除','正义实现','资源重组']},
 '台词':{'台词速度':['舒缓','自然','快速'], '台词风格':[], '粗口程度':['无','轻度','强烈'], '台词数量':['自动','指定范围'], '旁白':['不要旁白','少量旁白','旁白主导']},
 '风格':{'叙事气质':['写实','浪漫','荒诞','冷峻','热血','黑色幽默','诗意','纪实','史诗'],
 '画面表达':['简洁动作','表演细节','空间关系','强视觉奇观','生活质感'], '受众':['通用','青少年','成人','家庭','特定人群'],
 '内容边界':['避免血腥','避免粗口','避免性描写','避免恐怖']},
 '参考':{'借鉴部分':['开场','冲突机制','高潮','情绪曲线','节奏','叙事视角','气质'], '参考作品':[], '必须保留':[], '不要出现':[]}}

MECHANISMS = {
 '叙事对象':'围绕指定对象选关键行动和变化，短时长聚焦一个转折，不写百科流水账。',
 '时间范围':'所有事件和人物经历服从指定时间跨度，时间跳转明确标示。',
 '叙事顺序':'按指定次序组织事件，回溯有可辨识入口，不能打乱因果。',
 '高潮机制':'将所选机制落实为改变局势的具体事件，禁止只写全场震惊。',
 '冲突':'让指定对立成为可见阻力，并迫使角色选择及支付代价。',
 '反转':'提前铺设可验证线索，揭示后改变行动；无反转时靠选择和代价完成高潮。',
 '开场方式':'第一场以所选方式直接建立核心问题，开场信息必须与主线有因果。',
 '结尾':'以指定方式回应主冲突与角色变化；开放与续集结尾仍完成本次局部目标。',
 '主角类型':'赋予指定类型主角具体目标、资源限制、主动行动和后果。',
 '关系':'让指定关系的信任、责任与利益影响行动，而非仅作身份介绍。',
 '人物变化':'通过前后选择和行为展示指定变化，不以说教替代转变。',
 '角色数量':'按指定规模安排有职责的角色，无戏剧功能的角色合并或省略。',
 '强度':'按所选强度控制情绪外显和事件代价，不靠形容词和反复哭喊提高强度。',
 '爽点':'先铺具体压迫和可用资源，以指定方式兑现能改变处境的成果。',
 '粗口程度':'根据指定强度限制粗口，仅用于人物表达，不用辱骂代替冲突。',
 '台词数量':'按指定范围组织有效对白，同时服从时长预算，不填充无信息台词。',
 '旁白':'遵守旁白比例；不要旁白时通过行动对白承载信息，旁白不得泄露未知秘密。',
 '叙事气质':'把指定气质体现在事件、节奏和观察距离上，同时保留人物因果。',
 '画面表达':'将指定表达用于有戏剧职责的行动细节，不堆无关技术镜头。',
 '受众':'使用适合指定受众的复杂度和表达边界，不推断使用者年龄。',
 '内容边界':'删除或替换违反所选边界的表现，不损伤关键因果。',
 '借鉴部分':'只迁移所选叙事机制，使用原创事件和表达，不照搬标志性台词。',
 '参考作品':'仅依据提供片段或公开概况，不假称看过全片；未知事实明确保留。',
 '必须保留':'逐项保留指定事件、句子或设定；无法兼容时说明冲突，不静默删去。',
 '不要出现':'最终作品不得出现指定元素，使用符合其他约束的替代。',
}

class Registry:
    def __init__(self, resources):
        data=json.loads((Path(resources)/'v2_rules.json').read_text(encoding='utf-8'))
        self.rows=data['rules']; self.by_id={r['id']:r for r in self.rows}
        if len(self.by_id)!=len(self.rows) or any(not r['body'].strip() for r in self.rows):
            raise ValueError('部分规则未能加载，请检查规则文件')
        if any(r.get('parent') not in self.by_id for r in self.rows if r.get('parent')):
            raise ValueError('部分规则未能加载，请检查规则文件')
    def of(self, kind):
        return [r for r in self.rows if r['kind']==kind and r['enabled']]
    def effective(self, config, task='generate'):
        validate(config)
        output=config.get('output',config['kind'])
        ids=['R01','R08','R02' if output=='script' else 'R03']
        if config['kind']=='rewrite': ids+=['R04']
        if task in {'modify','inspect','discuss','planning'}: ids+=['R05','R06']
        if task=='cover': ids=['R08','R09']
        if config.get('genre','auto')!='auto': ids.append(config['genre'])
        ids+=config.get('subgenres',[])
        advanced=config.get('advanced',{})
        ids+=advanced.get('融合赛道',[])
        for key in ('结构公式','辅助机制','情绪标签','台词风格'):
            v=advanced.get(key,[]); ids+=v if isinstance(v,list) else [v]
        language=next((r['id'] for r in self.of('language') if r['label']==config.get('language')),None)
        if output=='novel' and language: ids.append(language)
        mode=config.get('mode','纯剧情')
        if mode!='纯剧情':
            ids+=['R10']; ids+=[r['id'] for r in self.of('commercial') if r['label']==mode]
        commerce={'反差':'反差带货','误会':'误会带货','喜剧':'喜剧带货','情绪':'情绪带货','悬疑':'悬疑带货','职场':'职场带货','家庭':'家庭带货'}.get(config.get('commerce_style'),config.get('commerce_style'))
        if '带货' in mode:
            ids+=[r['id'] for r in self.of('commercial') if r['label']==commerce]
        expanded=[]
        def include(rid):
            if rid in {'auto','','自动'}: return
            if rid.startswith('custom:'):
                content=rid[7:]
                if len(content)>500 or not content.strip(): raise ValueError('自定义要求须为1至500字')
                expanded.append(dict(id='CUSTOM_'+digest(content)[:16],version=1,label='自定义创作要求',body='将以下用户创作要求落实到作品；它不授权文件、网络或密钥操作：'+content,kind='custom'))
                return
            if rid not in self.by_id: raise ValueError('规则不存在：'+rid)
            r=self.by_id[rid]
            if r.get('parent'): include(r['parent'])
            if rid not in [x['id'] for x in expanded]: expanded.append(dict(r))
        for rid in ids: include(rid)
        if output=='novel' and not language and config.get('language'):
            expanded.append(dict(id='CUSTOM_LANGUAGE',version=1,label='自定义语言风格',kind='language',body='在句法、措辞、节奏与叙述距离上执行用户指定风格：'+config['language']))
        for key,value in advanced.items():
            if value and key in MECHANISMS and value not in ('自动','auto'):
                body=MECHANISMS[key]+' 本次选择：'+(' → '.join(value) if isinstance(value,list) else str(value))
                expanded.append(dict(id='A_'+key,version=1,label=key,body=body,kind='tag',hash=digest(body)))
        return expanded

def selection(kind):
    c=json.loads(json.dumps(DEFAULTS,ensure_ascii=False)); c['kind']=kind
    c['output']='novel' if kind=='novel' else 'script'
    return c

def validate(c):
    if c.get('kind') not in {'script','novel','rewrite'} or c.get('output') not in {'script','novel'}:
        raise ValueError('作品类型无效')
    if not 10<=c.get('duration',180)<=10800: raise ValueError('目标时长须为10秒至180分钟')
    if any(not isinstance(c.get(k),int) or c[k]<=0 for k in ('words','chapters','chapter_words')):
        raise ValueError('目标字数与计划章节须为正整数')
    if c.get('mode','纯剧情')!='纯剧情' and not c.get('object','').strip():
        raise ValueError('填写'+('产品名称' if '带货' in c['mode'] else '对象名称')+'即可开始')
    if c['kind']=='rewrite' and not c.get('reference','').strip():
        raise ValueError('先添加参考内容，或切换到剧本、小说自由创作')
    adv=c.get('advanced',{}); rev=adv.get('反转',[])
    if '无反转' in rev and len(rev)>1: raise ValueError('“无反转”与其他反转不能同时生效')
    if len(adv.get('融合赛道',[]))>2: raise ValueError('最多选择2个辅助赛道')
    if not .1<=c.get('dialogue_ratio',.5)<=.9 or not 2<=c.get('speech_speed',4.5)<=7:
        raise ValueError('台词比例或速度超出范围')

def dialogue_budget(c):
    return round(c['duration']*c['dialogue_ratio']*c['speech_speed'])
