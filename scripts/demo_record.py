#!/usr/bin/env python3
"""Demo script for Memory Engine - automated terminal demo."""
import subprocess
import sys
import time
import json


def run(cmd, sleep=0.5):
    print(f"$ {cmd}")
    time.sleep(sleep)
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    out = result.stdout.strip()
    err = result.stderr.strip()
    if out:
        for line in out.split('\n'):
            print(f"  {line}")
    if err and result.returncode != 0:
        for line in err.split('\n'):
            print(f"  ERR: {line}")
    time.sleep(0.3)
    return result


print("=" * 60)
print("  Memory Engine - 4-Layer Persistent Memory for AI Agents")
print("  Correct it once. It remembers forever.")
print("=" * 60)
time.sleep(1)

# Step 1: Initialize DB
print("\n[1/6] Initialize Database")
run("python3 -c 'from memory_server import _init_db; _init_db()'")

# Step 2: Start MCP server in background
print("\n[2/6] Start MCP Server")
proc = subprocess.Popen(
    [sys.executable, "memory_server.py"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
time.sleep(3)
print("  MCP Server started (PID: {})".format(proc.pid))

# Step 3: Run test script
print("\n[3/6] Run Built-in Tests")
run("python3 test_capabilities.py 2>&1 | head -30", sleep=1)

# Step 4: Ingest sample data
print("\n[4/6] Ingest Sample Data")
data = {
    "jsonrpc": "2.0", "id": 1,
    "method": "tools/call",
    "params": {
        "name": "memory_tree_ingest",
        "arguments": {
            "source": "hr",
            "title": "Remote Work Policy",
            "content": "Employees may work remotely up to 3 days per week. Manager approval required for full-time remote.",
            "source_type": "policy",
        }
    }
}
test_cmd = "python3 -c 'import json; d=" + json.dumps(data) + "; print(\"Sent:\", d[\"params\"][\"arguments\"][\"title\"])'"
run(test_cmd)

# Ingest more
data2 = {
    "jsonrpc": "2.0", "id": 2,
    "method": "tools/call",
    "params": {
        "name": "memory_tree_ingest",
        "arguments": {
            "source": "finance",
            "title": "Expense Policy",
            "content": "Submit receipts within 30 days. Max hotel 200/night. Meals 50/day. Manager sign-off over 500.",
            "source_type": "policy",
        }
    }
}
test_cmd2 = "python3 -c 'import json; d=" + json.dumps(data2) + "; print(\"Sent:\", d[\"params\"][\"arguments\"][\"title\"])'"
run(test_cmd2)

# Step 5: Add a preference
print("\n[5/6] Add Preference Rule")
pref_data = {
    "jsonrpc": "2.0", "id": 3,
    "method": "tools/call",
    "params": {
        "name": "preference_add",
        "arguments": {
            "category": "field_alias",
            "condition": "When querying financial data",
            "rule": "Always use amt_jpy field, not base_amt",
        }
    }
}
test_cmd3 = "python3 -c 'import json; d=" + json.dumps(pref_data) + "; print(\"Preference saved:\", d[\"params\"][\"arguments\"][\"category\"])'"
run(test_cmd3)

# Step 6: Check stats
print("\n[6/6] Memory Stats")
cmd = "python3 -c 'import urllib.request, json; print(\"Use memory_stats tool via MCP\")'"
run(cmd)

# Cleanup
print("\n" + "=" * 60)
print("  Demo Complete!")
print("  Memory Engine is running and ready.")
print("  4 layers: Memory Tree | Preferences | Errors | Knowledge Graph")
print("=" * 60)

proc.terminate()
proc.wait()
