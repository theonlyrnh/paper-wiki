#!/bin/bash
# tunnel.sh — Paper Wiki SSH 反向隧道管理脚本
#
# 架构：
#   浏览器 → https://wiki.your-domain.com → VPS Caddy → 127.0.0.1:19828
#                                                        ↓ SSH 反向隧道
#                                                   A100:127.0.0.1:19828 (FastAPI)
#
# 用法：
#   ./tunnel.sh start    启动后端服务 + SSH 隧道
#   ./tunnel.sh stop     停止所有进程
#   ./tunnel.sh restart  重启
#   ./tunnel.sh status   查看运行状态
#   ./tunnel.sh test     测试通信链路

set -euo pipefail

# ── 配置 ─────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="${SCRIPT_DIR}/pids"
LOG_DIR="${SCRIPT_DIR}/logs"

# SSH 隧道配置
SSH_TARGET="${VPS_USER:-your-vps-user}@${VPS_HOST:-your-vps-ip}"
REMOTE_BIND="127.0.0.1"
REMOTE_PORT="19828"

# 后端服务配置
LOCAL_HOST="127.0.0.1"
LOCAL_PORT="19828"

# SSH 保活配置
ALIVE_INTERVAL="30"
ALIVE_COUNT_MAX="3"

# 服务启动等待
START_WAIT="5"

# Conda 环境（backend 运行在哪个 conda env）
CONDA_ENV="${PAPER_WIKI_CONDA_ENV:-paper-wiki}"

# 公网域名（用于端到端测试）
PUBLIC_URL="${PAPER_WIKI_PUBLIC_URL:-https://wiki.your-domain.com/api/health}"

# ── 初始化 ─────────────────────────────────────────────
mkdir -p "${PID_DIR}" "${LOG_DIR}"

# ── 后端服务：启动 FastAPI ──────────────────────────────
start_service() {
    # 先检查端口是否已被占用（比如通过 scripts/start.sh 启动的）
    if ss -tlnp 2>/dev/null | grep -q ":${LOCAL_PORT}"; then
        echo "✅ Backend already running on port ${LOCAL_PORT} (external process), skipping"
        return 0
    fi

    if [ -f "${PID_DIR}/backend.pid" ]; then
        local pid
        pid=$(cat "${PID_DIR}/backend.pid")
        if kill -0 "${pid}" 2>/dev/null; then
            echo "⚠️  Backend already running (PID ${pid}), skipping"
            return 0
        else
            echo "⚠️  Stale PID file, removing"
            rm -f "${PID_DIR}/backend.pid"
        fi
    fi

    echo "Starting backend service..."

    # 用 conda run 启动 FastAPI，输出到日志
    conda run -n "${CONDA_ENV}" --no-banner \
        python -m uvicorn backend.main:app \
            --host "${LOCAL_HOST}" \
            --port "${LOCAL_PORT}" \
            --reload \
        > "${LOG_DIR}/backend.log" 2>&1 &

    local pid=$!
    echo "${pid}" > "${PID_DIR}/backend.pid"
    echo "✅ Backend started (PID ${pid}, port ${LOCAL_PORT})"

    echo "Waiting ${START_WAIT}s for service to initialize..."
    sleep "${START_WAIT}"

    if curl -fsS "http://${LOCAL_HOST}:${LOCAL_PORT}/api/health" > /dev/null 2>&1; then
        echo "✅ Backend health check passed"
    else
        echo "❌ Backend failed to start, check ${LOG_DIR}/backend.log"
        tail -20 "${LOG_DIR}/backend.log" 2>/dev/null || true
        return 1
    fi
}

# ── SSH 隧道：建立反向端口转发 ─────────────────────────
start_tunnel() {
    if [ -f "${PID_DIR}/tunnel.pid" ]; then
        local pid
        pid=$(cat "${PID_DIR}/tunnel.pid")
        if kill -0 "${pid}" 2>/dev/null; then
            echo "⚠️  Tunnel already running (PID ${pid}), skipping"
            return 0
        else
            echo "⚠️  Stale PID file, removing"
            rm -f "${PID_DIR}/tunnel.pid"
        fi
    fi

    echo "Starting SSH tunnel..."
    echo "  ${REMOTE_BIND}:${REMOTE_PORT} on remote → ${LOCAL_HOST}:${LOCAL_PORT} local"

    # 检查是否安装了 autossh
    if command -v autossh > /dev/null 2>&1; then
        echo "  Using autossh for auto-reconnect"
        AUTOSSH_PIDFILE="${PID_DIR}/tunnel.pid" \
        autossh -M 0 \
            -N \
            -o ExitOnForwardFailure=yes \
            -o ServerAliveInterval="${ALIVE_INTERVAL}" \
            -o ServerAliveCountMax="${ALIVE_COUNT_MAX}" \
            -o TCPKeepAlive=yes \
            -o StrictHostKeyChecking=accept-new \
            -R "${REMOTE_BIND}:${REMOTE_PORT}:${LOCAL_HOST}:${LOCAL_PORT}" \
            "${SSH_TARGET}" \
            > "${LOG_DIR}/tunnel.log" 2>&1 &
        local pid=$!
        echo "${pid}" > "${PID_DIR}/tunnel.pid"
    else
        echo "  autossh not found, using plain ssh"
        ssh -N \
            -o ExitOnForwardFailure=yes \
            -o ServerAliveInterval="${ALIVE_INTERVAL}" \
            -o ServerAliveCountMax="${ALIVE_COUNT_MAX}" \
            -o TCPKeepAlive=yes \
            -o StrictHostKeyChecking=accept-new \
            -R "${REMOTE_BIND}:${REMOTE_PORT}:${LOCAL_HOST}:${LOCAL_PORT}" \
            "${SSH_TARGET}" \
            > "${LOG_DIR}/tunnel.log" 2>&1 &
        local pid=$!
        echo "${pid}" > "${PID_DIR}/tunnel.pid"
    fi

    echo "✅ Tunnel started (PID ${pid})"
    sleep 3

    if kill -0 "${pid}" 2>/dev/null; then
        echo "✅ Tunnel process is running"
    else
        echo "❌ Tunnel failed to start, check ${LOG_DIR}/tunnel.log"
        cat "${LOG_DIR}/tunnel.log" 2>/dev/null || true
        return 1
    fi
}

# ── 停止所有进程 ────────────────────────────────────────
stop() {
    echo "Stopping tunnel..."
    if [ -f "${PID_DIR}/tunnel.pid" ]; then
        local pid
        pid=$(cat "${PID_DIR}/tunnel.pid")
        kill "${pid}" 2>/dev/null || true
        # 同时杀掉 autossh 的子进程
        pkill -P "${pid}" 2>/dev/null || true
        rm -f "${PID_DIR}/tunnel.pid"
        echo "✅ Tunnel stopped"
    else
        echo "⚠️  No tunnel PID file"
    fi

    # 只停止由本脚本启动的后端（有 PID 文件的）
    if [ -f "${PID_DIR}/backend.pid" ]; then
        echo "Stopping backend..."
        local pid
        pid=$(cat "${PID_DIR}/backend.pid")
        kill "${pid}" 2>/dev/null || true
        pkill -P "${pid}" 2>/dev/null || true
        rm -f "${PID_DIR}/backend.pid"
        echo "✅ Backend stopped"
    else
        echo "ℹ️  Backend not managed by this script, leaving it alone"
    fi

    # 清理可能残留的隧道进程
    pkill -f "ssh.*-R.*${REMOTE_PORT}.*${SSH_TARGET}" 2>/dev/null || true
}

# ── 查看状态 ────────────────────────────────────────────
status() {
    echo "=== Service Status ==="
    if [ -f "${PID_DIR}/backend.pid" ]; then
        local pid
        pid=$(cat "${PID_DIR}/backend.pid")
        if kill -0 "${pid}" 2>/dev/null; then
            echo "✅ Backend: running (PID ${pid}, managed by this script)"
        else
            echo "❌ Backend: dead (stale PID ${pid})"
        fi
    elif ss -tlnp 2>/dev/null | grep -q ":${LOCAL_PORT}"; then
        echo "✅ Backend: running on port ${LOCAL_PORT} (external process)"
    else
        echo "❌ Backend: not running"
    fi

    echo ""
    echo "=== Tunnel Status ==="
    if [ -f "${PID_DIR}/tunnel.pid" ]; then
        local pid
        pid=$(cat "${PID_DIR}/tunnel.pid")
        if kill -0 "${pid}" 2>/dev/null; then
            echo "✅ Tunnel: running (PID ${pid})"
            echo "   ${REMOTE_BIND}:${REMOTE_PORT} on ${SSH_TARGET} → ${LOCAL_HOST}:${LOCAL_PORT}"
        else
            echo "❌ Tunnel: dead (stale PID ${pid})"
        fi
    else
        echo "❌ Tunnel: not running"
    fi

    echo ""
    echo "=== Port Listening ==="
    ss -tlnp 2>/dev/null | grep ":${LOCAL_PORT}" || echo "Port ${LOCAL_PORT}: not listening"

    echo ""
    echo "=== Recent Logs ==="
    if [ -f "${LOG_DIR}/tunnel.log" ]; then
        echo "--- tunnel.log (last 5 lines) ---"
        tail -5 "${LOG_DIR}/tunnel.log"
    fi
    if [ -f "${LOG_DIR}/backend.log" ]; then
        echo "--- backend.log (last 5 lines) ---"
        tail -5 "${LOG_DIR}/backend.log"
    fi
}

# ── 测试通信链路 ────────────────────────────────────────
test_link() {
    local exit_code=0

    echo "=== 1. Local Backend ==="
    echo "    curl http://${LOCAL_HOST}:${LOCAL_PORT}/api/health"
    local local_resp
    local_resp=$(curl -fsS "http://${LOCAL_HOST}:${LOCAL_PORT}/api/health" 2>&1) && {
        echo "    ✅ ${local_resp}"
    } || {
        echo "    ❌ Backend unreachable"
        exit_code=1
    }

    echo ""
    echo "=== 2. Remote Tunnel Endpoint (via SSH) ==="
    echo "    ssh ${SSH_TARGET} \"curl http://${REMOTE_BIND}:${REMOTE_PORT}/api/health\""
    local remote_resp
    remote_resp=$(ssh "${SSH_TARGET}" "curl -fsS http://${REMOTE_BIND}:${REMOTE_PORT}/api/health" 2>&1) && {
        echo "    ✅ ${remote_resp}"
    } || {
        echo "    ❌ Tunnel unreachable (SSH tunnel may be down)"
        exit_code=1
    }

    echo ""
    echo "=== 3. Public URL (end-to-end) ==="
    echo "    curl ${PUBLIC_URL}"
    local public_resp
    public_resp=$(curl -fsS "${PUBLIC_URL}" 2>&1) && {
        echo "    ✅ ${public_resp}"
    } || {
        echo "    ❌ Public URL unreachable"
        exit_code=1
    }

    echo ""
    if [ "${exit_code}" -eq 0 ]; then
        echo "🎉 All tests passed! Paper Wiki is live at https://wiki.your-domain.com"
    else
        echo "⚠️  Some tests failed. Check the output above."
    fi

    return "${exit_code}"
}

# ── 启动全部 ────────────────────────────────────────────
start() {
    start_service || return 1
    echo ""
    start_tunnel || return 1
    echo ""
    echo "=== Startup Complete ==="
    status
}

# ── 重启 ────────────────────────────────────────────────
restart() {
    stop
    echo "Waiting 2s..."
    sleep 2
    start
}

# ── 帮助 ────────────────────────────────────────────────
help() {
    echo "Usage: $0 {start|stop|restart|status|test}"
    echo ""
    echo "Commands:"
    echo "  start    Start backend service + SSH tunnel"
    echo "  stop     Stop all processes"
    echo "  restart  Restart all processes"
    echo "  status   Show running status"
    echo "  test     Test communication links"
}

# ── 主入口 ──────────────────────────────────────────────
case "${1:-help}" in
    start)   start   ;;
    stop)    stop    ;;
    restart) restart ;;
    status)  status  ;;
    test)    test_link ;;
    help)    help    ;;
    *)       help; exit 1 ;;
esac
