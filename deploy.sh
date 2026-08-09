#!/usr/bin/env bash
#
# 铁玉兰管家 · 一键部署（非 Docker）
# 步骤: 1.本机打包 2.SSH 连接 3.上传 4.远程装 Python3.11+依赖 5.systemd 启动 6.健康检查
#
# 用法:
#   cp deploy.env.example deploy.env   # 首次
#   ./deploy.sh                        # 部署到 SERVER1
#   ./deploy.sh 1
#
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${CYAN}[STEP]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f deploy.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source deploy.env
  set +a
  log_info "已加载 deploy.env"
else
  log_error "未找到 deploy.env，请先: cp deploy.env.example deploy.env"
  exit 1
fi

TARGET="${1:-${DEPLOY_TARGET:-1}}"
if [[ "$TARGET" == "2" ]]; then
  REMOTE_HOST="${DEPLOY_SERVER2_HOST:?DEPLOY_SERVER2_HOST 未配置}"
  REMOTE_PORT="${DEPLOY_SERVER2_PORT:-22}"
  REMOTE_USER="${DEPLOY_SERVER2_USER:-root}"
  REMOTE_PASSWORD="${DEPLOY_SERVER2_PASSWORD:-}"
else
  REMOTE_HOST="${DEPLOY_SERVER1_HOST:?DEPLOY_SERVER1_HOST 未配置}"
  REMOTE_PORT="${DEPLOY_SERVER1_PORT:-22}"
  REMOTE_USER="${DEPLOY_SERVER1_USER:-root}"
  REMOTE_PASSWORD="${DEPLOY_SERVER1_PASSWORD:-}"
fi

REMOTE_DIR="${REMOTE_DIR:-/root/workshop-assistant}"
APP_PORT="${APP_PORT:-8000}"
APP_WORKERS="${APP_WORKERS:-1}"
DEPLOY_DB="${DEPLOY_DB:-sqlite}"
SEED_DEMO="${SEED_DEMO:-0}"
SERVICE_NAME="${SERVICE_NAME:-workshop-assistant}"
PYTHON_REMOTE_BIN="${PYTHON_REMOTE_BIN:-/usr/bin/python3.11}"

SSH_BASE=(ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -p "$REMOTE_PORT")
SCP_BASE=(scp -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -P "$REMOTE_PORT")
REMOTE_ADDR="${REMOTE_USER}@${REMOTE_HOST}"
DEPLOY_AUTH_MODE="plain"

if "${SSH_BASE[@]}" -o BatchMode=yes "$REMOTE_ADDR" "exit 0" 2>/dev/null; then
  DEPLOY_AUTH_MODE="key"
  SSH_CMD() { "${SSH_BASE[@]}" "$REMOTE_ADDR" "$@"; }
  SCP_CMD() { "${SCP_BASE[@]}" "$@"; }
  log_info "使用 SSH 密钥认证"
elif command -v sshpass &>/dev/null && [[ -n "$REMOTE_PASSWORD" ]]; then
  DEPLOY_AUTH_MODE="sshpass"
  SSH_CMD() { sshpass -p "$REMOTE_PASSWORD" "${SSH_BASE[@]}" "$REMOTE_ADDR" "$@"; }
  SCP_CMD() { sshpass -p "$REMOTE_PASSWORD" "${SCP_BASE[@]}" "$@"; }
  log_info "使用 sshpass 密码认证"
else
  if [[ -n "$REMOTE_PASSWORD" ]]; then
    log_warn "未安装 sshpass，将尝试交互式 SSH（可能失败于非交互环境）"
  else
    log_warn "无密钥且未配置密码，将尝试交互式 SSH"
  fi
  SSH_CMD() { "${SSH_BASE[@]}" "$REMOTE_ADDR" "$@"; }
  SCP_CMD() { "${SCP_BASE[@]}" "$@"; }
fi

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { log_error "缺少命令: $1"; exit 1; }
}

log_info "目标: $REMOTE_ADDR:$REMOTE_PORT → $REMOTE_DIR (port $APP_PORT, db=$DEPLOY_DB)"

# ========== 步骤1: 本机打包 ==========
log_step "步骤1: 本机打包前端+后端..."
need_cmd node
need_cmd npm
need_cmd python3
need_cmd tar
need_cmd scp

VERSION="$(date +%Y%m%d%H%M%S)"
export VERSION
export OUT_DIR="$SCRIPT_DIR/dist/workshop-assistant-$VERSION"
export ARCHIVE="$SCRIPT_DIR/dist/workshop-assistant-$VERSION.tar.gz"
./scripts/pack_release.sh
ARCHIVE_NAME="$(basename "$ARCHIVE")"

# ========== 步骤2: 远程准备 Python ==========
log_step "步骤2: 远程检查/安装 Python 3.11..."
SSH_CMD "bash -s" <<REMOTE_PY
set -euo pipefail
if ! command -v python3.11 >/dev/null 2>&1; then
  echo "==> 安装 python3.11 / pip / venv"
  if command -v yum >/dev/null 2>&1; then
    yum install -y python3.11 python3.11-pip python3.11-devel >/dev/null
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y python3.11 python3.11-pip python3.11-devel >/dev/null
  else
    echo "无法自动安装 python3.11，请手工安装后重试"
    exit 1
  fi
fi
python3.11 - <<'PY'
import sys
print(f"remote Python {sys.version}")
if sys.version_info < (3, 10):
    raise SystemExit("需要 Python >= 3.10")
PY
# ensure venv module
python3.11 -c "import venv" 2>/dev/null || {
  yum install -y python3.11-devel >/dev/null 2>&1 || true
}
mkdir -p "$REMOTE_DIR" /tmp
REMOTE_PY

# ========== 步骤3: 上传 ==========
log_step "步骤3: 上传 $ARCHIVE_NAME ..."
SCP_CMD "$ARCHIVE" "$REMOTE_ADDR:/tmp/$ARCHIVE_NAME"

# ========== 步骤4: 远程解压安装 ==========
log_step "步骤4: 远程解压并安装依赖..."

# 组装远程 .env 片段（仅首次或显式变量时写入）
ENV_SNIPPET=""
if [[ "$DEPLOY_DB" == "mysql" ]]; then
  DB_URL="${DATABASE_URL:-}"
  if [[ -z "$DB_URL" ]]; then
    log_error "DEPLOY_DB=mysql 时必须在 deploy.env 设置 DATABASE_URL"
    exit 1
  fi
  ENV_SNIPPET+="USE_SQLITE=false"$'\n'
  ENV_SNIPPET+="DATABASE_URL=${DB_URL}"$'\n'
else
  ENV_SNIPPET+="USE_SQLITE=true"$'\n'
  ENV_SNIPPET+="SQLITE_PATH=./data/workshop.db"$'\n'
fi

[[ -n "${SECRET_KEY:-}" ]] && ENV_SNIPPET+="SECRET_KEY=${SECRET_KEY}"$'\n'
[[ -n "${ADMIN_USERNAME:-}" ]] && ENV_SNIPPET+="ADMIN_USERNAME=${ADMIN_USERNAME}"$'\n'
[[ -n "${ADMIN_PASSWORD:-}" ]] && ENV_SNIPPET+="ADMIN_PASSWORD=${ADMIN_PASSWORD}"$'\n'

# DeepSeek：优先 deploy.env；未配则只从本地 .env 抽取 DEEPSEEK_*（不整文件 source，避免覆盖 RDS）
if [[ -z "${DEEPSEEK_API_KEY:-}" && -f "$SCRIPT_DIR/.env" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      DEEPSEEK_API_KEY=*|DEEPSEEK_BASE_URL=*|DEEPSEEK_MODEL=*|SCHEDULE_AGENT_ENABLED=*)
        export "$line"
        ;;
    esac
  done < "$SCRIPT_DIR/.env"
fi
[[ -n "${DEEPSEEK_API_KEY:-}" ]] && ENV_SNIPPET+="DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}"$'\n'
[[ -n "${DEEPSEEK_BASE_URL:-}" ]] && ENV_SNIPPET+="DEEPSEEK_BASE_URL=${DEEPSEEK_BASE_URL}"$'\n'
[[ -n "${DEEPSEEK_MODEL:-}" ]] && ENV_SNIPPET+="DEEPSEEK_MODEL=${DEEPSEEK_MODEL}"$'\n'
[[ -n "${WECHAT_TOKEN:-}" ]] && ENV_SNIPPET+="WECHAT_TOKEN=${WECHAT_TOKEN}"$'\n'
ENV_SNIPPET+="SCHEDULE_AGENT_ENABLED=${SCHEDULE_AGENT_ENABLED:-true}"$'\n'
ENV_SNIPPET+="SCHEDULE_AGENT_DATA_DIR=./data/schedule_agent"$'\n'
ENV_SNIPPET+="WEB_DIST_DIR=${REMOTE_DIR}/web/dist"$'\n'

# 通过 base64 传片段，避免引号/特殊字符问题
ENV_B64="$(printf '%s' "$ENV_SNIPPET" | base64 | tr -d '\n')"
MYSQL_META_B64=""
if [[ "$DEPLOY_DB" == "mysql" ]]; then
  MYSQL_META="$(cat <<EOF
MYSQL_HOST=${MYSQL_HOST:-}
MYSQL_PORT=${MYSQL_PORT:-3306}
MYSQL_USER=${MYSQL_USER:-}
MYSQL_PASSWORD=${MYSQL_PASSWORD:-}
MYSQL_DATABASE=${MYSQL_DATABASE:-workshop}
EOF
)"
  MYSQL_META_B64="$(printf '%s' "$MYSQL_META" | base64 | tr -d '\n')"
fi

SSH_CMD "bash -s" <<REMOTE_INSTALL
set -euo pipefail
REMOTE_DIR="$REMOTE_DIR"
ARCHIVE_NAME="$ARCHIVE_NAME"
PYTHON_BIN="$PYTHON_REMOTE_BIN"
APP_PORT="$APP_PORT"
APP_WORKERS="$APP_WORKERS"
SERVICE_NAME="$SERVICE_NAME"
SEED_DEMO="$SEED_DEMO"
DEPLOY_DB="$DEPLOY_DB"
ENV_B64="$ENV_B64"
MYSQL_META_B64="$MYSQL_META_B64"

TMP_EXTRACT="/tmp/workshop-extract-\$\$"
rm -rf "\$TMP_EXTRACT"
mkdir -p "\$TMP_EXTRACT" "\$REMOTE_DIR"
tar xzf "/tmp/\$ARCHIVE_NAME" -C "\$TMP_EXTRACT"
SRC="\$(find "\$TMP_EXTRACT" -maxdepth 1 -type d -name 'workshop-assistant-*' | head -1)"
if [[ -z "\$SRC" ]]; then
  echo "解压后未找到 workshop-assistant-* 目录"
  exit 1
fi

KEEP_ENV=0
KEEP_DATA=0
KEEP_VENV=0
[[ -f "\$REMOTE_DIR/.env" ]] && { cp "\$REMOTE_DIR/.env" /tmp/workshop.env.bak; KEEP_ENV=1; }
[[ -d "\$REMOTE_DIR/data" ]] && { mv "\$REMOTE_DIR/data" /tmp/workshop.data.bak; KEEP_DATA=1; }
[[ -d "\$REMOTE_DIR/.venv" ]] && { mv "\$REMOTE_DIR/.venv" /tmp/workshop.venv.bak; KEEP_VENV=1; }

# 清空目标目录后写入新版本
find "\$REMOTE_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
cp -a "\$SRC"/. "\$REMOTE_DIR"/

if [[ "\$KEEP_DATA" == "1" ]]; then
  rm -rf "\$REMOTE_DIR/data"
  mv /tmp/workshop.data.bak "\$REMOTE_DIR/data"
fi
mkdir -p "\$REMOTE_DIR/data/uploads" "\$REMOTE_DIR/data/schedule_agent" "\$REMOTE_DIR/logs"

SNIP=\$(printf '%s' "\$ENV_B64" | base64 -d)
if [[ "\$KEEP_ENV" == "1" ]]; then
  mv /tmp/workshop.env.bak "\$REMOTE_DIR/.env"
  echo "==> 保留已有 .env，并同步本次 DB / DeepSeek 配置"
  # 去掉旧 DB / DeepSeek 相关行后追加本次片段中的对应行
  grep -vE '^(USE_SQLITE|DATABASE_URL|SQLITE_PATH|DEEPSEEK_API_KEY|DEEPSEEK_BASE_URL|DEEPSEEK_MODEL|SCHEDULE_AGENT_ENABLED)=' "\$REMOTE_DIR/.env" > /tmp/workshop.env.merged || true
  printf '%s\n' "\$SNIP" | grep -E '^(USE_SQLITE|DATABASE_URL|SQLITE_PATH|DEEPSEEK_API_KEY|DEEPSEEK_BASE_URL|DEEPSEEK_MODEL|SCHEDULE_AGENT_ENABLED)=' >> /tmp/workshop.env.merged || true
  mv /tmp/workshop.env.merged "\$REMOTE_DIR/.env"
else
  {
    echo "# generated by deploy.sh"
    printf '%s\n' "\$SNIP"
    if ! printf '%s\n' "\$SNIP" | grep -q '^SECRET_KEY='; then
      SK=\$(openssl rand -hex 24 2>/dev/null || python3.11 -c 'import secrets;print(secrets.token_hex(24))')
      echo "SECRET_KEY=\$SK"
    fi
    if ! printf '%s\n' "\$SNIP" | grep -q '^ADMIN_USERNAME='; then
      echo "ADMIN_USERNAME=admin"
      echo "ADMIN_PASSWORD=admin123"
    fi
  } > "\$REMOTE_DIR/.env"
  echo "==> 已生成首次 .env"
fi

if [[ "\$KEEP_VENV" == "1" ]]; then
  mv /tmp/workshop.venv.bak "\$REMOTE_DIR/.venv"
fi

cd "\$REMOTE_DIR"
chmod +x install.sh start.sh
export PYTHON_BIN
./install.sh

# MySQL：确保 workshop 库存在（与 u8s 同 RDS）
if [[ "\$DEPLOY_DB" == "mysql" && -n "\$MYSQL_META_B64" ]]; then
  echo "==> 确保 MySQL 库存在"
  printf '%s' "\$MYSQL_META_B64" | base64 -d > /tmp/workshop.mysql.env
  set -a
  # shellcheck disable=SC1091
  source /tmp/workshop.mysql.env
  set +a
  rm -f /tmp/workshop.mysql.env
  # shellcheck disable=SC1091
  source "\$REMOTE_DIR/.venv/bin/activate"
  python - <<'PY'
import os, sys
try:
    import pymysql
except ImportError:
    print("pymysql 未安装", file=sys.stderr)
    sys.exit(1)
host = os.environ["MYSQL_HOST"]
port = int(os.environ.get("MYSQL_PORT") or "3306")
user = os.environ["MYSQL_USER"]
password = os.environ["MYSQL_PASSWORD"]
db = os.environ.get("MYSQL_DATABASE") or "workshop"
if not host or not user:
    print("MYSQL_HOST/MYSQL_USER 未配置", file=sys.stderr)
    sys.exit(1)
# 库名只允许字母数字下划线
if not db.replace("_", "").isalnum():
    raise SystemExit("非法库名: {}".format(db))
conn = pymysql.connect(host=host, port=port, user=user, password=password, charset="utf8mb4", connect_timeout=15)
try:
    with conn.cursor() as cur:
        try:
            cur.execute(
                "CREATE DATABASE IF NOT EXISTS {} DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci".format(
                    chr(96) + db + chr(96)
                )
            )
            conn.commit()
            print("database created/exists: {}/{}".format(host, db))
        except pymysql.err.OperationalError as e:
            # 1044: 无建库权（如 znzroot 仅 znz.*）——尝试直接使用目标库
            if e.args and e.args[0] == 1044:
                print("no CREATE privilege; try use existing db: {}".format(db))
            else:
                raise
    # 验证可连接目标库
    conn.select_db(db)
    print("database ok: {}/{}".format(host, db))
finally:
    conn.close()
PY
fi

cat > "/etc/systemd/system/\${SERVICE_NAME}.service" <<UNIT
[Unit]
Description=Workshop Assistant (铁玉兰管家)
After=network.target

[Service]
Type=simple
WorkingDirectory=\${REMOTE_DIR}
Environment=WEB_DIST_DIR=\${REMOTE_DIR}/web/dist
EnvironmentFile=-\${REMOTE_DIR}/.env
ExecStart=\${REMOTE_DIR}/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port \${APP_PORT} --workers \${APP_WORKERS}
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable "\$SERVICE_NAME" >/dev/null

systemctl stop "\$SERVICE_NAME" 2>/dev/null || true
if command -v lsof >/dev/null 2>&1; then
  PIDS=\$(lsof -ti:"\$APP_PORT" 2>/dev/null || true)
  if [[ -n "\$PIDS" ]]; then
    kill \$PIDS 2>/dev/null || true
    sleep 2
    kill -9 \$PIDS 2>/dev/null || true
  fi
fi

if [[ "\$SEED_DEMO" == "1" ]] && [[ ! -f "\$REMOTE_DIR/data/.seeded" ]]; then
  echo "==> 灌入演示数据"
  # shellcheck disable=SC1091
  source "\$REMOTE_DIR/.venv/bin/activate"
  cd "\$REMOTE_DIR"
  if python scripts/seed_demo.py; then
    touch "\$REMOTE_DIR/data/.seeded"
    echo "==> 演示数据导入成功"
  else
    echo "==> 演示数据导入失败" >&2
    exit 1
  fi
fi

systemctl start "\$SERVICE_NAME"
rm -rf "\$TMP_EXTRACT" "/tmp/\$ARCHIVE_NAME"
echo "==> systemd 已启动: \$SERVICE_NAME"
REMOTE_INSTALL

# ========== 步骤5: 健康检查 ==========
log_step "步骤5: 健康检查 http://${REMOTE_HOST}:${APP_PORT}/api/health ..."
HEALTH_URL="http://${REMOTE_HOST}:${APP_PORT}/api/health"
ok=0
for i in $(seq 1 30); do
  body="$(curl -fsS --max-time 3 "$HEALTH_URL" 2>/dev/null || true)"
  if echo "$body" | grep -q '"ok"[[:space:]]*:[[:space:]]*true'; then
    log_info "健康检查通过: $body"
    ok=1
    break
  fi
  # 若外网安全组未放行，改走远程本机探测
  remote_body="$(SSH_CMD "curl -fsS --max-time 2 http://127.0.0.1:${APP_PORT}/api/health" 2>/dev/null || true)"
  if echo "$remote_body" | grep -q '"ok"[[:space:]]*:[[:space:]]*true'; then
    log_info "本机健康检查通过: $remote_body"
    log_warn "若本机 curl 外网地址失败，请在云安全组放行 TCP ${APP_PORT}"
    ok=1
    break
  fi
  log_warn "等待就绪... ($i/30)"
  sleep 2
done

if [[ "$ok" != "1" ]]; then
  log_error "健康检查失败。远程日志: journalctl -u ${SERVICE_NAME} -n 80 --no-pager"
  SSH_CMD "systemctl status ${SERVICE_NAME} --no-pager -l | head -40; journalctl -u ${SERVICE_NAME} -n 40 --no-pager" || true
  exit 1
fi

log_info "部署完成"
echo "  访问: http://${REMOTE_HOST}:${APP_PORT}/"
echo "  管理台: http://${REMOTE_HOST}:${APP_PORT}/admin"
echo "  健康: $HEALTH_URL"
echo "  服务: systemctl status ${SERVICE_NAME}"
echo "  认证模式: $DEPLOY_AUTH_MODE"
