#!/bin/bash
# Auto-Fetch 定时同步脚本
# 由 Hermes cronjob 每 20 分钟触发
set -e

SCRIPT_DIR="/home/administrator/tools/enterprise-memory"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
LOG_FILE="$SCRIPT_DIR/auto_fetch.log"

# 确保 PATH 包含 lark-cli
export PATH="$HOME/.hermes/node/bin:$PATH"

cd "$SCRIPT_DIR"

echo "--- $(date '+%Y-%m-%d %H:%M:%S') Auto-Fetch ---" >> "$LOG_FILE"

# Step 1: 同步飞书数据
$VENV_PYTHON auto_fetch.py >> "$LOG_FILE" 2>&1
echo "  auto_fetch: OK" >> "$LOG_FILE"

# Step 2: 检查是否有新数据（memory_tree_chunks 数量变化）
BEFORE=$($VENV_PYTHON -c "import sqlite3; c=sqlite3.connect('memory.db'); print(c.execute('SELECT COUNT(*) FROM memory_tree_chunks WHERE source_type!=\"summary\"').fetchone()[0])")

# Step 3: 重建摘要树（如果 auto_fetch 有新增）
$VENV_PYTHON summary_tree.py --rebuild >> "$LOG_FILE" 2>&1
echo "  summary_tree: OK" >> "$LOG_FILE"

# Step 4: 重建 FAISS 向量索引（通过 MCP 协议调用 memory_server 的 reindex 工具）
$VENV_PYTHON -c "
import json, urllib.request, sys

payload = json.dumps({
    'jsonrpc': '2.0', 'id': 'reindex',
    'method': 'tools/call',
    'params': {'name': 'memory_tree_reindex', 'arguments': {}}
}).encode()
req = urllib.request.Request(
    'http://127.0.0.1:8765/mcp',
    data=payload,
    headers={'Content-Type': 'application/json'},
    method='POST'
)
try:
    resp = urllib.request.urlopen(req, timeout=300)
    body = resp.read().decode()
    result_text = ''
    for line in body.split('\n'):
        if line.startswith('data: '):
            try:
                msg = json.loads(line[6:])
                if 'result' in msg:
                    result_text = json.dumps(msg['result'])
            except:
                pass
    print(f'  FAISS reindex: {result_text or body[:200]}', flush=True)
except Exception as e:
    print(f'  FAISS reindex via MCP failed: {e}', file=sys.stderr, flush=True)
    print(f'  Fallback: reconstructing index directly...', flush=True)
    # 备用：直接重建（不依赖 MCP server）
    import sqlite3, gc, numpy as np
    from sentence_transformers import SentenceTransformer
    import faiss

    model = SentenceTransformer('all-MiniLM-L6-v2', local_files_only=True)
    VECTOR_DIM = 384

    conn = sqlite3.connect('memory.db')
    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT id, title, content FROM memory_tree_chunks').fetchall()
    conn.close()

    if rows:
        index = faiss.IndexIDMap(faiss.IndexFlatL2(VECTOR_DIM))
        vectors, ids, id_map = [], [], []
        batch_size = 16
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i+batch_size]
            texts = [f\"{r['title']}\n{r['content'][:8000]}\" for r in batch]
            batch_vecs = model.encode(texts).astype('float32')
            for j, (vec, row) in enumerate(zip(batch_vecs, batch)):
                vectors.append(vec)
                ids.append(i + j)
                id_map[i + j] = row['id']
            gc.collect()
        if vectors:
            vec_array = np.array(vectors).astype('float32')
            index.add_with_ids(vec_array, np.array(ids, dtype=np.int64))
            faiss.write_index(index, 'faiss.index')
            import json as _json
            with open('faiss_id_map.json', 'w') as f:
                _json.dump(id_map, f)
            print(f'  FAISS reindex (fallback): {len(ids)} docs', flush=True)
    else:
        print('  FAISS reindex: no docs to index', flush=True)
" >> "$LOG_FILE" 2>&1
echo "  reindex: OK" >> "$LOG_FILE"

AFTER=$($VENV_PYTHON -c "import sqlite3; c=sqlite3.connect('memory.db'); print(c.execute('SELECT COUNT(*) FROM memory_tree_chunks WHERE source_type!=\"summary\"').fetchone()[0])")
echo "  chunks: $BEFORE -> $AFTER" >> "$LOG_FILE"

echo "  done." >> "$LOG_FILE"
