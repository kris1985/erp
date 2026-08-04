import { defineStore } from 'pinia'
import { ref } from 'vue'
import http from '@/api/http'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('ws_token') || '')
  const displayName = ref(localStorage.getItem('ws_name') || '')
  const tenantId = ref(Number(localStorage.getItem('ws_tenant') || 0))

  async function login(username: string, password: string) {
    const res: any = await http.post('/auth/login', { username, password })
    token.value = res.data.access_token
    displayName.value = res.data.display_name
    tenantId.value = res.data.tenant_id
    localStorage.setItem('ws_token', token.value)
    localStorage.setItem('ws_name', displayName.value)
    localStorage.setItem('ws_tenant', String(tenantId.value))
  }

  function logout() {
    token.value = ''
    displayName.value = ''
    tenantId.value = 0
    localStorage.removeItem('ws_token')
    localStorage.removeItem('ws_name')
    localStorage.removeItem('ws_tenant')
  }

  return { token, displayName, tenantId, login, logout }
})
