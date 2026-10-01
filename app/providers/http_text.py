from __future__ import annotations

import json
import socket
import threading
from http.client import HTTPConnection, HTTPSConnection
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPHandler, HTTPSHandler, HTTPRedirectHandler, Request, build_opener

from app.providers.contracts import CancelToken, Connection, TextResult, normalize_usage, redact, redact_tree

MAX_RESPONSE = 16 * 1024**2


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        # Credentials must never follow a service redirect to another host.
        return None


class AbortScope:
    """Bound blocking receives and close the transport on timeout/cancellation."""
    def __init__(self, token, deadline):
        self.token, self.deadline = token, deadline
        self.entries = []

    def connected(self, transport):
        transport.settimeout(None)
        def abort():
            try:
                # urllib keeps a makefile reference; socket.close() alone defers
                # the actual close and cannot interrupt a different Windows reader.
                transport._real_close()
            except OSError:
                pass
        self.token.add_abort(abort)
        timer = threading.Timer(max(.01, self.deadline - time.monotonic()), abort)
        timer.daemon = True
        self.entries.append((abort, timer))
        timer.start()

    def close(self):
        for abort, timer in self.entries:
            timer.cancel()
            self.token.remove_abort(abort)


def cancellable_opener(scope):
    class Mixin:
        def connect(self):
            super().connect()
            scope.connected(self.sock)
    class Plain(Mixin, HTTPConnection):
        pass
    class Secure(Mixin, HTTPSConnection):
        pass
    class PlainHandler(HTTPHandler):
        def http_open(self, request):
            return self.do_open(Plain, request)
    class SecureHandler(HTTPSHandler):
        def https_open(self, request):
            return self.do_open(Secure, request, context=self._context)
    return build_opener(NoRedirect(), PlainHandler(), SecureHandler())


class HttpTextProvider:
    def __init__(self, opener=None):
        self.opener = opener or build_opener(NoRedirect())
        self.injected_opener = opener

    def list_models(self, connection: Connection, secret: str):
        connection.validate(require_model=False)
        request = Request(connection.base_url.rstrip('/') + '/models', headers={'Authorization': 'Bearer ' + secret, 'User-Agent': 'TTChuangzuo/0.2'})
        try:
            with self.opener.open(request, timeout=min(connection.timeout, 30)) as response:
                body = response.read(MAX_RESPONSE + 1)
                if len(body) > MAX_RESPONSE:
                    raise ValueError('模型列表响应过大')
                data = json.loads(body)
            models = data.get('data')
            if not isinstance(models, list):
                raise ValueError('服务未返回兼容的模型列表，可手动填写模型 ID')
            return [str(item['id']) for item in models if isinstance(item, dict) and isinstance(item.get('id'), str)]
        except (HTTPError, URLError) as exc:
            raise RuntimeError(redact(f'认证/模型列表检查失败：HTTP {getattr(exc, "code", "网络错误")}', secret)) from None

    def generate(self, connection: Connection, secret: str, messages: list[dict], cancel: CancelToken,
                 on_text=lambda text: None, schema=None, reasoning=None, tools=None):
        connection.validate()
        result = TextResult(model=connection.model)
        started = time.monotonic()
        if cancel.cancelled:
            result.status = 'cancelled'
            result.accepted = False
            return result
        if not secret:
            result.error = '请先在本机设置该连接的 KEY'
            result.accepted = False
            return result
        if len(secret) > 4096 or any(ord(char) < 33 or ord(char) > 126 for char in secret):
            result.error = 'KEY 含非法字符或过长，请检查本机连接设置'
            result.accepted = False
            return result
        payload = dict(model=connection.model, messages=messages, stream=connection.stream, max_tokens=connection.max_output)
        if tools:
            if not connection.tool_call:
                raise ValueError('当前连接未声明项目工具能力')
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'
        if connection.stream:
            payload['stream_options'] = dict(include_usage=True)
        if schema and connection.json_mode:
            payload['response_format'] = dict(type='json_object')
        if reasoning:
            if reasoning not in connection.reasoning_levels:
                raise ValueError('该连接未声明支持所选推理强度')
            payload['reasoning_effort'] = reasoning
        request = Request(connection.base_url.rstrip('/') + '/chat/completions',
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={'Authorization': 'Bearer ' + secret, 'Content-Type': 'application/json', 'User-Agent': 'TTChuangzuo/0.2'})
        scope = AbortScope(cancel, started + connection.timeout)
        opener = self.injected_opener or cancellable_opener(scope)
        try:
            with opener.open(request, timeout=min(connection.timeout, 15)) as response:
                result.accepted = True
                if connection.stream:
                    self._stream(response, result, cancel, on_text, started + connection.timeout, secret)
                else:
                    data = response.read(MAX_RESPONSE + 1)
                    if len(data) > MAX_RESPONSE:
                        raise ValueError('模型响应超过本地接收限制')
                    parsed = json.loads(data)
                    self._chunk(parsed, result, on_text, secret, stream=False)
            self._flush_text(result, on_text, secret)
            if cancel.cancelled:
                result.status = 'cancelled'
            elif result.finish_reason == 'stop' and result.text.strip():
                result.status = 'completed'
            elif result.finish_reason in {'length', 'max_tokens'}:
                result.status = 'incomplete'
                result.error = '输出被截断，保留未完成候选，不能采纳'
            elif result.finish_reason in {'content_filter', 'refusal'}:
                result.status = 'failed'
                result.error = '服务拒绝生成，原稿未改变'
            elif result.finish_reason == 'tool_calls':
                if not tools or not result.tool_calls:
                    result.status = 'incomplete'
                    result.error = '未提供可执行的完整项目工具调用，保留响应'
                else:
                    result.tool_calls = redact_tree(result.tool_calls, secret)
                    self._validate_calls(result)
                    result.status = 'tool_required'
            else:
                result.status = 'uncertain'
                result.error = '响应缺少完整结束标记，结果待确认；没有自动重发'
        except HTTPError as exc:
            # Explicit HTTP rejection is terminal. Never automatically resubmit writing.
            result.status, result.accepted = 'failed', False
            result.error = f'服务拒绝请求：HTTP {exc.code}。请核对连接、地域、模型及权限。'
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            result.status = 'cancelled' if cancel.cancelled else 'uncertain'
            result.error = '已停止等待，部分候选已保留；服务端可能仍计费' if cancel.cancelled else '网络中断或超时，结果待确认；重复发送可能再次计费'
        except (ValueError, TypeError, KeyError) as exc:
            result.status = 'failed'
            result.error = redact('响应格式无效：' + str(exc), secret)
        finally:
            scope.close()
            self._flush_text(result, on_text, secret)
        if cancel.cancelled:
            result.status = 'cancelled'
        result.request_id, result.model = redact(result.request_id, secret), redact(result.model, secret)
        result.finish_reason, result.error = redact(result.finish_reason, secret), redact(result.error, secret)
        result.raw_usage = redact_tree(result.raw_usage, secret)
        result.protocol_message = redact_tree(result.protocol_message, secret)
        result.tool_calls = redact_tree(result.tool_calls, secret)
        result.elapsed = round(time.monotonic() - started, 3)
        result.usage = normalize_usage(connection.provider, result.raw_usage)
        if result.tool_calls:
            result.protocol_message.update(role='assistant', content=result.text or None, tool_calls=result.tool_calls)
        return result

    @staticmethod
    def _flush_text(result, on_text, secret):
        pending = getattr(result, '_pending_text', '')
        if pending:
            clean = redact(pending, secret)
            result.text += clean
            on_text(clean)
            result._pending_text = ''

    def _stream(self, response, result, cancel, on_text, deadline, secret):
        total = 0
        event_lines = []
        for line in response:
            if cancel.cancelled:
                return
            if time.monotonic() > deadline:
                raise TimeoutError('接收超时')
            total += len(line)
            if total > MAX_RESPONSE:
                raise ValueError('流式响应超过本地接收限制')
            line = line.decode('utf-8').rstrip('\r\n')
            if line.startswith('data:'):
                event_lines.append(line[5:].lstrip())
            elif not line and event_lines:
                value = '\n'.join(event_lines)
                event_lines.clear()
                if value == '[DONE]':
                    return
                self._chunk(json.loads(value), result, on_text, secret, stream=True)
        if event_lines:
            value = '\n'.join(event_lines)
            if value != '[DONE]':
                self._chunk(json.loads(value), result, on_text, secret, stream=True)

    @staticmethod
    def _chunk(value, result, on_text, secret, stream):
        if not isinstance(value, dict) or value.get('error'):
            raise ValueError('服务返回错误对象')
        result.request_id = str(value.get('id') or result.request_id)
        result.model = str(value.get('model') or result.model)
        if isinstance(value.get('usage'), dict):
            result.raw_usage = value['usage']
        choices = value.get('choices')
        if not isinstance(choices, list):
            raise ValueError('缺少 choices 列表')
        if not choices:
            return
        first = choices[0]
        message = first.get('delta' if stream else 'message') or {}
        if not isinstance(message, dict):
            raise ValueError('消息格式无效')
        if isinstance(message.get('reasoning_content'), str):
            result.protocol_message['reasoning_content'] = result.protocol_message.get('reasoning_content', '') + message['reasoning_content']
        calls = message.get('tool_calls') or []
        if not isinstance(calls, list) or len(calls) > 16:
            raise ValueError('工具调用列表无效或过长')
        for ordinal, call in enumerate(calls):
            if not isinstance(call, dict) or not isinstance(call.get('function'), dict):
                raise ValueError('工具调用结构无效')
            index = call.get('index', ordinal)
            if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < 16:
                raise ValueError('工具调用索引无效')
            while len(result.tool_calls) <= index:
                result.tool_calls.append(dict(id='', type='function', function=dict(name='', arguments='')))
            target = result.tool_calls[index]
            if call.get('id'):
                target['id'] = str(call['id'])
            for key in ('name', 'arguments'):
                part = call['function'].get(key)
                if part is not None and not isinstance(part, str):
                    raise ValueError('工具函数参数片段应为文字')
                if part:
                    target['function'][key] += part
            if len(target['function']['arguments']) > 64000:
                raise ValueError('工具参数超过接收限制')
        content = message.get('content')
        if content is not None and not isinstance(content, str):
            raise ValueError('正文应为字符串')
        if content:
            if stream and secret:
                pending = getattr(result, '_pending_text', '') + content
                cut = max(0, len(pending) - max(len(secret), len(json.dumps(secret)[1:-1])))
                for form in (secret, json.dumps(secret, ensure_ascii=False)[1:-1]):
                    begin = pending.find(form)
                    if 0 <= begin < cut < begin + len(form):
                        cut = begin
                clean = redact(pending[:cut], secret)
                result._pending_text = pending[cut:]
            else:
                clean = redact(content, secret)
            if clean:
                result.text += clean
                on_text(clean)
        if first.get('finish_reason'):
            result.finish_reason = str(first['finish_reason'])
        if message.get('refusal'):
            result.finish_reason = 'refusal'

    @staticmethod
    def _validate_calls(result):
        seen = set()
        for call in result.tool_calls:
            if not call['id'] or call['id'] in seen or not call['function']['name']:
                raise ValueError('工具调用 ID 或函数名无效')
            if not isinstance(json.loads(call['function']['arguments']), dict):
                raise ValueError('工具函数参数尚未闭合为 JSON 对象')
            seen.add(call['id'])
