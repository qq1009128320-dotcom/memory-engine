#!/usr/bin/env python3
"""
事实提取器 — 从 Agent 与用户的对话中自动提取可记忆的事实。

1. 输入：一段完整的对话文本
2. LLM 分析对话，提取四类事实
3. 输出：结构化 JSON，供 memory_server.py 的 MCP 工具写入

可以在以下时机调用：
- 对话结束后（Hermes 的对话结束钩子）
- cronjob 定时批量处理当天的对话日志
- 用户手动触发「记住刚才说的」

注意：此模块本身不调用 LLM。它生成 LLM 提示词并解析 LLM 输出。
实际调用 LLM 由 Agent 框架（Hermes）完成。
"""

import json
from typing import Any


# ---------------------------------------------------------------------------
# LLM 提示词模板
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
# 解析和验证
# ---------------------------------------------------------------------------

def parse_extraction_result(llm_output: str) -> dict[str, list[dict[str, Any]]]:
    """
    解析 LLM 返回的 JSON，并做基本验证。

    返回格式：
    {
        "preferences": [...],
        "errors": [...],
        "entities": [...],
        "relationships": [...]
    }
    """
    # 清理 LLM 输出（去掉可能的 markdown 代码块标记）
    cleaned = llm_output.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        # 尝试提取 JSON 片段
        import re
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
            except json.JSONDecodeError:
                return _empty_result()
        else:
            return _empty_result()

    # 确保所有键都存在
    for key in ["preferences", "errors", "entities", "relationships"]:
        if key not in result:
            result[key] = []

    return result


def _empty_result() -> dict:
    return {"preferences": [], "errors": [], "entities": [], "relationships": []}


# ---------------------------------------------------------------------------
# 将提取结果转为 MCP 工具调用序列
# ---------------------------------------------------------------------------

def to_mcp_calls(extracted: dict) -> list[dict[str, Any]]:
    """
    将解析后的提取结果转换为 memory_server.py 的 MCP 工具调用序列。

    返回的列表可以直接在脚本中执行，或返回给 Agent 让它调用。
    每条记录包含 tool_name 和 arguments。
    """
    calls: list[dict[str, Any]] = []

    for pref in extracted.get("preferences", []):
        calls.append({
            "tool": "preference_add",
            "arguments": {
                "category": pref.get("category", "field_alias"),
                "condition": pref.get("condition", ""),
                "rule": pref.get("rule", ""),
                "scope": pref.get("scope", "personal"),
                "source_type": "extracted",
                "confidence": pref.get("confidence", 0.8),
            },
        })

    for err in extracted.get("errors", []):
        calls.append({
            "tool": "error_log",
            "arguments": {
                "task_type": err.get("task_type", "unknown"),
                "error_category": err.get("error_category", "field_selection"),
                "mistake_description": err.get("mistake", ""),
                "correction": err.get("correction", ""),
                "severity": err.get("severity", "minor"),
            },
        })

    for ent in extracted.get("entities", []):
        calls.append({
            "tool": "entity_add",
            "arguments": {
                "type": ent.get("type", "document"),   # 默认 document，在允许列表中
                "name": ent.get("name", ""),
                "aliases": json.dumps(ent.get("aliases", []), ensure_ascii=False),
                "properties": json.dumps(ent.get("properties", {}), ensure_ascii=False),
                "scope": ent.get("scope", "personal"),
            },
        })

    for rel in extracted.get("relationships", []):
        calls.append({
            "tool": "entity_link",
            "arguments": {
                "source_name": rel.get("source", ""),
                "source_type": rel.get("source_type", ""),
                "target_name": rel.get("target", ""),
                "target_type": rel.get("target_type", ""),
                "relation": rel.get("relation", ""),
                "scope": rel.get("scope", "personal"),
            },
        })

    return calls


# ---------------------------------------------------------------------------
# 命令行用法
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--prompt":
        # 输出提示词模板（供 Agent 使用）
        print(EXTRACTION_PROMPT)
    elif len(sys.argv) > 1 and sys.argv[1] == "--parse":
        # 从 stdin 读取 LLM 输出，解析并输出 MCP 调用序列
        llm_output = sys.stdin.read()
        extracted = parse_extraction_result(llm_output)
        calls = to_mcp_calls(extracted)
        print(json.dumps(calls, ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "--test":
        # 自测
        test_output = json.dumps({
            "preferences": [
                {"category": "field_alias", "condition": "金额查询", "rule": "用 amt_jpy", "confidence": 0.95, "scope": "personal"}
            ],
            "errors": [
                {"task_type": "data_query", "error_category": "field_selection", "mistake": "用了错误的金额字段", "correction": "金额字段应使用 amt_jpy", "severity": "minor"}
            ],
            "entities": [
                {"type": "client", "name": "测试客户", "aliases": ["Test"], "properties": {}, "scope": "personal"}
            ],
            "relationships": [
                {"source": "测试客户", "source_type": "client", "target": "财务部", "target_type": "department", "relation": "belongs_to", "scope": "personal"}
            ]
        }, ensure_ascii=False)
        extracted = parse_extraction_result(test_output)
        calls = to_mcp_calls(extracted)
        print(f"提取到 {len(extracted['preferences'])} 条偏好, {len(extracted['errors'])} 条纠正, "
              f"{len(extracted['entities'])} 个实体, {len(extracted['relationships'])} 条关系")
        print(f"生成 {len(calls)} 个 MCP 工具调用")
        for i, c in enumerate(calls):
            print(f"  [{i+1}] {c['tool']}: {c['arguments']}")
    else:
        print("用法：")
        print("  python3 extract_facts.py --prompt    输出 LLM 提示词")
        print("  python3 extract_facts.py --parse     从 stdin 读取 LLM 输出，解析为 MCP 调用")
        print("  python3 extract_facts.py --test      自测")
