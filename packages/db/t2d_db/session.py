"""Engine / session factory for the t2d state database.

SQLite-first with MySQL 8.0 compatibility (see CLAUDE.md rule 4):
- Primary keys use BigInteger with an Integer variant on SQLite (rowid alias
  must be INTEGER to autoincrement).
- No ENUM columns, no ON UPDATE CURRENT_TIMESTAMP, all Strings have lengths.
- Timestamps are naive UTC everywhere; MySQL connections pin time_zone='+00:00'.
- SQLite connections always run with WAL + busy_timeout + foreign_keys=ON so
  the API and the worker can write concurrently under demo load.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

SQLITE_PRAGMAS = {
    "journal_mode": "WAL",
    "busy_timeout": 5000,
    "foreign_keys": "ON",
    "synchronous": "NORMAL",
}


def utcnow() -> datetime:
    """Naive UTC now — the only clock used in the state DB."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _resolve_url(url: str | None = None) -> str:
    url = url or os.environ.get("STATE_DB_URL", "sqlite:///var/state.db")
    # Prefer MYSQL_URL when set (cloud deployment); STATE_DB_URL stays the
    # local default so dev never needs to touch it.
    mysql_url = os.environ.get("MYSQL_URL", "").strip()
    if mysql_url:
        url = mysql_url
    return url


def _apply_sqlite_pragmas(engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, _record):  # pragma: no cover - driver glue
        cursor = dbapi_conn.cursor()
        for pragma, value in SQLITE_PRAGMAS.items():
            cursor.execute(f"PRAGMA {pragma}={value}")
        cursor.close()


def _apply_mysql_session_settings(engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_tz(dbapi_conn, _record):  # pragma: no cover - driver glue
        cursor = dbapi_conn.cursor()
        cursor.execute("SET time_zone='+00:00'")
        cursor.close()


def make_engine(url: str | None = None, *, echo: bool = False):
    url = _resolve_url(url)
    kwargs: dict = {"echo": echo, "future": True}
    if url.startswith("sqlite"):
        # check_same_thread=False: the worker and API share the process in dev.
        kwargs["connect_args"] = {"check_same_thread": False}
        engine = create_engine(url, **kwargs)
        _apply_sqlite_pragmas(engine)
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 10
        engine = create_engine(url, **kwargs)
        _apply_mysql_session_settings(engine)
    return engine


@lru_cache(maxsize=4)
def _cached_engine(url: str):
    return make_engine(url)


def get_engine(url: str | None = None):
    """Process-wide engine (cached per URL)."""
    return _cached_engine(_resolve_url(url))


def get_sessionmaker(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(url), expire_on_commit=False, future=True
    )


@contextmanager
def session_scope(url: str | None = None):
    """Transactional scope: commit on success, rollback on error."""
    session = get_sessionmaker(url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
