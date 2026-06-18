# Paper Wiki

**个人论文知识库** — 上传 PDF 论文，自动解析、智能摄入、构建知识图谱，提供混合搜索与多轮对话。

![Python](https://img.shields.io/badge/Python-3.12-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green) ![Version](https://img.shields.io/badge/Version-0.3.0-orange) ![License](https://img.shields.io/badge/License-MIT-yellow)

## 功能特性

- 📄 **PDF 论文上传与解析** — MinerU 3.3.1 高精度 GPU 解析，pypdf 备用方案，SHA256 去重
- 🧠 **两步 LLM 摄入管线** — Chain-of-thought 自动提取实体/概念/来源，生成 Wiki 页面（中文输出）
- 🔄 **摄入稳定性** — DB schema 迁移、WAL 模式、LLM 重试/退避、stale 任务清理、并发控制
- 🔍 **混合搜索** — BM25 (jieba) + 向量语义搜索，RRF 融合排序
- 🕸️ **知识图谱** — 4-信号模型 + Louvain 社区检测，交互式力导向图可视化
- 💬 **多轮对话** — 带编号引用 `[1][2][3]`，可点击参考来源查看 PDF 切片
- 🖼️ **PDF 原文切片** — 搜索结果右侧展示原始 PDF 段落图片，点击放大查看
- 🔐 **多用户系统** — 用户名登录、邀请码注册、数据隔离、权限委派
- 🌓 **亮/暗主题** — 75+ CSS 规则完整覆盖，偏好持久化
- ⚙️ **用户级模型配置** — 每位用户可自定义 LLM / Embedding API 地址与密钥
- 🌐 **1M 上下文窗口** — 支持超长论文完整摄入，无截断丢失

## 系统架构

```
┌──────────┐     ┌──────────┐     ┌──────────────┐     ┌──────────┐
│  Browser  │────▶│  Reverse  │────▶│  FastAPI     │────▶│  MinerU  │
│  (SPA)    │     │  Proxy    │     │  (Backend)   │     │  (Parse) │
└──────────┘     └──────────┘     └──────────────┘     └──────────┘
                     │                   │
                     │  SSH Tunnel       ├────▶ SQLite (papers.db)
                     │  (Optional)       ├────▶ LanceDB (vectors)
                     ▼                   ├────▶ NetworkX (graph)
                your-server              └────▶ LLM API (configurable)
```

## 快速开始

### 1. 安装依赖

```bash
# Backend 环境
conda create -n paper-wiki python=3.12
conda activate paper-wiki
pip install -r requirements.txt

# MinerU 环境 (PDF 解析，独立 conda env)
conda create -n mineru python=3.12
conda activate mineru
pip install torch torchvision  # Add --index-url for CUDA 12.6 if using GPU
pip install "mineru"
pip install accelerate six ftfy shapely pyclipper "transformers>=4.57.3"
```

### 2. 配置

复制 `.env.example` 并填入你的 API 密钥：

```bash
cp .env.example .env
# 编辑 .env:
# LLM_API_KEY=你的密钥
# LLM_API_BASE=你的LLM API地址
# LLM_MODEL=DeepSeek-V4-Pro  # 或其他模型
# EMBEDDING_API_KEY=你的密钥
```

复制 `config.yaml.example` 并调整 Embedding 配置：

```bash
cp config.yaml.example config.yaml
# 编辑 config.yaml:
#   api_base: 你的 Embedding API 地址
#   api_key: "${EMBEDDING_API_KEY}"
#   model: GLM-Embedding-3   # 或 bge-m3, text-embedding-3-large 等
#   dimensions: 2048          # 对应模型的输出维度
```

### 3. 启动服务

```bash
# 启动 MinerU 解析服务
conda activate mineru
mineru-api --port 8888

# 启动 FastAPI 后端
conda activate paper-wiki
python -m uvicorn backend.main:app --host 127.0.0.1 --port 19828
```

或使用启动脚本：

```bash
./scripts/start.sh
```

启动脚本会自动定位当前项目目录，默认使用 `paper-wiki` 与 `mineru` 两个 Conda 环境。
如果你的 Conda 初始化脚本不在默认位置，可显式指定：

```bash
CONDA_SH="$(conda info --base)/etc/profile.d/conda.sh" ./scripts/start.sh
```

### 4. 访问

浏览器打开 `http://127.0.0.1:19828`

默认管理员账号需要在首次启动后通过邀请码注册创建。

## VPS 部署

使用 SSH 反向隧道将后端暴露到 VPS：

```bash
# 前端同步到 VPS
scp -r frontend/ your-vps-user@your-vps-ip:/var/www/paper-wiki/frontend/

# 在 frontend/ 目录下创建 static → . 软链接 (SPA 路径兼容)
cd /var/www/paper-wiki/frontend && ln -sfn . static

# 启动 SSH 隧道
./tunnel.sh start

# Caddy 配置 (在 VPS 上)
wiki.your-domain.com {
    handle /api/* {
        reverse_proxy 127.0.0.1:19828
    }
    handle {
        root * /var/www/paper-wiki/frontend
        try_files {path} /index.html
        file_server
    }
}
```

## 项目结构

```
paper-wiki/
├── backend/               # FastAPI 后端
│   ├── main.py            # 应用入口
│   ├── auth.py            # 认证逻辑
│   ├── config.py          # 配置管理
│   ├── database.py        # 数据库连接
│   ├── models.py          # 数据模型
│   ├── routers/           # API 路由
│   │   ├── auth.py        # 登录/注册/邀请码/用户管理
│   │   ├── papers.py      # 论文上传/PDF切片
│   │   ├── search.py      # 搜索接口
│   │   ├── wiki.py        # Wiki 页面
│   │   ├── chat.py        # 对话接口
│   │   ├── graph.py       # 知识图谱
│   │   ├── ingest.py      # 摄入管线
│   │   └── batch.py       # 批量上传
│   └── services/          # 业务逻辑
│       ├── llm_client.py  # LLM API 客户端
│       ├── embedding.py   # Embedding 客户端
│       ├── vector_store.py # LanceDB 向量存储
│       ├── search_engine.py # BM25 搜索引擎
│       ├── search_service.py # 混合搜索服务
│       ├── graph_engine.py # 知识图谱引擎
│       ├── ingest_pipeline.py # 摄入管线
│       ├── ingest_limits.py   # 并发控制
│       ├── ingest_maintenance.py # stale 清理
│       └── mineru_client.py # MinerU 客户端
│   └── utils/
├── frontend/              # SPA 前端 (纯 JS, 无构建工具)
│   ├── index.html         # 入口页面
│   ├── app.js             # 路由与主题管理
│   ├── api.js             # API 客户端
│   ├── pages/             # 页面模块
│   │   ├── home.js        # 首页 (洞察卡片)
│   │   ├── papers.js      # 论文列表
│   │   ├── search.js      # 搜索 + Wiki 页面 + PDF 切片
│   │   ├── chat.js        # 多轮对话
│   │   ├── graph.js       # 知识图谱可视化
│   │   ├── paper-detail.js # 论文详情
│   │   ├── settings.js    # 设置 (主题/LLM/邀请码/用户管理)
│   │   ├── login.js       # 登录
│   │   └── register.js    # 注册
│   ├── components/        # 共享组件
│   │   ├── sidebar.js     # 侧边栏
│   │   ├── markdown-renderer.js # Markdown/KaTeX 渲染
│   │   ├── pixel-uploader.js    # 上传动画
│   │   └── toast.js       # Toast 通知
│   └── styles/
│       └── design-tokens.css # 设计系统变量
├── docs/                  # 本地维护文档（内部设计/安全/审阅资料）
│   ├── design/
│   │   ├── DESIGN.md
│   │   └── login-design.md
│   ├── reviews/
│   │   └── CODE_REVIEW.md
│   └── security/
│       └── AI_UPLOAD_SECURITY.md
├── scripts/               # 本地维护脚本与检查脚本
│   ├── start.sh           # 启动脚本
│   ├── deploy-vps.sh      # VPS 部署脚本
│   ├── publish-safe.sh    # 安全发布脚本（默认 dry-run）
│   ├── diagnose_ingest.py # 摄入健康诊断
│   ├── test_ingest_stability.py # 摄入稳定性回归测试
│   └── test_*.py          # 其他回归测试脚本
├── improvements/          # 历史改进方案与补丁资料
├── artifacts/             # 本地截图/调试产物（不提交）
├── local-only/            # 本地私有脚本（不提交）
├── backups/               # 本地备份（不提交）
├── data/                  # 运行数据：SQLite/PDF/Wiki/向量库（不提交）
├── logs/                  # 运行日志（不提交）
├── pids/                  # 本地进程 PID（不提交）
├── output/                # 解析/导出产物（不提交）
├── config.yaml.example    # 配置模板
├── .env.example           # 环境变量模板
├── requirements.txt       # Python 依赖
├── AI_DEV_RULES.md        # AI 协作开发规范
└── tunnel.sh              # SSH 隧道管理
```

### 本地文件与提交边界

以下文件或目录包含本机配置、运行数据、备份或调试产物，默认由 `.gitignore` 排除：

| 路径 | 用途 |
| --- | --- |
| `.env`、`.env.*` | 本地密钥与环境变量，`.env.example` 除外 |
| `config.yaml`、`config.local.yaml` | 本地真实服务配置 |
| `data/`、`output/` | 论文、数据库、解析结果、导出产物 |
| `logs/`、`pids/` | 运行日志与进程文件 |
| `backups/`、`.upload-snapshot/` | 本地备份与上传快照 |
| `artifacts/`、`screenshots/` | 截图和临时调试产物 |
| `local-only/` | 本地私有脚本和与当前项目无关的辅助脚本 |
| `docs/design/`、`docs/reviews/`、`docs/security/` | 内部设计、审阅、安全资料 |

公开发布请使用 `scripts/publish-safe.sh` 生成脱敏快照。该脚本默认只执行 dry-run，不会推送；只有显式传入 `--push --repo <GitHub 仓库 URL>` 并在最终确认提示输入 `YES` 后才会发布。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | FastAPI, SQLite (aiosqlite), bcrypt |
| PDF 解析 | MinerU 3.3.1, pypdf 备用 |
| LLM | DeepSeek-V4-Pro / 任意 OpenAI 兼容 API (用户可配置) |
| Embedding | GLM-Embedding-3 (2048维) / 任意 OpenAI 兼容 API (用户可配置) |
| 向量存储 | LanceDB |
| 文本搜索 | BM25 (jieba 分词) |
| 知识图谱 | NetworkX + Louvain 社区检测 |
| PDF 切片 | PyMuPDF (fitz) + Pillow |
| 前端 | 纯 JavaScript SPA, Tailwind CSS, KaTeX, Marked.js |
| 部署 | Caddy (HTTPS) + SSH 反向隧道 |

## 数据隔离

每位用户拥有完全独立的数据空间：

- `data/raw/{user_id}/` — 原始 PDF 文件
- `data/wiki/{user_id}/` — Wiki 页面文件
- LanceDB 表名前缀 `u{uid}_` — 向量数据隔离
- 所有数据库查询 `WHERE user_id = ?` — 行级隔离

## License

MIT License — 本项目基于 [llm-wiki](https://github.com/nashsu/llm_wiki) fork 并完全重写。
