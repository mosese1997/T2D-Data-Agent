"""Demo-mode file store: a local volume directory simulating OBS.

Keys are relative paths under the root; traversal is rejected. sha256 is
computed on write and verified on read so file_refs rows stay trustworthy.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from ..base import AdapterError, FileMeta, FileStore


class LocalVolumeFileStore(FileStore):
    is_demo = True

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or os.environ.get("APP_DATA_DIR", "./var") ) / "files"
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise AdapterError(f"非法存储键: {key}")
        return path

    def put(self, key: str, data: bytes, *, mime: str = "application/json") -> FileMeta:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return FileMeta(
            storage_key=key,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            mime=mime,
        )

    def get(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.exists():
            raise AdapterError(f"文件不存在: {key}")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            path.unlink()
