---
title: "Building a 4-Layer Memory Engine for AI Agents: Beyond Simple RAG"
published: false
description: "How we built Memory Engine — an open-source, 4-layer persistent memory system for AI agents with zero external database dependencies."
tags: [ai, agents, machine-learning, python, opensource]
canonical_url: https://github.com/qq1009128320-dotcom/memory-engine
---

# Building a 4-Layer Memory Engine for AI Agents: Beyond Simple RAG

**TL;DR:** We built an open-source memory engine for AI agents with 4 specialized layers — Memory Tree (vector search), Preferences (learned rules), Error Memory (never repeat mistakes), and Knowledge Graph (entity relationships). It runs on SQLite + FAISS, exposes 22 MCP tools, and requires zero external databases. [GitHub](https://github.com/qq1009128320-dotcom/memory-engine)

---

## The Problem: Agents Have Amnesia

Every AI conversation starts from scratch. You tell your coding assistant your project structure. Next session, it's forgotten. You correct a data analysis agent about which field to use. Next report, same mistake.

This isn't just inconvenient — it's a fundamental limitation. Current agent memory solutions fall into two camps:

1. **Context window stuffing** — works for one conversation, resets after
2. **Vector databases** — stores chunks, retrieves by similarity, but doesn't *learn*

What's missing is a memory system that **learns from corrections**, **remembers mistakes**, and **accumulates domain knowledge** over time.

## Existing Solutions (and Their Gaps)

| System | Layers | Learns | Self-Hosted | Error Memory |
|--------|--------|--------|-------------|--------------|
| **Mem0** (60K⭐) | 2 | ❌ | ❌ (cloud) | ❌ |
| **agentmemory** (24K⭐) | 1 | ❌ | ✅ | ❌ |
| **Zep** (4.7K⭐) | 2 | ❌ | Limited | ❌ |
| **Letta** (19K⭐) | 1 | ❌ | ❌ (cloud) | ❌ |

Every existing system stores and retrieves. None of them **learn**.

## Our Approach: 4 Specialized Layers

Instead of one monolithic memory store, we split memory into four layers, each optimized for a specific purpose.

### Layer 1: Memory Tree — The Knowledge Base

The foundation. Ingest documents, policies, and data. Retrieves via:
- **FAISS vector search** (384-dim, all-MiniLM-L6-v2) — semantic similarity in ~3ms
- **Keyword fallback** — SQLite LIKE for exact matches
- **Hierarchical summaries** — L0 (global stats) → L1 (grouped topics) → L2 (raw blocks)

**Cold start:** ~500ms (model load) | **Hot query:** ~3ms

### Layer 2: Preferences — The Rule Book

When a user corrects the agent ("Use the `amt_jpy` field, not `base_amt`"), that correction is automatically extracted and saved as a **preference rule**. Next time the agent queries financial data, it knows which field to use.

Categories: `field_alias`, `date_rule`, `naming`, `policy`, `format`

### Layer 3: Error Memory — The Differentiator

**No competitor has this.** When an agent makes a mistake and the user corrects it, we log:
- What went wrong (`error_category`)
- How to fix it (`correction`)
- Severity (`minor` / `major` / `critical`)

If the **same error happens 3+ times**, it's **automatically promoted** to a permanent preference rule. The agent literally gets smarter with every mistake.

Before every task, the agent calls `error_check()` — if similar tasks have failed before, it sees the past mistake and avoids repeating it.

### Layer 4: Knowledge Graph — The Org Chart

Entity-relationship management for enterprise context: departments, clients, policies, people. Three-tier permissions (personal / department / enterprise).

## Why SQLite + FAISS (Not ChromaDB or Pinecone)

| Factor | SQLite + FAISS | ChromaDB | Cloud Vector DB |
|--------|----------------|----------|-----------------|
| External dependencies | **0** | 1 (ChromaDB) | 3+ (cloud infra) |
| Cold start time | **~2s** | ~10s | ~30s + network |
| Self-hosted | ✅ | ✅ | ❌ |
| Offline capable | ✅ | ✅ | ❌ |
| Vector search speed | **~3ms** | ~10ms | ~50ms (network) |
| Deployment complexity | **git clone + pip install** | pip install + configure | sign up + API keys |

## Results: 22 MCP Tools, 84 Tests Passing

The engine exposes 22 tools via the Model Context Protocol (MCP), making it compatible with any MCP-compatible agent — Hermes, Claude Code, Codex CLI, or custom builds.

```
Memory Tree (L1):       ingest, vector_search, search, fetch, score, delete, reindex, summary
Preferences (L2):       add, search, list, disable
Error Memory (L3):      check, log, list, delete
Knowledge Graph (L4):   entity_add, entity_search, entity_link, graph_query
Cross-layer:            memory_search, memory_stats, memory_health
```

## Production Hardening

- FAISS concurrent write lock (thread-safe)
- Request rate limiting (BoundedSemaphore 50)
- Log rotation + API key redaction
- WAL auto-checkpoint (every 5 min)
- Daily backup with integrity check → gzip → 30-day retention
- OOM protection (systemd MemoryMax)
- Docker multi-stage build (non-root user)
- 30-point comprehensive audit built-in

## Getting Started (30 seconds)

```bash
git clone https://github.com/qq1009128320-dotcom/memory-engine.git
cd memory-engine
pip install -r requirements.txt
python3 -c "from memory_server import _init_db; _init_db()"
python3 memory_server.py
```

Connect from any MCP-compatible agent:

```yaml
mcp_servers:
  enterprise-memory:
    command: /path/to/venv/bin/python3
    args: ["/path/to/memory_server.py"]
```

## Is It Production Ready?

Yes. We run it in production. The audit system checks 30 different health metrics. The deployment includes Docker, systemd, and a one-click deploy script.

## What's Next?

- **v2.3:** English docs complete, GitHub Pages site, benchmark suite
- **v2.4:** Multi-agent memory coordination (ShadowClone-X)
- **v3.0:** Milvus production deploy, horizontal scaling, enterprise SSO

## Try It

The entire engine is **MIT licensed** and available on GitHub:

**[github.com/qq1009128320-dotcom/memory-engine](https://github.com/qq1009128320-dotcom/memory-engine)**

If you find it useful, consider giving it a star. If you have questions, open an issue. If you need enterprise support, contact us.

---

*Memory Engine: Correct it once. It remembers forever.*
