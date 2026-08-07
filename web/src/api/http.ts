import axios from 'axios'
import { showToast } from 'vant'
import { useAuthStore } from '@/stores/auth'

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
      if (!silent) showToast(body.error?.message || '请求失败')
      return Promise.reject(body)
    }
    return body
  },
  (err) => {
    const silent = Boolean(err.config?.silent)
    const detail = err.response?.data?.detail
    let msg = err.message || '网络错误'
    if (typeof detail === 'string') {
      msg = detail
    } else if (Array.isArray(detail) && detail.length) {
      msg = detail
        .map((d: { msg?: string }) => d?.msg)
        .filter(Boolean)
        .join('；') || '请求参数有误'
    } else if (detail != null) {
      msg = JSON.stringify(detail)
    }
    if (!silent) showToast(msg)
    if (err.response?.status === 401) {
      const auth = useAuthStore()
      auth.logout()
      location.href = `/login?redirect=${encodeURIComponent(location.pathname + location.search)}`
    }
    return Promise.reject(err)
  },
)

export default http
