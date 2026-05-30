#!/usr/bin/env python3
"""
Cron extraction runner — 定期从 Hermes 会话提取事实到记忆引擎。

用法:
    python3 cron_extract.py [--input <file>] [--days 1]

Hermes cronjob 配置示例:
    cronjob:
      action: create
      name: "fact-extraction"
      schedule: "0 */6 * * *"
      prompt: "运行 python3 /path/to/cron_extract.py --days 1"
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser(description="Cron fact extraction")
    parser.add_argument("--input", type=str, help="Path to conversation text file")
    parser.add_argument("--days", type=int, default=1, help="Days of sessions to scan")
    args = parser.parse_args()

    if args.input:
        tmp_file = Path(args.input)
        if not tmp_file.exists():
            print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
            sys.exit(1)
        # P3-⑤ 修复: 检查文件非空
        if tmp_file.stat().st_size == 0:
            print(f"WARNING: input file is empty: {args.input}", file=sys.stderr)
            print("Skipping extraction.")
            return
    else:
        # No input provided — skip silently (cron mode, no data)
        print("No input file specified. Skipping extraction.")
        return

    result = subprocess.run(
        [sys.executable, str(ROOT / "run_extraction.py"), "--input", str(tmp_file)],
        capture_output=True,
        text=True,
        timeout=120,
    )

    print("STDOUT:", result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[:500])
    print(f"EXIT: {result.returncode}")


if __name__ == "__main__":
    main()
