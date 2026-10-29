"""Result cache with permission-scoped keys (task book §14).

Key composition — ALL of these, so a cache hit can never leak across
scopes (the two-user isolation requirement):
  user_id + workspace_id + role + granted-dataset scope   (permission scope)
  file_ref_id                                            (source version AND
                                                          refresh version —
                                                          refresh swaps the
                                                          file ref, so the
                                                          key changes with it)
  page + size                                            (parameters)

In-process TTL cache; demo scale (5 users) — no Redis by design (task book
§3: no Redis in v1).
"""

from __future__ import annotations

import os
import time
from collections import OrderedDict

TTL_S = int(os.environ.get("RESULT_CACHE_TTL_S", "60"))
MAX_ENTRIES = 512


def cache_key(*, user_id: int, workspace_id: int, role: str,
              datasets: frozenset[str], file_ref_id: int,
              page: int, size: int) -> tuple:
    return (user_id, workspace_id, role, datasets, file_ref_id, page, size)


class ResultCache:
    def __init__(self, ttl_s: int = TTL_S, max_entries: int = MAX_ENTRIES) -> None:
        self.ttl_s = ttl_s
        self.max_entries = max_entries
        self._store: OrderedDict[tuple, tuple[float, object]] = OrderedDict()

    def get(self, key: tuple):
        entry = self._store.get(key)
        if entry is None:
            return None, False
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None, False
        self._store.move_to_end(key)
        return value, True

    def put(self, key: tuple, value) -> None:
        self._store[key] = (time.monotonic() + self.ttl_s, value)
        self._store.move_to_end(key)
        while len(self._store) > self.max_entries:
            self._store.popitem(last=False)

    # No explicit invalidation API by design: file_ref_id is part of the
    # key, so a refresh (which swaps the file ref) naturally misses.


_result_cache = ResultCache()


def get_result_cache() -> ResultCache:
    return _result_cache
