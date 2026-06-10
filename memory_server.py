#!/usr/bin/env python3
"""
Agent 记忆引擎 — MCP Server
四层记忆：Memory Tree + 偏好记忆 + 纠错记忆 + 知识图谱

通过 MCP 协议接入任何 Agent 框架（Hermes / Claude / 自定义）。
FastMCP 3.x, Python 3.10+, SQLite.

v2.2.0: 全面修复版（FAISS-DB 一致性、连接池死锁、API 密钥泄露等）
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

from cachetools import TTLCache

from fastmcp import FastMCP

from observability import health_check, metrics

logger = logging.getLogger("memory_engine")

# 参数校验
from validators import (
    ValidationError,
    validate_not_empty, validate_enum, validate_int_range, validate_scope, validate_safe_text, validate_length,
    ALLOWED_CATEGORIES, ALLOWED_SEVERITIES, ALLOWED_ERROR_CATEGORIES,
    ALLOWED_ENTITY_TYPES, ALLOWED_SCOPES, ALLOWED_SOURCE_TYPES, ALLOWED_RELATIONS,
)

# P3-3: 导出公共 API（避免意外导入内部函数）
__all__ = [
    # MCP 工具（23 个）
    "memory_tree_ingest",
    "memory_tree_search",
    "memory_tree_fetch",
    "memory_tree_delete",
    "memory_tree_score",
    "memory_tree_reindex",
    "memory_tree_summary",
    "memory_tree_vector_search",
    "memory_reindex_status",
    "memory_stats",
    "memory_health",
    "memory_search",
    "preference_add",
    "preference_search",
    "preference_list",
    "preference_disable",
    "error_check",
    "error_log",
    "error_list",
    "error_delete",
    "entity_add",
    "entity_search",
    "entity_link",
    "entity_graph_query",
    "sync_all_sources",
    "sync_feishu",
    "sync_local_files",
    # 内部函数（不导出，通过 __all__ 排除）
]

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
    """获取 PID 文件锁。返回 True 表示获取成功，False 表示已有实例运行中。
    
    P3-8 (ARCH-4): Docker/K8s 兼容改进：
    - 支持 DISABLE_PID_LOCK 环境变量禁用锁（容器场景）
    - 锁文件包含启动时间戳，避免 PID 复用误判
    - 增加进程名校验
    """
    # 容器场景：通过环境变量禁用 PID 锁
    if os.getenv("DISABLE_PID_LOCK", "").lower() in ("1", "true", "yes"):
        logger.info("PID lock disabled (DISABLE_PID_LOCK=1)")
        return True
    
    if PID_FILE.exists():
        try:
            lock_content = PID_FILE.read_text().strip().split()
            if len(lock_content) >= 2:
                old_pid = int(lock_content[0])
                old_start = float(lock_content[1])
            else:
                # 旧格式，只包含 PID
                old_pid = int(lock_content[0])
                old_start = 0
            
            # P3-11: 如果 PID 文件中的 PID 等于当前进程，直接覆盖（不误判自己）
            if old_pid == os.getpid():
                logger.debug("PID file contains our own PID, overwriting")
                import time
                PID_FILE.write_text(f"{os.getpid()} {time.time()}")
                return True
            
            # 检查进程是否存在
            try:
                os.kill(old_pid, 0)
            except ProcessLookupError:
                # 进程已死，锁过期，可以抢占
                pass
            else:
                # 进程还在运行
                # P3-8: 增加进程名校验（避免误判其他进程）
                try:
                    import psutil
                    proc = psutil.Process(old_pid)
                    if proc.name() not in ("python3", "python", "memory_server"):
                        logger.warning("PID %d exists but is not a Python process, ignoring", old_pid)
                    else:
                        # 检查启动时间是否匹配（避免 PID 复用）
                        try:
                            proc_start = proc.create_time()
                            if old_start > 0 and abs(proc_start - old_start) > 60:
                                logger.warning("PID %d reused by different process (start time mismatch)", old_pid)
                            else:
                                logger.info("Another memory_server instance running (PID %d)", old_pid)
                                return False
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                except ImportError:
                    # psutil 未安装，跳过进程名校验
                    logger.info("Another memory_server instance running (PID %d, psutil not available)", old_pid)
                    return False
        except (ValueError, OSError) as e:
            logger.debug("Corrupted lock file, ignoring: %s", e)

    # 写入当前 PID 和启动时间戳
    import time
    PID_FILE.write_text(f"{os.getpid()} {time.time()}")
    return True


def _release_lock() -> None:
    """释放 PID 文件锁。"""
    try:
        if PID_FILE.exists() and int(PID_FILE.read_text().strip()) == os.getpid():
            PID_FILE.unlink(missing_ok=True)
    except Exception:
        logger.debug("释放 PID 锁失败（可能已被其他进程清理）")


_faiss_index: faiss.Index | None = None
_faiss_id_map: dict[int, str] = {}  # FAISS idx → chunk_id
_next_faiss_id: int = 0
_embedding_model = None  # type: ignore  # lazy-loaded SentenceTransformer

# ---------------------------------------------------------------------------
# TTL 内存缓存层（替代 Redis，无需额外进程）
# ---------------------------------------------------------------------------
_search_cache = TTLCache(maxsize=5000, ttl=1800)   # 5 千条缓存，30 分钟过期（原 5 万条，内存优化）
_embed_cache = TTLCache(maxsize=500, ttl=3600)      # 嵌入缓存，500 条，1 小时过期（原 2000 条，内存优化）

# ---------------------------------------------------------------------------
# 生产级防护：FAISS 写锁 + 请求限流 + 日志
# ---------------------------------------------------------------------------
_faiss_write_lock = threading.RLock()         # FAISS 索引并发写入锁（可重入，支持回滚路径嵌套获取）
_request_semaphore = threading.BoundedSemaphore(50)  # 最大并发 50 请求
_concurrent_requests = 0
_reindex_lock = threading.Lock()              # P2-2: reindex 主逻辑锁（保护 FAISS 重建）
_reindex_status_lock = threading.Lock()       # P1-⑨ 修复: 独立的 reindex 状态锁，避免进度查询阻塞 reindex
_reindex_tasks: dict[str, dict] = {}          # P2-2: 异步 reindex 任务状态字典

import time as _time_module
import functools as _functools


def _log_request(func):
    """请求日志装饰器：记录调用、耗时、并发数。

    P2-10: 异常分类记录 - 区分业务验证错误、超时错误和系统错误。
    """
    @_functools.wraps(func)
    def wrapper(*args, **kwargs):
        global _concurrent_requests
        _concurrent_requests += 1
        t0 = _time_module.monotonic()
        try:
            return func(*args, **kwargs)
        except ValidationError as e:
            # P2-10: 业务验证错误，记录为 warning（非系统错误）
            logger.warning("Validation error in %s: %s", func.__name__, e)
            raise
        except TimeoutError as e:
            # P2-10: 超时错误，记录为 error
            logger.error("Timeout in %s: %s", func.__name__, e)
            raise
        except Exception:
            # P2-10: 未预期错误，记录为 exception（包含完整 traceback）
            logger.exception("Unexpected error in %s", func.__name__)
            raise
        finally:
            _concurrent_requests -= 1
            elapsed = (_time_module.monotonic() - t0) * 1000
            if elapsed > 1000:  # 超过 1 秒才打 WARNING
                logger.warning(
                    "Slow request: %s took %.0fms (concurrent=%d)",
                    func.__name__, elapsed, _concurrent_requests,
                )
    return wrapper


def _rate_limit():
    """请求限流入口。阻塞直到有可用槽位，超时 30 秒抛异常。"""
    acquired = _request_semaphore.acquire(timeout=30)
    if not acquired:
        raise RuntimeError("服务繁忙，请求被限流（并发 > 50）")
    # 调用方负责在 finally 中 release()


mcp = FastMCP(MCP_SERVER_NAME)

# ---------------------------------------------------------------------------
# SQLite 连接池（线程本地 + 性能优化）
# ---------------------------------------------------------------------------
# SQLite 连接池（P0-2: 使用 threading.Condition 实现真正的阻塞等待，避免死锁）
# ---------------------------------------------------------------------------
class _ConnectionPool:
    """SQLite 连接池，限制最大连接数，自动回收闲置连接。

    P0-3 修复:
    - 健康检查移到锁外，避免在锁内执行 SQL 导致死锁
    - 连接关闭后正确递减 _created 并 notify 等待者
    - 使用线程安全的连接验证机制
    - 添加 _closed 标志支持优雅关闭
    """

    def __init__(self, db_path: str, max_size: int = 10):
        self._db_path = db_path
        self._max_size = max_size
        self._pool: list[sqlite3.Connection] = []
        self._cond = threading.Condition()
        self._created = 0
        self._closed = False

    def get_conn(self, timeout: float = 10.0) -> sqlite3.Connection:
        """从池中获取连接，或创建新连接（不超过 max_size）。"""
        import time as _time
        end_time = _time.monotonic() + timeout

        with self._cond:
            while True:
                if self._closed:
                    raise RuntimeError("Connection pool is closed")

                # 优先从池中获取闲置连接
                while self._pool:
                    conn = self._pool.pop()
                    # P0-3 修复: 健康检查移到锁外
                    if self._is_connection_valid(conn):
                        return conn
                    else:
                        # 连接已失效，关闭并继续检查池中其他连接
                        try:
                            conn.close()
                        except Exception:
                            pass
                        self._created -= 1  # P0-3 修复: 正确递减

                # 池为空，尝试创建新连接
                if self._created < self._max_size:
                    try:
                        conn = self._create_conn()
                        self._created += 1
                        return conn
                    except Exception:
                        # 创建失败，decrement 并继续等待
                        self._created -= 1
                        raise

                # 达到最大连接数，等待可用连接
                remaining = end_time - _time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(
                        f"SQLite 连接池已满（max={self._max_size}），获取连接超时"
                    )
                # P0-3 修复: 使用 Condition.wait 实现真正的阻塞等待
                self._cond.wait(timeout=remaining)

    def _is_connection_valid(self, conn: sqlite3.Connection) -> bool:
        """P0-3 修复: 在锁外验证连接有效性。"""
        try:
            conn.execute("SELECT 1")
            return True
        except sqlite3.OperationalError:
            return False

    def return_conn(self, conn: sqlite3.Connection):
        """归还连接到池中。"""
        with self._cond:
            if self._closed:
                try:
                    conn.close()
                except Exception:
                    pass
                return
            if len(self._pool) < self._max_size:
                # P0-3 修复: 归还前快速验证连接是否可用
                if self._is_connection_valid(conn):
                    self._pool.append(conn)
                    self._cond.notify()  # P0-3 修复: 通知等待的线程
                else:
                    conn.close()
                    self._created -= 1
                    self._cond.notify()
            else:
                conn.close()
                self._created -= 1

    def _create_conn(self) -> sqlite3.Connection:
        """创建新连接并应用优化配置。"""
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-128000")  # 128MB
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=134217728")  # 128MB
        conn.execute("PRAGMA busy_timeout=10000")   # 10s
        conn.execute("PRAGMA page_size=4096")       # 4KB 页
        return conn

    def close_all(self):
        """关闭所有连接（用于优雅关闭）。"""
        with self._cond:
            self._closed = True
            for conn in self._pool:
                try:
                    conn.close()
                except Exception:
                    pass
            self._pool.clear()
            self._created = 0
            self._cond.notify_all()  # P0-3 修复: 唤醒所有等待者，使其看到 _closed=True


# 全局连接池实例
_conn_pool = _ConnectionPool(str(DB_PATH), max_size=10)


def _get_conn():
    """获取 SQLite 连接（从连接池）。使用 contextmanager 确保自动归还。"""
    from contextlib import contextmanager
    
    @contextmanager
    def conn_context():
        conn = _conn_pool.get_conn()
        try:
            yield conn
        finally:
            _conn_pool.return_conn(conn)
    
    return conn_context()


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


def _get_embedding_model():
    """Lazy-load the SentenceTransformer embedding model.

    all-MiniLM-L6-v2 (384-dim, ~80MB). No GPU required.
    Uses local_files_only=True to avoid HF network timeouts in offline envs.
    Deferred import avoids loading torch (~2GB) until first embedding call.
    """
    from sentence_transformers import SentenceTransformer
    global _embedding_model
    if _embedding_model is None:
        logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL, local_files_only=True)
    return _embedding_model


VECTOR_DIM = 384  # all-MiniLM-L6-v2 维度
# FAISS_INDEX_PATH 已从 config 导入


def _get_faiss_index() -> faiss.Index:
    """Lazy-load FAISS index from disk.
    IVF400 with L2 distance. Supports ~500 万 vectors in 4GB RAM.
    使用数据库中存储的 faiss_id 字段重建 id_map，而非靠 ROWID 顺序推断。

    P0-3 修复: 使用 RLock + 局部变量模式确保初始化原子性。
    P1-7 修复: 使用局部变量完成初始化后再赋值给全局变量，避免部分初始化可见。
    """
    global _faiss_index, _faiss_id_map, _next_faiss_id

    # 快速检查（无锁）— 常见路径，避免锁开销
    if _faiss_index is not None:
        return _faiss_index

    # 使用 RLock（可重入），支持回滚路径中嵌套获取锁
    with _faiss_write_lock:
        # 双重检查（防止另一个线程在锁等待期间已完成初始化）
        if _faiss_index is not None:
            return _faiss_index

        # 使用局部变量完成整个初始化过程，最后再赋值给全局变量
        # 这确保了其他线程要么看到完全初始化的对象，要么看到 None
        local_index = None
        local_id_map = {}
        local_next_id = 0

        if FAISS_INDEX_PATH.exists():
            logger.info("Loading FAISS index from %s", FAISS_INDEX_PATH)
            local_index = faiss.read_index(str(FAISS_INDEX_PATH))

            # 用数据库中的 faiss_id 字段重建 id_map（精确，不依赖 ROWID 顺序）
            with _get_conn() as conn:
                rows = conn.execute(
                    "SELECT id, faiss_id FROM memory_tree_chunks "
                    "WHERE faiss_id >= 0 ORDER BY faiss_id"
                ).fetchall()
                for row in rows:
                    fid = row["faiss_id"]
                    local_id_map[fid] = row["id"]
                    if fid >= local_next_id:
                        local_next_id = fid + 1

            logger.info("FAISS index loaded: %d vectors", len(local_id_map))
        else:
            logger.info("Creating new FAISS index (Flat, L2)")
            local_index = faiss.IndexIDMap(faiss.IndexFlatL2(VECTOR_DIM))
            logger.info("Created new FAISS index: 0 vectors")

        # 原子赋值：所有线程要么看到旧值（None），要么看到完整的新值
        _faiss_index = local_index
        _faiss_id_map = local_id_map
        _next_faiss_id = local_next_id

    return _faiss_index


def _embed_text(text: str) -> np.ndarray:
    """Embed a single text to 384-dim vector（带 LRU 缓存，高频重复查询复用向量）。

    P1-⑦ 修复: 使用 ThreadPoolExecutor 替代 threading.Thread，
    超时后自动清理线程，避免资源泄漏。
    """
    cached = _embed_cache.get(text)
    if cached is not None:
        return cached

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

    model = _get_embedding_model()

    def _do_encode():
        return model.encode([text])[0].astype('float32')

    # P1-⑦ 修复: 使用 ThreadPoolExecutor 管理线程生命周期
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_do_encode)
        try:
            result = future.result(timeout=30)
        except FuturesTimeoutError:
            future.cancel()
            raise TimeoutError(f"Embedding timeout after 30s for text length {len(text)}")
        except Exception as e:
            future.cancel()
            raise

    _embed_cache[text] = result
    return result


def _embed_texts(texts: list[str]) -> np.ndarray:
    """Embed multiple texts in batch.

    P1-⑦ 修复: 使用 ThreadPoolExecutor 替代 threading.Thread，
    超时后自动清理线程，避免资源泄漏。
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

    model = _get_embedding_model()

    def _do_encode():
        return model.encode(texts).astype('float32')

    # P1-⑦ 修复: 使用 ThreadPoolExecutor 管理线程生命周期
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_do_encode)
        try:
            result = future.result(timeout=60)
        except FuturesTimeoutError:
            future.cancel()
            raise TimeoutError(f"Batch embedding timeout after 60s for {len(texts)} texts")
        except Exception as e:
            future.cancel()
            raise

    return result


from utils import now as _now, sha256 as _sha256


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """P2-1: 添加完整类型注解。
    P3-7/BUG-3: 排除 BLOB 字段（vector），避免 Pydantic JSON 序列化失败。
    """
    if row is None:
        return None
    d = dict(row)
    # 排除二进制向量字段，Pydantic 无法序列化 bytes 为 JSON
    d.pop("vector", None)
    return d


def _rows_to_list(rows: list[sqlite3.Row]) -> list[dict]:
    """P2-1: 添加完整类型注解。
    与 _row_to_dict 一致，排除 BLOB 字段（vector）避免 Pydantic 序列化失败。
    """
    result = []
    for r in rows:
        d = dict(r)
        d.pop("vector", None)
        result.append(d)
    return result


def _escape_like(term: str) -> str:
    """转义 LIKE 通配符，防止 LIKE wildcard injection（P1-4/SEC-1）。
    
    SQLite LIKE 中 % 和 _ 是通配符，需要转义才能匹配字面字符。
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _save_faiss_index_safe(index: faiss.Index, path: Path) -> None:
    """原子写入 FAISS 索引（P2-1/PERF-1）。
    
    先写临时文件再 rename，避免：
    1. 写一半时崩溃损坏索引
    2. 并发读取时读到不完整索引
    """
    import tempfile
    
    tmp_path = path.with_suffix(".tmp")
    faiss.write_index(index, str(tmp_path))
    # atomic rename（同磁盘分区内保证原子性）
    tmp_path.replace(path)


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
    validate_safe_text(content, "content")
    # P1-3 (SEC-2): 限制输入长度，防止 DoS 攻击
    from config import MAX_CONTENT_LENGTH
    content = validate_length(content, "content", max_len=MAX_CONTENT_LENGTH)
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
    # P3-① 修复: generate_summary 实际是预览截断，非 LLM 摘要
    summary = None
    if generate_summary and content:
        summary = content[:200] + "..." if len(content) > 200 else content

    # P3-7 (ARCH-3): 改进 entity_count 估算（基于启发式规则，非硬编码关键词）
    # 简单启发式：按段落数、列表项数、标题数估算实体密度
    paragraphs = content.count("\n\n") + 1
    list_items = content.count("- ") + content.count("* ") + content.count("1. ")
    entity_count = min(paragraphs + list_items // 2, 100)  # 上限 100

    # ── P0-2: 先 FAISS 后数据库（消除竞态条件）─────────────────
    # 步骤 1: 生成向量并写入 FAISS（失败则直接返回，不污染数据库）
    doc_text = f"{title}\n{content[:8000]}"
    try:
        vector = _embed_text(doc_text)
    except Exception as e:
        logger.error("Embedding failed for %s: %s", chunk_id, e)
        return {
            "status": "error",
            "message": f"嵌入模型失败: {e}",
            "id": chunk_id,
            "hash": content_hash,
        }

    # 获取 faiss_id（在写入前分配，保证原子性）
    with _faiss_write_lock:
        index = _get_faiss_index()

        if hasattr(index, "is_trained") and not index.is_trained:
            logger.info("Index not trained, upgrading to Flat index")
            index = faiss.IndexIDMap(faiss.IndexFlatL2(VECTOR_DIM))
            _faiss_index = index

        fid = _next_faiss_id
        index.add_with_ids(
            vector.reshape(1, -1),
            np.array([fid], dtype=np.int64),
        )
        _faiss_id_map[fid] = chunk_id
        _next_faiss_id = fid + 1

        # P2-1 (PERF-1): 原子写入 FAISS 索引（先写临时文件再 rename）
        _save_faiss_index_safe(index, FAISS_INDEX_PATH)

    # P0-2 修复: 先以 is_indexed=0 插入数据库，成功后再更新为 is_indexed=1
    # 这样即使 DB 写入失败，FAISS 索引也不会产生孤立的向量
    faiss_ok = False
    try:
        # 步骤 2: 以 is_indexed=0 插入数据库（标记为"待确认"）
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO memory_tree_chunks
                   (id, source, source_type, title, content, content_hash,
                    parent_id, summary, score, entity_count, metadata, faiss_id, is_indexed, vector)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?, ?, 0, ?)""",
                (
                    chunk_id, source, source_type, title, content, content_hash,
                    parent_id or None, summary, entity_count, metadata, fid, vector.tobytes(),
                ),
            )
            conn.commit()

        # 步骤 3: DB 写入成功后，更新 is_indexed=1（确认索引有效）
        with _get_conn() as conn:
            conn.execute(
                "UPDATE memory_tree_chunks SET is_indexed = 1 WHERE id = ?",
                (chunk_id,),
            )
            conn.commit()

        faiss_ok = True
    except Exception as e:
        logger.error("Database write failed for %s: %s, rolling back FAISS", chunk_id, e)
        # P0-2 修复: 回滚 FAISS 索引（移除刚添加的向量）
        try:
            with _faiss_write_lock:
                index = _get_faiss_index()
                if hasattr(index, "remove_ids"):
                    index.remove_ids(np.array([fid], dtype=np.int64))
                    _faiss_id_map.pop(fid, None)
                    _save_faiss_index_safe(index, FAISS_INDEX_PATH)
                logger.info("FAISS rollback completed for chunk %s", chunk_id)
        except Exception as rollback_err:
            logger.error("FAISS rollback failed: %s", rollback_err)
        raise

    # 清空搜索缓存
    _search_cache.clear()

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
    # P2-2: 限制 max_results 范围，防止异常值
    max_results = max(1, min(max_results, 100))
    
    sql = """SELECT id, source, source_type, title, summary, score, entity_count, created_at
             FROM memory_tree_chunks WHERE 1=1"""
    params: list = []

    if source_type:
        sql += " AND source_type = ?"
        params.append(source_type)

    # 全文搜索：按词分词匹配，不做整句连续匹配
    # P2-⑤ 修复: 改进中文分词策略
    if query:
        import re as _re
        raw_terms = _re.split(r'[\s,，.。;；!！?？]+', query)
        terms = []
        for term in raw_terms:
            term = term.strip()
            if len(term) < 2:
                continue  # P2-6: 跳过单字（中文单字搜索建议用 vector_search）
            # 对长中文词拆分为 n-gram，提高匹配率
            if len(term) >= 4 and not _re.search(r'[a-zA-Z0-9]', term):
                for i in range(len(term)):
                    for size in [2, 3]:
                        if i + size <= len(term):
                            ngram = term[i:i+size]
                            if ngram not in terms and len(ngram) >= 2:
                                terms.append(ngram)
            else:
                terms.append(term)

        for term in terms:
            sql += " AND (title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\')"
            like = f"%{_escape_like(term)}%"
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
    # P1-⑫ 修复: 添加输入验证
    validate_not_empty(id, "id")

    with _get_conn() as conn:
        conn.execute(
            "UPDATE memory_tree_chunks SET retrieval_count = retrieval_count + 1 WHERE id = ?",
            (id,),
        )
        row = conn.execute("SELECT * FROM memory_tree_chunks WHERE id = ?", (id,)).fetchone()
        conn.commit()
    return _row_to_dict(row)


@mcp.tool
def memory_tree_delete(id: str) -> dict:
    """
    从 Memory Tree 中删除一条记录（同时清理 FAISS 索引）。
    
    调用时机：
    - 需要清理错误写入的内容时
    - 需要删除过期/无效的记忆时
    
    注意：删除后无法恢复，请谨慎操作。
    """
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, faiss_id FROM memory_tree_chunks WHERE id = ?", (id,)
        ).fetchone()
        
        if not row:
            return {"status": "not_found", "message": f"记录 '{id}' 不存在"}
        
        faiss_id = row["faiss_id"]
        
        # 从数据库删除
        conn.execute("DELETE FROM memory_tree_chunks WHERE id = ?", (id,))
        # P0-1: 删除后清空搜索缓存，确保一致性
    
    # 从 FAISS 索引中删除（如果存在）
    # P1-3: 整个 FAISS 删除操作在 _faiss_write_lock 保护下，避免并发竞态
    if faiss_id and faiss_id >= 0:
        try:
            with _faiss_write_lock:
                index = _get_faiss_index()
                # FAISS IndexIDMap 支持 remove_ids
                if hasattr(index, "remove_ids"):
                    index.remove_ids(np.array([faiss_id], dtype=np.int64))
                    # 更新全局映射
                    global _faiss_id_map
                    _faiss_id_map.pop(faiss_id, None)
                    # 原子写入索引
                    _save_faiss_index_safe(index, FAISS_INDEX_PATH)
        except Exception as e:
            logger.warning("FAISS cleanup failed for id=%s: %s", id, e)
    
    # 清空搜索缓存
    _search_cache.clear()
    
    return {"status": "deleted", "id": id, "faiss_id": faiss_id}


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
            "UPDATE memory_tree_chunks SET score = MAX(0, MIN(10, score + ?)), "
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
    # P1-4 修复: 缓存键包含 max_results（防止不同 max_results 返回错误结果）
    # P1-④ 修复: 对 query 做哈希避免超长键，source_type 空字符串统一处理
    import hashlib as _hashlib
    query_hash = _hashlib.md5(query.encode("utf-8")).hexdigest()[:8]
    source_key = source_type.strip() if source_type else "default"
    cache_key = f"vs:{query_hash}:{source_key}:n{max_results}"
    cached_result = _search_cache.get(cache_key)
    if cached_result is not None:
        # P1-4: 确保返回数量不超过 max_results（缓存命中时可能返回更多）
        return cached_result[:max_results]

    index = _get_faiss_index()
    if index.ntotal == 0:
        return []

    query_vector = _embed_text(query)
    distances, indices = index.search(
        query_vector.reshape(1, -1).astype('float32'),
        min(max_results * 2, index.ntotal)
    )

    items: list[dict] = []
    # 批量获取所有候选 chunk_id
    candidate_ids = [_faiss_id_map[fid] for fid in indices[0] 
                     if fid >= 0 and fid in _faiss_id_map]
    
    with _get_conn() as conn:
        if not candidate_ids:
            return []
        
        # 批量查询，避免循环内单条查询
        # P0-1: 只返回 is_indexed=1 的记录，确保 FAISS-DB 一致性
        placeholders = ','.join('?' * len(candidate_ids))
        rows = conn.execute(
            f"SELECT id, source, source_type, title, summary, score "
            f"FROM memory_tree_chunks WHERE id IN ({placeholders}) AND is_indexed = 1",
            candidate_ids
        ).fetchall()
        
        # 构建 id 到 row 的映射
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
        # P1-4: 确保返回数量不超过 max_results（缓存命中时可能返回更多）
        return items[:max_results]

    return items


@mcp.tool
def memory_tree_reindex(async_mode: bool = False) -> dict:
    """
    重建所有现有 Memory Tree 条目的向量索引。
    在新安装 embedding 模型后、或更换模型后使用。

    P3-6 (PERF-2): 支持 async_mode 参数，异步执行不阻塞服务。

    调用时机：
    - 首次部署后
    - 切换 embedding 模型后
    - 向量索引损坏时

    Args:
        async_mode: 如果 True，后台异步执行，返回 task_id 供查询进度
    """
    if async_mode:
        import uuid
        task_id = str(uuid.uuid4())[:8]

        with _reindex_lock:
            _reindex_tasks[task_id] = {
                "status": "running",
                "progress": 0,
                "total": 0,
                "result": None,
                "error": None,
            }

        def _do_reindex():
            try:
                # P2-2 修复: 传递 task_id 以便更新进度
                result = _do_reindex_sync(task_id=task_id)
                with _reindex_status_lock:
                    if task_id in _reindex_tasks:
                        _reindex_tasks[task_id]["status"] = "completed"
                        _reindex_tasks[task_id]["result"] = result
                        # P3-11: 任务完成后清理，避免内存泄漏
                        del _reindex_tasks[task_id]
            except Exception as e:
                with _reindex_status_lock:
                    if task_id in _reindex_tasks:
                        _reindex_tasks[task_id]["status"] = "failed"
                        _reindex_tasks[task_id]["error"] = str(e)
                        # P3-11: 任务失败后也清理
                        del _reindex_tasks[task_id]

        threading.Thread(target=_do_reindex, daemon=True).start()
        return {"status": "started", "task_id": task_id, "message": "后台任务已启动"}

    return _do_reindex_sync()


def _do_reindex_sync(task_id: str | None = None) -> dict:
    """同步执行 reindex（内部函数）。

    Args:
        task_id: 异步任务 ID，用于更新进度（P2-2 修复）
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
        total_rows = len(rows)

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

            # P2-2 修复: 更新异步任务进度
            # P1-⑨ 修复: 使用独立的 _reindex_status_lock，避免阻塞 memory_reindex_status 查询
            if task_id:
                with _reindex_status_lock:
                    if task_id in _reindex_tasks:
                        _reindex_tasks[task_id]["progress"] = total
                        _reindex_tasks[task_id]["total"] = total_rows

            # P2-5: 进度反馈（每 100 条或最后 1 条打印一次）
            if total % 100 == 0 or total >= len(rows):
                pct = 100 * total / len(rows) if len(rows) > 0 else 100
                logger.info("Reindex progress: %d/%d (%.1f%%), batch=%d-%d",
                           total, len(rows), pct, i + 1, min(i + batch_size, len(rows)))

            gc.collect()

        if vectors:
            vec_array = np.array(vectors).astype('float32')
            if needs_train:
                index.train(vec_array)

            with _faiss_write_lock:
                index.add_with_ids(vec_array, np.array(ids, dtype=np.int64))
                _save_faiss_index_safe(index, FAISS_INDEX_PATH)

            # 保存向量和 faiss_id 到 SQLite（使用独立连接）
            # P0-1: 同时设置 is_indexed=1，确保搜索一致性
            standalone_conn2 = sqlite3.connect(str(DB_PATH), timeout=10)
            try:
                for fid, (vec, bid) in enumerate(zip(vectors, id_map.values())):
                    standalone_conn2.execute(
                        "UPDATE memory_tree_chunks SET vector = ?, faiss_id = ?, is_indexed = 1 WHERE id = ?",
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
        # P1-2 (BUG-1): 修复 exc_info 参数错误
        logger.error("memory_tree_reindex failed: %s", e, exc_info=True)
        return {"status": "error", "message": str(e)}


@mcp.tool
def memory_reindex_status(task_id: str) -> dict:
    """
    查询后台 reindex 任务的进度（P3-6/PERF-2）。
    
    Args:
        task_id: 由 memory_tree_reindex(async_mode=True) 返回的任务 ID
        
    Returns:
        {
            "status": "running" | "completed" | "failed",
            "progress": int,
            "total": int,
            "result": dict | None,
            "error": str | None,
        }
    """
    with _reindex_status_lock:
        task = _reindex_tasks.get(task_id)
        if not task:
            return {"status": "not_found", "message": f"任务 '{task_id}' 不存在"}
        return {
            "status": task["status"],
            "progress": task["progress"],
            "total": task["total"],
            "result": task["result"],
            "error": task["error"],
        }


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
        # P2-⑤ 修复: 改进分词策略，支持中文自然语言查询
        # 1. 先按空格/标点分词
        # 2. 对长词（>=4 字符）进一步拆分为 2-3 字符的 n-gram，提高中文匹配率
        import re as _re
        raw_terms = _re.split(r'[\s,，.。;；!！?？]+', query)
        terms = []
        for term in raw_terms:
            term = term.strip()
            if len(term) < 1:
                continue
            # 对长中文词拆分为 n-gram（如 "研发支出费用化" → "研发", "支出", "费用", "化"）
            if len(term) >= 4 and not _re.search(r'[a-zA-Z0-9]', term):
                # 纯中文长词，拆分为 2-3 字符的片段
                for i in range(len(term)):
                    for size in [2, 3]:
                        if i + size <= len(term):
                            ngram = term[i:i+size]
                            if ngram not in terms and len(ngram) >= 2:
                                terms.append(ngram)
            else:
                terms.append(term)

        for term in terms:
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
            # P2-4: occurrence_count >= 3 自动升级为 major
            conn.execute(
                """UPDATE error_memory
                   SET occurrence_count = ?, last_occurrence = ?, updated_at = ?,
                       severity = CASE WHEN ? >= 3 THEN 'major' ELSE severity END
                   WHERE id = ?""",
                (new_count, _now(), _now(), new_count, existing["id"]),
            )

            # 如果累计 3 次以上，自动升级为偏好记忆
            # P1-5: 规范化 correction 文本（去除多余空格、统一标点），避免微小差异导致重复规则
            # P0-⑧ 修复: 使用 INSERT OR IGNORE + 二次检查避免并发竞态
            if new_count >= 3:
                # 根据错误类型映射到合适的偏好分类
                _error_to_pref_category = {
                    "field_selection": "field_alias",
                    "logic_error":     "policy",
                    "scope_error":     "date_rule",
                    "omission":        "policy",
                }
                pref_category = _error_to_pref_category.get(error_category, "policy")
                # P1-5: 规范化 correction：去除首尾空格、压缩连续空格、统一标点
                norm_correction = " ".join(correction.strip().split())
                rule_hash = _sha256(f"prevent:{task_type}|{norm_correction}")

                # P0-⑧ 修复: 先检查是否已存在（包括其他并发请求刚创建的）
                existing_pref = conn.execute(
                    "SELECT id FROM preference_memory WHERE rule_hash = ?", (rule_hash,)
                ).fetchone()

                if existing_pref:
                    # 另一个并发请求已创建，关联到已有偏好
                    conn.execute(
                        "UPDATE error_memory SET is_resolved = 1, resolved_to = ? WHERE id = ?",
                        (existing_pref["id"], existing["id"]),
                    )
                    resolved_pref_id = existing_pref["id"]
                else:
                    # 尝试创建新偏好，使用 INSERT OR IGNORE 避免竞态重复
                    pref_id = str(uuid.uuid4())
                    conn.execute(
                        """INSERT OR IGNORE INTO preference_memory
                           (id, category, condition, rule, rule_hash, source_type, confidence, scope)
                           VALUES (?, ?, ?, ?, ?, 'extracted', 0.9, 'personal')""",
                        (pref_id, pref_category, f"任务类型={task_type}", norm_correction, rule_hash),
                    )
                    # 检查是否插入成功（另一个并发请求可能已插入相同 rule_hash）
                    pref_row = conn.execute(
                        "SELECT id FROM preference_memory WHERE rule_hash = ?", (rule_hash,)
                    ).fetchone()

                    if pref_row:
                        resolved_pref_id = pref_row["id"]
                        # 如果是我们插入的，关联 error 到 preference
                        conn.execute(
                            "UPDATE error_memory SET is_resolved = 1, resolved_to = ? WHERE id = ?",
                            (resolved_pref_id, existing["id"]),
                        )
                    else:
                        # 另一个并发请求插入了，获取其 ID 并关联
                        resolved_pref_id = pref_row["id"] if pref_row else None
                        if resolved_pref_id:
                            conn.execute(
                                "UPDATE error_memory SET is_resolved = 1, resolved_to = ? WHERE id = ?",
                                (resolved_pref_id, existing["id"]),
                            )
                        else:
                            # 极端情况：两次插入都失败，标记为已解决但不关联
                            conn.execute(
                                "UPDATE error_memory SET is_resolved = 1 WHERE id = ?",
                                (existing["id"],),
                            )
                            logger.warning("error_log: race condition on preference creation for rule_hash=%s", rule_hash)

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

    # P1-1: 严格校验 JSON 参数
    try:
        aliases_list = json.loads(aliases)
        if not isinstance(aliases_list, list):
            raise ValidationError("aliases 必须是 JSON 数组，如 '[]' 或 '[""alias1"", ""alias2""]'")
    except json.JSONDecodeError as e:
        raise ValidationError(f"aliases 不是有效的 JSON: {e}")

    try:
        props_dict = json.loads(properties)
        if not isinstance(props_dict, dict):
            raise ValidationError("properties 必须是 JSON 对象，如 '{}' 或 '{""key"": ""value""}'")
    except json.JSONDecodeError as e:
        raise ValidationError(f"properties 不是有效的 JSON: {e}")

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
            # P1-2: 改进 JSON 损坏时的处理策略
            # 如果现有别名 JSON 损坏，记录严重警告并保守处理：保留现有数据，仅添加新别名
            try:
                current_aliases = json.loads(current["aliases"]) if current and current["aliases"] else []
                if not isinstance(current_aliases, list):
                    raise ValueError("existing aliases is not a list")
                merged = list(set(current_aliases + aliases_list))
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.error(
                    "现有别名 JSON 损坏，需要手动修复: id=%s, current_aliases=%s, error=%s",
                    existing_id, current["aliases"] if current else None, e
                )
                # 保守策略：保留现有数据（不删除），仅添加新别名
                merged = aliases_list

            conn.execute(
                "UPDATE entities SET aliases = ?, updated_at = ? WHERE id = ?",
                (json.dumps(merged, ensure_ascii=False), _now(), existing_id),
            )
            conn.commit()
            return {"status": "merged", "id": existing_id, "aliases": merged}

        # 使用校验后的 JSON 对象存储（确保格式正确）
        conn.execute(
            """INSERT INTO entities (id, type, name, aliases, properties, scope, department)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (entity_id, type, name, json.dumps(aliases_list, ensure_ascii=False), 
             json.dumps(props_dict, ensure_ascii=False), scope, department or None),
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

        # P1-⑬ 修复: 自动创建实体前校验 type，非法类型使用默认值
        src_type = source_type or "document"
        if src_type and src_type not in ALLOWED_ENTITY_TYPES:
            logger.warning("entity_link: invalid source_type '%s', using 'document' instead", src_type)
            src_type = "document"

        if not src:
            src_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO entities (id, type, name, scope) VALUES (?, ?, ?, ?)",
                (src_id, src_type, source_name, scope),
            )
        else:
            src_id = src[0]

        # 查找或创建 target 实体
        tgt_type = target_type or "document"
        if tgt_type and tgt_type not in ALLOWED_ENTITY_TYPES:
            logger.warning("entity_link: invalid target_type '%s', using 'document' instead", tgt_type)
            tgt_type = "document"

        tgt = conn.execute(
            "SELECT id FROM entities WHERE name = ?" + (f" AND type = ?" if target_type else ""),
            (target_name,) + ((tgt_type,) if target_type else ()),
        ).fetchone()

        if not tgt:
            tgt_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO entities (id, type, name, scope) VALUES (?, ?, ?, ?)",
                (tgt_id, tgt_type, target_name, scope),
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
        # P1-⑪ 修复: 使用 JSON 函数搜索 aliases 数组，替代脆弱的 LIKE 匹配
        entity = conn.execute(
            """SELECT * FROM entities
               WHERE name = ?
                  OR EXISTS (
                      SELECT 1 FROM json_each(aliases) WHERE json_each.value = ?
                  )""",
            (entity_name, entity_name),
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
@_log_request
def memory_search(query: str, layers: str = "all", max_results: int = 20, timeout: float = 30.0) -> dict:
    """
    跨四层综合检索。
    输入用户的自然语言问题，返回所有相关记忆。

    这是最主要的检索入口。Agent 在执行任何涉及企业数据的任务前，
    应该先调用此工具获取上下文。

    layers 可选值：all | memory_tree | preferences | errors | graph
    timeout: 单层最大等待秒数（默认 30 秒）
    注意：各层内部函数有自己的超时保护（embedding 30s/60s）

    调用时机（每次对话开始时建议调用）：
    - 用户提到具体的客户名、项目名、部门名
    - 任务涉及财务数据、分析、报告
    - 需要了解企业政策或制度时
    """
    import concurrent.futures

    results: dict[str, list] = {}

    def _safe_call(fn, *args, **kw):
        try:
            return fn(*args, **kw)
        except Exception as e:
            logger.warning("memory_search layer %s failed: %s", fn.__name__, e)
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        if layers in ("all", "memory_tree"):
            futures["memory_tree"] = executor.submit(
                memory_tree_vector_search, query, max_results=max_results // 2
            )
        if layers in ("all", "preferences"):
            futures["preferences"] = executor.submit(
                preference_search, query, max_results=max_results // 2
            )
        if layers in ("all", "errors"):
            futures["errors"] = executor.submit(
                error_check, task_description=query, max_results=max_results // 2
            )
        if layers in ("all", "graph"):
            futures["graph"] = executor.submit(
                entity_search, query, max_results=max_results // 2
            )

        for key, future in futures.items():
            try:
                results[key] = future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                logger.warning("memory_search layer %s timed out after %.0fs", key, timeout)
                results[key] = []
            except Exception as e:
                logger.warning("memory_search layer %s failed: %s", key, e)
                results[key] = []

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
    # P1-⑭ 修复: 统一返回 int 类型，异常时返回 -1（而非字符串）
    try:
        index = _get_faiss_index()
        stats["faiss_indexed"] = int(index.ntotal) if index else 0
        stats["embedding_model"] = EMBEDDING_MODEL
        stats["vector_dim"] = VECTOR_DIM
    except Exception as e:
        logger.warning("FAISS stats unavailable: %s", e)
        stats["faiss_indexed"] = -1  # 统一为 int，-1 表示统计不可用
        stats["embedding_model"] = EMBEDDING_MODEL

    # 缓存统计
    stats["cache"] = {
        "search_cache_size": len(_search_cache),
        "search_cache_maxsize": _search_cache.maxsize,
        "embed_cache_size": len(_embed_cache),
        "embed_cache_maxsize": _embed_cache.maxsize,
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
# 优雅关闭信号处理（P3-4 修复）
# ---------------------------------------------------------------------------
_shutdown_event = threading.Event()


def _signal_handler(signum, frame):
    """处理 SIGTERM/SIGINT 信号，触发优雅关闭。"""
    sig_name = "SIGTERM" if signum == 15 else "SIGINT"
    logger.info("收到 %s 信号，开始优雅关闭...", sig_name)
    _shutdown_event.set()


# ---------------------------------------------------------------------------
# Entrypoint (SSE transport — 支持并发请求)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # P3-4: 注册信号处理器
    import signal
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # 1. 单实例锁
    if not _acquire_lock():
        print(f"[Memory Engine] 已有实例在运行 (PID 见 {PID_FILE})，退出。",
              file=sys.stderr)
        sys.exit(1)
    atexit.register(_release_lock)

    # 2. 配置校验（在 _init_db 之前，避免数据库创建后才发现配置错误）
    try:
        from config import validate_config, check_config
        missing = check_config()
        if missing:
            logger.warning("配置警告: %s", "; ".join(missing))
        validate_config()
        logger.info("配置校验通过")
    except Exception as e:
        logger.error("配置校验失败: %s", e)
        sys.exit(1)

    # 3. 初始化数据库
    _init_db()
    # 启动指标持久化线程
    from observability import start_metrics_persist_thread
    start_metrics_persist_thread()
    # 启动 WAL checkpoint 后台线程
    _wal_thread = threading.Thread(target=_wal_checkpoint_loop, daemon=True)
    _wal_thread.start()
    logger.info("WAL checkpoint thread started (interval=%ds)", _WAL_CHECKPOINT_INTERVAL)
    from config import MCP_SERVER_HOST, MCP_SERVER_PORT
    logger.info("Memory Engine v2.2.0 starting on %s:%d", MCP_SERVER_HOST, MCP_SERVER_PORT)

    # P3-4: 注册优雅关闭回调
    def _shutdown():
        logger.info("正在关闭 Memory Engine...")
        _release_lock()
        _conn_pool.close_all()
        logger.info("Memory Engine 已关闭")

    atexit.register(_shutdown)

    mcp.run(transport="streamable-http", host=MCP_SERVER_HOST, port=MCP_SERVER_PORT)
