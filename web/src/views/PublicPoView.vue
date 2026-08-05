<template>
  <div class="po-public">
    <div v-if="error" class="err">{{ error }}</div>
    <template v-else-if="detail">
      <header class="head">
        <div class="buyer">{{ detail.buyer_name || '采购方' }}</div>
        <div class="po-no">{{ detail.po_no }}</div>
        <div class="status">{{ detail.status_label || detail.status }}</div>
      </header>

      <section class="card">
        <div class="row"><span>要求到货</span><strong>{{ detail.expected_date || '—' }}</strong></div>
        <div class="row"><span>下单日期</span><strong>{{ orderDate }}</strong></div>
        <div class="row"><span>供应商</span><strong>{{ detail.partner_name || '—' }}</strong></div>
        <div class="row">
          <span>联系人</span>
          <strong>
            {{ detail.partner_contact_name || '—' }}
            <template v-if="detail.partner_contact_mobile">
              · {{ detail.partner_contact_mobile }}
            </template>
          </strong>
        </div>
        <div class="row block">
          <span>供应商地址</span>
          <strong>{{ detail.partner_address || '—' }}</strong>
        </div>
      </section>

      <section class="card">
        <div class="sec-title">采购明细</div>
        <div v-for="(ln, idx) in detail.summary_lines || []" :key="idx" class="line">
          <div class="line-main">
            <div class="code">{{ ln.supplier_product_code }}</div>
            <div class="name">{{ ln.supplier_product_name || '—' }}</div>
          </div>
          <div class="line-meta">
            <span>{{ formatNum(ln.qty) }} {{ ln.pricing_unit_name || '' }}</span>
            <span>¥{{ formatMoney(ln.unit_price) }}</span>
            <strong>¥{{ formatMoney(ln.amount) }}</strong>
          </div>
        </div>
        <div class="total">
          合计金额 <strong>¥{{ formatMoney(detail.summary_total_amount) }}</strong>
        </div>
      </section>

      <section v-if="detail.notes" class="card note">
        <div class="sec-title">备注</div>
        <p>{{ detail.notes }}</p>
      </section>

      <p class="foot-hint">只读预览 · 扫码即可查看</p>
    </template>
    <div v-else class="loading">加载中…</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'

const route = useRoute()
const detail = ref<any>(null)
const error = ref('')

const orderDate = computed(() => {
  const v = detail.value?.ordered_at
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 10)
})

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

onMounted(async () => {
  const token = String(route.params.token || '').trim()
  if (!token) {
    error.value = '链接无效'
    return
  }
  try {
    const res = await axios.get(`/api/v1/public/purchase-orders/${encodeURIComponent(token)}`)
    if (!res.data?.ok) {
      error.value = res.data?.error?.message || '采购单不存在'
      return
    }
    detail.value = res.data.data
    document.title = detail.value?.po_no || '采购单'
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '采购单不存在或链接无效'
  }
})
</script>

<style scoped>
.po-public {
  min-height: 100vh;
  padding: 16px;
  background: #f5f7fa;
  color: #1f2937;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
  max-width: 640px;
  margin: 0 auto;
}
.head {
  background: #fff;
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 12px;
  border: 1px solid #e5e7eb;
}
.buyer {
  font-size: 18px;
  font-weight: 700;
}
.po-no {
  margin-top: 6px;
  font-size: 15px;
  color: #0076ff;
  font-weight: 600;
}
.status {
  margin-top: 4px;
  font-size: 13px;
  color: #64748b;
}
.card {
  background: #fff;
  border-radius: 12px;
  padding: 14px 16px;
  margin-bottom: 12px;
  border: 1px solid #e5e7eb;
}
.row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 0;
  font-size: 14px;
  line-height: 1.45;
}
.row span {
  color: #64748b;
  flex-shrink: 0;
}
.row strong {
  font-weight: 500;
  text-align: right;
}
.row.block {
  flex-direction: column;
  gap: 4px;
}
.row.block strong {
  text-align: left;
}
.sec-title {
  font-weight: 600;
  margin-bottom: 10px;
}
.line {
  padding: 10px 0;
  border-top: 1px solid #f1f5f9;
}
.line:first-of-type {
  border-top: none;
  padding-top: 0;
}
.code {
  font-weight: 600;
  font-size: 14px;
}
.name {
  color: #64748b;
  font-size: 13px;
  margin-top: 2px;
}
.line-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  font-size: 13px;
  color: #475569;
}
.total {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #e5e7eb;
  text-align: right;
  font-size: 15px;
}
.note p {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.5;
  color: #475569;
}
.foot-hint {
  text-align: center;
  color: #94a3b8;
  font-size: 12px;
  margin: 8px 0 24px;
}
.err,
.loading {
  padding: 40px 16px;
  text-align: center;
  color: #64748b;
}
.err {
  color: #c45656;
}
</style>

<style>
body:has(.po-public) #app {
  max-width: none;
  margin: 0;
  background: #f5f7fa;
}
</style>
