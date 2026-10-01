"""Fingerprint the delivered sources; exclude runtime data, secrets and caches."""
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def fingerprint(path):
    value=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):
            value.update(block)
    return value.hexdigest()

files=[]
for directory in ('app','tools','resources','tests'):
    for path in (ROOT/directory).rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and not path.is_symlink() and path.resolve().is_relative_to(ROOT):
            files.append(path)
for filename in ('requirements.txt','README.md','THIRD_PARTY_NOTICES.md','启动TT创作助手开发版.bat'):
    path=ROOT/filename
    if path.is_file():
        files.append(path)
manifest=dict(created=datetime.now(timezone.utc).isoformat(),scope='现有开发试用版源码索引；不代表完整交接或真实通道验收',
    excluded=['user_data','logs','local.runtime.json','本机偏好与凭据','Python缓存'],
    files={path.relative_to(ROOT).as_posix():fingerprint(path) for path in sorted(files)})
output=ROOT/'docs'/'evidence'/'delivery_source_manifest.json'
output.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('SOURCE_MANIFEST_WRITTEN',len(manifest['files']))
