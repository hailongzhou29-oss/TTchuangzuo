"""Run the existing acceptance checks once and write an inspectable delivery receipt."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
batch=(ROOT/'启动TT创作助手开发版.bat').read_bytes()
if any(byte>=128 for byte in batch) or b'\n' in batch.replace(b'\r\n',b''):
    raise ValueError('批处理入口必须使用ASCII内容和Windows CRLF换行')
evidence=ROOT/'docs'/'evidence'
evidence.mkdir(exist_ok=True)
jobs=[
    ('批处理完整入口检查',[os.environ.get('COMSPEC','cmd.exe'),'/d','/c',str(ROOT/'启动TT创作助手开发版.bat'),'-CheckOnly']),
    ('数据与适配器自动化',[sys.executable,'-m','unittest','discover','-s','tests','-v']),
    ('源码启动',[sys.executable,'tools/source_smoke.py']),
    ('基础编辑界面',[sys.executable,'tools/ui_acceptance.py','--scale','1']),
    ('文字助手',[sys.executable,'tools/text_ui_acceptance.py']),
    ('图片助手',[sys.executable,'tools/image_ui_acceptance.py']),
    ('结构化创作与案例',[sys.executable,'tools/writing_ui_acceptance.py']),
    ('规则与事实',[sys.executable,'tools/knowledge_ui_acceptance.py']),
    ('预算备份与布局恢复',[sys.executable,'tools/maintenance_ui_acceptance.py']),
    ('项目导入备份与回收',[sys.executable,'tools/project_ui_acceptance.py']),
]
receipt=dict(created=datetime.now(timezone.utc).isoformat(),scope='现有开发试用版，UI精修后置；不执行真实模型或图片生成',
             original_handoff_complete=False,checks=[])
environment=dict(os.environ,PYTHONIOENCODING='utf-8')
for index,(name,command) in enumerate(jobs,1):
    print(f'CHECK {index}/{len(jobs)} {name}',flush=True)
    started=time.monotonic()
    result=subprocess.run(command,cwd=ROOT,env=environment,capture_output=True,text=True,encoding='utf-8',errors='replace',
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    log=evidence/('delivery_'+str(index).zfill(2)+'.log')
    log.write_text(result.stdout+result.stderr,encoding='utf-8')
    receipt['checks'].append(dict(name=name,passed=result.returncode==0,exit_code=result.returncode,
                                 elapsed_seconds=round(time.monotonic()-started,2),log=log.name))
    (evidence/'delivery_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(('PASS ' if result.returncode==0 else 'FAIL ')+name,flush=True)
    if result.returncode:
        print('\n'.join((result.stdout+result.stderr).splitlines()[-12:]),flush=True)
        raise SystemExit(result.returncode)
print('DELIVERY_CHECK_PASS',flush=True)
