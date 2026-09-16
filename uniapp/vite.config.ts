import os from 'node:os'
import { defineConfig, loadEnv } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'

function isPrivateIpv4(host: string): boolean {
  return /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host)
}

function firstLanIpv4(): string | undefined {
  try {
    const nets = os.networkInterfaces()
    for (const entries of Object.values(nets)) {
      for (const net of entries || []) {
        // 忽略 Docker/VPN 等虚拟网卡（例如 198.18.x.x），仅使用设备可访问的局域网地址。
        if (net.family === 'IPv4' && !net.internal && isPrivateIpv4(net.address)) return net.address
      }
    }
  } catch {
    // 受限环境可能读不到网卡，保留 .env 原值。
  }
  return undefined
}

/** 开发时若 .env 写的是过期局域网 IP，自动换成当前网卡地址，避免 App 真机请求超时。 */
function resolveDevApiBase(configured: string | undefined, lanIp: string | undefined): string | undefined {
  if (!configured || !lanIp) return configured
  try {
    const url = new URL(configured)
    if (!isPrivateIpv4(url.hostname) || url.hostname === lanIp) return configured
    url.hostname = lanIp
    return url.toString().replace(/\/$/, '')
  } catch {
    return configured
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const lanIp = firstLanIpv4()
  const apiBase = resolveDevApiBase(env.VITE_API_BASE_URL, lanIp)
  const h5Base = resolveDevApiBase(env.VITE_H5_BASE_URL, lanIp)

  if (env.VITE_API_BASE_URL && apiBase && apiBase !== env.VITE_API_BASE_URL) {
    console.info(`[uniapp] VITE_API_BASE_URL 局域网 IP 已过期，自动改为 ${apiBase}`)
  }

  return {
    // H5 与 PC 管理台同域发布到 /mobile/，避免两套 Vite 产物争用 /assets。
    base: '/mobile/',
    plugins: [uni()],
    define: {
      // 覆盖 import.meta.env，确保 App 打包/运行拿到可达地址。
      ...(apiBase ? { 'import.meta.env.VITE_API_BASE_URL': JSON.stringify(apiBase) } : {}),
      ...(h5Base ? { 'import.meta.env.VITE_H5_BASE_URL': JSON.stringify(h5Base) } : {}),
    },
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
  }
})
