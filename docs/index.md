---
layout: default
---

# Memory Engine

> **4-layer persistent memory for AI agents via MCP.**  
> Correct it once. It remembers forever.

[![CI](https://github.com/qq1009128320-dotcom/memory-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/qq1009128320-dotcom/memory-engine/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

---

## Why Memory Engine?

Every AI conversation starts from scratch — until now. Memory Engine gives your agent persistent memory across sessions, organized in **four specialized layers**.

| Traditional AI | With Memory Engine |
|---|---|
| Resets every conversation | Remembers across sessions |
| Makes the same mistakes repeatedly | Learns from corrections automatically |
| You re-explain context every time | Auto-retrieves relevant memories |
| Zero domain knowledge accumulation | Continuously learns your rules |

## Quick Start (30 seconds)

```bash
git clone https://github.com/qq1009128320-dotcom/memory-engine.git
cd memory-engine
pip install -r requirements.txt
python3 -c "from memory_server import _init_db; _init_db()"
python3 memory_server.py
```

## The 4 Memory Layers

| Layer | Name | What It Does | Uniqueness |
|-------|------|-------------|------------|
| **L1** | Memory Tree | Vector search + hierarchical summaries | FAISS-powered, <3ms hot query |
| **L2** | Preferences | Learns rules from user corrections | Auto-extracts from conversations |
| **L3** | Error Memory | Never repeats mistakes | **原创 — no competitor has this** |
| **L4** | Knowledge Graph | Entity relationship management | 3-tier permissions |

## Key Features

- **22 MCP tools** — full surface accessible via MCP protocol
- **Zero external databases** — SQLite + FAISS, deploy anywhere
- **Auto-learning** — ≥3 same errors → auto-upgraded to permanent rules
- **Hybrid search** — semantic (FAISS) + keyword (SQLite) fallback
- **Production ready** — 30-point audit, Docker, systemd, OOM protection
- **Bilingual** — English + Chinese documentation

## For Enterprise

Self-hosted. Your data never leaves your network. SLA-backed.

- [Enterprise Features & Pricing](en/ENTERPRISE.md)
- [Architecture Guide](en/ARCHITECTURE.md)
- [API Reference](en/API_REFERENCE.md)
- [Comparison with Alternatives](en/COMPARISON.md)

## Open Source

Memory Engine is **MIT licensed**. Free to use, modify, and distribute.

[⭐ Star on GitHub](https://github.com/qq1009128320-dotcom/memory-engine)
