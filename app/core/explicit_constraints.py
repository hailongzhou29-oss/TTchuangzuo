"""Narrow, source-backed constraints; prose and arbitrary numbers are not policy."""
import re
from datetime import date,timedelta

_RANGE=re.compile(r'(?:^|[。；;，,（(\n])\s*(?:本次正文|本章正文|正文|本章)(?:字数|长度|字符数|字符)?(?:目标|范围|限制)[：:\s]*(\d{1,7})\s*(?:到|至|[—–－\-~～])\s*(\d{1,7})\s*(非空白字符|汉字|字符|字)?')

def _length(value,source):
    if not isinstance(value,dict):raise ValueError('正文范围须有明确的下限、上限和单位')
    low=value.get('min');high=value.get('max');unit=value.get('unit','nonwhitespace')
    if type(low) is not int or type(high) is not int or not 0<low<=high or unit not in {'nonwhitespace','chinese'}:
        raise ValueError('正文范围无效：请核对下限、上限及字符／汉字单位')
    return dict(min=low,max=high,unit=unit,source=source)

def _text_range(text,source,default_unit):
    quotes=[m.span() for m in re.finditer(r'“[^”]*”|「[^」]*」|『[^』]*』|"[^\"]*"',text)]
    for match in _RANGE.finditer(text):
        if any(a<=match.start(1)<b for a,b in quotes):continue
        unit='chinese' if match.group(3)=='汉字' else 'nonwhitespace' if match.group(3) in {'非空白字符','字符'} else default_unit
        return _length(dict(min=int(match.group(1)),max=int(match.group(2)),unit=unit),source)

def length_range(config,instruction='',confirmed_facts=()):
    value=config.get('_length_range') or config.get('length_range')
    if value:
        if not isinstance(value,dict):raise ValueError('正文范围须为结构化限制')
        if value.get('scope','current_document') not in {'current_document','current_chapter'}:return None
        return _length(value,value.get('source','创作设置·正文范围'))
    unit='chinese' if config.get('word_count_unit')=='chinese' else 'nonwhitespace'
    for fact in confirmed_facts:
        if fact.get('state')=='confirmed':
            value=_text_range(str(fact.get('content','')),'已确认限制',unit)
            if value:return value
    return _text_range(instruction,'本次明确正文范围',unit)

def _timeline(value,source):
    if not isinstance(value,dict) or value.get('order')!='chronological':return None
    try:
        day=date.fromisoformat(value['date']);start=_minute(value.get('start','00:00'));end=_minute(value.get('end','23:59'))
    except (ValueError,KeyError,TypeError):raise ValueError('顺叙时间限制须明确同一日期、起止时刻')
    if start>end:raise ValueError('跨日时间限制不能当作同日顺叙；请明确日期和范围')
    return dict(order='chronological',date=day.isoformat(),start=start,end=end,source=source)

def _minute(text):
    if type(text) is int and 0<=text<1440:return text
    match=re.fullmatch(r'(\d{1,2}):(\d{2})',text)
    if not match or int(match[1])>23 or int(match[2])>59:raise ValueError('时刻无效')
    return int(match[1])*60+int(match[2])

def timeline_constraint(config,instruction='',confirmed_facts=()):
    value=config.get('_timeline_constraint') or config.get('timeline_constraint')
    if value:
        if not isinstance(value,dict):raise ValueError('时间限制须为结构化限制')
        return _timeline(value,value.get('source','创作设置·同日顺叙限制'))
    # Only an explicit restriction label with both date and chronological order.
    texts=[(str(f.get('content','')),'已确认时间限制') for f in confirmed_facts if f.get('state')=='confirmed']+[(instruction,'本次明确时间限制')]
    pattern=r'(?:^|[。\n])\s*本章时间范围[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日上午[，,；;]\s*(?:按)?顺叙[。\s]*$'
    for text,source in texts:
        match=re.search(pattern,text)
        if match:
            day=date(*(int(v) for v in match.groups()))
            return _timeline(dict(order='chronological',date=day.isoformat(),start='00:00',end='11:59'),source)

def _number(text):
    if text.isdigit():return int(text)
    digits={c:i for i,c in enumerate('零一二三四五六七八九')};digits.update({'〇':0,'两':2})
    if '十' in text:
        a,b=text.split('十',1);return (digits.get(a,1) if a else 1)*10+(digits[b] if b else 0)
    return int(''.join(str(digits[c]) for c in text))

_CLOCK=re.compile(r'(?P<period>上午|早上|凌晨|下午|晚上|傍晚)?\s*(?:(?P<h>\d{1,2})[：:](?P<m>\d{2})|(?P<ch>[零〇一二三四五六七八九十两]{1,3}|\d{1,2})点(?:(?P<cm>[零〇一二三四五六七八九十两]{1,3}|\d{1,2})分|(?P<half>半)|整)?)')
_DAY=re.compile(r'(?:(\d{4})年)?([零〇一二三四五六七八九十两]{1,3}|\d{1,2})月([零〇一二三四五六七八九十两]{1,3}|\d{1,2})日[，,\s]*')
_BACK=re.compile(r'回忆|想起|记起|记得|倒叙|往事|多年前|昨天|昨夜|昨晚|那年|曾经|从前|前一日')

def timeline_review(snapshot,proposed):
    """Only narrated paragraph-leading clocks; quoted/remembered clocks are not events."""
    rule=timeline_constraint(snapshot.get('constraints',{}),snapshot.get('instruction',''),snapshot.get('confirmed_facts',()))
    day=date.fromisoformat(rule['date']) if rule else None;anchors=[];offset=0
    for line in proposed.splitlines(keepends=True):
        clean=line.lstrip();leading=len(line)-len(clean);dated=False
        dm=_DAY.match(clean)
        if dm:
            try:
                year=int(dm[1]) if dm[1] else day.year if day else None
                if year:day=date(year,_number(dm[2]),_number(dm[3]));dated=True
                else:day=None
            except (ValueError,KeyError):day=None
            clean=clean[dm.end():];leading+=dm.end()
        relative=re.match(r'(次日|翌日|第二天)[，,\s]*',clean)
        if relative:
            day=day+timedelta(days=1) if day else None;clean=clean[relative.end():];leading+=relative.end();dated=True
        match=_CLOCK.match(clean)
        if match and not _BACK.search(clean):
            try:
                hour=int(match['h']) if match['h'] else _number(match['ch']);minute=int(match['m']) if match['m'] else _number(match['cm']) if match['cm'] else 30 if match['half'] else 0
                if match['period'] in {'下午','晚上','傍晚'} and hour<12:hour+=12
                if hour<24 and minute<60:anchors.append(dict(day=day,minute=hour*60+minute,position=offset+leading,label=match.group(0).strip(),dated=dated,evidence=line.strip()[:110]))
            except (ValueError,KeyError):pass
        offset+=len(line)
    notes=[]
    start=snapshot.get('target_start',0);end=snapshot.get('target_end',0)+len(proposed)-len(snapshot.get('frozen',{}).get('text',proposed))
    if rule:
        for anchor in anchors:
            if anchor['day'] and (anchor['day'].isoformat()!=rule['date'] or not rule['start']<=anchor['minute']<=rule['end']):
                notes.append(dict(kind='time_range',level='conflict',source=rule['source'],evidence=anchor['evidence'],message='拼接全文中的'+anchor['label']+'超出已明确的同日时间范围；请扩大修改范围或调整要求，未改范围外正文'))
    for previous,current in zip(anchors,anchors[1:]):
        between=proposed[previous['position']:current['position']]
        if _BACK.search(between):continue
        same_day=previous['day'] is not None and previous['day']==current['day']
        if current['minute']>=previous['minute'] or previous['day'] and current['day'] and previous['day']!=current['day']:continue
        strict=bool(rule and same_day)
        boundary=previous['position']<start<=current['position'] or previous['position']<end<=current['position']
        prefix='修改选区与范围外相邻时间冲突：' if boundary else '拼接全文相邻时间倒退：'
        message=prefix+previous['label']+' → '+current['label']
        message+='；已明确同日顺叙，请扩大修改范围或调整要求，原稿保留' if strict else '；顺叙／跨日／倒叙语境未明确，仅提示核对，不自动判错'
        notes.append(dict(kind='time_order',level='conflict' if strict else 'review',source=rule['source'] if strict else '相邻段落显式时刻',evidence=previous['evidence']+' → '+current['evidence'],message=message))
    return notes
