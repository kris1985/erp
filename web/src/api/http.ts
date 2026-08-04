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
      showToast(body.error?.message || '请求失败')
      return Promise.reject(body)
    }
    return body
  },
  (err) => {
    const msg = err.response?.data?.detail || err.message || '网络错误'
    showToast(typeof msg === 'string' ? msg : JSON.stringify(msg))
    if (err.response?.status === 401) {
      const auth = useAuthStore()
      auth.logout()
      location.hash = '#/login'
    }
    return Promise.reject(err)
  },
)

export default http
