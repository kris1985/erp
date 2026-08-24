<template>
  <view class="native-tabbar">
    <button class="native-tab" :class="{ active: active === 'home' }" @click="go('/pages/home/index')"><text class="native-tab__icon">⌂</text><text>首页</text></button>
    <button class="native-tab" :class="{ active: active === 'worklogs' }" @click="go('/pages/worklogs/index')"><text class="native-tab__icon">▤</text><text>计件</text></button>
    <button class="native-scan" @click="scan"><text>⌗</text></button>
    <button class="native-tab" :class="{ active: active === 'salary' }" @click="go('/pages/salary/index')"><text class="native-tab__icon">¥</text><text>工资</text></button>
    <button class="native-tab" :class="{ active: active === 'mine' }" @click="go('/pages/mine/index')"><text class="native-tab__icon">○</text><text>我的</text></button>
  </view>
</template>
<script setup lang="ts">
import { parseScanText } from '../services/scanner'
defineProps<{ active: 'home' | 'worklogs' | 'salary' | 'mine' }>()
let scanning = false
function go(url: string) { uni.redirectTo({ url }) }
function scan() {
  if (scanning) return
  scanning = true
  uni.scanCode({
    scanType: ['qrCode', 'barCode'], autoDecodeCharset: true,
    success: (result) => {
      const target = parseScanText(result.result)
      if (target) {
        uni.navigateTo({ url: `/pages/report/index?target=${encodeURIComponent(JSON.stringify(target))}` })
      }
      else uni.showToast({ title: '无法识别该二维码', icon: 'none' })
    },
    fail: (error) => { if (!String(error.errMsg || '').includes('cancel')) uni.showToast({ title: '扫码失败，请检查相机权限', icon: 'none' }) },
    complete: () => { scanning = false },
  })
}
</script>
