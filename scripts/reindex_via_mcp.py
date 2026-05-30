#!/usr/bin/env python3
"""通过 MCP 协议调用 memory_tree_reindex，带重试机制。

P3-⑬ 修复: 使用 httpx 替代 urllib，更好的错误处理和超时控制。
"""
import json
import sys
import time
import random

try:
    import httpx
except ImportError:
    print("ERROR: httpx required. Install: pip install httpx", file=sys.stderr)
    sys.exit(1)

MAX_RETRIES = 3
BASE_DELAY = 5
MCP_URL = "http://127.0.0.1:8765/mcp"


def reindex_with_retry():
    payload = json.dumps({
        "jsonrpc": "2.0", "id": "reindex",
        "method": "tools/call",
        "params": {"name": "memory_tree_reindex", "arguments": {}}
    }).encode()

    for attempt in range(MAX_RETRIES):
        try:
            # P3-⑬ 修复: 使用 httpx 替代 urllib
            with httpx.Client(timeout=300.0) as client:
                resp = client.post(
                    MCP_URL,
                    content=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                body = resp.text
                # 解析 SSE 格式响应
                for line in body.split("\n"):
                    if line.startswith("data: "):
                        try:
                            msg = json.loads(line[6:])
                            if "result" in msg:
                                print(f"MCP reindex OK: {json.dumps(msg['result'])}", flush=True)
                                return 0
                        except json.JSONDecodeError:
                            pass
                print("MCP reindex: 无结果", flush=True)
                return 0
        except httpx.TimeoutException:
            if attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                print(f"MCP reindex 超时 (尝试 {attempt+1}/{MAX_RETRIES}): 等待 {delay:.1f}s 后重试...",
                      file=sys.stderr, flush=True)
                time.sleep(delay)
            else:
                print(f"MCP reindex 最终超时", file=sys.stderr, flush=True)
                return 1
        except httpx.ConnectError as e:
            print(f"MCP reindex 连接失败: {e}", file=sys.stderr, flush=True)
            return 1
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                print(f"MCP reindex 失败 (尝试 {attempt+1}/{MAX_RETRIES}): {e}", file=sys.stderr, flush=True)
                print(f"  {delay:.1f}s 后重试...", file=sys.stderr, flush=True)
                time.sleep(delay)
            else:
                print(f"MCP reindex 最终失败: {e}", file=sys.stderr, flush=True)
                return 1
    return 1


if __name__ == "__main__":
    sys.exit(reindex_with_retry())
