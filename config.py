# 记忆引擎 (Memory Engine) 统一配置
# 加载顺序: 环境变量 > .env 文件 > 默认值

import os
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 自动加载 .env
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env", override=False)

# ---------------------------------------------------------------------------
# 数据库
# 同时支持 ENTERPRISE_MEMORY_DB 和 MEMORY_DB_PATH（README 中两者均有记载）
# ---------------------------------------------------------------------------

DB_PATH = Path(
    os.getenv("ENTERPRISE_MEMORY_DB")
    or os.getenv("MEMORY_DB_PATH", str(ROOT / "memory.db"))
)

# ---------------------------------------------------------------------------
# FAISS 向量索引
# ---------------------------------------------------------------------------

FAISS_INDEX_PATH = Path(os.getenv("FAISS_INDEX_PATH", str(ROOT / "faiss.index")))
EMBEDDING_MODEL  = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# ---------------------------------------------------------------------------
# LLM 配置
# ---------------------------------------------------------------------------

LLM_API_KEY    = os.getenv("DEEPSEEK_API_KEY", "")
LLM_BASE_URL   = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
LLM_MODEL      = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))
LLM_TIMEOUT    = int(os.getenv("LLM_TIMEOUT", "30"))    # 生产默认 30 秒（原 60 秒）

# ---------------------------------------------------------------------------
# 飞书集成
# ---------------------------------------------------------------------------

FEISHU_APP_ID     = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_ENABLED    = os.getenv("FEISHU_ENABLED", "1")

# ---------------------------------------------------------------------------
# 限制
# ---------------------------------------------------------------------------

MAX_MEMORY_ROWS       = int(os.getenv("MAX_MEMORY_ROWS", "100"))
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "50"))
MAX_CONTENT_LENGTH    = int(os.getenv("MAX_CONTENT_LENGTH", "50000"))  # 单条内容上限

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

MCP_SERVER_NAME = os.getenv("MCP_SERVER_NAME", "Memory Engine")
MCP_SERVER_HOST = os.getenv("MCP_SERVER_HOST", "127.0.0.1")
MCP_SERVER_PORT = int(os.getenv("MCP_SERVER_PORT", "8765"))

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

LOG_LEVEL          = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE           = os.getenv("LOG_FILE", "")               # 空 = 仅 stderr
LOG_MAX_BYTES      = int(os.getenv("LOG_MAX_BYTES", "10485760"))   # 10 MB 轮转
LOG_BACKUP_COUNT   = int(os.getenv("LOG_BACKUP_COUNT", "5"))       # 保留 5 个历史文件

# ---------------------------------------------------------------------------
# PID 锁文件（防止多个实例同时启动）
# ---------------------------------------------------------------------------

PID_FILE = Path(os.getenv("MEMORY_PID_FILE", str(ROOT / ".memory_server.pid")))

# ---------------------------------------------------------------------------
# 验证必需配置
# ---------------------------------------------------------------------------

def check_config() -> list[str]:
    """检查必需配置项，返回缺失项列表。"""
    missing = []
    if not LLM_API_KEY and not os.getenv("SKIP_API_KEY_CHECK"):
        missing.append("DEEPSEEK_API_KEY (事实提取和摘要生成需要)")
    if not DB_PATH.exists():
        missing.append(f"数据库路径不存在: {DB_PATH}")
    return missing


def validate_config() -> None:
    """启动时校验配置合法性，不合法直接 raise。"""
    errors = []
    # 下限检查
    if LLM_TIMEOUT < 5:
        errors.append(f"LLM_TIMEOUT 过小: {LLM_TIMEOUT}s（建议 >= 10s）")
    if MAX_CONCURRENT_REQUESTS < 1:
        errors.append(f"MAX_CONCURRENT_REQUESTS 无效: {MAX_CONCURRENT_REQUESTS}")
    if MAX_CONTENT_LENGTH < 1000:
        errors.append(f"MAX_CONTENT_LENGTH 过小: {MAX_CONTENT_LENGTH}")
    # P2-12: 上限检查
    if LLM_TIMEOUT > 300:
        errors.append(f"LLM_TIMEOUT 过大: {LLM_TIMEOUT}s（建议 <= 300s）")
    if MAX_CONCURRENT_REQUESTS > 200:
        errors.append(f"MAX_CONCURRENT_REQUESTS 过大: {MAX_CONCURRENT_REQUESTS}（建议 <= 200）")
    if MAX_CONTENT_LENGTH > 200000:
        errors.append(f"MAX_CONTENT_LENGTH 过大: {MAX_CONTENT_LENGTH}（建议 <= 200000）")
    if errors:
        # P3-2: 格式化错误信息，便于阅读
        error_msg = "配置校验失败:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)
