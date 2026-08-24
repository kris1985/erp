import { clearSession, getToken } from './storage'

// H5 默认与 ERP 同域；原生 App 打包时用 VITE_API_BASE_URL 覆盖为 HTTPS 绝对地址。
const API_BASE = String(import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

export interface ApiEnvelope<T> {
  ok?: boolean
  data?: T
  error?: { message?: string }
}

export async function request<T>(path: string, options: UniApp.RequestOptions = {}): Promise<T> {
  const token = getToken()
  const response = await uni.request({
    ...options,
    url: `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`,
    header: {
      'content-type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.header || {}),
    },
  })

  if (response.statusCode === 401) {
    clearSession()
    uni.reLaunch({ url: '/pages/login/index' })
    throw new Error('登录已失效，请重新登录')
  }
  const body = response.data as ApiEnvelope<T> | T
  if (response.statusCode < 200 || response.statusCode >= 300) {
    const detail = (body as any)?.detail
    throw new Error(typeof detail === 'string' ? detail : `请求失败（${response.statusCode}）`)
  }
  if ((body as ApiEnvelope<T>)?.ok === false) {
    throw new Error((body as ApiEnvelope<T>).error?.message || '请求失败')
  }
  return ((body as ApiEnvelope<T>)?.data ?? body) as T
}

export function post<T>(path: string, data: unknown) {
  return request<T>(path, { method: 'POST', data })
}

export function get<T>(path: string, data?: Record<string, unknown>) {
  return request<T>(path, { method: 'GET', data })
}

export function del<T>(path: string, data?: Record<string, unknown>) {
  const query = data
    ? Object.entries(data)
        .filter(([, value]) => value !== undefined && value !== null)
        .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
        .join('&')
    : ''
  return request<T>(`${path}${query ? `${path.includes('?') ? '&' : '?'}${query}` : ''}`, {
    method: 'DELETE',
  })
}
