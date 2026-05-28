# 贡献指南 (CONTRIBUTING.md)

感谢你对记忆引擎的兴趣！本指南帮助你快速上手贡献代码。

## 开发环境设置

```bash
# 1. Fork 仓库并克隆
git clone https://github.com/你的用户名/memory-engine.git
cd memory-engine

# 2. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 3. 安装依赖（含开发工具）
pip install -e ".[dev]"

# 4. 初始化数据库
python3 -c "from memory_server import _init_db; _init_db()"
```

## 代码风格

- **格式化工具**: Ruff (line-length=100)
- **类型检查**: mypy (Python 3.10)
- **运行 lint**: `ruff check .` 和 `mypy .`

## 提交代码

```bash
# 1. 创建功能分支
git checkout -b feature/你的功能名

# 2. 提交遵循 Conventional Commits
git commit -m "feat: 添加 FAISS 写入失败回滚"
git commit -m "fix: 修复 conftest 测试污染问题"
git commit -m "docs: 更新 README 版本为 v2.1.0"

# 3. 推送并提交 PR
git push origin feature/你的功能名
```

### Commit 类型

| 类型 | 说明 | 示例 |
|------|------|------|
| `feat` | 新功能 | feat: 添加嵌入缓存 |
| `fix` | Bug 修复 | fix: 修复 FAISS 回滚逻辑 |
| `docs` | 文档变更 | docs: 更新部署说明 |
| `refactor` | 代码重构 | refactor: 简化 config 加载 |
| `test` | 测试相关 | test: 添加 LLM_TIMEOUT 范围检查 |
| `chore` | 构建/工具 | chore: 更新 CI 配置 |

## 测试

```bash
# 运行所有测试
pytest tests/ -v

# 带覆盖率
pytest tests/ --cov=. --cov-report=term-missing

# 只运行特定测试
pytest tests/test_memory_server.py -v -k "ingest"
```

## 提交 PR 检查清单

- [ ] 代码通过 `ruff check .`
- [ ] 代码通过 `mypy .`（忽略缺失导入）
- [ ] 所有测试通过 `pytest tests/ -v`
- [ ] 覆盖率不低于 85%
- [ ] 更新 CHANGELOG.md
- [ ] 更新版本号为 v2.x.x

## 开发流程

1. **Issue 驱动**: 先在 Issues 中讨论功能/缺陷
2. **分支开发**: 每个功能一个分支
3. **小步提交**: 每次提交解决一个明确问题
4. **PR 审查**: 至少需要 1 人审查通过
5. **合并**: Squash merge 保持主分支整洁

## 四层记忆架构

贡献前请了解四层记忆架构的设计原则：

| 层 | 用途 | 写入触发 |
|----|------|----------|
| Memory Tree | 外部数据（飞书/文件/DB） | auto_fetch / 手动导入 |
| 偏好记忆 | 用户纠正的规则 | 用户说"应该用 X" |
| 纠错记忆 | 犯过的错误 | 用户指出错误 |
| 知识图谱 | 实体关系 | 自动提取 + 手动添加 |

## 问题反馈

- **Bug**: 请提供复现步骤、错误日志、环境信息
- **功能建议**: 请描述使用场景和预期行为
- **安全问题**: 请私信维护者，不要公开 Issue

## 许可证

本项目采用 MIT 许可证。贡献代码即表示同意按 MIT 许可证发布。
