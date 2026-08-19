"""
Fixtures local to the tests package.
"""

import importlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app import models  # noqa: F401 -- registers models on Base before create_all
from app.database import Base, get_db
from app.main import app


@pytest.fixture(autouse=True)
def _restore_config_after_test():
    """app.config computes its constants (DATA_DIR, DATABASE_URL, ...) at
    import time, from environment variables. Tests that need a different
    DATA_DIR set the env var and importlib.reload() the module (see
    test_config.py) -- reload it once more here after each test, once
    monkeypatch has restored the real environment, so a temp path from one
    test never leaks into the next one."""
    yield
    importlib.reload(config)


@pytest.fixture()
def db_session():
    """A throwaway in-memory SQLite database, isolated per test. StaticPool
    makes every connection share the same in-memory database -- without it,
    each new connection would see a separate, blank database."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session):
    """A FastAPI TestClient wired to the throwaway DB via a get_db()
    override.

    Deliberately used WITHOUT `with TestClient(app) as c:` -- that form
    runs the app's lifespan, which would call the real init_db() against
    the actually-configured DATA_DIR (see app/main.py). Tables are created
    directly on the throwaway engine instead (see db_session above).

    The override also deliberately does NOT close db_session after each
    request, unlike the real get_db() -- keeping the session open lets a
    test inspect/refresh the same objects the endpoint just wrote, after
    the request returns.
    """

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
