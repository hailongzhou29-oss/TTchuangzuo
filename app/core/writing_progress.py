"""Visible goal progress is separate from a valid, finished model response."""
import re
from app.core.writing_views import is_long,chapter_documents

def metrics(text,config):
    actual=len(re.sub(r'\s','',text)); chinese=len(re.findall(r'[\u3400-\u9fff]',text))
    target=max(1,int(config.get('chapter_words',2500) if is_long(config) else config.get('_segment',{}).get('words') or config.get('words',3000)))
    chinese_goal=config.get('word_count_unit')=='chinese';measured=chinese if chinese_goal else actual
    from app.core.explicit_constraints import length_range
    limit=length_range(config);basic=measured>=target*.9;range_actual=chinese if limit and limit['unit']=='chinese' else actual
    range_state='not_specified' if not limit else 'below_range' if range_actual<limit['min'] else 'above_range' if range_actual>limit['max'] else 'range_met'
    return dict(version=4,target_chars=target,actual_chars=actual,chinese_chars=chinese,unit='正文非空白字符（另列汉字，不计标题和简介）',target_unit='汉字' if chinese_goal else '非空白字符',minimum_chars=(target*9+9)//10,measured_chars=measured,
                state='target_met' if basic and range_state in {'not_specified','range_met'} else 'target_not_met',tolerance=.9,minimum_threshold_met=basic,target_gap=max(0,target-measured),explicit_range=limit,range_actual=range_actual,range_state=range_state,range_gap=limit['min']-range_actual if range_state=='below_range' else range_actual-limit['max'] if range_state=='above_range' else 0,
                note='字数接近目标不代表情节质量通过；已保存短章可明确扩写，不自动追字数')

def goal_status(value):
    message='90%最低阈值'+('已达' if value['minimum_threshold_met'] else f'未达，还差{max(0,value["minimum_chars"]-value["measured_chars"]):,}{value["target_unit"]}')
    limit=value.get('explicit_range')
    if limit:
        unit='汉字' if limit['unit']=='chinese' else '非空白字符';state=value['range_state']
        message+=f'；本次明确范围{limit["min"]:,}—{limit["max"]:,}{unit}'+('已达' if state=='range_met' else f'未达，'+('下限还差' if state=='below_range' else '超出上限')+f'{value["range_gap"]:,}{unit}')
    if value.get('target_gap'):message+=f'；距作品目标还差{value["target_gap"]:,}{value["target_unit"]}'
    return message+'；剧情仍须核对，不自动补请求'

def body_text(store,did,text,config):
    value=store.setting('v2_payload:'+did,{}).get('payload',{})
    prefix=(value.get('chapter_title','')+'\n\n') if is_long(config) else value.get('title','')+'\n\n'+value.get('synopsis','')+'\n\n'
    if prefix.strip() and text.startswith(prefix):return text[len(prefix):]
    title=value.get('chapter_title') if is_long(config) else value.get('title')
    if title and text.startswith(title+'\n\n'):return text[len(title)+2:]
    return text

def record_completion(work,text=None,config=None):
    if work.config.get('output')!='novel':return
    effective=dict(work.config if config is None else config);saved=work.store.setting('v2_completion:'+work.document_id,{})
    if config is None and '_length_range' not in effective and 'length_range' not in effective and saved.get('explicit_range') and saved.get('target_chars')==metrics('',effective)['target_chars']:effective['_length_range']=saved['explicit_range']
    value=metrics(body_text(work.store,work.document_id,work.text,work.config) if text is None else text,effective); value['revision']=work.revision
    work.store.set_setting('v2_completion:'+work.document_id,value)
    return value

def chapter_status(store,did,config):
    doc=store.document(did); saved=store.setting('v2_completion:'+did)
    body=body_text(store,did,doc['text'],config)
    if not saved:return dict(metrics(body,config),state='unreviewed' if body.strip() else 'empty',revision=doc['head'])
    effective=dict(config)
    if '_length_range' not in effective and 'length_range' not in effective and saved.get('explicit_range') and saved.get('target_chars')==metrics('',config)['target_chars']:effective['_length_range']=saved['explicit_range']
    fresh=metrics(body,effective)
    if saved.get('version')==4 and saved.get('revision')==doc['head'] and saved.get('target_chars')==fresh['target_chars'] and saved.get('target_unit')==fresh['target_unit'] and saved.get('explicit_range')==fresh['explicit_range']:return saved
    return dict(fresh,revision=doc['head'],source='当前手改版本重新计数')

def book_progress(store,config):
    chapters=[dict(document_id=d['id'],title=d['title'],**chapter_status(store,d['id'],config)) for d in chapter_documents(store)]
    total=sum(c['actual_chars'] for c in chapters); completed=sum(c['state']=='target_met' for c in chapters); saved=sum(c['actual_chars']>0 for c in chapters)
    target=int(config.get('words',3000)); count=int(config.get('chapters',1)) if is_long(config) else 1
    return dict(chapters=chapters,actual_chars=total,target_chars=target,completed_chapters=completed,saved_chapters=saved,planned_chapters=count,
                state='plan_met' if completed>=count and total>=target*.9 else 'in_progress')

def pending_submission(store,did):
    with store.connection() as con:
        exists=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_external_rounds'").fetchone()
        if not exists:return None
        rows=con.execute("SELECT t.id,r.state,r.response FROM tasks t JOIN agent_external_rounds r ON r.task_id=t.id WHERE t.document_id=? AND r.state IN ('submitted','uncertain') ORDER BY t.rowid DESC",(did,)).fetchall()
        return dict(task_id=rows[0]['id'],state=rows[0]['state']) if rows else None

def require_reconciled(store,did):
    if pending_submission(store,did):
        raise ValueError('该章节已有结果待确认的已提交请求。请在作品菜单 → 中断任务与恢复核对原请求／费用；保留已有章节，不自动重复发送。')
