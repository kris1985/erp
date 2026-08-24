import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'

export default defineConfig({
  // H5 与 PC 管理台同域发布到 /mobile/，避免两套 Vite 产物争用 /assets。
  base: '/mobile/',
  plugins: [uni()],
  server: {
    // 开发环境与 PC 端的 5173 分开，避免请求落到错误的 Vite 服务。
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/uploads': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
