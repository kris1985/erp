<template>
  <div class="print-page">
    <div class="no-print actions">
      <button type="button" @click="doPrint">打印</button>
      <button type="button" class="ghost" @click="closeOrBack">关闭</button>
    </div>

    <div v-if="error" class="err">{{ error }}</div>
    <template v-else-if="detail">
      <div v-if="detail.is_rush" class="watermark">急单</div>
      <div v-else-if="detail.status === 'cancelled'" class="watermark muted">已取消</div>

      <!-- MERGE_BATCH_MEMBERS: 合批卡见 MergeBatchFlowCardPrintView（B2f） -->
      <div class="sheet">
        <h1 class="doc-title">生 产 流 转 卡</h1>
        <p class="doc-sub">开裁 / 配码 · 生产单</p>

        <div class="meta-grid">
          <div><strong>生产单号：</strong>{{ detail.order_no }}</div>
          <div><strong>交期：</strong>{{ detail.delivery_date || '—' }}</div>
          <div><strong>货号：</strong>{{ detail.product_code || '—' }}</div>
          <div><strong>总数量：</strong>{{ detail.total_qty ?? 0 }} 双</div>
          <div><strong>客户：</strong>{{ detail.customer_name || '—' }}</div>
          <div>
            <strong>关联销售单：</strong>{{ detail.sales_order_no || '—' }}
          </div>
        </div>

        <div class="section-title">色码数量</div>
        <table>
          <thead>
            <tr>
              <th class="seq">序号</th>
              <th>颜色</th>
              <th>尺码</th>
              <th class="num">数量</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(it, idx) in detail.items || []" :key="it.id || idx">
              <td class="seq">{{ idx + 1 }}</td>
              <td>{{ it.color_name || '—' }}</td>
              <td>{{ it.size_value || '—' }}</td>
              <td class="num">{{ it.qty }}</td>
            </tr>
            <tr v-if="!(detail.items || []).length">
              <td colspan="4" class="empty">（无色码明细，请先在生产单维护色码）</td>
            </tr>
          </tbody>
        </table>
        <div class="totals">
          <strong>合计：{{ itemsTotal }} 双</strong>
          <span v-if="qtyMismatch" class="warn">（与单头总数量 {{ detail.total_qty }} 不一致，请核对）</span>
        </div>

        <div class="section-title">工序流转</div>
        <table>
          <thead>
            <tr>
              <th class="seq">序</th>
              <th>工序</th>
              <th class="num">计划</th>
              <th class="chk">完成</th>
              <th>签字/日期</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(p, idx) in detail.processes || []" :key="p.id || idx">
              <td class="seq">{{ idx + 1 }}</td>
              <td>{{ p.process_name || '—' }}</td>
              <td class="num">{{ p.plan_qty ?? '—' }}</td>
              <td class="chk">□</td>
              <td class="sign-cell" />
            </tr>
            <tr v-if="!(detail.processes || []).length">
              <td colspan="5" class="empty">（无工序，请先在产品工艺维护后同步到生产单）</td>
            </tr>
          </tbody>
        </table>

        <div class="note">备注：{{ detail.notes || '无' }}</div>

        <div class="sign">
          <div>
            <label>开卡 / PMC</label>
            <div class="line" />
            <div class="date">日期：________</div>
          </div>
          <div>
            <label>裁床确认</label>
            <div class="line" />
            <div class="date">日期：________</div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api/http'

const route = useRoute()
const router = useRouter()

const detail = ref<any>(null)
const error = ref('')

const itemsTotal = computed(() =>
  (detail.value?.items || []).reduce((s: number, it: any) => s + Number(it.qty || 0), 0),
)

const qtyMismatch = computed(() => {
  if (!detail.value) return false
  const head = Number(detail.value.total_qty || 0)
  return head > 0 && itemsTotal.value > 0 && head !== itemsTotal.value
})

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
    error.value = '生产单无效'
    return
  }
  try {
    const res: any = await http.get(`/orders/${id}`)
    detail.value = res.data
  } catch {
    error.value = '生产单不存在或无权查看'
    return
  }
  document.title = detail.value?.order_no ? `流转卡 ${detail.value.order_no}` : ''
  setTimeout(() => {
    document.title = ''
    doPrint()
  }, 400)
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
  max-width: 900px;
  margin: 0 auto;
}
.doc-title {
  font-size: 22px;
  font-weight: 700;
  text-align: center;
  margin: 0;
  letter-spacing: 0.28em;
}
.doc-sub {
  text-align: center;
  margin: 6px 0 16px;
  color: #555;
  font-size: 12px;
  letter-spacing: 0.08em;
}
.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 24px;
  margin: 10px 0 14px;
  line-height: 1.7;
}
.meta-grid strong {
  color: #555;
  font-weight: 500;
}
.section-title {
  margin: 16px 0 8px;
  font-size: 13px;
  font-weight: 700;
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
.seq {
  text-align: center !important;
  width: 48px;
}
.num {
  text-align: right !important;
  width: 72px;
}
.chk {
  text-align: center !important;
  width: 56px;
  font-size: 14px;
}
.sign-cell {
  min-width: 120px;
  height: 28px;
}
.empty {
  text-align: center;
  color: #666;
}
.totals {
  margin-top: 8px;
  text-align: right;
  font-size: 13px;
  line-height: 1.7;
}
.totals .warn {
  margin-left: 8px;
  color: #c45656;
  font-size: 12px;
}
.note {
  margin-top: 12px;
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
.watermark.muted {
  color: #888;
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
    padding: 12mm 14mm;
  }
  .sheet {
    max-width: none;
    width: 100%;
    margin: 0 auto;
  }
}
</style>

<style>
@page {
  size: A4 portrait;
  margin: 12mm 14mm;
}
body:has(.print-page) #app {
  max-width: none;
  margin: 0;
  background: #fff;
}
</style>
