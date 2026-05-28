# 记忆引擎 — 生产级 Dockerfile
# 构建: docker build -t memory-engine:v2.0.5 .
# 运行: docker run -d -p 8765:8765 --env-file .env memory-engine:v2.0.5

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

# 创建非 root 用户
RUN useradd --create-home --shell /bin/bash memory && \
    mkdir -p /data && chown memory:memory /data

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY . .

# 切换到非 root 用户
USER memory

# 健康检查（30s 间隔，3 次失败后重启）
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python3 -c "from memory_server import memory_health; assert memory_health()['status'] == 'healthy'"

# 资源限制（docker run 时可覆盖）
# --memory=2g --cpus=2

EXPOSE 8765
CMD ["python3", "memory_server.py"]
