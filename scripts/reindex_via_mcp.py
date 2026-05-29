#!/usr/bin/env python3
"""通过 MCP 协议调用 memory_tree_reindex，带重试机制。"""
import json
import urllib.request
import sys
import time

MAX_RETRIES = 3
BASE_DELAY = 5

def reindex_with_retry():
    payload = json.dumps({
        "jsonrpc": "2.0", "id": "reindex",
        "method": "tools/call",
        "params": {"name": "memory_tree_reindex", "arguments": {}}
    }).encode()
    
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8765/mcp",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            resp = urllib.request.urlopen(req, timeout=300)
            body = resp.read().decode()
            for line in body.split(chr(10)):
                if line.startswith("data: "):
                    try:
                        msg = json.loads(line[6:])
                        if "result" in msg:
                            print(f"MCP reindex OK: {json.dumps(msg[chr(39)+chr(39).join([chr(114),chr(101),chr(115),chr(117),chr(108),chr(116)])])}", flush=True)
                            return 0
                    except json.JSONDecodeError:
                        pass
            print(f"MCP reindex: 无结果", flush=True)
            return 0
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2 ** attempt)
                print(f"MCP reindex 失败 (尝试 {attempt+1}/{MAX_RETRIES}): {e}", file=sys.stderr, flush=True)
                print(f"  {delay}s 后重试...", file=sys.stderr, flush=True)
                time.sleep(delay)
            else:
                print(f"MCP reindex 最终失败: {e}", file=sys.stderr, flush=True)
                return 1
    return 1

if __name__ == "__main__":
    sys.exit(reindex_with_retry())
