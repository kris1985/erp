<template>
  <div class="print-page" :class="{ 'is-sheet': kind === 'quote' || kind === 'delivery' }">
    <div class="no-print actions">
      <button type="button" @click="printDoc('delivery')">打印送货单</button>
      <button type="button" @click="printDoc('quote')">打印报价单</button>
      <button type="button" class="ghost" @click="closeOrBack">关闭</button>
    </div>

    <div v-if="error" class="err">{{ error }}</div>
    <div v-else-if="detail && !kind" class="pick">请选择送货单或报价单</div>
    <div v-else-if="detail && kind === 'delivery'" class="quote-sheet">
      <h1>送货单</h1>
      <div class="customer">客户：{{ detail.customer_name || '—' }}</div>
      <div class="sub">
        日期 {{ detail.remake_date || '—' }}
        · 送货单号 {{ detail.delivery_no || '—' }}
      </div>
      <table>
        <thead>
          <tr>
            <th>品牌</th>
            <th class="code">工厂型号</th>
            <th class="img">图片</th>
            <th class="color">颜色</th>
            <th class="price">数量</th>
            <th class="price">样品单价</th>
            <th class="price">总价</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(line, index) in lines" :key="line.id || index">
            <td>{{ line.brand || '—' }}</td>
            <td class="code">{{ line.factory_model || '—' }}</td>
            <td class="img">
              <img v-if="line.image_url" :src="line.image_url" alt="" />
              <span v-else class="no-img">无图</span>
            </td>
            <td class="color">{{ line.color || '—' }}</td>
            <td class="price">{{ line.qty ?? '—' }}</td>
            <td class="price">{{ money(line.unit_price) }}</td>
            <td class="price">{{ money(line.total_price) }}</td>
          </tr>
        </tbody>
      </table>
      <div class="footer">合计 {{ totalQty }} · 总价 ¥{{ money(totalAmount) }}</div>
      <div class="sign">
        <div class="company">{{ companyName || '—' }}</div>
        <div class="date">{{ signDate }}</div>
      </div>
    </div>
    <div v-else-if="detail && kind === 'quote'" class="quote-sheet">
      <h1>产品报价单</h1>
      <div class="customer">{{ detail.customer_name ? `客户：${detail.customer_name}` : '统一报价' }}</div>
      <table>
        <thead>
          <tr>
            <th class="idx">#</th>
            <th class="img">图片</th>
            <th class="code">编号</th>
            <th class="color">颜色</th>
            <th class="fabric">面料</th>
            <th class="lining">内里</th>
            <th class="price">价格</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in quoteRows" :key="index">
            <td class="idx">{{ index + 1 }}</td>
            <td class="img">
              <img v-if="row.image_url" :src="row.image_url" alt="" />
              <span v-else class="no-img">无图</span>
            </td>
            <td class="code">{{ row.code || '—' }}</td>
            <td class="color">{{ row.color || '—' }}</td>
            <td class="fabric">{{ row.fabric || '—' }}</td>
            <td class="lining">{{ row.lining || '—' }}</td>
            <td class="price">
              <template v-if="row.price != null">¥{{ money(row.price) }}</template>
              <span v-else class="muted">未报价</span>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="footer">共 {{ quoteRows.length }} 款</div>
      <div class="sign">
        <div class="company">{{ companyName || '—' }}</div>
        <div class="date">{{ signDate }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api/http'

const route = useRoute()
const router = useRouter()
const detail = ref<any>(null)
const error = ref('')
const products = ref<Record<number, any>>({})
const companyName = ref('')

const kind = computed<'delivery' | 'quote' | ''>(() => {
  const doc = String(route.query.doc || '')
  if (doc === 'delivery' || doc === 'quote') return doc
  return ''
})
const lines = computed(() => (detail.value?.lines?.length ? detail.value.lines : []))
const totalQty = computed(() => lines.value.reduce((sum: number, line: any) => sum + Number(line.qty || 0), 0))
const totalAmount = computed(() =>
  lines.value.reduce((sum: number, line: any) => sum + Number(line.total_price || 0), 0),
)
const signDate = computed(() => new Date().toISOString().slice(0, 10))

function hasPrice(value: unknown) {
  return value != null && value !== ''
}

function resolveQuotePrice(product: any, customerId: number | null | undefined, brandName: string | null | undefined) {
  if (!product) return null
  const brand = String(brandName || '').trim().toLowerCase()
  if (brand) {
    const matched = (product.brand_quotes || []).find(
      (item: any) => String(item.brand_name || '').trim().toLowerCase() === brand,
    )
    if (hasPrice(matched?.quote_price)) return Number(matched.quote_price)
  }
  if (customerId != null) {
    const matched = (product.quotes || []).find((item: any) => Number(item.partner_id) === Number(customerId))
    if (hasPrice(matched?.quote_price)) return Number(matched.quote_price)
  }
  if (hasPrice(product.quote_price)) return Number(product.quote_price)
  return null
}

const sheetRows = computed(() =>
  lines.value.map((line: any) => {
    const product = line.own_product_id ? products.value[line.own_product_id] : null
    return {
      image_url: line.image_url || product?.image_url || '',
      code: line.factory_model || product?.product_code || '',
      color: line.color || '',
      fabric: product?.fabric || '',
      lining: product?.lining || '',
      qty: line.qty ?? '—',
      price: resolveQuotePrice(product, detail.value?.customer_id, line.brand),
    }
  }),
)
const quoteRows = sheetRows

function money(value: unknown) {
  return Number(value || 0).toFixed(2)
}

async function printDoc(doc: 'delivery' | 'quote') {
  if (kind.value !== doc) {
    await router.replace({ query: { ...route.query, doc } })
    await nextTick()
  }
  doPrint()
}

function doPrint() {
  const prevTitle = document.title
  const prevUrl = `${location.pathname}${location.search}${location.hash}`
  document.title = ''
  try {
    history.replaceState(null, '', '/')
  } catch {
    /* ignore */
  }
  let restored = false
  const restore = () => {
    if (restored) return
    restored = true
    document.title = prevTitle
    try {
      history.replaceState(null, '', prevUrl)
    } catch {
      /* ignore */
    }
  }
  window.addEventListener('afterprint', restore, { once: true })
  window.print()
}

function closeOrBack() {
  if (window.opener) window.close()
  else router.back()
}

async function load() {
  const id = Number(route.params.id)
  if (!id) {
    error.value = '复版记录无效'
    return
  }
  try {
    const res: any = await http.get(`/sample-remakes/${id}`)
    detail.value = res.data
  } catch {
    error.value = '复版记录不存在或无权查看'
    return
  }
  const ids = [...new Set(lines.value.map((line: any) => line.own_product_id).filter(Boolean))]
  const loaded = await Promise.all(
    ids.map(async (id) => {
      try {
        const product: any = await http.get(`/own-products/${id}`)
        return [id, product.data] as const
      } catch {
        return [id, null] as const
      }
    }),
  )
  products.value = Object.fromEntries(loaded.filter((item) => item[1]))
  try {
    const me: any = await http.get('/auth/me')
    companyName.value = String(me.data?.tenant_name || '').trim()
  } catch {
    companyName.value = ''
  }
  document.title = ''
  if (kind.value) setTimeout(() => doPrint(), 400)
}

onMounted(load)
</script>

<style scoped>
.print-page {
  min-height: 100vh;
  padding: 20px;
  background: #fff;
  color: #111;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
  font-size: 12px;
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
.actions button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.err {
  color: #c45656;
}
.pick {
  color: #666;
}
.quote-sheet {
  max-width: 920px;
  margin: 0 auto;
  color: #111827;
}
.quote-sheet h1 {
  margin: 0 0 14px;
  text-align: center;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0;
}
.quote-sheet .customer,
.quote-sheet .sub {
  text-align: left;
  line-height: 1.4;
}
.quote-sheet .customer {
  margin: 0 0 6px;
  font-size: 16px;
  font-weight: 650;
}
.quote-sheet .sub {
  margin: 0 0 14px;
  font-size: 13px;
  color: #334155;
}
.quote-sheet table {
  width: 100%;
  border-collapse: collapse;
}
.quote-sheet th,
.quote-sheet td {
  border: 1px solid #cbd5e1;
  padding: 8px 10px;
  text-align: left;
  vertical-align: middle;
}
.quote-sheet th {
  background: #0076ff;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
}
.quote-sheet th.idx,
.quote-sheet td.idx {
  width: 40px;
  text-align: center;
}
.quote-sheet th.img,
.quote-sheet td.img {
  width: 72px;
  text-align: center;
}
.quote-sheet td.img img {
  width: 56px;
  height: 56px;
  object-fit: contain;
}
.quote-sheet td.code {
  font-weight: 700;
}
.quote-sheet th.price,
.quote-sheet td.price {
  text-align: right;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.quote-sheet .no-img,
.quote-sheet .muted {
  color: #94a3b8;
  font-size: 12px;
  font-weight: 400;
}
.quote-sheet .footer {
  margin-top: 20px;
  text-align: center;
  color: #64748b;
  font-size: 12px;
}
.quote-sheet .sign {
  margin-top: 40px;
  text-align: right;
}
.quote-sheet .sign .company {
  font-size: 14px;
  font-weight: 650;
  line-height: 1.4;
}
.quote-sheet .sign .date {
  margin-top: 8px;
  font-size: 13px;
  color: #64748b;
}
@media print {
  .no-print {
    display: none !important;
  }
  .print-page {
    padding: 0;
  }
  .quote-sheet {
    max-width: none;
  }
  .quote-sheet th {
    background: #0076ff;
    color: #fff;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
}
</style>

<style>
@page quote-page {
  size: A4 portrait;
  margin: 12mm;
}
.print-page.is-sheet {
  page: quote-page;
}
body:has(.print-page) #app {
  max-width: none;
  margin: 0;
  background: #fff;
}
</style>
