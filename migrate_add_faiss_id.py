#!/usr/bin/env python3
"""
迁移脚本：为旧数据库添加 faiss_id 和 ingest_count 字段。
首次安装不需要运行，只有升级旧版本时才需要。
用法：python3 migrate_add_faiss_id.py
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import DB_PATH

def migrate():
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # 检查并添加 faiss_id 字段
    cols = {row[1] for row in cursor.execute("PRAGMA table_info(memory_tree_chunks)")}

    if "faiss_id" not in cols:
        cursor.execute("ALTER TABLE memory_tree_chunks ADD COLUMN faiss_id INTEGER DEFAULT -1")
        print("✅ 添加 faiss_id 字段")
    else:
        print("ℹ️  faiss_id 字段已存在")

    if "ingest_count" not in cols:
        cursor.execute("ALTER TABLE memory_tree_chunks ADD COLUMN ingest_count INTEGER DEFAULT 1")
        print("✅ 添加 ingest_count 字段")
    else:
        print("ℹ️  ingest_count 字段已存在")

    # 添加索引（IF NOT EXISTS 保证幂等）
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_mt_faissid ON memory_tree_chunks(faiss_id)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_mt_hash ON memory_tree_chunks(content_hash)")

    conn.commit()
    conn.close()
    print("\n✅ 迁移完成。请运行 python3 memory_server.py 中的 memory_tree_reindex 重建 FAISS 索引。")

if __name__ == "__main__":
    migrate()
