"""
可观测性 + 性能工具 — trace_id、指标、LLM 重试

v2.0.5: 指标持久化到 SQLite，支持重启后恢复。
"""

import json
import time
import uuid
import threading
import functools
from typing import Any, Callable
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Trace ID
# ---------------------------------------------------------------------------
_trace_local = threading.local()


def get_trace_id() -> str:
    """获取或生成当前调用的 trace_id。"""
    if not hasattr(_trace_local, "trace_id"):
        _trace_local.trace_id = str(uuid.uuid4())[:8]
    return _trace_local.trace_id


def new_trace() -> str:
    """为新请求生成新的 trace_id。"""
    _trace_local.trace_id = str(uuid.uuid4())[:8]
    return _trace_local.trace_id


# ---------------------------------------------------------------------------
# 性能指标（进程内计数 + 定期持久化）
# ---------------------------------------------------------------------------
class Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self.request_count = 0
        self.error_count = 0
        self.total_latency_ms = 0.0
        self.llm_call_count = 0
        self.llm_error_count = 0
        self._load_persisted()

    def record_request(self, latency_ms: float):
        with self._lock:
            self.request_count += 1
            self.total_latency_ms += latency_ms

    def record_error(self):
        with self._lock:
            self.error_count += 1

    def record_llm_call(self):
        with self._lock:
            self.llm_call_count += 1

    def record_llm_error(self):
        with self._lock:
            self.llm_error_count += 1

    def snapshot(self) -> dict:
        with self._lock:
            avg_latency = (self.total_latency_ms / self.request_count) if self.request_count > 0 else 0
            return {
                "requests": self.request_count,
                "errors": self.error_count,
                "avg_latency_ms": round(avg_latency, 2),
                "llm_calls": self.llm_call_count,
                "llm_errors": self.llm_error_count,
                "error_rate": round(self.error_count / max(self.request_count, 1), 4),
            }

    def persist(self):
        """持久化当前指标到磁盘（由后台线程定期调用）。"""
        try:
            from config import ROOT
            path = ROOT / ".metrics.json"
            path.write_text(json.dumps(self.snapshot()))
        except Exception:
            pass

    def _load_persisted(self):
        """启动时从磁盘恢复上次指标。"""
        try:
            from config import ROOT
            path = ROOT / ".metrics.json"
            if path.exists():
                data = json.loads(path.read_text())
                self.request_count = data.get("requests", 0)
                self.error_count = data.get("errors", 0)
                self.llm_call_count = data.get("llm_calls", 0)
                self.llm_error_count = data.get("llm_errors", 0)
        except Exception:
            pass


metrics = Metrics()


def start_metrics_persist_thread(interval: int = 300):
    """启动后台线程，每 interval 秒持久化指标。"""
    def _loop():
        while True:
            time.sleep(interval)
            metrics.persist()
    t = threading.Thread(target=_loop, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# LLM 重试装饰器
# ---------------------------------------------------------------------------
def with_retry(max_retries: int = 3, base_delay: float = 1.0):
    """LLM 调用自动重试，指数退避。"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries):
                try:
                    metrics.record_llm_call()
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    metrics.record_llm_error()
                    if attempt < max_retries - 1:
                        delay = base_delay * (2**attempt)
                        import logging
                        logging.getLogger("memory_engine").warning(
                            "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                            attempt + 1, max_retries, delay, e,
                        )
                        time.sleep(delay)
            raise last_exc
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# 工具调用计时装饰器
# ---------------------------------------------------------------------------
def track_mcp_tool(func: Callable) -> Callable:
    """记录 MCP 工具调用的延迟和错误。"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        new_trace()
        t0 = time.monotonic()
        try:
            result = func(*args, **kwargs)
            metrics.record_request((time.monotonic() - t0) * 1000)
            return result
        except Exception:
            metrics.record_error()
            raise
    return wrapper


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------
def health_check() -> dict:
    """返回服务健康状态。"""
    import sqlite3
    from config import DB_PATH

    status = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trace_id": get_trace_id(),
    }

    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("SELECT 1")
        conn.close()
        status["database"] = "ok"
    except Exception as e:
        status["database"] = f"error: {e}"
        status["status"] = "degraded"

    return status
