#!/bin/bash
# 企业级 Agent 记忆引擎 — 初始化脚本
# 运行一次即可完成数据库初始化
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# P3-4: 动态检测 venv，优先使用当前环境的 Python
if [ -f "$SCRIPT_DIR/venv/bin/python3" ]; then
    VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
elif command -v python3 &>/dev/null; then
    VENV_PYTHON="python3"
    echo "⚠️  未检测到 venv，使用系统 Python"
else
    echo "❌ 未找到 Python3，请安装"
    exit 1
fi

echo "=== 企业级 Agent 记忆引擎 — 初始化 ==="
echo ""

# 1. 初始化数据库
echo "[1/3] 初始化 SQLite 数据库..."
cd "$SCRIPT_DIR"
"$VENV_PYTHON" -c "
import os
os.environ['ENTERPRISE_MEMORY_DB'] = 'memory.db'
from memory_server import _init_db
_init_db()
print('  数据库已创建: memory.db')
"

# 2. 验证 MCP Server
echo "[2/3] 验证 MCP Server..."
"$VENV_PYTHON" -c "
import os
os.environ['ENTERPRISE_MEMORY_DB'] = 'memory.db'
from memory_server import memory_stats
stats = memory_stats()
tool_count = sum(1 for name in dir(__import__('memory_server')) if name.startswith('memory_') or name.startswith('preference_') or name.startswith('error_') or name.startswith('entity_') or name.startswith('graph_'))
print(f'  工具可用: {tool_count} 个')
print(f'  表已就绪: memory_tree_chunks, preference_memory, error_memory, entities, relationships')
"

# 3. 提示 MCP 配置
echo "[3/3] MCP 配置"
echo ""
echo "将以下配置添加到 ~/.hermes/config.yaml 的顶层："
echo ""
echo "mcp_servers:"
echo "  enterprise-memory:"
echo "    command: \"$VENV_PYTHON\""
echo "    args: [\"$SCRIPT_DIR/memory_server.py\"]"
echo "    timeout: 60"
echo ""
echo "添加后重启 Hermes Agent，MCP 工具将自动注册。"
echo ""
echo "=== 初始化完成 ==="
