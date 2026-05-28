"""
pytest fixtures for memory engine tests.
"""
import os
import sys
import sqlite3
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True, scope="function")
def _setup_env():
    """Set environment variables for the entire test session."""
    os.environ["DEEPSEEK_API_KEY"] = "test-key"
    os.environ.setdefault("FAISS_INDEX_PATH", "/tmp/test_faiss.index")
    yield


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    """Create a temporary SQLite database initialized with schema.sql."""
    db_path = tmp_path / "test_memory.db"
    schema_path = PROJECT_ROOT / "schema.sql"

    schema_sql = schema_path.read_text()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()

    import config
    import importlib
    monkeypatch.setattr(config, "DB_PATH", db_path)
    os.environ["MEMORY_DB_PATH"] = str(db_path)
    importlib.reload(config)

    yield db_path

    if db_path.exists():
        db_path.unlink(missing_ok=True)


@pytest.fixture
def temp_db_conn(temp_db):
    """Return an open SQLite connection to the temp database."""
    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()
