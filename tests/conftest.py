"""
pytest fixtures for memory engine tests.

Provides temporary SQLite and ChromaDB environments,
and sets up import paths and environment variables.
"""

import os
import sys
import tempfile
import sqlite3
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# sys.path setup — make project root importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Session-scoped: set environment variables before any imports
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True, scope="session")
def _setup_env():
    """Set environment variables for the entire test session."""
    os.environ["DEEPSEEK_API_KEY"] = "test-key"
    # Use temp paths set per-test via fixtures below; just ensure they exist
    os.environ.setdefault("MEMORY_DB_PATH", ":memory:")
    os.environ.setdefault("CHROMADB_PATH", str(PROJECT_ROOT / "tests" / "_tmp_chromadb"))
    yield
    # Don't clean up here — individual fixtures handle it


# ---------------------------------------------------------------------------
# temp_db: temporary SQLite database with full schema
# ---------------------------------------------------------------------------
@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    """
    Create a temporary SQLite database initialized with schema.sql.
    Returns the path to the database file.
    """
    db_path = tmp_path / "test_memory.db"
    schema_path = PROJECT_ROOT / "schema.sql"

    # Read and execute schema
    schema_sql = schema_path.read_text()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()

    # Monkeypatch config so memory_server uses our temp DB
    import config
    monkeypatch.setattr(config, "DB_PATH", db_path)
    os.environ["MEMORY_DB_PATH"] = str(db_path)

    yield db_path

    # Cleanup
    if db_path.exists():
        db_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# temp_db_conn: like temp_db but returns a connection for direct SQL
# ---------------------------------------------------------------------------
@pytest.fixture
def temp_db_conn(temp_db):
    """Return an open SQLite connection to the temp database."""
    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# temp_chromadb: temporary ChromaDB directory (mocked)
# ---------------------------------------------------------------------------
@pytest.fixture
def temp_chromadb(monkeypatch, tmp_path):
    """
    Create a temporary directory for ChromaDB and set config.
    Returns the path.
    """
    chromadb_dir = tmp_path / "chromadb"
    chromadb_dir.mkdir(exist_ok=True)

    import config
    monkeypatch.setattr(config, "CHROMADB_PATH", chromadb_dir)
    os.environ["CHROMADB_PATH"] = str(chromadb_dir)

    yield chromadb_dir

    # Cleanup
    if chromadb_dir.exists():
        shutil.rmtree(str(chromadb_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# mock_chromadb: returns a MagicMock that stands in for a ChromaDB collection
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_chromadb():
    """
    Returns a MagicMock that mimics a ChromaDB collection.
    Useful for tests that call tools with ChromaDB side effects.
    """
    collection = MagicMock()
    collection.count.return_value = 0
    collection.query.return_value = {"ids": [[]], "metadatas": [[]], "distances": [[]]}
    collection.add.return_value = None
    return collection
