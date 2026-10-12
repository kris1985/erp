<template>
  <view class="page">
    <view v-if="error" class="card">{{ error }}</view>
    <template v-else-if="slip">
      <view class="card">
        <text class="kind">{{ slip.kind_label }}</text>
        <text class="doc">{{ slip.doc_no }}</text>
        <text v-if="slip.header_no" class="muted">生产单 {{ slip.header_no }}</text>
      </view>
      <view class="card">
        <view v-for="line in slip.lines || []" :key="line.id" class="line">
          <view>
            <text class="name">{{ line.material_name }}</text>
            <text class="muted">{{ line.material_code }}{{ line.size_value ? ` · ${line.size_value}` : '' }}</text>
          </view>
          <text class="qty">{{ line.qty }}{{ line.unit_name || '' }}</text>
        </view>
      </view>
      <view v-if="slip.status === 'signed'" class="card">{{ slip.picker_name || (returning ? '退料人' : '领料人') }} 已确认{{ returning ? '退料' : '领料' }}</view>
      <view v-else-if="slip.status === 'cancelled'" class="card error">这张{{ returning ? '退料单' : '领料单' }}已取消</view>
      <view v-else class="card">
        <button class="submit" :disabled="submitting" @click="submit">确认{{ returning ? '退料' : '领料' }}</button>
      </view>
    </template>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { get, post } from '../../services/http'

const slip = ref<any>(null)
const error = ref('')
const submitting = ref(false)
const returning = computed(() => String(slip.value?.kind || '').includes('return'))
let token = ''

onLoad(async (query) => {
  token = String(query?.token || '').trim()
  if (!token) {
    error.value = '缺少单据'
    return
  }
  try {
    slip.value = await get(`/warehouse-pickups/by-token/${encodeURIComponent(token)}`)
    uni.setNavigationBarTitle({ title: returning.value ? '退料确认' : '领料确认' })
  } catch (err: any) {
    error.value = err?.message || '单据不存在'
  }
})

async function submit() {
  if (submitting.value) return
  submitting.value = true
  try {
    slip.value = await post(`/warehouse-pickups/by-token/${encodeURIComponent(token)}/sign`, {})
    uni.setNavigationBarTitle({ title: returning.value ? '退料确认' : '领料确认' })
    uni.showToast({ title: returning.value ? '已确认退料' : '已确认领料', icon: 'none' })
  } catch (err: any) {
    uni.showToast({ title: err?.message || '确认失败', icon: 'none' })
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped lang="scss">
.card {
  margin-bottom: 24rpx;
  padding: 28rpx;
  background: #fff;
  border-radius: 16rpx;
}
.kind,
.muted {
  display: block;
  color: #666;
  font-size: 24rpx;
}
.doc {
  display: block;
  margin: 8rpx 0;
  font-size: 40rpx;
  font-weight: 700;
}
.line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24rpx;
  padding: 16rpx 0;
}
.line + .line {
  border-top: 1px solid #eee;
}
.name,
.qty {
  display: block;
  font-size: 30rpx;
  font-weight: 600;
}
.submit {
  background: #1677ff;
  color: #fff;
}
.error {
  color: #c00;
}
</style>
