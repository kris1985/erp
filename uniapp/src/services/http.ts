import { clearSession, getToken } from './storage'

function resolveApiBase() {
  let base = String(import.meta.env.VITE_API_BASE_URL || '/api/v1')
  // H5 始终走同源接口（开发时由 Vite 代理），避免本地 App 的局域网地址被打进 H5。
  // #ifdef H5
  base = '/api/v1'
  // #endif
  return base.replace(/\/$/, '')
}

// 原生 App 打包时用 VITE_API_BASE_URL 覆盖为设备可访问的绝对地址。
const API_BASE = resolveApiBase()
const REQUEST_TIMEOUT_MS = 15_000

export interface ApiEnvelope<T> {
  ok?: boolean
  data?: T
  error?: { message?: string }
}

export async function request<T>(path: string, options: UniApp.RequestOptions = {}): Promise<T> {
  const token = getToken()
  const url = `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`
  const method = options.method || 'GET'
  const startedAt = Date.now()
  console.info('[http] request', { method, url })

  let response: UniApp.RequestSuccessCallbackResult
  try {
    response = await uni.request({
      ...options,
      url,
      timeout: options.timeout ?? REQUEST_TIMEOUT_MS,
      header: {
        'content-type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.header || {}),
      },
    })
  } catch (error: any) {
    const elapsedMs = Date.now() - startedAt
    console.error('[http] network error', { method, url, elapsedMs, error: error?.errMsg || error?.message || error })
    const reason = String(error?.errMsg || error?.message || '')
    if (/timeout/i.test(reason)) throw new Error('请求超时，请检查服务器地址和网络连接')
    throw new Error('无法连接服务器，请检查服务器地址和网络连接')
  }

  console.info('[http] response', {
    method,
    url,
    statusCode: response.statusCode,
    elapsedMs: Date.now() - startedAt,
  })

  if (response.statusCode === 401) {
    // 登录失败是账号/密码错误，不是已有会话失效，不能重启当前登录页。
    if (!path.startsWith('/auth/login')) {
      clearSession()
      uni.reLaunch({ url: '/pages/login/index' })
      throw new Error('登录已失效，请重新登录')
    }
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

export function patch<T>(path: string, data: unknown) {
  return request<T>(path, { method: 'PATCH', data })
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

export function uploadFile<T>(path: string, filePath: string, name = 'file') {
  const token = getToken()
  const url = `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`
  return new Promise<T>((resolve, reject) => {
    uni.uploadFile({
      url,
      filePath,
      name,
      header: token ? { Authorization: `Bearer ${token}` } : {},
      success: response => {
        if (response.statusCode === 401) {
          clearSession()
          uni.reLaunch({ url: '/pages/login/index' })
          reject(new Error('登录已失效，请重新登录'))
          return
        }
        let body: ApiEnvelope<T> | T
        try {
          body = JSON.parse(response.data || '{}')
        } catch {
          reject(new Error('上传失败'))
          return
        }
        if (response.statusCode < 200 || response.statusCode >= 300) {
          const detail = (body as any)?.detail
          reject(new Error(typeof detail === 'string' ? detail : `上传失败（${response.statusCode}）`))
          return
        }
        if ((body as ApiEnvelope<T>)?.ok === false) {
          reject(new Error((body as ApiEnvelope<T>).error?.message || '上传失败'))
          return
        }
        resolve(((body as ApiEnvelope<T>)?.data ?? body) as T)
      },
      fail: error => reject(new Error(error?.errMsg || '上传失败')),
    })
  })
}
