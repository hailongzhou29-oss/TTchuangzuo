"""Persistable creator-facing task states, without protocol jargon."""
def failure_message(result,received=''):
    status=result.get('status','failed'); text=received or result.get('text','') or ''
    if status=='cancelled': lead='已停止'
    elif status in {'uncertain','interrupted'}: lead='结果待确认，未自动重发'
    elif status in {'invalid_output','application_failed'}: lead='回复格式或采用校验未通过'
    elif status=='budget_paused': lead='已暂停'
    elif status=='incomplete': lead='未完成'
    else: lead='生成失败'
    error=result.get('error','')
    if '发声记录缺少稳定说话者' in error:error='某段台词没有明确说话者，无法对应人物台词；请在收到的片段核对该段，原稿保留。本次不自动重发。'
    elif '输出合同检查失败，原响应保留：' in error:error=error.split('原响应保留：',1)[1]+'；收到的结果仅供核对，不自动重发'
    elif any(x in error for x in ('受限工具','DSML','工具桥')): error='模型返回了不支持的操作格式，未执行修改；可查看收到的片段和请求记录，核对资料范围后再明确发起新请求。本次不自动重发'
    detail=f'收到{text.__len__()}字片段，仅供查看，可在改稿与候选打开' if text.strip() else '未收到正文'
    return lead+'；'+detail+'；原稿保留'+('。'+error if error else '')
