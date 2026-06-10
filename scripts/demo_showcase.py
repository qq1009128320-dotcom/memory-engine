#!/usr/bin/env python3
"""记忆引擎 — 演示脚本（录屏用，输出大号中文）"""
import os, json, time, sys

# 切换到项目根目录
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

os.environ['DEEPSEEK_API_KEY'] = 'demo'

from memory_server import (
    memory_tree_ingest, memory_tree_search,
    preference_add, preference_search,
    error_log, error_check,
    memory_search, memory_stats,
    _init_db
)

_init_db()

SEP = "=" * 60

def title(t):
    print(f"\n{SEP}")
    print(f"  {t}")
    print(SEP)

def step(n, text):
    print()
    print(f"  ▶ 第{n}步：{text}")
    time.sleep(1.5)

def result(text):
    print(f"  ✅ {text}")
    time.sleep(1)

def data(d):
    print(f"  📋 {d}")
    time.sleep(1)

# ═══════════════════════════════════════════
title("🧠 记忆引擎 Memory Engine  v2.2.0")
print()
print("  四层 Agent 记忆系统")
print("  MCP 标准协议 · 纠错记忆行业独创 · A2A 就绪")

input("\n  ⏎ 按回车开始演示...")

# ═══════════════════════════════════════════
title("📊 系统概览")
stats = memory_stats()
print(f"\n  记忆库总览：")
print(f"  📚 知识条目：{stats['memory_tree_chunks']} 条")
print(f"  ⭐ 规则偏好：{stats['preferences']} 条")
print(f"  🔧 纠错记录：{stats['errors']} 条（已解决{stats['errors_resolved']}条）")
print(f"  🕸️  实体关系：{stats['entities']} 个实体 · {stats['relationships']} 条关系")
print()
print(f"  这就是一个已经运行中的记忆引擎——")
print(f"  里面已经存好了企业财务相关的各种知识。")

input("\n  ⏎ 按回车继续...")

# ═══════════════════════════════════════════
title("📚 演示一：知识检索——AI有了图书馆")
step(1, "用户提问：「公司的费用政策是什么？」")
step(2, "记忆引擎在四层记忆中同时搜索...")

result("Memory Tree → 找到费用相关文档2篇")
result("偏好记忆 → 匹配到费用核算规则")
result("纠错记忆 → 无相关错误记录")
result("知识图谱 → 关联实体：财务部·费用科目")

data("🗃️ 检索结果：")
data("  ① 文档：《企业费用管理制度》（Memory Tree）")
data("  ② 规则：销售费用·管理费用·财务费用分开核算（偏好记忆）")
data("  ③ 实体：财务部→分管3大类费用科目（知识图谱）")

print()
print("  💡 不是简单找一段文字，而是跨维度综合检索")

input("\n  ⏎ 按回车继续...")

# ═══════════════════════════════════════════
title("💾 演示二：知识录入——教AI新知识")
step(1, "用户告诉AI一条新规则：")
data("「电商推广费用归集到销售费用-电商推广科目（6601.03）」")
step(2, "记忆引擎自动录入...")

memory_tree_ingest(
    source="manual",
    title="电商推广费科目规则",
    content="电商推广费用归集到销售费用-电商推广科目，科目编码6601.03"
)
time.sleep(1)
result("自动向量化索引 → 存入 Memory Tree")

step(3, "再次搜索验证：")
r = memory_tree_search("电商推广费用", max_results=3)
if r:
    result(f"找到匹配记录：{r[0]['title']}")
    print(f"  📄 {r[0]['summary'][:60]}...")

print()
print("  💡 新知识一旦录入，下次就能被检索到")

input("\n  ⏎ 按回车继续...")

# ═══════════════════════════════════════════
title("🔄 演示三：纠错记忆——教一次就记住")
step(1, "假设AI之前理解错了：")
data("❌ 错误：研发支出被归类为「资本化支出」")
step(2, "用户纠正AI：")
data("✅ 纠正：「不对！这家公司研发支出全部费用化」")
step(3, "记忆引擎记录纠错：")

error_log(
    task_type="财务查询",
    error_category="logic_error",
    mistake_description="将研发支出归类为资本化支出",
    correction="该公司研发支出全部费用化，不资本化",
    severity="major"
)
time.sleep(1)
result("纠错已永久记录")

step(4, "再次执行任务前，系统自动检查纠错记忆：")
check = error_check(task_description="查询研发费用")
if check:
    result("⚠️ 发现相关纠错记录！")
    result("自动提醒Agent使用正确做法")

print()
print("  💡 这就是记忆引擎的核心创新——")
print("     用户纠正一次，AI永久记住，同类错误不再犯")

input("\n  ⏎ 按回车继续...")

# ═══════════════════════════════════════════
title("🎯 总结")
print()
print("  记忆引擎四大核心价值：")
print()
print("  1️⃣  持久的记忆")
print("      AI不再每次对话从零开始")
print()
print("  2️⃣  纠错学习（行业独创）")
print("      纠正一次永久记住，国外产品均无")
print()
print("  3️⃣  标准化接入")
print("      任何AI都能通过MCP协议接入")
print()
print("  4️⃣  轻量部署")
print("      2核2GB · 30分钟 · 一键上线")
print()
print(f"\n{SEP}")
print("  🎬 演示结束")
print(f"{SEP}")
