#!/usr/bin/env python3
"""
记忆引擎事实提取运行器

使用方式：
  方式1: 从文件读取对话
    python3 run_extraction.py --input conversation.txt

  方式2: 从 stdin 读取
    cat conversation.txt | python3 run_extraction.py

  方式3: 直接传文本
    python3 run_extraction.py --text "用户: 帮我查腾讯的研发费用\nAgent: ..."

依赖：
  - DEEPSEEK_API_KEY 环境变量（从 Hermes .env 自动加载）
  - memory_server.py 的 MCP 工具（通过直接函数调用）
"""

import json
import sys
import time
from pathlib import Path
from typing import Any

# 统一配置（从 config.py 加载，自动读取 .env）
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_MAX_TOKENS, LLM_TIMEOUT
from utils import parse_extraction_result, empty_result as _empty_result

# P3-④ 修复: MCP 工具导入包裹在 try/except 中
try:
    from memory_server import (
        preference_add,
        error_log,
        entity_add,
        entity_link,
        _init_db,
    )
    from extract_facts import EXTRACTION_PROMPT, to_mcp_calls
except ImportError as e:
    print(f"❌ 导入失败: {e}", file=sys.stderr)
    print("   请确保已在虚拟环境中安装依赖: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# LLM 调用
