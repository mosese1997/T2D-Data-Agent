"""cloud_adapters — DWS / CSS / OBS behind three interfaces.

Demo mode (no cloud credentials): Postgres simulates DWS, the local hybrid
retriever simulates CSS, a local volume simulates OBS. factory.demo_mode
tells the UI to show the 演示数据模式 banner — simulated execution is
never presented as a real cloud call (CLAUDE.md rule 3).
"""

from .base import DataWarehouse, Retriever, FileStore, FileMeta, AdapterError
from .factory import build_adapters, Adapters, demo_mode_active

__all__ = [
    "DataWarehouse", "Retriever", "FileStore", "FileMeta", "AdapterError",
    "build_adapters", "Adapters", "demo_mode_active",
]
