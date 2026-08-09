#!/usr/bin/env bash
# 打生产发布包（无 Docker）：前端构建 + 后端源码 + 启动脚本
# 目标机需要 Python >= 3.10（推荐 3.11/3.12）。不支持 3.6。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="${VERSION:-$(date +%Y%m%d%H%M)}"
OUT_DIR="${OUT_DIR:-$ROOT/dist/workshop-assistant-$VERSION}"
ARCHIVE="${ARCHIVE:-$ROOT/dist/workshop-assistant-$VERSION.tar.gz}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "缺少命令: $1"; exit 1; }
}

need_cmd node
need_cmd npm
need_cmd python3
need_cmd tar

echo "==> 检查本机打包用 Python（仅构建环境，非生产机）"
PY_VER="$(python3 -c 'import sys; print("%d.%d"%sys.version_info[:2])')"
echo "    python3 = $PY_VER"

echo "==> 构建前端 web/dist"
(
  cd web
  if [[ ! -d node_modules ]]; then
    npm ci 2>/dev/null || npm install
  fi
  npm run build
)

echo "==> 组装发布目录: $OUT_DIR"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

# 运行时需要的目录
cp -R app "$OUT_DIR/app"
cp -R alembic "$OUT_DIR/alembic"
cp -R scripts "$OUT_DIR/scripts"
cp alembic.ini "$OUT_DIR/"
cp requirements.txt "$OUT_DIR/"
cp .env.example "$OUT_DIR/"
mkdir -p "$OUT_DIR/web"
cp -R web/dist "$OUT_DIR/web/dist"
mkdir -p "$OUT_DIR/data"

# 生产启动 / 安装脚本
cat > "$OUT_DIR/install.sh" << 'EOF'
#!/usr/bin/env bash
# 在生产机执行：创建 venv 并安装依赖
# 用法: PYTHON_BIN=/opt/python312/bin/python3.12 ./install.sh
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
echo "==> 使用解释器: $PYTHON_BIN"
"$PYTHON_BIN" - <<'PY'
import sys
v = sys.version_info
print(f"Python {v.major}.{v.minor}.{v.micro}")
if v < (3, 10):
    raise SystemExit(
        "错误: 需要 Python >= 3.10（当前太旧）。\n"
        "系统若只有 3.6，请安装独立的 3.11/3.12，例如:\n"
        "  - 从 python.org 装到 /opt/python312\n"
        "  - 或 miniconda / pyenv\n"
        "然后: PYTHON_BIN=/opt/python312/bin/python3.12 ./install.sh"
    )
PY

if [[ ! -d .venv ]]; then
  "$PYTHON_BIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "==> 已生成 .env，请按生产环境修改 DATABASE_URL / SECRET_KEY 等"
fi

echo "==> 安装完成。启动: ./start.sh"
EOF

cat > "$OUT_DIR/start.sh" << 'EOF'
#!/usr/bin/env bash
# 生产启动（同域托管前端 dist + API）
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  echo "请先执行 ./install.sh"
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

export WEB_DIST_DIR="${WEB_DIST_DIR:-$(pwd)/web/dist}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-2}"

# 首次可灌演示数据（生产慎用）: SEED=1 ./start.sh
if [[ "${SEED:-0}" == "1" ]]; then
  python scripts/seed_demo.py
fi

exec uvicorn app.main:app --host "$HOST" --port "$PORT" --workers "$WORKERS"
EOF

cat > "$OUT_DIR/README-DEPLOY.md" << 'EOF'
# 铁玉兰管家 · 无 Docker 部署

## 硬性要求

- **Python >= 3.10**（推荐 3.11 / 3.12）
- **不支持 Python 3.6.8**（FastAPI / Pydantic2 / SQLAlchemy2 及源码语法均无法兼容）
- 生产机若只有系统自带 3.6，请**另装一套独立 Python**，不要尝试降级本项目依赖

### 生产机只有 3.6 时怎么办

任选其一（与系统 Python 并存，互不影响）：

1. **官方便携/源码安装到 /opt**（推荐）
2. **Miniconda**：`conda create -n workshop python=3.12` 后用该环境的 python
3. **pyenv** 安装 3.12

然后：

```bash
PYTHON_BIN=/path/to/python3.12 ./install.sh
./start.sh
```

## 本机打包（有 Node 的开发机）

```bash
./scripts/pack_release.sh
# 产物: dist/workshop-assistant-YYYYMMDDHHMM.tar.gz
```

## 生产机安装

```bash
tar xzf workshop-assistant-*.tar.gz
cd workshop-assistant-*
# 编辑 .env（install 会从 example 复制）
PYTHON_BIN=/opt/python312/bin/python3.12 ./install.sh
vim .env   # DATABASE_URL / SECRET_KEY / ADMIN_*
./start.sh
```

访问: `http://服务器:8000`（API + 前端同域）  
健康检查: `http://服务器:8000/api/health`

## systemd 示例

```ini
[Unit]
Description=Workshop Assistant
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/workshop-assistant
Environment=WEB_DIST_DIR=/opt/workshop-assistant/web/dist
ExecStart=/opt/workshop-assistant/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
User=www

[Install]
WantedBy=multi-user.target
```

## 说明

- 前端已在打包机 `npm run build` 进 `web/dist`，生产机**不需要 Node**
- 生产机**不需要 Docker**
- 数据库可用本机 MySQL，或 `.env` 里 `USE_SQLITE=true`（仅小流量试用）
EOF

chmod +x "$OUT_DIR/install.sh" "$OUT_DIR/start.sh"

echo "==> 打 tar.gz: $ARCHIVE"
mkdir -p "$(dirname "$ARCHIVE")"
# macOS: 避免把 ._ AppleDouble 打进包
COPYFILE_DISABLE=1 tar -C "$(dirname "$OUT_DIR")" -czf "$ARCHIVE" "$(basename "$OUT_DIR")"

echo ""
echo "完成:"
echo "  目录: $OUT_DIR"
echo "  包:   $ARCHIVE"
echo "  说明: $OUT_DIR/README-DEPLOY.md"
ls -lh "$ARCHIVE"
