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

# P2-⑧ 修复: 迁移函数使用命名函数而非 lambda，便于调试和堆栈跟踪


def _migrate_001_add_vector_column(conn: sqlite3.Connection) -> None:
    """添加 vector BLOB 列到 memory_tree_chunks。"""
    conn.execute("ALTER TABLE memory_tree_chunks ADD COLUMN vector BLOB")


def _migrate_002_add_faiss_id_column(conn: sqlite3.Connection) -> None:
    """添加 faiss_id INTEGER 列到 memory_tree_chunks。"""
    conn.execute(
        "ALTER TABLE memory_tree_chunks ADD COLUMN faiss_id INTEGER DEFAULT -1"
    )


def _migrate_003_create_faiss_id_index(conn: sqlite3.Connection) -> None:
    """在 memory_tree_chunks(faiss_id) 上创建索引。"""
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_mt_faissid ON memory_tree_chunks(faiss_id)"
    )


# 迁移版本列表：(version_id, description, callback)
# 每个迁移只应用一次，按版本顺序执行
MIGRATIONS = [
    # v2.1.0: 添加 vector 列到 memory_tree_chunks
    ("001_add_vector_column", "Add vector BLOB column to memory_tree_chunks", _migrate_001_add_vector_column),
    # v2.1.0: 添加 faiss_id 列到 memory_tree_chunks
    ("002_add_faiss_id_column", "Add faiss_id INTEGER column to memory_tree_chunks", _migrate_002_add_faiss_id_column),
    # v2.1.0: 创建 faiss_id 索引
    ("003_create_faiss_id_index", "Create index on memory_tree_chunks(faiss_id)", _migrate_003_create_faiss_id_index),
    # v2.1.1: 添加级联删除到 relationships 表
    ("004_add_cascade_delete", "Add ON DELETE CASCADE to relationships (rebuild table)", _migrate_004_add_cascade_delete),
    # v2.2.0: 添加 is_indexed 列到 memory_tree_chunks
    ("005_add_is_indexed_column", "Add is_indexed column for FAISS sync tracking", _migrate_005_add_is_indexed_column),
    # v2.2.0: 为所有表的 created_at/updated_at 添加索引
    ("006_add_timestamp_indexes", "Add indexes on created_at/updated_at for all tables", _migrate_006_add_timestamp_indexes),
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
            # P2-⑧ 修复: 使用事务包裹迁移，失败时自动回滚
            conn = sqlite3.connect(str(db_path))
            try:
                callback(conn)
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version_id, _now()),
                )
                conn.commit()
                applied_this_run.append(version_id)
                print(f"✅ Applied migration: {version_id} - {description}")
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
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
    """获取当前 UTC 时间 ISO 字符串（与 utils.now() 格式略有不同，保留兼容性）。"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()



def _migrate_005_add_is_indexed_column(conn: sqlite3.Connection) -> None:
    """添加 is_indexed 列到 memory_tree_chunks。"""
    # 检查列是否已存在
    cursor = conn.execute("PRAGMA table_info(memory_tree_chunks)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'is_indexed' not in columns:
        conn.execute("ALTER TABLE memory_tree_chunks ADD COLUMN is_indexed INTEGER DEFAULT 0")
        # 将已有记录标记为已索引（faiss_id >= 0 表示已在 FAISS 中）
        conn.execute("UPDATE memory_tree_chunks SET is_indexed = 1 WHERE faiss_id >= 0")

def _migrate_004_add_cascade_delete(conn: sqlite3.Connection) -> None:
    """P2-10: 为 relationships 表添加级联删除支持。

    SQLite 不支持直接修改外键约束，需要重建表。
    此迁移重建 relationships 表，保留所有数据，新表具备 ON DELETE CASCADE。

    P2-⑨ 修复: 使用事务保护，确保旧表在新表验证成功后才删除。
    """
    cursor = conn.cursor()

    # 备份现有数据
    cursor.execute("SELECT * FROM relationships")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]

    # P2-⑨ 修复: 先创建新表，验证成功后再替换旧表
    # 使用临时表名避免与现有表冲突
    temp_table = "relationships_new_temp"
    cursor.execute(f"""
        CREATE TABLE {temp_table} (
            id         TEXT PRIMARY KEY,
            source_id  TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            target_id  TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            relation   TEXT NOT NULL,
            properties JSON,
            scope      TEXT DEFAULT 'personal',
            department TEXT,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 迁移数据
    if rows:
        placeholders = ",".join("?" for _ in columns)
        col_names = ",".join(columns)
        cursor.executemany(
            f"INSERT INTO {temp_table} ({col_names}) VALUES ({placeholders})", rows
        )

    # P2-⑨ 修复: 验证新表数据完整性
    new_count = cursor.execute(f"SELECT COUNT(*) FROM {temp_table}").fetchone()[0]
    old_count = len(rows)
    if new_count != old_count:
        cursor.execute(f"DROP TABLE {temp_table}")
        raise RuntimeError(
            f"Table rebuild data mismatch: expected {old_count} rows, got {new_count}"
        )

    # 验证通过，删除旧表并重命名新表
    cursor.execute("DROP TABLE relationships")
    cursor.execute(f"ALTER TABLE {temp_table} RENAME TO relationships")

    # 重建索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_relation ON relationships(relation)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_scope ON relationships(scope)")


def _migrate_006_add_timestamp_indexes(conn: sqlite3.Connection) -> None:
    """v2.2.0: 为所有表的 created_at/updated_at 添加索引。"""
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_mt_created ON memory_tree_chunks(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_mt_updated ON memory_tree_chunks(updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_pm_created ON preference_memory(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_pm_updated ON preference_memory(updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_em_created ON error_memory(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_em_updated ON error_memory(updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_ent_created ON entities(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_ent_updated ON entities(updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_rel_created ON relationships(created_at)",
    ]
    for sql in indexes:
        conn.execute(sql)


def check_schema_integrity(db_path: Path) -> dict[str, str | list[str]]:
    """P2-1: 添加完整返回类型注解。"""
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
