import { watch, type Directive } from 'vue'
import { useAuthStore } from '@/stores/auth'

type PermissionBinding = string | string[]

/** 任一权限满足即可。管理员在 hasPermission 里始终通过。 */
export function canPermission(value: PermissionBinding | undefined): boolean {
  const auth = useAuthStore()
  const codes = Array.isArray(value) ? value : value ? [value] : []
  return codes.length === 0 || codes.some((code) => auth.hasPermission(code))
}

function allowed(value: PermissionBinding | undefined): boolean {
  return canPermission(value)
}

declare module 'vue' {
  interface ComponentCustomProperties {
    $can: typeof canPermission
  }
}

const originalDisplay = Symbol('permissionOriginalDisplay')
const stopWatch = Symbol('permissionStopWatch')
const currentBinding = Symbol('permissionBinding')
type PermissionElement = HTMLElement & {
  [originalDisplay]?: string
  [stopWatch]?: () => void
  [currentBinding]?: PermissionBinding | undefined
}

function applyPermission(el: PermissionElement, value: PermissionBinding | undefined) {
  if (el[originalDisplay] === undefined) el[originalDisplay] = el.style.display
  el.style.display = allowed(value) ? el[originalDisplay] : 'none'
}

function trackPermission(el: PermissionElement, value: PermissionBinding | undefined) {
  el[currentBinding] = value
  applyPermission(el, value)
  if (el[stopWatch]) return
  const auth = useAuthStore()
  el[stopWatch] = watch(
    () => `${auth.role}|${auth.baseRole}|${auth.roles.join(',')}|${auth.permissions.join(',')}`,
    () => applyPermission(el, el[currentBinding]),
  )
}

/**
 * 任一权限满足时显示元素；否则隐藏。
 * 只对单根 DOM 生效（按钮、div）。el-dropdown-item 是多根组件，指令不会执行，菜单项用 v-if="$can('code')"。
 */
export const permissionDirective: Directive<PermissionElement, PermissionBinding> = {
  mounted: (el, binding) => trackPermission(el, binding.value),
  updated: (el, binding) => trackPermission(el, binding.value),
  unmounted: (el) => {
    el[stopWatch]?.()
    el[stopWatch] = undefined
  },
}
