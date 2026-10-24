<template>
  <view class="page mobile-workbench-page">
    <view class="workbench-hero">
      <text class="workbench-eyebrow">ACTION OVERVIEW</text>
      <text class="workbench-title">{{ greeting }}，{{ profile?.displayName || '主管' }}</text>
      <text class="workbench-role">{{ activeRoleName }}</text>
    </view>

    <view v-if="loading" class="empty-state">正在加载工作台…</view>
    <template v-else>
      <scroll-view v-if="roles.length > 1" scroll-x class="role-strip">
        <view class="role-strip__inner">
          <button v-for="role in roles" :key="role.code" class="role-chip" :class="{ active: activeRole === role.code }" @click="activeRole = role.code">{{ role.name }}</button>
        </view>
      </scroll-view>

      <view class="workbench-metrics">
        <view class="card metric-card"><text>待到货</text><strong>{{ data.counts?.purchase_receive || 0 }}</strong><small>项</small></view>
        <view class="card metric-card"><text>超期/今日</text><strong class="danger">{{ overdueCount }}</strong><small>项</small></view>
      </view>

      <view class="workbench-shortcuts">
        <view class="card shortcut-card" @click="goOrders"><text>生产进度</text><strong>查看交期与工序</strong><small>›</small></view>
        <view class="card shortcut-card" @click="startScan"><text>现场扫码</text><strong>报工、入库、出库</strong><small>⌗</small></view>
        <view v-if="canWarehouse" class="card shortcut-card" @click="goWarehouse"><text>物料仓</text><strong>现存、领退、盘点</strong><small>›</small></view>
        <view v-if="canPurchase" class="card shortcut-card" @click="goPurchase"><text>物料采购</text><strong>反馈、损耗、到货</strong><small>›</small></view>
        <view v-if="canCutUsage" class="card shortcut-card" @click="goCutUsage"><text>裁断用料</text><strong>预算和实际用量</strong><small>›</small></view>
        <view v-if="canOwnProducts" class="card shortcut-card" @click="goOwnProducts"><text>产品开发</text><strong>基础资料和审批</strong><small>›</small></view>
        <view v-if="['leader', 'workshop', 'manager', 'admin'].includes(activeRole)" class="card shortcut-card" @click="goLineReport"><text>线产量</text><strong>按班组拆分计件</strong><small>›</small></view>
        <view v-if="isLeader" class="card shortcut-card" @click="goTeam"><text>我的班组</text><strong>成员加入与移除</strong><small>›</small></view>
      </view>

      <view class="section-row"><text>行动清单</text><text>{{ filteredTasks.length }} 项</text></view>
      <view v-if="!filteredTasks.length" class="card clear-card"><strong>当前没有紧急事项</strong><text>新的工作会自动排进清单</text></view>
      <view v-else class="task-list">
        <view v-for="task in filteredTasks" :key="`${task.kind}-${task.id || task.title}`" class="card task-card" @click="openTask(task)">
          <view class="task-card__head"><text :class="`severity severity--${task.severity}`">{{ task.status }}</text><text>{{ task.source }}</text></view>
          <strong>{{ task.title }}</strong><text class="task-meta">{{ task.meta }}</text>
          <text class="task-action">{{ task.action_label || '去处理' }} ›</text>
        </view>
      </view>
    </template>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { get, post } from '../../services/http'
import { getProfile } from '../../services/storage'
import { appPageForTarget, parseScanText } from '../../services/scanner'

const profile = ref(getProfile())
const data = ref<any>({ roles: [], counts: {}, tasks: [] })
const loading = ref(false)
const activeRole = ref('')
const isLeader = computed(() => Boolean(profile.value?.isLeader) || profile.value?.role === 'leader')
const canWarehouse = computed(() => {
  const features = profile.value?.featurePermissions || []
  return features.includes('shared_materials') || features.includes('shared_materials_write')
})
const canPurchase = computed(() => {
  const features = profile.value?.featurePermissions || []
  return features.includes('purchase_orders') || features.includes('purchase_orders_write')
})
const canCutUsage = computed(() => {
  const features = profile.value?.featurePermissions || []
  return features.includes('cut_material_usage') || features.includes('cut_material_usage_write')
})
const canOwnProducts = computed(() => {
  const features = profile.value?.featurePermissions || []
  return features.includes('own_products') || features.includes('own_products_write') || features.includes('own_products_approve')
})
const roles = computed(() => data.value.roles || [])
const activeRoleName = computed(() => roles.value.find((x: any) => x.code === activeRole.value)?.name || '现场管理')
const greeting = computed(() => { const h = new Date().getHours(); return h < 11 ? '早上好' : h < 18 ? '下午好' : '晚上好' })
const overdueCount = computed(() => Number(data.value.counts?.overdue || 0) + Number(data.value.counts?.due_today || 0))
const filteredTasks = computed(() => {
  const tasks = data.value.tasks || []
  if (['admin', 'manager'].includes(activeRole.value)) return tasks
  if (activeRole.value === 'warehouse') return tasks.filter((x: any) => ['采购', 'IQC'].includes(x.source))
  if (activeRole.value === 'merchandiser') return tasks.filter((x: any) => x.source === '采购')
  return tasks.filter((x: any) => !['采购', 'IQC'].includes(x.source))
})

async function load() {
  profile.value = getProfile()
  loading.value = true
  try {
    data.value = await get('/mobile-workbench/overview')
    const codes = roles.value.map((x: any) => x.code)
    activeRole.value = codes.includes(profile.value?.role || '') ? String(profile.value?.role) : String(codes[0] || '')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '工作台加载失败', icon: 'none' })
  } finally { loading.value = false }
}

function goOrders() { uni.navigateTo({ url: '/pages/orders/index' }) }
function goWarehouse() { uni.navigateTo({ url: '/pages/warehouse/index' }) }
function goPurchase() { uni.navigateTo({ url: '/pages/purchase/index' }) }
function goCutUsage() { uni.navigateTo({ url: '/pages/cut-usage/index' }) }
function goOwnProducts() { uni.navigateTo({ url: '/pages/own-products/index' }) }
function goLineReport() { uni.navigateTo({ url: '/pages/line-report/index' }) }
function goTeam() { uni.navigateTo({ url: '/pages/team/index' }) }
function startScan() {
  uni.scanCode({
    scanType: ['qrCode', 'barCode'],
    success: (result) => {
      const target = parseScanText(result.result)
      if (target) uni.navigateTo({ url: appPageForTarget(target) })
      else uni.showToast({ title: '无法识别该二维码', icon: 'none' })
    },
  })
}
function openTask(task: any) {
  if (String(task.to || '').includes('orders')) return goOrders()
  if (task.kind === 'iqc') return decideIqc(task)
  const po = String(task.to || '').match(/po-receive\/(\d+)/)
  if (po?.[1]) return uni.navigateTo({ url: `/pages/purchase/index?id=${po[1]}&action=receive` })
  uni.showToast({ title: '请在 PC 管理台处理', icon: 'none' })
}

function decideIqc(task: any) {
  const decisions = [{ label: '合格入库', value: 'pass' }, { label: '让步接收', value: 'concede' }, { label: '不合格', value: 'fail' }]
  uni.showActionSheet({ itemList: decisions.map(x => x.label), success: async result => {
    const action = decisions[result.tapIndex]
    if (!action) return
    try { await post(`/material-iqc/${task.id}/decide`, { decision: action.value }); uni.showToast({ title: `${action.label}完成`, icon: 'success' }); await load() }
    catch (e: any) { uni.showToast({ title: e?.message || 'IQC 判定失败', icon: 'none' }) }
  } })
}

onShow(load)
</script>
