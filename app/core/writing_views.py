"""Novel/rewrite view budgets and objects; separate from the existing WritingService."""
import copy
import math
from app.core.files import digest

LONG_LENGTHS={'长篇连载','长篇小说'}
NOVEL_ONLY={'length','words','chapters','chapter_words','perspective','language'}
SCRIPT_ONLY={'format','duration','duration_label','duration_custom_draft','minutes','seconds','ratio','density','dialogue_ratio','speech_speed','mode','object','supplemental','commerce_style','marketing','script_settings'}

def is_long(config): return config.get('output')=='novel' and config.get('length') in LONG_LENGTHS

def normalize_budget(config,changed='words'):
    c=copy.deepcopy(config)
    total=max(1,int(c.get('words',3000)))
    chapters=max(1,min(total,int(c.get('chapters',30))))
    if changed=='chapter_words':
        budget=max(1,int(c.get('chapter_words',2500))); chapters=max(1,math.ceil(total/budget))
    else: budget=math.ceil(total/chapters)
    c.update(words=total,chapters=chapters,chapter_words=budget)
    return c

def writing_config(config,kind):
    from app.core.selection import selection
    c=dict(selection(kind),**copy.deepcopy(config)); c['kind']=kind
    if kind=='novel': c['output']='novel'
    if 'writing_version' not in c:
        c['writing_original']=copy.deepcopy(config); c['writing_version']=1
        if is_long(c):
            prior=(c['words'],c['chapters'],c['chapter_words']); c=normalize_budget(c)
            if prior!=(c['words'],c['chapters'],c['chapter_words']): c['writing_notes']=['旧章节预算已按总字数协调；旧数值完整保留，已有章节未改写。']
    if kind=='rewrite':
        c.setdefault('rewrite_branches',{})
        c.setdefault('reference_source',dict(name='粘贴文本',type='粘贴文本',status='已读取文字' if c.get('reference','').strip() else '未提供参考'))
    return c

def active_config(config):
    """Inactive branch data is stored locally, never sent as simultaneous constraints."""
    c=copy.deepcopy(config)
    for key in ['writing_original','writing_notes','rewrite_branches']: c.pop(key,None)
    if c.get('output')=='novel':
        for key in SCRIPT_ONLY: c.pop(key,None)
    else:
        for key in NOVEL_ONLY: c.pop(key,None)
    return c

def source_snapshot(config):
    text=config.get('reference','').strip()
    description=config.get('reference_description','').strip()
    if not text and not description: raise ValueError('先粘贴或导入可读参考，或填写明确的结构描述，再开始仿写。')
    source=copy.deepcopy(config.get('reference_source',{}))
    return dict(id=source.get('id') or 'source-'+digest(text or description)[:20],name=source.get('name') or '用户提供的参考',
                text=text or description,status='已读取文字' if text else '用户结构描述',source_type=source.get('type','粘贴文本'),
                source_revision=source.get('revision') or digest(text or description),hash=digest(text or description),enabled=True,scope='整部作品')

def validate_rewrite(config):
    source_snapshot(config)
    advanced=config.get('advanced',{})
    keep=set(config.get('keep',[])); change=set(config.get('change',[]))
    if keep & change: raise ValueError('保留与改变要求冲突：'+ '、'.join(sorted(keep & change)))
    import re
    def parts(value): return {v.strip() for v in re.split('[，,；;\n]',value or '') if v.strip()}
    kept=parts(advanced.get('必须保留',''))
    forbidden=parts(advanced.get('不要出现',''))|parts(config.get('must_change',''))
    if kept & forbidden: raise ValueError('保留与改变／排除要求冲突：'+ '、'.join(sorted(kept & forbidden)))

def chapter_documents(store): return [d for d in store.documents() if d['kind'] not in {'reference','outline'}]

def outline_text(plan):
    if isinstance(plan.get('outline_text'),str): return plan['outline_text']
    chapters=plan.get('chapters',[])
    return '故事简介\n'+str(plan.get('synopsis',''))+'\n\n人物约束\n'+str(plan.get('characters',''))+'\n\n章节规划\n'+'\n'.join(chapters)

def ensure_outline(store,config,plan=None,update=False):
    if not is_long(config): return None
    did=store.setting('v2_outline_id')
    if did and any(d['id']==did for d in store.documents()):
        if update and plan is not None:
            document=store.document(did); store.save_document(did,document['head'],outline_text(plan),'更新故事大纲')
        return did
    plan=plan if plan is not None else store.setting('v2_plan',{})
    if not plan: return None
    did=store.add_document('故事大纲',text=outline_text(plan),kind='outline')
    store.set_setting('v2_outline_id',did); store.set_setting('v2_document:'+did,True)
    return did
