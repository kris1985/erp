<script setup lang="ts">
import { onLaunch } from '@dcloudio/uni-app'
import { appEntryUrl, isLoggedIn } from './services/auth'

onLaunch(() => {
  // 启动页是登录页。已登录时立刻进入首页，不要等 /auth/me，否则会先停在登录表单上。
  if (isLoggedIn()) uni.reLaunch({ url: appEntryUrl() })
})
</script>

<style lang="scss">
page {
  background: #faf9ff;
  color: #181b23;
  font-family: 'Manrope', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}
uni-page[data-page="pages/home/index"] uni-page-body {
  background: #f2f5f9;
}
</style>
