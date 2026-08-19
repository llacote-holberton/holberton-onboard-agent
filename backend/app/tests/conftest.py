"""
Fixtures local to the tests package.
"""

import importlib

import pytest

from app import config


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
