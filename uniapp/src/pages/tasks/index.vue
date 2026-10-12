<template>
  <view class="page h5-home-page">
    <view v-if="loading" class="h5-home-empty">加载中…</view>
    <view v-else-if="!tasks.length" class="h5-home-empty">暂无已领取任务，扫码后可领取</view>
    <view v-else>
      <view v-for="(row, index) in tasks" :key="`${row.header_id}-${row.segment_id}`" class="card h5-task-row" @click="openTask(row)">
        <view class="h5-task-main">
          <text class="h5-task-index">{{ index + 1 }}</text>
          <view class="h5-task-body">
            <view class="h5-task-top">
              <strong>{{ row.header_no }}</strong>
              <text class="h5-task-chip">{{ row.task_name }}</text>
            </view>
            <view class="h5-task-info">
              <view><text>工厂型号</text><strong>{{ row.product_code || '—' }}</strong></view>
              <view><text>颜色</text><strong>{{ row.color_name || '—' }}</strong></view>
              <view><text>交期</text><strong>{{ formatDate(row.delivery_date) }}</strong></view>
            </view>
            <view class="h5-task-tags">
              <text class="h5-task-tag">数量 {{ row.qty || 0 }} 双</text>
              <text class="h5-task-tag h5-task-tag--done">完工 {{ row.completed_qty || 0 }} 双</text>
            </view>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { get } from '../../services/http'
import { appPageForTarget } from '../../services/scanner'

const overview = ref<any>(null), loading = ref(false)
const tasks = computed(() => overview.value?.tasks || [])
const formatDate = (v?: string) => {
  const raw = String(v || '').trim()
  return raw ? raw.slice(0, 10) : '—'
}
function openTask(row: any) {
  const segment = row.segment_code === 'stitch' || row.segment_code === 'forming' || row.segment_code === 'cut' ? row.segment_code : 'cut'
  uni.navigateTo({
    url: appPageForTarget({
      kind: 'flow-card',
      code: String(row.header_id),
      h5Path: `/flow-card/${row.header_id}`,
      label: '生产流转卡',
      segmentCode: segment,
    }),
  })
}
async function load() {
  loading.value = true
  try { overview.value = await get('/home/overview') }
  catch (e: any) { uni.showToast({ title: e?.message || '任务加载失败', icon: 'none' }) }
  finally { loading.value = false }
}
onShow(load)
</script>
