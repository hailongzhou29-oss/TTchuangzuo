"""Compile the supplied editorial specification into the shipped rule registry."""
import json
import re
import sys
from pathlib import Path


def compile_spec(text):
    rows = []
    def add(rid, label, body, kind, parent=None):
        row = dict(id=rid, version=1, label=label, body=body.strip(), kind=kind,
                   applies_to=['script', 'novel', 'rewrite'], source_type='editorial_rule', enabled=True)
        if parent:
            row['parent'] = parent
        rows.append(row)
    for match in re.finditer(r'^### (G\d{2}) (.+)\n\n(.+?)\n\n((?:- G.+\n?)+)', text, re.M):
        rid, label, body, children = match.groups()
        add(rid, label, body, 'genre')
        for child in re.finditer(r'- (G\d{2}\.\d) (.+?)：(.+)', children):
            cid, name, rule = child.groups()
            add(cid, name, rule, 'subgenre', rid)
    for match in re.finditer(r'^\| (F\d{2}) \| (.+?) \| (.+?) \|', text, re.M):
        add(*match.groups(), 'formula')
    section = text.split('### 10.1 情绪标签', 1)[1].split('### 10.2', 1)[0]
    for i, match in enumerate(re.finditer(r'^\| ([^|]+) \| ([^|]+) \|', section, re.M)):
        label, body = [v.strip() for v in match.groups()]
        if label != '标签' and not label.startswith('-'):
            add('E%02d' % i, label, body, 'emotion')
    section = text.split('### 10.2 台词标签', 1)[1].split('### 10.3', 1)[0]
    for i, match in enumerate(re.finditer(r'^- (.+?)：(.+)', section, re.M), 1):
        add('D%02d' % i, *match.groups(), 'dialogue')
    section = text.split('### 10.3 小说语言风格', 1)[1].split('## 11', 1)[0]
    for i, match in enumerate(re.finditer(r'^(.+?)：(.+)', section, re.M), 1):
        add('L%02d' % i, *match.groups(), 'language')
    section = text.split('## 11 商业模式的独立规则', 1)[1].split('## 12', 1)[0]
    for i, match in enumerate(re.finditer(r'^\| ([^|]+) \| ([^|]+) \|', section, re.M)):
        label, body = [v.strip() for v in match.groups()]
        if label != '模式或子选项' and not label.startswith('-'):
            add('B%02d' % i, label, body, 'commercial')
    section = text.split('## 16 可直接使用的核心提示词', 1)[1].split('## 17', 1)[0]
    for match in re.finditer(r'^### (R\d{2}) ([^\n]+)\n\n(.+?)(?=\n### |\Z)', section, re.M | re.S):
        add(*match.groups(), 'core')
    cover = text.split('### 13.2 封面提示词完整规则', 1)[1].split('### 13.3', 1)[0].strip()
    next(row for row in rows if row['id'] == 'R09')['body'] = cover
    assert len([r for r in rows if r['kind'] == 'genre']) == 24
    assert len([r for r in rows if r['kind'] == 'subgenre']) == 144
    assert len([r for r in rows if r['kind'] == 'formula']) == 30
    assert len({r['id'] for r in rows}) == len(rows)
    return dict(schema_version=2, source='TT创作助手 V2 逐项开发总方案 2026-10-01', rules=rows)


if __name__ == '__main__':
    source, output = map(Path, sys.argv[1:3])
    text = source.read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    data = compile_spec(text)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'rules': len(data['rules']), 'genres': 24, 'subgenres': 144, 'formulas': 30}))
