# 记忆引擎 — 生产级 Dockerfile
# 构建: docker build -t memory-engine:v2.1.2 .
# 运行: docker run -d -p 8765:8765 --env-file .env memory-engine:v2.1.2
#
# P3-10: 优化项：
# - 使用多阶段构建（builder + runtime）
# - 非 root 用户运行
# - 健康检查
# - 环境变量支持

FROM python:3.11-slim AS builder

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ============================================================================
# 运行阶段（最小化镜像）
# ============================================================================
FROM python:3.11-slim

# P3-10: 安装运行时依赖（faiss 需要 libgomp1，健康检查需要 curl）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN useradd --create-home --shell /bin/bash memory && \
    mkdir -p /data && chown memory:memory /data

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
# models/ 目录包含 embedding 模型，已纳入版本控制
COPY . .

# P3-10: 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1

# 切换到非 root 用户
USER memory

# P2-7 修复: 简化健康检查，避免依赖 LLM API（可能超时导致容器重启）
# 只检查 SQLite 数据库和 FAISS 索引文件是否可读
HEALTHCHECK --interval=60s --timeout=10s --retries=3 --start-period=60s \
    CMD python3 -c "
import sqlite3, os, sys
db = os.environ.get('MEMORY_DB_PATH', '/data/memory.db')
faiss = os.environ.get('FAISS_INDEX_PATH', '/data/faiss.index')
try:
    conn = sqlite3.connect(db, timeout=5)
    conn.execute('SELECT 1')
    conn.close()
    # FAISS 索引存在则返回 0，不存在也返回 0（启动时可自动重建）
    # 但记录警告以便监控
    if not os.path.exists(faiss):
        print('WARNING: FAISS index not found at', faiss, file=sys.stderr)
    sys.exit(0)
except Exception as e:
    print('Health check failed:', e, file=sys.stderr)
    sys.exit(1)
"
# --memory=2g --cpus=2

EXPOSE 8765
CMD ["python3", "memory_server.py"]
