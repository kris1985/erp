import axios from 'axios'
import { ElMessage } from 'element-plus'
import { showToast } from 'vant'
import { useAuthStore } from '@/stores/auth'

type ApiErrorPayload = {
  detail?: unknown
  message?: unknown
  error?: unknown
}

function readable(value: unknown): string {
  if (typeof value === 'string') {
    const text = value.trim()
    return text.startsWith('<') ? '' : text
  }
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === 'string') return item.trim()
        if (!item || typeof item !== 'object') return ''
        const row = item as { msg?: unknown; message?: unknown; loc?: unknown[] }
        const text = readable(row.msg) || readable(row.message)
        const field = Array.isArray(row.loc)
          ? row.loc.filter((part) => part !== 'body').join('.')
          : ''
        return text && field ? `${field}：${text}` : text
      })
      .filter(Boolean)
      .join('；')
  }
  if (value && typeof value === 'object') {
    const object = value as { message?: unknown; msg?: unknown; detail?: unknown }
    return readable(object.message) || readable(object.msg) || readable(object.detail)
  }
  return ''
}

export function apiErrorMessage(payload: unknown, fallback = '请求失败'): string {
  if (!payload || typeof payload !== 'object') return readable(payload) || fallback
  const data = payload as ApiErrorPayload
  return (
    readable(data.detail) ||
    readable(data.message) ||
    readable(data.error) ||
    fallback
  )
}

function showRequestError(message: string) {
  // 后台弹窗由 Element Plus 管理层级；Vant Toast 可能落在 el-dialog 遮罩后面。
  if (typeof location !== 'undefined' && location.pathname.startsWith('/admin')) {
    ElMessage({ type: 'error', message, grouping: true, duration: 5000 })
  } else {
    showToast({ type: 'fail', message, duration: 5000, wordBreak: 'break-word' })
  }
}

const http = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
})

http.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

http.interceptors.response.use(
  (res) => {
    const body = res.data
    if (body && body.ok === false) {
      const silent = Boolean((res.config as { silent?: boolean } | undefined)?.silent)
      if (!silent) showRequestError(apiErrorMessage(body))
      return Promise.reject(body)
    }
    return body
  },
  (err) => {
    const silent = Boolean(err.config?.silent)
    const data = err.response?.data
    const status = err.response?.status
    const fallback = status === 500
      ? '服务器内部错误，请稍后重试或联系管理员'
      : status
        ? `请求失败（${status}）`
        : err.code === 'ECONNABORTED'
          ? '请求超时，请稍后重试'
          : '网络连接失败，请检查网络后重试'
    const msg = apiErrorMessage(data, fallback)
    if (!silent) showRequestError(msg)
    if (err.response?.status === 401) {
      const url = err.config?.url || ''
      // 登录接口失败只提示，不跳转刷新（登录页本身就能重试）
      if (!url.includes('/auth/login')) {
        const auth = useAuthStore()
        auth.logout()
        // 按入口分流：后台路径回后台登录页，其余回手机端登录页
        const loginPath = location.pathname.startsWith('/admin') ? '/admin/login' : '/login'
        location.href = `${loginPath}?redirect=${encodeURIComponent(location.pathname + location.search)}`
      }
    }
    return Promise.reject(err)
  },
)

export default http
