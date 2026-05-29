#!/usr/bin/env python3
"""
记忆引擎每日备份脚本
- 备份 memory.db + faiss.index
- 备份前做完整性检查
- 保留 30 天历史
- 静默成功，异常时输出报警信息
"""
import sqlite3
import shutil
import gzip
from pathlib import Path
import os
import sys
from datetime import datetime, timedelta

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.path.join(PROJECT_DIR, "memory.db")
FAISS_PATH = os.path.join(PROJECT_DIR, "faiss.index")
BACKUP_DIR = os.path.join(PROJECT_DIR, "backups")
RETENTION_DAYS = 30

def main():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    errors = []

    # 1. 完整性检查
    try:
        conn = sqlite3.connect(DB_PATH)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        if result[0] != "ok":
            errors.append(f"INTEGRITY_CHECK_FAILED: {result[0]}")
    except Exception as e:
        errors.append(f"INTEGRITY_CHECK_ERROR: {e}")

    # 2. WAL checkpoint
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    except Exception as e:
        errors.append(f"WAL_CHECKPOINT_ERROR: {e}")

    # 3. 备份数据库
    db_backup = os.path.join(BACKUP_DIR, f"memory_{timestamp}.db.gz")
    try:
        with open(DB_PATH, "rb") as src:
            with gzip.open(db_backup, "wb") as dst:
                shutil.copyfileobj(src, dst)
    except Exception as e:
        errors.append(f"DB_BACKUP_ERROR: {e}")

    # 4. 备份 FAISS 索引
    if os.path.exists(FAISS_PATH):
        faiss_backup = os.path.join(BACKUP_DIR, f"faiss_{timestamp}.index")
        try:
            shutil.copy2(FAISS_PATH, faiss_backup)
        except Exception as e:
            errors.append(f"FAISS_BACKUP_ERROR: {e}")

    # 5. 清理过期备份
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    for f in os.listdir(BACKUP_DIR):
        fpath = os.path.join(BACKUP_DIR, f)
        if os.path.isfile(fpath):
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            if mtime < cutoff:
                try:
                    os.remove(fpath)
                except Exception:
                    pass

    # 6. 统计
    backups = [f for f in os.listdir(BACKUP_DIR) if os.path.isfile(os.path.join(BACKUP_DIR, f))]
    db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    faiss_size = os.path.getsize(FAISS_PATH) if os.path.exists(FAISS_PATH) else 0

    if errors:
        for e in errors:
            print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    else:
        # 静默成功 — cronjob watchdog 模式下空输出 = 正常
        # 如需日志：取消下面注释
        # print(f"Backup OK: {timestamp} | db={db_size}B faiss={faiss_size}B | total_backups={len(backups)}")
        pass

if __name__ == "__main__":
    main()
