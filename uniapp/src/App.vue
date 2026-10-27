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
/* 主页以外的系统标题栏：纯色，白字 */
.uni-page-head {
  background: #0e4fa8 !important;
}
.uni-page-head .uni-page-head__title,
.uni-page-head .uni-page-head-btn,
.uni-page-head .uni-btn-icon {
  color: #fff !important;
}
.uni-page-head .uni-page-head__title {
  font-weight: 700 !important;
}
.app-nav-bar + .page,
.app-nav-bar + .acceptance-page {
  min-height: calc(100vh - var(--app-nav-offset, calc(44px + var(--status-bar-height, 0px))));
}
uni-page[data-page="pages/home/index"] uni-page-body {
  background: #f2f5f9;
}
</style>
