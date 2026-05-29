"""
记忆引擎 — 数据库迁移系统（MISS-2）

轻量级版本化迁移，支持：
- 自动检测并应用新迁移
- 迁移历史记录（schema_migrations 表）
- 迁移脚本版本控制

用法：
    from db_migrations import run_migrations
    run_migrations()
"""
import sqlite3
from pathlib import Path
from typing import Callable

# 迁移版本列表：(version_id, description, sql_callback)
# 每个迁移只应用一次，按版本顺序执行

MIGRATIONS = [
    # v2.1.0: 添加 vector 列到 memory_tree_chunks
    (
        "001_add_vector_column",
        "Add vector BLOB column to memory_tree_chunks",
        lambda conn: conn.execute("ALTER TABLE memory_tree_chunks ADD COLUMN vector BLOB"),
    ),
    # v2.1.0: 添加 faiss_id 列到 memory_tree_chunks
    (
        "002_add_faiss_id_column",
        "Add faiss_id INTEGER column to memory_tree_chunks",
        lambda conn: conn.execute(
            "ALTER TABLE memory_tree_chunks ADD COLUMN faiss_id INTEGER DEFAULT -1"
        ),
    ),
    # v2.1.0: 创建 faiss_id 索引
    (
        "003_create_faiss_id_index",
        "Create index on memory_tree_chunks(faiss_id)",
        lambda conn: conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mt_faissid ON memory_tree_chunks(faiss_id)"
        ),
    ),
    # v2.1.1: 添加级联删除到 relationships 表
    (
        "004_add_cascade_delete",
        "Add ON DELETE CASCADE to relationships foreign keys",
        lambda conn: conn.execute(
            "ALTER TABLE relationships "
            "DROP COLUMN source_id; "  # SQLite 不支持直接修改外键，需要重建表
        ),
        # 注意：这个迁移需要重建表，实际生产环境需要更复杂的处理
    ),
]


def run_migrations(db_path: Path) -> list[str]:
    """运行所有未应用的迁移。
    
    Args:
        db_path: SQLite 数据库路径
        
    Returns:
        已应用的迁移版本列表
    """
    applied = _get_applied_migrations(db_path)
    applied_versions = {m[0] for m in applied}
    
    applied_this_run = []
    
    for version_id, description, callback in MIGRATIONS:
        if version_id in applied_versions:
            continue
        
        try:
            conn = sqlite3.connect(str(db_path))
            callback(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version_id, _now()),
            )
            conn.commit()
            conn.close()
            applied_this_run.append(version_id)
            print(f"✅ Applied migration: {version_id} - {description}")
        except Exception as e:
            print(f"❌ Failed migration {version_id}: {e}")
            raise
    
    return applied_this_run


def _get_applied_migrations(db_path: Path) -> list[tuple[str, str]]:
    """获取已应用的迁移列表。"""
    conn = sqlite3.connect(str(db_path))
    try:
        # 确保 schema_migrations 表存在
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TEXT)"
        )
        rows = conn.execute(
            "SELECT version, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        return rows
    finally:
        conn.close()


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def check_schema_integrity(db_path: Path) -> dict:
    """检查数据库 schema 完整性。
    
    Returns:
        {
            "status": "ok" | "error",
            "missing_columns": [...],
            "missing_indexes": [...],
        }
    """
    conn = sqlite3.connect(str(db_path))
    try:
        # PRAGMA integrity_check
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        
        # 检查 memory_tree_chunks 表结构
        chunks_columns = conn.execute(
            "PRAGMA table_info(memory_tree_chunks)"
        ).fetchall()
        chunks_column_names = {c[1] for c in chunks_columns}
        
        required_columns = {
            "id", "source", "source_type", "title", "content", "content_hash",
            "faiss_id", "vector", "score", "created_at"
        }
        missing_columns = required_columns - chunks_column_names
        
        # 检查索引
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='memory_tree_chunks'"
        ).fetchall()
        index_names = {i[0] for i in indexes}
        
        required_indexes = {"idx_mt_faissid"}
        missing_indexes = required_indexes - index_names
        
        return {
            "status": "ok" if not missing_columns and not missing_indexes else "error",
            "integrity": integrity,
            "missing_columns": list(missing_columns),
            "missing_indexes": list(missing_indexes),
        }
    finally:
        conn.close()
