"""Adapter factory: pick real implementations when credentials exist,
demo implementations otherwise. demo_mode drives the UI banner."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .base import DataWarehouse, FileStore, Retriever
from .dw.postgres_dw import PostgresDataWarehouse
from .files.local_volume import LocalVolumeFileStore
from .retriever.local_numpy import LocalRetriever


@dataclass
class Adapters:
    warehouse: DataWarehouse
    retriever: Retriever
    file_store: FileStore

    @property
    def demo_mode(self) -> bool:
        return (
            self.warehouse.is_demo or self.retriever.is_demo or self.file_store.is_demo
        )


def demo_mode_active() -> bool:
    """True when any real cloud credential is missing."""
    has_dws = bool(os.environ.get("DWS_HOST") and os.environ.get("DWS_PASSWORD"))
    has_css = bool(os.environ.get("CSS_HOST"))
    has_obs = bool(os.environ.get("OBS_ACCESS_KEY") and os.environ.get("OBS_BUCKET"))
    return not (has_dws and has_css and has_obs)


def build_adapters(*, semantic_registry=None) -> Adapters:
    # Real implementations activate only after a live verification pass —
    # presence of credentials alone does not flip the switch (the classes
    # raise NotImplementedError until wired). Demo stays the default.
    warehouse = PostgresDataWarehouse()
    file_store = LocalVolumeFileStore()
    if semantic_registry is not None:
        retriever: Retriever = LocalRetriever(semantic_registry)
    else:
        # No registry yet (early boot / health check): search returns [].
        retriever = _EmptyRetriever()
    return Adapters(warehouse=warehouse, retriever=retriever, file_store=file_store)


class _EmptyRetriever(Retriever):
    is_demo = True

    def search(self, query: str, *, top_k: int = 5, kind: str = "all") -> list[dict]:
        return []
