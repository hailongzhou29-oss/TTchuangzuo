"""Durable candidate-only assistant edits with atomic adoption and undo."""
import json
from app.core.files import digest
from app.storage.project import ConflictError,LockedError,now

def packed(value): return json.dumps(value,ensure_ascii=False,sort_keys=True)

def readonly_fragment_text(raw):
    """Extract display text only; never execute a tool or make a draft adoptable."""
    text=raw if isinstance(raw,str) else ''
    hidden='收到未完成或无法核对的响应片段，尚不能提取正文。原始响应保存在请求记录中；此结果仅供查看，不能采用。'
    for _ in range(3):
        value=text.strip()
        if any(mark in value for mark in ('<｜DSML｜','<function_calls>')):return hidden
        if not value.startswith(('{','[','```')):return text
        try:parsed=json.loads(value)
        except (ValueError,TypeError):return hidden
        if isinstance(parsed,dict) and set(parsed)=={'action','arguments','text'}:
            if parsed['action']!='final' or not isinstance(parsed['text'],str):return hidden
            text=parsed['text'];continue
        if isinstance(parsed,dict) and set(parsed) in ({'text','explanation'},{'title','synopsis','text'}) and isinstance(parsed.get('text'),str):return parsed['text']
        return hidden
    return hidden
def put(con,key,value): con.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,packed(value)))
def get(con,key,default=None):
    row=con.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else default

class AgentCandidates:
    def __init__(self,store):
        self.store=store
        with store.connection(write=True) as con:
            con.execute('CREATE TABLE IF NOT EXISTS agent_candidates(id TEXT PRIMARY KEY,document_id TEXT NOT NULL,snapshot TEXT NOT NULL,result TEXT NOT NULL,state TEXT NOT NULL,receipt TEXT,created TEXT NOT NULL)')
            if get(con,'agent_schema_version',0)<1:
                put(con,'agent_schema_version',1); put(con,'agent_migration',dict(version=1,completed=True,created=now(),operation='新增候选与采用记录；没有导入或替换正文'))
    def save(self,snapshot,result):
        if result['status']!='completed' or snapshot['v2_task'] not in {'modify','planning','generate'}: raise ValueError('只有完整改稿或规划结果可形成候选')
        # Freeze exact IDs/ranges. Matching repeated text elsewhere never retargets.
        snapshot=json.loads(packed(snapshot)); blocks=[]; offset=0
        with self.store.connection() as con: source=con.execute('SELECT blocks FROM revisions WHERE id=? AND document_id=?',(snapshot['base_revision'],snapshot['target_id'])).fetchone()
        if source is None: raise ValueError('候选的冻结来源版本不存在')
        for block in json.loads(source['blocks']):
            end=offset+len(block['text'])
            if snapshot['target_start']<end and snapshot['target_end']>offset: blocks.append(dict(id=block['block_id'],start=offset,end=end,hash=digest(block['text'])))
            offset=end+1
        snapshot['target_blocks']=blocks
        snapshot.setdefault('settings_hash',digest(packed(self.store.setting('v2_settings',{}))))
        with self.store.connection(write=True) as con:
            con.execute('INSERT OR IGNORE INTO agent_candidates VALUES(?,?,?,?,?,?,?)',(snapshot['task_id'],snapshot['target_id'],packed(snapshot),packed(result),'pending',None,now()))
        return snapshot['task_id']
    def row(self,cid):
        with self.store.connection() as con: row=con.execute('SELECT * FROM agent_candidates WHERE id=?',(cid,)).fetchone()
        if not row:
            legacy=next((c for c in self.store.setting('v2_candidates',[]) if c['request_id']==cid),None)
            if not legacy: raise ValueError('候选不存在于当前作品')
            with self.store.connection() as con: task=con.execute('SELECT snapshot FROM tasks WHERE id=?',(cid,)).fetchone()
            snapshot=json.loads(task['snapshot']) if task else None
            return dict(id=cid,document_id=legacy['document_id'],state='pending' if legacy['complete'] else 'partial',snapshot=snapshot,result=dict(status=legacy['state'],candidate=legacy.get('payload'),text=legacy.get('partial','')),receipt=None,created=legacy['created_at'],legacy=True,reason=legacy['reason'])
        value=dict(row); value['snapshot']=json.loads(value['snapshot']); value['result']=json.loads(value['result']); value['receipt']=json.loads(value['receipt']) if value['receipt'] else None; return value
    def pending(self):
        with self.store.connection() as con: return [dict(row) for row in con.execute("SELECT id,document_id,state FROM agent_candidates WHERE state='pending' ORDER BY rowid")]
    def applied(self):
        with self.store.connection() as con: return [dict(row) for row in con.execute("SELECT id,document_id,state FROM agent_candidates WHERE state='applied' ORDER BY rowid DESC LIMIT 5")]
    def history(self,work):
        with self.store.connection() as con: rows=con.execute('SELECT id,state,snapshot,receipt FROM agent_candidates WHERE document_id=? ORDER BY rowid',(work.document_id,)).fetchall()
        values=[]
        for row in rows:
            value=dict(row); snapshot=json.loads(value.pop('snapshot')); frozen=snapshot['frozen']
            receipt=json.loads(value.pop('receipt')) if row['receipt'] else {}
            value['can_undo']=value['state']=='applied' and not work.dirty and work.revision==receipt.get('after_revision') and digest(work.text)==receipt.get('after_hash')
            if value['state']=='pending' and (work.text!=frozen['text'] or work.revision!=frozen['revision'] or work.store.document(work.document_id)['head']!=frozen['revision'] or snapshot['settings_hash']!=digest(packed(work.store.setting('v2_settings',{})))): value['state']='stale'
            if value['state']=='pending' and snapshot.get('selection_hash') and snapshot['selection_hash']!=digest(packed(self.store.setting('v2_selection',{}))): value['state']='stale'
            if value['state']=='pending' and snapshot.get('selection_buffer_hash') and snapshot['selection_buffer_hash']!=digest(packed(work.config)): value['state']='stale'
            values.append(value)
        ids={r['id'] for r in values}
        for c in self.store.setting('v2_candidates',[]):
            if c['document_id']!=work.document_id or c['request_id'] in ids or not (c.get('payload') or c.get('partial','').strip()): continue
            row=self.row(c['request_id']); snapshot=row.get('snapshot'); frozen=c['frozen']
            state='pending' if c['complete'] else 'partial'
            if c['complete'] and (not snapshot or not snapshot.get('selection_hash') or work.dirty or work.text!=frozen['text'] or work.revision!=frozen['revision'] or self.store.document(work.document_id)['head']!=frozen['revision'] or snapshot['settings_hash']!=digest(packed(self.store.setting('v2_settings',{}))) or snapshot['selection_hash']!=digest(packed(self.store.setting('v2_selection',{})))): state='stale'
            values.append(dict(id=c['request_id'],state=state,document_id=c['document_id'],reason=c['reason'],legacy=True))
        with self.store.connection() as con:
            request_order={row['id']:row['rowid'] for row in con.execute('SELECT id,rowid FROM tasks ORDER BY rowid')}
        values.sort(key=lambda entry:request_order.get(entry['id'],-1))
        return values
    def preview(self,cid,replacement=None):
        row=self.row(cid); snapshot=row['snapshot']; payload=row['result']['candidate']
        if not snapshot or not payload: return row['result'].get('text','')
        if snapshot['v2_task']=='generate': return payload['text']
        if snapshot['v2_task']=='planning':
            from app.core.writing_views import outline_text
            return outline_text(payload)
        frozen=snapshot['frozen']; text=frozen['text'][:snapshot['target_start']]+(payload['text'] if replacement is None else replacement)+frozen['text'][snapshot['target_end']:]
        if snapshot['constraints'].get('output')=='script' and '第二部分｜完整剧本' in text:
            from app.core.speech_records import sync
            text,_=sync(text,self.store.setting('v2_speech:'+snapshot['target_id'],{}).get('records',[]),snapshot['constraints'] if snapshot['constraints'].get('script_settings') else None)
        return text
    def review(self,cid,replacement=None):
        from app.core.explicit_constraints import length_range,timeline_review
        from app.core.writing_progress import metrics,body_text
        row=self.row(cid);snapshot=row.get('snapshot') or {};payload=row['result'].get('candidate') or {};text=self.preview(cid,replacement)
        effective=dict(snapshot.get('constraints',{}));limit=length_range(effective,snapshot.get('instruction',''),snapshot.get('confirmed_facts',()))
        if limit:effective['_length_range']=limit
        goal=None
        writing=snapshot.get('v2_task') in {'modify','generate','next'}
        if effective.get('output')=='novel' and payload and writing:
            body=payload.get('raw_text',text) if snapshot.get('v2_task')=='generate' else body_text(self.store,snapshot['target_id'],text,effective)
            goal=metrics(body,effective)
        notes=timeline_review(snapshot,text) if payload and writing else []
        return dict(length=goal,timeline=notes,conflicts=[n for n in notes if n['level']=='conflict'])
    def adopt(self,cid,work,reviewed_text=None):
        row=self.row(cid); snapshot=row['snapshot']; payload=row['result']['candidate']
        if not snapshot: raise ConflictError('该结果缺少原请求基线，仅可查看，不能采用')
        frozen=snapshot['frozen']
        if row.get('legacy'):
            if not snapshot or not snapshot.get('selection_hash') or row['result']['status']!='completed': raise ConflictError('该结果缺少可核对的原请求基线，仅可查看，不能采用')
            self.save(snapshot,row['result']); row=self.row(cid)
        if snapshot['project_id']!=work.store.metadata()['id'] or row['document_id']!=work.document_id: raise ConflictError('请打开候选所属作品和文档')
        if row['state']=='applied': return row['receipt']
        if row['state']!='pending': raise ConflictError('这项候选已撤销；需要新的修改候选')
        if payload.get('needs_review'):
            if not isinstance(reviewed_text,str) or not reviewed_text.strip(): raise ValueError('未结构化回复须先核对替换正文和范围，再明确采用')
            payload=dict(payload,text=reviewed_text)
        same_buffer=frozen.get('buffer_id')==work.buffer_id
        if work.dirty or work.text!=frozen['text'] or work.revision!=frozen['revision'] or same_buffer and work.epoch!=frozen['epoch']: raise ConflictError('请求后的原稿已变化，未覆盖；请重新生成候选')
        if snapshot['settings_hash']!=digest(packed(work.store.setting('v2_settings',{}))): raise ConflictError('项目设定已变化，请重新核对候选')
        if snapshot.get('selection_hash') and snapshot['selection_hash']!=digest(packed(work.store.setting('v2_selection',{}))): raise ConflictError('创作设置已变化，旧候选未覆盖原稿')
        if snapshot.get('selection_buffer_hash') and snapshot['selection_buffer_hash']!=digest(packed(work.config)): raise ConflictError('创作设置有未保存的变化，旧候选未覆盖原稿')
        text=self.preview(cid,payload['text'] if snapshot['v2_task']=='modify' else None); records=None
        if snapshot['v2_task'] in {'modify','generate'}:
            from app.core.creation_flow import dialogues,script_body
            old=frozen['text'][snapshot['target_start']:snapshot['target_end']]
            if any(v in snapshot['instruction'] for v in ('保留台词','不要改台词','只改动作','台词不动','台词不改','台词不变','台词不要动')) and dialogues(script_body(old))!=dialogues(script_body(payload['text'])): raise LockedError('候选改变了要求保留的台词，尚未应用')
            if any(v in snapshot['instruction'] for v in ('结尾不改','保留结尾','结尾不动','结尾不变','不要改结尾')):
                ending=next((line for line in reversed(script_body(frozen['text']).splitlines()) if line.strip()),'')
                if next((line for line in reversed(script_body(text).splitlines()) if line.strip()),'')!=ending: raise ValueError('候选改变了要求保留的结尾，尚未应用')
            if work.config['output']=='script' and '第二部分｜完整剧本' in text:
                from app.core.speech_records import sync,validate_text
                if work.config.get('script_settings'): validate_text(text,work.config)
                text,records=sync(text,work.store.setting('v2_speech:'+work.document_id,{}).get('records',[]),work.config if work.config.get('script_settings') else None)
        from app.core.explicit_constraints import timeline_review
        conflicts=[note for note in timeline_review(snapshot,text) if note['level']=='conflict'] if snapshot['v2_task'] in {'modify','generate'} else []
        if conflicts:raise ConflictError(conflicts[0]['message'])
        receipt=dict(before=frozen['text'],before_revision=frozen['revision'],documents=[],settings_before={})
        with work.store.connection(write=True) as con:
            current=con.execute('SELECT d.head,r.text,r.blocks FROM documents d JOIN revisions r ON r.id=d.head WHERE d.id=?',(work.document_id,)).fetchone()
            state=con.execute('SELECT state,receipt FROM agent_candidates WHERE id=?',(cid,)).fetchone()
            if state['state']=='applied': return json.loads(state['receipt'])
            if current['head']!=frozen['revision'] or digest(current['text'])!=frozen['hash']: raise ConflictError('磁盘正文已更新，旧候选未应用')
            if snapshot['settings_hash']!=digest(packed(get(con,'v2_settings',{}))) or snapshot.get('selection_hash') and snapshot['selection_hash']!=digest(packed(get(con,'v2_selection',{}))): raise ConflictError('采用时创作设定已更新，旧候选未应用')
            identities={b['block_id']:b for b in json.loads(current['blocks'])}
            for block in snapshot['target_blocks']:
                if block['id'] not in identities or digest(identities[block['id']]['text'])!=block['hash']: raise ConflictError('目标段落已变化，未替换其他同名文字')
            def remember(key): receipt['settings_before'][key]=get(con,key)
            if snapshot['v2_task']=='planning':
                if digest(packed(get(con,'v2_plan',{})))!=snapshot['plan_hash']: raise ConflictError('规划已变化，候选未应用')
                remember('v2_plan'); put(con,'v2_plan',dict(payload,source_document_id=work.document_id,source_revision=work.revision,source_stale=False))
                from app.core.writing_views import is_long
                if is_long(work.config):
                    outline_id=get(con,'v2_outline_id'); outline=con.execute('SELECT d.head,r.text FROM documents d JOIN revisions r ON r.id=d.head WHERE d.id=?',(outline_id,)).fetchone() if outline_id else None
                    if outline:
                        manifest={d['document_id']:d['revision'] for d in snapshot['document_manifest']}
                        if manifest.get(outline_id)!=outline['head']: raise ConflictError('故事大纲已更新，旧候选未应用')
                        rid=work.store.save_document(outline_id,outline['head'],text,'采用 AI 规划候选',_connection=con); receipt['documents'].append(dict(id=outline_id,before=outline['text'],after_revision=rid))
                    else:
                        outline_id=work.store.add_document('故事大纲',text,kind='outline',_connection=con); remember('v2_outline_id'); put(con,'v2_outline_id',outline_id); put(con,'v2_document:'+outline_id,True); receipt['documents'].append(dict(id=outline_id,new=True))
                if not is_long(work.config) or outline_id!=work.document_id: rid=frozen['revision']; text=frozen['text']
            else:
                rid=work.store.save_document(work.document_id,frozen['revision'],text,'采用 AI 修改候选',_connection=con); receipt['documents'].append(dict(id=work.document_id,before=frozen['text'],after_revision=rid))
                if records is not None:
                    remember('v2_speech:'+work.document_id); put(con,'v2_speech:'+work.document_id,dict(revision=rid,records=records,text_hash=digest(text))); remember('v2_third_unsynced:'+work.document_id); put(con,'v2_third_unsynced:'+work.document_id,False)
                if work.config.get('output')=='novel':
                    from app.core.writing_progress import metrics,body_text
                    from app.core.explicit_constraints import length_range
                    effective=dict(snapshot['constraints']);limit=length_range(effective,snapshot.get('instruction',''),snapshot.get('confirmed_facts',()))
                    if limit:effective['_length_range']=limit
                    key='v2_completion:'+work.document_id; remember(key); completion=metrics(payload.get('raw_text',text) if snapshot['v2_task']=='generate' else body_text(work.store,work.document_id,text,work.config),effective); completion['revision']=rid; put(con,key,completion)
                if snapshot['v2_task']=='generate':
                    for key,value in [('v2_payload:'+work.document_id,dict(revision=rid,payload=payload)),('v2_result_config:'+work.document_id,snapshot['constraints']),('v2_plan',dict(synopsis=payload.get('synopsis',payload.get('outline','')),chapters=payload.get('plan',[]),characters=payload.get('characters',{}),source_document_id=work.document_id,source_revision=rid,source_stale=False))]: remember(key); put(con,key,value)
                    if snapshot.get('rewrite_source'): remember('v2_rewrite_source:'+work.document_id); put(con,'v2_rewrite_source:'+work.document_id,snapshot['rewrite_source'])
                    if snapshot['constraints'].get('script_settings'):
                        key='v2_adopted:'+work.document_id; remember(key); put(con,key,dict(revision=rid,values=payload.get('adopted',{}),request_id=snapshot['task_id']))
                remember('v2_memories'); memories=get(con,'v2_memories',{}); memories.pop(work.document_id,None); put(con,'v2_memories',memories)
                plan=get(con,'v2_plan',{})
                if snapshot['v2_task']!='generate' and plan.get('source_document_id')==work.document_id:
                    remember('v2_plan'); plan['source_stale']=True; put(con,'v2_plan',plan)
            receipt.update(after_hash=digest(text),after_revision=rid,settings_after={key:digest(packed(get(con,key))) for key in receipt['settings_before']})
            con.execute('UPDATE agent_candidates SET state=?,receipt=? WHERE id=?',('applied',packed(receipt),cid))
            if payload.get('needs_review'):
                reviewed=dict(row['result'],candidate=payload,reviewed=True)
                con.execute('UPDATE agent_candidates SET result=? WHERE id=?',(packed(reviewed),cid))
            memory=row['result'].get('semantic_memory')
            if memory and memory['source_hash']==digest(text):
                value=dict(memory,project_id=work.store.metadata()['id'],document_id=work.document_id,title=work.store.document(work.document_id)['title'],kind=work.store.document(work.document_id)['kind'],source_revision=rid,complete=False)
                memories=get(con,'v2_memories',{}); memories[work.document_id]=value; put(con,'v2_memories',memories)
                receipt['settings_after']['v2_memories']=digest(packed(memories)); con.execute('UPDATE agent_candidates SET receipt=? WHERE id=?',(packed(receipt),cid))
        work.text=text; work.revision=rid; work.dirty=False; work.epoch+=1; return receipt
    def undo(self,cid,work):
        row=self.row(cid); receipt=row['receipt']
        if row['state']=='undone': return False
        if row['state']!='applied' or row['document_id']!=work.document_id: raise ValueError('先打开这次修改所属的文档')
        if work.dirty or work.revision!=receipt['after_revision'] or digest(work.text)!=receipt['after_hash']: raise ConflictError('正文又发生了变化，不能直接撤销')
        with self.store.connection(write=True) as con:
            for key,expected in receipt['settings_after'].items():
                if key=='v2_memories': continue  # Derived summaries do not change manuscript intent.
                if digest(packed(get(con,key)))!=expected: raise ConflictError('设定或衍生记录又发生变化，不能直接撤销')
            for doc in receipt['documents']:
                if doc.get('new'): con.execute('UPDATE documents SET deleted=1 WHERE id=?',(doc['id'],)); continue
                rid=self.store.save_document(doc['id'],doc['after_revision'],doc['before'],'撤销 AI 候选',_connection=con)
                if doc['id']==work.document_id: restored=rid
            for key,value in receipt['settings_before'].items():
                if key=='v2_memories':
                    memories=get(con,key,{}) or {}; memories.pop(work.document_id,None); put(con,key,memories); continue
                if value is None: con.execute('DELETE FROM settings WHERE key=?',(key,))
                else: put(con,key,value)
            speech=get(con,'v2_speech:'+work.document_id)
            if speech and receipt['documents'] and any(d['id']==work.document_id for d in receipt['documents']):
                speech.update(revision=restored,text_hash=digest(receipt['before'])); put(con,'v2_speech:'+work.document_id,speech)
            con.execute('UPDATE agent_candidates SET state=? WHERE id=?',('undone',cid))
        latest=self.store.document(work.document_id); work.text=latest['text']; work.revision=latest['head']; work.epoch+=1; return True
