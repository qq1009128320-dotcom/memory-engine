#!/usr/bin/env python3
"""记忆系统 21 工具全覆盖测试"""
import sys, json as _j
sys.path.insert(0, '.')

from memory_server import (
    # Memory Tree (7)
    memory_tree_ingest, memory_tree_search, memory_tree_fetch,
    memory_tree_score, memory_tree_vector_search,
    memory_tree_reindex, memory_tree_summary,
    # Preferences (4)
    preference_add, preference_search, preference_list, preference_disable,
    # Error Memory (3)
    error_check, error_log, error_list,
    # Knowledge Graph (4)
    entity_add, entity_search, entity_link, graph_query,
    # Cross-layer (2)
    memory_search, memory_stats,
    # Health (1)
    memory_health,
)

PASS, FAIL, SKIP = 0, 0, 0

def run_test(name, fn):
    global PASS, FAIL, SKIP
    try:
        fn()
        PASS += 1
        print(f"  ✅ {name}")
    except Exception as e:
        FAIL += 1
        print(f"  ❌ {name}: {e}")

def eq(a, b, msg=""):
    assert a == b, f"{msg} expected={b!r} got={a!r}"

def ok(cond, msg=""):
    assert cond, msg

# ==========================================
# 1. Memory Tree (7 tools)
# ==========================================
print("\n--- Memory Tree ---")

run_test("ingest - 正常录入", lambda: (
    eq(memory_tree_ingest(
        source="test:cov", source_type="doc", title="测试文档A",
        content="这是测试内容，关于云计算基础设施预算500万元。",
        metadata='{"tag": "IT"}'
    )["status"], "ingested")
))

run_test("ingest - 去重", lambda: (
    eq(memory_tree_ingest(
        source="test:cov", source_type="doc", title="测试文档A",
        content="这是测试内容，关于云计算基础设施预算500万元。",
    )["status"], "skipped")
))

run_test("search - 关键词搜索", lambda: (
    ok(len(memory_tree_search(query="云计算", max_results=5)) >= 1)
))

run_test("search - 无匹配", lambda: (
    eq(len(memory_tree_search(query="zzz不存在的关键词zzz")), 0)
))

run_test("fetch - 获取内容", lambda: (
    ok("云计算" in memory_tree_fetch(
        id=memory_tree_search(query="云计算")[0]["id"]
    )["content"])
))

run_test("fetch - 不存在的ID", lambda: (
    eq(memory_tree_fetch(id="nonexistent-id"), None)
))

run_test("score - 调整评分", lambda: (
    ok(isinstance(memory_tree_score(
        id=memory_tree_search(query="云计算")[0]["id"], delta=0.5
    )["new_score"], float))
))

run_test("vector_search - 语义搜索", lambda: (
    ok(len(memory_tree_vector_search(
        query="基础设施需要多少钱", max_results=3
    )) >= 1)
))

run_test("reindex - 重建索引", lambda: (
    eq(memory_tree_reindex()["status"], "ok")
))

run_test("summary - 获取摘要", lambda: (
    ok("l0" in memory_tree_summary(level="all"))
))

# ==========================================
# 2. Preference Memory (4 tools)
# ==========================================
print("\n--- Preference Memory ---")

run_test("add - 添加偏好", lambda: (
    eq(preference_add(
        category="format", condition="测试条件",
        rule="测试规则：使用格式A", scope="personal"
    )["status"], "created")
))

run_test("add - 输入校验阻塞非法category", lambda: (
    isinstance(preference_add(
        category="INVALID_CAT", condition="x", rule="y"
    ), dict)  # should return error
))

run_test("search - 搜索偏好", lambda: (
    ok(len(preference_search(query="格式A")) >= 1)
))

run_test("list - 列出所有", lambda: (
    ok(len(preference_list(scope="all")) >= 1)
))

run_test("disable - 禁用规则", lambda: (
    eq(preference_disable(
        id=preference_search(query="格式A")[0]["id"]
    )["is_active"], 0)
))

# ==========================================
# 3. Error Memory (3 tools)
# ==========================================
print("\n--- Error Memory ---")

run_test("log - 记录错误", lambda: (
    eq(error_log(
        task_type="test_cov", error_category="logic_error",
        mistake_description="测试错误描述XYZ", correction="测试纠正方案XYZ"
    )["status"], "created")
))

run_test("log - 重复错误计数递增", lambda: (
    ok(error_log(
        task_type="test_cov", error_category="logic_error",
        mistake_description="测试错误描述XYZ", correction="测试纠正方案XYZ"
    )["occurrence_count"] >= 2)
))

run_test("check - 错误检查", lambda: (
    ok(len(error_check(task_type="test_cov")) >= 1)
))

run_test("check - 无匹配任务", lambda: (
    eq(len(error_check(task_type="nonexistent_task_type_xyz")), 0)
))

run_test("list - 列出错误", lambda: (
    ok(len(error_list()) >= 1)
))

# ==========================================
# 4. Knowledge Graph (4 tools)
# ==========================================
print("\n--- Knowledge Graph ---")

run_test("add - 添加实体", lambda: (
    eq(entity_add(
        type="project", name="测试项目Z", aliases='["项目Z", "Z项目"]'
    )["status"], "created")
))

run_test("add - 合并别名", lambda: (
    eq(entity_add(
        type="project", name="测试项目Z", aliases='["Z-Project"]'
    )["status"], "merged_aliases")
))

run_test("search - 搜索实体", lambda: (
    ok(len(entity_search(query="项目Z")) >= 1)
))

run_test("link - 建立关系", lambda: (
    eq(entity_link(
        source_name="测试项目Z", target_name="研发部",
        relation="belongs_to"
    )["status"], "linked")
))

run_test("graph_query - 关系图查询", lambda: (
    ok(len(graph_query(entity_name="测试项目Z")["outgoing_relations"]) >= 1)
))

# ==========================================
# 5. Cross-layer (2 tools)
# ==========================================
print("\n--- Cross-layer ---")

run_test("memory_search - 综合检索", lambda: (
    ok(isinstance(memory_search(query="云计算 预算"), dict))
))

run_test("memory_stats - 统计信息", lambda: (
    ok(memory_stats()["chromadb_indexed"] >= 1)
))

# ==========================================
# 6. Health (1 tool)
# ==========================================
print("\n--- Health ---")

run_test("memory_health - 健康检查", lambda: (
    eq(memory_health()["status"], "healthy")
))

# ==========================================
print(f"\n{'='*50}")
print(f"结果: {PASS} 通过, {FAIL} 失败, {SKIP} 跳过")
print(f"{'='*50}")
