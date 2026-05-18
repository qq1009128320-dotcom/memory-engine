"""
记忆引擎 — 结构化日志工具

用法:
    from log_utils import get_logger
    logger = get_logger(__name__)
    logger.info("something happened", extra={"key": "value"})
"""

import logging
import sys
from datetime import datetime, timezone


def setup_logging(level: str = "INFO", log_file: str = "") -> None:
    """配置全局日志。level: DEBUG|INFO|WARNING|ERROR，log_file: 可选文件路径。"""
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fmt.converter = lambda *args: datetime.now(timezone.utc).timetuple()

    root = logging.getLogger("memory_engine")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 控制台输出
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(fmt)
    root.handlers.clear()
    root.addHandler(handler)

    # 可选文件输出
    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    """获取命名 logger。"""
    return logging.getLogger(f"memory_engine.{name}")


# 模块初始化时按默认配置
setup_logging()
