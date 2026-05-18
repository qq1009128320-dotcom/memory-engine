#!/usr/bin/env python3
"""
层级摘要树 — 将 Memory Tree 的零散块聚合成 L0/L1/L2 层级

使用方式:
  python3 summary_tree.py              # 生成全部层级摘要
  python3 summary_tree.py --rebuild    # 重建所有摘要
"""

import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from config import DB_PATH, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
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


def call_llm(prompt: str, max_tokens: int = 1024) -> str:
    if not LLM_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 未设置")

    import httpx
    response = httpx.post(
        f"{LLM_BASE_URL}/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": "你是一个精确的知识摘要器。只输出摘要文本。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": max_tokens,
        },
        timeout=LLM_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# 分组逻辑
# ---------------------------------------------------------------------------

def _group_chunks(chunks: list[dict]) -> dict[str, list[dict]]:
    """将 chunk 按 source_type 分组，再按内容相似度细分。"""
    groups: dict[str, list[dict]] = {}

    for c in chunks:
        st = c.get("source_type", "unknown")
        title = c.get("title", "")

        # 用 source_type + 标题前几个字做简单分组
        group_key = st
        if title:
            # 尝试用标题关键字进一步分组
            keywords = ["财务", "制度", "政策", "客户", "研发", "行政", "人事", "合同"]
            for kw in keywords:
                if kw in title:
                    group_key = f"{st}:{kw}"
                    break

        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(c)

    return groups


# ---------------------------------------------------------------------------
# 摘要生成
# ---------------------------------------------------------------------------

def build_summary_tree(rebuild: bool = False) -> dict:
    """构建 L0/L1 层级摘要树。"""
    with _get_conn() as conn:
        # 获取所有未分组的 chunk（parent_id 为 NULL）
        where = "" if rebuild else "WHERE parent_id IS NULL AND (summary IS NULL OR summary = '')"
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

            try:
                l1_summary = call_llm(
                    SUMMARIZE_L1_PROMPT.format(docs=docs_text), max_tokens=800
                )
            except Exception as e:
                l1_summary = f"[LLM 摘要生成失败: {e}]"

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

        try:
            l0_summary = call_llm(
                SUMMARIZE_L0_PROMPT.format(summaries=all_l1_text), max_tokens=400
            )
        except Exception as e:
            l0_summary = f"[LLM 摘要生成失败: {e}]"

        # 存储 L0 摘要到数据库（作为一个特殊的 chunk）
        import uuid, hashlib
        l0_id = str(uuid.uuid4())
        l0_hash = hashlib.sha256(l0_summary.encode()).hexdigest()[:16]
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
