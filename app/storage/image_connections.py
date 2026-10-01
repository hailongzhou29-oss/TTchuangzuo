import json

from app.providers.image_contracts import ImageConnection
from app.storage.connections import ConnectionStore


class ImageConnectionStore(ConnectionStore):
    def __init__(self, root):
        super().__init__(root)
        self.path = root / 'image_connections.json'

    def all(self):
        if not self.path.is_file():
            return []
        value = json.loads(self.path.read_text(encoding='utf-8-sig'))
        if value.get('schema_version') != 1 or not isinstance(value.get('connections'), list):
            raise ValueError('图片连接配置格式不受支持')
        return [ImageConnection.from_dict(item) for item in value['connections']]
