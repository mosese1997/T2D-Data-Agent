"""Demo-mode retriever: wraps the semantic package's hybrid matcher.

CSS adapter (css.py) replaces this when credentials exist. Interface stays
identical so the search_semantics tool never changes.
"""

from __future__ import annotations

from ..base import Retriever


class LocalRetriever(Retriever):
    is_demo = True

    def __init__(self, registry) -> None:
        # registry: semantic.SemanticRegistry — the worker builds the
        # SemanticRetriever once per semantic version and hands it here.
        from semantic import SemanticRetriever
        self._retriever = SemanticRetriever(registry)

    def search(self, query: str, *, top_k: int = 5, kind: str = "all") -> list[dict]:
        return [
            {"kind": h.kind, "key": h.key, "name": h.name,
             "score": h.score, "snippet": h.snippet}
            for h in self._retriever.search(query, top_k=top_k, kind=kind)
        ]
