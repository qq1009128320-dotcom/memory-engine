# 记忆引擎 — 生产级 Dockerfile
# 构建: docker build -t memory-engine:v2.1.1 .
# 运行: docker run -d -p 8765:8765 --env-file .env memory-engine:v2.1.1
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

# P3-10: 安装运行时依赖（faiss 需要 libgomp1）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN useradd --create-home --shell /bin/bash memory && \
    mkdir -p /data && chown memory:memory /data

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY . .

# P3-10: 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1

# 切换到非 root 用户
USER memory

# P3-10: 优化健康检查（避免 assert 导致的非零退出）
HEALTHCHECK --interval=60s --timeout=30s --retries=3 --start-period=60s \
    CMD python3 -c "from memory_server import memory_health; h=memory_health(); exit(0 if h['status']=='healthy' else 1)"

# 资源限制（docker run 时可覆盖）
# --memory=2g --cpus=2

EXPOSE 8765
CMD ["python3", "memory_server.py"]
