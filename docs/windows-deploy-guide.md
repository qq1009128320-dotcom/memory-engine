# 记忆引擎（Memory Engine）Windows 完整安装教程

> **写给谁看的：** 完全不懂编程的电脑用户。每一步都告诉你"为什么"和"怎么看结果"。
> **装完能得到什么：** Hermes Agent 多出一个"记忆"功能，越用越聪明。

---

## 📋 准备工作

### 你需要的东西
| 项目 | 说明 |
|------|------|
| 一台 Windows 10 或 11 的电脑 | ✅ |
| 能上网 | 要下载软件 |
| 你手里有一份"私钥文件" | 我叫它 `memory-engine-deploy`，后面会用到 |

### 装完需要占用多少空间
- 整个记忆引擎项目：约 **500MB**（大部分是 Python 运行环境）
- 不影响电脑速度，只在 Hermes 调用记忆功能时才运行

---

## 🔰 第一步：打开 PowerShell（命令行工具）

PowerShell 是 Windows 自带的"黑框框"，我们后面所有操作都在这里输入命令。

**打开方法（任选一种）：**

**方法一：**
1. 键盘按 `Win` 键（左下角四个方块的键）
2. 输入 `powershell`
3. 搜索结果出现 "Windows PowerShell"，**右键点击** → **以管理员身份运行**

**方法二：**
1. 键盘按 `Win + R`（同时按）
2. 输入 `powershell`
3. 按 `Ctrl + Shift + Enter`（以管理员身份打开）

> **怎么判断打开成功了？**
> 你会看到一个深蓝色背景的窗口，左上角写着 "Windows PowerShell"，光标在闪烁等你输入命令。

---

## 🔰 第二步：安装 Python（运行记忆引擎的"发动机"）

Python 是记忆引擎的"运行环境"，没有它记忆引擎跑不起来。

### 2.1 下载 Python

1. 打开浏览器，访问：https://www.python.org/downloads/
2. 你会看到一个大大的黄色按钮写着 **Download Python 3.12.x**（x 是版本号，比如 3.12.4）
3. 点击那个黄色按钮，浏览器会下载一个 `.exe` 文件

### 2.2 安装 Python

1. 找到下载好的文件（一般在"下载"文件夹里），**双击运行**
2. **最重要的一步：** 安装窗口打开后，**看最下面**，有一个勾选框写着：
   - `☐ Add Python 3.12 to PATH`
   - **必须勾上！** 如果不勾选，后面所有命令都用不了
3. 勾选后，点击上面的 **Install Now**（立即安装）
4. 等进度条走完，显示 "Setup was successful"，点 **Close**

### 2.3 验证 Python 是否装好

回到 PowerShell，输入以下命令然后按回车：

```powershell
python --version
```

**✅ 成功的样子：**
```
Python 3.12.4
```
（版本号可能不一样，只要是 3.10 以上就行）

**❌ 失败的样子：**
```
'python' 不是内部或外部命令，也不是可运行的程序
```
→ 原因：上一步忘记勾"Add Python to PATH"了，卸载重装，记得勾上。

再验证 pip（Python 的"软件商店"）：

```powershell
pip --version
```

**✅ 成功的样子：**
```
pip 24.x.x from C:\Users\... 
```

---

## 🔰 第三步：安装 Git（用来下载项目代码）

Git 是一个"下载代码的工具"，我们要用它从 GitHub 上把记忆引擎的项目文件拉到你的电脑上。

### 3.1 下载 Git

1. 浏览器打开：https://git-scm.com/download/win
2. 会自动开始下载（一个 `.exe` 文件，约 60MB）
3. 如果没自动下载，点页面上的 "Click here to download"

### 3.2 安装 Git

1. 双击下载好的安装文件
2. **一路点 Next（下一步），所有选项保持默认就行**
3. 最后点 **Install**，装完点 **Finish**
4. **不需要重启电脑**

### 3.3 验证 Git 是否装好

回到 PowerShell，输入：

```powershell
git --version
```

**✅ 成功的样子：**
```
git version 2.4x.x.windows.1
```

**❌ 失败的样子：** 提示找不到命令 → 重启 PowerShell 再试，还不行就重启电脑。

---

## 🔰 第四步：放好私钥文件（身份凭证）

你手里的 `memory-engine-deploy` 文件是一把"钥匙"，用来从 GitHub 上把记忆引擎项目下载下来。

> **这个文件是开发人员单独发给你的，请通过加密方式接收（如微信加密压缩包）。**

### 4.1 创建 .ssh 文件夹

```powershell
mkdir -Force $env:USERPROFILE\.ssh
```

**这行命令做了什么？** 在你的用户目录下创建一个叫 `.ssh` 的隐藏文件夹，用来存放 SSH 密钥。

### 4.2 放入私钥文件

1. 打开文件管理器（键盘按 `Win + E`）
2. 在地址栏输入：`%USERPROFILE%\.ssh` 然后按回车
3. 把收到的 `memory-engine-deploy` 文件**复制**到这个文件夹里
4. **不要改名！** 就保留 `memory-engine-deploy` 这个名字

### 4.3 设置文件权限（重要）

```powershell
icacls $env:USERPROFILE\.ssh\memory-engine-deploy /inheritance:r /grant "%USERNAME%:(R,W)"
```

**这行命令做了什么？** 告诉 Windows 这个文件只有你能读，别人不能看。

### 4.4 配置 SSH 使用这个密钥

用记事本创建（或编辑）SSH 配置文件：

```powershell
notepad $env:USERPROFILE\.ssh\config
```

如果弹出"是否创建新文件"的提示，点 **是**。然后把下面的内容完整粘贴进去：

```
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/memory-engine-deploy
```

点 **文件 → 保存**，关掉记事本。

**这步做了什么？** 告诉电脑："以后连接 GitHub 的时候，自动用 `memory-engine-deploy` 这个钥匙。"

### 4.5 测试连接

```powershell
ssh -T git@github.com
```

**✅ 成功的样子：**
```
Hi qq1009128320-dotcom/memory-engine! You've successfully authenticated...
```

**❌ 失败的样子：** 显示 "Permission denied" → 检查 `memory-engine-deploy` 文件是否放在了 `C:\Users\你的用户名\.ssh\` 目录下。

---

## 🔰 第五步：下载记忆引擎项目代码

在 PowerShell 里输入以下命令（可以复制粘贴，然后按回车）：

```powershell
cd C:\
mkdir -Force C:\tools
cd C:\tools
git clone git@github.com:qq1009128320-dotcom/memory-engine.git
```

```
Cloning into 'memory-engine'...
remote: Enumerating objects: ...
Receiving objects: 100% (.../...), done.
```

**验证是否下载成功：**

```powershell
dir C:\tools\memory-engine\
```

你会看到一堆文件名，其中必须有 `memory_server.py` 这个文件。

---

## 🔰 第六步：安装 Python 依赖（装记忆引擎的"零件"）

### 6.1 进入项目目录

```powershell
cd C:\tools\memory-engine
```

### 6.2 创建虚拟环境（一个独立的小房间）

```powershell
python -m venv venv
```

**这行命令做了什么？** 创建一个"虚拟环境"，相当于给记忆引擎一个独立的小空间来安装它的零件，不会影响你电脑上其他软件。

**⏳ 等待约 10-20 秒。**

**✅ 成功的样子：** 没有报错，直接出现下一行等待输入的光标。

**验证：**

```powershell
dir venv\Scripts\
```

应该能看到 `Activate.ps1`、`python.exe` 等文件。

### 6.3 激活虚拟环境

```powershell
.\venv\Scripts\Activate.ps1
```

**✅ 成功的样子：** 命令行前面多了 `(venv)` 字样：
```
(venv) PS C:\tools\memory-engine>
```

**❌ 如果报错：** "无法加载文件...因为在此系统上禁止运行脚本"

这是 Windows 的安全限制，执行以下命令解除限制（只需要做一次）：

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

输入 `Y` 确认，然后重新激活：
```powershell
.\venv\Scripts\Activate.ps1
```

### 6.4 安装依赖包

```powershell
pip install -r requirements.txt
```

**这行命令做了什么？** 从网上下载记忆引擎需要的所有"零件"（Python 库），自动安装。

**⏳ 等待 2-10 分钟**（取决于网络速度）。这期间会：
1. 下载 ChromaDB（向量数据库）—— 较大，约 30MB
2. 下载 ONNX 嵌入模型（all-MiniLM-L6-v2）—— 约 80MB，**首次下载会慢一些**
3. 下载其他小工具

**✅ 成功的样子：** 最后几行显示：
```
Successfully installed ... ...
```

**❌ 如果中途报错或者卡住不动：**

**情况一：pip 版本太旧**
```powershell
python -m pip install --upgrade pip
```
然后重新执行 `pip install -r requirements.txt`

**情况二：下载太慢**
```powershell
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```
（这行命令改用国内清华镜像下载，速度会快很多）

**情况三：网络超时**
多试几次，或者换个网络环境（比如手机开热点）。

---

## 🔰 第七步：初始化数据库（准备存储空间）

在 PowerShell 里输入（确保前面有 `(venv)` 标记）：

```powershell
python -c "from memory_server import _init_db; _init_db(); print('数据库初始化完成')"
```

**✅ 成功的样子：**
```
数据库初始化完成
```

**这步做了什么？** 创建了 6 张数据表（就像 Excel 里建好了 6 个 Sheet 的模板），用来存放记忆内容。

**验证：** 看看是不是多了一个文件：

```powershell
dir memory.db
```
应该能看到 `memory.db` 文件（大小约 16KB，刚创建是空的）。

---

## 🔰 第八步：配置 Hermes Agent（让 Hermes 认识记忆引擎）

Hermes Agent 是你已经在用的 AI 助手，我们需要告诉它："嘿，隔壁新装了一个记忆引擎，你可以调用它。"

### 8.1 找到 Hermes 的配置文件

在 PowerShell 里输入（不用管前面有没有 `(venv)`）：

```powershell
notepad $env:USERPROFILE\.hermes\config.yaml
```

**这行命令做了什么？** 用记事本打开 Hermes 的配置文件。如果弹出窗口问"是否创建新文件"，点 **是**。

### 8.2 修改配置文件

记事本打开后，你会看到一些已有的配置内容。**在文件的最末尾，另起一行**，完整地粘贴以下内容：

```yaml
mcp_servers:
  enterprise-memory:
    command: C:\tools\memory-engine\venv\Scripts\python.exe
    args: ["C:/tools/memory-engine/memory_server.py"]
    timeout: 120
    connect_timeout: 60
    enabled: true
```

**粘贴完成后**，点记事本的 **文件 → 保存**（或者按 `Ctrl + S`），然后关掉记事本。

> ⚠️ **注意：** 如果你看到文件里已经有 `mcp_servers:` 的内容，不要重复添加。找到 `mcp_servers:` 下面已有的配置，把上面这段加到它后面。

### 8.3 验证配置文件有没有写对

```powershell
type $env:USERPROFILE\.hermes\config.yaml
```

应该能看到你刚才粘贴的内容出现在最后。

---

## 🔰 第九步：一键验证（确认一切正常）

在 PowerShell 里逐条执行以下命令（每条都看到 ✅ 才算通过）：

```powershell
cd C:\tools\memory-engine
.\venv\Scripts\Activate.ps1
```

确认前面出现 `(venv)` 后，复制粘贴以下完整命令：

```powershell
python -c "
import os
os.environ['DEEPSEEK_API_KEY'] = 'test-key'

from memory_server import _init_db, memory_stats, memory_tree_ingest, memory_health

print('=== 记忆引擎安装验证 ===')
print()

_init_db()
print('✅ 1/4 数据库初始化成功')

stats = memory_stats()
print(f'✅ 2/4 记忆库统计正常')
print(f'   数据表状态: 已就绪')

result = memory_tree_ingest(
    source='smoke_test',
    title='安装验证',
    content='这是一条验证记忆引擎安装是否正常的测试内容。',
)
print(f'✅ 3/4 记忆录入测试: {result[\"status\"]}')

health = memory_health()
print(f'✅ 4/4 健康检查: {health[\"status\"]}')

print()
print('🎉 所有验证通过！记忆引擎安装成功！')
"
```

**✅ 全部通过的样子：**
```
=== 记忆引擎安装验证 ===

✅ 1/4 数据库初始化成功
✅ 2/4 记忆库统计正常
✅ 3/4 记忆录入测试: ingested
✅ 4/4 健康检查: healthy

🎉 所有验证通过！记忆引擎安装成功！
```

如果某一步出现红色报错，截图发给我帮你排查。

---

## 🔰 第十步：使用记忆引擎

### 10.1 启动 Hermes

一切配置好后，你像平时一样启动 Hermes 就行：

```powershell
hermes
```

Hermes 会自动帮你启动记忆引擎（在后台运行），你不需要手动去启动它。

### 10.2 怎么知道记忆引擎在工作？

和 Hermes 对话时，当你提到需要"记住"的内容，Hermes 会自动调用记忆引擎。你也可以直接问："记忆引擎现在记住了多少东西？"

---

## 🔰 第十一步（可选）：以后如何更新？

当项目有新版本时，更新命令：

```powershell
cd C:\tools\memory-engine
git pull
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt --upgrade
```

---

## ❓ 常见问题解答

### Q1: 每一步都报错怎么办？
**第一步：看错误信息** — 错误信息里有原因，通常包含关键词如 "not found"、"denied"、"timeout"。
**第二步：截图** — 把整个 PowerShell 窗口截图发给我。

### Q2: 什么是"以管理员身份运行"？
右键点击 PowerShell → 选择"以管理员身份运行"。有些操作需要管理员权限。

### Q3: 我的 PowerShell 打不开？
按 `Win + R` → 输入 `powershell` → 按回车。

### Q4: 装到一半断电/断网了怎么办？
从断掉的那一步重新开始就行，已经装好的部分不会丢失。

### Q5: 怎么知道记忆引擎有没有在运行？
启动 Hermes 后，打开任务管理器（按 `Ctrl + Shift + Esc`），在"进程"里找 `python.exe`，如果有说明记忆引擎在运行。

### Q6: 电脑重启后要重新装吗？
不用。重启后只需要打开 PowerShell 启动 Hermes（`hermes` 命令），它会自动拉起记忆引擎。

### Q7: 装完之后 C 盘空间够不够？
记忆引擎项目约 500MB，如果你 C 盘空间紧张，也可以装到 D 盘。只需把第五步的路径 `C:\tools` 换成 `D:\tools` 即可，后续所有路径也要跟着改。

### Q8: 更新后会不会丢失已经记住的内容？
不会。记忆存在 `memory.db` 文件里，更新代码不会动这个文件。

---

## 📊 最后确认清单

| 步骤 | 内容 | 状态 |
|------|------|------|
| ① | PowerShell 能打开 | ☐ |
| ② | Python 装好（`python --version` 有输出） | ☐ |
| ③ | Git 装好（`git --version` 有输出） | ☐ |
| ④ | 私钥放好（`ssh -T git@github.com` 提示成功） | ☐ |
| ⑤ | 项目代码下载到 `C:\tools\memory-engine\` | ☐ |
| ⑥ | 依赖安装完成（`pip install` 无报错） | ☐ |
| ⑦ | 数据库初始化成功 | ☐ |
| ⑧ | Hermes 配置文件修改完成 | ☐ |
| ⑨ | 一键验证全部通过 | ☐ |
| ⑩ | 启动 Hermes 使用 | ☐ |

---

> **有问题？** 直接把 PowerShell 的报错截图发过来，我帮你一步步排查。
