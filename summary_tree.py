#!/usr/bin/env python3
"""
层级摘要树 — 将 Memory Tree 的零散块聚合成 L0/L1/L2 层级

使用方式:
  python3 summary_tree.py              # 生成全部层级摘要
  python3 summary_tree.py --rebuild    # 重建所有摘要
"""

import json
import logging
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from config import DB_PATH, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT
from utils import now as _now, sha256

# 使用 memory_engine 命名空间的 logger，自动启用脱敏过滤器
logger = logging.getLogger("memory_engine.summary_tree")


def _get_conn() -> sqlite3.Connection:
    """获取 SQLite 连接并应用完整优化配置。"""
    conn = sqlite3.connect(str(DB_PATH), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-128000")  # 128MB
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=134217728")  # 128MB
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA page_size=4096")
    return conn


# ---------------------------------------------------------------------------
# LLM 摘要生成
# ---------------------------------------------------------------------------

SUMMARIZE_L1_PROMPT = """你是一个企业知识系统。以下是同一主题下的多个文档片段。
请生成一个简洁的组级摘要(不超过500字)，覆盖：
1. 这组文档涉及哪些主题
2. 关键规则/政策/数据点
3. 如果 Agent 需要回答相关问题，应该知道什么

文档片段:
{docs}

输出纯文本摘要(不要 markdown):"""

SUMMARIZE_L0_PROMPT = """你是一个企业知识系统。以下是多个主题组的摘要。
请生成一个全局概览(不超过200字)：
1. 当前知识库覆盖哪些领域
2. 最重要的规则或制度是什么
3. Agent 回答问题时应该优先关注什么

主题组摘要:
{summaries}

输出纯文本(不要 markdown):"""


def _llm_summarize(prompt: str, max_tokens: int = 1024) -> str:
    """Call LLM for summarization (thin wrapper around shared client)."""
    from llm_client import call_llm
    return call_llm(
        prompt,
        system_prompt="你是一个精确的知识摘要器。只输出摘要文本。",
        max_tokens=max_tokens,
        temperature=0.3,
    )


# ---------------------------------------------------------------------------
# 分组逻辑
# ---------------------------------------------------------------------------

# P2-3 修复: 可配置的分组关键词，支持自定义领域
DEFAULT_GROUP_KEYWORDS = [
    "财务", "制度", "政策", "客户", "研发", "行政", "人事", "合同",
    "预算", "费用", "报销", "采购", "销售", "项目", "会议", "培训",
]


def _group_chunks(chunks: list[dict], keywords: list[str] | None = None) -> dict[str, list[dict]]:
    """将 chunk 按 source_type 分组，再按标题关键字细分。

    P2-3 修复: 支持自定义关键词列表，改进分组逻辑。
    """
    keywords = keywords or DEFAULT_GROUP_KEYWORDS
    groups: dict[str, list[dict]] = {}

    for c in chunks:
        st = c.get("source_type", "unknown")
        title = c.get("title", "")

        # 用 source_type + 标题关键字做分组
        group_key = st
        if title:
            # 尝试用标题关键字进一步分组（优先匹配较长的关键词）
            for kw in sorted(keywords, key=len, reverse=True):
                if kw in title:
                    group_key = f"{st}:{kw}"
                    break

        # P2-3 修复: 处理无关键词匹配的情况，归入默认组
        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(c)

    # P2-3 修复: 过滤掉空组
    groups = {k: v for k, v in groups.items() if v}

    return groups


# ---------------------------------------------------------------------------
# 摘要生成
# ---------------------------------------------------------------------------

def build_summary_tree(rebuild: bool = False) -> dict:
    """构建 L0/L1 层级摘要树。"""
    with _get_conn() as conn:
        # 获取所有未分组的 chunk（parent_id 为 NULL）
        # 排除已经是摘要节点本身（source_type='summary'），避免摘要的摘要
        if rebuild:
            where = "WHERE source_type != 'summary'"
        else:
            where = "WHERE source_type != 'summary' AND parent_id IS NULL AND (summary IS NULL OR summary = '')"
        # P1-2: where 为硬编码白名单字符串，非用户输入，SQL 注入风险可控
        chunks = conn.execute(
            f"SELECT id, source_type, title, content FROM memory_tree_chunks {where} ORDER BY source_type, title"
        ).fetchall()

        if not chunks:
            return {"status": "empty", "message": "没有需要摘要的数据"}

        chunk_dicts = [dict(c) for c in chunks]
        groups = _group_chunks(chunk_dicts)

        print(f"📊 {len(chunks)} 个块 → {len(groups)} 个分组")

        l1_summaries = []
        l1_total = len(groups)

        # 生成 L1 摘要
        for group_key, group_chunks in groups.items():
            print(f"  🔹 处理分组: {group_key} ({len(group_chunks)} 块)")

            # 拼接文档内容（每个块最多 2000 字）
            docs_text = "\n---\n".join(
                f"[{c['title']}]\n{c['content'][:2000]}" for c in group_chunks
            )

            # P2-⑥ 修复: LLM 摘要失败时生成默认摘要，避免数据丢失
            try:
                l1_summary = _llm_summarize(
                    SUMMARIZE_L1_PROMPT.format(docs=docs_text), max_tokens=800
                )
            except Exception as e:
                logger.warning("LLM 摘要生成失败，使用默认摘要 for %s: %s", group_key, e)
                # 生成默认摘要：列出该组包含的文档标题
                titles = [c.get('title', '无标题') for c in group_chunks if c.get('title')]
                l1_summary = f"[自动摘要生成失败] 本组包含 {len(group_chunks)} 个文档: {', '.join(titles[:5])}"

            l1_summaries.append({"group": group_key, "summary": l1_summary, "count": len(group_chunks)})

            # 更新每个 chunk 的 parent_id 和 summary
            group_parent_id = f"l1:{group_key}"
            for c in group_chunks:
                conn.execute(
                    "UPDATE memory_tree_chunks SET parent_id = ?, summary = ? WHERE id = ?",
                    (group_parent_id, l1_summary, c["id"]),
                )

            print(f"     ✅ L1 摘要生成完毕")

        # 生成 L0 全局摘要
        print(f"  🌐 生成 L0 全局摘要...")
        all_l1_text = "\n---\n".join(
            f"分组[{s['group']}]({s['count']}块): {s['summary']}" for s in l1_summaries
        )

        # P2-⑦ 修复: L0 摘要失败时使用通用占位文本，不暴露内部错误细节
        try:
            l0_summary = _llm_summarize(
                SUMMARIZE_L0_PROMPT.format(summaries=all_l1_text), max_tokens=400
            )
        except Exception as e:
            logger.warning("L0 全局摘要生成失败: %s", e)
            l0_summary = "[全局摘要生成中，请稍后查看]"

        # 存储 L0 摘要到数据库（作为一个特殊的 chunk）
        import uuid, hashlib
        l0_id = str(uuid.uuid4())
        l0_hash = sha256(l0_summary)[:16]
        existing_l0 = conn.execute(
            "SELECT id FROM memory_tree_chunks WHERE source_type = 'summary' AND title = 'L0_全局概览'"
        ).fetchone()
        if existing_l0:
            conn.execute(
                "UPDATE memory_tree_chunks SET content = ?, content_hash = ?, updated_at = ? WHERE id = ?",
                (l0_summary, l0_hash, _now(), existing_l0["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO memory_tree_chunks (id, source, source_type, title, content, content_hash, score, parent_id, summary)
                   VALUES (?, 'system', 'summary', 'L0_全局概览', ?, ?, 1.0, NULL, ?)""",
                (l0_id, l0_summary, l0_hash, l0_summary),
            )

        conn.commit()

    return {
        "status": "ok",
        "l0_summary": l0_summary,
        "l1_groups": len(l1_summaries),
        "total_chunks": len(chunks),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    rebuild = "--rebuild" in sys.argv
    result = build_summary_tree(rebuild=rebuild)
    if result["status"] == "ok":
        print(f"\n✅ 摘要树构建完成")
        print(f"   L0 全局: {result['l0_summary'][:100]}...")
        print(f"   L1 分组: {result['l1_groups']} 个")
        print(f"   覆盖块: {result['total_chunks']} 个")
    else:
        print(f"⚠️  {result['message']}")
