# 更新日志

本文档记录了企业记忆引擎项目的所有重要版本变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [v2.1.1] - 当前版本（生产级全面加固）

### 安全
- **路径遍历防护**：auto_fetch.py sync_local_files 使用 relative_to 验证文件在目录内
- **JSON 参数严格校验**：entity_add 的 aliases/properties 参数现在验证类型和格式
- **控制字符过滤增强**：validators.py 扩展范围包含 DEL、C1 控制字符和 Unicode 零宽字符
- **日志脱敏优化**：log_utils.py 只匹配长字符串（真实密钥），避免误匹配短文本

### 新增
- **SQLite 连接池**：_ConnectionPool 类限制最大连接数（10），自动回收闲置连接
- **共享工具模块**：utils.py 提取重复函数（now, sha256, parse_extraction_result, empty_result）
- **进度反馈**：memory_tree_reindex 每 100 条打印一次进度
- **部署回滚机制**：deploy.sh 失败时自动恢复备份

### 修复
- **P0-1**: migrate_add_faiss_id.py 添加 vector 列迁移
- **P0-2**: memory_tree_ingest 改为"先 FAISS 后数据库"，消除竞态条件
- **P0-3**: 实现 SQLite 连接池，解决连接泄漏问题
- **P1-4**: 缓存键包含 max_results，防止返回错误数量结果
- **P1-6**: error_log 升级偏好规则添加去重，避免重复创建
- **P2-2**: memory_tree_search LIMIT 默认值保护（1-100 范围）
- **P2-4**: observability.py 指标持久化使用文件锁
- **P2-7**: docker-compose.yml 健康检查优化（60s 间隔，60s 启动宽限期）
- **P2-8**: conftest.py 添加测试数据清理 fixture
- **P2-10**: _log_request 装饰器添加异常分类（ValidationError/TimeoutError/Exception）

### 优化
- **版本统一**：所有文件版本号统一为 v2.1.1
- **requirements.txt 精确版本约束**：使用 >=x.y.z,<x.y+1.0 格式
- **systemd 环境变量**：添加 PYTHONUNBUFFERED=1, PYTHONDONTWRITEBYTECODE=1
- **错误信息格式化**：config.py validate_config 输出更易读
- **代码审查清单**：CONTRIBUTING.md 添加详细审查检查项

---

## [v2.1.0] - 上一版本

### 新增
- **FAISS 写入失败自动回滚**：memory_tree_ingest 在 FAISS 索引失败时自动删除数据库行，保持数据一致性
- **嵌入调用超时保护**：_embed_text 和 _embed_texts 添加 timeout 参数，防止嵌入模型挂起
- **schema.sql 时间字段索引**：为所有表的 created_at/updated_at 字段添加索引，提升时间范围查询性能
- **部署脚本版本常量**：deploy.sh 使用 VERSION 常量统一管理版本号

### 修复
- **测试隔离**：conftest.py _setup_env fixture 从 session-scope 改为 function-scope，防止测试间状态泄露
- **test_config 脆弱断言**：LLM_TIMEOUT 从精确等于 30 改为范围检查（10-120 秒）
- **部署脚本错误处理**：set -euo pipefail + 改进 FAISS 重建错误处理逻辑

### 优化
- **pyproject.toml 完整化**：添加 [project]、[build-system]、[tool.ruff]、[tool.mypy] 完整配置
- **Dockerfile 简化**：移除 uv 依赖声明，使用标准 pip install
- **README 去重**：移除重复的"项目结构"段落，版本统一为 v2.1.0

---

## [v2.0.5] - 上一版本

### 新增
- 统一配置管理：通过 `config.py` 集中管理所有配置项，支持环境变量覆盖
- Docker 支持：提供 Dockerfile 和 docker-compose.yml，支持容器化部署
- 输入验证：对所有外部输入进行严格的参数校验和类型检查

### 修复
- 移除裸 `except:` 语句，改为捕获具体异常类型，提升错误处理精度
- 清理死代码（dead code），移除未使用的函数和导入

### 优化
- 代码结构重构，提升模块间解耦程度
- 日志输出更加规范化，便于问题排查

---

## [v1.1.0]

### 新增
- ChromaDB 向量搜索：集成 ChromaDB 作为向量存储后端，支持高效的语义相似度检索
- ONNX 嵌入模型：引入 ONNX Runtime 驱动的嵌入模型，实现跨平台高性能文本向量化
- 事实抽取管道：构建端到端的事实抽取流水线，自动从对话和文档中提取结构化知识

### 优化
- 记忆检索延迟降低约 40%
- 向量索引内存占用优化

---

## [v1.0.0]

### 新增
- MCP Server：基于 Model Context Protocol 构建的服务端，提供 20 个记忆管理工具
- 四层记忆架构：
  - **短期记忆**：会话上下文窗口
  - **工作记忆**：当前任务的临时状态
  - **长期记忆**：持久化存储的结构化知识
  - **情景记忆**：带时间戳的事件记录
- 飞书（Feishu）集成：支持将记忆同步至飞书文档和消息
- 层级摘要树：自动生成多层级记忆摘要，支持逐级下钻查看细节

---

## 版本说明

- **主版本号**：不兼容的 API 变更
- **次版本号**：向后兼容的功能新增
- **修订号**：向后兼容的问题修复
