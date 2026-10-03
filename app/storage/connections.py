from __future__ import annotations

import ctypes
import json
import os
import threading
from dataclasses import replace
from ctypes import wintypes
from pathlib import Path

from app.core.files import atomic_write, write_json
from app.providers.contracts import Connection


class Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


class SecretVault:
    """Independent Windows DPAPI vault; never read another product's credentials."""
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()

    @staticmethod
    def _crypt(data: bytes, decrypt=False):
        if os.name != 'nt':
            raise RuntimeError('凭据持久化需要 Windows 安全存储')
        buffer = ctypes.create_string_buffer(data)
        source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        output = Blob()
        crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
        ok = function(ctypes.byref(source), None if decrypt else 'TTChuangzuo', None, None, None, 1, ctypes.byref(output))
        if not ok:
            raise OSError(ctypes.get_last_error(), 'Windows 安全凭据解密失败' if decrypt else 'Windows 安全凭据加密失败')
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)

    def _read(self):
        if not self.path.is_file():
            return {}
        value = json.loads(self._crypt(self.path.read_bytes(), decrypt=True).decode('utf-8'))
        if not isinstance(value, dict):
            raise ValueError('凭据存储格式损坏')
        return value

    def get(self, key):
        with self.lock:
            return self._read().get(key, '')

    def contains(self, key):
        with self.lock:
            return key in self._read()

    def set(self, key, value, allow_empty=False):
        from app.core.test_isolation import guard_test_write
        guard_test_write(self.path)
        with self.lock:
            values = self._read()
            if value or allow_empty:
                values[key] = value
            else:
                values.pop(key, None)
            atomic_write(self.path, self._crypt(json.dumps(values, ensure_ascii=False).encode('utf-8')))

    def delete_connection(self, connection_id):
        from app.core.test_isolation import guard_test_write
        guard_test_write(self.path)
        with self.lock:
            values = self._read()
            values = {key: value for key, value in values.items() if key != connection_id and not key.startswith(connection_id + ':v')}
            atomic_write(self.path, self._crypt(json.dumps(values, ensure_ascii=False).encode('utf-8')))
    def clear(self):
        from app.core.test_isolation import guard_test_write
        guard_test_write(self.path)
        with self.lock:
            self.path.unlink(missing_ok=True)


class ConnectionStore:
    def __init__(self, root: Path):
        self.path = root / 'connections.json'
        self.vault = SecretVault(root / 'credentials.dat')
        self.lock = threading.RLock()

    def all(self):
        if not self.path.is_file():
            return []
        data = json.loads(self.path.read_text(encoding='utf-8-sig'))
        if data.get('schema_version') != 1 or not isinstance(data.get('connections'), list):
            raise ValueError('模型连接配置格式不受支持')
        return [Connection.from_dict(value) for value in data['connections']]

    def get(self, connection_id):
        result = next((item for item in self.all() if item.id == connection_id), None)
        if not result:
            raise ValueError('模型连接不存在')
        return result

    def save(self, connection: Connection, secret=None):
        from app.core.test_isolation import guard_test_write
        guard_test_write(self.path)
        with self.lock:
            connection.validate(require_model=False)
            previous = self.all()
            old = next((item for item in previous if item.id == connection.id), None)
            changed_scope = old and (old.provider != connection.provider or old.base_url.rstrip('/') != connection.base_url.rstrip('/'))
            changed_capability = old and any(getattr(old, key, None) != getattr(connection, key, None) for key in ('provider', 'base_url', 'model', 'cli_path'))
            if changed_capability or secret is not None:
                connection = replace(connection, capability_status='未验证', verification={})
            if secret is not None or changed_scope:
                connection = replace(connection, credential_version=(old.credential_version if old else 0) + 1)
                # Append-only credential references: failed JSON writes leave old
                # configurations pointing to their old secret, never the new one.
                self.vault.set(connection.id + ':v' + str(connection.credential_version), secret.strip() if secret is not None else '', allow_empty=True)
                if changed_scope:
                    connection = replace(connection, capability_status='未验证', verification={})
            elif old:
                connection = replace(connection, credential_version=old.credential_version)
            items = [item for item in previous if item.id != connection.id] + [connection]
            write_json(self.path, dict(schema_version=1, connections=[item.public() for item in items]))

    def secret_snapshot(self, connection):
        with self.lock:
            current = self.get(connection.id)
            if current.credential_version != connection.credential_version:
                raise ValueError('任务准备后凭据已变更，未发送；请使用当前连接重新提交')
            reference = connection.id + ':v' + str(connection.credential_version)
            return self.vault.get(reference) if self.vault.contains(reference) else self.vault.get(connection.id)

    def delete(self, connection_id):
        with self.lock:
            write_json(self.path, dict(schema_version=1, connections=[item.public() for item in self.all() if item.id != connection_id]))
            self.vault.delete_connection(connection_id)
