FROM python:3.12-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

# 创建数据目录
RUN mkdir -p /data

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD python3 -c "from memory_server import memory_stats; memory_stats()" || exit 1

EXPOSE 8000

CMD ["python3", "memory_server.py"]
