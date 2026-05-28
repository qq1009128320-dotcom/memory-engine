#!/bin/bash
# 记忆引擎一键部署脚本
# 适用于轻量级部署（FAISS + SQLite）

set -e

echo "========================================"
echo "  记忆引擎 v2.0.5 一键部署"
echo "  FAISS + SQLite 轻量级架构"
echo "========================================"
echo ""

# 1. 检查 Python 版本
echo "[1/6] 检查 Python 环境..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
REQUIRED_VERSION="3.10"
if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "❌ Python 版本不足：需要 >= $REQUIRED_VERSION，当前是 $PYTHON_VERSION"
    exit 1
fi
echo "✅ Python $PYTHON_VERSION"

# 2. 创建虚拟环境
echo ""
echo "[2/6] 创建虚拟环境..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ venv 创建完成"
else
    echo "✅ venv 已存在"
fi

# 3. 激活虚拟环境并安装依赖
echo ""
echo "[3/6] 安装依赖..."
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "✅ 依赖安装完成"

# 4. 运行迁移脚本（幂等，安全）
echo ""
echo "[4/6] 检查数据库迁移..."
python3 -c "
import os
os.environ.setdefault('DEEPSEEK_API_KEY', 'deploy-check')
from memory_server import _init_db
_init_db()
" || python3 migrate_add_faiss_id.py
echo "✅ 数据库检查完成"

# 5. 重建 FAISS 索引（如果存在旧数据）
echo ""
echo "[5/6] 重建 FAISS 索引..."
if [ -f "faiss.index" ]; then
    python3 -c "
import os
os.environ.setdefault('DEEPSEEK_API_KEY', 'deploy-check')
from memory_server import memory_tree_reindex
result = memory_tree_reindex()
print(f'索引重建: {result}')
" || echo "⚠️ 索引重建跳过（可能已有有效索引）"
else
    echo "✅ 无旧索引，跳过重建"
fi

# 6. 验证安装
echo ""
echo "[6/6] 验证安装..."
python3 -c "
import os
os.environ.setdefault('DEEPSEEK_API_KEY', 'deploy-check')
from memory_server import memory_health, memory_stats
health = memory_health()
stats = memory_stats()
print(f'✅ 健康状态: {health[\"status\"]}')
print(f'✅ Memory Tree: {stats[\"memory_tree_chunks\"]} 条')
print(f'✅ 偏好记忆: {stats[\"preferences\"]} 条')
print(f'✅ 知识图谱: {stats[\"entities\"]} 实体, {stats[\"relationships\"]} 关系')
"

echo ""
echo "========================================"
echo "  🎉 部署完成！"
echo "========================================"
echo ""
echo "启动命令:"
echo "  source venv/bin/activate"
echo "  python3 memory_server.py"
echo ""
echo "或作为 systemd 服务:"
echo "  sudo cp memory-engine.service /etc/systemd/system/"
echo "  sudo systemctl enable --now memory-engine.service"
echo ""
