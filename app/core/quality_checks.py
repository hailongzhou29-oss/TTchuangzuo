"""Source-backed local review reminders, never silent prose correction."""
import re

def requirements(snapshot):
    config=snapshot.get('constraints',{});values=[]
    for key,label in [('idea','创作要求'),('must_keep','必须保留'),('must_change','必须改变'),('must_avoid','不要出现')]:
        if config.get(key):values.append(dict(source=label,text=str(config[key])))
    for key,value in config.get('advanced',{}).items():
        if isinstance(value,str) and value.strip() and value not in {'自动','auto'}:values.append(dict(source='创作设置·'+key,text=value))
    if snapshot.get('instruction'):values.append(dict(source='本次要求',text=snapshot['instruction']))
    for value in snapshot.get('locked_content',[]):values.append(dict(source='锁定原文',text=value))
    for fact in snapshot.get('confirmed_facts',[]):
        if fact.get('content'):values.append(dict(source='已确认事实',text=fact['content']))
    return values

def review_notes(snapshot,text):
    req=snapshot.get('quality_requirements') or requirements(snapshot)
    notes=[dict(kind='requirement',source=r['source'],evidence=r['text'],status='需人工核对') for r in req]
    clocks=re.findall(r'.{0,22}(?:\d{1,2}[：:]\d{2}|[一二三四五六七八九十两零〇]{1,3}点[一二三四五六七八九十两零〇]{0,4}分?).{0,22}',text)
    if clocks:notes.append(dict(kind='timeline',source='返回正文',evidence='；'.join(clocks[:8]),status='逐项核对日期、上午/下午与事件顺序'))
    names=[m.group(0) for m in re.finditer(r'[\u4e00-\u9fff]{1,3}叔([\u4e00-\u9fff]{1,3})叔',text) if not m.group(1).startswith(('和','与','及','跟'))]
    if names:notes.append(dict(kind='names',source='返回正文',evidence='；'.join(names[:4]),status='可能称谓粘连，需核对，未自动改文'))
    from app.core.explicit_constraints import timeline_review
    notes += [dict(n,status=n['message']) for n in timeline_review(snapshot,text)]
    return notes

def reminder(snapshot,text):
    req=snapshot.get('quality_requirements') or requirements(snapshot)
    parts=[r['source']+'：'+r['text'][:90] for r in req[:2]]
    hints=[n['status']+'（'+n['evidence'][:70]+'）' for n in review_notes(snapshot,text) if n['kind'] in {'timeline','names'}]
    return '采用前核对：'+'；'.join(parts+hints)+'。结构有效不代表剧情正确；可返回正文手改，或在右侧明确要求新改稿。' if parts or hints else ''
