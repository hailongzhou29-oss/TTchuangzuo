"""Extract explicit handoff controls/gates; evidence is reviewed separately."""
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'TT创作助手_完整开发交接书_V1.1.md'
text=source.read_text(encoding='utf-8-sig')
controls=[]
gates=[]
for line_number,line in enumerate(text.splitlines(),1):
    match=re.match(r'^\| ([A-Z]\d{2}) \| (.+?) \| (.+)',line)
    if not match:
        continue
    code,name,contract=match.groups()
    record=dict(id=code,name=name,contract=contract,source_line=line_number,status='待逐项核验',evidence=[])
    (gates if code.startswith('V') else controls).append(record)
if len({row['id'] for row in controls})!=len(controls) or len({row['id'] for row in gates})!=len(gates):
    raise ValueError('交接编号重复，不能生成完成结论')
reviews_path=ROOT/'docs'/'acceptance_reviews.json'
reviews=json.loads(reviews_path.read_text(encoding='utf-8')) if reviews_path.is_file() else {}
for row in controls+gates:
    review=reviews.get(row['id'])
    # A reviewed conclusion is invalid when its source contract changes.
    if review and review.get('contract')==row['contract']:
        row.update(status=review['status'],evidence=review.get('evidence',[]),remaining=review.get('remaining',''))
result=dict(controls=controls,gates=gates,completion_proven=False,
            note='这里只提取合同。按钮存在、测试绿色或关键词匹配不能证明对应完整要求已完成。')
path=ROOT/'docs'/'acceptance_inventory.json'
path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# 完整交接验收追踪','',f'提取 {len(controls)} 项控件合同、{len(gates)} 项验收场景。当前没有将全部列为通过。','',
       '| 编号 | 名称 | 当前证据状态 |','|---|---|---|']
lines += [f"| {row['id']} | {row['name']} | {row['status']} |" for row in controls+gates]
lines += ['', '逐项证据与剩余条件见 `acceptance_inventory.json`；人工审查记录为 `acceptance_reviews.json`。来源合同改变后，旧结论自动失效。']
(ROOT/'docs'/'完整交接验收追踪.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(f'CONTROLS={len(controls)} GATES={len(gates)} COMPLETION_PROVEN=False')
