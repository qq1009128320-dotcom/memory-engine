#!/bin/bash
# Auto-Fetch 定时同步脚本
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
LOG_FILE="$SCRIPT_DIR/auto_fetch.log"

HERMES_NODE="$HOME/.hermes/node/bin"
if [ -d "$HERMES_NODE" ]; then
    export PATH="$HERMES_NODE:$PATH"
fi

cd "$SCRIPT_DIR"

echo "--- $(date "+%Y-%m-%d %H:%M:%S") Auto-Fetch ---" >> "$LOG_FILE"

$VENV_PYTHON auto_fetch.py >> "$LOG_FILE" 2>&1
echo "  auto_fetch: OK" >> "$LOG_FILE"

BEFORE=$($VENV_PYTHON -c "import sqlite3; c=sqlite3.connect(\"memory.db\"); print(c.execute(\"SELECT COUNT(*) FROM memory_tree_chunks WHERE source_type != \\\"summary\\\"\").fetchone()[0])")

$VENV_PYTHON summary_tree.py --rebuild >> "$LOG_FILE" 2>&1
echo "  summary_tree: OK" >> "$LOG_FILE"

$VENV_PYTHON "$SCRIPT_DIR/scripts/reindex_via_mcp.py" >> "$LOG_FILE" 2>&1
echo "  reindex: OK" >> "$LOG_FILE"

AFTER=$($VENV_PYTHON -c "import sqlite3; c=sqlite3.connect(\"memory.db\"); print(c.execute(\"SELECT COUNT(*) FROM memory_tree_chunks WHERE source_type != \\\"summary\\\"\").fetchone()[0])")
echo "  chunks: $BEFORE -> $AFTER" >> "$LOG_FILE"

echo "  done." >> "$LOG_FILE"
