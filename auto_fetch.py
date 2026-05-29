#!/usr/bin/env python3
"""
Auto-Fetch — 飞书/本地数据定时同步到 Memory Tree

使用方式：
1. 手动：python3 auto_fetch.py
2. Hermes cronjob 定时触发：每 20 分钟执行
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import logging
logger = logging.getLogger("auto_fetch")
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 统一配置
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from config import DB_PATH, FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_ENABLED
from utils import now as _now, sha256 as _sha256


# ---------------------------------------------------------------------------
# 同步状态管理
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
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
    """直接写入 SQLite（同步场景下批量写入）。
    带重试机制：写入失败自动重试最多 3 次。
    """
    content_hash = _sha256(content)
    max_retries = 3

    for attempt in range(max_retries):
        try:
            with _get_conn() as conn:
                existing = conn.execute(
                    "SELECT id FROM memory_tree_chunks WHERE content_hash = ?", (content_hash,)
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE memory_tree_chunks SET ingest_count = ingest_count + 1, "
                        "freshness_score = 1.0, updated_at = ? WHERE id = ?",
                        (_now(), existing["id"]),
                    )
                    conn.commit()
                    return {"status": "duplicate", "id": existing["id"]}

                import uuid
                chunk_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO memory_tree_chunks
                       (id, source, source_type, title, content, content_hash, score, metadata, faiss_id)
                       VALUES (?, ?, ?, ?, ?, ?, 1.0, ?, -1)  # P2-8: faiss_id=-1, 需后续调用 memory_tree_reindex 重建向量索引""",
                    (chunk_id, source, source_type, title, content, content_hash, "{}"),
                )
                conn.commit()
                return {"status": "ingested", "id": chunk_id}
        except sqlite3.OperationalError:
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise

    return {"status": "error", "message": "写入失败（已达最大重试次数）"}


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
                docs_raw = json.loads(result.stdout)
                docs = docs_raw if isinstance(docs_raw, list) else docs_raw.get("items", [])
                for doc in docs:
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
            except json.JSONDecodeError as e:
                counts["errors"] += 1
                    logger.warning("文件同步失败 %s: %s", file_path.name if "file_path" in dir() else "unknown", e)
                logger.warning("JSON 解析失败: %s", e)

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
            except json.JSONDecodeError as e:
                counts["errors"] += 1
                    logger.warning("文件同步失败 %s: %s", file_path.name if "file_path" in dir() else "unknown", e)
                logger.warning("JSON 解析失败: %s", e)

        _update_sync_status("feishu", "success", items=counts["docs"] + counts["tables"])

    except subprocess.TimeoutExpired:
        _update_sync_status("feishu", "failed", error="timeout")
        counts["errors"] += 1
                    logger.warning("文件同步失败 %s: %s", file_path.name if "file_path" in dir() else "unknown", e)
    except Exception as e:
        _update_sync_status("feishu", "failed", error=str(e))
        counts["errors"] += 1
                    logger.warning("文件同步失败 %s: %s", file_path.name if "file_path" in dir() else "unknown", e)
        logger.error("飞书同步失败: %s", e)
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
        # P1-2: 路径遍历防护 - 解析绝对路径并验证文件在目录内
        base_path = Path(directory).resolve()
        if not base_path.is_dir():
            logger.warning("跳过无效目录: %s", directory)
            continue

        for file_path in base_path.rglob("*"):
            # 确保文件在 base_path 内（防止软链接越界）
            try:
                file_path.resolve().relative_to(base_path)
            except ValueError:
                logger.warning("跳过越界文件（路径遍历防护）: %s", file_path)
                continue

            if file_path.is_file() and file_path.suffix in (".md", ".txt", ".csv", ".json"):
                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    _ingest_to_memory_tree(
                        source=f"file:{file_path.name}",  # 只记录文件名，不包含完整路径
                        source_type="file",
                        title=file_path.name,
                        content=content[:50000],
                    )
                    counts["files"] += 1
                except Exception as e:
                    counts["errors"] += 1
                    logger.warning("文件同步失败 %s: %s", file_path.name if "file_path" in dir() else "unknown", e)

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
