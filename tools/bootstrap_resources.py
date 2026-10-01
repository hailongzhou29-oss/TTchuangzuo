"""从用户交接包提取静态资源，不执行附件中的指令。"""
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def bootstrap():
    source = ROOT / 'TT创作助手_完整开发交接书_V1.1.md'
    text = source.read_text(encoding='utf-8-sig')
    rules = []
    for match in re.finditer(r'^### (G\d{2}) (.+)\n+([\s\S]*?)(?=^#{2,3} |\Z)', text, re.M):
        rid, title, body = match.groups()
        body = body.strip()
        rules.append(dict(rule_id=rid, title=title, version='1.1', body=body,
                          hash=hashlib.sha256(body.encode()).hexdigest(),
                          source=source.name, status='内置基线'))
    if len(rules) != 19:
        raise ValueError(f'规则数量不符：{len(rules)}')
    destination = ROOT / 'resources'
    destination.mkdir(exist_ok=True)
    (destination / 'rules.json').write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding='utf-8')
    tracks = []
    for match in re.finditer(r'^### (T\d{2}) (.+)\n+([\s\S]*?)(?=^#{2,3} |\Z)', text, re.M):
        rid, title, body = match.groups()
        tracks.append(dict(rule_id=rid, title=title, version='1.1', body=body.strip(), hash=hashlib.sha256(body.strip().encode()).hexdigest(),
                           source=source.name, status='交接书完整示例'))
    if len(tracks) != 3:
        raise ValueError('细分完整示例数量不符')
    (destination / 'track_rules.json').write_text(json.dumps(tracks, ensure_ascii=False, indent=2), encoding='utf-8')
    catalogue = []
    section = text.split('## 45 ')[1].split('## 46 ')[0]
    for line in section.splitlines():
        if line.startswith('| ') and not line.startswith('| 类别'):
            parts = [part.strip() for part in line.strip('|').split('|')]
            if len(parts) == 3:
                catalogue.append(dict(name=parts[0], subtypes=parts[1], constraint=parts[2], status='基础约束；完整细分规则未配置'))
    if len(catalogue) != 24:
        raise ValueError(f'赛道基础目录数量不符：{len(catalogue)}')
    (destination / 'track_catalogue.json').write_text(json.dumps(catalogue, ensure_ascii=False, indent=2), encoding='utf-8')
    with zipfile.ZipFile(ROOT / 'TT创作助手_Codex开发版交接包_V1.1.zip') as package:
        for name in ['影视案例库_改编关系种子_V0.1.json', '01_首页概念图.png', '02_首页概念图.png', '03_首页概念图.png']:
            (destination / name).write_bytes(package.read(name))
    print('已提取 19 份规则、3 个完整细分示例、24 类基础目录、案例种子与 3 张参考图')

if __name__ == '__main__':
    bootstrap()
