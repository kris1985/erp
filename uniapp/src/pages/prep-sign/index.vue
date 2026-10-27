<template>
  <app-nav-bar />
  <view class="page">
    <view v-if="error" class="card">{{ error }}</view>
    <template v-else-if="slip">
      <view class="card">
        <text class="slot">备料码 {{ slip.slot }}</text>
        <text class="doc">{{ slip.header_no }}</text>
        <text class="muted">{{ slip.pairs }} 双</text>
      </view>
      <view class="card">
        <view v-for="line in slip.lines || []" :key="line.id" class="line">
          <view>
            <text class="name">{{ line.material_name }}</text>
            <text class="muted">{{ line.material_code }}{{ line.color_name ? ` · ${line.color_name}` : '' }}</text>
          </view>
          <text class="qty">{{ line.actual_qty }}{{ line.unit_name || '' }}</text>
        </view>
      </view>
      <view v-if="slip.status === 'signed'" class="card">{{ slip.picker_name || '领料人' }} 已确认领料</view>
      <view v-else-if="slip.status === 'cancelled'" class="card error">这张备料已取消</view>
      <view v-else class="card">
        <button class="submit" :disabled="submitting" @click="submit">确认领料</button>
      </view>
    </template>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { get, post } from '../../services/http'

const slip = ref<any>(null)
const error = ref('')
const submitting = ref(false)
let token = ''

onLoad(async (query) => {
  token = String(query?.token || '').trim()
  if (!token) {
    error.value = '缺少备料码'
    return
  }
  try {
    slip.value = await get(`/material-preps/by-token/${encodeURIComponent(token)}`)
    uni.setNavigationBarTitle({ title: '确认领料' })
  } catch (err: any) {
    error.value = err?.message || '备料码不存在'
  }
})

async function submit() {
  if (submitting.value) return
  submitting.value = true
  try {
    slip.value = await post(`/material-preps/by-token/${encodeURIComponent(token)}/sign`, {})
    uni.showToast({ title: '已确认领料人', icon: 'none' })
  } catch (err: any) {
    uni.showToast({ title: err?.message || '确认失败', icon: 'none' })
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped lang="scss">
.card { margin-bottom: 24rpx; padding: 28rpx; background: #fff; border-radius: 16rpx; }
.slot, .doc { display: block; color: #181b23; font-weight: 750; }
.doc { margin-top: 8rpx; font-size: 32rpx; }
.muted { display: block; margin-top: 6rpx; color: #727786; font-size: 24rpx; }
.line { display: flex; align-items: center; justify-content: space-between; gap: 16rpx; padding: 16rpx 0; }
.name { display: block; color: #181b23; font-size: 28rpx; }
.qty { color: #181b23; font-size: 28rpx; font-weight: 750; }
.error { color: #ba1a1a; }
.submit {
  width: 100%;
  height: 80rpx;
  border: 0;
  border-radius: 14rpx;
  background: #0057c2;
  color: #fff;
  font-size: 30rpx;
  font-weight: 750;
  line-height: 80rpx;
}
.submit::after { border: 0; }
</style>
