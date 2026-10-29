"""Adapter interfaces. Real implementations activate only with credentials;
demo implementations are the honest, clearly-labelled fallback."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class AdapterError(Exception):
    """Adapter-level failure (connection, credentials, upstream)."""


@dataclass
class FileMeta:
    storage_key: str
    size_bytes: int
    sha256: str
    mime: str = "application/json"


class DataWarehouse(ABC):
    """Business warehouse (DWS in production, Postgres in demo mode).

    The query_gateway owns validation/limits/audit; the adapter only
    provides connection targets and schema introspection.
    """

    is_demo: bool = True

    @abstractmethod
    def dsn_for(self, identity: str) -> str:
        """DSN for a service identity: draft | publisher (read-only roles)."""

    @abstractmethod
    def authorized_schema(self, datasets: list[str]) -> dict:
        """{dataset: {columns: [{name, type, comment}], row_estimate}} for
        the get_authorized_schema tool."""

    @abstractmethod
    def test_connection(self) -> bool:
        """Health probe for /api/healthz."""


class Retriever(ABC):
    """Semantic retrieval (CSS in production, local hybrid in demo mode)."""

    is_demo: bool = True

    @abstractmethod
    def search(self, query: str, *, top_k: int = 5, kind: str = "all") -> list[dict]:
        """[{kind, key, name, score, snippet}]"""


class FileStore(ABC):
    """File storage (OBS in production, local volume in demo mode)."""

    is_demo: bool = True

    @abstractmethod
    def put(self, key: str, data: bytes, *, mime: str = "application/json") -> FileMeta:
        ...

    @abstractmethod
    def get(self, key: str) -> bytes:
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        ...
