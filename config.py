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
# ---------------------------------------------------------------------------
DB_PATH = Path(os.getenv("MEMORY_DB_PATH", str(ROOT / "memory.db")))

# ---------------------------------------------------------------------------
# ChromaDB 向量存储
# ---------------------------------------------------------------------------
CHROMADB_PATH = Path(os.getenv("CHROMADB_PATH", str(ROOT / "chromadb")))
CHROMADB_COLLECTION = os.getenv("CHROMADB_COLLECTION", "memory_tree")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# ---------------------------------------------------------------------------
# LLM 配置
# ---------------------------------------------------------------------------
LLM_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
LLM_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))

# ---------------------------------------------------------------------------
# 飞书集成
# ---------------------------------------------------------------------------
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_ENABLED = os.getenv("FEISHU_ENABLED", "1")

# ---------------------------------------------------------------------------
# 限制
# ---------------------------------------------------------------------------
MAX_MEMORY_ROWS = int(os.getenv("MAX_MEMORY_ROWS", "100"))

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
MCP_SERVER_NAME = os.getenv("MCP_SERVER_NAME", "Memory Engine")

# ---------------------------------------------------------------------------
# 验证必需配置
# ---------------------------------------------------------------------------
def check_config() -> list[str]:
    """检查必需配置项，返回缺失项列表。"""
    missing = []
    if not LLM_API_KEY:
        missing.append("DEEPSEEK_API_KEY (事实提取和摘要生成需要)")
    return missing
