"""Shared pytest fixtures: temp SQLite state DB + demo PG (optional)."""

from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture()
def sqlite_env(tmp_path, monkeypatch):
    """Point the state DB at a fresh temp SQLite file."""
    db_path = tmp_path / "state.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("STATE_DB_URL", url)
    monkeypatch.delenv("MYSQL_URL", raising=False)
    # Reset the cached engine for the new URL.
    from t2d_db import session as session_mod
    session_mod._cached_engine.cache_clear()
    yield url
    session_mod._cached_engine.cache_clear()


@pytest.fixture()
def migrated_db(sqlite_env):
    """Run migrations and yield the URL."""
    from alembic import command
    from alembic.config import Config

    config = Config(os.path.join(os.path.dirname(__file__), "..", "packages", "db", "alembic.ini"))
    config.set_main_option("script_location", os.path.join(
        os.path.dirname(__file__), "..", "packages", "db", "t2d_db", "alembic"))
    config.set_main_option("sqlalchemy.url", sqlite_env)
    command.upgrade(config, "head")
    yield sqlite_env


@pytest.fixture()
def demo_pg():
    """Skip-dependent fixture: business Postgres (demo DWS). Available when
    the compose stack is up; tests using it skip otherwise."""
    import psycopg

    dsn = (
        f"host={os.environ.get('DEMO_PG_HOST', 'localhost')} "
        f"port={os.environ.get('DEMO_PG_PORT', '5434')} "
        f"dbname={os.environ.get('DEMO_PG_DATABASE', 't2d_biz')} "
        f"user={os.environ.get('DEMO_PG_USER', 't2d')} "
        f"password={os.environ.get('DEMO_PG_PASSWORD', 't2d-demo-only')}"
    )
    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
    except psycopg.Error:
        pytest.skip("业务 Postgres 未运行（先 make up）")
    return dsn
