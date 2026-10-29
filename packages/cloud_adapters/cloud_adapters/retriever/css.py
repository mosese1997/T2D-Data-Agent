"""Real CSS (Elasticsearch-compatible) retriever — activates only with
credentials + a verified vector engine.

Wiring checklist when credentials arrive:
- CSS_HOST/PORT/SSL/USER/PASSWORD in .env
- confirm the cluster's vector engine support and index mapping
- EMBEDDING_* config: model source (MaaS or external API) + dimension
- semantic_version change => new index (t2d_semantic_v{N}), rebuild, switch

Not wired into the factory until a live verification pass runs against the
real cluster (no unverified capability claims).
"""

from __future__ import annotations

import os

from ..base import AdapterError, Retriever


class CssRetriever(Retriever):
    is_demo = False

    def __init__(self) -> None:
        self.host = os.environ.get("CSS_HOST", "")
        self.port = int(os.environ.get("CSS_PORT", "9200"))
        self.ssl = os.environ.get("CSS_SSL", "false").lower() == "true"
        self.user = os.environ.get("CSS_USER", "")
        self.password = os.environ.get("CSS_PASSWORD", "")
        self.index_prefix = os.environ.get("CSS_INDEX_PREFIX", "t2d_semantic")
        if not self.host:
            raise AdapterError("CSS 凭据不完整（需要 CSS_HOST）")

    def search(self, query: str, *, top_k: int = 5, kind: str = "all") -> list[dict]:
        raise NotImplementedError("待真实 CSS 集群接入后按实测补齐（含向量引擎验证）")
