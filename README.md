# 记忆引擎 (Memory Engine)

四层 Agent 记忆系统。让 Agent 越用越聪明，越用越懂你。

## 核心理念

传统 AI 工具每次对话都是从零开始。记忆引擎让 Agent 从每次交互中学习——
被纠正就记住，犯过错不再犯，新信息自动沉淀。

```
传统 AI：每次从头开始，能力不变
记忆引擎：每次被纠正就更聪明一点
```

## 四层记忆架构

| 层 | 名称 | 功能 | 借鉴 |
|---|------|------|------|
| L1 | Memory Tree | 外部数据感知，自动同步 + 层级摘要 | OpenHuman |
| L2 | 偏好记忆 | 从对话中自动学习规则和习惯 | Mem0 |
| L3 | 纠错记忆 | 记住错误，≥3次自动升级为永久规则 | 独创 |
| L4 | 知识图谱 | 实体关系 + 三级权限共享 | Zep |

## 环境要求

- **Python >= 3.10**（FastMCP 3.x 需要）
- 操作系统：Linux / macOS / WSL2
- 磁盘空间：约 200MB（含 ONNX 嵌入模型 80MB）

## 快速开始

```bash
# 1. 安装依赖
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. ONNX 嵌入模型（首次运行自动下载，80MB）
# ChromaDB 的 DefaultEmbeddingFunction 会在首次使用时自动从 HuggingFace
# 下载 all-MiniLM-L6-v2 ONNX 模型到 ~/.cache/chroma/onnx_models/
# 如果网络受限，也可以手动下载到上述目录：
# curl -L https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz | tar xz
# 然后将解压内容放入 ~/.cache/chroma/onnx_models/all-MiniLM-L6-v2/

# 3. 初始化数据库
python3 -c "from memory_server import _init_db; _init_db()"

# 4. 启动 MCP Server（验证安装是否成功）
python3 memory_server.py
# 看到 "FastMCP server" 或类似输出即为成功，Ctrl+C 退出
```

## 环境变量

项目通过 `.env` 文件（放在项目根目录）或直接设置环境变量来配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥（事实提取和摘要生成需要） | 空（不设置则 LLM 功能不可用） |
| `DEEPSEEK_BASE_URL` | DeepSeek API 地址 | `https://api.deepseek.com` |
| `LLM_MODEL` | 使用的 LLM 模型 | `deepseek-chat` |
| `LLM_MAX_TOKENS` | LLM 最大输出 token | `2048` |
| `LLM_TIMEOUT` | LLM 请求超时（秒） | `60` |
| `ENTERPRISE_MEMORY_DB` / `MEMORY_DB_PATH` | SQLite 数据库路径 | `./memory.db` |
| `CHROMADB_PATH` | ChromaDB 向量存储路径 | `./chromadb` |
| `CHROMADB_COLLECTION` | ChromaDB 集合名称 | `memory_tree` |
| `EMBEDDING_MODEL` | 嵌入模型名称 | `all-MiniLM-L6-v2` |
| `MAX_MEMORY_ROWS` | 查询结果最大行数 | `100` |
| `MCP_SERVER_NAME` | MCP Server 名称 | `Memory Engine` |
| `FEISHU_APP_ID` | 飞书应用 ID（飞书集成用） | 空 |
| `FEISHU_APP_SECRET` | 飞书应用密钥 | 空 |

创建 `.env` 文件示例：

```bash
echo 'DEEPSEEK_API_KEY=sk-your-key-here' > .env
echo 'MEMORY_DB_PATH=./my_memory.db' >> .env
```

## MCP 工具列表

### Memory Tree（外部数据）
- `memory_tree_ingest` — 录入数据
- `memory_tree_search` — 关键词搜索
- `memory_tree_vector_search` — 向量语义搜索
- `memory_tree_fetch` — 获取完整内容
- `memory_tree_score` — 调整评分
- `memory_tree_reindex` — 重建向量索引
- `memory_tree_summary` — 层级摘要树 (L0/L1/L2)

### 偏好记忆（规则）
- `preference_add` / `preference_search` / `preference_list` / `preference_disable`

### 纠错记忆（不重犯）
- `error_check` / `error_log` / `error_list`

### 知识图谱（实体关系）
- `entity_add` / `entity_search` / `entity_link` / `graph_query`

### 综合
- `memory_search` — 跨四层综合检索
- `memory_stats` — 记忆库统计

## 事实自动提取

```bash
python3 run_extraction.py --text "用户: 帮我查腾讯的研发费用
Agent: 查询完成。研发支出 28.3 亿元。
用户: 用 amt_jpy 字段，不是 base_amt。
Agent: 已记录。"
```

自动提取：字段别名规则 + 错误纠正 + 实体关系。

## 层级摘要树

```bash
python3 summary_tree.py --rebuild
```

将零散的 Memory Tree 块聚合成 L0（全局概览）→ L1（主题分组）→ L2（原始块）三级结构。

## 飞书集成

```bash
# 手动同步
python3 auto_fetch.py

# 定时同步（每20分钟）
# 已通过 Hermes cronjob 自动调度
```

需要 `~/.hermes/.env` 中配置 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`。

## 接入 Hermes

在 `config.yaml` 中添加 MCP Server：

```yaml
mcp_servers:
  enterprise-memory:
    command: python3
    args: ["/path/to/enterprise-memory/memory_server.py"]
    env:
      ENTERPRISE_MEMORY_DB: "/path/to/enterprise-memory/memory.db"
```

## 项目结构

```
├── memory_server.py    # MCP Server 主程序（20个工具）
├── schema.sql          # 数据库 Schema（6张表）
├── run_extraction.py   # 端到端事实提取
├── extract_facts.py    # LLM 提示词模板 + 解析
├── summary_tree.py     # 层级摘要树生成
├── auto_fetch.py       # 飞书数据自动同步
├── setup.sh            # 安装脚本
└── memory.db           # SQLite 数据库（含演示数据）
```

## 技术栈

- **MCP 协议**: FastMCP 3.x
- **存储**: SQLite (单机) / PostgreSQL (生产)
- **向量检索**: ChromaDB + ONNX (all-MiniLM-L6-v2, 384维)
- **LLM**: DeepSeek (事实提取 + 摘要生成)
- **数据源**: 飞书 CLI / 本地文件 / 数据库

## 验证安装

安装完成后，运行以下 smoke test 确认一切正常：

```bash
# 确保虚拟环境已激活
source venv/bin/activate

# Smoke test：完整的端到端验证
python3 -c "
import os
os.environ['DEEPSEEK_API_KEY'] = 'test-key'  # 跳过 LLM 调用

from memory_server import _init_db, memory_stats, memory_tree_ingest, memory_health

# 1. 初始化数据库
_init_db()
print('✅ 数据库初始化成功')

# 2. 检查统计信息
stats = memory_stats()
print(f'✅ 记忆库统计: {stats}')

# 3. 测试录入
result = memory_tree_ingest(
    source='smoke_test',
    title='安装验证',
    content='这是一条验证记忆引擎安装是否正常的测试内容。',
)
print(f'✅ 录入测试: {result[\"status\"]}')

# 4. 健康检查
health = memory_health()
print(f'✅ 健康检查: {health[\"status\"]}')

print()
print('🎉 记忆引擎安装验证全部通过！')
"
```
