<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">应收 / 客户欠款</h1>
        <p class="page-desc">出货挂账 · 账龄 · 调账</p>
      </div>
    </header>
    <div class="admin-card" style="margin-bottom: 16px">
      <div style="font-weight: 600; margin-bottom: 8px">客户汇总</div>
      <div ref="tableHostRef">
      <el-table :data="summary" stripe border size="small" style="width: 100%" :max-height="tableMaxHeight" @header-dragend="onHeaderDragend">
        <el-table-column prop="customer_name" label="客户" :width="colWidth('customer_name', 140)" resizable />
        <el-table-column prop="balance" label="未收" :width="colWidth('balance', 100)" resizable />
        <el-table-column column-key="aging_0_30" label="0-30天" :width="colWidth('aging_0_30', 90)" resizable>
          <template #default="{ row }">{{ row.aging?.['0-30'] }}</template>
        </el-table-column>
        <el-table-column column-key="aging_31_60" label="31-60天" :width="colWidth('aging_31_60', 90)" resizable>
          <template #default="{ row }">{{ row.aging?.['31-60'] }}</template>
        </el-table-column>
        <el-table-column column-key="aging_60_plus" label="60+天" :width="colWidth('aging_60_plus', 90)" resizable>
          <template #default="{ row }">{{ row.aging?.['60+'] }}</template>
        </el-table-column>
      </el-table>
      </div>
      <div class="admin-pagination">
        <el-pagination
          v-model:current-page="summaryPage"
          v-model:page-size="summaryPageSize"
          background
          layout="total, sizes, prev, pager, next"
          :total="summaryTotal"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="loadSummary"
          @size-change="onSummaryPageSizeChange"
        />
      </div>
    </div>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-button @click="load">刷新</el-button>
      </div>
      <div ref="tableHostRef1">
      <el-table :data="rows" stripe border style="width: 100%" :max-height="tableMaxHeight1" @header-dragend="onHeaderDragend1">
        <el-table-column prop="receivable_date" label="日期" :width="colWidth1('receivable_date', 110)" resizable />
        <el-table-column prop="customer_name" label="客户" :width="colWidth1('customer_name', 120)" resizable />
        <el-table-column prop="order_id" label="订单ID" :width="colWidth1('order_id', 90)" resizable />
        <el-table-column prop="amount" label="应收" :width="colWidth1('amount', 90)" resizable />
        <el-table-column prop="adjustment" label="调账" :width="colWidth1('adjustment', 80)" resizable />
        <el-table-column prop="received_amount" label="已收" :width="colWidth1('received_amount', 90)" resizable />
        <el-table-column prop="balance" label="未收" :width="colWidth1('balance', 90)" resizable />
        <el-table-column column-key="aging" label="账龄" :width="colWidth1('aging', 90)" resizable>
          <template #default="{ row }">{{ ageBucketLabel(row.age_bucket) }}</template>
        </el-table-column>
        <el-table-column column-key="status" label="状态" :width="colWidth1('status', 90)" resizable>
          <template #default="{ row }">{{ arStatusLabel(row.status) }}</template>
        </el-table-column>
        <el-table-column column-key="actions" label="操作" :width="colWidth1('actions', 120)" resizable>
          <template #default="{ row }">
            <el-button
              v-if="row.status !== 'void' && row.status !== 'settled'"
              link
              type="primary"
              @click="adjust(row)"
            >调账</el-button>
          </template>
        </el-table-column>
      </el-table>
      </div>
      <div class="admin-pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="loadRows"
          @size-change="onPageSizeChange"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const {
  tableHostRef: tableHostRef1,
  tableMaxHeight: tableMaxHeight1,
  measureTableHeight: measureTableHeight1,
} = useTableMaxHeight()
const { colWidth, onHeaderDragend } = useTableColWidths('receivables-summary')
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths('receivables-list')
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const summary = ref<any[]>([])
const summaryTotal = ref(0)
const summaryPage = ref(1)
const summaryPageSize = ref(20)

const AR_STATUS: Record<string, string> = {
  open: '未收',
  partial: '部分已收',
  settled: '已结清',
  void: '已作废',
}

function arStatusLabel(s: string) {
  return AR_STATUS[s] || s || '—'
}

function ageBucketLabel(s: string) {
  if (s === '0-30') return '0–30天'
  if (s === '31-60') return '31–60天'
  if (s === '60+') return '60天以上'
  return s || '—'
}

async function loadRows() {
  const res: any = await http.get('/receivables', {
    params: { page: page.value, page_size: pageSize.value },
  })
  const payload = res.data
  rows.value = payload?.items || (Array.isArray(payload) ? payload : [])
  total.value = payload?.total ?? rows.value.length
  void nextTick(measureTableHeight1)
}

async function loadSummary() {
  const res: any = await http.get('/receivables/customer-summary', {
    params: { page: summaryPage.value, page_size: summaryPageSize.value },
  })
  const payload = res.data
  summary.value = payload?.items || (Array.isArray(payload) ? payload : [])
  summaryTotal.value = payload?.total ?? summary.value.length
  void nextTick(measureTableHeight)
}

async function load() {
  await Promise.all([loadRows(), loadSummary()])
}

function onPageSizeChange() {
  page.value = 1
  void loadRows()
}

function onSummaryPageSizeChange() {
  summaryPage.value = 1
  void loadSummary()
}

async function adjust(row: any) {
  const { value } = await ElMessageBox.prompt('调账金额（可为负，如折让）', '应收调账', {
    inputValue: '0',
  })
  await http.post(`/receivables/${row.id}/adjust`, { adjustment_delta: Number(value) })
  ElMessage.success('已调账')
  load()
}

onMounted(load)
</script>
