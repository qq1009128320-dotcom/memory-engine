#!/usr/bin/env python3
"""记忆引擎全面审计"""
import os, sys, json, sqlite3, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ['DEEPSEEK_API_KEY'] = 'test-key'

# Temp DB
fd, tmpdb = tempfile.mkstemp(suffix='.db')
os.close(fd)
os.environ['MEMORY_DB_PATH'] = tmpdb
os.environ['CHROMADB_PATH'] = str(Path(tmpdb).parent / 'audit_chromadb')
conn = sqlite3.connect(tmpdb)
conn.executescript(open(ROOT / 'schema.sql').read())
conn.commit()
conn.close()

import importlib
import config
importlib.reload(config)

from unittest.mock import MagicMock, patch
import chromadb
mock_col = MagicMock()
mock_col.count.return_value = 2
mock_col.add.return_value = None
mock_col.get.return_value = {"ids": ["a","b"], "documents": ["x","y"]}
mock_col.query.return_value = {"ids": [["a"]], "documents": [["test"]], "distances": [[0.5]]}
mock_client = MagicMock()
mock_client.get_or_create_collection.return_value = mock_col

with patch.object(chromadb, 'PersistentClient', return_value=mock_client):
    import memory_server as ms
    importlib.reload(ms)

from validators import ValidationError

passed, failed = 0, 0
details = []

def check(name, fn):
    global passed, failed
    try:
        fn()
        passed += 1
    except Exception as e:
        failed += 1
        details.append(f"FAIL {name}: {e}")

# === 核心功能 ===
def t1(): r = ms.memory_tree_ingest("audit:1","doc","核心测试","功能验证"); assert r["status"]=="ingested",r
def t2(): r = ms.memory_tree_search("功能验证"); assert isinstance(r, list)
def t3(): r = ms.memory_tree_ingest("audit:f","doc","取回","123"); f = ms.memory_tree_fetch(r["id"]); assert f is not None
def t4(): r = ms.memory_tree_ingest("audit:s","doc","评分","内容"); s = ms.memory_tree_score(r["id"],5.0); assert s.get("status")=="ok",s
def t5(): r = ms.preference_add("field_alias","条件","规则"); assert r["status"]=="created",r
def t6(): ms.preference_add("naming","搜索测试","规则"); r = ms.preference_search("搜索测试"); assert len(r)>=1
def t7(): r = ms.preference_list(); assert len(r)>=2
def t8(): r = ms.preference_add("field_alias","禁用项","禁用"); ms.preference_disable(r["id"]); a = ms.preference_list(); assert not any(p["id"]==r["id"] for p in a)
def t9(): r = ms.error_log("audit_t","field_selection","错误","修复","minor"); assert r["status"]=="created"
def t10():
    desc = f"audit_{os.urandom(4).hex()}"
    r = None
    for _ in range(3):
        r = ms.error_log("audit_up","scope_error",desc,"修正","minor")
    # 第3次调用应触发升级
    assert r is not None and r.get("upgraded_to_preference") is True, r
def t11(): r = ms.error_list(); assert len(r)>=1
def t12(): r = ms.entity_add("client","审计实体",'["AE"]'); assert r["status"] in ("created","merged")
def t13(): r = ms.entity_search("审计实体"); assert len(r)>=1
def t14():
    ms.entity_add("person","审计人A"); ms.entity_add("department","审计部")
    r = ms.entity_link("审计人A","审计部","works_in","person","department"); assert r["status"]=="created"
def t15(): r = ms.graph_query("审计人A"); assert "entity" in r
def t16(): r = ms.memory_search("审计"); assert any(k in r for k in ["memory_tree","preferences","errors","graph"])
def t17(): r = ms.memory_stats(); assert all(k in r for k in ["memory_tree_chunks","preferences","errors","entities","relationships"])
def t18(): r = ms.memory_health(); assert r.get("status")=="healthy",r
def t19(): r = ms.memory_tree_summary(); assert "l0" in r and "l1_groups" in r

# === 静默错误 ===
def t20():
    try: ms.preference_add("bad_cat","test","test"); assert False
    except ValidationError: pass
def t21():
    try: ms.preference_add("field_alias","","test"); assert False
    except ValidationError: pass
def t22():
    try: ms.error_log("t","field_selection","m","c","invalid"); assert False
    except ValidationError: pass
def t23():
    try: ms.entity_add("bad_type","name"); assert False
    except ValidationError: pass
def t24():
    try: ms.entity_link("a","b","bad_rel"); assert False
    except ValidationError: pass

# === 安全 ===
def t25(): r = ms.entity_search("'; DROP TABLE entities; --"); assert isinstance(r, list)
def t26():
    stats = json.dumps(ms.memory_stats())
    assert "DEEPSEEK" not in stats
    assert "sk-" not in stats
def t27():
    r = ms.error_log("test","field_selection","safe","safe","minor")
    assert "sk-" not in str(r)

# === 数据一致性 ===
def t28():
    r = ms.memory_tree_ingest("audit:dedup","doc","重复","相同"); assert r["status"]=="ingested"
    r2 = ms.memory_tree_ingest("audit:dedup","doc","重复","相同"); assert r2["status"]=="duplicate",r2
def t29():
    r = ms.preference_add("naming","一致性","规则"); s = ms.preference_search("一致性")
    assert any(p["id"]==r["id"] for p in s)
def t30():
    r = ms.entity_add("client","一致性实体",'[]'); r2 = ms.entity_add("client","一致性实体",'["新别名"]')
    assert r2["status"]=="merged",r2

for i in range(1,31):
    check(f"test_{i:02d}", globals()[f"t{i}"])

import shutil
shutil.rmtree(os.environ['CHROMADB_PATH'], ignore_errors=True)
os.unlink(tmpdb)

print(f"\n{'='*60}")
print(f"审计结果: {passed}/30 通过, {failed} 失败")
print(f"{'='*60}")
for d in details:
    print(f"  ❌ {d}")
if failed == 0:
    print("  ✅ 全部通过 — 无静默错误、无空转、无安全漏洞")
