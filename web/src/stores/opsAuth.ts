import { defineStore } from 'pinia'
import { ref } from 'vue'

/** 运营登录态与工厂后台分开，避免互相顶掉。 */
export const useOpsAuthStore = defineStore('ops-auth', () => {
  const token = ref(localStorage.getItem('ops_token') || '')
  const name = ref(localStorage.getItem('ops_name') || '')

  function setSession(data: { access_token: string; name?: string }) {
    token.value = data.access_token
    name.value = data.name || ''
    localStorage.setItem('ops_token', token.value)
    localStorage.setItem('ops_name', name.value)
  }

  function logout() {
    token.value = ''
    name.value = ''
    localStorage.removeItem('ops_token')
    localStorage.removeItem('ops_name')
  }

  return { token, name, setSession, logout }
})
