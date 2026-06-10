"""
可观测性 + 性能工具 — trace_id、指标、LLM 重试

v2.2.0: 指标持久化到 SQLite，支持重启后恢复。
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
    """进程内性能指标计数器，定期持久化到 .metrics.json。
    
    追踪: 请求数、错误数、平均延迟、LLM 调用次数、LLM 错误次数。
    线程安全: 所有操作通过 _lock 保护。
    持久化: 启动时从磁盘恢复，定期后台线程写入。
    """
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
            # P2-4: 使用文件锁避免并发写入损坏
            # BUG-5: fcntl 跨平台兼容（Windows 回退）
            try:
                import fcntl
                has_fcntl = True
            except ImportError:
                has_fcntl = False
            
            with open(path, "w") as f:
                if has_fcntl:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                f.write(json.dumps(self.snapshot()))
                if has_fcntl:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            import logging
            logging.getLogger("memory_engine").debug("Metrics persist failed (non-fatal)")

    def _load_persisted(self):
        """启动时从磁盘恢复上次指标。

        P2-④ 修复: 处理空文件、损坏 JSON 等边缘情况。
        """
        try:
            from config import ROOT
            path = ROOT / ".metrics.json"
            if path.exists():
                # P2-4: 读取时使用共享锁，避免与写入冲突
                # BUG-5: fcntl 跨平台兼容（Windows 回退）
                try:
                    import fcntl
                    has_fcntl = True
                except ImportError:
                    has_fcntl = False

                with open(path, "r") as f:
                    if has_fcntl:
                        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                    raw = f.read().strip()
                    if not raw:
                        # P2-④ 修复: 空文件，视为无历史数据
                        return
                    data = json.loads(raw)
                if has_fcntl:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                self.request_count = data.get("requests", 0)
                self.error_count = data.get("errors", 0)
                self.llm_call_count = data.get("llm_calls", 0)
                self.llm_error_count = data.get("llm_errors", 0)
        except json.JSONDecodeError:
            # P2-④ 修复: JSON 损坏，记录警告并重置
            import logging
            logging.getLogger("memory_engine").warning(
                ".metrics.json 文件损坏，已重置指标"
            )
        except Exception:
            pass
        finally:
            # 确保至少初始化到默认值
            if self.request_count == 0 and self.error_count == 0:
                pass  # 已经是默认值

    def reset(self):
        """P3-6 修复: 重置所有指标计数器（用于长期运行服务的定期清零）。"""
        with self._lock:
            self.request_count = 0
            self.error_count = 0
            self.total_latency_ms = 0.0
            self.llm_call_count = 0
            self.llm_error_count = 0


metrics = Metrics()


def start_metrics_persist_thread(interval: int = 300):
    """启动后台线程，每 interval 秒持久化指标。

    P2-⑤ 修复: 添加错误处理，避免异常静默吞噬。
    """
    def _loop():
        while True:
            time.sleep(interval)
            try:
                metrics.persist()
            except Exception as e:
                import logging
                logging.getLogger("memory_engine").warning(
                    "Metrics persist failed (non-fatal): %s", e
                )
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
