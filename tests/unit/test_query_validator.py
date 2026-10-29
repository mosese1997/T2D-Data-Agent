"""Unit tests: SQL validator (query_gateway)."""

import pytest

from query_gateway import validate_sql


ALLOWED = {"orders", "order_items", "fx_rates"}


def test_simple_select_valid():
    r = validate_sql("SELECT country, SUM(amount) FROM orders GROUP BY 1", allowed_objects=ALLOWED)
    assert r.valid
    assert r.objects_referenced == ["orders"]


def test_with_cte_valid():
    r = validate_sql(
        "WITH t AS (SELECT 1 AS x) SELECT x FROM t", allowed_objects=ALLOWED
    )
    assert r.valid


def test_multi_statement_rejected():
    r = validate_sql("SELECT 1; SELECT 2", allowed_objects=ALLOWED)
    assert not r.valid
    assert r.errors[0]["code"] == "multi_statement"


def test_delete_rejected():
    r = validate_sql("DELETE FROM orders", allowed_objects=ALLOWED)
    assert not r.valid
    assert r.errors[0]["code"] == "not_select"


def test_update_rejected():
    r = validate_sql("UPDATE orders SET status = 'x'", allowed_objects=ALLOWED)
    assert not r.valid


def test_system_catalog_rejected():
    r = validate_sql("SELECT * FROM pg_catalog.pg_tables", allowed_objects=ALLOWED)
    assert not r.valid
    assert r.errors[0]["code"] == "system_object"


def test_information_schema_rejected():
    r = validate_sql("SELECT * FROM information_schema.tables", allowed_objects=ALLOWED)
    assert not r.valid


def test_unauthorized_object_rejected():
    r = validate_sql("SELECT * FROM secret_table", allowed_objects=ALLOWED)
    assert not r.valid
    assert r.errors[0]["code"] == "object_not_authorized"


def test_forbidden_function_rejected():
    r = validate_sql("SELECT pg_sleep(10)", allowed_objects=ALLOWED)
    assert not r.valid
    assert r.errors[0]["code"] == "forbidden_function"


def test_forbidden_function_set_config():
    r = validate_sql("SELECT set_config('a', 'b', false)", allowed_objects=ALLOWED)
    assert not r.valid
    assert r.errors[0]["code"] == "forbidden_function"


def test_known_function_allowed():
    r = validate_sql("SELECT SUM(x) FROM orders", allowed_objects=ALLOWED)
    assert r.valid


def test_mutating_cte_rejected():
    r = validate_sql(
        "WITH t AS (DELETE FROM orders RETURNING *) SELECT * FROM t",
        allowed_objects=ALLOWED,
    )
    assert not r.valid


def test_parse_error_rejected():
    r = validate_sql("SELEC nonsense", allowed_objects=ALLOWED)
    assert not r.valid
    # sqlglot may classify malformed input as a non-SELECT statement rather
    # than a parse error — either way it must be rejected.
    assert r.errors[0]["code"] in {"parse_error", "not_select"}


def test_empty_sql_rejected():
    r = validate_sql("   ", allowed_objects=ALLOWED)
    assert not r.valid
    assert r.errors[0]["code"] == "empty_sql"


def test_missing_limit_warns():
    r = validate_sql("SELECT * FROM orders", allowed_objects=ALLOWED)
    assert r.valid
    assert any("LIMIT" in w for w in r.warnings)
