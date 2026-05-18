#!/usr/bin/env python3
"""
Auto-Fetch — 飞书/本地数据定时同步到 Memory Tree

使用方式：
1. 手动：python3 auto_fetch.py
2. Hermes cronjob 定时触发：每 20 分钟执行

依赖：
- 飞书 CLI（lark-cli）用于飞书数据同步
- memory_server.py 的 MCP 工具（通过 HTTP 或直接导入）

环境变量：
- ENTERPRISE_MEMORY_DB: 数据库路径
- FEISHU_ENABLED: 是否启用飞书同步（1/0，默认 1）
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 项目根目录
ROOT = Path(__file__).parent
DB_PATH = os.getenv("ENTERPRISE_MEMORY_DB", str(ROOT / "memory.db"))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 同步状态管理
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _update_sync_status(source: str, status: str, items: int = 0, error: str = "") -> None:
    with _get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO sync_status (source, last_sync_at, items_synced, status, error_message, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (source, _now(), items, status, error or None, _now()),
        )
        conn.commit()


def _last_sync(source: str) -> str | None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT last_sync_at FROM sync_status WHERE source = ?", (source,)
        ).fetchone()
        return row["last_sync_at"] if row else None


# ---------------------------------------------------------------------------
# Memory Tree 写入
# ---------------------------------------------------------------------------

def _ingest_to_memory_tree(source: str, source_type: str, title: str, content: str) -> dict:
    """直接写入 SQLite（避免通过 MCP 的额外开销，同步场景下批量写入）"""
    content_hash = _sha256(content)

    with _get_conn() as conn:
        # 去重
        existing = conn.execute(
            "SELECT id FROM memory_tree_chunks WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE memory_tree_chunks SET retrieval_count = retrieval_count + 1, "
                "freshness_score = 1.0, updated_at = ? WHERE id = ?",
                (_now(), existing[0]),
            )
            conn.commit()
            return {"status": "duplicate", "id": existing[0]}

        import uuid
        chunk_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO memory_tree_chunks
               (id, source, source_type, title, content, content_hash, score, metadata)
               VALUES (?, ?, ?, ?, ?, ?, 1.0, ?)""",
            (chunk_id, source, source_type, title, content, content_hash, "{}"),
        )
        conn.commit()
        return {"status": "ingested", "id": chunk_id}


# ---------------------------------------------------------------------------
# 飞书数据同步
# ---------------------------------------------------------------------------

def sync_feishu() -> dict[str, int]:
    """
    从飞书同步最新数据到 Memory Tree。
    需要 lark-cli 已安装并授权。
    """
    counts = {"docs": 0, "tables": 0, "errors": 0}

    if os.getenv("FEISHU_ENABLED", "1") != "1":
        return {"skipped": "FEISHU_ENABLED=0"}

    # 检查 lark-cli 是否可用
    lark_bin = os.path.expanduser("~/.hermes/node/bin/lark-cli")
    if not os.path.exists(lark_bin):
        # 尝试 PATH 中的 lark-cli
        try:
            subprocess.run(["lark-cli", "auth", "status"], capture_output=True, timeout=5)
            lark_bin = "lark-cli"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            _update_sync_status("feishu", "failed", error="lark-cli not found or not authorized")
            return {"error": "lark-cli not available"}

    try:
        # 同步最近文档列表
        result = subprocess.run(
            [lark_bin, "doc", "list", "--limit", "20", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            try:
                docs = json.loads(result.stdout)
                for doc in docs if isinstance(docs, list) else docs.get("items", []):
                    doc_id = doc.get("id") or doc.get("document_id", "")
                    title = doc.get("title") or doc.get("name", "未命名文档")
                    if doc_id:
                        # 获取文档内容
                        content_result = subprocess.run(
                            [lark_bin, "doc", "get", doc_id, "--json"],
                            capture_output=True, text=True, timeout=30,
                        )
                        if content_result.returncode == 0:
                            content_data = json.loads(content_result.stdout)
                            content = content_data if isinstance(content_data, str) else json.dumps(content_data, ensure_ascii=False)
                            _ingest_to_memory_tree(
                                source=f"feishu:doc:{doc_id}",
                                source_type="doc",
                                title=title,
                                content=content[:50000],  # 限制大小
                            )
                            counts["docs"] += 1
            except json.JSONDecodeError:
                counts["errors"] += 1

        # 同步多维表格
        result = subprocess.run(
            [lark_bin, "base", "list", "--limit", "10", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            try:
                bases = json.loads(result.stdout)
                for base in bases if isinstance(bases, list) else bases.get("items", []):
                    base_id = base.get("id") or base.get("base_id", "")
                    title = base.get("title") or base.get("name", "未命名表格")
                    if base_id:
                        table_result = subprocess.run(
                            [lark_bin, "base", "table", "list", base_id, "--json"],
                            capture_output=True, text=True, timeout=30,
                        )
                        if table_result.returncode == 0:
                            _ingest_to_memory_tree(
                                source=f"feishu:table:{base_id}",
                                source_type="table",
                                title=title,
                                content=table_result.stdout[:50000],
                            )
                            counts["tables"] += 1
            except json.JSONDecodeError:
                counts["errors"] += 1

        _update_sync_status("feishu", "success", items=counts["docs"] + counts["tables"])

    except subprocess.TimeoutExpired:
        _update_sync_status("feishu", "failed", error="timeout")
        counts["errors"] += 1
    except Exception as e:
        _update_sync_status("feishu", "failed", error=str(e))
        counts["errors"] += 1

    return counts


# ---------------------------------------------------------------------------
# 本地文件同步
# ---------------------------------------------------------------------------

def sync_local_files(directories: list[str] | None = None) -> dict[str, int]:
    """
    从本地目录同步文件到 Memory Tree。
    适用于企业有本地文档服务器/NAS 的场景。
    """
    counts = {"files": 0, "errors": 0}

    if directories is None:
        # 默认扫描的目录（按需配置）
        directories = []

    for directory in directories:
        path = Path(directory)
        if not path.exists():
            continue

        for file_path in path.rglob("*"):
            if file_path.is_file() and file_path.suffix in (".md", ".txt", ".csv", ".json"):
                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    _ingest_to_memory_tree(
                        source=f"file:{file_path}",
                        source_type="file",
                        title=file_path.name,
                        content=content[:50000],
                    )
                    counts["files"] += 1
                except Exception:
                    counts["errors"] += 1

    _update_sync_status("local_files", "success", items=counts["files"])
    return counts


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main() -> None:
    """执行全量同步。"""
    print(f"[{_now()}] Auto-Fetch 开始...")

    # 飞书同步
    feishu_result = sync_feishu()
    print(f"  飞书: {feishu_result}")

    # 本地文件同步（如果配置了目录）
    local_dirs = os.getenv("AUTO_FETCH_LOCAL_DIRS", "").split(":") if os.getenv("AUTO_FETCH_LOCAL_DIRS") else []
    if local_dirs and local_dirs[0]:
        local_result = sync_local_files(local_dirs)
        print(f"  本地文件: {local_result}")

    # 汇总
    with _get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) as n FROM memory_tree_chunks").fetchone()
        print(f"  Memory Tree 总条目: {total['n']}")

    print(f"[{_now()}] Auto-Fetch 完成")


if __name__ == "__main__":
    main()
