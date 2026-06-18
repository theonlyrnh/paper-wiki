#!/bin/bash
# deploy-vps.sh — 在笔记本上执行，将前端部署到 VPS
#
# 前置条件：
#   1. 能从笔记本 SSH 到 A100 服务器（获取前端文件）
#   2. 能从笔记本 SSH 到 VPS
#
# 用法：
#   # 先设置 A100 连接方式
#   export A100_HOST="your-user@your-backend-host"   # 或跳板机地址
#   # A100_PROJECT 必须设置为后端服务器上的真实项目绝对路径
#
#   chmod +x deploy-vps.sh
#   ./deploy-vps.sh

set -e

A100_HOST="${A100_HOST:-your-user@your-backend-host}"
VPS_HOST="${VPS_HOST:-your-vps-user@your-vps-ip}"
DOMAIN="${DOMAIN:-wiki.your-domain.com}"
A100_PROJECT="${A100_PROJECT:-}"

if [ -z "${A100_PROJECT}" ]; then
    echo "❌ 请先设置 A100_PROJECT 为后端服务器上的项目绝对路径"
    exit 1
fi

echo "============================================"
echo "  Paper Wiki — VPS 部署脚本"
echo "  <SERVER_MODEL>: $A100_HOST"
echo "  VPS:  $VPS_HOST"
echo "  域名: $DOMAIN"
echo "============================================"
echo ""

# ── Step 1: 从 A100 拉取前端文件 ──────────────────────
echo "📦 Step 1/4: 从 <SERVER_MODEL> 拉取前端文件..."
TMPDIR=$(mktemp -d)
scp -r "$A100_HOST:$A100_PROJECT/frontend" "$TMPDIR/"
echo "   ✅ 前端文件已下载到 $TMPDIR/frontend"

# ── Step 2: 上传前端到 VPS ─────────────────────────────
echo ""
echo "📤 Step 2/4: 上传前端到 VPS..."
ssh "$VPS_HOST" "mkdir -p /var/www/paper-wiki"
scp -r "$TMPDIR/frontend" "$VPS_HOST:/var/www/paper-wiki/"
echo "   ✅ 前端文件已上传"

# ── Step 3: 配置 Nginx ─────────────────────────────────
echo ""
echo "⚙️  Step 3/4: 配置 Nginx..."
ssh "$VPS_HOST" 'bash -s' << 'VPS_SCRIPT'
set -e

# 安装 Nginx
if ! command -v nginx &>/dev/null; then
    echo "   安装 Nginx..."
    apt-get update -qq && apt-get install -y -qq nginx
fi

# 写 Nginx 配置
cat > /etc/nginx/sites-available/paper-wiki << 'NGINX'
server {
    listen 80;
    server_name wiki.your-domain.com;

    root /var/www/paper-wiki/frontend;
    index index.html;

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Static files
    location /static/ {
        alias /var/www/paper-wiki/frontend/;
        expires 1h;
        add_header Cache-Control "public, immutable";
    }

    # API proxy to SSH tunnel
    location /api/ {
        proxy_pass http://127.0.0.1:19828;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 10s;
    }

    # WebSocket support (for future use)
    location /ws/ {
        proxy_pass http://127.0.0.1:19828;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
    }
}
NGINX

# 启用站点
ln -sf /etc/nginx/sites-available/paper-wiki /etc/nginx/sites-enabled/paper-wiki
rm -f /etc/nginx/sites-enabled/default

# 测试并重载
nginx -t
systemctl reload nginx || service nginx reload

echo "   ✅ Nginx 配置完成"
VPS_SCRIPT

# ── Step 4: 建立 SSH 隧道 ──────────────────────────────
echo ""
echo "🔗 Step 4/4: 建立 SSH 隧道 (VPS:19828 → <SERVER_MODEL>:19828)"
echo ""
echo "   在另一个终端窗口执行以下命令（保持运行）："
echo ""
echo "   ssh -R 19828:127.0.0.1:19828 $VPS_HOST -N -o ServerAliveInterval=60"
echo ""
echo "   或者用 autossh 自动重连："
echo ""
echo "   autossh -M 0 -R 19828:127.0.0.1:19828 $VPS_HOST -N -o ServerAliveInterval=30"
echo ""

# ── 清理临时文件 ───────────────────────────────────────
rm -rf "$TMPDIR"

echo "============================================"
echo "  ✅ 部署完成！"
echo ""
echo "  访问: http://$DOMAIN"
echo ""
echo "  注意：需要保持 SSH 隧道运行，后端 API 才能访问。"
echo "============================================"
