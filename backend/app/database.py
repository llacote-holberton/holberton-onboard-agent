"""
Database engine and session setup.

On the SQLite init question (see ARCHITECTURE.md "Point de vigilance"):
init_db() is safe to call from both backend and mcp-server — create_all()
checks for existing tables first — and WAL mode below absorbs the small
race risk on a very first cold start.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    # Required for SQLite when used with FastAPI: requests can be handled on
    # a different thread than the one that created the connection.
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Enable WAL mode + a busy timeout on every new connection, to reduce
    lock contention with mcp-server writing to the same SQLite file."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    """Create all tables if they don't exist yet. Called once at startup."""
    from app import models  # noqa: F401 — registers models on Base before create_all

    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: yields a session, closes it once the request is done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
