# 使用 Deploy Key 为客户远程安装记忆引擎

## 概述

通过 GitHub Deploy Key 机制，让客户机器能安全地克隆私有仓库，不需要将仓库改为公开，也不需要把 GitHub 密码给客户。

工作原理：你生成一对 SSH 密钥，把公钥加到仓库的 Deploy Keys 里，把私钥给客户。客户用这把专用密钥只克隆这一个仓库，用完你可以随时吊销。

---

## 第一步：在你本地生成部署密钥

```bash
ssh-keygen -t ed25519 -f ~/.ssh/memory-engine-deploy -C "memory-engine-deploy"
```

执行后会在 `~/.ssh/` 生成两个文件：
- `memory-engine-deploy` — 私钥（给客户的）
- `memory-engine-deploy.pub` — 公钥（加到 GitHub）

---

## 第二步：把公钥加到 GitHub 仓库

浏览器打开：
`https://github.com/qq1009128320-dotcom/memory-engine/settings/keys`

点 **Deploy Keys** → **Add deploy key**

填写：
- **Title**: `memory-engine-deploy`
- **Key**: 粘贴 `~/.ssh/memory-engine-deploy.pub` 的内容
- **Allow write access**: ✅ 勾选（如果安装脚本需要 git push 写日志或配置则勾，只读安装可以不勾）

点 **Add key**

---

## 第三步：把私钥交给客户

把私钥文件安全地发给客户：
```bash
cat ~/.ssh/memory-engine-deploy
```

通过加密通道发送（如微信加密压缩包、企业微信文件、或当面 U 盘）。**不要明文发在聊天里**，这是相当于仓库密码的敏感文件。

---

## 第四步：客户机器上的安装命令

客户拿到 `memory-engine-deploy` 私钥文件后，保存到 `~/.ssh/` 并执行：

```bash
# 1. 保存私钥
mkdir -p ~/.ssh
# 把收到的私钥内容粘贴到这个文件：
chmod 600 ~/.ssh/memory-engine-deploy

# 2. 测试连接（可选）
ssh -T -i ~/.ssh/memory-engine-deploy git@github.com
# 如果看到 "Hi qq1009128320-dotcom/memory-engine-deploy" 就对了

# 3. 克隆项目
git clone --config core.sshCommand="ssh -i ~/.ssh/memory-engine-deploy" \
  git@github.com:qq1009128320-dotcom/memory-engine.git \
  /home/administrator/tools/enterprise-memory

# 4. 进入目录
cd /home/administrator/tools/enterprise-memory

# 5. 安装依赖
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 6. 启动记忆引擎
python3 memory_server.py
```

如果客户后续想更新代码：

```bash
cd /home/administrator/tools/enterprise-memory
git pull
```

把上面的核心命令做成一个安装脚本来简化：

```bash
curl -sL https://raw.githubusercontent.com/qq1009128320-dotcom/memory-engine/main/scripts/remote-install.sh | bash
```

> 注意：这个脚本本身需要访问公开的 raw.githubusercontent.com，所以你得把脚本写成通用安装框架，运行时再让它去拉取私钥 ~
> 或者，直接把安装脚本用类似方式一起加密发给客户。

---

## 第五步：用完吊销（可选）

安装完成、或者客户不再需要访问权限后，你可以在 GitHub 上删除那把 Deploy Key：

`https://github.com/qq1009128320-dotcom/memory-engine/settings/keys` → 找到那把 key → **Delete**

客户机器上的代码还能继续用，但无法再 `git pull` 更新了。

---

## 快速参考

| 步骤 | 操作 | 谁来执行 |
|------|------|---------|
| 生成密钥 | `ssh-keygen -t ed25519 -f ~/.ssh/memory-engine-deploy` | 你 |
| 加公钥到仓库 | GitHub Settings → Deploy Keys → Add | 你 |
| 发私钥给客户 | 加密通道传送 | 你 |
| 客户克隆安装 | `git clone --config core.sshCommand=...` | 客户 |

## 注意事项

1. **私钥不要明文发聊天** — 它等同于仓库密码
2. **如果私钥泄露** — 立即去 GitHub 删除那把 Deploy Key，重新生成一把新的
3. **Deploy Key 粒度是一个仓库** — 你可以为每个项目生成独立的 Deploy Key，彼此隔离
4. **阅读权限** — Deploy Key 默认只读，勾选 Allow write access 才可写入
