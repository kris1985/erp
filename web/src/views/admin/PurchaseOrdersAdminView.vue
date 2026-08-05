<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">采购单</h1>
        <p class="page-desc">下单 · 发货 · 到货登记</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-select v-model="status" clearable placeholder="状态" style="width: 140px" @change="load">
          <el-option label="草稿" value="draft" />
          <el-option label="已下单" value="ordered" />
          <el-option label="已发货" value="shipped" />
          <el-option label="部分到货" value="partial_received" />
          <el-option label="已到齐" value="received" />
          <el-option label="已取消" value="cancelled" />
        </el-select>
        <el-select v-model="alertFilter" clearable placeholder="交期告警" style="width: 140px" @change="load">
          <el-option label="逾期未到" value="overdue" />
          <el-option label="即将到期" value="due_soon" />
        </el-select>
        <el-tag v-if="overdueCount" type="danger" effect="plain">逾期 {{ overdueCount }}</el-tag>
        <el-tag v-if="dueSoonCount" type="warning" effect="plain">即将到期 {{ dueSoonCount }}</el-tag>
        <el-button @click="load">刷新</el-button>
      </div>
      <el-table :data="rows" stripe border style="width: 100%">
        <el-table-column prop="po_no" label="采购单号" min-width="130">
          <template #default="{ row }">
            <el-button link type="primary" @click="open(row)">{{ row.po_no }}</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="partner_name" label="供应商" min-width="120" />
        <el-table-column label="状态" min-width="90">
          <template #default="{ row }">{{ poStatusLabel(row.status) }}</template>
        </el-table-column>
        <el-table-column label="下单时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.ordered_at) }}</template>
        </el-table-column>
        <el-table-column label="预计到货" min-width="120">
          <template #default="{ row }">
            <span :class="{ 'text-danger': row.delivery_alert === 'overdue', 'text-warn': row.delivery_alert === 'due_soon' }">
              {{ row.expected_date || '—' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="交期告警" min-width="130">
          <template #default="{ row }">
            <el-tag v-if="row.delivery_alert === 'overdue'" type="danger" size="small">
              {{ row.delivery_alert_label }}
            </el-tag>
            <el-tag v-else-if="row.delivery_alert === 'due_soon'" type="warning" size="small">
              {{ row.delivery_alert_label }}
            </el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="tracking_no" label="运单号" min-width="120">
          <template #default="{ row }">
            <template v-if="row.tracking_no">
              {{ row.tracking_no }}
              <el-button
                v-if="row.tracking_search_url"
                link
                type="primary"
                @click="windowOpen(row.tracking_search_url)"
              >查询</el-button>
            </template>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="采购汇总" min-width="200">
          <template #default="{ row }">
            <div v-for="ln in row.summary_lines || []" :key="ln.supplier_product_id" class="muted">
              {{ ln.supplier_product_code }} × {{ formatNum(ln.qty) }}
            </div>
            <span v-if="!(row.summary_lines || []).length" class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'draft'" link type="primary" @click="submit(row)">下单</el-button>
            <el-button
              v-if="row.status === 'ordered' || row.status === 'shipped'"
              link
              @click="openReceive(row)"
            >到货</el-button>
            <el-button
              v-if="row.status === 'ordered'"
              link
              @click="markShip(row)"
            >标发货</el-button>
            <el-button v-if="row.status === 'draft'" link type="danger" @click="cancel(row)">取消</el-button>
            <el-button
              v-if="['partial_received', 'ordered', 'shipped'].includes(row.status)"
              link
              @click="closeOpen(row)"
            >关闭未交</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="detailVisible" :title="detail?.po_no" size="720px">
      <template v-if="detail">
        <div class="detail-actions">
          <el-button @click="exportDoc">导出</el-button>
          <el-button type="primary" plain @click="printPo">打印</el-button>
        </div>
        <el-descriptions :column="1" border size="small" style="margin-bottom: 12px">
          <el-descriptions-item label="买方">{{ detail.buyer_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="供应商">{{ detail.partner_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ poStatusLabel(detail.status) }}</el-descriptions-item>
          <el-descriptions-item label="下单时间">{{ formatDateTime(detail.ordered_at) }}</el-descriptions-item>
          <el-descriptions-item label="交期告警">
            <el-tag v-if="detail.delivery_alert === 'overdue'" type="danger" size="small">
              {{ detail.delivery_alert_label }}
            </el-tag>
            <el-tag v-else-if="detail.delivery_alert === 'due_soon'" type="warning" size="small">
              {{ detail.delivery_alert_label }}
            </el-tag>
            <span v-else class="muted">正常</span>
          </el-descriptions-item>
        </el-descriptions>
        <el-form label-width="100px" style="margin-bottom: 16px">
          <el-form-item label="预计到货">
            <el-date-picker
              v-model="detail.expected_date"
              type="date"
              value-format="YYYY-MM-DD"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item label="物流公司">
            <el-input v-model="detail.logistics_company" />
          </el-form-item>
          <el-form-item label="运单号">
            <el-input v-model="detail.tracking_no" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="detail.notes" type="textarea" />
          </el-form-item>
          <el-button type="primary" @click="saveMeta">保存</el-button>
        </el-form>

        <div class="section-head">
          <strong>采购汇总</strong>
          <span class="muted">
            按物料合计 · 金额 ¥{{ formatMoney(detail.summary_total_amount) }}
          </span>
        </div>
        <el-table :data="detail.summary_lines || []" border size="small" style="width: 100%; margin-bottom: 16px">
          <el-table-column label="图片" width="70" align="center">
            <template #default="{ row }">
              <el-image
                v-if="row.image_url"
                :src="row.image_url"
                :preview-src-list="[row.image_url]"
                fit="contain"
                class="mat-thumb"
                preview-teleported
              />
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column prop="supplier_product_code" label="物料编码" min-width="110" />
          <el-table-column prop="supplier_product_name" label="名称" min-width="120">
            <template #default="{ row }">{{ row.supplier_product_name || '—' }}</template>
          </el-table-column>
          <el-table-column label="单位" width="70">
            <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
          </el-table-column>
          <el-table-column label="数量" min-width="90" align="right">
            <template #default="{ row }">{{ formatNum(row.qty) }}</template>
          </el-table-column>
          <el-table-column label="已到" min-width="70" align="right">
            <template #default="{ row }">{{ formatNum(row.received_qty) }}</template>
          </el-table-column>
          <el-table-column label="单价" min-width="120" align="right">
            <template #default="{ row }">
              <el-input-number
                v-if="detail.status === 'draft'"
                :model-value="Number(row.unit_price || 0)"
                :min="0"
                :precision="2"
                :step="0.01"
                :controls="false"
                size="small"
                style="width: 100px"
                @change="(v: number) => onSummaryPrice(row, v)"
              />
              <span v-else>{{ formatMoney(row.unit_price) }}</span>
              <div v-if="row.price_mixed" class="text-warn" style="font-size: 12px">分订单单价不一致</div>
            </template>
          </el-table-column>
          <el-table-column label="金额" min-width="90" align="right">
            <template #default="{ row }">¥{{ formatMoney(row.amount) }}</template>
          </el-table-column>
          <el-table-column label="最近成交价" min-width="90" align="right">
            <template #default="{ row }">
              {{ row.last_purchase_price != null ? formatMoney(row.last_purchase_price) : '—' }}
            </template>
          </el-table-column>
        </el-table>

        <div class="section-head">
          <strong>分订单明细</strong>
          <span class="muted">到货回写用 · 不合并</span>
        </div>
        <el-table :data="detail.lines" border size="small" style="width: 100%">
          <el-table-column prop="supplier_product_code" label="物料" min-width="100" />
          <el-table-column prop="order_no" label="订单" min-width="90" />
          <el-table-column label="单位" width="70">
            <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
          </el-table-column>
          <el-table-column label="数量" min-width="70" align="right">
            <template #default="{ row }">{{ formatNum(row.qty) }}</template>
          </el-table-column>
          <el-table-column label="已到" min-width="70" align="right">
            <template #default="{ row }">{{ formatNum(row.received_qty) }}</template>
          </el-table-column>
          <el-table-column label="单价" min-width="80" align="right">
            <template #default="{ row }">{{ formatMoney(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column label="最近成交价" min-width="100" align="right">
            <template #default="{ row }">
              {{ row.last_purchase_price != null ? formatMoney(row.last_purchase_price) : '—' }}
            </template>
          </el-table-column>
        </el-table>
      </template>
    </el-drawer>

    <el-dialog v-model="recvVisible" title="到货登记" width="760px" destroy-on-close>
      <p class="recv-hint muted">
        到货先入库存池；挂订单的行会按未收订购量自动分配到订单（齐套占用）。超收留在池中。
      </p>

      <div v-if="recvBatches.length" class="recv-batch">
        <div class="section-head">
          <strong>按物料录总量</strong>
          <span class="muted">填写后点「建议拆分」按未收比例拆到各订单行，可再改</span>
        </div>
        <el-table :data="recvBatches" border size="small" style="width: 100%; margin-bottom: 14px">
          <el-table-column prop="supplier_product_code" label="物料" min-width="110" />
          <el-table-column prop="supplier_product_name" label="名称" min-width="120">
            <template #default="{ row }">{{ row.supplier_product_name || '—' }}</template>
          </el-table-column>
          <el-table-column label="未收合计" min-width="90" align="right">
            <template #default="{ row }">{{ formatNum(row.open_total) }}</template>
          </el-table-column>
          <el-table-column label="本次总量" min-width="140" align="right">
            <template #default="{ row }">
              <el-input-number v-model="row.total_qty" :min="0" :step="1" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="" width="100" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="suggestSplit(row)">建议拆分</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="section-head">
        <strong>分订单明细</strong>
      </div>
      <el-table :data="recvLines" border size="small" style="width: 100%">
        <el-table-column prop="supplier_product_code" label="物料" min-width="100" />
        <el-table-column label="订单号" min-width="110">
          <template #default="{ row }">
            <span v-if="row.order_no">{{ row.order_no }}</span>
            <span v-else class="muted">无挂单</span>
          </template>
        </el-table-column>
        <el-table-column label="订购" min-width="70" align="right">
          <template #default="{ row }">{{ formatNum(row.qty) }}</template>
        </el-table-column>
        <el-table-column label="已到" min-width="70" align="right">
          <template #default="{ row }">{{ formatNum(row.received_qty) }}</template>
        </el-table-column>
        <el-table-column label="未收" min-width="70" align="right">
          <template #default="{ row }">{{ formatNum(row.open_qty) }}</template>
        </el-table-column>
        <el-table-column label="本次" min-width="140" align="right">
          <template #default="{ row }">
            <el-input-number v-model="row.this_qty" :min="0" :step="1" size="small" />
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="recvVisible = false">取消</el-button>
        <el-button type="primary" @click="doReceive">确认到货</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const rows = ref<any[]>([])
const status = ref<string>()
const alertFilter = ref<string>()
const detailVisible = ref(false)
const detail = ref<any>(null)
const recvVisible = ref(false)
const recvLines = ref<any[]>([])
const recvBatches = ref<any[]>([])
const recvPoId = ref(0)

const overdueCount = computed(() => rows.value.filter((r) => r.delivery_alert === 'overdue').length)
const dueSoonCount = computed(() => rows.value.filter((r) => r.delivery_alert === 'due_soon').length)

const PO_STATUS: Record<string, string> = {
  draft: '草稿',
  ordered: '已下单',
  shipped: '已发货',
  partial_received: '部分到货',
  received: '已到齐',
  cancelled: '已取消',
}

function poStatusLabel(s: string) {
  return PO_STATUS[s] || s || '—'
}

function formatDateTime(v: string | null | undefined) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 19)
}

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

function formatMoney(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '0.00'
  return n.toFixed(2)
}

function windowOpen(url: string) {
  window.open(url, '_blank')
}

async function load() {
  const res: any = await http.get('/purchase-orders', {
    params: {
      status: status.value || undefined,
      delivery_alert: alertFilter.value || undefined,
    },
  })
  rows.value = res.data || []
}

async function open(row: any) {
  const res: any = await http.get(`/purchase-orders/${row.id}`)
  detail.value = res.data
  detailVisible.value = true
}

async function saveMeta() {
  if (!detail.value) return
  await http.patch(`/purchase-orders/${detail.value.id}`, {
    expected_date: detail.value.expected_date || undefined,
    logistics_company: detail.value.logistics_company,
    tracking_no: detail.value.tracking_no,
    notes: detail.value.notes,
  })
  ElMessage.success('已保存')
  detailVisible.value = false
  load()
}

async function onSummaryPrice(row: any, v: number) {
  if (!detail.value || detail.value.status !== 'draft') return
  const res: any = await http.patch(`/purchase-orders/${detail.value.id}/summary-price`, {
    supplier_product_id: row.supplier_product_id,
    unit_price: v,
  })
  detail.value = res.data
  ElMessage.success('已按合计数量更新单价')
  load()
}

async function choosePoDocMode(action: '导出' | '打印'): Promise<boolean | null> {
  if (!detail.value) return null
  if (detail.value.status === 'draft') {
    try {
      await ElMessageBox.confirm(
        action === '打印'
          ? '当前为草稿，确认仍要打印？建议下单后再发给供应商。'
          : '当前为草稿，确认仍要导出？',
        `${action}确认`,
        {
          type: 'warning',
          confirmButtonText: `继续${action}`,
          cancelButtonText: '取消',
        },
      )
    } catch {
      return null
    }
  }
  try {
    await ElMessageBox.confirm(`请选择${action}内容`, `${action}采购单`, {
      distinguishCancelAndClose: true,
      confirmButtonText: '完整（含内部明细）',
      cancelButtonText: '仅供应商联',
      type: 'info',
    })
    return true
  } catch (actionType) {
    if (actionType === 'close') return null
    return false
  }
}

async function exportDoc() {
  const includeInternal = await choosePoDocMode('导出')
  if (includeInternal === null || !detail.value) return
  const d = detail.value
  const res = await fetch(
    `/api/v1/purchase-orders/${d.id}/export?internal=${includeInternal ? '1' : '0'}`,
    { headers: auth.token ? { Authorization: `Bearer ${auth.token}` } : {} },
  )
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
  let filename = `${d.po_no || 'po'}.xlsx`
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

async function printPo() {
  const includeInternal = await choosePoDocMode('打印')
  if (includeInternal === null || !detail.value) return
  // 用真实路由打开，避免打印页脚出现 about:blank
  const url = `${window.location.origin}/admin/purchase-orders/print/${detail.value.id}?internal=${includeInternal ? '1' : '0'}`
  const w = window.open(url, '_blank')
  if (!w) ElMessage.warning('请允许弹出窗口以打印')
}

async function submit(row: any) {
  let expected = row.expected_date as string | undefined
  try {
    const { value } = await ElMessageBox.prompt('请填写预计到货日期（YYYY-MM-DD）', '确认下单', {
      inputValue: expected || new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10),
      inputPattern: /^\d{4}-\d{2}-\d{2}$/,
      inputErrorMessage: '日期格式应为 YYYY-MM-DD',
    })
    expected = value
  } catch {
    return
  }
  if (expected) {
    await http.patch(`/purchase-orders/${row.id}`, { expected_date: expected })
  }
  await http.post(`/purchase-orders/${row.id}/submit`)
  ElMessage.success('已下单')
  load()
}

async function cancel(row: any) {
  await http.post(`/purchase-orders/${row.id}/cancel`)
  ElMessage.success('已取消')
  load()
}

async function closeOpen(row: any) {
  await http.post(`/purchase-orders/${row.id}/close-open`)
  ElMessage.success('已关闭未交')
  load()
}

async function markShip(row: any) {
  await http.post(`/purchase-orders/${row.id}/ship`, {})
  ElMessage.success('已标记发货')
  load()
}

async function openReceive(row: any) {
  const res: any = await http.get(`/purchase-orders/${row.id}`)
  const po = res.data
  recvPoId.value = po.id
  recvLines.value = (po.lines || []).map((ln: any) => {
    const open = Math.max(0, Number(ln.qty) - Number(ln.received_qty || 0))
    return {
      ...ln,
      open_qty: open,
      this_qty: open,
    }
  })
  const bySp = new Map<number, any>()
  for (const ln of recvLines.value) {
    const spId = ln.supplier_product_id
    if (!bySp.has(spId)) {
      bySp.set(spId, {
        supplier_product_id: spId,
        supplier_product_code: ln.supplier_product_code,
        supplier_product_name: ln.supplier_product_name,
        open_total: 0,
        total_qty: 0,
      })
    }
    const b = bySp.get(spId)
    b.open_total += Number(ln.open_qty) || 0
  }
  for (const b of bySp.values()) {
    b.total_qty = b.open_total
  }
  recvBatches.value = [...bySp.values()]
  recvVisible.value = true
}

/** 按未收订购量比例拆分；同物料多订单时优先填未收>0 的行 */
function suggestSplit(batch: any) {
  const spId = batch.supplier_product_id
  const total = Math.max(0, Number(batch.total_qty) || 0)
  const lines = recvLines.value.filter((l) => l.supplier_product_id === spId)
  const openSum = lines.reduce((s, l) => s + (Number(l.open_qty) || 0), 0)
  // 先清零
  for (const ln of lines) ln.this_qty = 0
  if (total <= 0 || lines.length === 0) return
  if (openSum <= 0) {
    // 全部超收：记在第一行
    lines[0].this_qty = total
    return
  }
  let left = total
  // 按未收比例分配，最后一行吃尾差
  const withOpen = lines.filter((l) => Number(l.open_qty) > 0)
  withOpen.forEach((ln, idx) => {
    const open = Number(ln.open_qty) || 0
    if (idx === withOpen.length - 1) {
      ln.this_qty = Math.max(0, left)
      return
    }
    const share = Math.min(open, Math.round((total * open) / openSum))
    ln.this_qty = share
    left -= share
  })
  // 总量超过未收合计：余量加到最后一行（超收进池）
  if (left > 0 && withOpen.length) {
    withOpen[withOpen.length - 1].this_qty = Number(withOpen[withOpen.length - 1].this_qty) + left
  } else if (left > 0 && lines.length) {
    lines[0].this_qty = Number(lines[0].this_qty) + left
  }
  ElMessage.success('已按未收比例建议拆分，可再手工调整')
}

async function doReceive() {
  const payload = recvLines.value
    .filter((l) => Number(l.this_qty) > 0)
    .map((l) => ({ line_id: l.id, qty: l.this_qty }))
  if (!payload.length) {
    ElMessage.warning('请填写本次到货数量')
    return
  }
  await http.post(`/purchase-orders/${recvPoId.value}/receive`, { lines: payload })
  ElMessage.success('到货已登记（入池并自动分配挂单行）')
  recvVisible.value = false
  load()
  if (detailVisible.value && detail.value?.id === recvPoId.value) {
    open({ id: recvPoId.value })
  }
}

onMounted(load)
</script>

<style scoped>
.text-danger {
  color: #c45656;
  font-weight: 600;
}
.text-warn {
  color: #c45c26;
  font-weight: 600;
}
.detail-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.section-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 4px 0 8px;
}
.recv-hint {
  margin: 0 0 12px;
  font-size: 13px;
  line-height: 1.5;
}
.recv-batch {
  margin-bottom: 8px;
}
.mat-thumb {
  width: 40px;
  height: 40px;
  border-radius: 6px;
  background: #f8fafc;
  display: block;
  margin: 0 auto;
}
</style>
