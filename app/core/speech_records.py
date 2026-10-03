"""All three script parts share ordered, versioned speech records."""
import re,copy
from app.storage.project import new_id
from app.core.files import digest
from app.core.script_settings import active_settings,budget,numeric_range

SECOND='第二部分｜完整剧本'
THIRD='第三部分｜完整人物台词'
SOURCE_LABELS={'dialogue':'对白','narration':'旁白','inner':'内心'}
SOURCE_IDS={'dialogue':'sources.01','narration':'sources.02','inner':'sources.03'}
DELIVERIES={'现场','画外','电话','录音播放'}

def render(record):
    name=record['speaker']; source=record['source']; delivery=record['delivery']
    mark=''
    if source!='dialogue' or delivery!='现场': mark='〔'+SOURCE_LABELS[source]+'·'+delivery+'〕'
    return name+mark+'：'+record['text'].replace('\n','\n    ')

def extract(text, previous=()):
    body=text.split(SECOND,1)[-1].split(THIRD,1)[0]; records=[]
    for line in body.splitlines():
        if line.startswith('    ') and records:
            records[-1]['text']+='\n'+line[4:]; continue
        match=re.match(r'^([^：:\n]{1,80})[：:]\s*(.+)$',line.strip())
        if not match or match[1].startswith(('第','[动作]','动作','预计','目标','场景','地点','时间','估计','预算')): continue
        rawname=match[1]; tagged=re.match(r'^(.*?)〔(对白|旁白|内心)·(现场|画外|电话|录音播放)〕$',rawname)
        name=tagged[1] if tagged else rawname
        source={'对白':'dialogue','旁白':'narration','内心':'inner'}[tagged[2]] if tagged else 'narration' if rawname=='旁白' else 'inner' if rawname.endswith('内心') else 'dialogue'
        records.append(dict(id=new_id(),speaker=name,source=source,delivery=tagged[3] if tagged else '现场',order=len(records),text=match[2]))
    unused=list(previous)
    for index,r in enumerate(records):
        match=next((p for p in unused if all(p.get(k)==r[k] for k in ['speaker','source','delivery','text'])),None)
        if match is None and index<len(previous):
            p=previous[index]
            if p in unused and all(p.get(k)==r[k] for k in ['speaker','source','delivery']): match=p
        if match: r['id']=match['id']; unused.remove(match)
    return records

def sync(text,previous=(),config=None):
    if SECOND not in text: return text,[]
    records=extract(text,previous); base=text.split(THIRD,1)[0].rstrip()
    if config:
        summary=estimate_summary(config,records)
        base=re.sub(r'(?m)^目标时长：.*未配音实测。$',summary,base,count=1)
    return base+'\n\n'+THIRD+'\n\n'+('\n'.join(render(r) for r in records) if records else '本作品无发声台词'),records

def verify(text,records=None):
    if SECOND not in text or THIRD not in text: raise ValueError('剧本缺少完整三段结构')
    records=extract(text) if records is None else records
    actual=text.split(THIRD,1)[1].strip(); expected='\n'.join(render(r) for r in records) if records else '本作品无发声台词'
    if actual!=expected: raise ValueError('第三部分与正文发声记录的文字、顺序或数量不一致，请先保存同步')
    if len({r['id'] for r in records})!=len(records): raise ValueError('发声记录存在重复ID')
    return records

def save_speech_work(work,rebuild=False):
    """Save all user text before resolving a third-part conflict explicitly."""
    if SECOND not in work.text:
        work.save(); return False
    did=work.document_id; store=work.store
    saved=store.setting('v2_speech:'+did,{})
    previous=saved.get('records',[])
    original=store.document(did)['text']
    third=work.text.split(THIRD,1)[-1].strip() if THIRD in work.text else ''
    baseline=('\n'.join(render(r) for r in previous) if previous else '本作品无发声台词') if 'records' in saved else original.split(THIRD,1)[-1].strip()
    baseline_invalid=False
    if 'records' not in saved and SECOND in original:
        try: verify(original)
        except ValueError: baseline_invalid=True
    try: verify(work.text)
    except ValueError: invalid=True
    else: invalid=False
    pending=bool(store.setting('v2_third_unsynced:'+did,False))
    conflict=invalid and (pending or baseline_invalid or third!=baseline)
    if conflict:
        work.save('保留正文与台词手改草稿')
        store.set_setting('v2_third_unsynced:'+did,True)
        store.set_setting('v2_third_draft:'+did,dict(revision=work.revision,text=work.text))
        # Keep the last synchronized records as the comparison baseline.
        if not rebuild: return True
    synced,records=sync(work.text,previous,work.config)
    if synced!=work.text: work.edit(synced)
    work.save('明确重建人物台词' if rebuild else '同步正文发声记录')
    store.set_setting('v2_speech:'+did,dict(revision=work.revision,records=records,text_hash=digest(work.text)))
    store.set_setting('v2_third_unsynced:'+did,False)
    return False

def validate_text(text,config):
    records=extract(text)
    nodes=[dict(type=r['source'],speaker=r['speaker'],text=r['text'],delivery=r['delivery']) for r in records]
    if not nodes: nodes=[dict(type='action',speaker='',text=script_action(text))]
    payload(dict(title='正文校验',outline='当前正文',scenes=[dict(title='当前正文',nodes=nodes)]),config)
    return records

def script_action(text):
    return text.split(SECOND,1)[-1].split(THIRD,1)[0].strip() or '无发声动作场景'

def estimate_speech(config,records):
    b=budget(config); text='\n'.join(r['text'] for r in records)
    count=len(re.findall(r'[\u4e00-\u9fff]',text)); latin=len(re.findall('[A-Za-z]',text))
    unsupported=not b['reliable'] or bool(re.search(r'[\u3040-\u30ff\uac00-\ud7af\u0400-\u04ff]',text)) or (latin>0 and latin>=count)
    warnings=[]
    if unsupported: warnings.append('非中文或混合语言没有适用估算器，不支持可靠估时；未套中文语速')
    elif re.search(r'\d|[A-Za-z]',text): warnings.append('含数字／外语，读法未知，中文规划估计不确定')
    if unsupported: b=dict(b,reliable=False,speed=None,word_budget=None,note='当前发声没有适用语言估算器，不支持可靠估时；未提供时间戳，不具备精确重叠测量')
    seconds=None if unsupported else count/b['speed'] if b['speech_ratio'] else 0
    by_source={source:(None if unsupported else sum(len(re.findall(r'[\u4e00-\u9fff]',r['text'])) for r in records if r['source']==source)/b['speed']) for source in SOURCE_LABELS}
    denominator=None if unsupported else by_source['narration']+by_source['dialogue']
    ratio=by_source['narration']/denominator*100 if denominator else None
    target=active_settings(config)['explicit'].get('narration_ratio')
    if target and ratio is not None and abs(ratio-float(target))>5:
        warnings.append(f'旁白占对白＋旁白发声时间估计约{ratio:.1f}%，与指定{float(target):g}%有差距；按同一有效语速估计，未实测，不自动改句')
    elif target and ratio is None: warnings.append('无法可靠估计旁白／对白占时比例；未按段数冒充比例')
    if b['word_budget'] is not None and count>b['word_budget']*1.25: warnings.append('语言超过建议预算，可延长时长或调整密度；未自动升速')
    return dict(chinese_count=count,segments=len(records),seconds=seconds,source_seconds=by_source,narration_percent=ratio,reliable=not unsupported,estimated=True,time_windows_available=False,warnings=warnings,budget=b)

def estimate_summary(config,records):
    e=estimate_speech(config,records); b=e['budget']; seconds=e['seconds']
    timing=(f'估计发声{seconds:.0f}秒；动作留白预算约{max(0,config["duration"]-seconds):.0f}秒' if seconds is not None else '不支持可靠发声估时／动作留白估时')
    return f'目标时长：{config["duration"]}秒；{timing}。未配音实测。'

def payload(raw,config):
    raw=copy.deepcopy(raw); normalized_narration=False
    if not isinstance(raw,dict) or not {'title','outline','scenes'}<=raw.keys() or set(raw)-{'title','outline','scenes','adopted'}: raise ValueError('剧本结构无效')
    if not isinstance(raw['title'],str) or not isinstance(raw['outline'],str) or not isinstance(raw['scenes'],list) or not raw['scenes']: raise ValueError('剧本缺少标题、大纲或场次')
    active=active_settings(config)['explicit']; allowed=active.get('sources'); records=[]; blocks=[]; body=[]; speakers={}
    for i,scene in enumerate(raw['scenes'],1):
        if not isinstance(scene,dict) or set(scene)!={'title','nodes'} or not isinstance(scene['title'],str) or not isinstance(scene['nodes'],list): raise ValueError('场次结构无效')
        title=re.sub(r'^\s*(?:第\d+场|\d+)\s*','',scene['title']); body.append(f'第{i}场 {title}')
        for node in scene['nodes']:
            if not isinstance(node,dict) or not {'type','speaker','text'}<=node.keys() or set(node)-{'type','speaker','text','source','delivery','id'} or not isinstance(node['text'],str) or not node['text'].strip() or not isinstance(node['speaker'],str): raise ValueError('动作或发声记录无效')
            kind=node['type']; block=dict(node,id=new_id())
            if kind=='action': body.append('[动作] '+node['text'])
            elif kind in SOURCE_LABELS:
                source=node.get('source',kind)
                if source not in SOURCE_IDS: raise ValueError('未知声音内容来源')
                if allowed is not None and SOURCE_IDS[source] not in allowed: raise ValueError('结果使用了语言模式不允许的'+SOURCE_LABELS[source])
                delivery=node.get('delivery','现场')
                if delivery not in DELIVERIES: raise ValueError('未知传播方式')
                selected_delivery=active.get('delivery')
                if selected_delivery and delivery not in [__import__('app.core.script_settings',fromlist=['label']).label(v) for v in selected_delivery]: raise ValueError('结果使用了未允许的传播方式')
                name=node['speaker'].strip()
                if not name and kind=='narration' and source=='narration':
                    name='旁白';node['speaker']=name;block['speaker']=name;normalized_narration=True
                if not name or any(ch in name for ch in '\n：:〔〕'): raise ValueError('发声记录缺少稳定说话者')
                record=dict(id=block['id'],speaker=name,source=source,delivery=delivery,order=len(records),text=node['text'])
                records.append(record); body.append(render(record)); speakers.setdefault(name,new_id()); block.update(source=source,delivery=delivery,speaker_id=speakers[name])
            else: raise ValueError('未知剧本节点类型')
            blocks.append(block)
        body.append('')
    e=estimate_speech(config,records); b=e['budget']; count=e['chinese_count']; seconds=e['seconds']
    estimated=round(seconds/b['speech_ratio']) if seconds is not None and b['speech_ratio'] else config['duration'] if not b['speech_ratio'] else None
    warnings=e['warnings']
    if normalized_narration:warnings=warnings+['未命名的旁白已标为“旁白”；文本、来源和传播方式保留，可核对完整人物台词。']
    words=numeric_range(active.get('word_range',''),'发声汉字范围'); segments=numeric_range(active.get('segment_range',''),'发言段范围')
    if words and not words[0]<=count<=words[1]: raise ValueError('结果未满足明确发声汉字范围，保留为候选')
    if segments and not segments[0]<=len(records)<=segments[1]: raise ValueError('结果未满足连续发言段范围，保留为候选')
    speechtext='\n'.join(r['text'] for r in records)
    for line in active.get('required_lines','').splitlines():
        if line.strip() and line.strip() not in speechtext: raise ValueError('结果缺少必须保留的句子')
    for line in active.get('banned_lines','').splitlines():
        if line.strip() and line.strip() in speechtext: raise ValueError('结果包含禁用词句')
    summary=estimate_summary(config,records)
    text='第一部分｜故事大纲与建议时长\n\n'+raw['outline']+'\n\n'+summary+'\n\n'+SECOND+'\n\n'+'\n'.join(body).rstrip()+'\n\n'+THIRD+'\n\n'+('\n'.join(render(r) for r in records) if records else '本作品无发声台词')
    verify(text,records)
    adopted=dict(raw.get('adopted',{}),budget_density=b['density'],budget_strategy=b['strategy'],budget_note=b['note'],budget_speed=str(b['speed']) if b['reliable'] else '没有适用估算器')
    return dict(raw,text=text,blocks=blocks,speakers=speakers,speech_records=records,record_version=digest(text),estimated_duration=estimated,speech_estimate=e,warnings=warnings,adopted=adopted)
