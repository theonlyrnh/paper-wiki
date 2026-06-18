#!/bin/bash
# scripts/start.sh — One-click start for Paper Wiki
#
# Usage:
#   ./scripts/start.sh          # Start both services
#   ./scripts/start.sh --backend-only  # Start only the backend
#   ./scripts/start.sh --mineru-only   # Start only MinerU
#
# Optional env:
#   PAPER_WIKI_CONDA_ENV=paper-wiki
#   MINERU_CONDA_ENV=mineru
#   CONDA_SH="$(conda info --base)/etc/profile.d/conda.sh"
#   MINERU_CMD='mineru-api --port 8888'

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_CONDA_ENV="${PAPER_WIKI_CONDA_ENV:-paper-wiki}"
MINERU_CONDA_ENV="${MINERU_CONDA_ENV:-mineru}"
CONDA_SH="${CONDA_SH:-}"
MINERU_CMD="${MINERU_CMD:-mineru-api --port 8888}"
START_MINERU=true
START_BACKEND=true

for arg in "$@"; do
    case $arg in
        --backend-only) START_MINERU=false ;;
        --mineru-only) START_BACKEND=false ;;
    esac
done

echo "=== Paper Wiki 启动 ==="
echo ""

load_conda() {
    if command -v conda > /dev/null 2>&1; then
        eval "$(conda shell.bash hook)"
        return 0
    fi

    local candidates=()
    if [ -n "${CONDA_SH}" ]; then
        candidates+=("${CONDA_SH}")
    fi
    candidates+=(
        "${HOME}/miniforge3/etc/profile.d/conda.sh"
        "${HOME}/miniconda3/etc/profile.d/conda.sh"
        "${HOME}/anaconda3/etc/profile.d/conda.sh"
        "/opt/conda/etc/profile.d/conda.sh"
    )

    local candidate
    for candidate in "${candidates[@]}"; do
        if [ -f "${candidate}" ]; then
            # shellcheck source=/dev/null
            source "${candidate}"
            return 0
        fi
    done

    echo "❌ 未找到 conda。请先安装 conda，或设置 CONDA_SH=/absolute/path/to/conda.sh"
    exit 1
}

load_conda

MINERU_PID=""
BACKEND_PID=""

# === MinerU API ===
if [ "$START_MINERU" = true ]; then
    # Check if already running
    if curl -s http://localhost:8888/health > /dev/null 2>&1; then
        echo "✅ MinerU API 已在运行 (port 8888)"
    else
        echo "🚀 启动 MinerU API (conda: ${MINERU_CONDA_ENV}, port 8888)..."
        conda activate "${MINERU_CONDA_ENV}"
        HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}" nohup bash -lc "${MINERU_CMD}" > /tmp/mineru.log 2>&1 &
        MINERU_PID=$!
        echo "   PID: $MINERU_PID"
        conda deactivate || true
        echo "   等待启动..."
        sleep 8
        if curl -s http://localhost:8888/health > /dev/null 2>&1; then
            echo "   ✅ MinerU API 就绪"
        else
            echo "   ⚠️ MinerU 启动中，请稍后检查"
        fi
    fi
fi

# === Backend ===
if [ "$START_BACKEND" = true ]; then
    # Check if already running
    if curl -s http://localhost:19828/api/health > /dev/null 2>&1; then
        echo "✅ 知识库后端已在运行 (port 19828)"
    else
        echo "🚀 启动知识库后端 (conda: ${BACKEND_CONDA_ENV}, port 19828)..."
        conda activate "${BACKEND_CONDA_ENV}"
        cd "$PROJECT_DIR"
        nohup python -m backend.main > /tmp/paper-wiki.log 2>&1 &
        BACKEND_PID=$!
        echo "   PID: $BACKEND_PID"
        conda deactivate || true
        sleep 3
        if curl -s http://localhost:19828/api/health > /dev/null 2>&1; then
            echo "   ✅ 知识库后端就绪"
        else
            echo "   ⚠️ 后端启动中，请稍后检查"
        fi
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  📚 Paper Wiki 已就绪!"
echo ""
echo "  MinerU API:    http://localhost:8888"
echo "  知识库 Web:     http://localhost:19828"
echo ""
echo "  SSH 隧道:  ssh -L 19828:127.0.0.1:19828 your-user@your-server"
echo "  然后浏览器: http://localhost:19828"
echo ""
echo "  日志: tail -f /tmp/paper-wiki.log"
echo "  停止: fuser -k 19828/tcp; fuser -k 8888/tcp"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
