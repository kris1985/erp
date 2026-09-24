<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">总账</h1>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始"
          end-placeholder="结束"
          clearable
          @change="reload"
        />
        <el-select v-model="bizType" clearable placeholder="业务类型" style="width: 140px" @change="reload">
          <el-option v-for="t in bizTypes" :key="t.value" :label="t.label" :value="t.value" />
        </el-select>
        <el-checkbox v-model="includeVoid" @change="reload">含已作废</el-checkbox>
        <el-button @click="load">刷新</el-button>
        <div class="spacer" />
        <el-button v-permission="'btn.ledger.export'" type="primary" @click="exportCsv">导出 CSV</el-button>
      </div>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          :data="rows"
          stripe
          border
          show-summary
          :summary-method="getSummaries"
          style="width: 100%"
          :max-height="tableMaxHeight"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column
            prop="entry_date"
            label="日期"
            :width="colWidth('entry_date', 120)"
            resizable
          />
          <el-table-column
            prop="biz_type_label"
            label="类型"
            :width="colWidth('biz_type_label', 110)"
            resizable
          />
          <el-table-column
            prop="summary"
            label="摘要"
            :width="colWidth('summary', 260)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="amount_in"
            label="进帐金额"
            :width="colWidth('amount_in', 120)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <span v-if="row.amount_in" class="amount-in">{{ formatMoney(row.amount_in) }}</span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column
            prop="amount_piece"
            label="计件/提成"
            :width="colWidth('amount_piece', 120)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <span v-if="row.amount_piece" class="amount-out">{{ formatMoney(row.amount_piece) }}</span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column
            prop="amount_out"
            label="出账金额"
            :width="colWidth('amount_out', 120)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <span v-if="row.amount_out" class="amount-out">{{ formatMoney(row.amount_out) }}</span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column
            prop="balance"
            label="余额"
            :width="colWidth('balance', 120)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <span v-if="row.balance != null">{{ formatMoney(row.balance) }}</span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column
            prop="source_no"
            label="来源单号"
            :width="colWidth('source_no', 140)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column label="状态" :width="colWidth('status', 90)" resizable>
            <template #default="{ row }">
              <el-tag :type="row.status === 'posted' ? 'success' : 'info'" size="small">
                {{ row.status === 'posted' ? '正常' : '已作废' }}
              </el-tag>
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
          @current-change="load"
          @size-change="onPageSizeChange"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const auth = useAuthStore()
const tableRef = ref()
const { colWidth, onHeaderDragend } = useTableColWidths('ledger-list', tableRef, {
  flexKey: 'summary',
  flexDefaultMin: 200,
  fitToContainer: true,
})
const { tableHostRef, tableMaxHeight } = useTableMaxHeight()

const dateRange = ref<[string, string] | null>(null)
const bizType = ref<string | null>(null)
const includeVoid = ref(false)
const bizTypes = ref<{ value: string; label: string }[]>([])
const rows = ref<any[]>([])
const summary = ref<any>({})
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

function formatMoney(v: any) {
  const n = Number(v || 0)
  return `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function getSummaries({ columns }: { columns: any[] }) {
  const s = summary.value || {}
  return columns.map((col: any, index: number) => {
    if (index === 0) return '合计'
    const key = col.property || col.columnKey
    if (key === 'amount_in') return formatMoney(s.inflow)
    if (key === 'amount_piece') return formatMoney(s.piece)
    if (key === 'amount_out') return formatMoney(Math.abs(s.outflow || 0))
    if (key === 'balance') return formatMoney(s.balance ?? s.net)
    return ''
  })
}

function reload() {
  page.value = 1
  return load()
}

function onPageSizeChange() {
  page.value = 1
  return load()
}

async function load() {
  const res: any = await http.get('/ledger', {
    params: {
      date_from: dateRange.value?.[0] || undefined,
      date_to: dateRange.value?.[1] || undefined,
      biz_type: bizType.value || undefined,
      include_void: includeVoid.value || undefined,
      page: page.value,
      page_size: pageSize.value,
    },
  })
  rows.value = res.data?.items || []
  total.value = res.data?.total ?? rows.value.length
  summary.value = res.data?.summary || {}
  if (res.data?.biz_types?.length) bizTypes.value = res.data.biz_types
}

async function exportCsv() {
  const query = new URLSearchParams()
  if (dateRange.value?.[0]) query.set('date_from', dateRange.value[0])
  if (dateRange.value?.[1]) query.set('date_to', dateRange.value[1])
  if (bizType.value) query.set('biz_type', bizType.value)
  if (includeVoid.value) query.set('include_void', 'true')
  const res = await fetch(`/api/v1/ledger/export?${query.toString()}`, {
    headers: { Authorization: `Bearer ${auth.token}` },
  })
  if (!res.ok) {
    ElMessage.error('导出失败')
    return
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = '总账.csv'
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已下载')
}

onMounted(async () => {
  const meta: any = await http.get('/ledger/meta')
  bizTypes.value = meta.data?.biz_types || []
  await load()
})
</script>

<style scoped>
.amount-in {
  color: #067a3e;
}
.amount-out {
  color: #c03639;
}
</style>
