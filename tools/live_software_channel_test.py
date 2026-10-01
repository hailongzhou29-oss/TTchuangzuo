"""Explicitly authorized single real request through the application's own UI/services."""
import argparse
import getpass
import json
import os
import sys
import time
import tomllib
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.core.files import write_json
from app.core.services import Workspace
from app.providers.contracts import Connection,redact_tree
from app.providers.http_text import HttpTextProvider
from app.providers.image_contracts import ImageConnection
from app.storage.connections import ConnectionStore
from app.storage.image_connections import ImageConnectionStore
from app.ui.cover_dialog import CoverDialog
from app.ui.window import MainWindow

parser=argparse.ArgumentParser()
parser.add_argument('channel',choices=['ds','codex-image'])
args=parser.parse_args()
settings=Path(os.environ['LOCALAPPDATA'])/'TTChuangzuo'
prefs=settings/'preferences.json'
workspace=Workspace(ROOT/'user_data')
secret=None
if args.channel=='ds':
    secret=getpass.getpass('DeepSeek key (hidden input): ')
    if not secret:
        raise ValueError('未提供密钥，没有提交')
    connections=ConnectionStore(settings)
    connection=Connection('live_deepseek','DeepSeek 软件通道实测','deepseek','',
        base_url='https://api.deepseek.com',timeout=60,max_output=128,stream=True,reasoning_levels=('none',))
    models=HttpTextProvider().list_models(connection,secret)
    selected=next((name for name in ('deepseek-flash','deepseek-v4-flash','deepseek-chat') if name in models),None)
    if not selected:
        raise ValueError('没有找到本次小文本测试支持的模型，未生成')
    from dataclasses import replace
    connection=replace(connection,model=selected,verification=dict(auth_models=dict(status='已实测',checked=datetime.now(timezone.utc).isoformat(),model_count=len(models))))
    connections.save(connection,secret)
    print(json.dumps(dict(stage='models_received',models=models,chosen_model=selected),ensure_ascii=False),flush=True)
else:
    home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    config=tomllib.loads((home/'config.toml').read_text(encoding='utf-8'))
    connection=ImageConnection('live_codex_image','Codex 软件生图实测','image_codex',config['model'],
        cli_path='K:/Tools/nodejs22/codex.cmd',timeout=420,sizes=('1024x1536',))
    ImageConnectionStore(settings).save(connection)

project=workspace.create('软件通道实测_'+args.channel+'_'+datetime.now().strftime('%Y%m%d_%H%M%S'),'小说')
app=QApplication([])
window=MainWindow(workspace,ROOT/'resources',prefs)
window.open_project(project.root)
window.show()
dialog=None
started=time.monotonic()
if args.channel=='ds':
    connection=window.connections.get(connection.id)
    window.model_combo.setCurrentIndex(window.model_combo.findData(connection.id))
    window.start_text_task(connection_override=connection,test_request=True)
    active=window.active_task
    service,task_id=active['service'],active['snapshot']['task_id']
else:
    dialog=CoverDialog(project,window)
    dialog.show()
    dialog.image_model.setCurrentIndex(dialog.image_model.findData(connection.id))
    dialog.ratio.setCurrentText('2:3')
    dialog.image_size.setCurrentIndex(dialog.image_size.findData('1024x1536'))
    dialog.prompt.setPlainText('尺寸验收用真实生成图片：竖版2:3，期望原生1024x1536像素。浅灰背景上三件磨砂陶瓷几何物件：一个蓝色圆球、一个橙色圆柱和一个白色立方体，自然柔和侧光，细腻真实材质。整幅无文字、无标识、无人物。只生成一张，不用SVG或程序绘图，不裁剪或放大后冒充原生尺寸。')
    dialog.generate_background(confirmed=True)
    service,task_id=dialog.image_service,dialog.last_image_task
print(json.dumps(dict(stage='submitted_through_software',channel=args.channel,project=str(project.root),task_id=task_id),ensure_ascii=False),flush=True)
deadline=started+(75 if args.channel=='ds' else 435)
while (window.active_task if args.channel=='ds' else window.active_image_task) and time.monotonic()<deadline:
    QTest.qWait(50)
active=window.active_task if args.channel=='ds' else window.active_image_task
if active:
    active['cancel'].cancel()
    stop_deadline=time.monotonic()+20
    while (window.active_task if args.channel=='ds' else window.active_image_task) and time.monotonic()<stop_deadline:
        QTest.qWait(50)
task=service.get(task_id)
result=task.get('result') or {}
report=dict(channel=args.channel,software_entry='MainWindow.start_text_task' if args.channel=='ds' else 'CoverDialog.generate_background',
    project=str(project.root),task_id=task_id,status=task['state'],model=connection.model,development_test=task['snapshot'].get('development_test'),
    elapsed_seconds=round(time.monotonic()-started,2),actual_cost=None,result=result)
if args.channel=='codex-image':
    report['requested_size']='1024x1536'
    report['actual_images']=[dict(path=str(project.root/image['relative']),width=image['width'],height=image['height'],mime=image['mime'],sha256=image['sha256']) for image in result.get('images',[])]
if secret:
    report=redact_tree(report,secret)
evidence=ROOT/'docs'/'evidence'
write_json(evidence/('live_'+args.channel+'_software.json'),report)
print(json.dumps(report,ensure_ascii=False),flush=True)
if dialog:
    dialog.close()
window.close()
raise SystemExit(0 if task['state'] in {'completed','verified'} else 1)
