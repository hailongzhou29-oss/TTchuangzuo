from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


def digest(text: str | bytes) -> str:
    return hashlib.sha256(text.encode('utf-8') if isinstance(text, str) else text).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    from app.core.test_isolation import guard_test_write
    guard_test_write(path)
    path=Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Packaged Windows apps can redirect AppData to another volume. Resolve the
    # existing parent before creating the sibling temp file and replacing it.
    path=path.resolve()
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path: Path, value) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8'))


def inside(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or Path(relative).is_absolute():
        raise ValueError('路径超出项目目录')
    return target
