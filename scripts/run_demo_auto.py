#!/usr/bin/env python3
"""自动运行演示脚本（按回车推进步骤，每步等待充足时间）"""
import subprocess, time, sys, threading

p = subprocess.Popen(
    ['python3', '-u', 'scripts/demo_showcase.py'],
    stdin=subprocess.PIPE,
    stdout=sys.stdout,
    stderr=sys.stderr,
    text=True,
    bufsize=1,
)

# Feed Enter keys at regular intervals
# The script has about 7 input() pauses
# Steps 4-5 (memory_tree_ingest) need extra time for embedding generation
delays = [8,          # wait for imports + title page
          3,          # system overview
          3,          # demo 1: knowledge retrieval
          15,         # demo 2: memory_tree_ingest (slow - embedding)
          5,          # demo 3: error correction
          3]          # summary

for i, delay in enumerate(delays):
    time.sleep(delay)
    p.stdin.write('\n')
    p.stdin.flush()
    print(f'  [auto: step {i+1} Enter sent after {delay}s]', flush=True)

# Final wait and close
time.sleep(5)
p.stdin.close()
try:
    p.wait(timeout=60)
except subprocess.TimeoutExpired:
    p.kill()
    print('\n  [auto: process killed after timeout]', flush=True)
