"""Bounded synthetic cross-chapter production UI review and factual memory check."""
import json,os,sys,time
from pathlib import Path
from dataclasses import replace
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from app.ui.v2_window import MainWindow
from app.core.services import Workspace
from app.core.work_context import CurrentWork
from app.core.selection import selection
from app.core.full_book_review import FullBookReview
from app.core.project_memory import ProjectMemory
from app.core.budget import BudgetBook
from app.core.files import write_json
from app.storage.project import ProjectStore
from app.storage.connections import ConnectionStore
from app.core.tasks import TaskService
from app.providers.contracts import redact
from merged_live_acceptance import StoredConnections,PRICE

def main():
    out=ROOT/'docs/evidence/upgrade_live_book'; out.mkdir(parents=True,exist_ok=True); path=out/'results.json'
    repair='--repair' in sys.argv
    if path.exists() and not repair: raise SystemExit('已有真实整本检查记录，先对账，不重复运行')
    if repair and not path.exists(): raise ValueError('没有可对账的原记录')
    base=json.loads((ROOT/'backups/upgrade_round_20261002/baseline.json').read_text(encoding='utf-8')); prior=json.loads((ROOT/'docs/evidence/live_merged/ds.json').read_text(encoding='utf-8')); store=ProjectStore(Path(prior['project_root'])); project=store.metadata()['id']; book=BudgetBook(Path(base['budget_root']))
    if project!=base['project_id']: raise ValueError('原预算项目不匹配，未提交')
    def budget():
        rows=book.rows(project); total=sum((Decimal(r['amount']) for r in rows if r['state']!='released'),Decimal(0)); return dict(cumulative_cny=str(total),remaining_cny=str(Decimal('10')-total),unknown=[r['id'] for r in rows if r['state'] in {'reserved','unconfirmed'}],calls=len([r for r in rows if r['state']!='released']))
    before=budget()
    if before['unknown'] or Decimal(before['remaining_cny'])<1: raise ValueError('预算或费用未确认，停止')
    source=ConnectionStore(Path(os.environ['LOCALAPPDATA'])/'TTChuangzuo'); original=next(c for c in source.all() if c.provider=='deepseek' and c.enabled)
    if original.model!='deepseek-flash': raise ValueError('模型价表不匹配')
    if repair:
        report=json.loads(path.read_text(encoding='utf-8'))
        if report['state']!='failed' or report['project_id']!=project: raise ValueError('不是本次已核对的失败记录')
        report.setdefault('previous_failures',[]).append(report.pop('error')); report['repair_before']=before; report['state']='repairing'
    else: report=dict(state='started',project_id=project,cap_cny='10',before=before,records=[],checks=[],controlled_chapters=[])
    write_json(path,report)
    def record(**value): report['records'].append(value); report['after']=budget(); write_json(path,report); print(json.dumps(value,ensure_ascii=True),flush=True)
    def check(name,value):
        report['checks'].append(dict(check=name,passed=bool(value))); write_json(path,report)
        if not value: raise AssertionError(name)
    app=QApplication([])
    def spin(ms=80):
        end=time.monotonic()+ms/1000
        while time.monotonic()<end: app.processEvents(); time.sleep(.01)
    def wait(window):
        stop=time.monotonic()+430
        while window.active_task and time.monotonic()<stop: spin(50)
        if window.active_task: window.stop_task(); raise TimeoutError('分组检查等待超时，不重发')
        if budget()['unknown']: raise ValueError('分组费用存在未知状态，停止下一组')
    try:
        connections=StoredConnections(Path(base['budget_root']),source); c=replace(original,max_output=4096,context_limit=65536,timeout=120,json_mode=True,pricing=PRICE); connections.save(c); store.set_setting('budget_settings',dict(monetary_limits=dict(currency='CNY',task_amount='1',project_amount='10')))
        config=selection('novel'); config.update(length='长篇连载',words=10000,chapters=3,chapter_words=3300); store.set_setting('v2_selection',config); store.set_setting('v2_kind','novel')
        paragraphs=[
            '同一晚19:00，青禾的右手完好无伤，从未受伤。青禾是墨川的姐姐，双方出生年份从未改变。唯一的红钥匙已经投入熔炉彻底烧毁，世界上不存在第二把同样的钥匙。车站的大门牢牢锁着。',
            '同一晚19:00，青禾的右手受伤且正在包扎，在此之前已伤了三天，没有治疗或痊愈过程。青禾是墨川的妹妹，双方出生年份从未改变。车站大门已经敞开，从未上锁。本文没有叙述任何改变关系或改变门状态的事件。',
            '同一晚19:00，青禾从抽屉拿出原先那把唯一的红钥匙，钥匙完好无损，从未重铸或修复，也不是复制品。青禾是墨川的妹妹，右手仍然包扎着。'
        ]
        filler='雨沿着旧站台边缘流下，玻璃映着灰蓝的天空。铜灯在窗边投下暖色的光，空轨道通向看不清的远处，潮湿石阶没有脚印。'
        for index,prefix in enumerate(paragraphs):
            if repair: break
            text=prefix+'\n'
            while len(text)<3200: text+=filler+'\n'
            text+='抽屉底部还有一只尚未开启的蓝盒，盒内的旧地图用途未知。'
            did=store.add_document('合成长篇 第'+str(index+1)+'章',kind='小说'); store.set_setting('v2_document:'+did,True); work=CurrentWork.load(store,did,config); work.edit(text); work.save(); report['controlled_chapters'].append(dict(id=did,revision=work.revision,characters=len(text),seeded_facts=prefix)); write_json(path,report)
        selected=report['controlled_chapters'][0]['id']; store.set_setting('v2_last_document',selected); workspace=Workspace(ROOT/'docs/evidence/live_merged/ds_data'); prefs=out/'ui_prefs/preferences.json'; window=MainWindow(workspace,ROOT/'resources',prefs); window.connections=connections; window.options['default_connection']=c.id; window.assistant.refresh_models(); window.open_project(store.root); window.select_document(selected); window.show(); spin(); window.creators['novel'].set_view(1); window.set_assistant_visible(True)
        if repair:
            review=FullBookReview(store,ROOT/'resources',connections); review.retry_failed_part(report['review_id']); window.resume_full_review(report['review_id'])
        else:
            instruction='整本检查，不改稿。重点比较合成长篇三章中青禾右手受伤状态、青禾与墨川的姐弟顺序、唯一红钥匙烧毁后又完好的矛盾，检查同一晚19:00且无解释的变化；综合各章证据并引用来源。此前独立测试短文也照实列入读取范围，不能声称未提供正文已检查。'; window.assistant.input.setPlainText(instruction); QTest.mouseClick(window.assistant.send_button,Qt.MouseButton.LeftButton)
        spin(20)
        if not window.active_task: raise ValueError('实际整本任务未启动')
        rid=window.active_task['snapshot']['full_review_id']; report['review_id']=rid; report['project_root']=str(store.root); record(event='review_started',review_id=rid); wait(window); review=FullBookReview(store,ROOT/'resources',connections); first=review.get(rid); record(event='first_group_completed',state=first['state'],parts_completed=sum(p['state']=='completed' for p in first['parts']),total_parts=len(first['parts'])); window.grab().save(str(out/'01-partial-review.png')); window.close(); spin()
        window=MainWindow(workspace,ROOT/'resources',prefs); window.connections=connections; window.options['default_connection']=c.id; window.assistant.refresh_models(); window.open_project(store.root); window.select_document(selected); window.show(); spin(); rounds=1
        while review.get(rid)['state']=='budget_paused' and rounds<3:
            rounds+=1; window.resume_full_review(rid); spin(); wait(window); current=review.get(rid); record(event='next_group_completed',group=rounds,state=current['state'],parts_completed=sum(p['state']=='completed' for p in current['parts']))
        final=review.get(rid); result=review.result(final); report['coverage']=result['coverage']; report['synthesis']=result['synthesis']; write_json(path,report); check('all actual provided parts are read and cross-chapter synthesis is verified',final['state']=='completed' and result['coverage']['completed_characters']==result['coverage']['total_characters'] and result['coverage']['cross_chapter_completed']); combined='\n'.join(i['issue']+' '+i['left']['quote']+' '+i['right']['quote'] for i in final['synthesis']['contradictions']); check('three seeded contradictions have actual cited evidence',all(term in combined for term in ('右手','姐姐','红钥匙')) and len(final['synthesis']['contradictions'])>=3); before_replay=budget(); review.run(rid,__import__('app.providers.contracts',fromlist=['CancelToken']).CancelToken()); check('completed review reopens without resubmitting paid parts',before_replay==budget()); (out/'cross-chapter-report.md').write_text(result['text'],encoding='utf-8'); window.creators['novel'].set_view(1); window.grab().save(str(out/'02-cross-chapter-completed.png'))
        did=report['controlled_chapters'][2]['id']; window.select_document(did); window.assistant.input.setPlainText('只讨论当前章中人物状态、青禾与墨川的关系、红钥匙事件和蓝盒伏笔，简短回答，不改稿，不调用工具。'); QTest.mouseClick(window.assistant.send_button,Qt.MouseButton.LeftButton); spin(20)
        if not window.active_task: raise ValueError('真实语义记忆任务未启动')
        task_id=window.active_task['snapshot']['task_id']; wait(window); task=TaskService(store,ROOT/'resources',connections).get(task_id); record(event='memory_result',task_id=task_id,status=task['state'],used_calls=task['result']['used_calls'],memory_warning=task['result'].get('memory_warning'))
        record_value=ProjectMemory(store).refresh()[did]; report['memory_record']=record_value; check('real source-bound semantic memory exposes all four factual kinds',task['state']=='completed' and {f['category'] for f in record_value.get('facts',[])}=={'character','relationship','event','foreshadow'}); window.open_memory(); spin(); window.grab().save(str(out/'03-real-memory-source.png')); window.close(); spin(); report['state']='passed'; record(event='completed',groups=rounds)
    except Exception as exc: report['state']='failed'; report['error']=redact(str(exc)); print(json.dumps(dict(state='failed',error=report['error']),ensure_ascii=True),flush=True)
    finally: report['after']=budget(); write_json(path,report)
    return int(report['state']!='passed')
if __name__=='__main__': raise SystemExit(main())
