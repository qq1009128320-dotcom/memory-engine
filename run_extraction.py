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
# ---------------------------------------------------------------------------

def call_llm_extract(conversation_text: str) -> dict:
    """调用 LLM 提取事实。"""
    if not LLM_API_KEY:
        print("⚠️ 警告: LLM_API_KEY 未配置，跳过提取", file=sys.stderr)
        return _empty_result()

    prompt = EXTRACTION_PROMPT.format(conversation=conversation_text)

    try:
        from llm_client import call_llm as llm_call
        content = llm_call(
            prompt,
            system_prompt="你是一个记忆引擎的事实提取器，只输出纯JSON。",
            temperature=0.1,
        )
        return parse_extraction_result(content)
    except Exception as e:
        print(f"❌ LLM 调用失败: {e}", file=sys.stderr)
        return _empty_result()


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def main():
    _init_db()
    
    # 解析命令行参数
    text = None
    input_file = None
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--text" and len(sys.argv) > 2:
            text = sys.argv[2]
        elif sys.argv[1] == "--input" and len(sys.argv) > 2:
            input_file = sys.argv[2]
        elif len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
            # 直接传文本作为第一个非标志参数
            text = sys.argv[1]
    
    # 读取输入
    if input_file:
        with open(input_file, 'r', encoding='utf-8') as f:
            text = f.read()
    elif text is None:
        # 从 stdin 读取
        text = sys.stdin.read()
    
    if not text or not text.strip():
        print("⚠️ 没有输入文本，跳过提取")
        return
    
    print(f"📝 输入文本长度: {len(text)} 字符")
    
    # 调用 LLM 提取
    print("🔄 正在调用 LLM 提取事实...")
    extracted = call_llm_extract(text)
    
    # 统计结果
    n_prefs = len(extracted.get("preferences", []))
    n_errors = len(extracted.get("errors", []))
    n_entities = len(extracted.get("entities", []))
    n_rels = len(extracted.get("relationships", []))
    
    print(f"📊 提取结果:")
    print(f"   偏好: {n_prefs} 条")
    print(f"   纠正: {n_errors} 条")
    print(f"   实体: {n_entities} 个")
    print(f"   关系: {n_rels} 条")
    
    if n_prefs + n_errors + n_entities + n_rels == 0:
        print("✅ 没有发现新事实，无需写入记忆库")
        return
    
    # 写入记忆库
    print("💾 写入记忆库...")
    calls = to_mcp_calls(extracted)
    
    success_count = 0
    for call in calls:
        tool = call["tool"]
        args = call["arguments"]
        try:
            if tool == "preference_add":
                preference_add(**args)
            elif tool == "error_log":
                error_log(**args)
            elif tool == "entity_add":
                entity_add(**args)
            elif tool == "entity_link":
                entity_link(**args)
            success_count += 1
        except Exception as e:
            print(f"   ❌ {tool} 失败: {e}", file=sys.stderr)
    
    print(f"✅ 成功写入 {success_count}/{len(calls)} 条记录")


if __name__ == "__main__":
    main()
