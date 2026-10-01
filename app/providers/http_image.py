from __future__ import annotations

import base64
import ipaddress
import json
import mimetypes
import socket
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, build_opener

from app.providers.contracts import redact, redact_tree
from app.providers.http_text import AbortScope, NoRedirect, cancellable_opener
from app.providers.image_contracts import ImageResult

MAX_IMAGE_BYTES = 30 * 1024**2
MAX_JSON_BYTES = 48 * 1024**2


def sanitize_metadata(value, secret):
    if isinstance(value, dict):
        return {key: item if key in {'b64_json', 'url'} else sanitize_metadata(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_metadata(item, secret) for item in value]
    return redact_tree(value, secret)


class HttpImageProvider:
    def __init__(self, opener=None):
        self.opener = opener

    def _request(self, request, connection, cancel):
        scope = AbortScope(cancel, time.monotonic() + connection.timeout)
        opener = self.opener or cancellable_opener(scope)
        try:
            with opener.open(request, timeout=min(connection.timeout, 15)) as response:
                data = response.read(MAX_JSON_BYTES + 1)
                if len(data) > MAX_JSON_BYTES:
                    raise ValueError('图片响应超过本地接收限制')
                value = json.loads(data)
                if not isinstance(value, dict):
                    raise ValueError('图片接口须返回 JSON 对象')
                return value
        finally:
            scope.close()

    def submit(self, connection, secret, snapshot, cancel, references=None, mask=None):
        connection.validate()
        result = ImageResult(model=connection.model)
        started = time.monotonic()
        if cancel.cancelled:
            return ImageResult(status='cancelled', accepted=False, model=connection.model)
        if not secret or len(secret) > 4096 or any(ord(char) < 33 or ord(char) > 126 for char in secret):
            return ImageResult(error='图片连接 KEY 缺失或格式无效', accepted=False, model=connection.model)
        fields = dict(model=connection.model, prompt=snapshot['prompt'], n=snapshot['count'])
        if snapshot.get('provider_size'):
            fields['size'] = snapshot['provider_size']
        for key in ('quality', 'negative_prompt', 'seed'):
            if snapshot.get(key) is not None and snapshot[key] != '':
                fields[key] = snapshot[key]
        headers = {'Authorization': 'Bearer ' + secret, 'User-Agent': 'TTChuangzuo/0.4'}
        if snapshot['operation'] == 'edit':
            data, boundary = self.multipart(fields, references or [], mask)
            headers['Content-Type'] = 'multipart/form-data; boundary=' + boundary
            suffix = connection.edit_path
        else:
            data = json.dumps(fields, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
            suffix = connection.generate_path
        try:
            value = self._request(Request(connection.base_url.rstrip('/') + suffix, data=data, headers=headers, method='POST'), connection, cancel)
            result = self.parse(sanitize_metadata(value, secret), connection.model)
            result.accepted = True
        except HTTPError as exc:
            result = ImageResult(error=f'图片请求被拒绝：HTTP {exc.code}，未自动重试', accepted=False, model=connection.model)
        except (URLError, OSError, TimeoutError):
            result = ImageResult(status='cancelled' if cancel.cancelled else 'uncertain', model=connection.model,
                                 error='本地等待已停止，服务端可能仍计费' if cancel.cancelled else '暂时无法确认图片提交结果，未自动重新生成')
        except (ValueError, TypeError, KeyError) as exc:
            result = ImageResult(status='uncertain', model=connection.model, error=redact('返回格式未确认：' + str(exc), secret))
        result.elapsed = round(time.monotonic() - started, 3)
        return result

    def query(self, connection, secret, job_id, cancel):
        if not connection.poll_path or not job_id:
            raise ValueError('该连接没有已声明的任务查询接口或服务端任务号')
        path = connection.poll_path.replace('{job_id}', quote(job_id, safe=''))
        request = Request(connection.base_url.rstrip('/') + path, headers={'Authorization': 'Bearer ' + secret})
        value = self._request(request, connection, cancel)
        result = self.parse(sanitize_metadata(value, secret), connection.model)
        result.job_id = result.job_id or job_id
        result.accepted = True
        return result

    @staticmethod
    def parse(value, model):
        result = ImageResult(model=str(value.get('model') or model), job_id=str(value.get('task_id') or value.get('job_id') or ''),
            request_id=str(value.get('id') or ''), raw_usage=value.get('usage') if isinstance(value.get('usage'), dict) else None)
        container = value.get('data')
        nested = container if isinstance(container, dict) else value
        result.job_id = result.job_id or str(nested.get('task_id') or nested.get('job_id') or '')
        rows = container if isinstance(container, list) else nested.get('data') or nested.get('images') or []
        if not isinstance(rows, list) or len(rows) > 8:
            raise ValueError('图片结果列表无效')
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('图片结果项无效')
            if isinstance(row.get('b64_json'), str) and row['b64_json']:
                if len(row['b64_json']) > MAX_IMAGE_BYTES * 4 // 3 + 8:
                    raise ValueError('Base64 图片超过30MB解码上限')
                result.items.append({'b64_json': row['b64_json']})
            elif isinstance(row.get('url'), str) and row['url']:
                result.items.append({'url': row['url']})
            if isinstance(row.get('revised_prompt'), str):
                result.revised_prompt = row['revised_prompt']
        status = str(value.get('status') or nested.get('status') or '').lower()
        if result.items:
            result.status = 'generated'
        elif status in {'failed', 'failure', 'error', 'cancelled', 'canceled'} or value.get('error'):
            result.status = 'cancelled' if status in {'cancelled', 'canceled'} else 'failed'
            result.error = '服务返回任务失败或取消；原封面保留'
        elif result.job_id:
            result.status = 'accepted'
        else:
            result.status = 'uncertain'
            result.error = '返回没有可下载图片或可查询任务号，未当成成功'
        return result

    @staticmethod
    def multipart(fields, references, mask=None):
        if not references:
            raise ValueError('参考编辑需要已确认的本地底图')
        boundary = 'TTCreateImage' + uuid.uuid4().hex
        parts = []
        for name, value in fields.items():
            parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode('utf-8')]
        for index, path in enumerate(references):
            path = Path(path)
            content = path.read_bytes()
            if len(content) > MAX_IMAGE_BYTES:
                raise ValueError('参考图片超过30MB')
            field = 'image' if len(references) == 1 else 'image[]'
            mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            header = f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="ref_{index}{path.suffix.lower()}"\r\nContent-Type: {mime}\r\n\r\n'
            parts += [header.encode(), content, b'\r\n']
        if mask:
            path = Path(mask)
            parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="mask"; filename="mask.png"\r\nContent-Type: image/png\r\n\r\n'.encode(), path.read_bytes(), b'\r\n']
        parts.append(f'--{boundary}--\r\n'.encode())
        return b''.join(parts), boundary

    def bytes_for(self, item, connection, cancel):
        if item.get('b64_json'):
            data = base64.b64decode(item['b64_json'], validate=True)
            if len(data) > MAX_IMAGE_BYTES:
                raise ValueError('图片解码后超过30MB')
            return data
        if item.get('path'):
            return Path(item['path']).read_bytes()
        url = item.get('url', '')
        self.validate_asset_url(url, connection)
        scope = AbortScope(cancel, time.monotonic() + min(connection.timeout, 60))
        opener = self.opener or cancellable_opener(scope)
        try:
            # Signed asset URLs do not inherit the API Authorization header.
            with opener.open(Request(url, headers={'User-Agent': 'TTChuangzuo/0.4'}), timeout=15) as response:
                data = response.read(MAX_IMAGE_BYTES + 1)
                if len(data) > MAX_IMAGE_BYTES:
                    raise ValueError('图片下载超过30MB')
                return data
        finally:
            scope.close()

    @staticmethod
    def validate_asset_url(url, connection):
        parts, base = urlparse(url), urlparse(connection.base_url)
        if not parts.hostname or parts.username or parts.password or parts.fragment:
            raise ValueError('图片下载地址无效')
        local_base = base.hostname in {'localhost', '127.0.0.1', '::1'}
        local = parts.hostname in {'localhost', '127.0.0.1', '::1'}
        if local:
            if not local_base or (parts.hostname, parts.port) != (base.hostname, base.port):
                raise ValueError('服务结果不能诱导访问本机其他地址')
        elif parts.scheme != 'https':
            raise ValueError('远程资产必须使用 HTTPS')
        if parts.hostname not in {base.hostname, *connection.asset_hosts}:
            raise ValueError('图片来源域名未允许；请配置资产来源或使用Base64结果')
        if not local:
            addresses = socket.getaddrinfo(parts.hostname, parts.port or 443)
            if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
                raise ValueError('图片地址解析为非公开网络，未下载')
