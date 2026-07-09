#!/bin/bash
# Memory Engine Demo - Simulated Terminal Session
# Record with: asciinema rec -c "bash demo.sh" -w 2 demo.cast
# Convert: agg demo.cast demo.gif --font-size 14 --cols 72 --rows 20

set -e

# Clean screen
clear

# Title frame
cat << 'TITLE'
╔══════════════════════════════════════════════════════════════╗
║          Memory Engine — 4-Layer Persistent Memory          ║
║              for AI Agents via MCP                          ║
╚══════════════════════════════════════════════════════════════╝
TITLE
sleep 2
clear

# Step 1: Clone & Install
echo ""
echo "  $ git clone https://github.com/qq1009128320-dotcom/memory-engine.git"
echo "  $ cd memory-engine"
echo "  $ pip install -r requirements.txt"
sleep 1
echo ""
echo "  ✓ 22 dependencies installed"
echo "  ✓ 4 memory layers initialized"
sleep 1
clear

# Step 2: Architecture overview
echo ""
echo "  ┌──────────────────────────────────────────────────────┐"
echo "  │               Memory Engine Architecture              │"
echo "  ├──────────┬──────────┬──────────────┬─────────────────┤"
echo "  │  L1      │  L2      │  L3          │  L4             │"
echo "  │  Memory   │  Prefer- │  Error       │  Knowledge      │"
echo "  │  Tree     │  ences   │  Memory      │  Graph          │"
echo "  │  FAISS    │  Rules   │  Auto-Learn  │  Entities       │"
echo "  └──────────┴──────────┴──────────────┴─────────────────┘"
echo ""
sleep 2
clear

# Step 3: Ingest data
echo ""
echo "  $ python3 memory_server.py &"
sleep 0.5
echo "  ✓ MCP Server started (22 tools available)"
sleep 0.5
echo ""
echo "  # Ingest company policies"
echo '  $ memory_tree_ingest("Remote Work Policy", "3 days/week WFH")'
sleep 0.5
echo '  $ memory_tree_ingest("Expense Policy", "$200/night hotel")'
sleep 0.5
echo '  $ entity_add("client", "Acme Corp")'
sleep 0.5
echo ""
echo "  ✓ 3 items ingested across 2 layers"
sleep 1
clear

# Step 4: Semantic search
echo ""
echo "  $ memory_tree_vector_search(query=\"How many days can I WFH?\")"
sleep 1
echo ""
echo "  ┌──────────────────────────────────────────────────────┐"
echo "  │ Rank  │ Score │ Title                    │ Layer     │"
echo "  ├───────┼───────┼──────────────────────────┼───────────┤"
echo "  │ 1     │ 0.92  │ Remote Work Policy       │ Memory    │"
echo "  │       │       │ → 3 days/week WFH        │ Tree      │"
echo "  │ 2     │ 0.45  │ Expense Policy           │ Memory    │"
echo "  │       │       │ → Hotel reimbursement    │ Tree      │"
echo "  └───────┴───────┴──────────────────────────┴───────────┘"
echo ""
echo "  ✓ Semantic vector search in <3ms"
sleep 2
clear

# Step 5: Error Memory (unique feature)
echo ""
echo "  # Agent makes a mistake..."
echo "  $ Used base_amt instead of amt_jpy"
sleep 0.5
echo ""
echo "  # User corrects the agent"
echo '  $ error_log("field_selection", "Always use amt_jpy")'
sleep 0.5
echo ""
echo "  # Next time, agent checks before running"
echo "  $ error_check(task_type=\"financial_report\")"
sleep 0.5
echo '  ⚠ Found 1 past mistake: "Used base_amt instead of amt_jpy"'
echo "  ⚠ Auto-applying rule: Always use amt_jpy"
sleep 0.5
echo ""
echo "  ✓ Error auto-learned. Will never repeat."
echo "  ✓ After 3 similar errors → permanent preference rule"
sleep 2
clear

# Step 6: Stats
echo ""
echo "  $ memory_stats()"
sleep 0.5
echo ""
echo "  ┌──────────────────────────────────────────────┐"
echo "  │ Memory Layer          │ Count    │ Engine   │"
echo "  ├───────────────────────┼──────────┼──────────┤"
echo "  │ Memory Tree (L1)      │ 87       │ FAISS    │"
echo "  │ Preferences (L2)      │ 42       │ SQLite   │"
echo "  │ Error Memory (L3)     │ 13       │ SQLite   │"
echo "  │ Knowledge Graph (L4)  │ 25       │ SQLite   │"
echo "  └───────────────────────┴──────────┴──────────┘"
echo ""
echo "  ✓ 0 external databases required"
echo "  ✓ Production health check: 30/30 PASS"
sleep 1
clear

# Final frame
cat << 'FINAL'
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║     Memory Engine — Correct it once. It remembers forever.   ║
║                                                              ║
║     ⭐ GitHub: qq1009128320-dotcom/memory-engine            ║
║     📖 Docs: docs/en/                                       ║
║     🔌 MCP: 22 tools ready                                  ║
║                                                              ║
║     4 Layers | 0 External DBs | MIT License                 ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
FINAL
sleep 2
clear
