import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import http from '@/api/http'
import {
  DEFAULT_INVENTORY,
  normalizeInventory,
  type InventoryCapabilityCode,
  type InventoryConfig,
} from '@/inventory/types'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('ws_token') || '')
  const displayName = ref(localStorage.getItem('ws_name') || '')
  const tenantId = ref(Number(localStorage.getItem('ws_tenant') || 0))
  const role = ref(localStorage.getItem('ws_role') || '')
  const baseRole = ref(localStorage.getItem('ws_base_role') || '')
  const actor = ref(localStorage.getItem('ws_actor') || 'user')
  const workerId = ref(Number(localStorage.getItem('ws_worker_id') || 0))
  const mustChangePassword = ref(localStorage.getItem('ws_must_change') === '1')
  const permissions = ref<string[]>([])
  const inventory = ref<InventoryConfig>(normalizeInventory(DEFAULT_INVENTORY))

  function persist() {
    localStorage.setItem('ws_token', token.value)
    localStorage.setItem('ws_name', displayName.value)
    localStorage.setItem('ws_tenant', String(tenantId.value))
    localStorage.setItem('ws_role', role.value)
    localStorage.setItem('ws_base_role', baseRole.value)
    localStorage.setItem('ws_actor', actor.value)
    localStorage.setItem('ws_worker_id', String(workerId.value || ''))
    localStorage.setItem('ws_must_change', mustChangePassword.value ? '1' : '0')
  }

  function setPermissions(list: string[] | undefined | null) {
    permissions.value = Array.isArray(list) ? [...list] : []
  }

  function setInventory(raw: unknown) {
    inventory.value = normalizeInventory(raw)
  }

  function hasPermission(code: string) {
    if (role.value === 'admin') return true
    return permissions.value.includes(code)
  }

  function hasCapability(code: InventoryCapabilityCode | string) {
    const caps = inventory.value.capabilities as Record<string, boolean>
    return !!caps[code]
  }

  async function refreshPermissions() {
    if (!token.value || actor.value === 'worker') {
      setPermissions([])
      return null
    }
    try {
      const res: any = await http.get('/auth/me')
      setPermissions(res.data?.permissions)
      if (res.data?.inventory) setInventory(res.data.inventory)
      if (res.data?.role) role.value = res.data.role
      if (res.data?.base_role) baseRole.value = res.data.base_role
      if (res.data?.display_name) displayName.value = res.data.display_name
      persist()
      return res.data || null
    } catch {
      return null
    }
  }

  async function login(username: string, password: string) {
    const res: any = await http.post('/auth/login', { username, password })
    token.value = res.data.access_token
    displayName.value = res.data.display_name
    tenantId.value = res.data.tenant_id
    role.value = res.data.role || ''
    baseRole.value = res.data.base_role || res.data.role || ''
    actor.value = 'user'
    workerId.value = 0
    mustChangePassword.value = false
    setPermissions(res.data.permissions)
    setInventory(res.data.inventory)
    persist()
  }

  async function workerLogin(mobile: string, password: string) {
    const res: any = await http.post('/auth/worker/login', { mobile, password })
    token.value = res.data.access_token
    displayName.value = res.data.display_name
    tenantId.value = res.data.tenant_id
    role.value = res.data.role || 'worker'
    baseRole.value = ''
    actor.value = 'worker'
    workerId.value = res.data.worker_id
    mustChangePassword.value = !!res.data.must_change_password
    setPermissions([])
    setInventory(DEFAULT_INVENTORY)
    persist()
  }

  async function changeWorkerPassword(oldPassword: string, newPassword: string) {
    await http.post('/auth/worker/change-password', {
      old_password: oldPassword,
      new_password: newPassword,
    })
    mustChangePassword.value = false
    persist()
  }

  async function changeUserPassword(oldPassword: string, newPassword: string) {
    await http.post('/auth/change-password', {
      old_password: oldPassword,
      new_password: newPassword,
    })
  }

  async function changePassword(oldPassword: string, newPassword: string) {
    if (actor.value === 'worker') {
      await changeWorkerPassword(oldPassword, newPassword)
    } else {
      await changeUserPassword(oldPassword, newPassword)
    }
  }

  function logout() {
    token.value = ''
    displayName.value = ''
    tenantId.value = 0
    role.value = ''
    baseRole.value = ''
    actor.value = 'user'
    workerId.value = 0
    mustChangePassword.value = false
    permissions.value = []
    inventory.value = normalizeInventory(DEFAULT_INVENTORY)
    localStorage.removeItem('ws_token')
    localStorage.removeItem('ws_name')
    localStorage.removeItem('ws_tenant')
    localStorage.removeItem('ws_role')
    localStorage.removeItem('ws_base_role')
    localStorage.removeItem('ws_actor')
    localStorage.removeItem('ws_worker_id')
    localStorage.removeItem('ws_must_change')
  }

  const isAdmin = () => role.value === 'admin' || baseRole.value === 'admin'
  const isTeamScoped = computed(() => actor.value !== 'worker' && baseRole.value === 'leader')
  const showFinanceHome = computed(
    () => actor.value !== 'worker' && (role.value === 'admin' || baseRole.value === 'admin'),
  )
  const isWorker = computed(() => actor.value === 'worker')

  return {
    token,
    displayName,
    tenantId,
    role,
    baseRole,
    actor,
    workerId,
    mustChangePassword,
    permissions,
    inventory,
    isWorker,
    isTeamScoped,
    showFinanceHome,
    login,
    workerLogin,
    changeWorkerPassword,
    changeUserPassword,
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
