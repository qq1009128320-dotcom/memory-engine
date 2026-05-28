#!/usr/bin/env python3
"""记忆系统四层能力实测"""
import sys
sys.path.insert(0, '.')
import json as _j

from memory_server import (
    memory_tree_ingest,
    memory_tree_vector_search,
    memory_tree_search,
    memory_tree_fetch,
    memory_tree_summary,
    memory_search,
    preference_add,
    preference_search,
    preference_list,
    error_check,
    error_log,
    error_list,
    entity_add,
    entity_search,
    entity_link,
    graph_query,
    memory_stats,
    memory_health,
)

SEP = "=" * 60

# ============================================================
# 1. INGEST: 录入测试数据
# ============================================================
print(f"{SEP}\n1. INGEST 录入测试文档\n{SEP}")
r = memory_tree_ingest(
    source="test:demo",
    source_type="doc",
    title="2026年度研发预算",
    content="2026年公司AI部门研发预算为3000万元，大模型训练1800万，推理服务700万，数据标注500万。研发人员编制60人。",
    metadata=_j.dumps({"department": "AI研发部", "year": "2026"}),
)
print(f"  结果: {r}")

# ============================================================
# 2. 向量语义搜索
# ============================================================
print(f"\n{SEP}\n2. 向量语义搜索 (memory_tree_vector_search)\n{SEP}")
r = memory_tree_vector_search(query="大模型训练需要多少钱", max_results=3)
for i, item in enumerate(r):
    print(f"  #{i+1} [{item['score']:.3f}] {item['title']}")

# ============================================================
# 3. 关键词搜索
# ============================================================
print(f"\n{SEP}\n3. 关键词搜索 (memory_tree_search)\n{SEP}")
r = memory_tree_search(query="研发 预算", max_results=5)
for i, item in enumerate(r):
    content = item.get('content', '')[:60]
    print(f"  #{i+1} [{item.get('score', 0)}] {item['title']}: {content}")

# ============================================================
# 4. 获取完整内容
# ============================================================
print(f"\n{SEP}\n4. 获取完整内容 (memory_tree_fetch)\n{SEP}")
if r:
    doc_id = r[0]['id']
    doc = memory_tree_fetch(id=doc_id)
    if doc:
        print(f"  id: {doc['id']}")
        print(f"  title: {doc['title']}")
        print(f"  content: {doc['content']}")
        print(f"  source: {doc['source']}")

# ============================================================
# 5. 跨层综合检索
# ============================================================
print(f"\n{SEP}\n5. 跨层综合检索 (memory_search)\n{SEP}")
r = memory_search(query="研发预算 财务政策", layers="all", max_results=5)
for layer in ['memory_tree', 'preferences', 'errors', 'graph']:
    items = r.get(layer, [])
    print(f"  [{layer}] {len(items)} 条")
    for item in items[:2]:
        if isinstance(item, dict):
            title = item.get('title', item.get('category', item.get('name', item.get('task_type', '?'))))
            print(f"    - {title}")

# ============================================================
# 6. 偏好记忆
# ============================================================
print(f"\n{SEP}\n6. 偏好记忆层 (preferences)\n{SEP}")
rules = preference_list(scope="all")
print(f"  共 {len(rules)} 条偏好规则:")
cats = {}
for p in rules:
    cats[p['category']] = cats.get(p['category'], 0) + 1
for cat, cnt in sorted(cats.items()):
    print(f"    {cat}: {cnt} 条")

# 搜索偏好
print(f"\n  搜索 '金额':")
r = preference_search(query="金额")
for p in r[:3]:
    print(f"    [{p['category']}] {p['condition']} → {p['rule'][:80]}")

# ============================================================
# 7. 纠错记忆
# ============================================================
print(f"\n{SEP}\n7. 纠错记忆层 (errors)\n{SEP}")
errs = error_list()
print(f"  未解决错误: {len(errs)} 条")
for e in errs[:5]:
    print(f"    [{e['severity']}] {e['task_type']}: {e['mistake_description'][:70]}")

# 错误检查
print(f"\n  检查 'data_query' 类型任务:")
r = error_check(task_type="data_query")
if r:
    for e in r[:2]:
        print(f"    ⚠ {e.get('mistake_description', '')[:80]}")
        print(f"    ✅ 正确做法: {e.get('correction', '')[:80]}")
else:
    print(f"    无相关错误记录")

# ============================================================
# 8. 知识图谱
# ============================================================
print(f"\n{SEP}\n8. 知识图谱层 (graph)\n{SEP}")
ents = entity_search(query="", type="", max_results=20)
print(f"  实体总数: {len(ents)}")
for e in ents:
    aliases = e.get('aliases', '')
    if isinstance(aliases, str) and aliases:
        aliases = f" ({aliases})"
    print(f"    [{e['type']}] {e['name']}{aliases}")

# 查关系图
if ents:
    name = ents[0]['name']
    print(f"\n  查询 '{name}' 的关系图:")
    g = graph_query(entity_name=name)
    if 'error' in g:
        print(f"    {g['error']}")
    else:
        for rel in g.get('relationships', []):
            print(f"    {rel['source']} --[{rel['relation']}]--> {rel['target']}")

# ============================================================
# 9. 摘要树
# ============================================================
print(f"\n{SEP}\n9. 层级摘要树 (summary_tree)\n{SEP}")
r = memory_tree_summary(level="all")
for k, v in r.items():
    if isinstance(v, str):
        print(f"  {k}: {v[:120]}...")
    elif isinstance(v, list):
        print(f"  {k}: {len(v)} 条")

# ============================================================
# 10. 统计和健康
# ============================================================
print(f"\n{SEP}\n10. 统计 & 健康\n{SEP}")
stats = memory_stats()
for k, v in stats.items():
    print(f"  {k}: {v}")

print(f"\n  Health:")
h = memory_health()
print(f"    status: {h.get('status', '?')}")
print(f"    db_ok: {h.get('database', '?')}")

print(f"\n{SEP}\n全部 10 项测试完成\n{SEP}")
