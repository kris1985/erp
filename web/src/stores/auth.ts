import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import http from '@/api/http'
import {
  DEFAULT_INVENTORY,
  normalizeInventory,
  type InventoryCapabilityCode,
  type InventoryConfig,
} from '@/inventory/types'

export interface TenantChoice {
  tenant_id: number
  tenant_name: string
}

/** 读取本地缓存的后台角色列表；损坏/缺失时回退为空（纯生产员工）。 */
function readRoles(raw: string | null): string[] {
  if (!raw) return []
  try {
    const v = JSON.parse(raw)
    return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []
  } catch {
    return []
  }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('ws_token') || '')
  const displayName = ref(localStorage.getItem('ws_name') || '')
  const tenantId = ref(Number(localStorage.getItem('ws_tenant') || 0))
  const tenantName = ref(localStorage.getItem('ws_tenant_name') || '')
  const role = ref(localStorage.getItem('ws_role') || '')
  const baseRole = ref(localStorage.getItem('ws_base_role') || '')
  // 必须持久化：isPureStaff / 路由守卫靠它区分后台用户与纯生产员工，
  // 否则刷新后 roles 为空，admin 会被 /admin 守卫当成纯员工踢回 h5 页。
  const roles = ref<string[]>(readRoles(localStorage.getItem('ws_roles')))
  const actor = ref(localStorage.getItem('ws_actor') || 'employee')
  const employeeId = ref(Number(localStorage.getItem('ws_worker_id') || 0))
  const mustChangePassword = ref(localStorage.getItem('ws_must_change') === '1')
  const isLeader = ref(localStorage.getItem('ws_is_leader') === '1')
  const permissions = ref<string[]>([])
  const inventory = ref<InventoryConfig>(normalizeInventory(DEFAULT_INVENTORY))

  function persist() {
    localStorage.setItem('ws_token', token.value)
    localStorage.setItem('ws_name', displayName.value)
    localStorage.setItem('ws_tenant', String(tenantId.value))
    localStorage.setItem('ws_tenant_name', tenantName.value)
    localStorage.setItem('ws_role', role.value)
    localStorage.setItem('ws_base_role', baseRole.value)
    localStorage.setItem('ws_roles', JSON.stringify(roles.value))
    localStorage.setItem('ws_actor', actor.value)
    localStorage.setItem('ws_worker_id', String(employeeId.value || ''))
    localStorage.setItem('ws_must_change', mustChangePassword.value ? '1' : '0')
    localStorage.setItem('ws_is_leader', isLeader.value ? '1' : '0')
  }

  function setPermissions(list: string[] | undefined | null) {
    permissions.value = Array.isArray(list) ? [...list] : []
  }

  function setInventory(raw: unknown) {
    inventory.value = normalizeInventory(raw)
  }

  function hasPermission(code: string) {
    if (role.value === 'admin' || baseRole.value === 'admin' || roles.value.includes('admin')) return true
    return permissions.value.includes(code)
  }

  function hasCapability(code: InventoryCapabilityCode | string) {
    const caps = inventory.value.capabilities as Record<string, boolean>
    return !!caps[code]
  }

  async function refreshPermissions() {
    if (!token.value) {
      setPermissions([])
      return null
    }
    try {
      const res: any = await http.get('/auth/me')
      setPermissions(res.data?.permissions)
      if (res.data?.inventory) setInventory(res.data.inventory)
      if (res.data?.role) role.value = res.data.role
      if (Array.isArray(res.data?.roles)) roles.value = res.data.roles
      if (res.data?.base_role) baseRole.value = res.data.base_role
      if (res.data?.name) displayName.value = res.data.name
      if (res.data?.tenant_name) tenantName.value = res.data.tenant_name
      persist()
      return res.data || null
    } catch {
      return null
    }
  }

  function applyLoginPayload(d: any) {
    token.value = d.access_token || ''
    displayName.value = d.display_name || d.name || ''
    tenantId.value = d.tenant_id || 0
    tenantName.value = d.tenant_name || ''
    role.value = d.role || 'worker'
    roles.value = Array.isArray(d.roles) ? d.roles : []
    baseRole.value = d.base_role || ''
    actor.value = 'employee'
    employeeId.value = Number(d.id || d.employee_id || 0)
    mustChangePassword.value = !!d.must_change_password
    isLeader.value = !!d.is_leader
    setPermissions(d.permissions)
    setInventory(d.inventory)
    persist()
  }

  /** 登录：单账号（用户名或手机号）。返回 null 表示需选择租户（need_select）。 */
  async function login(identifier: string, password: string): Promise<null | { need_select: true; tenants: TenantChoice[] }> {
    const res: any = await http.post('/auth/login', { identifier, password })
    const d = res.data || {}
    if (d.need_select) {
      return { need_select: true, tenants: d.tenants || [] }
    }
    applyLoginPayload(d)
    return null
  }

  /** 多租户命中后选择工厂完成登录。 */
  async function selectTenant(identifier: string, password: string, tenantId: number) {
    const res: any = await http.post('/auth/login/select', { identifier, password, tenant_id: tenantId })
    applyLoginPayload(res.data || {})
  }

  async function changePassword(oldPassword: string, newPassword: string) {
    await http.post('/auth/change-password', {
      old_password: oldPassword,
      new_password: newPassword,
    })
    mustChangePassword.value = false
    persist()
  }

  function logout() {
    token.value = ''
    displayName.value = ''
    tenantId.value = 0
    tenantName.value = ''
    role.value = ''
    roles.value = []
    baseRole.value = ''
    actor.value = 'employee'
    employeeId.value = 0
    mustChangePassword.value = false
    isLeader.value = false
    permissions.value = []
    inventory.value = normalizeInventory(DEFAULT_INVENTORY)
    localStorage.removeItem('ws_token')
    localStorage.removeItem('ws_name')
    localStorage.removeItem('ws_tenant')
    localStorage.removeItem('ws_tenant_name')
    localStorage.removeItem('ws_role')
    localStorage.removeItem('ws_base_role')
    localStorage.removeItem('ws_roles')
    localStorage.removeItem('ws_actor')
    localStorage.removeItem('ws_worker_id')
    localStorage.removeItem('ws_must_change')
    localStorage.removeItem('ws_is_leader')
  }

  const isAdmin = () => role.value === 'admin' || baseRole.value === 'admin' || roles.value.includes('admin')
  const isTeamScoped = computed(() => false)
  /** 纯生产员工：无任何后台角色 → 使用生产端 UI（计件/工资/扫码报工）。
   * 同时看 base_role（已持久化）：兼容修复前已登录、localStorage 还没有 ws_roles 的存量会话。 */
  const isPureStaff = computed(() => roles.value.length === 0 && !baseRole.value)
  const showFinanceHome = computed(
    () =>
      !isPureStaff.value &&
      (role.value === 'admin' || baseRole.value === 'admin' || roles.value.includes('admin')),
  )
  // 兼容别名
  const isWorker = isPureStaff
  const workerId = employeeId

  return {
    token,
    displayName,
    tenantId,
    tenantName,
    role,
    roles,
    baseRole,
    actor,
    employeeId,
    workerId,
    mustChangePassword,
    isLeader,
    permissions,
    inventory,
    isWorker,
    isPureStaff,
    isTeamScoped,
    showFinanceHome,
    login,
    selectTenant,
    changePassword,
    logout,
    isAdmin,
    hasPermission,
    hasCapability,
    refreshPermissions,
    setPermissions,
    setInventory,
  }
})
