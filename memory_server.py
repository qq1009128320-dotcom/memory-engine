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
import logging
import os
import sqlite3
import atexit
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from cachetools import TTLCache, cached

from fastmcp import FastMCP

from observability import health_check, metrics

logger = logging.getLogger("memory_engine")

# 参数校验
from validators import (
    validate_not_empty, validate_enum, validate_int_range, validate_scope,
    ALLOWED_CATEGORIES, ALLOWED_SEVERITIES, ALLOWED_ERROR_CATEGORIES,
    ALLOWED_ENTITY_TYPES, ALLOWED_SCOPES, ALLOWED_SOURCE_TYPES, ALLOWED_RELATIONS,
)

# ---------------------------------------------------------------------------
# 统一配置（从 config.py 读取，可被 .env 覆盖）
# ---------------------------------------------------------------------------
import sys
sys.path.insert(0, str(Path(__file__).parent))
from config import (
    DB_PATH,
    FAISS_INDEX_PATH, EMBEDDING_MODEL, MAX_MEMORY_ROWS as MAX_ROWS,
    MCP_SERVER_NAME, PID_FILE, ROOT,
)

# ---------------------------------------------------------------------------
# 单实例锁（防止多个 memory_server 同时运行导致 SQLite 锁冲突）
# ---------------------------------------------------------------------------

def _acquire_lock() -> bool:
    """获取 PID 文件锁。返回 True 表示获取成功，False 表示已有实例运行中。"""
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            os.kill(old_pid, 0)  # 信号 0 只检查进程是否存在
            # 进程还在运行 —— 锁被持有
            return False
        except (ValueError, ProcessLookupError, OSError):
            # PID 无效或进程已死（OSError 覆盖 Windows 等平台）—— 过期锁，可以抢占
            pass

    # 写入当前 PID
    PID_FILE.write_text(str(os.getpid()))
    return True


def _release_lock() -> None:
    """释放 PID 文件锁。"""
    try:
        if PID_FILE.exists() and int(PID_FILE.read_text().strip()) == os.getpid():
            PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


_faiss_index: faiss.Index | None = None
_faiss_id_map: dict[int, str] = {}  # FAISS idx → chunk_id
_next_faiss_id: int = 0
_embedding_model: SentenceTransformer | None = None

# ---------------------------------------------------------------------------
# TTL 内存缓存层（替代 Redis，无需额外进程）
# ---------------------------------------------------------------------------
_search_cache = TTLCache(maxsize=5000, ttl=1800)   # 5 千条缓存，30 分钟过期（原 5 万条，内存优化）
_ingest_cache = TTLCache(maxsize=1000, ttl=86400)  # 去重缓存，24 小时过期（原 1 万条，内存优化）
_embed_cache = TTLCache(maxsize=500, ttl=3600)      # 嵌入缓存，500 条，1 小时过期（原 2000 条，内存优化）

mcp = FastMCP(MCP_SERVER_NAME)

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# SQLite 连接池（线程本地 + 性能优化）
# ---------------------------------------------------------------------------
_conn_local = threading.local()

def _get_conn() -> sqlite3.Connection:
    """获取线程本地的 SQLite 连接（复用，避免每次新建）。"""
    if not hasattr(_conn_local, "conn") or _conn_local.conn is None:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-128000")  # 128MB（提升查询性能）
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=134217728")   # 128MB（原 512MB，内存优化）
        conn.execute("PRAGMA busy_timeout=10000")   # 5s → 10s
        conn.execute("PRAGMA page_size=4096")        # 4KB 页（适配 SSD）
        _conn_local.conn = conn
    return _conn_local.conn


def _init_db() -> None:
    """Initialize the database schema."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    if not os.path.exists(schema_path):
        return
    with open(schema_path) as f:
        schema_sql = f.read()
    with _get_conn() as conn:
        conn.executescript(schema_sql)
        # 持久化性能优化配置
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-128000")  # 128MB 缓存
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=134217728")   # 128MB 内存映射
        conn.execute("PRAGMA busy_timeout=10000")   # 10s 超时
        conn.execute("PRAGMA page_size=4096")        # 4KB 页
        conn.commit()


def _get_embedding_model() -> SentenceTransformer:
    """Lazy-load the SentenceTransformer embedding model.

    all-MiniLM-L6-v2 (384-dim, ~80MB). No GPU required.
    Uses local_files_only=True to avoid HF network timeouts in offline envs.
    """
    global _embedding_model
    if _embedding_model is None:
        logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL, local_files_only=True)
    return _embedding_model


VECTOR_DIM = 384  # all-MiniLM-L6-v2 维度
# FAISS_INDEX_PATH 已从 config 导入


def _get_faiss_index() -> faiss.Index:
    """Lazy-load FAISS index from disk.
    IVF400 with L2 distance. Supports ~500万 vectors in 4GB RAM.
    使用数据库中存储的 faiss_id 字段重建 id_map，而非靠 ROWID 顺序推断。
    """
    global _faiss_index, _faiss_id_map, _next_faiss_id

    if _faiss_index is None:
        if FAISS_INDEX_PATH.exists():
            logger.info("Loading FAISS index from %s", FAISS_INDEX_PATH)
            _faiss_index = faiss.read_index(str(FAISS_INDEX_PATH))

            # 用数据库中的 faiss_id 字段重建 id_map（精确，不依赖 ROWID 顺序）
            _faiss_id_map = {}
            _next_faiss_id = 0
            with _get_conn() as conn:
                rows = conn.execute(
                    "SELECT id, faiss_id FROM memory_tree_chunks "
                    "WHERE faiss_id >= 0 ORDER BY faiss_id"
                ).fetchall()
                for row in rows:
                    fid = row["faiss_id"]
                    _faiss_id_map[fid] = row["id"]
                    if fid >= _next_faiss_id:
                        _next_faiss_id = fid + 1

            logger.info("FAISS index loaded: %d vectors", len(_faiss_id_map))
        else:
            logger.info("Creating new FAISS index (Flat, L2)")
            _faiss_index = faiss.IndexIDMap(faiss.IndexFlatL2(VECTOR_DIM))
            _faiss_id_map = {}
            _next_faiss_id = 0

    return _faiss_index


def _embed_text(text: str) -> np.ndarray:
    """Embed a single text to 384-dim vector（带 LRU 缓存，高频重复查询复用向量）。"""
    cached = _embed_cache.get(text)
    if cached is not None:
        return cached
    vector = _get_embedding_model().encode([text])[0].astype('float32')
    _embed_cache[text] = vector
    return vector


def _embed_texts(texts: list[str]) -> np.ndarray:
    """Embed multiple texts in batch."""
    return _get_embedding_model().encode(texts).astype('float32')


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

    global _faiss_index, _faiss_id_map, _next_faiss_id

    # ── 去重检查 ──────────────────────────────────────────────
    with _get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM memory_tree_chunks WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()

        if existing:
            # 更新 ingest_count（不是 retrieval_count）和新鲜度
            conn.execute(
                "UPDATE memory_tree_chunks SET ingest_count = ingest_count + 1, "
                "freshness_score = 1.0, updated_at = ? WHERE id = ?",
                (_now(), existing["id"]),
            )
            conn.commit()
            return {
                "status": "duplicate",
                "message": "内容已存在，已更新新鲜度",
                "existing_id": existing["id"],
            }

    # ── 计算摘要（可选）────────────────────────────────────────
    summary = ""
    if generate_summary:
        summary = content[:200] + "..." if len(content) > 200 else content

    entity_count = content.count("客户") + content.count("部门") + content.count("项目")

    # ── 先插入数据库行（faiss_id 暂设 -1）─────────────────────
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO memory_tree_chunks
               (id, source, source_type, title, content, content_hash,
                parent_id, summary, score, entity_count, metadata, faiss_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?, -1)""",
            (
                chunk_id, source, source_type, title, content, content_hash,
                parent_id or None, summary, entity_count, metadata,
            ),
        )
        conn.commit()

    # 清空搜索缓存
    _search_cache.clear()

    # ── 生成向量并写入 FAISS ───────────────────────────────────
    try:
        doc_text = f"{title}\n{content[:8000]}"
        vector = _embed_text(doc_text)
        index = _get_faiss_index()

        if hasattr(index, "is_trained") and not index.is_trained:
            logger.info("Index not trained, upgrading to Flat index")
            index = faiss.IndexIDMap(faiss.IndexFlatL2(VECTOR_DIM))
            _faiss_index = index

        fid = _next_faiss_id
        index.add_with_ids(
            vector.reshape(1, -1).astype("float32"),
            np.array([fid], dtype=np.int64),
        )
        _faiss_id_map[fid] = chunk_id
        _next_faiss_id = fid + 1

        faiss.write_index(index, str(FAISS_INDEX_PATH))

        # 同步更新数据库中的 faiss_id 和 vector（新连接，保证事务独立）
        with _get_conn() as conn:
            conn.execute(
                "UPDATE memory_tree_chunks SET faiss_id = ?, vector = ? WHERE id = ?",
                (fid, vector.tobytes(), chunk_id),
            )
            conn.commit()

    except Exception as e:
        logger.warning("FAISS indexing failed: %s", e)

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

    # 全文搜索：按词分词匹配，不做整句连续匹配
    if query:
        terms = query.split()
        for term in terms:
            if len(term) < 2:
                continue  # 跳过单字
            sql += " AND (title LIKE ? OR content LIKE ? OR summary LIKE ?)"
            like = f"%{term}%"
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
    使用 SentenceTransformer (all-MiniLM-L6-v2, 384-dim) + FAISS IVFFlat 索引。

    比关键词搜索更精准。Agent 应优先使用此工具。

    调用时机：
    - Agent 需要了解企业文档/数据时
    - 用户问自然语言问题（非精确关键词）
    - memory_tree_search 结果不理想时
    """
    cache_key = f"vs:{query}:{source_type}:{max_results}"
    cached_result = _search_cache.get(cache_key)
    if cached_result is not None:
        return cached_result

    index = _get_faiss_index()
    if index.ntotal == 0:
        return []

    query_vector = _embed_text(query)
    distances, indices = index.search(
        query_vector.reshape(1, -1).astype('float32'),
        min(max_results * 2, index.ntotal)
    )

    items: list[dict] = []
    # 批量获取所有候选chunk_id
    candidate_ids = [_faiss_id_map[fid] for fid in indices[0] 
                     if fid >= 0 and fid in _faiss_id_map]
    
    with _get_conn() as conn:
        if not candidate_ids:
            return []
        
        # 批量查询，避免循环内单条查询
        placeholders = ','.join('?' * len(candidate_ids))
        rows = conn.execute(
            f"SELECT id, source, source_type, title, summary, score "
            f"FROM memory_tree_chunks WHERE id IN ({placeholders})",
            candidate_ids
        ).fetchall()
        
        # 构建id到row的映射
        row_map = {row["id"]: row for row in rows}
        
        for dist, fid in zip(distances[0], indices[0]):
            if fid < 0 or fid not in _faiss_id_map:
                continue
            chunk_id = _faiss_id_map[fid]
            row = row_map.get(chunk_id)
            if row:
                items.append({
                    "id": row["id"],
                    "title": row["title"] or "",
                    "source": row["source"] or "",
                    "source_type": row["source_type"] or "",
                    "summary": row["summary"] or "",
                    "score": float(1.0 / (1.0 + dist)),
                })
                if len(items) >= max_results:
                    break

    if items:
        _search_cache[cache_key] = items

    return items


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
        # 使用独立 SQLite 连接（不复用 server 线程本地连接，避免并发冲突）
        standalone_conn = sqlite3.connect(str(DB_PATH), timeout=10)
        standalone_conn.row_factory = sqlite3.Row
        standalone_conn.execute("PRAGMA journal_mode=WAL")
        try:
            rows = standalone_conn.execute(
                "SELECT id, title, content FROM memory_tree_chunks"
            ).fetchall()
        finally:
            standalone_conn.close()

        if not rows:
            return {"status": "ok", "indexed": 0, "message": "没有需要索引的条目"}

        # 批量生成 embeddings
        import gc
        batch_size = 16
        total = 0

        # 重建 FAISS 索引
        n_vectors = len(rows)
        if n_vectors >= 1000:
            n_clusters = min(400, n_vectors // 4)
            logger.info("Creating IVF index with %d clusters for %d vectors", n_clusters, n_vectors)
            quantizer = faiss.IndexFlatL2(VECTOR_DIM)
            index = faiss.IndexIVFFlat(quantizer, VECTOR_DIM, n_clusters, faiss.METRIC_L2)
            index.nprobe = 10
            needs_train = True
        else:
            logger.info("Creating Flat index for %d vectors (<1000)", n_vectors)
            index = faiss.IndexIDMap(faiss.IndexFlatL2(VECTOR_DIM))
            needs_train = False

        vectors = []
        ids = []
        id_map = {}

        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            texts = [f"{r['title']}\n{r['content'][:8000]}" for r in batch]
            batch_vecs = _embed_texts(texts)
            batch_ids = [r['id'] for r in batch]

            for j, (vec, bid) in enumerate(zip(batch_vecs, batch_ids)):
                vectors.append(vec)
                ids.append(total + j)
                id_map[total + j] = bid

            total += len(batch)
            gc.collect()

        if vectors:
            vec_array = np.array(vectors).astype('float32')
            if needs_train:
                index.train(vec_array)
            index.add_with_ids(vec_array, np.array(ids, dtype=np.int64))

            # 保存索引
            faiss.write_index(index, str(FAISS_INDEX_PATH))

            # 保存向量和 faiss_id 到 SQLite（使用独立连接）
            standalone_conn2 = sqlite3.connect(str(DB_PATH), timeout=10)
            try:
                for fid, (vec, bid) in enumerate(zip(vectors, id_map.values())):
                    standalone_conn2.execute(
                        "UPDATE memory_tree_chunks SET vector = ?, faiss_id = ? WHERE id = ?",
                        (vec.tobytes(), ids[fid], bid),
                    )
                standalone_conn2.commit()
            finally:
                standalone_conn2.close()

            # 更新全局状态
            global _faiss_index, _faiss_id_map, _next_faiss_id
            _faiss_index = index
            _faiss_id_map = id_map
            _next_faiss_id = total

        _search_cache.clear()
        _embed_cache.clear()
        return {"status": "ok", "indexed": total}

    except Exception as e:
        logger.error("memory_tree_reindex failed: %s", e, exc_info=True)
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
        # 按空格分词，每个词独立 LIKE 匹配后取交集（AND）
        # 解决中文长句"研发支出费用化政策"无法匹配"研发"或"费用化"的问题
        terms = query.split()
        for term in terms:
            term = term.strip()
            if len(term) < 1:
                continue
            sql += " AND (condition LIKE ? OR rule LIKE ?)"
            params.extend([f"%{term}%", f"%{term}%"])

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
                # 根据错误类型映射到合适的偏好分类
                _error_to_pref_category = {
                    "field_selection": "field_alias",
                    "logic_error":     "policy",
                    "scope_error":     "date_rule",
                    "omission":        "policy",
                }
                pref_category = _error_to_pref_category.get(error_category, "policy")
                rule_hash = _sha256(f"prevent:{task_type}|{correction}")
                pref_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT OR IGNORE INTO preference_memory
                       (id, category, condition, rule, rule_hash, source_type, confidence, scope)
                       VALUES (?, ?, ?, ?, ?, 'extracted', 0.9, 'personal')""",
                    (pref_id, pref_category, f"任务类型={task_type}", correction, rule_hash),
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


@mcp.tool
def error_delete(id: str) -> dict:
    """
    删除一条错误记录。
    用于清理测试数据或已不再需要跟踪的错误。

    调用时机：
    - 清理测试错误
    - 错误已在代码层面修复，无需继续跟踪
    """
    with _get_conn() as conn:
        conn.execute("DELETE FROM error_memory WHERE id = ?", (id,))
        conn.commit()
    return {"status": "deleted", "id": id}


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
            existing_id = existing["id"]
            # 合并别名
            current = conn.execute(
                "SELECT aliases FROM entities WHERE id = ?", (existing_id,)
            ).fetchone()
            try:
                current_aliases = json.loads(current["aliases"]) if current and current["aliases"] else []
                new_aliases = json.loads(aliases) if isinstance(aliases, str) else aliases
                merged = list(set(current_aliases + new_aliases))
            except (json.JSONDecodeError, TypeError):
                merged = []

            conn.execute(
                "UPDATE entities SET aliases = ?, updated_at = ? WHERE id = ?",
                (json.dumps(merged, ensure_ascii=False), _now(), existing_id),
            )
            conn.commit()
            return {"status": "merged", "id": existing_id, "aliases": merged}

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
                (src_id, source_type or "document", source_name, scope),
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
                (tgt_id, target_type or "document", target_name, scope),
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

    # FAISS 索引统计
    try:
        index = _get_faiss_index()
        stats["faiss_indexed"] = index.ntotal if index else 0
        stats["embedding_model"] = EMBEDDING_MODEL
        stats["vector_dim"] = VECTOR_DIM
    except Exception as e:
        logger.warning("FAISS stats unavailable: %s", e)
        stats["faiss_indexed"] = "统计异常"
        stats["embedding_model"] = EMBEDDING_MODEL

    # 缓存统计
    stats["cache"] = {
        "search_cache_size": len(_search_cache),
        "search_cache_maxsize": _search_cache.maxsize,
        "ingest_cache_size": len(_ingest_cache),
        "ingest_cache_maxsize": _ingest_cache.maxsize,
    }

    return stats


@mcp.tool
def memory_health() -> dict:
    """
    健康检查 + 运行指标。

    返回数据库连接状态、FAISS 状态、请求量/延迟/错误率等。
    """
    result = health_check()
    result["metrics"] = metrics.snapshot()
    return result


# ---------------------------------------------------------------------------
# WAL checkpoint 后台线程（每 5 分钟截断 WAL，防止无限增长）
# ---------------------------------------------------------------------------

_WAL_CHECKPOINT_INTERVAL = 300  # 5 分钟


def _wal_checkpoint_loop() -> None:
    """后台循环，定期截断 WAL 文件 + 释放 Python 内存碎片。"""
    import time as _time
    import gc as _gc
    while True:
        _time.sleep(_WAL_CHECKPOINT_INTERVAL)
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=5)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
            _gc.collect()  # 释放 Python 内存碎片
            logger.debug("WAL checkpoint + GC completed")
        except Exception as exc:
            logger.warning("WAL checkpoint + GC failed: %s", exc)


# ---------------------------------------------------------------------------
# Entrypoint (SSE transport — 支持并发请求)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not _acquire_lock():
        print(f"[Memory Engine] 已有实例在运行 (PID 见 {PID_FILE})，退出。",
              file=sys.stderr)
        sys.exit(0)
    atexit.register(_release_lock)
    _init_db()
    # 4GB 方案：添加 vector 列（如果不存在）
    try:
        with _get_conn() as conn:
            conn.execute("ALTER TABLE memory_tree_chunks ADD COLUMN vector BLOB")
            conn.commit()
            logger.info("Schema migration: added vector column")
    except Exception:
        pass  # 列已存在，忽略
    # 启动 WAL checkpoint 后台线程
    _wal_thread = threading.Thread(target=_wal_checkpoint_loop, daemon=True)
    _wal_thread.start()
    logger.info("WAL checkpoint thread started (interval=%ds)", _WAL_CHECKPOINT_INTERVAL)
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8765)
