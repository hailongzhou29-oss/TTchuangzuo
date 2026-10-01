"""Explicit public-page reading; no cookies, model calls or implicit URL execution."""
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener

from app.providers.http_text import NoRedirect


class Reader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag in {'script','style','noscript'}:
            self.hidden += 1
        elif tag in {'p','div','h1','h2','h3','li','br'}:
            self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in {'script','style','noscript'}:
            self.hidden = max(0, self.hidden-1)
    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def fetch_public(url, opener=None):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('只读取用户明确选择的公开HTTPS资料，不执行文件/脚本地址')
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError('资料地址不是公开网络，未请求')
    try:
        with (opener or build_opener(NoRedirect())).open(Request(url, headers={'User-Agent':'TTChuangzuo/0.5'}), timeout=25) as response:
            body = response.read(2*1024**2+1)
            if len(body)>2*1024**2:
                raise ValueError('资料超过2MB，请选择必要段落或本地导入')
            charset = response.headers.get_content_charset() or 'utf-8'
            text = body.decode(charset)
    except HTTPError as exc:
        raise ValueError(f'来源返回HTTP {exc.code}，访问受限或未成功；没有绕过限制或编造内容') from None
    except (URLError, OSError, UnicodeError) as exc:
        raise ValueError('资料未能读取，请核对公开来源或改用本地材料；没有伪造检索结果') from None
    reader = Reader()
    reader.feed(text)
    plain = '\n'.join(line.strip() for line in ''.join(reader.parts).splitlines() if line.strip())
    if not plain:
        raise ValueError('页面没有可提取正文，不能据此作资料分析')
    return plain
