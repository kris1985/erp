/**
 * 组织设置（工序段重构 33.1/33.3）：enable_teams / team_label / skiving_enabled。
 *
 * 启动时从 GET /org/settings 拉取一次（惰性，带缓存），供各页面读取；
 * t('team') 术语函数（D5）：按 team_label 输出 班组/部/产线/班。
 */
import { ref } from 'vue'
import http from '@/api/http'

export interface OrgSettings {
  enable_teams: boolean
  team_label: string
  skiving_enabled: boolean
}

const cache = ref<OrgSettings | null>(null)
let loading: Promise<OrgSettings> | null = null

export async function fetchOrgSettings(force = false): Promise<OrgSettings> {
  if (cache.value && !force) return cache.value
  if (!loading) {
    loading = (async () => {
      const res: any = await http.get('/org/settings')
      const data = res?.data || {}
      cache.value = {
        enable_teams: Boolean(data.enable_teams),
        team_label: data.team_label || '班组',
        skiving_enabled: Boolean(data.skiving_enabled),
      }
      return cache.value
    })()
  }
  try {
    return await loading
  } finally {
    loading = null
  }
}

export function useOrgSettings() {
  return {
    settings: cache,
    load: fetchOrgSettings,
  }
}

/** 车间单位叫法（D5）：班组/部/产线/班。默认'班组'。 */
export function teamLabel(): string {
  return cache.value?.team_label || '班组'
}

/** 术语函数 t('team')：按租户配置输出班组叫法。 */
export function t(key: 'team' | string): string {
  if (key === 'team') return teamLabel()
  return key
}
