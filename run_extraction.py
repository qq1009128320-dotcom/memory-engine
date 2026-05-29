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

# ---------------------------------------------------------------------------
# 导入 MCP 工具（直接调用 memory_server 的函数，不走 MCP 协议）
# ---------------------------------------------------------------------------

from memory_server import (
    preference_add,
    error_log,
    entity_add,
    entity_link,
    _init_db,
)

# ---------------------------------------------------------------------------
# 提示词模板
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """你是一个记忆引擎的事实提取器。
从以下对话中提取值得长期记住的事实。

对话：
{conversation}

请提取以下四类事实：

1. **preferences（偏好/规则）**：
   - field_alias: 字段名映射。用户说「用 amt_jpy 不用 base_amt」→ 提取
   - date_rule: 日期规则。用户说「结算是 25 号」→ 提取
   - naming: 命名约定。用户说「腾讯客户名是 Tencent」→ 提取
   - policy: 业务政策。用户说「研发全部费用化」→ 提取
   - format: 格式偏好。用户说「报告用环比不用同比」→ 提取

2. **errors（纠正）**：
   - 用户纠正了 Agent 的什么行为？
   - 错误类型：field_selection | logic_error | scope_error | omission
   - 严重程度：minor | major | critical

3. **entities（实体）**：
   - 新出现的客户、人员、部门、项目、政策等
   - 包含别名和属性

4. **relationships（关系）**：
   - 实体之间的关系：A 属于 B / A 负责 B 等

输出规则：
- 只输出【之前没有提取过的】事实
- 如果这段对话没有新事实，输出空数组
- 事实要具体、可验证、不包含推测
- 必须输出纯 JSON，不要 markdown 标记

输出格式（严格的 JSON）：
{{
  "preferences": [
    {{
      "category": "field_alias",
      "condition": "查询金额时",
      "rule": "使用 amt_jpy 字段而非 base_amt",
      "confidence": 0.9,
      "scope": "personal"
    }}
  ],
  "errors": [
    {{
      "task_type": "financial_query",
      "error_category": "field_selection",
      "mistake": "Agent 使用了 base_amt 字段",
      "correction": "应该使用 amt_jpy 字段",
      "severity": "minor"
    }}
  ],
  "entities": [
    {{
      "type": "client",
      "name": "腾讯科技",
      "aliases": ["腾讯", "Tencent"],
      "properties": {{}},
      "scope": "personal"
    }}
  ],
  "relationships": [
    {{
      "source": "张经理",
      "source_type": "person",
      "target": "财务部",
      "target_type": "department",
      "relation": "works_in",
      "scope": "personal"
    }}
  ]
}}

如果没有任何可提取的事实，返回：
{{"preferences": [], "errors": [], "entities": [], "relationships": []}}"""


# ---------------------------------------------------------------------------
# LLM 调用
# ---------------------------------------------------------------------------

def call_llm(prompt: str, max_tokens: int = None) -> str:
    """使用 DeepSeek API 调用 LLM（使用共享 llm_client 模块）。"""
    from llm_client import call_llm as _client_call
    return _client_call(
        prompt,
        system_prompt="你是一个精确的事实提取器。只输出 JSON，不输出其他内容。",
        max_tokens=max_tokens or LLM_MAX_TOKENS,
        temperature=0.1,
    )


# ---------------------------------------------------------------------------
# 解析和验证（使用 utils 中的共享函数）
# ---------------------------------------------------------------------------
# parse_extraction_result 和 _empty_result 已移至 utils.py




# ---------------------------------------------------------------------------
# 写入 MCP
# ---------------------------------------------------------------------------

def save_extracted_facts(extracted: dict) -> dict[str, int]:
    """将提取结果写入记忆引擎。"""
    counts = {"preferences": 0, "errors": 0, "entities": 0, "relationships": 0}

    for pref in extracted.get("preferences", []):
        try:
            result = preference_add(
                category=pref.get("category", "field_alias"),
                condition=pref.get("condition", ""),
                rule=pref.get("rule", ""),
                scope=pref.get("scope", "personal"),
                source_type="extracted",
                confidence=float(pref.get("confidence", 0.8)),
            )
            counts["preferences"] += 1
        except Exception as e:
            print(f"  ⚠ 偏好写入失败: {e}", file=sys.stderr)

    for err in extracted.get("errors", []):
        try:
            result = error_log(
                task_type=err.get("task_type", "unknown"),
                error_category=err.get("error_category", "field_selection"),
                mistake_description=err.get("mistake", ""),
                correction=err.get("correction", ""),
                severity=err.get("severity", "minor"),
            )
            counts["errors"] += 1
        except Exception as e:
            print(f"  ⚠ 错误记录写入失败: {e}", file=sys.stderr)

    for ent in extracted.get("entities", []):
        try:
            aliases = ent.get("aliases", [])
            result = entity_add(
                type=ent.get("type", "document"),
                name=ent.get("name", ""),
                aliases=json.dumps(aliases, ensure_ascii=False) if isinstance(aliases, list) else str(aliases),
                properties=json.dumps(ent.get("properties", {}), ensure_ascii=False),
                scope=ent.get("scope", "personal"),
            )
            counts["entities"] += 1
        except Exception as e:
            print(f"  ⚠ 实体写入失败: {e}", file=sys.stderr)

    for rel in extracted.get("relationships", []):
        try:
            result = entity_link(
                source_name=rel.get("source", ""),
                source_type=rel.get("source_type", ""),
                target_name=rel.get("target", ""),
                target_type=rel.get("target_type", ""),
                relation=rel.get("relation", ""),
                scope=rel.get("scope", "personal"),
            )
            counts["relationships"] += 1
        except Exception as e:
            print(f"  ⚠ 关系写入失败: {e}", file=sys.stderr)

    return counts


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="从对话中提取事实并写入企业记忆引擎")
    parser.add_argument("--input", "-i", help="对话文本文件路径")
    parser.add_argument("--text", "-t", help="直接传入对话文本")
    parser.add_argument("--dry-run", action="store_true", help="只提取不写入")
    parser.add_argument("--prompt-only", action="store_true", help="只输出提示词和对话文本，不调用 LLM")
    args = parser.parse_args()

    # 读取对话文本
    conversation = ""
    if args.text:
        conversation = args.text
    elif args.input:
        with open(args.input, encoding="utf-8") as f:
            conversation = f.read()
    else:
        # 从 stdin 读取
        if not sys.stdin.isatty():
            conversation = sys.stdin.read()
        else:
            print("用法: run_extraction.py --input file.txt | --text '对话' | < stdin")
            print("      run_extraction.py --prompt-only  输出提示词模板")
            sys.exit(1)

    if not conversation.strip():
        print("错误: 对话内容为空", file=sys.stderr)
        sys.exit(1)

    # 初始化数据库
    _init_db()

    if args.prompt_only:
        print(EXTRACTION_PROMPT.format(conversation=conversation))
        return

    print(f"📄 对话长度: {len(conversation)} 字符")
    print("🤖 正在调用 LLM 提取事实...")

    try:
        prompt = EXTRACTION_PROMPT.format(conversation=conversation)
        llm_output = call_llm(prompt)
        extracted = parse_extraction_result(llm_output)

        total = (len(extracted["preferences"]) + len(extracted["errors"]) +
                 len(extracted["entities"]) + len(extracted["relationships"]))

        print(f"\n📊 提取结果: {total} 条新事实")
        print(f"  偏好: {len(extracted['preferences'])}")
        print(f"  纠正: {len(extracted['errors'])}")
        print(f"  实体: {len(extracted['entities'])}")
        print(f"  关系: {len(extracted['relationships'])}")

        if total == 0:
            print("\n未提取到新事实，跳过写入。")
            return

        if args.dry_run:
            print("\n🔍 提取内容预览 (dry-run):")
            print(json.dumps(extracted, ensure_ascii=False, indent=2))
            return

        # 写入
        counts = save_extracted_facts(extracted)
        print(f"\n✅ 已写入记忆引擎:")
        print(f"  偏好记忆: +{counts['preferences']}")
        print(f"  纠错记忆: +{counts['errors']}")
        print(f"  知识图谱实体: +{counts['entities']}")
        print(f"  知识图谱关系: +{counts['relationships']}")

    except Exception as e:
        print(f"\n❌ 提取失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
