<template>
  <div>
    <header v-if="!embedded" class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">出货单</h1>
      </div>
    </header>
    <div :class="embedded ? 'shipments-embedded' : 'admin-card'">
      <div class="admin-toolbar">
        <el-input
          v-model="keyword"
          clearable
          placeholder="出货单号 / 销售单号 / 客户 / 运单"
          style="width: 320px"
          @clear="reloadList"
          @keyup.enter="reloadList"
        />
        <el-select
          v-model="statusFilter"
          clearable
          placeholder="状态"
          style="width: 120px"
          @change="reloadList"
        >
          <el-option label="草稿" value="draft" />
          <el-option label="已出货" value="shipped" />
          <el-option label="已作废" value="void" />
        </el-select>
        <el-button @click="reloadList">搜索</el-button>
        <el-button @click="load">刷新</el-button>
      </div>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          class="shipments-table"
          :data="rows"
          stripe
          border
          size="small"
          show-summary
          :summary-method="getSummaries"
          :max-height="tableMaxHeight"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column
            prop="shipment_no"
            label="出货单号"
            :width="colWidth('shipment_no', 130)"
            resizable
          />
          <el-table-column
            prop="sales_order_no"
            label="订单号"
            :width="colWidth('sales_order_no', 120)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ text(row.sales_order_no) }}</template>
          </el-table-column>
          <el-table-column prop="customer_name" label="客户" :width="colWidth('customer_name', 100)" show-overflow-tooltip resizable>
            <template #default="{ row }">{{ text(row.customer_name) }}</template>
          </el-table-column>
          <el-table-column prop="ordered_at" label="下单日期" width="96" show-overflow-tooltip>
            <template #default="{ row }">{{ text(row.ordered_at) }}</template>
          </el-table-column>
          <el-table-column prop="sort_no" label="序号" width="48" align="center">
            <template #default="{ row }">{{ row.sort_no ?? '—' }}</template>
          </el-table-column>
          <el-table-column prop="product_code" label="工厂型号" width="96" show-overflow-tooltip>
            <template #default="{ row }">{{ text(row.product_code) }}</template>
          </el-table-column>
          <el-table-column label="图片" width="52" align="center">
            <template #default="{ row }">
              <el-image
                v-if="row.product_image_url"
                :src="row.product_image_url"
                :preview-src-list="[row.product_image_url]"
                fit="contain"
                preview-teleported
                class="product-thumb"
              />
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column prop="color_name" label="颜色" width="72" show-overflow-tooltip>
            <template #default="{ row }">{{ text(row.color_name) }}</template>
          </el-table-column>
          <el-table-column prop="fabric" label="面料" width="80" show-overflow-tooltip>
            <template #default="{ row }">{{ text(row.fabric) }}</template>
          </el-table-column>
          <el-table-column prop="lining" label="内里/垫脚" width="88" show-overflow-tooltip>
            <template #default="{ row }">{{ text(row.lining) }}</template>
          </el-table-column>
          <el-table-column prop="brand_name" label="品牌" width="72" show-overflow-tooltip>
            <template #default="{ row }">{{ text(row.brand_name) }}</template>
          </el-table-column>
          <el-table-column prop="customer_sku" label="客户型号" width="88" show-overflow-tooltip>
            <template #default="{ row }">{{ text(row.customer_sku) }}</template>
          </el-table-column>
          <el-table-column label="码数" align="center">
            <el-table-column v-for="size in sizes" :key="size.id" :label="size.value" width="44" align="center">
              <template #default="{ row }">{{ sizeQty(row, size.id) || '' }}</template>
            </el-table-column>
          </el-table-column>
          <el-table-column label="箱数" width="72" align="right" class-name="shipment-carton-col">
            <template #default="{ row }">{{ row.carton_qty ?? 0 }}</template>
          </el-table-column>
          <el-table-column
            prop="total_qty"
            label="数量"
            :width="colWidth('total_qty', 80)"
            align="right"
            resizable
          />
          <el-table-column prop="delivery_date" label="交货日期" width="96" show-overflow-tooltip>
            <template #default="{ row }">{{ text(row.delivery_date) }}</template>
          </el-table-column>
          <el-table-column prop="line_notes" label="备注" width="96" show-overflow-tooltip>
            <template #default="{ row }">{{ text(row.line_notes) }}</template>
          </el-table-column>
          <el-table-column prop="ship_date" label="出货日" :width="colWidth('ship_date', 110)" resizable />
          <el-table-column prop="amount" label="金额" :width="colWidth('amount', 100)" align="right" resizable>
            <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
          </el-table-column>
          <el-table-column column-key="status" label="状态" :width="colWidth('status', 90)" resizable>
            <template #default="{ row }">{{ shipmentStatusLabel(row.status) }}</template>
          </el-table-column>
          <el-table-column
            prop="tracking_no"
            label="运单"
            :width="colWidth('tracking_no', 120)"
            resizable
          />
          <el-table-column column-key="actions" label="操作" width="250" fixed="right" :resizable="false">
            <template #default="{ row }">
              <el-button link type="primary" @click="printShipment(row)">打印</el-button>
              <el-button link type="primary" @click="printCartonMarks(row)">箱唛</el-button>
              <el-button link type="primary" @click="exportShipment(row)">导出</el-button>
              <el-button v-if="row.status === 'draft'" v-permission="'btn.shipments.write'" link type="primary" @click="confirm(row)">
                确认出货
              </el-button>
              <el-button
                v-if="row.status === 'shipped' && Number(row.carton_qty) > 0"
                v-permission="'btn.shipments.write'"
                link
                type="danger"
                @click="returnCartons(row)"
              >
                退回
              </el-button>
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
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const props = withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })
const embedded = computed(() => props.embedded)
const auth = useAuthStore()
const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths('shipments-list', tableRef, {
  flexKey: 'customer_name',
  flexDefaultMin: 120,
  fitToContainer: false,
})
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const rows = ref<any[]>([])
const summary = ref<any>({})
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const statusFilter = ref<string | null>(null)
const sizes = computed(() => {
  const catalog = new Map<number, string>()
  for (const row of rows.value) {
    for (const line of row.lines || []) {
      const sizeId = Number(line.size_id || 0)
      if (!sizeId) continue
      catalog.set(sizeId, String(line.size_value || sizeId))
    }
  }
  return [...catalog.entries()]
    .map(([id, value]) => ({ id, value }))
    .sort((a, b) => a.value.localeCompare(b.value, undefined, { numeric: true }))
})

const SHIPMENT_STATUS: Record<string, string> = {
  draft: '草稿',
  shipped: '已出货',
  void: '已作废',
}

function shipmentStatusLabel(s: string) {
  return SHIPMENT_STATUS[s] || s || '—'
}

function text(value: string | number | null | undefined) {
  const raw = String(value ?? '').trim()
  return raw || '—'
}

function sizeQty(row: any, sizeId: number) {
  const qty = (row.lines || [])
    .filter((line: any) => Number(line.size_id) === sizeId)
    .reduce((sum: number, line: any) => sum + Number(line.qty || 0), 0)
  if (!qty) return 0
  const boxes = Number(row.carton_qty) || 0
  if (boxes <= 1) return qty
  return qty % boxes === 0 ? qty / boxes : Math.round(qty / boxes)
}

function formatMoney(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// A2a 放货回款提示：复用 finance_service.customer_pay_risk（经 /partners/{id}/pay-risk）
async function fetchPayRisk(customerId: number | null | undefined) {
  if (!customerId) return null
  try {
    const res: any = await http.get(`/partners/${customerId}/pay-risk`)
    return res?.data || null
  } catch {
    return null
  }
}

function payRiskSummaryText(risk: any) {
  if (!risk) return ''
  const bits = [risk.risk_label || '回款提示']
  if ((risk.reasons || []).length) bits.push(risk.reasons.join('；'))
  return bits.filter(Boolean).join(' · ')
}

async function confirmWithPayRiskCheck(
  customerId: number | null | undefined,
  action: () => Promise<void>,
) {
  const risk = await fetchPayRisk(customerId)
  if (risk && (risk.risk === 'high' || risk.risk === 'medium')) {
    try {
      await ElMessageBox.confirm(
        payRiskSummaryText(risk) || '该客户回款需关注，是否仍确认出货？',
        '放货前回款提示',
        {
          type: risk.risk === 'high' ? 'error' : 'warning',
          confirmButtonText: '仍确认出货',
          cancelButtonText: '取消',
        },
      )
    } catch {
      return
    }
  }
  await action()
}

function getSummaries({ columns }: { columns: any[] }) {
  const s = summary.value || {}
  return columns.map((col: any, index: number) => {
    if (index === 0) return '合计'
    const key = col.property || col.columnKey
    if (key === 'total_qty') return String(s.total_qty ?? 0)
    if (key === 'amount') return formatMoney(s.amount)
    return ''
  })
}

async function load() {
  const res: any = await http.get('/shipments', {
    params: {
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim() || undefined,
      status: statusFilter.value || undefined,
    },
  })
  const payload = res.data
  rows.value = payload?.items || (Array.isArray(payload) ? payload : [])
  total.value = payload?.total ?? rows.value.length
  summary.value = payload?.summary || {}
  void nextTick(() => {
    measureTableHeight()
    relayoutTable()
  })
}

function reloadList() {
  page.value = 1
  void load()
}

function onPageSizeChange() {
  page.value = 1
  void load()
}

async function confirmDraftPrintOrExport(row: any, action: '打印' | '导出') {
  if (row.status !== 'draft') return true
  try {
    await ElMessageBox.confirm(
      action === '打印'
        ? '当前为草稿，确认仍要打印？建议确认出货后再发给客户。'
        : '当前为草稿，确认仍要导出？',
      `${action}确认`,
      {
        type: 'warning',
        confirmButtonText: `继续${action}`,
        cancelButtonText: '取消',
      },
    )
    return true
  } catch {
    return false
  }
}

async function printShipment(row: any) {
  if (!(await confirmDraftPrintOrExport(row, '打印'))) return
  const url = `${window.location.origin}/admin/shipments/print/${row.id}`
  const w = window.open(url, '_blank')
  if (!w) ElMessage.warning('请允许弹出窗口以打印')
}

async function printCartonMarks(row: any) {
  try {
    const res: any = await http.get(`/shipments/${row.id}/packing-cartons`)
    const items = res.data?.items || []
    if (!items.length) {
      ElMessage.warning('该出货单暂无落成箱唛（直发/成品仓出货落成后可补打）')
      return
    }
    for (const c of items.slice(0, 8)) {
      window.open(`${window.location.origin}/admin/packing/print/${c.id}`, '_blank')
    }
    if (items.length > 8) {
      ElMessage.info(`已打开前 8 箱，共 ${items.length} 箱`)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载箱唛失败')
  }
}

async function exportShipment(row: any) {
  if (!(await confirmDraftPrintOrExport(row, '导出'))) return
  const res = await fetch(`/api/v1/shipments/${row.id}/export`, {
    headers: auth.token ? { Authorization: `Bearer ${auth.token}` } : {},
  })
  if (!res.ok) {
    let msg = '导出失败'
    try {
      const body = await res.json()
      msg = body.detail || body.error?.message || msg
    } catch {
      /* ignore */
    }
    ElMessage.error(msg)
    return
  }
  const blob = await res.blob()
  const cd = res.headers.get('Content-Disposition') || ''
  let filename = `${row.shipment_no || 'shipment'}.xlsx`
  const mStar = cd.match(/filename\*=UTF-8''([^;]+)/i)
  const m = cd.match(/filename="?([^";]+)"?/i)
  if (mStar?.[1]) filename = decodeURIComponent(mStar[1])
  else if (m?.[1]) filename = m[1]
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出 Excel')
}

async function confirm(row: any) {
  await confirmWithPayRiskCheck(row.customer_id, async () => {
    await http.post(`/shipments/${row.id}/confirm`)
    ElMessage.success('已确认出货')
    await load()
  })
}

async function returnCartons(row: any) {
  const max = Number(row.carton_qty) || 0
  if (max <= 0) {
    ElMessage.warning('没有可退箱数')
    return
  }
  let value = ''
  try {
    const res = await ElMessageBox.prompt(`本次退回箱数，最多 ${max} 箱`, '退回', {
      inputPlaceholder: '箱数',
      inputPattern: /^[1-9]\d*$/,
      inputErrorMessage: '请输入正整数箱数',
      confirmButtonText: '退回',
      cancelButtonText: '取消',
    })
    value = res.value
  } catch {
    return
  }
  const cartons = Number(value)
  if (!Number.isInteger(cartons) || cartons < 1 || cartons > max) {
    ElMessage.warning(`请输入 1 到 ${max} 的箱数`)
    return
  }
  try {
    await http.post(`/shipments/${row.id}/return`, { carton_qty: cartons })
  } catch {
    return
  }
  ElMessage.success(`已退回 ${cartons} 箱`)
  await load()
}

onMounted(async () => {
  await load()
})
</script>

<style scoped>
.shipments-table :deep(.el-table__cell) { padding: 4px 0; }
.shipments-table :deep(.cell) { padding: 0 4px; white-space: nowrap; }
.product-thumb { width: 32px; height: 26px; vertical-align: middle; }
</style>

