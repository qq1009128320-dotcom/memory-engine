# 贡献指南

感谢你对企业记忆引擎项目的关注！本文档将帮助你了解如何参与项目开发。

---

## 目录

- [行为准则](#行为准则)
- [开发环境搭建](#开发环境搭建)
- [编码规范](#编码规范)
- [提交信息规范](#提交信息规范)
- [测试要求](#测试要求)
- [Pull Request 流程](#pull-request-流程)
- [PR 检查清单](#pr-检查清单)

---

## 行为准则

请保持专业和友善。我们致力于为所有参与者营造一个相互尊重、开放包容的社区环境。

---

## 开发环境搭建

```bash
# 克隆仓库
git clone <仓库地址>
cd enterprise-memory

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 安装依赖
pip install -e ".[dev]"
```

---

## 编码规范

本项目使用以下工具确保代码风格统一：

### 代码格式化：Black

所有 Python 代码必须通过 [Black](https://github.com/psf/black) 格式化：

```bash
black --line-length 100 .
```

### 导入排序：isort

使用 [isort](https://github.com/PyCQA/isort) 对 import 语句进行排序和分组：

```bash
isort --profile black .
```

### 代码检查：flake8

提交前必须通过 [flake8](https://github.com/PyCQA/flake8) 检查，不允许存在任何警告：

```bash
flake8 --max-line-length 100 .
```

### 一般原则

- 优先使用类型注解（Type Hints），便于静态分析和 IDE 支持
- 函数和类必须有 docstring，格式遵循 Google 风格
- 变量和函数命名使用 `snake_case`，类名使用 `PascalCase`
- 避免使用 `except:` 裸异常捕获，始终指定具体的异常类型
- 模块级别的常量使用 `UPPER_CASE`
- 每个模块尽量保持单一职责，避免上帝类（God Class）

---

## 提交信息规范

本项目遵循 [约定式提交（Conventional Commits）](https://www.conventionalcommits.org/zh-hans/) 规范。

### 提交信息格式

```
<类型>(<范围>): <简短描述>

<详细描述>

<关联的 Issue 编号>
```

### 类型（type）

| 类型 | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档更新 |
| `style` | 代码格式（不影响运行的改动） |
| `refactor` | 重构（既非新功能也非修复） |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `chore` | 构建过程或辅助工具的变动 |
| `ci` | CI/CD 配置变更 |

### 示例

```
feat(memory): 添加记忆去重功能

基于 embedding 相似度对长期记忆进行自动去重，
相似度阈值可通过 config.py 中的 MEMORY_DEDUP_THRESHOLD 配置。

Closes #42
```

```
fix(server): 修复 Feishu 集成 token 过期未刷新的问题
```

```
docs: 更新 API 文档中的返回值示例
```

---

## 测试要求

### 测试框架：pytest

所有测试使用 [pytest](https://docs.pytest.org/) 编写，确保代码的正确性和稳定性。

### 覆盖率要求

- **最低覆盖率：80%**
- 新增代码必须包含对应的测试用例
- 核心模块（memory engine、MCP server）建议达到 90% 以上

### 运行测试

```bash
# 运行全部测试并生成覆盖率报告
pytest --cov=. --cov-report=term-missing

# 仅运行特定模块的测试
pytest tests/test_memory.py -v

# 生成 HTML 覆盖率报告
pytest --cov=. --cov-report=html
```

### 测试编写建议

- 每个功能点至少一个正向测试和一个异常测试
- 使用 `pytest.fixture` 管理测试数据和依赖
- 外部依赖（数据库、API）使用 mock 或 stub 隔离
- 测试函数命名遵循 `test_<功能>_<场景>` 格式

---

## Pull Request 流程

1. **Fork 仓库** 并创建功能分支：

   ```bash
   git checkout -b feat/my-feature
   ```

2. **开发并提交**：遵循编码规范和提交信息规范。

3. **保持同步**：确保你的分支与主分支没有冲突：

   ```bash
   git fetch origin
   git rebase origin/main
   ```

4. **提交 PR**：推送到你的远程仓库并发起 Pull Request。

5. **代码评审**：至少一位维护者审核通过后方可合并。

6. **合并策略**：优先使用 Squash and Merge，保持主分支提交历史清晰。

---

## PR 检查清单

在提交 Pull Request 之前，请确认以下事项：

- [ ] 代码已通过 `black` 格式化
- [ ] 已运行 `isort` 排序导入语句
- [ ] 通过 `flake8` 检查，无警告和错误
- [ ] 所有现有测试继续通过（`pytest` 全绿）
- [ ] 测试覆盖率不低于 80%，新增代码有对应测试
- [ ] 提交信息遵循约定式提交规范
- [ ] 如有新功能，已更新相关文档
- [ ] 如有破坏性变更，已在 CHANGELOG.md 中记录
- [ ] 未包含调试用的 `print`、`breakpoint()` 或注释掉的代码
- [ ] 敏感信息（API Key、密码等）未硬编码在代码中，使用 `config.py` 管理

---

> 如有疑问，欢迎通过 Issue 或讨论区与我们交流。感谢你的贡献！
