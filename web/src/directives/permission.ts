import type { Directive } from 'vue'
import { useAuthStore } from '@/stores/auth'

type PermissionBinding = string | string[]

function allowed(value: PermissionBinding | undefined): boolean {
  const auth = useAuthStore()
  const codes = Array.isArray(value) ? value : value ? [value] : []
  return codes.length === 0 || codes.some((code) => auth.hasPermission(code))
}

const originalDisplay = Symbol('permissionOriginalDisplay')
type PermissionElement = HTMLElement & { [originalDisplay]?: string }

function applyPermission(el: PermissionElement, value: PermissionBinding | undefined) {
  if (el[originalDisplay] === undefined) el[originalDisplay] = el.style.display
  el.style.display = allowed(value) ? el[originalDisplay] : 'none'
}

/** 任一权限满足时显示元素；否则隐藏，并支持动态权限值切换。 */
export const permissionDirective: Directive<HTMLElement, PermissionBinding> = {
  mounted: (el, binding) => applyPermission(el, binding.value),
  updated: (el, binding) => applyPermission(el, binding.value),
}
