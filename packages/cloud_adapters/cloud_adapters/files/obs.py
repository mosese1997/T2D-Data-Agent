"""Real OBS file store — activates only with credentials.

Wiring checklist when credentials arrive:
- OBS_ACCESS_KEY/SECRET_KEY/SERVER/BUCKET/REGION in .env
- private bucket; downloads proxied through the authenticated API only
  (never a public bucket or presigned URLs handed to the browser)
- lifecycle rule for temporary objects (expires_at cleanup)

Not wired into the factory until a live verification pass runs against the
real bucket (no unverified capability claims).
"""

from __future__ import annotations

import os

from ..base import AdapterError, FileMeta, FileStore


class ObsFileStore(FileStore):
    is_demo = False

    def __init__(self) -> None:
        self.access_key = os.environ.get("OBS_ACCESS_KEY", "")
        self.secret_key = os.environ.get("OBS_SECRET_KEY", "")
        self.server = os.environ.get("OBS_SERVER", "")
        self.bucket = os.environ.get("OBS_BUCKET", "")
        if not all([self.access_key, self.secret_key, self.server, self.bucket]):
            raise AdapterError("OBS 凭据不完整（需要 ACCESS_KEY/SECRET_KEY/SERVER/BUCKET）")

    def put(self, key: str, data: bytes, *, mime: str = "application/json") -> FileMeta:
        raise NotImplementedError("待真实 OBS 桶接入后按实测补齐")

    def get(self, key: str) -> bytes:
        raise NotImplementedError("待真实 OBS 桶接入后按实测补齐")

    def delete(self, key: str) -> None:
        raise NotImplementedError("待真实 OBS 桶接入后按实测补齐")
