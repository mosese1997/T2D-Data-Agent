"""Unit tests: permission-scoped result cache (task book §14).

The fixed two-user isolation proof: different users / roles / dataset
scopes / file versions MUST get different cache keys — a hit can never
cross a permission boundary.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "api"))

from t2d_api.cache import ResultCache, cache_key  # noqa: E402


def test_key_includes_permission_scope():
    analyst = cache_key(user_id=1, workspace_id=1, role="analyst",
                        datasets=frozenset({"orders"}), file_ref_id=10,
                        page=1, size=50)
    viewer = cache_key(user_id=2, workspace_id=1, role="viewer",
                       datasets=frozenset({"orders"}), file_ref_id=10,
                       page=1, size=50)
    assert analyst != viewer, "不同用户/角色必须不同缓存键（隔离要求）"


def test_key_includes_dataset_scope():
    full = cache_key(user_id=1, workspace_id=1, role="analyst",
                     datasets=frozenset({"orders", "refunds"}), file_ref_id=10,
                     page=1, size=50)
    subset = cache_key(user_id=1, workspace_id=1, role="analyst",
                       datasets=frozenset({"orders"}), file_ref_id=10,
                       page=1, size=50)
    assert full != subset, "数据集授权范围不同必须不同缓存键"


def test_key_includes_file_version():
    """Refresh swaps the file ref — the key must follow (no stale hits)."""
    before = cache_key(user_id=1, workspace_id=1, role="analyst",
                       datasets=frozenset({"orders"}), file_ref_id=10,
                       page=1, size=50)
    after = cache_key(user_id=1, workspace_id=1, role="analyst",
                      datasets=frozenset({"orders"}), file_ref_id=11,
                      page=1, size=50)
    assert before != after


def test_key_includes_params():
    a = cache_key(user_id=1, workspace_id=1, role="analyst",
                  datasets=frozenset(), file_ref_id=10, page=1, size=50)
    b = cache_key(user_id=1, workspace_id=1, role="analyst",
                  datasets=frozenset(), file_ref_id=10, page=2, size=50)
    assert a != b


def test_cache_hit_miss_and_ttl():
    cache = ResultCache(ttl_s=60)
    key = ("k",)
    assert cache.get(key)[1] is False
    cache.put(key, {"rows": []})
    value, hit = cache.get(key)
    assert hit and value == {"rows": []}
    expired = ResultCache(ttl_s=0)
    expired.put(key, "v")
    import time

    time.sleep(0.01)
    assert expired.get(key)[1] is False


def test_cache_eviction_order():
    cache = ResultCache(ttl_s=60, max_entries=2)
    cache.put(("a",), 1)
    cache.put(("b",), 2)
    cache.put(("c",), 3)  # evicts ("a",)
    assert cache.get(("a",))[1] is False
    assert cache.get(("b",))[1] is True
    assert cache.get(("c",))[1] is True
