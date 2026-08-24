<template>
  <view class="page mobile-orders-page">
    <view class="mobile-page-head"><view><text>生产进度</text><text>交期、齐套与工序完成情况</text></view><button @click="load">刷新</button></view>
    <view class="order-filter">
      <input v-model.trim="keyword" placeholder="搜索单号、客户、款号" confirm-type="search" />
      <picker :range="statusOptions" range-key="label" @change="changeStatus"><text>{{ activeStatusLabel }}⌄</text></picker>
    </view>
    <view v-if="loading" class="empty-state">正在加载生产进度…</view>
    <view v-else-if="!filtered.length" class="empty-state">没有符合条件的生产单</view>
    <view v-else>
      <view v-for="order in filtered" :key="order.id" class="card mobile-order-card" @click="toggle(order.id)">
        <view class="mobile-order-head"><view><strong>{{ order.order_no }}</strong><text>{{ order.customer_name || '—' }} · {{ order.product_code || '—' }}</text></view><text :class="`order-status order-status--${order.status}`">{{ statusLabel(order.status) }}</text></view>
        <view class="order-tags"><text v-if="order.is_rush" class="danger-tag">急单</text><text :class="order.kit_ok ? 'ok-tag' : 'warning-tag'">{{ order.kit_ok ? '已齐套' : '待齐套' }}</text><text v-if="order.risk_label" class="risk-tag">{{ order.risk_label }}</text></view>
        <view class="order-progress"><view><text>总进度</text><text>{{ overall(order) }}%</text></view><view class="progress-track"><view :style="{ width: `${overall(order)}%` }" /></view></view>
        <view class="order-meta"><text>数量 {{ order.total_qty || 0 }}</text><text>交期 {{ order.delivery_date || '未设置' }}</text></view>
        <view v-if="expanded === order.id" class="process-list">
          <view v-for="process in order.processes || []" :key="process.id" class="process-row"><view><strong>{{ process.process_name }}</strong><text>{{ process.assigned_worker_names?.join('、') || '未派工' }}</text></view><text>{{ process.completed_qty || 0 }}/{{ process.plan_qty || 0 }}</text></view>
          <view v-if="!(order.processes || []).length" class="process-empty">尚未生成工序</view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { get } from '../../services/http'

const items = ref<any[]>([]), loading = ref(false), keyword = ref(''), activeStatus = ref(''), expanded = ref<number | null>(null)
const statusOptions = [{ label: '全部状态', value: '' }, { label: '待生产', value: 'confirmed' }, { label: '生产中', value: 'in_progress' }, { label: '已完成', value: 'completed' }]
const activeStatusLabel = computed(() => statusOptions.find(x => x.value === activeStatus.value)?.label || '全部状态')
const filtered = computed(() => {
  const needle = keyword.value.toLowerCase()
  return items.value.filter((x: any) => (!activeStatus.value || x.status === activeStatus.value) && (!needle || [x.order_no, x.customer_name, x.product_code, x.sales_order_no].some(v => String(v || '').toLowerCase().includes(needle))))
})
const statusLabel = (v: string) => ({ confirmed: '待生产', in_progress: '生产中', completed: '已完成', cancelled: '已取消' } as any)[v] || v || '—'
function overall(order: any) { const ps = order.processes || []; if (!ps.length) return 0; const plan = ps.reduce((s: number, x: any) => s + Number(x.plan_qty || 0), 0); const done = ps.reduce((s: number, x: any) => s + Math.min(Number(x.completed_qty || 0), Number(x.plan_qty || 0)), 0); return plan ? Math.min(100, Math.round(done / plan * 100)) : 0 }
function toggle(id: number) { expanded.value = expanded.value === id ? null : id }
function changeStatus(e: any) { activeStatus.value = statusOptions[Number(e.detail.value)]?.value || '' }
async function load() { loading.value = true; try { const data: any = await get('/orders', { page_size: 200 }); items.value = data?.items || [] } catch (e: any) { uni.showToast({ title: e?.message || '订单加载失败', icon: 'none' }) } finally { loading.value = false } }
onShow(load)
</script>
