# Quick Start Guide

> Get Memory Engine running in under 2 minutes.

## Prerequisites

- Python 3.10+
- 2GB RAM (for embedding model)

## 30-Second Install

```bash
# Clone
git clone https://github.com/qq1009128320-dotcom/memory-engine.git
cd memory-engine

# Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Initialize database
python3 -c "from memory_server import _init_db; _init_db()"

# Start MCP server
python3 memory_server.py
```

That's it. Your memory engine is running on stdio MCP.

> **Note:** The embedding model (all-MiniLM-L6-v2) downloads automatically on first start (~90MB).

## Verify It's Running

In another terminal:

```bash
# Ingest some data
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"memory_tree_ingest","arguments":{"source":"test","title":"Hello World","content":"Memory Engine is running!"}}}' | python3 -c "
import sys, json
# Send via MCP stdio
"

# Or use the test script
python3 test_capabilities.py
```

## Connect Your Agent

### Hermes Agent

Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  enterprise-memory:
    command: /path/to/venv/bin/python3
    args: ["/path/to/memory_server.py"]
```

Restart Hermes, and you now have 22 memory tools available.

### Claude Code

```bash
claude --mcp-servers '{"memory-engine": {"command": "/path/to/venv/bin/python3", "args": ["/path/to/memory_server.py"]}}'
```

### Codex CLI

Add to your Codex setup:

```json
{
  "mcpServers": {
    "memory-engine": {
      "command": "/path/to/venv/bin/python3",
      "args": ["/path/to/memory_server.py"]
    }
  }
}
```

## Docker Deploy

```bash
docker compose up -d
```

Connects on HTTP port 8765 via MCP.

## One-Click Deploy (Linux)

```bash
chmod +x deploy.sh
sudo ./deploy.sh  # Automates everything: deps, DB, systemd service
```

## What's Next?

- Read the [Architecture Guide](ARCHITECTURE.md) to understand the 4-layer design
- Browse the [API Reference](API_REFERENCE.md) for all 22 MCP tools
- See how we compare with [other memory systems](COMPARISON.md)
