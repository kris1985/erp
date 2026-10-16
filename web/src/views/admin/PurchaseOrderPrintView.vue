<template>
  <div class="print-page">
    <div class="no-print actions">
      <button type="button" @click="doPrint">打印</button>
      <button type="button" class="ghost" @click="closeOrBack">关闭</button>
    </div>

    <div v-if="error" class="err">{{ error }}</div>
    <template v-else-if="detail">
      <div v-if="detail.status === 'draft'" class="watermark">未反馈</div>

      <div class="sheet">
        <div class="doc-head">
          <div class="party">
            <div class="buyer-name">{{ detail.buyer_name || '—' }}</div>
            <div>
              <strong>联系人</strong>{{ detail.buyer_contact_person || '—' }}
              &nbsp;&nbsp;<strong>电话</strong>{{ detail.buyer_contact_mobile || '—' }}
            </div>
            <div><strong>地址</strong>{{ detail.buyer_address || '—' }}</div>
          </div>
          <div class="qr-box">
            <img v-if="qrUrl" :src="qrUrl" alt="qr" />
            <small>{{ detail.po_no }}</small>
            <small class="qr-hint">{{ qrHint }}</small>
          </div>
        </div>
        <div class="meta-grid">
          <div><strong>采购单号：</strong>{{ detail.po_no }}</div>
          <div><strong>协商交货日期：</strong>{{ detail.expected_date || '—' }}</div>
          <div><strong>供应商：</strong>{{ detail.partner_name || '—' }}</div>
          <div><strong>下单日期：</strong>{{ orderDate }}</div>
          <div>
            <strong>联系人：</strong>{{ detail.partner_contact_name || '—' }}
            &nbsp;{{ detail.partner_contact_mobile || '' }}
          </div>
          <div class="span2"><strong>供应商地址：</strong>{{ detail.partner_address || '—' }}</div>
        </div>
        <table>
          <thead>
            <tr>
              <th :rowspan="sizeColumns.length ? 2 : 1">物料编码</th>
              <th :rowspan="sizeColumns.length ? 2 : 1">名称</th>
              <th :rowspan="sizeColumns.length ? 2 : 1">单位</th>
              <th v-if="sizeColumns.length" :colspan="sizeColumns.length">码数</th>
              <th class="mid" :rowspan="sizeColumns.length ? 2 : 1">数量</th>
              <th class="num" :rowspan="sizeColumns.length ? 2 : 1">单价</th>
              <th class="num" :rowspan="sizeColumns.length ? 2 : 1">金额</th>
            </tr>
            <tr v-if="sizeColumns.length">
              <th v-for="size in sizeColumns" :key="size" class="mid">{{ size }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="ln in printRows" :key="ln.key">
              <td>{{ ln.supplier_product_code }}</td>
              <td>{{ ln.supplier_product_name || '—' }}</td>
              <td>{{ ln.pricing_unit_name || '—' }}</td>
              <td v-for="size in sizeColumns" :key="size" class="mid">
                {{ ln.size_qty[size] != null ? formatNum(ln.size_qty[size]) : '—' }}
              </td>
              <td class="mid">{{ formatNum(ln.qty) }}</td>
              <td class="num">{{ formatMoney(ln.unit_price) }}</td>
              <td class="num">{{ formatMoney(ln.amount) }}</td>
            </tr>
          </tbody>
        </table>
        <div class="totals">
          <strong>合计金额：¥{{ formatMoney(printTotal) }}</strong>
        </div>
        <div class="note">
          备注：{{ detail.notes || '无' }}<br />
          {{ detail.tax_note || '' }}
        </div>
        <div class="sign">
          <div>
            <label>采购方签字/盖章</label>
            <div class="line" />
            <div class="date">日期：________</div>
          </div>
          <div>
            <label>供应商签字/盖章</label>
            <div class="line" />
            <div class="date">日期：________</div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const detail = ref<any>(null)
const error = ref('')
const qrUrl = ref('')
const qrHint = '扫码预览（无价格）'

const printRows = computed(() => buildPrintRows(detail.value))

const sizeColumns = computed(() => {
  const lines = detail.value?.lines || []
  const items: { size: string; order: number }[] = []
  const seen = new Set<string>()
  for (const ln of lines) {
    if (!ln.size_value) continue
    const size = String(ln.size_value)
    if (seen.has(size)) continue
    seen.add(size)
    items.push({ size, order: Number(ln.size_sort_order || 0) })
  }
  items.sort((a, b) => a.order - b.order || a.size.localeCompare(b.size, 'zh'))
  return items.map((x) => x.size)
})

const printTotal = computed(() =>
  printRows.value.reduce((sum, row) => sum + Number(row.amount || 0), 0),
)

const orderDate = computed(() => {
  const v = detail.value?.ordered_at
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 10)
})

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, '')
}

function formatMoney(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '0.00'
  return n.toFixed(2)
}

function moneyRound(n: number) {
  return Math.round(n * 100) / 100
}

/** 待下单时损耗还没并进数量；下单之后数量已经含损耗。 */
function purchaseQty(qty: unknown, loss: unknown, status: string) {
  const base = Number(qty || 0)
  if (status !== 'draft') return base
  return Math.round((base + Number(loss || 0)) * 10000) / 10000
}

function buildPrintRows(po: any) {
  if (!po) return []
  const lines = po.lines || []
  const status = String(po.status || '')
  if (!lines.length) {
    return (po.summary_lines || []).map((ln: any) => {
      const qty = purchaseQty(ln.qty, ln.loss_qty, status)
      const price = Number(ln.unit_price || 0)
      return {
        key: String(ln.supplier_product_id),
        supplier_product_code: ln.supplier_product_code,
        supplier_product_name: ln.supplier_product_name,
        pricing_unit_name: ln.pricing_unit_name,
        size_qty: {} as Record<string, number>,
        qty,
        unit_price: price,
        amount: status === 'draft' ? moneyRound(qty * price) : Number(ln.amount || 0),
      }
    })
  }
  const buckets = new Map<number, any>()
  for (const ln of lines) {
    const id = Number(ln.supplier_product_id)
    let bucket = buckets.get(id)
    if (!bucket) {
      bucket = {
        key: String(id),
        supplier_product_id: id,
        supplier_product_code: ln.supplier_product_code,
        supplier_product_name: ln.supplier_product_name,
        pricing_unit_name: ln.pricing_unit_name,
        size_qty: {} as Record<string, number>,
        qty: 0,
        amount: 0,
        unit_price: Number(ln.unit_price || 0),
      }
      buckets.set(id, bucket)
    }
    const buy = purchaseQty(ln.qty, ln.loss_qty, status)
    const price = Number(ln.unit_price || 0)
    bucket.qty = Math.round((bucket.qty + buy) * 10000) / 10000
    bucket.amount += buy * price
    if (ln.size_value) {
      const size = String(ln.size_value)
      bucket.size_qty[size] = Math.round(((bucket.size_qty[size] || 0) + buy) * 10000) / 10000
    }
  }
  const rows = [...buckets.values()]
  rows.sort((a, b) =>
    String(a.supplier_product_code || '').localeCompare(String(b.supplier_product_code || ''), 'zh'),
  )
  for (const row of rows) row.amount = moneyRound(row.amount)
  return rows
}

function doPrint() {
  window.print()
}

function closeOrBack() {
  if (window.opener) window.close()
  else router.back()
}

async function load() {
  const id = Number(route.params.id)
  if (!id) {
    error.value = '采购单无效'
    return
  }
  try {
    const res: any = await http.get(`/purchase-orders/${id}`)
    detail.value = res.data
    // 避免浏览器打印页眉出现「采购订单」标题与多余文案
    document.title = res.data?.po_no || String(id)
  } catch {
    error.value = '采购单不存在或无权查看'
    return
  }
  try {
    const qrRes = await fetch(
      `/api/v1/purchase-orders/${id}/qr.png?purpose=public`,
      {
        headers: auth.token ? { Authorization: `Bearer ${auth.token}` } : {},
      },
    )
    if (qrRes.ok) {
      qrUrl.value = URL.createObjectURL(await qrRes.blob())
    }
  } catch {
    /* ignore */
  }
  setTimeout(() => window.print(), 400)
}

onMounted(load)
onBeforeUnmount(() => {
  if (qrUrl.value) URL.revokeObjectURL(qrUrl.value)
})
</script>

<style scoped>
.print-page {
  min-height: 100vh;
  padding: 20px;
  background: #fff;
  color: #111;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
  font-size: 12px;
  position: relative;
}
.actions {
  margin-bottom: 12px;
}
.actions button {
  margin-right: 8px;
  padding: 6px 12px;
  border: 1px solid #ccc;
  background: #0076ff;
  color: #fff;
  border-radius: 6px;
  cursor: pointer;
}
.actions button.ghost {
  background: #fff;
  color: #333;
}
.err {
  color: #c45656;
}
.sheet {
  position: relative;
  max-width: 1100px;
  margin: 0 auto;
}
.doc-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}
.buyer-name {
  font-size: 18px;
  font-weight: 700;
  margin: 0 0 6px;
}
.party {
  line-height: 1.65;
}
.party strong {
  display: inline-block;
  min-width: 4em;
  color: #555;
  font-weight: 500;
}
.qr-box {
  text-align: center;
  flex-shrink: 0;
}
.qr-box img {
  width: 88px;
  height: 88px;
  display: block;
  margin: 0 auto 4px;
}
.qr-box small {
  display: block;
  color: #666;
}
.qr-box .qr-hint {
  font-size: 10px;
  color: #999;
}
.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 24px;
  margin: 10px 0 14px;
  line-height: 1.7;
}
.span2 {
  grid-column: 1 / -1;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  border: 1px solid #333;
  padding: 7px 8px;
  text-align: left;
  vertical-align: middle;
}
th {
  background: #f3f4f6;
  font-weight: 600;
}
.num {
  text-align: right !important;
}
.mid {
  text-align: center !important;
}
.totals {
  margin-top: 10px;
  text-align: right;
  font-size: 13px;
  line-height: 1.7;
}
.note {
  margin-top: 10px;
  color: #444;
}
.sign {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 40px;
  margin-top: 36px;
}
.sign .line {
  margin-top: 28px;
  border-bottom: 1px solid #333;
  height: 1px;
}
.sign label {
  color: #555;
}
.sign .date {
  margin-top: 8px;
}
.watermark {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  z-index: 0;
  opacity: 0.12;
  font-size: 72px;
  font-weight: 700;
  color: #c45656;
  transform: rotate(-24deg);
}
.sheet > * {
  position: relative;
  z-index: 1;
}

@media print {
  .no-print {
    display: none !important;
  }
  .print-page {
    padding: 0;
  }
}
</style>

<style>
/* 打印页不受 H5 窄容器限制 */
body:has(.print-page) #app {
  max-width: none;
  margin: 0;
  background: #fff;
}
</style>
