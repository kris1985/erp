import axios from 'axios'
import { ElMessage } from 'element-plus'
import { apiErrorMessage } from '@/api/http'
import { useOpsAuthStore } from '@/stores/opsAuth'

const opsHttp = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
})

opsHttp.interceptors.request.use((config) => {
  const ops = useOpsAuthStore()
  if (ops.token) {
    config.headers.Authorization = `Bearer ${ops.token}`
  }
  return config
})

opsHttp.interceptors.response.use(
  (res) => {
    const body = res.data
    if (body && body.ok === false) {
      ElMessage({ type: 'error', message: apiErrorMessage(body), grouping: true, duration: 5000 })
      return Promise.reject(body)
    }
    return body
  },
  (err) => {
    const data = err.response?.data
    const status = err.response?.status
    const fallback = status ? `请求失败（${status}）` : '网络连接失败，请检查网络后重试'
    ElMessage({ type: 'error', message: apiErrorMessage(data, fallback), grouping: true, duration: 5000 })
    const url = String(err.config?.url || '')
    if (status === 401 && !url.includes('/operators/login')) {
      useOpsAuthStore().logout()
      const next = location.pathname + location.search
      location.href = `/ops/login?redirect=${encodeURIComponent(next)}`
    }
    return Promise.reject(err)
  },
)

export default opsHttp
