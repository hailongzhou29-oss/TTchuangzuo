"""Bounded per-request output planning; character targets are not token counts."""
import math
from urllib.parse import urlparse

CAPABILITY_SOURCE='https://api-docs.deepseek.com/api/create-chat-completion/'
TOKEN_SOURCE='https://api-docs.deepseek.com/zh-cn/quick_start/token_usage/'
REVIEWED='2026-10-02'
AUTO_LIMIT=16384

def provider_output_cap(connection):
    parsed=urlparse(connection.base_url)
    if (connection.provider=='deepseek' and parsed.scheme=='https' and parsed.hostname=='api.deepseek.com'
            and parsed.path.rstrip('/') in {'','/v1'}
            and connection.model in {'deepseek-flash','deepseek-v4-flash','deepseek-v4-flash-vision-exp','deepseek-v4-pro'}):
        return dict(tokens=393216,source=CAPABILITY_SOURCE,reviewed=REVIEWED,json_supported=True)
    return None

def output_plan(connection,config,task='generate',selected_chars=0,input_tokens=0,instruction=''):
    cap=provider_output_cap(connection)
    mode=connection.output_mode
    if connection.provider=='codex':
        return dict(mode='manual',saved_tokens=connection.max_output,effective_tokens=connection.max_output,
                    recommended_tokens=connection.max_output,minimum_tokens=128,needs_attention=False,
                    source='CLI为软限制，未推断API硬上限',target='当前任务',provider_cap=None)
    if task=='modify':
        chars=max(1,selected_chars);overhead=384;target='本次修改范围'
        chars=math.ceil(chars*1.6)
        import re
        requested=re.search(r'(?:约|扩写到|改成|写成|达到|不少于)\s*(\d{1,7})\s*(?:字|汉字)',instruction)
        if requested: chars=max(chars,int(requested[1]))
    elif task in {'generate','next'}:
        if config.get('output')=='script':
            seconds=max(1,int(config.get('_segment',{}).get('duration') or config.get('duration',180)));speed=float(config.get('speech_speed') or 4.5);ratio=float(config.get('dialogue_ratio') or .5)
            # Spoken characters + repeated dialogue extraction + action prose.
            chars=math.ceil(seconds*speed*ratio*2.2+seconds*2);overhead=1024;target='本段剧本（含三部分）'
        else:
            long=config.get('length') in {'长篇小说','长篇连载'} or task=='next'
            chars=max(1,int(config.get('chapter_words',2500) if long else config.get('_segment',{}).get('words') or config.get('words',3000)))
            overhead=768;target='当前章节' if long else '本次小说'
    else:
        chars=600;overhead=256;target='本次回复'
    # Official Chinese ratio is approximate .6; add 50% token margin and schema
    # overhead. This is an estimate, never an assurance of target completion.
    minimum=math.ceil(chars*.6)+overhead
    wanted=math.ceil(chars*.6*1.5)+overhead
    recommended=next((n for n in (1536,2048,4096,8192,AUTO_LIMIT) if n>=wanted),AUTO_LIMIT)
    hard=min(connection.context_limit,connection.context_limit-int(input_tokens)-512,cap['tokens'] if cap else min(connection.max_output,4096))
    if hard<128: raise ValueError('当前资料超过上下文预算，请缩小章节或修改范围；本次未发送')
    effective=min(recommended,AUTO_LIMIT,hard) if mode=='auto' else connection.max_output
    if cap and effective>cap['tokens']:
        raise ValueError('输出上限超过当前模型官方能力，请在设置中降低')
    return dict(mode=mode,saved_tokens=connection.max_output,effective_tokens=effective,recommended_tokens=min(recommended,hard),
                minimum_tokens=minimum,estimated_target_chars=chars,target=target,provider_cap=cap['tokens'] if cap else None,
                source=cap['source'] if cap else '已保存手动上限；模型能力未确认',reviewed=cap['reviewed'] if cap else None,
                token_estimate_source=TOKEN_SOURCE,auto_limit=AUTO_LIMIT,context_available=hard,
                needs_attention=task in {'generate','next','modify'} and effective<minimum)

def output_warning(plan):
    if plan['mode']=='auto':
        return (f'本次目标超出可用输出预算（{plan["effective_tokens"]:,} token；预计至少约{plan["minimum_tokens"]:,}）。'
                '请缩短单章／本段目标或选择按章节创作，正文保留，本次未发送；不会无限续写或自动加费用。')
    return (f'本次输出上限{plan["effective_tokens"]:,} token偏低，{plan["target"]}预计需要至少约{plan["minimum_tokens"]:,} token，可能截断。'
            '请到设置 → 国内模型 → 当前连接调整“输出长度”，或缩短本次目标／修改范围；正文未覆盖，本次未发送。token不等于汉字数。')
