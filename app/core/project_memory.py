"""Revision-bound semantic summaries with a clearly labelled excerpt fallback."""
from app.core.files import digest
import json

LEGACY_KEYS={'summary','characters','events','unresolved','evidence'}
FACT_KINDS=('character','relationship','event','foreshadow')
MEMORY_SCHEMA=dict(type='object',properties={key:dict(type='string') if key=='summary' else dict(type='array',items=dict(type='string')) for key in ('summary','characters','relationships','events','foreshadow','unresolved','evidence')},required=['summary','characters','relationships','events','foreshadow','unresolved','evidence','facts'],additionalProperties=False)
MEMORY_SCHEMA['properties']['facts']=dict(type='array',maxItems=8,items=dict(type='object',properties=dict(category=dict(type='string',enum=list(FACT_KINDS)),content=dict(type='string'),entities=dict(type='array',items=dict(type='string')),evidence=dict(type='string')),required=['category','content','entities','evidence'],additionalProperties=False))

def resolve_evidence(quote,source):
    """Locate an unchanged literal body; only a final comma/period may differ.

    Internal punctuation, whitespace, words and numbers are never normalized.
    An ambiguous location is rejected. The saved citation comes from the source,
    while the model's original citation remains in the resolution receipt.
    """
    if quote in source: return quote,None
    endings='。，.,'
    if len(quote)<8 or quote[-1] not in endings: raise ValueError('原文证据不能唯一定位')
    body=quote[:-1]; locations=[]; offset=0
    while True:
        start=source.find(body,offset)
        if start<0: break
        end=start+len(body)
        if end<len(source) and source[end] in endings: locations.append((start,end+1))
        offset=start+1
    if len(locations)!=1: raise ValueError('原文证据不能唯一定位')
    start,end=locations[0]; exact=source[start:end]
    return exact,dict(model_quote=quote,source_quote=exact,start=start,end=end,method='唯一原文位置，末尾逗号/句号差异；引用由原稿截取')

def parse_memory(text,source):
    value=json.loads(text)
    if not isinstance(value,dict) or set(value) not in (LEGACY_KEYS,set(MEMORY_SCHEMA['required'])) or not isinstance(value['summary'],str) or not value['summary'].strip() or len(value['summary'])>1600: raise ValueError('项目摘要合同无效')
    value.setdefault('relationships',[]); value.setdefault('foreshadow',[]); value.setdefault('facts',[])
    for key in ('characters','relationships','events','foreshadow','unresolved','evidence'):
        if not isinstance(value[key],list) or len(value[key])>20 or any(not isinstance(item,str) or not item.strip() or len(item)>400 for item in value[key]): raise ValueError('项目摘要字段无效')
    if not value['evidence']: raise ValueError('项目摘要缺少当前原文证据')
    resolutions=[]
    for index,quote in enumerate(value['evidence']):
        exact,receipt=resolve_evidence(quote,source); value['evidence'][index]=exact
        if receipt: resolutions.append(dict(receipt,field='evidence',index=index))
    if not isinstance(value['facts'],list) or len(value['facts'])>8: raise ValueError('语义事实数量无效')
    for index,fact in enumerate(value['facts']):
        if not isinstance(fact,dict) or set(fact)!={'category','content','entities','evidence'} or fact['category'] not in FACT_KINDS or not isinstance(fact['content'],str) or not 1<=len(fact['content'])<=400 or not isinstance(fact['entities'],list) or len(fact['entities'])>4 or any(not isinstance(name,str) or not 1<=len(name)<=100 for name in fact['entities']) or not isinstance(fact['evidence'],str) or not 1<=len(fact['evidence'])<=400: raise ValueError('语义事实缺少可定位的原文证据')
        fact['evidence'],receipt=resolve_evidence(fact['evidence'],source)
        if receipt: resolutions.append(dict(receipt,field='facts',index=index))
    return dict(value,source_hash=digest(source),method='模型语义摘要（有来源证据，非正式事实）',evidence_resolutions=resolutions)

def accept_memory(store,did,revision,value,connection=None):
    if not value: return False
    document=store.document(did)
    if document['head']!=revision or digest(document['text'])!=value['source_hash']: return False
    memories=store.setting('v2_memories',{})
    memories[did]=dict(value,project_id=store.metadata()['id'],document_id=did,title=document['title'],kind=document['kind'],source_revision=revision,complete=False)
    if connection is None: store.set_setting('v2_memories',memories)
    else: connection.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('v2_memories',json.dumps(memories,ensure_ascii=False)))
    return True

class ProjectMemory:
    def __init__(self,store): self.store=store
    def propose_fact(self,did,index):
        from app.core.knowledge import FactService
        record=self.refresh().get(did,{})
        if not isinstance(index,int) or isinstance(index,bool) or not 0<=index<len(record.get('facts',[])): raise ValueError('先选择当前版本的语义事实')
        fact=record['facts'][index]; source=self.store.document(did)
        if record['source_revision']!=source['head'] or record['source_hash']!=digest(source['text']): raise ValueError('记忆来源已变化，请重新核对')
        block=next((b for b in source['blocks'] if fact['evidence'] in b['text']),None)
        if not block: raise ValueError('证据跨越段落或已无法定位，不能作为事实候选')
        service=FactService(self.store); name=(fact['entities'] or [{'character':'人物','relationship':'人物关系','event':'事件','foreshadow':'伏笔'}[fact['category']]])[0]
        entity=next((e['id'] for e in service.entities() if e['name']==name),None) or service.add_entity(name,'character' if fact['category'] in {'character','relationship'} else 'other')
        with self.store.connection(write=True) as con:
            current=con.execute('SELECT head FROM documents WHERE id=?',(did,)).fetchone()
            if not current or current['head']!=source['head']: raise ValueError('来源版本已变化，未保存候选')
            fid=service.propose(entity,fact['content'],source_document_id=did,source_revision=source['head'],source_block_id=block['block_id'],evidence=fact['evidence'],_connection=con)
            row=con.execute('SELECT value FROM settings WHERE key=?',('v2_fact_categories',)).fetchone(); categories=json.loads(row[0]) if row else {}; categories[fid]=fact['category']; con.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('v2_fact_categories',json.dumps(categories,ensure_ascii=False)))
        return fid
    def refresh(self):
        project=self.store.metadata()['id']; old=self.store.setting('v2_memories',{}); current={}
        for row in self.store.documents():
            if row['kind']=='reference': continue
            document=self.store.document(row['id']); text=document['text'].strip()
            if not text: continue
            record=old.get(row['id'],{})
            if record.get('project_id')!=project or record.get('source_revision')!=document['head'] or record.get('source_hash')!=digest(document['text']):
                excerpt=text if len(text)<=600 else text[:280]+'\n【中间正文未包含在摘要，可分页读取】\n'+text[-280:]
                record=dict(project_id=project,document_id=row['id'],title=row['title'],kind=row['kind'],source_revision=document['head'],source_hash=digest(document['text']),summary=excerpt,method='当前原文自动节选',complete=len(text)<=600)
            current[row['id']]=record
        if current!=old: self.store.set_setting('v2_memories',current)
        return current
    def context(self,limit=5000):
        values=self.refresh(); used=0; result=[]; omitted=[]
        for did,record in values.items():
            size=len(json.dumps(record,ensure_ascii=False))
            if used+size>limit: omitted.append(did); continue
            result.append(record); used+=size
        return dict(project_id=self.store.metadata()['id'],documents=result,omitted_documents=omitted,note='每条记录标明模型语义摘要或原文节选；摘要不能证明全文已检查。当前正文与用户设定优先，旧来源版本不会复用。')
