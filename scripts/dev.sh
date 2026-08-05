#!/usr/bin/env bash
# 本地一键启动：API (8000) + 前端 Vite (5173)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
SEED="${SEED:-0}"
USE_SQLITE="${USE_SQLITE:-}"

cleanup() {
  local code=$?
  [[ -n "${API_PID:-}" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "${WEB_PID:-}" ]] && kill "$WEB_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  exit "$code"
}
trap cleanup EXIT INT TERM

echo "==> 工作目录: $ROOT"

# ---- Python 环境 ----
if [[ ! -d .venv ]]; then
  echo "==> 创建虚拟环境 .venv"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if [[ ! -f .venv/.deps_ok ]] || [[ requirements.txt -nt .venv/.deps_ok ]]; then
  echo "==> 安装 Python 依赖"
  pip install -q -r requirements.txt
  touch .venv/.deps_ok
fi

if [[ ! -f .env ]]; then
  echo "==> 复制 .env.example -> .env"
  cp .env.example .env
fi

if [[ "$USE_SQLITE" == "true" ]]; then
  echo "==> 使用 SQLite（USE_SQLITE=true）"
  # 临时覆盖，不改写 .env 文件
  export USE_SQLITE=true
fi

# ---- 演示数据（可选：SEED=1 ./scripts/dev.sh）----
if [[ "$SEED" == "1" ]]; then
  echo "==> 写入演示数据"
  python scripts/seed_demo.py
fi

# ---- 前端依赖 ----
if [[ ! -d web/node_modules ]]; then
  echo "==> 安装前端依赖"
  (cd web && npm install)
fi

# ---- 启动 ----
# BIND=127.0.0.1 仅本机；默认 0.0.0.0 允许局域网访问
BIND="${BIND:-0.0.0.0}"
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo '<本机局域网IP>')"

echo "==> 启动 API  http://${BIND}:${API_PORT}"
uvicorn app.main:app --reload --host "$BIND" --port "$API_PORT" &
API_PID=$!

echo "==> 启动前端 http://${BIND}:${WEB_PORT}"
(cd web && npm run dev -- --host "$BIND" --port "$WEB_PORT") &
WEB_PID=$!

echo ""
echo "----------------------------------------"
echo "  本机 H5:     http://127.0.0.1:${WEB_PORT}"
echo "  本机管理台:  http://127.0.0.1:${WEB_PORT}/admin"
echo "  局域网 H5:   http://${LAN_IP}:${WEB_PORT}"
echo "  局域网管理台: http://${LAN_IP}:${WEB_PORT}/admin"
echo "  API 文档:    http://${LAN_IP}:${API_PORT}/docs"
echo "  账号: admin / admin123"
echo "----------------------------------------"
echo "Ctrl+C 停止全部进程"
echo ""

wait
