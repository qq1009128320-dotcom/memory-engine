#!/usr/bin/env python3
"""
Agent 记忆引擎 — MCP Server
四层记忆：Memory Tree + 偏好记忆 + 纠错记忆 + 知识图谱

通过 MCP 协议接入任何 Agent 框架（Hermes / Claude / 自定义）。
FastMCP 3.x, Python 3.10+, SQLite.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils import embedding_functions

from fastmcp import FastMCP

# 参数校验
from validators import (
    validate_not_empty, validate_enum, validate_int_range,
    ALLOWED_CATEGORIES, ALLOWED_SEVERITIES, ALLOWED_ERROR_CATEGORIES,
    ALLOWED_ENTITY_TYPES, ALLOWED_SCOPES, ALLOWED_SOURCE_TYPES, ALLOWED_RELATIONS,
)

# ---------------------------------------------------------------------------
# 统一配置（从 config.py 读取，可被 .env 覆盖）
# ---------------------------------------------------------------------------
import sys
sys.path.insert(0, str(Path(__file__).parent))
from config import (
    DB_PATH, CHROMADB_PATH, CHROMADB_COLLECTION,
    EMBEDDING_MODEL, MAX_MEMORY_ROWS as MAX_ROWS,
    MCP_SERVER_NAME,
)

_chroma_client: chromadb.PersistentClient | None = None
_embedding_fn: embedding_functions.EmbeddingFunction | None = None
_chroma_collection: chromadb.Collection | None = None

mcp = FastMCP(MCP_SERVER_NAME)

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    """Get a read-write connection with WAL mode for concurrent access."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_db() -> None:
    """Initialize the database schema."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    if not os.path.exists(schema_path):
        return
    with open(schema_path) as f:
        schema_sql = f.read()
    with _get_conn() as conn:
        conn.executescript(schema_sql)
        conn.commit()


def _get_embedding_fn() -> embedding_functions.EmbeddingFunction:
    """Lazy-load the embedding function.

    Uses ChromaDB built-in ONNX model (all-MiniLM-L6-v2, 384-dim, ~80MB).
    No PyTorch/CUDA required.
    """
    global _embedding_fn
    if _embedding_fn is None:
        _embedding_fn = embedding_functions.DefaultEmbeddingFunction()
    return _embedding_fn


def _get_chroma_collection(force_refresh: bool = False) -> chromadb.Collection:
    """Lazy-load ChromaDB client and collection."""
    global _chroma_client, _chroma_collection
    if force_refresh:
        _chroma_collection = None
    if _chroma_collection is None:
        os.makedirs(str(CHROMADB_PATH), exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=str(CHROMADB_PATH),
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
        ef = _get_embedding_fn()
        _chroma_collection = _chroma_client.get_or_create_collection(
            name=CHROMADB_COLLECTION,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
    return _chroma_collection


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def _rows_to_list(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Layer 1: Memory Tree — 外部数据感知层
# ---------------------------------------------------------------------------

@mcp.tool
def memory_tree_ingest(
    source: str,
    title: str,
    content: str,
    source_type: str = "manual",
    parent_id: str = "",
    metadata: str = "{}",
    generate_summary: bool = False,
) -> dict:
    """
    将内容录入 Memory Tree。
    用于从飞书文档、数据库表、文件等自动同步数据。
    自动做 SHA256 去重——相同内容不会重复存储。

    调用时机：
    - auto_fetch 从飞书/数据库同步数据时
    - 用户手动导入文档时
    - 对话中产生了值得长期保留的信息时
    """
    content_hash = _sha256(content)
    chunk_id = str(uuid.uuid4())

    # 去重检查
    with _get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM memory_tree_chunks WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        if existing:
            # 更新检索计数和新鲜度
            conn.execute(
                "UPDATE memory_tree_chunks SET retrieval_count = retrieval_count + 1, "
                "freshness_score = 1.0, updated_at = ? WHERE id = ?",
                (_now(), existing[0]),
            )
            conn.commit()
            return {
                "status": "duplicate",
                "message": "内容已存在，已更新新鲜度",
                "existing_id": existing[0],
            }

        # 计算摘要（如果启用）
        summary = ""
        if generate_summary:
            summary = content[:200] + "..." if len(content) > 200 else content

        # 估算实体数量（简单的关键词计数）
        entity_count = content.count("客户") + content.count("部门") + content.count("项目")

        conn.execute(
            """INSERT INTO memory_tree_chunks
               (id, source, source_type, title, content, content_hash,
                parent_id, summary, score, entity_count, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?)""",
            (
                chunk_id, source, source_type, title, content, content_hash,
                parent_id or None, summary, entity_count, metadata,
            ),
        )
        conn.commit()

        # 同时写入 ChromaDB 向量索引
        try:
            collection = _get_chroma_collection()
            doc_text = f"{title}\n{content[:8000]}"
            collection.add(
                ids=[chunk_id],
                documents=[doc_text],
                metadatas=[{
                    "source": source,
                    "source_type": source_type,
                    "title": title,
                    "id": chunk_id,
                }],
            )
        except Exception as e:
            import logging
            logging.getLogger("memory_engine").warning("ChromaDB indexing skipped: %s", e)

    return {
        "status": "ingested",
        "id": chunk_id,
        "hash": content_hash,
        "entity_count": entity_count,
    }


@mcp.tool
def memory_tree_search(query: str, max_results: int = 10, source_type: str = "") -> list[dict]:
    """
    从 Memory Tree 中搜索相关内容。
    按评分降序排列——经常被检索、新、重要的内容排在前面。

    调用时机：
    - Agent 需要了解企业文档/数据时
    - 用户问「关于 XX 有什么资料」
    - 任务开始前，了解相关背景
    """
    sql = """SELECT id, source, source_type, title, summary, score, entity_count, created_at
             FROM memory_tree_chunks WHERE 1=1"""
    params: list = []

    if source_type:
        sql += " AND source_type = ?"
        params.append(source_type)

    # 全文搜索：标题或内容包含关键词
    if query:
        sql += " AND (title LIKE ? OR content LIKE ? OR summary LIKE ?)"
        like = f"%{query}%"
        params.extend([like, like, like])

    sql += " ORDER BY score DESC LIMIT ?"
    params.append(max_results)

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    return _rows_to_list(rows)


@mcp.tool
def memory_tree_fetch(id: str) -> dict | None:
    """
    获取 Memory Tree 中某一条记录的完整内容。
    用于 Agent 需要深入查看某条记忆的详情时。

    调用时机：
    - memory_tree_search 返回摘要后，需要查看完整内容
    """
    with _get_conn() as conn:
        conn.execute(
            "UPDATE memory_tree_chunks SET retrieval_count = retrieval_count + 1 WHERE id = ?",
            (id,),
        )
        row = conn.execute("SELECT * FROM memory_tree_chunks WHERE id = ?", (id,)).fetchone()
        conn.commit()
    return _row_to_dict(row)


@mcp.tool
def memory_tree_score(id: str, delta: float) -> dict:
    """
    调整 Memory Tree 中某条记录的评分。
    正数提升，负数降低。被用户纠正的内容应该降分。

    调用时机：
    - 用户指出某条记忆不准确
    - 用户标记某条记忆很重要
    """
    with _get_conn() as conn:
        conn.execute(
            "UPDATE memory_tree_chunks SET score = MAX(0, score + ?), "
            "correction_count = correction_count + CASE WHEN ? < 0 THEN 1 ELSE 0 END, "
            "updated_at = ? WHERE id = ?",
            (delta, delta, _now(), id),
        )
        conn.commit()
    return {"status": "ok", "id": id, "delta": delta}


@mcp.tool
def memory_tree_vector_search(
    query: str,
    max_results: int = 10,
    source_type: str = "",
) -> list[dict]:
    """
    语义向量搜索 Memory Tree。
    使用 BGE-M3 做语义匹配，比关键词搜索更精准。

    优先使用此工具而非 memory_tree_search（关键词搜索）
    当用户用自然语言描述需求时。

    调用时机：
    - Agent 需要了解企业文档/数据时
    - 用户问自然语言问题（非精确关键词）
    - memory_tree_search 结果不理想时
    """
    try:
        collection = _get_chroma_collection()

        where_filter = None
        if source_type:
            where_filter = {"source_type": source_type}

        results = collection.query(
            query_texts=[query],
            n_results=max_results,
            where=where_filter,
        )

        items: list[dict] = []
        if results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results.get("distances") else 0.0
                items.append({
                    "id": chunk_id,
                    "title": metadata.get("title", ""),
                    "source": metadata.get("source", ""),
                    "source_type": metadata.get("source_type", ""),
                    "score": 1.0 - distance,  # cosine distance → similarity
                })

        return items
    except Exception as e:
        # 向量搜失败时降级为关键词搜索
        return memory_tree_search(query, max_results, source_type)


@mcp.tool
def memory_tree_reindex() -> dict:
    """
    重建所有现有 Memory Tree 条目的向量索引。
    在新安装 embedding 模型后、或更换模型后使用。

    调用时机：
    - 首次部署后
    - 切换 embedding 模型后
    - 向量索引损坏时
    """
    try:
        collection = _get_chroma_collection(force_refresh=True)
        # 清空现有向量索引
        existing = collection.get()
        if existing["ids"]:
            collection.delete(ids=existing["ids"])

        # 从 SQLite 读取所有条目
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT id, source, source_type, title, content FROM memory_tree_chunks"
            ).fetchall()

        if not rows:
            return {"status": "ok", "indexed": 0, "message": "没有需要索引的条目"}

        # 批量生成 embeddings
        batch_size = 32
        total = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            ids = []
            documents = []
            metadatas = []
            for row in batch:
                doc_text = f"{row['title']}\n{row['content'][:8000]}"
                ids.append(row["id"])
                documents.append(doc_text)
                metadatas.append({
                    "source": row["source"],
                    "source_type": row["source_type"],
                    "title": row["title"] or "",
                    "id": row["id"],
                })

            collection.add(ids=ids, documents=documents, metadatas=metadatas)
            total += len(batch)

        return {"status": "ok", "indexed": total}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool
def memory_tree_summary(level: str = "all") -> dict:
    """
    获取 Memory Tree 的层级摘要树（L0/L1/L2）。

    level 可选值:
    - l0: 只返回全局概览
    - l1: 返回全局概览 + 各组摘要
    - l2: 返回全局概览 + 各组摘要 + 展开某个组的所有原始块（需指定 group_key）
    - all: 返回 L0+L1 结构（默认）

    调用时机：
    - 对话开始时了解整体知识覆盖范围
    - 用户问"公司有哪些制度/政策"
    - 需要快速了解知识库内容时
    """
    with _get_conn() as conn:
        # 查 L0
        l0 = conn.execute(
            "SELECT content FROM memory_tree_chunks WHERE source_type = 'summary' AND title = 'L0_全局概览'"
        ).fetchone()

        # 查 L1（所有有 parent_id 的 chunk，按 parent_id 分组）
        groups = conn.execute(
            """SELECT parent_id, summary, COUNT(*) as chunk_count
               FROM memory_tree_chunks
               WHERE parent_id IS NOT NULL AND parent_id LIKE 'l1:%'
               GROUP BY parent_id"""
        ).fetchall()

    return {
        "l0": l0["content"] if l0 else None,
        "l1_groups": [
            {
                "group_key": g["parent_id"],
                "summary": g["summary"],
                "chunk_count": g["chunk_count"],
            }
            for g in groups
        ],
    }


# ---------------------------------------------------------------------------
# Layer 2: Preference Memory — 偏好/规则层
# ---------------------------------------------------------------------------

@mcp.tool
def preference_add(
    category: str,
    condition: str,
    rule: str,
    scope: str = "personal",
    department: str = "",
    source_type: str = "manual",
    confidence: float = 0.8,
) -> dict:
    """
    添加一条偏好/规则记忆。
    用户纠正 Agent 后、或发现新的数据规范时调用。

    category 可选值：
    - field_alias: 字段名映射（如 "amt_jpy 是正确金额字段"）
    - date_rule: 日期规则（如 "结算是 25 号到 25 号"）
    - naming: 命名约定（如 "腾讯客户名是 Tencent"）
    - policy: 业务政策（如 "研发全部费用化"）
    - format: 格式偏好（如 "报告用环比而非同比"）

    调用时机：
    - 用户纠正了 Agent 的错误
    - 用户明确告诉 Agent 「记住...」
    """
    validate_not_empty(condition, "condition")
    validate_not_empty(rule, "rule")
    validate_enum(category, "category", ALLOWED_CATEGORIES)
    validate_enum(source_type, "source_type", ALLOWED_SOURCE_TYPES)

    rule_hash = _sha256(f"{condition}|{rule}")
    pref_id = str(uuid.uuid4())

    with _get_conn() as conn:
        existing = conn.execute(
            "SELECT id, correction_count FROM preference_memory WHERE rule_hash = ?",
            (rule_hash,),
        ).fetchone()

        if existing:
            # 更新已存在的规则
            conn.execute(
                """UPDATE preference_memory
                   SET correction_count = correction_count + 1,
                       confidence = MIN(1.0, confidence + 0.05),
                       updated_at = ?
                   WHERE id = ?""",
                (_now(), existing[0]),
            )
            conn.commit()
            return {
                "status": "updated",
                "id": existing[0],
                "correction_count": existing["correction_count"] + 1,
                "message": "规则已存在，已提升可信度",
            }

        conn.execute(
            """INSERT INTO preference_memory
               (id, category, condition, rule, rule_hash, source_type,
                confidence, scope, department)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pref_id, category, condition, rule, rule_hash, source_type,
             confidence, scope, department or None),
        )
        conn.commit()

    return {"status": "created", "id": pref_id, "rule_hash": rule_hash}


@mcp.tool
def preference_search(query: str, category: str = "", scope: str = "", max_results: int = 20) -> list[dict]:
    """
    搜索偏好记忆。Agent 在执行任务前应调用此工具。

    调用时机（每次执行涉及以下内容的任务前必须调用）：
    - 涉及客户名、供应商名、项目名
    - 涉及金额、日期、费用
    - 任务类型为分析/对比/生成报告
    """
    sql = """SELECT id, category, condition, rule, scope, department,
                    confidence, correction_count, is_active
             FROM preference_memory WHERE is_active = 1"""
    params: list = []

    if category:
        sql += " AND category = ?"
        params.append(category)

    if scope:
        if scope == "all_shared":
            sql += " AND scope != 'personal'"
        else:
            sql += " AND (scope = ? OR scope = 'organization')"
            params.append(scope)

    if query:
        sql += " AND (condition LIKE ? OR rule LIKE ?)"
        like = f"%{query}%"
        params.extend([like, like])

    sql += " ORDER BY confidence DESC, correction_count DESC LIMIT ?"
    params.append(max_results)

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    return _rows_to_list(rows)


@mcp.tool
def preference_list(scope: str = "personal", department: str = "") -> list[dict]:
    """
    列出所有偏好记忆（按范围过滤）。
    用于 Agent 了解当前已有哪些已知规则。

    调用时机：
    - 新 Agent 启动时，加载已有偏好
    - 用户想查看 Agent 都记住了什么
    """
    sql = "SELECT id, category, condition, rule, scope, confidence FROM preference_memory WHERE is_active = 1"
    params: list = []

    if scope == "all":
        pass  # 不过滤
    elif scope == "shared":
        sql += " AND scope != 'personal'"
    else:
        sql += " AND (scope = ? OR scope = 'organization')"
        params.append(scope)

    if department:
        sql += " AND department = ?"
        params.append(department)

    sql += " ORDER BY category, confidence DESC"

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return _rows_to_list(rows)


@mcp.tool
def preference_disable(id: str) -> dict:
    """
    禁用一条偏好记忆。
    当规则被证明不再适用时调用。

    调用时机：
    - 用户说「这个不对，以后别这样了」
    - 旧规则被新规则取代
    """
    with _get_conn() as conn:
        conn.execute(
            "UPDATE preference_memory SET is_active = 0, updated_at = ? WHERE id = ?",
            (_now(), id),
        )
        conn.commit()
    return {"status": "disabled", "id": id}


# ---------------------------------------------------------------------------
# Layer 3: Error Memory — 纠错记忆层
# ---------------------------------------------------------------------------

@mcp.tool
def error_check(task_type: str = "", task_description: str = "", max_results: int = 5) -> list[dict]:
    """
    检查类似任务以前是否出过错。
    执行任务前必须调用此工具——它会返回以前的相关错误，帮助 Agent 避免重蹈覆辙。

    调用时机（强制）：
    - 每次执行财务/数据/分析等任务前
    - 任务涉及计算结果时
    - 用户明确提到「上次这里出过错」
    """
    sql = """SELECT id, task_type, error_category, mistake_description,
                    correction, prevention_rule, severity, occurrence_count
             FROM error_memory WHERE is_resolved = 0"""
    params: list = []

    if task_type:
        sql += " AND task_type = ?"
        params.append(task_type)

    if task_description:
        sql += " AND (mistake_description LIKE ? OR correction LIKE ?)"
        like = f"%{task_description}%"
        params.extend([like, like])

    sql += " ORDER BY occurrence_count DESC, severity = 'critical' DESC LIMIT ?"
    params.append(max_results)

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    return _rows_to_list(rows)


@mcp.tool
def error_log(
    task_type: str,
    error_category: str,
    mistake_description: str,
    correction: str,
    severity: str = "minor",
    prevention_rule: str = "",
) -> dict:
    """
    记录一次 Agent 错误和用户纠正。
    用户纠正 Agent 后调用此工具。

    error_category 可选值：
    - field_selection: 选错了字段
    - logic_error: 逻辑错误（如把同比当环比）
    - scope_error: 范围错误（如用了自然月而非结算月）
    - omission: 遗漏了步骤或数据源

    severity 可选值：minor | major | critical

    调用时机：
    - 用户纠正 Agent 的任何错误后
    - extract_facts.py 自动检测到纠正行为后
    """
    validate_not_empty(task_type, "task_type")
    validate_not_empty(mistake_description, "mistake_description")
    validate_not_empty(correction, "correction")
    validate_enum(error_category, "error_category", ALLOWED_ERROR_CATEGORIES)
    validate_enum(severity, "severity", ALLOWED_SEVERITIES)

    error_id = str(uuid.uuid4())

    # 查找相似错误
    with _get_conn() as conn:
        existing = conn.execute(
            """SELECT id, occurrence_count FROM error_memory
               WHERE is_resolved = 0 AND task_type = ? AND error_category = ?
               AND mistake_description LIKE ? LIMIT 1""",
            (task_type, error_category, f"%{mistake_description[:50]}%"),
        ).fetchone()

        if existing:
            new_count = existing["occurrence_count"] + 1
            conn.execute(
                """UPDATE error_memory
                   SET occurrence_count = ?, last_occurrence = ?, updated_at = ?,
                       severity = CASE WHEN ? >= 3 THEN 'major' ELSE severity END
                   WHERE id = ?""",
                (new_count, _now(), _now(), new_count, existing["id"]),
            )

            # 如果累计 3 次以上，自动升级为偏好记忆
            if new_count >= 3:
                # 创建对应的偏好规则
                rule_hash = _sha256(f"prevent:{task_type}|{correction}")
                pref_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT OR IGNORE INTO preference_memory
                       (id, category, condition, rule, rule_hash, source_type, confidence, scope)
                       VALUES (?, 'field_alias', ?, ?, ?, 'extracted', 0.9, 'personal')""",
                    (pref_id, f"任务类型={task_type}", correction, rule_hash),
                )
                conn.execute(
                    "UPDATE error_memory SET is_resolved = 1, resolved_to = ? WHERE id = ?",
                    (pref_id, existing["id"]),
                )

            conn.commit()
            return {
                "status": "updated",
                "id": existing["id"],
                "occurrence_count": new_count,
                "upgraded_to_preference": new_count >= 3,
            }

        # 新错误
        conn.execute(
            """INSERT INTO error_memory
               (id, task_type, error_category, mistake_description, correction,
                prevention_rule, severity)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (error_id, task_type, error_category, mistake_description, correction,
             prevention_rule or None, severity),
        )
        conn.commit()

    return {"status": "created", "id": error_id}


@mcp.tool
def error_list(task_type: str = "", is_resolved: int = 0) -> list[dict]:
    """
    列出错误记录。
    用于审核 Agent 的性能和改进情况。

    调用时机：
    - 管理员想查看 Agent 都犯过什么错
    - 复盘 Agent 的表现
    """
    sql = "SELECT id, task_type, error_category, mistake_description, severity, occurrence_count FROM error_memory WHERE 1=1"
    params: list = []

    if task_type:
        sql += " AND task_type = ?"
        params.append(task_type)

    sql += " AND is_resolved = ?"
    params.append(is_resolved)

    sql += " ORDER BY occurrence_count DESC"

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return _rows_to_list(rows)


# ---------------------------------------------------------------------------
# Layer 4: Knowledge Graph — 知识图谱层
# ---------------------------------------------------------------------------

@mcp.tool
def entity_add(
    type: str,
    name: str,
    aliases: str = "[]",
    properties: str = "{}",
    scope: str = "personal",
    department: str = "",
) -> dict:
    """
    添加一个实体到知识图谱。
    实体可以是客户、部门、人员、政策、项目等。

    type 可选值：person | department | client | policy | document | field | project

    调用时机：
    - 发现新的客户/供应商/人员时
    - 从飞书文档中自动提取实体时
    - extract_facts.py 检测到新的实体关系时
    """
    validate_not_empty(name, "name")
    validate_enum(type, "type", ALLOWED_ENTITY_TYPES)
    validate_enum(scope, "scope", ALLOWED_SCOPES)

    entity_id = str(uuid.uuid4())

    with _get_conn() as conn:
        # 检查是否已有同名实体
        existing = conn.execute(
            "SELECT id FROM entities WHERE name = ? AND type = ?",
            (name, type),
        ).fetchone()

        if existing:
            # 合并别名
            current = conn.execute(
                "SELECT aliases FROM entities WHERE id = ?", (existing[0],)
            ).fetchone()
            try:
                current_aliases = json.loads(current["aliases"]) if current and current["aliases"] else []
                new_aliases = json.loads(aliases) if isinstance(aliases, str) else aliases
                merged = list(set(current_aliases + new_aliases))
            except (json.JSONDecodeError, TypeError):
                merged = []

            conn.execute(
                "UPDATE entities SET aliases = ?, updated_at = ? WHERE id = ?",
                (json.dumps(merged, ensure_ascii=False), _now(), existing[0]),
            )
            conn.commit()
            return {"status": "merged", "id": existing[0], "aliases": merged}

        conn.execute(
            """INSERT INTO entities (id, type, name, aliases, properties, scope, department)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (entity_id, type, name, aliases, properties, scope, department or None),
        )
        conn.commit()

    return {"status": "created", "id": entity_id}


@mcp.tool
def entity_search(query: str, type: str = "", max_results: int = 10) -> list[dict]:
    """
    搜索知识图谱中的实体。
    支持按名称和别名搜索。

    调用时机：
    - 任务涉及某个客户/部门/人员时
    - 需要确认实体是否存在时
    """
    sql = """SELECT id, type, name, aliases, properties, scope, department
             FROM entities WHERE 1=1"""
    params: list = []

    if type:
        sql += " AND type = ?"
        params.append(type)

    if query:
        sql += " AND (name LIKE ? OR aliases LIKE ?)"
        like = f"%{query}%"
        params.extend([like, like])

    sql += " LIMIT ?"
    params.append(max_results)

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    return _rows_to_list(rows)


@mcp.tool
def entity_link(
    source_name: str,
    target_name: str,
    relation: str,
    source_type: str = "",
    target_type: str = "",
    scope: str = "personal",
    properties: str = "{}",
) -> dict:
    """
    建立两个实体之间的关系。
    如果实体不存在，会自动创建。

    relation 可选值：belongs_to | manages | alias_of | depends_on | owns | approves | works_in

    调用时机：
    - 发现「张三是财务部的人」这类关系时
    - 从对话中提取实体关系后
    - extract_facts.py 检测到新关系时
    """
    validate_not_empty(source_name, "source_name")
    validate_not_empty(target_name, "target_name")
    validate_enum(relation, "relation", ALLOWED_RELATIONS)

    with _get_conn() as conn:
        # 查找或创建 source 实体
        src = conn.execute(
            "SELECT id FROM entities WHERE name = ?" + (f" AND type = ?" if source_type else ""),
            (source_name,) + ((source_type,) if source_type else ()),
        ).fetchone()

        if not src:
            src_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO entities (id, type, name, scope) VALUES (?, ?, ?, ?)",
                (src_id, source_type or "unknown", source_name, scope),
            )
        else:
            src_id = src[0]

        # 查找或创建 target 实体
        tgt = conn.execute(
            "SELECT id FROM entities WHERE name = ?" + (f" AND type = ?" if target_type else ""),
            (target_name,) + ((target_type,) if target_type else ()),
        ).fetchone()

        if not tgt:
            tgt_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO entities (id, type, name, scope) VALUES (?, ?, ?, ?)",
                (tgt_id, target_type or "unknown", target_name, scope),
            )
        else:
            tgt_id = tgt[0]

        # 建立关系（去重）
        existing_rel = conn.execute(
            "SELECT id FROM relationships WHERE source_id = ? AND target_id = ? AND relation = ?",
            (src_id, tgt_id, relation),
        ).fetchone()

        if existing_rel:
            return {"status": "duplicate", "id": existing_rel[0]}

        rel_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO relationships (id, source_id, target_id, relation, properties, scope)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (rel_id, src_id, tgt_id, relation, properties, scope),
        )
        conn.commit()

    return {"status": "created", "id": rel_id, "source_id": src_id, "target_id": tgt_id}


@mcp.tool
def graph_query(entity_name: str) -> dict:
    """
    查询某个实体的完整知识图谱——实体信息 + 所有关联关系。

    调用时机：
    - Agent 需要全面了解某个客户/人员/部门时
    - 做复杂决策需要上下文时
    """
    with _get_conn() as conn:
        # 查找实体
        entity = conn.execute(
            "SELECT * FROM entities WHERE name = ? OR aliases LIKE ?",
            (entity_name, f"%{entity_name}%"),
        ).fetchone()

        if not entity:
            return {"error": f"实体 '{entity_name}' 未找到"}

        entity_dict = dict(entity)

        # 查找所有关联
        outgoing = conn.execute(
            """SELECT r.relation, r.properties, r.scope,
                      e2.name as target_name, e2.type as target_type
               FROM relationships r
               JOIN entities e2 ON r.target_id = e2.id
               WHERE r.source_id = ?""",
            (entity_dict["id"],),
        ).fetchall()

        incoming = conn.execute(
            """SELECT r.relation, r.properties, r.scope,
                      e1.name as source_name, e1.type as source_type
               FROM relationships r
               JOIN entities e1 ON r.source_id = e1.id
               WHERE r.target_id = ?""",
            (entity_dict["id"],),
        ).fetchall()

    return {
        "entity": entity_dict,
        "outgoing_relations": _rows_to_list(outgoing),
        "incoming_relations": _rows_to_list(incoming),
    }


# ---------------------------------------------------------------------------
# Cross-layer: 综合检索
# ---------------------------------------------------------------------------

@mcp.tool
def memory_search(query: str, layers: str = "all", max_results: int = 20) -> dict:
    """
    跨四层综合检索。
    输入用户的自然语言问题，返回所有相关记忆。

    这是最主要的检索入口。Agent 在执行任何涉及企业数据的任务前，
    应该先调用此工具获取上下文。

    layers 可选值：all | memory_tree | preferences | errors | graph

    调用时机（每次对话开始时建议调用）：
    - 用户提到具体的客户名、项目名、部门名
    - 任务涉及财务数据、分析、报告
    - 需要了解企业政策或制度时
    """
    results: dict[str, list] = {}

    if layers in ("all", "memory_tree"):
        # 优先向量语义搜索，失败时自动降级为关键词搜索
        results["memory_tree"] = memory_tree_vector_search(query, max_results=max_results // 2)

    if layers in ("all", "preferences"):
        results["preferences"] = preference_search(query, max_results=max_results // 2)

    if layers in ("all", "errors"):
        results["errors"] = error_check(task_description=query, max_results=max_results // 2)

    if layers in ("all", "graph"):
        results["graph"] = entity_search(query, max_results=max_results // 2)

    return results


@mcp.tool
def memory_stats() -> dict:
    """
    获取记忆系统统计信息。
    用于了解当前记忆库的规模和使用情况。

    调用时机：
    - 管理员检查系统状态
    - 用户问「Agent 记住了多少东西」
    """
    with _get_conn() as conn:
        stats = {
            "memory_tree_chunks": conn.execute(
                "SELECT COUNT(*) as n FROM memory_tree_chunks"
            ).fetchone()["n"],
            "preferences": conn.execute(
                "SELECT COUNT(*) as n FROM preference_memory WHERE is_active = 1"
            ).fetchone()["n"],
            "preferences_disabled": conn.execute(
                "SELECT COUNT(*) as n FROM preference_memory WHERE is_active = 0"
            ).fetchone()["n"],
            "errors": conn.execute(
                "SELECT COUNT(*) as n FROM error_memory WHERE is_resolved = 0"
            ).fetchone()["n"],
            "errors_resolved": conn.execute(
                "SELECT COUNT(*) as n FROM error_memory WHERE is_resolved = 1"
            ).fetchone()["n"],
            "entities": conn.execute(
                "SELECT COUNT(*) as n FROM entities"
            ).fetchone()["n"],
            "relationships": conn.execute(
                "SELECT COUNT(*) as n FROM relationships"
            ).fetchone()["n"],
            "top_categories": _rows_to_list(conn.execute(
                "SELECT category, COUNT(*) as count FROM preference_memory "
                "WHERE is_active = 1 GROUP BY category ORDER BY count DESC LIMIT 5"
            ).fetchall()),
            "top_error_types": _rows_to_list(conn.execute(
                "SELECT error_category, COUNT(*) as count FROM error_memory "
                "WHERE is_resolved = 0 GROUP BY error_category ORDER BY count DESC LIMIT 5"
            ).fetchall()),
        }

    # 附加 ChromaDB 统计（需要在 with 块外面，因为 _get_chroma_collection 会打开自己的连接）
    try:
        collection = _get_chroma_collection()
        stats["chromadb_indexed"] = collection.count()
        stats["embedding_model"] = EMBEDDING_MODEL
    except Exception as e:
        import logging
        logging.getLogger("memory_engine").warning("ChromaDB stats unavailable: %s", e)
        stats["chromadb_indexed"] = "未初始化"
        stats["embedding_model"] = EMBEDDING_MODEL

    return stats


@mcp.tool
def memory_health() -> dict:
    """
    健康检查 + 运行指标。

    返回数据库连接状态、ChromaDB 状态、请求量/延迟/错误率等。
    """
    from observability import health_check, metrics
    result = health_check()
    result["metrics"] = metrics.snapshot()
    return result


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _init_db()
    mcp.run()
