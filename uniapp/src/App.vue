<script setup lang="ts">
import { onLaunch } from '@dcloudio/uni-app'
import { isLoggedIn } from './services/auth'
import { get } from './services/http'
import { getProfile, getToken, setSession } from './services/storage'

onLaunch(async () => {
  if (!isLoggedIn()) {
    uni.reLaunch({ url: '/pages/login/index' })
    return
  }
  try {
    const me: any = await get('/auth/me')
    const cached = getProfile()
    if (cached && getToken()) {
      setSession(getToken(), {
        ...cached,
        displayName: me?.display_name || me?.name || cached.displayName,
        role: me?.role || cached.role,
        isLeader: Boolean(me?.is_leader),
        mustChangePassword: Boolean(me?.must_change_password),
      })
    }
    uni.reLaunch({ url: me?.must_change_password ? '/pages/change-password/index' : '/pages/home/index' })
  } catch {
    // 401 会由请求层清除失效会话并返回登录页。
    // 临时断网不应误删有效 Token，保留会话进入首页后由各页面提示网络状态。
    if (isLoggedIn()) uni.reLaunch({ url: getProfile()?.mustChangePassword ? '/pages/change-password/index' : '/pages/home/index' })
  }
})
</script>

<style lang="scss">
page {
  background: #f4f7fb;
  color: #172033;
}
</style>
