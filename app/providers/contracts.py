from __future__ import annotations

import re
import json
import threading
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

PRESETS = {
    'deepseek': ('DeepSeek', 'https://api.deepseek.com'),
    'ark': ('火山方舟', 'https://ark.cn-beijing.volces.com/api/v3'),
    'qwen': ('千问', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
    'codex': ('Codex CLI', ''),
    'custom': ('自定义兼容接口', ''),
}


def redact(value: str, *secrets: str) -> str:
    text = str(value)
    for secret in secrets:
        if secret:
            for form in (secret, json.dumps(secret, ensure_ascii=False)[1:-1]):
                text = text.replace(form, '[凭据已隐藏]')
    text = re.sub(r'(?i)(Bearer\s+)[\w.\-/+=]+', r'\1[隐藏]', text)
    return re.sub(r'\bsk-[A-Za-z0-9_-]{8,}\b', '[凭据已隐藏]', text)


def redact_tree(value, secret=''):
    if isinstance(value, str):
        return redact(value, secret)
    if isinstance(value, list):
        return [redact_tree(item, secret) for item in value]
    if isinstance(value, dict):
        return {redact(str(key), secret): redact_tree(item, secret) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class Connection:
    id: str
    name: str
    provider: str
    model: str
    base_url: str = ''
    cli_path: str = ''
    timeout: int = 120
    max_output: int = 4096
    context_limit: int = 32768
    enabled: bool = True
    stream: bool = True
    json_mode: bool = False
    reasoning_levels: tuple[str, ...] = ()
    capability_status: str = '未验证'
    verification: dict = field(default_factory=dict)
    credential_version: int = 0
    tool_call: bool = False
    tool_stream: bool = False
    pricing: dict = field(default_factory=dict)

    def validate(self, require_model=True):
        if self.pricing:
            from app.core.budget import validate_price
            validate_price(self.pricing)
        if self.provider not in PRESETS or not self.name.strip() or (require_model and not self.model.strip()):
            raise ValueError('请填写连接名称、服务商和实际模型 ID')
        if not 10 <= self.timeout <= 1800 or not 128 <= self.max_output <= 65536 or self.context_limit < self.max_output:
            raise ValueError('超时、输出限制或上下文限制无效')
        if self.provider != 'codex':
            parts = urlparse(self.base_url)
            local = parts.hostname in {'localhost', '127.0.0.1', '::1'}
            if not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
                raise ValueError('Base URL 应为服务地址，不包含凭据、查询参数或片段')
            if parts.scheme != 'https' and not (parts.scheme == 'http' and local):
                raise ValueError('远程接口需要 HTTPS；本机接口可使用 HTTP')
            if '{' in self.base_url:
                raise ValueError('请把地址模板中的业务空间 ID 替换为实际值')

    def public(self):
        value = asdict(self)
        value['reasoning_levels'] = list(self.reasoning_levels)
        return value

    @classmethod
    def from_dict(cls, value):
        fields = cls.__dataclass_fields__
        clean = {key: value[key] for key in fields if key in value}
        clean['reasoning_levels'] = tuple(clean.get('reasoning_levels', ()))
        return cls(**clean)


class CancelToken:
    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._aborters = []

    def cancel(self):
        self._event.set()
        with self._lock:
            callbacks = list(self._aborters)
        for callback in callbacks:
            try:
                callback()
            except OSError:
                pass

    def add_abort(self, callback):
        with self._lock:
            self._aborters.append(callback)
        if self.cancelled:
            callback()

    def remove_abort(self, callback):
        with self._lock:
            if callback in self._aborters:
                self._aborters.remove(callback)

    @property
    def cancelled(self):
        return self._event.is_set()


@dataclass
class TextResult:
    text: str = ''
    status: str = 'failed'
    finish_reason: str = ''
    request_id: str = ''
    raw_usage: dict | None = None
    usage: dict = field(default_factory=dict)
    model: str = ''
    error: str = ''
    elapsed: float = 0
    accepted: bool | None = None
    warnings: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    protocol_message: dict = field(default_factory=dict)

    def public(self):
        return asdict(self)


def normalize_usage(provider: str, raw: dict | None):
    def integer(value):
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    raw = raw or {}
    output_details = raw.get('completion_tokens_details') or {}
    input_details = raw.get('prompt_tokens_details') or raw.get('input_tokens_details') or {}
    output_details = output_details if isinstance(output_details, dict) else {}
    input_details = input_details if isinstance(input_details, dict) else {}
    return dict(input=integer(raw.get('prompt_tokens', raw.get('input_tokens'))),
                output=integer(raw.get('completion_tokens', raw.get('output_tokens'))),
                reasoning=integer(output_details.get('reasoning_tokens', raw.get('reasoning_output_tokens'))),
                cached_read=integer(raw.get('prompt_cache_hit_tokens', raw.get('cached_input_tokens', input_details.get('cached_tokens')))),
                cache_write=integer(raw.get('cache_creation_input_tokens')),
                tool_cost=None, currency=None, actual_cost=None,
                accounting='缓存读取属于 input 的子集；reasoning 属于 output 的子集，不额外相加', provider=provider)
