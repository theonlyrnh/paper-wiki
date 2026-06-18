# AI 开发规范（跨项目可复用版）

> 适用于：VS Code SSH 远程开发、Linux 服务器、大模型 API 项目、GitHub 上传、VPS 部署。  
> 核心目标：让 AI 助手和开发者在不同项目中都能安全、可验证、可复现地交付。

---

## 一、最高优先级：敏感信息绝不入库

**敏感信息包括但不限于**：

- API Key、Token、Cookie、Session、JWT
- 密码、数据库连接串、Redis/MQ 地址
- 真实 Base URL、内网地址、服务器 IP、SSH 用户名
- SSH 私钥、证书、`.pem`、`.key`
- 生产配置、真实 `.env`、包含密钥的日志

```python
# ❌ 错误：硬编码真实密钥
API_KEY = "<API_KEY>"

# ✅ 正确：从环境变量读取，并显式报错
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("LLM_API_KEY")
if not API_KEY:
    raise RuntimeError("缺少环境变量 LLM_API_KEY，请检查 .env 文件")
```

**日志规则**：

- 禁止打印完整密钥、Cookie、数据库连接串。
- 需要排错时只能打印掩码值，例如：`sk-****abcd`。
- 对外文档只能写占位符，不写真实服务地址和账号。

---

## 二、项目必备文件

| 文件 | 说明 | 能否上传 GitHub |
| --- | --- | :---: |
| `.env` | 真实密钥，本机/服务器保存 | ❌ 禁止 |
| `.env.example` | 占位符模板，供他人参考 | ✅ 可以 |
| `.gitignore` | 必须屏蔽敏感配置和运行产物 | ✅ 可以 |
| `README.md` | 项目说明、运行方式、配置说明 | ✅ 可以 |
| `requirements.txt` / `package.json` | 依赖清单 | ✅ 可以 |

**`.env.example` 示例**：

```env
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://api.example.com/v1
LLM_MODEL=your_model_name
EMBEDDING_API_KEY=your_embedding_key_here
```

**`.gitignore` 最小要求**：

```gitignore
# 敏感配置
.env
.env.*
!.env.example

# Python
__pycache__/
.venv/
venv/
*.py[cod]

# Node
node_modules/
dist/
build/

# 数据、日志与临时文件
data/
output/
*.log
logs/
tmp/

# 密钥与证书
*.pem
*.key
id_rsa
id_ed25519
```

---

## 三、新项目初始化流程

```text
1. 新建目录：~/projects/<项目名>
2. 初始化 Git：git init
3. 先创建 .gitignore / .env.example / README.md
4. Python 项目：python3 -m venv .venv && source .venv/bin/activate
5. Node 项目：确认 package.json 和 lockfile 策略
6. 复制 .env.example → .env，并只在本机/服务器填真实值
7. 开发前确认依赖、启动命令、测试命令都能运行
8. 上传前执行安全检查
```

**重要习惯**：

- 不要默认 `git add .`，优先 `git add <具体文件>`。
- 每次提交前看 `git status` 和 `git diff --cached`。
- README 里写清楚“如何配置、如何启动、如何测试”，但不要写真实密钥。

---

## 四、上传 GitHub 前的安全检查

优先使用项目真实可用工具；没有 `rg` 时再回退到 `grep`。

```bash
# 1. 确认 .env 没有被 Git 跟踪（正常应无输出）
git ls-files | grep -E "^\\.env$|^\\.env\\."

# 2. 搜索常见密钥形态
rg -n "sk-[a-zA-Z0-9_-]{20,}|api[_-]?key|token|secret|password|BEGIN .*PRIVATE KEY" .

# 3. 查看将要提交的文件和内容
git status
git diff --cached
```

如果 `.env` 已经被跟踪：

```bash
git rm --cached .env
```

如果真实密钥已经推送到远程仓库：

1. 立即去平台撤销/轮换该密钥。
2. 清理 Git 历史或直接新建干净仓库。
3. 不要只删除当前文件后继续使用旧密钥。

---

## 五、大模型 API 调用要求

LLM / Embedding / Rerank 等 API 客户端必须满足：

- Key、Base URL、模型名从环境变量或用户配置读取。
- 必须设置 `timeout`，建议 30 秒起步。
- 必须捕获网络错误、超时、空响应、非 JSON、格式异常。
- 日志不能打印完整密钥或完整请求头。
- 封装成单独模块，例如 `llm_client.py` / `embedding_client.py`，不要散落在业务代码各处。
- 错误信息要能指导用户修复配置，例如“缺少 LLM_API_KEY”而不是只报 `NoneType`。

---

## 六、AI 助手开发流程要求

AI 助手处理开发任务时，应按以下顺序执行：

```text
1. 明确需求和边界
2. 阅读项目说明、AGENTS/CLAUDE/GEMINI 等本地规则
3. 确认将修改哪些文件
4. 先验证现状，再提出结论
5. 小步修改，优先编辑现有文件
6. 运行测试/语法检查/启动检查
7. 输出：结论 → 证据 → 下一步
```

**禁止行为**：

- 硬编码真实密钥。
- 未经确认执行删除、覆盖、重置、清库、强推。
- 未验证路径、命令、依赖是否存在就写入文档。
- 把未安装工具写成必需能力。
- 声称“已通过测试”但没有给出实际命令和输出。
- 一次性甩大量代码但不说明如何运行和验证。

---

## 七、VPS / 服务器部署要点

- 在 VPS 上单独创建 `.env`，不要通过 GitHub 同步密钥。
- 用普通用户运行服务，避免长期使用 root。
- `.env` 权限收紧：

```bash
chmod 600 .env
```

- 使用 `systemd` 时推荐：

```ini
EnvironmentFile=/absolute/path/to/.env
```

- 部署后至少验证：

```bash
systemctl status <service-name>
journalctl -u <service-name> -n 100 --no-pager
curl -I http://127.0.0.1:<port>/
```

---

## 八、提交与文档规范

**提交信息格式**：

```text
feat: 新功能
fix: 修复问题
docs: 文档变更
chore: 工具/配置
refactor: 重构
test: 测试
```

**README 至少包含**：

- 项目用途
- 依赖安装
- 环境变量说明
- 本地启动命令
- 测试命令
- 部署注意事项

**文档原则**：

- 写真实可运行命令，不写伪路径。
- 示例值用占位符或 `example.com`。
- 高风险操作要写前置条件和回滚方式。

---

## 九、最小交付检查清单

每次交付前至少确认：

- [ ] `.gitignore` 已屏蔽 `.env`、日志、运行数据、密钥文件。
- [ ] `.env.example` 存在且只包含占位符。
- [ ] 没有硬编码 API Key / Token / 密码 / 私钥。
- [ ] README 写明启动和配置方式。
- [ ] 修改过的代码通过语法检查或测试。
- [ ] 输出结果包含实际验证命令和关键输出。

---

## 十、给 AI 助手的固定回复结构

开发完成或评审完成时，优先使用：

```text
结论：
- 做了什么 / 发现了什么

关键证据：
- 读了哪些文件
- 改了哪些文件
- 跑了哪些命令，结果是什么

风险与注意：
- 是否涉及敏感配置
- 是否需要用户本地补充 .env
- 是否有未验证项

下一步：
- 用户如何运行
- 用户如何测试
```
