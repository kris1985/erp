<template>
  <view class="app-nav-bar" :class="{ 'is-pad': pad }">
    <view class="app-nav-bar__fixed" :style="fixedStyle">
      <view class="app-nav-bar__side" :style="sideStyle" @click="back">
        <view class="app-nav-bar__chevron" />
      </view>
      <view class="app-nav-bar__title" :style="titleStyle">{{ title }}</view>
      <view class="app-nav-bar__side app-nav-bar__right" :style="rightStyle">
        <slot name="right" />
      </view>
    </view>
    <view class="app-nav-bar__spacer" :style="{ height: offset + 'px' }" />
  </view>
</template>

<script setup lang="ts">
import { computed, ref, useSlots } from 'vue'
import { onShow, onUnload } from '@dcloudio/uni-app'
import { pageTitles, consumePageBack } from '../../services/page-title'

const slots = useSlots()

const DEFAULTS: Record<string, string> = {
  'pages/attendance/index': '打卡',
  'pages/tasks/index': '任务',
  'pages/defects/index': '报废记录',
  'pages/material-pickups/index': '领料',
  'pages/material-prep/index': '备料',
  'pages/prep-sign/index': '确认领料',
  'pages/supplier-products/index': '物料色卡',
  'pages/warehouse/index': '物料仓',
  'pages/purchase/index': '物料采购',
  'pages/cut-usage/index': '裁断用料',
  'pages/own-products/index': '产品开发',
  'pages/attendance-rules/index': '考勤规则',
  'pages/leaves/index': '请假登记',
  'pages/employees/index': '员工管理',
  'pages/partners/index': '合作商',
  'pages/expenses/index': '报销',
  'pages/pickup-sign/index': '领料确认',
  'pages/material-label/index': '物料',
  'pages/worklogs/index': '报工记录',
  'pages/salary/index': '我的工资',
  'pages/mine/index': '我的',
  'pages/report/index': '扫码报工',
  'pages/workbench/index': '主管工作台',
  'pages/orders/index': '生产进度',
  'pages/po-receive/index': '登记到货',
  'pages/subcontract-acceptance/index': '外发验收',
  'pages/line-report/index': '线产量报工',
  'pages/team/index': '我的班组',
  'pages/change-password/index': '修改密码',
}

function currentRoute() {
  return getCurrentPages().slice(-1)[0]?.route || ''
}

const route = ref(currentRoute())
const pad = ref(false)
const statusHeight = ref(0)
const barHeight = ref(44)
const offset = computed(() => statusHeight.value + barHeight.value)
const fixedStyle = computed(() => ({
  height: offset.value + 'px',
  paddingTop: statusHeight.value + 'px',
}))
const sideStyle = computed(() => ({
  width: barHeight.value + 'px',
  height: barHeight.value + 'px',
  flexBasis: barHeight.value + 'px',
}))
const rightStyle = computed(() => {
  if (slots.right) {
    return {
      width: 'auto',
      minWidth: barHeight.value + 'px',
      height: barHeight.value + 'px',
      flexBasis: 'auto',
      paddingRight: '10px',
    }
  }
  return sideStyle.value
})
const titleStyle = computed(() => ({
  top: statusHeight.value + 'px',
  height: barHeight.value + 'px',
  lineHeight: barHeight.value + 'px',
}))

function isPad(info: UniApp.GetSystemInfoResult) {
  const model = `${info.model || ''} ${(info as { deviceModel?: string }).deviceModel || ''}`
  if (info.deviceType === 'pad' || /ipad/i.test(model)) return true
  const shortSide = Math.min(Number(info.screenWidth) || 0, Number(info.screenHeight) || 0)
  // iPad mini 短边 744，手机最长边不超过这个值
  return shortSide >= 744 && info.deviceType !== 'phone'
}

function measure() {
  const info = uni.getSystemInfoSync()
  const tablet = isPad(info)
  const reported = Number(info.statusBarHeight) || 0
  const inset = Number(info.safeAreaInsets?.top) || 0
  // iPad 时间在左上角。状态栏高度报 0 时返回会叠在时间上，至少留出 24pt
  pad.value = tablet
  statusHeight.value = Math.max(reported, inset, tablet ? 24 : 0)
  barHeight.value = tablet ? 56 : 44
  if (typeof document !== 'undefined') {
    document.documentElement.style.setProperty('--app-nav-offset', `${offset.value}px`)
  }
}

measure()

function onResize() {
  measure()
}

onShow(() => {
  route.value = currentRoute()
  measure()
  uni.offWindowResize(onResize)
  uni.onWindowResize(onResize)
})

onUnload(() => {
  uni.offWindowResize(onResize)
})

const title = computed(() => pageTitles[route.value] || DEFAULTS[route.value] || '')

function back() {
  if (consumePageBack(route.value || currentRoute())) return
  const pages = getCurrentPages()
  if (pages.length > 1) {
    uni.navigateBack({ delta: 1 })
    return
  }
  uni.reLaunch({ url: '/pages/home/index' })
}
</script>

<style scoped lang="scss">
.app-nav-bar__fixed {
  position: fixed;
  z-index: 998;
  top: 0;
  right: 0;
  left: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-sizing: border-box;
  background: #0e4fa8;
}
.app-nav-bar__side {
  position: relative;
  z-index: 2;
  display: flex;
  flex: 0 0 44px;
  align-items: center;
  justify-content: center;
}
.app-nav-bar__right {
  justify-content: flex-end;
}
.app-nav-bar__chevron {
  width: 11px;
  height: 11px;
  margin-left: 4px;
  border-bottom: 2.5px solid #fff;
  border-left: 2.5px solid #fff;
  transform: rotate(45deg);
}
.is-pad .app-nav-bar__chevron {
  width: 13px;
  height: 13px;
  border-bottom-width: 3px;
  border-left-width: 3px;
}
.app-nav-bar__title {
  position: absolute;
  right: 0;
  left: 0;
  z-index: 1;
  overflow: hidden;
  color: #fff;
  font-size: 17px;
  font-weight: 700;
  text-align: center;
  text-overflow: ellipsis;
  white-space: nowrap;
  pointer-events: none;
}
.is-pad .app-nav-bar__title {
  font-size: 20px;
}
</style>
