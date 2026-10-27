import { reactive } from 'vue'

/** 各页当前标题。系统标题栏加不了粗，自定义栏从这里读。 */
export const pageTitles = reactive<Record<string, string>>({})

export function installPageTitle() {
  const raw = uni.setNavigationBarTitle.bind(uni)
  uni.setNavigationBarTitle = ((options: UniNamespace.SetNavigationBarTitleOptions) => {
    const route = getCurrentPages().slice(-1)[0]?.route || ''
    const title = String(options?.title || '')
    if (route && title) pageTitles[route] = title
    return raw(options)
  }) as typeof uni.setNavigationBarTitle
}
