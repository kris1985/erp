<template>
  <div class="shipments-root" :class="{ 'is-embedded': embedded }">
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
          v-if="!statemented"
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
      <div ref="tableHostRef" class="shipments-table-host">
        <el-table
          ref="tableRef"
          class="shipments-table"
          :data="rows"
          stripe
          border
          size="small"
          show-summary
          :summary-method="getSummaries"
          :height="tableMaxHeight"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column prop="ship_date" label="出货日期" :width="colWidth('ship_date', 110)" resizable />
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
          <el-table-column prop="ordered_at" label="下单日期" :width="colWidth('ordered_at', 96)" show-overflow-tooltip resizable>
            <template #default="{ row }">{{ text(row.ordered_at) }}</template>
          </el-table-column>
          <el-table-column prop="product_code" label="工厂型号" :width="colWidth('product_code', 96)" show-overflow-tooltip resizable>
            <template #default="{ row }">{{ text(row.product_code) }}</template>
          </el-table-column>
          <el-table-column column-key="image" label="图片" :width="colWidth('image', 52)" align="center" resizable>
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
          <el-table-column prop="color_name" label="颜色" :width="colWidth('color_name', 72)" show-overflow-tooltip resizable>
            <template #default="{ row }">{{ text(row.color_name) }}</template>
          </el-table-column>
          <el-table-column prop="fabric" label="面料" :width="colWidth('fabric', 72)" show-overflow-tooltip resizable>
            <template #default="{ row }">{{ text(row.fabric) }}</template>
          </el-table-column>
          <el-table-column prop="lining" label="内里/垫脚" :width="colWidth('lining', 80)" show-overflow-tooltip resizable>
            <template #default="{ row }">{{ text(row.lining) }}</template>
          </el-table-column>
          <el-table-column prop="brand_name" label="品牌" :width="colWidth('brand_name', 64)" show-overflow-tooltip resizable>
            <template #default="{ row }">{{ text(row.brand_name) }}</template>
          </el-table-column>
          <el-table-column prop="customer_sku" label="客户型号" :width="colWidth('customer_sku', 80)" show-overflow-tooltip resizable>
            <template #default="{ row }">{{ text(row.customer_sku) }}</template>
          </el-table-column>
          <el-table-column column-key="sizes" label="码数" align="center">
            <el-table-column
              v-for="size in sizes"
              :key="size.id"
              :column-key="`size_${size.id}`"
              :label="size.value"
              :width="colWidth(`size_${size.id}`, 32)"
              align="center"
              resizable
            >
              <template #default="{ row }">{{ sizeQty(row, size.id) || '' }}</template>
            </el-table-column>
          </el-table-column>
          <el-table-column column-key="carton_qty" label="箱数" :width="colWidth('carton_qty', 52)" align="right" class-name="shipment-carton-col" resizable>
            <template #default="{ row }">{{ row.carton_qty ?? 0 }}</template>
          </el-table-column>
          <el-table-column
            prop="total_qty"
            label="数量"
            :width="colWidth('total_qty', 80)"
            align="right"
            resizable
          />
          <el-table-column prop="unit_price" label="单价" :width="colWidth('unit_price', 80)" align="right" resizable>
            <template #default="{ row }">{{ formatMoney(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column prop="amount" label="总价" :width="colWidth('amount', 100)" align="right" resizable>
            <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
          </el-table-column>
          <el-table-column prop="line_notes" label="备注" :width="colWidth('line_notes', 64)" show-overflow-tooltip resizable>
            <template #default="{ row }">{{ text(row.line_notes) }}</template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" width="72" fixed="right" :resizable="false">
            <template #default="{ row }">
              <div class="row-actions">
                <el-dropdown
                  v-if="rowActions(row).length"
                  trigger="click"
                  @command="(cmd: string) => runRowAction(row, cmd)"
                >
                  <el-button link type="primary" :icon="MoreFilled" aria-label="更多操作" />
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item v-for="action in rowActions(row)" :key="action.cmd" :command="action.cmd">
                        {{ action.label }}
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
                <span v-else>—</span>
              </div>
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

    <el-dialog v-model="logisticsVisible" title="填写运单" width="420px" :close-on-click-modal="false">
      <el-form label-width="88px">
        <el-form-item label="快递公司">
          <el-input v-model="logisticsForm.company" clearable maxlength="100" placeholder="如顺丰、中通" />
        </el-form-item>
        <el-form-item label="运单号">
          <el-input v-model="logisticsForm.tracking" clearable maxlength="100" placeholder="运单号" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="logisticsVisible = false">取消</el-button>
        <el-button type="primary" :loading="logisticsSaving" @click="saveLogistics">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MoreFilled } from '@element-plus/icons-vue'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const props = withDefaults(defineProps<{ embedded?: boolean; statemented?: boolean }>(), {
  embedded: false,
  statemented: false,
})
const embedded = computed(() => props.embedded)
const statemented = computed(() => props.statemented)
const auth = useAuthStore()
const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths('shipments-list', tableRef, {
  flexKey: 'line_notes',
  flexDefaultMin: 64,
  fitToContainer: true,
  groupEdgeResize: true,
})
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
// 本页是成品仓「已出货」。默认不含草稿和已作废，否则合计会把作废单的数量、总价算进去。
const statusFilter = ref<string | null>('shipped')
const logisticsVisible = ref(false)
const logisticsSaving = ref(false)
const logisticsRow = ref<any>(null)
const logisticsForm = ref({ company: '', tracking: '' })
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

function getSummaries({ columns, data }: { columns: any[]; data?: any[] }) {
  // 只加表格当前这页的单元格，不把其他页的出货单算进合计。
  const source = Array.isArray(data) ? data : rows.value
  let qty = 0
  let amount = 0
  for (const row of source) {
    const q = Number(row?.total_qty || 0)
    if (Number.isFinite(q)) qty += q
    const lineAmount = Number(row?.amount)
    if (Number.isFinite(lineAmount)) amount += lineAmount
  }
  return columns.map((col: any, index: number) => {
    if (index === 0) return '合计'
    const key = col.property || col.columnKey
    if (key === 'total_qty') return String(qty)
    if (key === 'amount') return formatMoney(amount)
    return ''
  })
}

async function load() {
  const res: any = await http.get('/shipments', {
    params: {
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim() || undefined,
      status: statemented.value ? 'shipped' : statusFilter.value || undefined,
      statemented: statemented.value,
    },
  })
  const payload = res.data
  rows.value = payload?.items || (Array.isArray(payload) ? payload : [])
  total.value = payload?.total ?? rows.value.length
  void nextTick(() => {
    measureTableHeight()
    relayoutTable()
    requestAnimationFrame(() => measureTableHeight())
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

function canEditLogistics(row: any) {
  return !statemented.value && row.status !== 'void' && auth.hasPermission('btn.fg_stocks.logistics')
}

function openLogistics(row: any) {
  logisticsRow.value = row
  logisticsForm.value = {
    company: row.logistics_company || '',
    tracking: row.tracking_no || '',
  }
  logisticsVisible.value = true
}

async function saveLogistics() {
  const row = logisticsRow.value
  if (!row) return
  logisticsSaving.value = true
  try {
    await http.post(`/shipments/${row.id}/logistics`, {
      logistics_company: logisticsForm.value.company.trim() || null,
      tracking_no: logisticsForm.value.tracking.trim() || null,
    })
    ElMessage.success('已保存运单')
    logisticsVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '保存失败')
  } finally {
    logisticsSaving.value = false
  }
}

function rowActions(row: any) {
  const actions: { cmd: string; label: string }[] = []
  if (auth.hasPermission('btn.fg_stocks.print')) actions.push({ cmd: 'print', label: '打印' })
  if (auth.hasPermission('btn.fg_stocks.export')) actions.push({ cmd: 'export', label: '导出' })
  if (canEditLogistics(row)) {
    actions.push({ cmd: 'logistics', label: '填写运单' })
  }
  if (row.status === 'draft' && auth.hasPermission('btn.fg_stocks.ship')) {
    actions.push({ cmd: 'confirm', label: '确认出货' })
  }
  if (
    !statemented.value &&
    row.status === 'shipped' &&
    Number(row.carton_qty) > 0 &&
    auth.hasPermission('btn.fg_stocks.return')
  ) {
    actions.push({ cmd: 'return', label: '退回工厂' })
  }
  return actions
}

function runRowAction(row: any, cmd: string) {
  if (!rowActions(row).some(action => action.cmd === cmd)) return
  if (cmd === 'print') return printShipment(row)
  if (cmd === 'export') return exportShipment(row)
  if (cmd === 'logistics') return openLogistics(row)
  if (cmd === 'confirm') return confirm(row)
  if (cmd === 'return') return returnCartons(row)
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
    const res = await ElMessageBox.prompt(`本次退回箱数，最多 ${max} 箱`, '退回工厂', {
      inputPlaceholder: '箱数',
      inputPattern: /^[1-9]\d*$/,
      inputErrorMessage: '请输入正整数箱数',
      confirmButtonText: '退回工厂',
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
.shipments-root.is-embedded {
  flex: 1 1 auto;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
}
.shipments-embedded {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.shipments-embedded > .admin-toolbar {
  flex: 0 0 auto;
}
.shipments-table-host {
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
}
.shipments-embedded > .admin-pagination {
  flex: 0 0 auto;
  margin-top: 0;
}
.shipments-table :deep(.el-table__cell) { padding: 4px 0; }
.shipments-table :deep(.cell) { padding: 0 4px; white-space: nowrap; }
.product-thumb { width: 32px; height: 26px; vertical-align: middle; }
.row-actions {
  display: inline-flex;
  align-items: center;
  white-space: nowrap;
}
.row-actions :deep(.el-dropdown) {
  display: inline-flex;
  align-items: center;
  line-height: 1;
}
.row-actions :deep(.el-button) { margin: 0; }
</style>

