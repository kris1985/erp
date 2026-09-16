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
  role?: string
  base_role?: string
  is_leader?: boolean
  must_change_password?: boolean
  need_select?: boolean
  tenants?: TenantChoice[]
  feature_permissions?: string[]
  process_ids?: number[]
  process_names?: string[]
}

export type LoginResult = { needSelect: false } | { needSelect: true; tenants: TenantChoice[] }

function save(payload: LoginPayload) {
  if (!payload.access_token) throw new Error('登录响应缺少访问令牌')
  const profile: UserProfile = {
    id: Number(payload.id || payload.employee_id || 0),
    displayName: payload.display_name || payload.name || '',
    tenantName: payload.tenant_name || '',
    role: payload.base_role || payload.role || 'worker',
    isLeader: Boolean(payload.is_leader),
    mustChangePassword: Boolean(payload.must_change_password),
    featurePermissions: Array.isArray(payload.feature_permissions) ? payload.feature_permissions : [],
    processIds: Array.isArray(payload.process_ids) ? payload.process_ids.map(Number).filter(Boolean) : [],
    processNames: Array.isArray(payload.process_names) ? payload.process_names.map(String).filter(Boolean) : [],
  }
  setSession(payload.access_token, profile)
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
