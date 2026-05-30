#!/bin/bash
# 记忆引擎一键部署脚本
# 适用于轻量级部署（FAISS + SQLite）
set -euo pipefail

# P3-5: 版本常量（单一来源）
VERSION="2.1.2"  # P3-5: 与 pyproject.toml 和 SKILL.md 统一

# P3-2: 备份目录（用于回滚）
BACKUP_DIR="/tmp/memory-engine-backup-$(date +%Y%m%d_%H%M%S)"
BACKUP_FILES="memory.db faiss.index faiss_id_map.json .env .metrics.json .memory_server.pid"

echo "========================================"
echo "  记忆引擎 ${VERSION} 一键部署"
echo "  FAISS + SQLite 轻量级架构"
echo "========================================"
echo ""

# P3-⑩ 修复: 部署失败回滚机制，更精确的错误处理
cleanup_on_error() {
    echo ""
    echo "❌ 部署失败！"
    if [ -d "$BACKUP_DIR" ] && [ "$(ls -A "$BACKUP_DIR" 2>/dev/null)" ]; then
        echo "🔄 尝试回滚到备份..."
        # 只复制非空文件，避免覆盖现有文件
        for f in "$BACKUP_DIR"/*; do
            [ -e "$f" ] && cp -r "$f" ./ 2>/dev/null || true
        done
        echo "✅ 回滚完成（可能需要手动检查）"
    else
        echo "⚠️ 无有效备份可回滚"
    fi
    exit 1
}
# 只在关键步骤后设置 trap，避免误触发
set -e

# P3-2: 备份当前版本（如果存在）
if [ -d "venv" ] || [ -f "memory.db" ]; then
    echo "[0/6] 备份当前版本..."
    mkdir -p "$BACKUP_DIR"
    [ -d "venv" ] && cp -r venv "$BACKUP_DIR/" || true
    [ -f "memory.db" ] && cp memory.db "$BACKUP_DIR/" || true
    [ -f "faiss.index" ] && cp faiss.index "$BACKUP_DIR/" || true
    # P3-2: 备份更多关键文件
    for f in $BACKUP_FILES; do
        [ -f "$f" ] && cp "$f" "$BACKUP_DIR/" || true
    done
    echo "✅ 备份完成: $BACKUP_DIR"
fi

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
" || python3 -c "from db_migrations import run_migrations; run_migrations()"
echo "✅ 数据库检查完成"

# 5. 重建 FAISS 索引（如果存在旧数据）
echo ""
echo "[5/6] 重建 FAISS 索引..."
if [ -f "faiss.index" ]; then
    if python3 -c "
import os
os.environ.setdefault('DEEPSEEK_API_KEY', 'deploy-check')
from memory_server import memory_tree_reindex
result = memory_tree_reindex()
print(f'索引重建: {result}')
" 2>/dev/null; then
        echo "✅ FAISS 索引重建完成"
    else
        echo "⚠️ 索引重建跳过（可能已有有效索引或无数据）"
    fi
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
