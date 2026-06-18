#!/bin/bash
# 一键部署改进版本（本地测试）

set -e  # Exit on error

echo "=========================================="
echo "Paper Wiki 改进版本部署脚本"
echo "=========================================="
echo ""

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查当前目录
if [ ! -f "config.yaml" ]; then
    echo -e "${RED}错误: 请在 paper-wiki 项目根目录运行此脚本${NC}"
    exit 1
fi

echo -e "${YELLOW}步骤 1/5: 安装新依赖${NC}"
pip install slowapi orjson || {
    echo -e "${RED}依赖安装失败，请检查pip${NC}"
    exit 1
}
echo -e "${GREEN}✓ 依赖安装完成${NC}"
echo ""

echo -e "${YELLOW}步骤 2/5: 备份原文件${NC}"
backup_dir="backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$backup_dir"
cp backend/main.py "$backup_dir/main.py.backup" 2>/dev/null || true
cp backend/routers/chat.py "$backup_dir/chat.py.backup" 2>/dev/null || true
cp frontend/index.html "$backup_dir/index.html.backup" 2>/dev/null || true
echo -e "${GREEN}✓ 备份完成: $backup_dir${NC}"
echo ""

echo -e "${YELLOW}步骤 3/5: 复制改进文件${NC}"

# 后端文件
mkdir -p backend/utils
cp improvements/backend/rate_limiter.py backend/
cp improvements/backend/utils/sanitizer.py backend/utils/
cp improvements/backend/services/llm_client_enhanced.py backend/services/

# 前端文件
mkdir -p frontend/styles
cp improvements/frontend/components/toast.js frontend/components/
cp improvements/frontend/styles/design-tokens.css frontend/styles/

echo -e "${GREEN}✓ 文件复制完成${NC}"
echo ""

echo -e "${YELLOW}步骤 4/5: 修改配置文件${NC}"

# 自动修改 main.py（如果还没修改过）
if ! grep -q "GZipMiddleware" backend/main.py; then
    echo "正在修改 backend/main.py..."
    # 创建修补后的版本
    cat improvements/backend/main_enhanced.py > backend/main.py
    echo -e "${GREEN}✓ backend/main.py 已更新${NC}"
else
    echo -e "${YELLOW}⚠ backend/main.py 似乎已经修改过，跳过${NC}"
fi

# 修改 index.html（自动添加新资源）
if ! grep -q "design-tokens.css" frontend/index.html; then
    echo "正在修改 frontend/index.html..."
    # 在 </head> 前插入
    sed -i 's|</head>|    <!-- Design System -->\n    <link rel="stylesheet" href="/static/styles/design-tokens.css">\n</head>|' frontend/index.html
    # 在第一个 <script> 前插入
    sed -i 's|<script src="/static/api.js|    <!-- Toast Notifications -->\n    <script src="/static/components/toast.js"></script>\n    <script src="/static/api.js|' frontend/index.html
    echo -e "${GREEN}✓ frontend/index.html 已更新${NC}"
else
    echo -e "${YELLOW}⚠ frontend/index.html 似乎已经修改过，跳过${NC}"
fi

echo ""

echo -e "${YELLOW}步骤 5/5: 准备测试环境${NC}"

# 确保本地配置存在
if [ ! -f "config.local.yaml" ]; then
    cp config.yaml config.local.yaml
    # 修改端口为 19829
    sed -i 's/port: 19828/port: 19829/' config.local.yaml
    echo -e "${GREEN}✓ 创建本地测试配置: config.local.yaml (端口 19829)${NC}"
else
    echo -e "${YELLOW}⚠ config.local.yaml 已存在，跳过创建${NC}"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}部署完成！${NC}"
echo "=========================================="
echo ""
echo "启动测试服务:"
echo "  export CONFIG_FILE=config.local.yaml"
echo "  python backend/main.py"
echo ""
echo "访问地址:"
echo "  http://127.0.0.1:19829"
echo ""
echo "回滚方案:"
echo "  cp $backup_dir/main.py.backup backend/main.py"
echo "  cp $backup_dir/index.html.backup frontend/index.html"
echo ""
echo "原服务端口 19828 不受影响，可继续运行"
echo ""
