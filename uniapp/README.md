# 铁玉兰管家 UniApp 移动端

这是现有 ERP 的 App/PDA 移动壳，保留 `web/` PC/H5 前端并复用同一套 `/api/v1` 后端。

当前第一阶段包含：

- 单账号登录及多工厂选择；
- App 原生扫码（不依赖 H5 `getUserMedia`）；
- 工位码、框/捆码、生产流转卡、箱唛识别；
- 扫码结果在 App 内置 WebView 中进入现有成熟 H5 业务页；
- API 和 H5 服务器地址环境化配置。

## 运行

1. 用 `.env.development` / `.env.production` 切换 API 域名（勿再依赖未提交的 `.env`）：
   - 开发：`npm run dev:app` / `dev:h5` → 读 `.env.development`（本机/局域网）
   - 生产：`npm run build:app` / `build:h5` → 读 `.env.production`（默认 `https://tyulan.cn`）
2. 真机调试改 `.env.development` 里的局域网 IP；IP 过期时 vite 会自动纠正。
3. 使用 HBuilderX 导入本目录，运行到 Android/iOS App；或 `npm run dev:h5` 做界面联调。

注意：真机不能把服务器地址写成 `localhost`；`localhost` 指向手机/PDA 自身。H5 始终走同源 `/api/v1`；原生 App 才会把 `VITE_API_BASE_URL` 打进包。

UniApp 登录存储与内置 H5 WebView 的存储相互独立，因此首次进入 H5 报工页时仍可能需要登录一次；WebView 会保留后续会话。完全取消二次登录需要在下一阶段将报工表单原生化，或增加后端签发的一次性登录交换码，不能通过 URL 直接传长期 Token。

## 下一阶段

将 `ScanReportView.vue`、`TraceUnitView.vue`、`FlowCardScanView.vue` 和 `CartonReportView.vue` 的表单逐页原生化，取消从 App 跳转现有 H5 页。工业 PDA 的硬件扫码键需要按设备厂家接入广播或原生 SDK 插件。
