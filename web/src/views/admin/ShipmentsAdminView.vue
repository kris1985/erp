<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">出货单</h1>
        <p class="page-desc">出货确认 · 欠交 · 触发应收</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-button type="primary" @click="openCreate">新建出货</el-button>
        <el-button @click="load">刷新</el-button>
      </div>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          class="shipments-table"
          :data="rows"
          stripe
          border
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
          <el-table-column prop="order_no" label="订单" :width="colWidth('order_no', 110)" resizable />
          <el-table-column
            prop="customer_name"
            label="客户"
            :width="colWidth('customer_name', 120)"
            resizable
          />
          <el-table-column prop="ship_date" label="出货日" :width="colWidth('ship_date', 110)" resizable />
          <el-table-column
            prop="total_qty"
            label="数量"
            :width="colWidth('total_qty', 80)"
            align="right"
            resizable
          />
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
          <el-table-column column-key="actions" label="操作" width="260" fixed="right" :resizable="false">
            <template #default="{ row }">
              <el-button link type="primary" @click="openDetail(row)">查看</el-button>
              <el-button link type="primary" @click="printShipment(row)">打印</el-button>
              <el-button link type="primary" @click="exportShipment(row)">导出</el-button>
              <el-button v-if="row.status === 'draft'" link type="primary" @click="confirm(row)">
                确认出货
              </el-button>
              <el-button v-if="row.status === 'shipped'" link type="danger" @click="voidSh(row)">
                作废
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

    <el-dialog v-model="createVisible" title="新建出货" width="1100px">
      <el-form label-width="90px">
        <el-alert
          v-if="createPayRisk"
          :type="payRiskAlertType(createPayRisk.risk)"
          :title="payRiskSummaryText(createPayRisk)"
          show-icon
          :closable="false"
          style="margin-bottom: 12px"
        />
        <el-form-item label="订单">
          <el-select v-model="form.order_id" filterable style="width: 100%" @change="loadDelivery">
            <el-option
              v-for="o in orders"
              :key="o.id"
              :label="`${o.order_no} · ${o.customer_name}`"
              :value="o.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="售价(元/双)">
          <span>{{ formatMoney(delivery?.unit_price) }}</span>
        </el-form-item>
        <el-form-item label="货号">
          <span>{{ delivery?.product_code || '—' }}</span>
        </el-form-item>
        <el-form-item v-if="delivery" label="齐码闸">
          <span class="muted">{{ delivery.gate_note || '—' }}</span>
        </el-form-item>
        <el-form-item label="出货明细">
          <el-table
            :data="form.lines"
            border
            size="small"
            style="width: 100%"
            empty-text="请先选择订单"
            @header-dragend="onHeaderDragend1"
          >
            <el-table-column
              prop="product_code"
              label="货号"
              :width="colWidth1('product_code', 110)"
              show-overflow-tooltip
              resizable
            >
              <template #default="{ row }">{{ row.product_code || '—' }}</template>
            </el-table-column>
            <el-table-column
              prop="color_name"
              label="颜色"
              :min-width="flexColMinWidth1('color_name', 90)"
              show-overflow-tooltip
              resizable
            >
              <template #default="{ row }">{{ row.color_name || '—' }}</template>
            </el-table-column>
            <el-table-column
              prop="size_value"
              label="尺码"
              :width="colWidth1('size_value', 70)"
              resizable
            >
              <template #default="{ row }">{{ row.size_value || '—' }}</template>
            </el-table-column>
            <el-table-column
              prop="plan_qty"
              label="计划"
              :width="colWidth1('plan_qty', 70)"
              align="right"
              resizable
            />
            <el-table-column
              prop="shipped_qty"
              label="已出"
              :width="colWidth1('shipped_qty', 70)"
              align="right"
              resizable
            />
            <el-table-column
              prop="backlog_qty"
              label="欠交"
              :width="colWidth1('backlog_qty', 70)"
              align="right"
              resizable
            />
            <el-table-column
              prop="last_qualified_qty"
              label="末道合格"
              :width="colWidth1('last_qualified_qty', 90)"
              align="right"
              resizable
            >
              <template #default="{ row }">
                {{ delivery?.gate_enabled ? (row.last_qualified_qty ?? 0) : '—' }}
              </template>
            </el-table-column>
            <el-table-column
              prop="shippable_qty"
              label="可出码"
              :width="colWidth1('shippable_qty', 80)"
              align="right"
              resizable
            >
              <template #default="{ row }">
                <span :class="{ 'is-short': row.shippable_qty < row.backlog_qty }">
                  {{ row.shippable_qty ?? 0 }}
                </span>
              </template>
            </el-table-column>
            <el-table-column
              prop="short_qty"
              label="欠码"
              :width="colWidth1('short_qty', 70)"
              align="right"
              resizable
            >
              <template #default="{ row }">
                {{ delivery?.gate_enabled ? (row.short_qty ?? 0) : '—' }}
              </template>
            </el-table-column>
            <el-table-column
              column-key="ship_qty"
              label="本次出货"
              :width="colWidth1('ship_qty', 120)"
              resizable
            >
              <template #default="{ row }">
                <el-input-number
                  v-model="row.qty"
                  :min="0"
                  :max="shipQtyMax(row)"
                  size="small"
                  style="width: 100%"
                />
              </template>
            </el-table-column>
          </el-table>
        </el-form-item>
        <el-form-item label="物流">
          <el-input v-model="form.logistics_company" placeholder="物流公司" />
        </el-form-item>
        <el-form-item label="运单号">
          <el-input v-model="form.tracking_no" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="create(false)">存草稿</el-button>
        <el-button type="primary" @click="create(true)">确认出货</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="detailVisible"
      :title="detail ? `出货明细 · ${detail.shipment_no}` : '出货明细'"
      width="720px"
      destroy-on-close
    >
      <template v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="订单">{{ detail.order_no || '—' }}</el-descriptions-item>
          <el-descriptions-item label="货号">{{ detail.product_code || '—' }}</el-descriptions-item>
          <el-descriptions-item label="客户">{{ detail.customer_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="出货日">{{ detail.ship_date || '—' }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ shipmentStatusLabel(detail.status) }}</el-descriptions-item>
          <el-descriptions-item label="数量">{{ detail.total_qty ?? 0 }}</el-descriptions-item>
          <el-descriptions-item label="金额">{{ formatMoney(detail.amount) }}</el-descriptions-item>
          <el-descriptions-item label="物流">{{ detail.logistics_company || '—' }}</el-descriptions-item>
          <el-descriptions-item label="运单">
            <a
              v-if="detail.tracking_no && detail.tracking_search_url"
              :href="detail.tracking_search_url"
              target="_blank"
              rel="noopener"
            >{{ detail.tracking_no }}</a>
            <span v-else>{{ detail.tracking_no || '—' }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <el-alert
          v-if="detailPayRisk && detail.status === 'draft'"
          :type="payRiskAlertType(detailPayRisk.risk)"
          :title="payRiskSummaryText(detailPayRisk)"
          show-icon
          :closable="false"
          style="margin-top: 12px"
        />
        <el-table
          :data="detail.lines || []"
          border
          size="small"
          style="margin-top: 12px"
          empty-text="无明细"
          @header-dragend="onHeaderDragend2"
        >
          <el-table-column
            prop="product_code"
            label="货号"
            :width="colWidth2('product_code', 110)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.product_code || detail.product_code || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="color_name"
            label="颜色"
            :min-width="flexColMinWidth2('color_name', 90)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.color_name || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="size_value"
            label="尺码"
            :width="colWidth2('size_value', 80)"
            resizable
          >
            <template #default="{ row }">{{ row.size_value || '—' }}</template>
          </el-table-column>
          <el-table-column prop="qty" label="数量" :width="colWidth2('qty', 80)" align="right" resizable />
          <el-table-column
            prop="unit_price"
            label="单价"
            :width="colWidth2('unit_price', 90)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatMoney(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column
            prop="amount"
            label="金额"
            :width="colWidth2('amount', 100)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
          </el-table-column>
        </el-table>
      </template>
      <template #footer>
        <el-button v-if="detail" @click="printShipment(detail)">打印</el-button>
        <el-button v-if="detail" @click="exportShipment(detail)">导出 Excel</el-button>
        <el-button
          v-if="detail?.status === 'draft'"
          type="primary"
          @click="confirm(detail!)"
        >
          确认出货
        </el-button>
        <el-button
          v-if="detail?.status === 'shipped'"
          type="danger"
          @click="voidSh(detail!)"
        >
          作废
        </el-button>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const auth = useAuthStore()
const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths('shipments-list', tableRef, {
  flexKey: 'customer_name',
  flexDefaultMin: 120,
  fitToContainer: true,
})
const {
  colWidth: colWidth1,
  flexColMinWidth: flexColMinWidth1,
  onHeaderDragend: onHeaderDragend1,
} = useTableColWidths('shipments-lines', undefined, {
  flexKey: 'color_name',
  flexDefaultMin: 90,
})
const {
  colWidth: colWidth2,
  flexColMinWidth: flexColMinWidth2,
  onHeaderDragend: onHeaderDragend2,
} = useTableColWidths('shipments-detail-lines', undefined, {
  flexKey: 'color_name',
  flexDefaultMin: 90,
})
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const rows = ref<any[]>([])
const summary = ref<any>({})
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const orders = ref<any[]>([])
const createVisible = ref(false)
const detailVisible = ref(false)
const detail = ref<any>(null)
const delivery = ref<any>(null)
const createPayRisk = ref<any>(null)
const detailPayRisk = ref<any>(null)

const SHIPMENT_STATUS: Record<string, string> = {
  draft: '草稿',
  shipped: '已出货',
  void: '已作废',
}

function shipmentStatusLabel(s: string) {
  return SHIPMENT_STATUS[s] || s || '—'
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

function payRiskAlertType(risk: string | null | undefined): 'success' | 'warning' | 'error' | 'info' {
  if (risk === 'high') return 'error'
  if (risk === 'medium') return 'warning'
  if (risk === 'low') return 'success'
  return 'info'
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

const form = reactive<any>({
  order_id: null,
  lines: [],
  logistics_company: '',
  tracking_no: '',
})

async function load() {
  const res: any = await http.get('/shipments', {
    params: { page: page.value, page_size: pageSize.value },
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

function onPageSizeChange() {
  page.value = 1
  void load()
}

async function openCreate() {
  const res: any = await http.get('/orders', { params: { page: 1, page_size: 100 } })
  const payload = res.data
  orders.value = payload?.items || []
  form.order_id = null
  form.lines = []
  delivery.value = null
  createPayRisk.value = null
  createVisible.value = true
}

async function openDetail(row: any) {
  const res: any = await http.get(`/shipments/${row.id}`)
  detail.value = res.data
  detailVisible.value = true
  detailPayRisk.value = await fetchPayRisk(res.data?.customer_id)
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

async function loadDelivery() {
  if (!form.order_id) return
  const res: any = await http.get(`/orders/${form.order_id}/delivery`)
  delivery.value = res.data
  const order = orders.value.find((o: any) => o.id === form.order_id)
  createPayRisk.value = await fetchPayRisk(order?.customer_id)
  form.lines = (res.data?.items || []).map((it: any) => {
    const backlog = Number(it.backlog_qty || 0)
    const shippable = Number(it.shippable_qty ?? backlog)
    const maxQty = Math.min(backlog, shippable)
    return {
      order_item_id: it.order_item_id,
      product_code: it.product_code || res.data?.product_code,
      color_name: it.color_name,
      size_value: it.size_value,
      plan_qty: it.plan_qty,
      shipped_qty: it.shipped_qty,
      backlog_qty: backlog,
      last_qualified_qty: it.last_qualified_qty,
      shippable_qty: shippable,
      short_qty: it.short_qty,
      qty: maxQty,
    }
  })
}

function shipQtyMax(row: any) {
  const backlog = Number(row?.backlog_qty || 0)
  const shippable = Number(row?.shippable_qty ?? backlog)
  return Math.max(0, Math.min(backlog, shippable))
}

async function create(confirm: boolean) {
  const submit = async () => {
    await http.post('/shipments', {
      order_id: form.order_id,
      lines: form.lines
        .filter((l: any) => l.qty > 0)
        .map((l: any) => ({
          order_item_id: l.order_item_id,
          qty: l.qty,
        })),
      logistics_company: form.logistics_company || undefined,
      tracking_no: form.tracking_no || undefined,
      confirm,
    })
    ElMessage.success(confirm ? '已出货并生成应收' : '草稿已保存')
    createVisible.value = false
    await load()
  }
  if (confirm) {
    const order = orders.value.find((o: any) => o.id === form.order_id)
    await confirmWithPayRiskCheck(order?.customer_id, submit)
  } else {
    await submit()
  }
}

async function confirm(row: any) {
  await confirmWithPayRiskCheck(row.customer_id, async () => {
    await http.post(`/shipments/${row.id}/confirm`)
    ElMessage.success('已确认出货')
    detailVisible.value = false
    await load()
  })
}

async function voidSh(row: any) {
  await http.post(`/shipments/${row.id}/void`)
  ElMessage.success('已作废')
  detailVisible.value = false
  await load()
}

onMounted(async () => {
  await load()
})
</script>

<style scoped>
.muted {
  color: #64748b;
  font-size: 13px;
  line-height: 1.45;
}
.is-short {
  color: #dc2626;
  font-weight: 600;
}
</style>
