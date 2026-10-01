"""Isolated runtime-owner fixture. Never connects to an external provider."""
import argparse
import base64
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.core.cover import default_cover
from app.core.image_service import ImageService
from app.providers.contracts import CancelToken
from app.providers.image_contracts import ImageResult
from app.storage.image_connections import ImageConnectionStore
from app.storage.project import ProjectStore

parser=argparse.ArgumentParser()
parser.add_argument('phase',choices=['submit','query'])
parser.add_argument('project')
parser.add_argument('settings')
parser.add_argument('image')
parser.add_argument('--task-id')
args=parser.parse_args()
store=ProjectStore(Path(args.project))
store.check()
if store.setting('runtime_test_fixture') is not True:
    raise ValueError('运行时测试只允许明确标记的隔离项目')
connections=ImageConnectionStore(Path(args.settings))
connection=connections.get('runtime_image')
service=ImageService(store,ROOT/'resources',connections)

class Fixture:
    queries=0
    downloads=0
    def submit(self,connection,secret,snapshot,cancel,**kwargs):
        return ImageResult(status='accepted',job_id='runtime-job',model=connection.model,accepted=True)
    def query(self,connection,secret,job_id,cancel):
        self.queries+=1
        print(json.dumps(dict(ready=True,pid=os.getpid())),flush=True)
        if sys.stdin.readline().strip()!='release':
            raise ValueError('隔离测试未收到继续信号')
        image=Path(args.image).read_bytes()
        return ImageResult(status='generated',job_id=job_id,model=connection.model,
                           items=[dict(b64_json=base64.b64encode(image).decode())],accepted=True)
    def bytes_for(self,item,connection,cancel):
        self.downloads+=1
        return base64.b64decode(item['b64_json'])

fixture=Fixture()
if args.phase=='submit':
    snapshot=service.prepare(connection,'隔离固定响应，不调用供应商',default_cover('隔离封面','小说'),development_test=True)
    result=service.execute(snapshot,CancelToken(),provider=fixture)
    print(json.dumps(dict(task_id=snapshot['task_id'],pid=os.getpid(),status=result['status'])),flush=True)
else:
    result=service.query(task_id=args.task_id,cancel=CancelToken(),provider=fixture)
    print(json.dumps(dict(status=result['status'],queries=fixture.queries,downloads=fixture.downloads)),flush=True)
