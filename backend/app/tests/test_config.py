"""
Tests for app.config.

config.py computes its constants (DATA_DIR, DATABASE_PATH, DATABASE_URL, ...)
at import time, from environment variables. To exercise it with different
DATA_DIR values we set the env var and importlib.reload() the module --
a plain re-import would return the already-cached module and skip the
top-level code entirely.
"""

import importlib

from app import config as config_module


def _reload_config_with(monkeypatch, data_dir):
    """Set DATA_DIR then reload app.config so its module-level constants
    are recomputed from the new value."""
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    importlib.reload(config_module)
    return config_module


def test_database_url_is_derived_from_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    config = _reload_config_with(monkeypatch, data_dir)

    assert config.DATA_DIR == data_dir
    assert config.DATABASE_PATH == data_dir / "onboarding.db"
    assert config.DATABASE_URL == f"sqlite:///{data_dir / 'onboarding.db'}"


def test_data_dir_is_created_if_missing(tmp_path, monkeypatch):
    data_dir = tmp_path / "does_not_exist_yet"
    assert not data_dir.exists()

    _reload_config_with(monkeypatch, data_dir)

    assert data_dir.exists()


def test_documents_and_calendar_dirs_are_subdirs_of_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    config = _reload_config_with(monkeypatch, data_dir)

    assert config.DOCUMENTS_DIR == data_dir / "documents"
    assert config.CALENDAR_DIR == data_dir / "calendar"


def test_default_backend_port_is_8000_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("BACKEND_PORT", raising=False)
    config = _reload_config_with(monkeypatch, tmp_path / "data")

    assert config.BACKEND_PORT == 8000


def test_backend_port_reads_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_PORT", "9999")
    config = _reload_config_with(monkeypatch, tmp_path / "data")

    assert config.BACKEND_PORT == 9999
