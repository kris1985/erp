<template>
  <app-nav-bar />
  <view class="page">
    <view v-if="error" class="card label-card">{{ error }}</view>
    <view v-else-if="item" class="card label-card">
      <text class="label-kind">物料</text>
      <text class="label-code">{{ item.product_code }}</text>
      <text class="label-name">{{ item.name || '—' }}</text>
      <view class="label-row"><text>颜色</text><text>{{ item.color_name || '—' }}</text></view>
      <view class="label-row"><text>分类</text><text>{{ item.category_name || '—' }}</text></view>
      <view class="label-row"><text>供应商</text><text>{{ item.partner_name || '—' }}</text></view>
      <view class="label-row"><text>单位</text><text>{{ item.pricing_unit_name || '—' }}</text></view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { get } from '../../services/http'

const item = ref<any>(null)
const error = ref('')

onLoad(async (query) => {
  const code = String(query?.code || '').trim()
  if (!code) {
    error.value = '缺少物料编号'
    return
  }
  try {
    item.value = await get('/supplier-products/by-code', { code })
  } catch {
    error.value = '物料不存在或无权查看'
  }
})
</script>

<style scoped lang="scss">
.label-card {
  padding: 32rpx;
}
.label-kind {
  display: block;
  color: #666;
  font-size: 24rpx;
  letter-spacing: 0.14em;
}
.label-code {
  display: block;
  margin-top: 12rpx;
  font-size: 40rpx;
  font-weight: 700;
  word-break: break-all;
}
.label-name {
  display: block;
  margin: 8rpx 0 20rpx;
  font-size: 30rpx;
}
.label-row {
  display: flex;
  justify-content: space-between;
  gap: 24rpx;
  padding: 16rpx 0;
  border-top: 1px solid #eee;
  font-size: 28rpx;
}
</style>
