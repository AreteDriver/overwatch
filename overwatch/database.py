"""Database engine and session management."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from overwatch.config import DATABASE_URL
from overwatch.models import Base


def _enable_wal(dbapi_conn: object, _connection_record: object) -> None:
    """Enable WAL mode and foreign keys for SQLite."""
    cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine(url: str | None = None) -> Engine:
    db_url = url or DATABASE_URL
    if db_url.startswith("sqlite"):
        # Ensure directory exists for file-based SQLite
        if ":///" in db_url:
            db_path = db_url.split("///", 1)[1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            echo=False,
        )
        event.listen(engine, "connect", _enable_wal)
    else:
        engine = create_engine(db_url, echo=False)
    return engine


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
