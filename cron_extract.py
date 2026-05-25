#!/usr/bin/env python3
"""Cron extraction runner — calls run_extraction.py with recent session text."""
import json
import sys
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent

# Compile conversation text from today's sessions
conversation = """
会话1: 2026-05-22 09:17-09:28 — 记忆引擎全面审查与代码修复 v1.3.0

用户要求对 enterprise-memory 项目进行全面审查，重点关注稳定性、存储和调用速率。

审查结果：
- 系统状态健康，数据库正常
- 当前记忆库：memory_tree_chunks=42, preferences=26, errors=14（已解4）, entities=48, relationships=31
- 发现8个未解决错误，包括：
  - 逻辑错误（major）：研发支出未费用化处理
  - 字段选择错误（minor）：使用了 base_amt 字段而非 amt_jpy 查询财务费用
  - 遗漏（major）：7个关键偏好（含研发费用化、客户名映射等）被禁用

代码修复（v1.3.0）：
- 修复 ChromaDB stale collection 重试逻辑
- 修复 run_extraction.py 实体/关系类型枚举限制（file类型、非标准关系被拒绝写入）
- 修复 config.py 嵌入模型注释（BGE-M3 -> all-MiniLM-L6-v2）
- 修复 logging 模块在函数内部导入的问题
- 修复 test_21_tools.py pytest fixture 错误

ChromaDB 索引重建后恢复（45条全部索引成功）

记忆库增长监测：纠错记忆 8->14（+6），知识图谱实体 45->48（+3）

关键文件路径：
- 记忆引擎项目：/home/administrator/tools/enterprise-memory/
- 财务数据项目：/home/administrator/finance_data/
- ChromaDB数据：/home/administrator/tools/enterprise-memory/chromadb/
- SQLite数据库：/home/administrator/tools/enterprise-memory/memory.db

会话2: 2026-05-22 00:43-02:02 — 记忆引擎审查与 GitHub 同步

用户要求全面审查记忆引擎并完成 v1.3.0 的代码修复和 GitHub 同步。

触发电机优化：
- SKILL.md triggers 从 11 个扩展到 44 个，按 6 个场景分组
- 用户偏好：用户说"记录"或"记一下"时，自动调用 memory_tree_ingest 存入记忆引擎

GitHub 提交：
- commit 95922cb: fix(memory-server): v1.3.0 — 修复 ChromaDB stale 和中文搜索问题
- commit c3703ce: docs(readme): 更新接入方式、项目结构、版本信息
- commit 1aece96: docs(skill): 扩展触发词列表从11到44个
- commit 53b9122: docs(readme): 项目结构增加SKILL.md条目
仓库：github.com/qq1009128320-dotcom/memory-engine，main 分支

systemd 服务：memory-engine.service，MemoryHigh=512M, MemoryMax=1G, Restart=always
端口：8765（SSE 模式）
"""

# Write conversation to temp file
tmp_file = ROOT / "tmp_dialogue.txt"
tmp_file.write_text(conversation)

# Run extraction
result = subprocess.run(
    [sys.executable, str(ROOT / "run_extraction.py"), "--input", str(tmp_file)],
    capture_output=True,
    text=True,
    timeout=120,
)

print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
print("EXIT:", result.returncode)

# Cleanup
if tmp_file.exists():
    tmp_file.unlink()
