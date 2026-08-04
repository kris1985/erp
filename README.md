# 铁玉兰管家

> 微信里的 AI 车间管家，接单-派工-报工-算薪，一句话闭环。

本仓库是 **MVP + 管理台**：手动接单 + 语音/文字报工（规则 NLU）+ 个人计件/返修 + 查工资/进度 + **Vue H5 现场端** + **Element Plus PC 管理后台**。  
架构：**FastAPI JSON API（`/api/v1`）+ Vue3**，同仓 monorepo，**单镜像同域部署**，便于日后 uniapp 复用同一套 API。

## 快速开始（本机 MySQL）

开发库与 [chatbi](../chatbi) local 同源：`root` / `123456` @ `localhost:3306`，库名 `workshop`。

```bash
# 建库（首次）
mysql -u root -p123456 -h localhost -e "CREATE DATABASE IF NOT EXISTS workshop DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

cd workshop-assistant
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

python scripts/seed_demo.py
uvicorn app.main:app --reload --port 8000
```

无 MySQL 时可临时改 `.env`：`USE_SQLITE=true`。

另开终端启动前端开发（代理 `/api` → 8000）：

```bash
cd web && npm install && npm run dev
```

- 管理后台（H5）：http://127.0.0.1:5173  
- PC 管理台：http://127.0.0.1:5173/admin  
- API 文档：http://127.0.0.1:8000/docs  
- 账号：`admin` / `admin123`（管理员）；`manager` / `manager123`（主管）  
- 员工登录：手机号（如 `13800138001`）+ 默认密码 `123456`，**首次登录须改密**  
- 演示订单：`230711` / `230712`，工人：张三 / 李四 / 王五  
- 工位扫码：`/scan/ZC-01` → 自动预选派给张三的针车在制单（多单可更换）  
- 派工配额：订单「派工」可填每人可报上限；未派完进入「未分配池」；请假点「收回剩余」锁到已报，再从池改派；PC 可按色码派工；H5 主管可改派；扫码候选自动隐藏配额已满的单
- 进度看板：PC 管理台首页，看在制单/瓶颈工序/今日产量/交期风险
- 订单：支持改色码明细；CSV 批量导入（下载模板）
- 补数/尾数：计价设置可配，也可「一键补齐」；扫码/对话可报

生产同域打包：

```bash
cd web && npm run build
uvicorn app.main:app --port 8000
```

或 Docker 只跑 App（仍连本机 MySQL）：

```bash
docker compose up --build
# http://localhost:8000
```

## DevChat 示例

在后台「对话」页选择「张三」后发送：

- `230711 红 37码 针车 做了100双`
- `230711 红 37码 针车 返修了50双`
- `230711 红 37码 针车 补数了20双` / `尾数了10双`
- `230711 成型 做了300双`（成型为集体工序：先派工多人，再均分计件）
- `我这个月做了多少了？`
- `230711进度` / `今天整体产量`

## 微信公众号

回调 URL：`https://你的域名/api/wechat/callback`  
Token 与环境变量 `WECHAT_TOKEN` 一致。  
语音：优先使用微信自带 `Recognition` 字段；否则走 `AsrAdapter` 可替换实现。

## 目录

- `app/` FastAPI、模型、领域服务、微信回调  
- `web/` Vue3 + Vant H5  
- `scripts/seed_demo.py` 演示数据  
- `tests/` 报工/工资/微信验签单测  

## MVP 范围外（后续）

AI 接单、按数量拆派工、uniapp 客户端工程。
