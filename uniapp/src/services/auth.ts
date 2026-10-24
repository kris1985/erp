import { post } from './http'
import { clearSession, getProfile, getToken, setSession, type UserProfile } from './storage'

interface TenantChoice {
  tenant_id: number
  tenant_name: string
}

interface LoginPayload {
  access_token?: string
  id?: number
  employee_id?: number
  display_name?: string
  name?: string
  tenant_name?: string
  department_id?: number | null
  department_name?: string | null
  role?: string
  base_role?: string
  is_leader?: boolean
  must_change_password?: boolean
  need_select?: boolean
  tenants?: TenantChoice[]
  feature_permissions?: string[]
  permissions?: string[]
  process_ids?: number[]
  process_names?: string[]
}

export type LoginResult = { needSelect: false } | { needSelect: true; tenants: TenantChoice[] }

function profileFromPayload(payload: LoginPayload, cached: UserProfile | null = null): UserProfile {
  return {
    id: Number(payload.id || payload.employee_id || cached?.id || 0),
    displayName: payload.display_name || payload.name || cached?.displayName || '',
    tenantName: payload.tenant_name || cached?.tenantName || '',
    departmentId: payload.department_id ?? cached?.departmentId ?? null,
    departmentName: payload.department_name || cached?.departmentName || '',
    role: payload.base_role || payload.role || cached?.role || 'worker',
    isLeader: Boolean(payload.is_leader),
    mustChangePassword: Boolean(payload.must_change_password),
    featurePermissions: Array.isArray(payload.feature_permissions) ? payload.feature_permissions : (cached?.featurePermissions || []),
    permissions: Array.isArray(payload.permissions) ? payload.permissions.map(String) : (cached?.permissions || []),
    processIds: Array.isArray(payload.process_ids) ? payload.process_ids.map(Number).filter(Boolean) : (cached?.processIds || []),
    processNames: Array.isArray(payload.process_names) ? payload.process_names.map(String).filter(Boolean) : (cached?.processNames || []),
  }
}

function save(payload: LoginPayload) {
  if (!payload.access_token) throw new Error('登录响应缺少访问令牌')
  setSession(payload.access_token, profileFromPayload(payload))
}

/** 用 /auth/me 刷新本地资料。令牌沿用当前会话。 */
export function syncProfile(payload: LoginPayload) {
  const token = getToken()
  if (!token) return null
  const profile = profileFromPayload(payload, getProfile())
  setSession(token, profile)
  return profile
}

export function appEntryUrl() {
  return getProfile()?.mustChangePassword ? '/pages/change-password/index' : '/pages/home/index'
}

export function isLoggedIn() {
  return Boolean(getToken())
}

export async function login(identifier: string, password: string): Promise<LoginResult> {
  const payload = await post<LoginPayload>('/auth/login', { identifier, password })
  if (payload.need_select) {
    return { needSelect: true, tenants: payload.tenants || [] }
  }
  save(payload)
  return { needSelect: false }
}

export async function selectTenant(identifier: string, password: string, tenantId: number) {
  const payload = await post<LoginPayload>('/auth/login/select', {
    identifier,
    password,
    tenant_id: tenantId,
  })
  save(payload)
}

export async function changePassword(oldPassword: string, newPassword: string) {
  await post('/auth/change-password', { old_password: oldPassword, new_password: newPassword })
  const token = getToken()
  const profile = getProfile()
  if (token && profile) setSession(token, { ...profile, mustChangePassword: false })
}

export function logout() {
  clearSession()
  uni.reLaunch({ url: '/pages/login/index' })
}
