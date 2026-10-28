import { reactive } from 'vue'

/** 各页当前标题。系统标题栏加不了粗，自定义栏从这里读。 */
export const pageTitles = reactive<Record<string, string>>({})

const backHandlers = new Map<string, () => boolean>()

export function setPageBackHandler(route: string, handler: (() => boolean) | null) {
  if (!route) return
  if (handler) backHandlers.set(route, handler)
  else backHandlers.delete(route)
}

/** 返回 true 表示页面自己处理了返回，导航栏不要再退出。 */
export function consumePageBack(route: string) {
  return backHandlers.get(route)?.() === true
}

export function installPageTitle() {
  const raw = uni.setNavigationBarTitle.bind(uni)
  uni.setNavigationBarTitle = ((options: UniNamespace.SetNavigationBarTitleOptions) => {
    const route = getCurrentPages().slice(-1)[0]?.route || ''
    const title = String(options?.title || '')
    if (route && title) pageTitles[route] = title
    return raw(options)
  }) as typeof uni.setNavigationBarTitle
}
