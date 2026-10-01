from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse


@dataclass(frozen=True)
class ImageConnection:
    id: str
    name: str
    provider: str
    model: str
    base_url: str = ''
    cli_path: str = ''
    timeout: int = 300
    credential_version: int = 0
    enabled: bool = True
    supports_edit: bool = False
    supports_mask: bool = False
    supports_seed: bool = False
    supports_negative: bool = False
    max_count: int = 1
    sizes: tuple[str, ...] = ('1024x1024',)
    qualities: tuple[str, ...] = ()
    poll_path: str = ''
    asset_hosts: tuple[str, ...] = ()
    capability_status: str = '手动声明，未实测'
    verification: dict = field(default_factory=dict)
    pricing: dict = field(default_factory=dict)

    def validate(self, require_model=True):
        if self.pricing:
            from app.core.budget import validate_price
            validate_price(self.pricing,True)
        if self.provider not in {'image_http', 'image_codex'} or not self.id or not self.name.strip() or (require_model and not self.model.strip()):
            raise ValueError('请填写独立图片连接名称及实际模型 ID')
        if not 10 <= self.timeout <= 1800 or not 1 <= self.max_count <= 8:
            raise ValueError('图片超时或数量声明无效')
        if self.provider == 'image_http':
            parts = urlparse(self.base_url)
            if parts.username or parts.password or parts.query or parts.fragment or not parts.hostname:
                raise ValueError('图片 Base URL 不能包含凭据、查询或片段')
            local = parts.hostname in {'127.0.0.1', 'localhost', '::1'}
            if parts.scheme != 'https' and not (parts.scheme == 'http' and local):
                raise ValueError('远程图片接口需要 HTTPS')
        if any(size != 'auto' and not re.fullmatch(r'[1-9]\d{1,4}x[1-9]\d{1,4}', size) for size in self.sizes):
            raise ValueError('尺寸声明应为 WIDTHxHEIGHT 或 auto')
        if self.poll_path and (not self.poll_path.startswith('/') or self.poll_path.startswith('//') or
                               '{job_id}' not in self.poll_path or '?' in self.poll_path or '..' in self.poll_path):
            raise ValueError('查询路径须为含 {job_id} 的相对接口路径')
        if any(not re.fullmatch(r'[a-zA-Z0-9.-]+', host) for host in self.asset_hosts):
            raise ValueError('资产来源声明只填写域名，不填写 URL 或凭据')
        if self.supports_mask and not self.supports_edit:
            raise ValueError('蒙版能力需要编辑能力')
        if self.provider == 'image_codex' and self.max_count != 1:
            raise ValueError('当前 CLI 图片通道每任务只生成一张')

    def public(self):
        data = asdict(self)
        for key in ('sizes', 'qualities', 'asset_hosts'):
            data[key] = list(data[key])
        return data

    @classmethod
    def from_dict(cls, data):
        values = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        for key in ('sizes', 'qualities', 'asset_hosts'):
            if key in values:
                values[key] = tuple(values[key])
        return cls(**values)


@dataclass
class ImageResult:
    status: str = 'failed'
    job_id: str = ''
    request_id: str = ''
    items: list[dict] = field(default_factory=list)
    raw_usage: dict | None = None
    revised_prompt: str = ''
    model: str = ''
    error: str = ''
    accepted: bool | None = None
    elapsed: float = 0
    warnings: list[str] = field(default_factory=list)

    def public(self):
        data = asdict(self)
        data['items'] = [{key: value for key, value in item.items() if key not in {'url', 'b64_json'}} for item in self.items]
        return data
