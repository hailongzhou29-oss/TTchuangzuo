"""Explicitly authorized synthetic live checks. No secret is copied or printed."""
import argparse,json,os,sys,time
from decimal import Decimal
from pathlib import Path
from dataclasses import replace
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.core.services import Workspace
from app.core.work_context import CurrentWork
from app.core.selection import selection
from app.core.creation_flow import CreationFlow
from app.core.agent_candidates import AgentCandidates
from app.core.files import write_json,digest
from app.storage.connections import ConnectionStore
from app.providers.contracts import Connection,CancelToken,redact
from app.providers.http_text import HttpTextProvider
from app.providers.codex_text import CodexTextProvider
from PySide6.QtWidgets import QApplication
from app.ui.v2_window import MainWindow
from app.ui.cover_panel import CoverPanel
from app.providers.image_contracts import ImageConnection

PRICE=dict(currency='CNY',version='2026-10-02-peak',source='https://api-docs.deepseek.com/zh-cn/quick_start/pricing/',input_per_million=2,cached_read_per_million=.04,output_per_million=8,input_includes_cached=True)
class StoredConnections(ConnectionStore):
    def __init__(self,root,source): super().__init__(root); self.source=source
    def secret_snapshot(self,c): return self.source.secret_snapshot(c)
class RealProvider:
    def __init__(self): self.calls=0; self.http=HttpTextProvider()
    def generate(self,*args,**kw):
        if self.calls>=12: raise ValueError('达到本轮真实请求次数上限')
        self.calls+=1; kw.setdefault('thinking',False); return self.http.generate(*args,**kw)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('channel',choices=['ds','codex','cover']); parser.add_argument('--repair',action='store_true'); args=parser.parse_args()
    if args.repair and args.channel!='ds': raise SystemExit('有界复验仅用于已确认失败的文本合同')
    out=ROOT/'docs/evidence/live_merged'; out.mkdir(parents=True,exist_ok=True); reportfile=out/(args.channel+('_repair' if args.repair else '')+'.json')
    if reportfile.exists(): raise SystemExit('已有本轮持久化测试记录；不自动重复真实请求。')
    report=dict(channel=args.channel,started=time.time(),state='started',records=[],paid_api_cap_cny=10,synthetic_project=True)
    write_json(reportfile,report)
    def record(**value): report['records'].append(value); write_json(reportfile,report); print(json.dumps(value,ensure_ascii=True),flush=True)
    app=QApplication([]); prefs=out/(args.channel+'_prefs'); workspace=Workspace(out/(args.channel+'_data'))
    if args.repair:
        from app.storage.project import ProjectStore
        previous=json.loads((out/'ds.json').read_text(encoding='utf-8'))
        if previous['state']!='failed' or any(r['state'] in {'reserved','unconfirmed'} for r in previous.get('budget_rows',[])): raise ValueError('原费用或接受状态未知，不允许复验')
        store=ProjectStore(Path(previous['project_root']))
    else: store=workspace.create('合并修复隔离实测_'+args.channel,'小说')
    store.set_setting('system_test_project',True); report['project_root']=str(store.root)
    work=CurrentWork.load(store,store.documents()[0]['id'],selection('novel')); work.config.update(words=120,chapters=1,chapter_words=120,idea='写一个约120字的微型故事：阿宁找到林远留下的旧信，两人决定守住旧车站。不要加入其他角色。')
    if not args.repair: work.edit('阿宁把旧信藏进抽屉。林远在旧车站的门外等她。'); work.save()
    try:
        if args.channel=='ds':
            source=ConnectionStore(Path(os.environ['LOCALAPPDATA'])/'TTChuangzuo'); original=next(c for c in source.all() if c.provider=='deepseek' and c.enabled)
            if original.model!='deepseek-flash': raise ValueError('保存模型与本轮核验价表不匹配，未提交')
            c=replace(original,max_output=2048,context_limit=65536,timeout=120,stream=True,pricing=PRICE,json_mode=True)
            connections=StoredConnections(prefs,source); connections.save(c); store.set_setting('budget_settings',dict(monetary_limits=dict(currency='CNY',task_amount='1',project_amount='10'))); flow=CreationFlow(work,ROOT/'resources',connections); provider=RealProvider()
            def execute(task,instruction,selected=(0,0)):
                snap=flow.prepare(c,task,instruction,selected); snap['tools_enabled']=False; snap['test_non_thinking']=True
                record(event='prepared',task=task,task_id=snap['task_id'],model=c.model,input_estimate=snap['estimated_input_tokens'])
                result=flow.service.execute(snap,CancelToken(),provider=provider)
                record(event='result',task=task,task_id=snap['task_id'],status=result['status'],used_calls=result['used_calls'],usage=result['usage'],memory_updated=bool(result.get('semantic_memory')),memory_warning=result.get('memory_warning'),error=result.get('error'))
                amounts=flow.service.budget_book.rows(store.metadata()['id']); report['budget_rows']=amounts; report['estimated_cny']=str(sum((Decimal(r['amount']) for r in amounts if r['state']!='released'),Decimal(0))); report['request_count']=provider.calls; write_json(reportfile,report)
                if result['status']!='completed' or any(r['state'] in {'reserved','unconfirmed'} for r in amounts): raise ValueError('真实任务未完成或费用未可靠确认；停止后续请求')
                return snap,result
            if not args.repair:
                snap,result=execute('generate',work.config['idea']); flow.apply(snap,result); base=work.text
                record(event='assertion',check='真实生成及语义摘要',passed=bool(base.strip() and result.get('semantic_memory')),body_hash=digest(base))
                snap,result=execute('discuss','只讨论：上一条旧信故事里两位角色决定守住什么地方？一句话回答，不改正文。'); flow.apply(snap,result)
                record(event='assertion',check='连续对话及不改稿',passed=work.text==base and '车站' in result['candidate']['text'])
            else: base=work.text
            end=base.find('。')+1 or len(base); snap,result=execute('modify','仅修改已选第一句，让动作更果断；保留人物姓名、旧信、地点，不改其他文字。',(0,end)); candidates=AgentCandidates(store); cid=candidates.save(snap,result); candidates.adopt(cid,work)
            scoped=work.text.endswith(base[end:]); candidates.undo(cid,work); record(event='assertion',check='定点候选采用及撤销',passed=scoped and work.text==base)
            snap,result=execute('inspect','只检查当前微型故事的人物、旧信与车站是否一致；不续写、不改稿。两句话以内。'); flow.apply(snap,result); record(event='assertion',check='只检查不改稿',passed=work.text==base)
            (out/'真实合成小说.md').write_text(work.text,encoding='utf-8'); window=MainWindow(workspace,ROOT/'resources',prefs/'preferences.json'); window.connections=connections; window.options['default_connection']=c.id; window.assistant.refresh_models(); window.open_project(store.root); window.show(); app.processEvents(); window.grab().save(str(out/'ds-real-ui.png')); window.close()
        elif args.channel=='codex':
            p=CodexTextProvider(); detected=p.detect(login=True)
            if not detected['logged_in']: raise ValueError('当前正常用户上下文未登录；未启动登录或模型请求')
            connections=ConnectionStore(prefs); c=Connection('live_merged_codex','Codex 最小隔离实测','codex','',max_output=128,timeout=90); connections.save(c); flow=CreationFlow(work,ROOT/'resources',connections); snap=flow.prepare(c,'discuss','只回复“旧信已收到”，不使用工具、不修改文件。'); snap.update(tools_enabled=False,suppress_memory=True)
            record(event='prepared',task_id=snap['task_id'],version=detected['version'],model='跟随 CLI 默认模型'); result=flow.service.execute(snap,CancelToken(),provider=p); record(event='result',task_id=snap['task_id'],status=result['status'],request_id=result['request_id'],usage=result['usage'],reply=result['text'],error=result.get('error'))
            if result['status']!='completed': raise ValueError('Codex 真实文本未完成，未重试')
        else:
            if not CodexTextProvider().detect(login=True)['logged_in']: raise ValueError('当前正常用户上下文未登录；未生成图片')
            window=MainWindow(workspace,ROOT/'resources',prefs/'preferences.json'); c=ImageConnection('live_merged_cover','Codex 单张隔离实测','image_codex','',timeout=300,sizes=('1024x1024',)); window.image_connections.save(c); window.options['default_image']=c.id; window.open_project(store.root); window.show(); app.processEvents(); panel=CoverPanel(window,window.work); window.show_inline('隔离封面实测',panel); panel.prompt.setPlainText('生成单张方形小说封面背景：夜晚旧车站值班室，桌上一封旧信，门外柔和暖光，安静克制，无人物、无文字、无标识。'); panel.ratio.setCurrentText('1:1'); app.processEvents(); panel.generate(); record(event='submitted',task_id=(panel.snapshot or {}).get('task_id'),count=1,provider='image_codex')
            stop=time.monotonic()+315
            while window.active_image_task and time.monotonic()<stop: app.processEvents(); time.sleep(.03)
            if window.active_image_task: window.stop_image(); raise TimeoutError('单张任务超时，未重新提交')
            window.grab().save(str(out/'cover-real-ui.png')); app.processEvents()
            if not panel.candidate: record(event='result',status='failed',error=panel.status.text()); window.close(); raise ValueError('本次没有可核验图片，未重试或调用图片API')
            record(event='result',status='verified',task_id=panel.snapshot['task_id'],pixels=[panel.candidate['width'],panel.candidate['height']],sha256=panel.candidate['sha256']); panel.adopt(); record(event='assertion',check='真实单张预览采用',passed=bool(store.setting('active_cover'))); window.close()
        report['state']='passed' if all(r.get('passed',True) for r in report['records']) else 'failed'
    except Exception as exc:
        report['state']='failed'; report['error']=redact(str(exc)); print(json.dumps(dict(state='failed',error=report['error']),ensure_ascii=True),flush=True)
    finally: write_json(reportfile,report)
    return int(report['state']!='passed')
if __name__=='__main__': raise SystemExit(main())
