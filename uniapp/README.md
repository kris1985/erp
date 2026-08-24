# 铁玉兰管家 UniApp 移动端

这是现有 ERP 的 App/PDA 移动壳，保留 `web/` PC/H5 前端并复用同一套 `/api/v1` 后端。

当前第一阶段包含：

- 单账号登录及多工厂选择；
- App 原生扫码（不依赖 H5 `getUserMedia`）；
- 工位码、框/捆码、生产流转卡、箱唛识别；
- 扫码结果在 App 内置 WebView 中进入现有成熟 H5 业务页；
- API 和 H5 服务器地址环境化配置。

## 运行

1. 复制 `.env.example` 为 `.env`，填入手机/PDA 能访问的服务器地址。
2. 使用 HBuilderX 导入本目录，运行到 Android/iOS App。
3. 或安装依赖后运行 `npm run dev:h5` 进行界面联调。

注意：真机不能把服务器地址写成 `localhost`；`localhost` 指向手机/PDA 自身。正式环境建议 API 与 H5 都使用 HTTPS。

UniApp 登录存储与内置 H5 WebView 的存储相互独立，因此首次进入 H5 报工页时仍可能需要登录一次；WebView 会保留后续会话。完全取消二次登录需要在下一阶段将报工表单原生化，或增加后端签发的一次性登录交换码，不能通过 URL 直接传长期 Token。

## 下一阶段

将 `ScanReportView.vue`、`TraceUnitView.vue`、`FlowCardScanView.vue` 和 `CartonReportView.vue` 的表单逐页原生化，取消从 App 跳转现有 H5 页。工业 PDA 的硬件扫码键需要按设备厂家接入广播或原生 SDK 插件。
