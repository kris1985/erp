<template>
  <view class="page mobile-list-page">
    <view class="worklogs-salary-link" @click="goSalary"><view><text>本月收入</text><strong>查看工资预估与结算明细</strong></view><text class="worklogs-arrow">›</text></view>
    <view class="segment">
      <button v-for="item in tabs" :key="item.value" class="segment__item" :class="{ active: status === item.value }" @click="changeStatus(item.value)">{{ item.label }}</button>
    </view>
    <view v-if="loading" class="empty-state">加载中…</view>
    <view v-else-if="errorMessage" class="empty-state"><text>{{ errorMessage }}</text><button class="retry-button" @click="load">重新加载</button></view>
    <view v-else-if="!rows.length" class="empty-state">暂无计件记录</view>
    <view v-else class="record-list">
      <view v-for="row in rows" :key="row.id" class="card record-card">
        <view class="record-head">
          <text class="record-title">{{ row.order_no }} · {{ row.process_name }}</text>
          <text class="status-pill" :class="`status-pill--${row.status}`">{{ statusLabel(row.status) }}</text>
        </view>
        <text class="record-meta">{{ typeLabel(row.report_type) }} · {{ row.report_type === 'rework' ? `返修 ${row.rework_qty || 0}` : `合格 ${row.qualified_qty || 0}` }}</text>
        <text v-if="row.color_name || row.size_value" class="record-meta">{{ row.color_name || '' }} {{ row.size_value || '' }}</text>
        <text class="record-time">{{ formatDate(row.created_at) }}</text>
      </view>
    </view>
    <MobileTabBar active="worklogs" />
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { get } from '../../services/http'
import MobileTabBar from '../../components/MobileTabBar.vue'

const tabs = [{ label: '全部', value: '' }, { label: '有效', value: 'valid' }, { label: '申诉中', value: 'appealed' }]
const status = ref('')
const loading = ref(false)
const rows = ref<any[]>([])
const errorMessage = ref('')

const statusLabel = (value: string) => ({ valid: '有效', appealed: '申诉中', void: '已作废', corrected: '已更正' } as any)[value] || value
const typeLabel = (value: string) => ({ normal: '正常', rework: '返修', group: '集体', supplement: '补数', tail: '尾数' } as any)[value] || value
// 部分工业 PDA 的旧版 Android WebView 没有 String.prototype.replaceAll。
// 该函数在列表首条记录渲染时抛错会导致整个“我的计件”页面白屏。
const formatDate = (value?: string) => String(value || '').slice(0, 10).replace(/-/g, '/')

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    const data: any = await get('/work-logs', { status: status.value || undefined, page_size: 100 })
    const items = data?.items ?? data?.data?.items ?? []
    rows.value = Array.isArray(items) ? items : []
  } catch (error: any) {
    errorMessage.value = error?.message || '计件记录加载失败'
  } finally {
    loading.value = false
  }
}

function goSalary() { uni.redirectTo({ url: '/pages/salary/index' }) }

function changeStatus(value: string) {
  status.value = value
  void load()
}

onShow(load)
</script>
