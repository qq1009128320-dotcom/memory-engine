# Architecture

> Memory Engine is a **4-layer persistent memory system** for AI agents, exposed via the Model Context Protocol (MCP).

## Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     AI Agent (Any MCP Client)                │
│  Hermes Agent · Claude Code · Codex CLI · Custom Agent      │
└──────────────────────────┬──────────────────────────────────┘
                           │ MCP Protocol (stdio / HTTP)
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                   🔌 MCP Server (22 Tools)                    │
│    memory_server.py — FastMCP-based, multi-threaded           │
├──────────┬──────────┬──────────────┬─────────────────────────┤
│  L1      │  L2      │  L3          │  L4                     │
│ Memory   │ Prefer-  │  Error       │  Knowledge              │
│ Tree     │ ences    │  Memory      │  Graph                  │
│          │          │              │                         │
│ FAISS    │ SQLite   │ SQLite       │ SQLite                  │
│ Vector   │ Key-Val  │ Error Log    │ Entity-Relationship     │
│ Index    │ Rules    │ + Auto-      │ + 3-Tier Permissions     │
│          │          │  Upgrade     │                         │
└──────────┴──────────┴──────────────┴─────────────────────────┘
                           │
                           ▼
              ┌───────────────────────┐
              │     🗄️ SQLite DB       │
              │  (6 tables, WAL mode)  │
              └───────────────────────┘
```

## Layer Details

### Layer 1: Memory Tree

The primary external data storage layer. Designed for ingesting documents, policies, and structured data.

- **Storage:** SQLite table `memory_tree` with FAISS vector index (384-dim, all-MiniLM-L6-v2)
- **Search:** Hybrid — semantic vector search (FAISS IVFFlat) + keyword fallback (SQLite LIKE)
- **Hierarchical Summaries:** L0 (global stats) → L1 (grouped topics) → L2 (raw blocks)
- **Deduplication:** SHA256 content hash prevents duplicate ingestion
- **Scoring:** Relevance scoring system; frequently retrieved items rank higher

### Layer 2: Preferences

Learns user rules and habits from corrections. The "gets smarter over time" layer.

- **Storage:** SQLite table `preference_memory`
- **Categories:** `field_alias`, `date_rule`, `naming`, `policy`, `format`
- **Scopes:** Personal, department, or enterprise-wide
- **Confidence scoring:** Rules start at 0.8 confidence; user confirmation increases it
- **Auto-extraction:** extract_facts.py detects corrections in conversation and auto-creates preferences

### Layer 3: Error Memory (原创)

Prevents agents from repeating mistakes. The most unique layer.

- **Storage:** SQLite table `error_memory`
- **Categories:** `field_selection`, `logic_error`, `scope_error`, `omission`
- **Auto-upgrade:** Same error ≥3 times → automatically promoted to a permanent preference rule
- **Prevention:** `error_check()` is called before every task to surface past failures

### Layer 4: Knowledge Graph

Manages entities and relationships for enterprise context.

- **Storage:** SQLite tables `entities` + `entity_relations`
- **Entity types:** `person`, `department`, `client`, `policy`, `document`, `field`, `project`
- **Relations:** `belongs_to`, `manages`, `alias_of`, `depends_on`, `owns`, `approves`, `works_in`
- **Permissions:** 3-tier (personal, department, enterprise)
- **Auto-extraction:** run_extraction.py parses conversations for entity relationships

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **SQLite + FAISS** (not ChromaDB) | Zero external dependencies, simpler deployment, faster cold start |
| **FAISS IVFFlat** (not HNSW) | Better memory/speed tradeoff for < 1M vectors |
| **MCP Protocol** (not custom API) | Universal agent compatibility — any MCP client can connect |
| **Multi-threaded** (not async) | FAISS operations are CPU-bound; threading is more predictable |
| **Error auto-upgrade** | Key differentiator — no competitor has learned-from-mistakes |
| **22 tools, not 5** | Each layer needs full CRUD; too-few tools means agent can't operate autonomously |
