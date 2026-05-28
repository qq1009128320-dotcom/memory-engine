"""
记忆引擎 — 结构化日志工具（生产级：轮转 + 脱敏 + 结构化）

用法:
    from log_utils import get_logger
    logger = get_logger(__name__)
    logger.info("something happened", extra={"key": "value"})
"""

import logging
import logging.handlers
import re
import sys
from datetime import datetime, timezone


# 敏感字段正则（匹配 API key、token、password 等）
_SENSITIVE_PATTERNS = [
    (re.compile(r'(api_key|apikey|secret|password|token|auth)\s*[:=]\s*["\']?([^"\'&\s]+)', re.IGNORECASE),
     r'\1=***REDACTED***'),
    (re.compile(r'sk-[A-Za-z0-9]{20,}'),
     'sk-***REDACTED***'),
]


class SensitiveDataFilter(logging.Filter):
    """自动脱敏日志中的敏感信息。"""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pattern, replacement in _SENSITIVE_PATTERNS:
            msg = pattern.sub(replacement, msg)
        record.msg = msg
        record.args = ()  # 清空 args 避免二次格式化
        return True


def setup_logging(
    level: str = "INFO",
    log_file: str = "",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """配置全局日志。支持轮转、脱敏、结构化。

    Args:
        level: 日志级别 (DEBUG|INFO|WARNING|ERROR)
        log_file: 可选文件路径，空则仅输出到 stderr
        max_bytes: 单个日志文件最大字节数（触发轮转）
        backup_count: 保留的历史文件数
    """
    fmt = logging.Formatter(
        '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    fmt.converter = lambda *args: datetime.now(timezone.utc).timetuple()

    root = logging.getLogger("memory_engine")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    # 脱敏过滤器
    sensitive_filter = SensitiveDataFilter()
    root.addFilter(sensitive_filter)

    # stderr 输出
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    root.addHandler(console)

    # 文件输出（带轮转）
    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    # 抑制第三方库噪音
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取命名 logger。"""
    return logging.getLogger(f"memory_engine.{name}")


# 模块初始化时按默认配置
setup_logging()
