"""Semantic retrieval — demo mode: lexical + char-ngram hash hybrid.

No ML embedding model in demo mode (disk budget + honest boundary, see
boundaries.md): character 3-gram hashing gives fuzzy matching over
synonyms/typos, exact-token overlap dominates when present. The CSS adapter
replaces this whole class when credentials exist — same interface.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .loader import SemanticRegistry

# CJK chars tokenize individually (no dictionary segmentation in demo
# mode); latin/digit runs stay whole. This makes mixed queries like
# "上周各国家GMV趋势" match both the Chinese context and the "gmv" token.
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[一-鿿]")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _ngrams(text: str, n: int = 3) -> set[str]:
    joined = "".join(_tokens(text))
    if len(joined) < n:
        return {joined} if joined else set()
    return {joined[i : i + n] for i in range(len(joined) - n + 1)}


def _hash_vector(text: str) -> dict[int, int]:
    """Sparse char-ngram vector via hashing (fixed 20-bit space)."""
    vec: dict[int, int] = Counter()
    for gram in _ngrams(text):
        vec[hash(gram) & 0xFFFFF] += 1
    return vec


def _cosine(a: dict[int, int], b: dict[int, int]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


@dataclass
class RetrievalHit:
    kind: str  # metric | term
    key: str
    name: str
    score: float
    snippet: str


class SemanticRetriever:
    """Hybrid retriever over metrics + terms of one semantic registry."""

    def __init__(self, registry: SemanticRegistry) -> None:
        self.registry = registry
        # (kind, key, name, hash_vector, identity_tokens, body_tokens)
        self._docs: list[tuple[str, str, str, dict[int, int], set[str], set[str]]] = []
        for metric in registry.active_metrics():
            identity = " ".join([metric.name, *metric.synonyms])
            body = " ".join([metric.description, *metric.exclusions])
            self._docs.append(("metric", metric.metric_key, metric.name,
                               _hash_vector(identity + " " + body),
                               set(_tokens(identity)), set(_tokens(body))))
        for term in registry.terms.values():
            identity = " ".join([term.term, *term.aliases])
            body = term.definition
            self._docs.append(("term", term.term, term.term,
                               _hash_vector(identity + " " + body),
                               set(_tokens(identity)), set(_tokens(body))))
        # IDF over all token sets — suppresses high-frequency single CJK
        # chars (的/单/订) that would otherwise create false overlaps.
        doc_count = max(1, len(self._docs))
        df: Counter = Counter()
        for _, _, _, _, id_tokens, body_tokens in self._docs:
            df.update(id_tokens | body_tokens)
        self._idf = {
            token: math.log((doc_count + 1) / (count + 1)) + 1.0
            for token, count in df.items()
        }

    def _token_score(self, query_tokens: set[str], doc_tokens: set[str]) -> float:
        matched = query_tokens & doc_tokens
        if not matched:
            return 0.0
        total = sum(self._idf.get(t, 1.0) for t in query_tokens)
        if total <= 0:
            return 0.0
        return sum(self._idf.get(t, 1.0) for t in matched) / total

    def search(self, query: str, *, top_k: int = 5, kind: str = "all") -> list[RetrievalHit]:
        query_tokens = set(_tokens(query))
        query_vec = _hash_vector(query)
        hits: list[RetrievalHit] = []
        for doc_kind, key, name, vec, id_tokens, body_tokens in self._docs:
            if kind != "all" and doc_kind != kind:
                continue
            # Identity fields (name + synonyms) dominate; description only
            # supports. This keeps "订单取消的多吗" on cancel_rate instead of
            # drifting to GMV whose description happens to contain 取消订单的.
            identity_score = self._token_score(query_tokens, id_tokens)
            body_score = self._token_score(query_tokens, body_tokens)
            token_score = 0.65 * identity_score + 0.35 * body_score
            vector_score = _cosine(query_vec, vec)
            score = 0.7 * token_score + 0.3 * vector_score
            if score > 0.01:
                hits.append(RetrievalHit(doc_kind, key, name, round(score, 4), name))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]
