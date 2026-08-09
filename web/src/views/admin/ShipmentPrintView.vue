<template>
  <div class="print-page">
    <div class="no-print actions">
      <button type="button" @click="doPrint">打印</button>
      <button type="button" class="ghost" @click="closeOrBack">关闭</button>
    </div>

    <div v-if="error" class="err">{{ error }}</div>
    <template v-else-if="detail">
      <div v-if="detail.status === 'draft'" class="watermark">草稿</div>
      <div v-else-if="detail.status === 'void'" class="watermark muted">作废</div>

      <div class="sheet">
        <h1 class="doc-title">出 货 单</h1>

        <div class="party">
          <div class="party-name">{{ detail.seller_name || '—' }}</div>
          <div>
            <strong>联系人</strong>{{ detail.seller_contact_person || '—' }}
            &nbsp;&nbsp;<strong>电话</strong>{{ detail.seller_contact_mobile || '—' }}
          </div>
          <div><strong>地址</strong>{{ detail.seller_address || '—' }}</div>
        </div>

        <div class="meta-grid">
          <div><strong>出货单号：</strong>{{ detail.shipment_no }}</div>
          <div><strong>出货日期：</strong>{{ detail.ship_date || '—' }}</div>
          <div><strong>生产单：</strong>{{ detail.order_no || '—' }}</div>
          <div><strong>货号：</strong>{{ detail.product_code || '—' }}</div>
          <div><strong>物流：</strong>{{ detail.logistics_company || '—' }}</div>
          <div><strong>运单号：</strong>{{ detail.tracking_no || '—' }}</div>
        </div>

        <div class="party receive">
          <div><strong>收货单位：</strong>{{ detail.customer_name || '—' }}</div>
          <div>
            <strong>联系人：</strong>{{ detail.customer_contact_name || '—' }}
            &nbsp;{{ detail.customer_contact_mobile || '' }}
          </div>
          <div><strong>收货地址：</strong>{{ detail.customer_address || '—' }}</div>
        </div>

        <table>
          <thead>
            <tr>
              <th class="seq">序号</th>
              <th>货号</th>
              <th>颜色</th>
              <th>尺码</th>
              <th class="num">数量</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="ln in detail.lines || []" :key="ln.id">
              <td class="seq">{{ ln.seq }}</td>
              <td>{{ ln.product_code || detail.product_code || '—' }}</td>
              <td>{{ ln.color_name || '—' }}</td>
              <td>{{ ln.size_value || '—' }}</td>
              <td class="num">{{ ln.qty }}</td>
            </tr>
            <tr v-if="!(detail.lines || []).length">
              <td colspan="5" class="empty">（无明细）</td>
            </tr>
          </tbody>
        </table>

        <div class="totals">
          <strong>合计数量：{{ detail.total_qty ?? 0 }} 双</strong>
        </div>

        <div class="note">备注：{{ detail.notes || '无' }}</div>

        <div class="sign">
          <div>
            <label>发货方签字/盖章</label>
            <div class="line" />
            <div class="date">日期：________</div>
          </div>
          <div>
            <label>收货方签字/盖章</label>
            <div class="line" />
            <div class="date">日期：________</div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api/http'

const route = useRoute()
const router = useRouter()

const detail = ref<any>(null)
const error = ref('')

function doPrint() {
  // 清空标题，并临时改写地址，减少浏览器默认页眉/页脚（标题、完整网址）
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
    error.value = '出货单无效'
    return
  }
  try {
    const res: any = await http.get(`/shipments/${id}`)
    detail.value = res.data
  } catch {
    error.value = '出货单不存在或无权查看'
    return
  }
  document.title = ''
  setTimeout(() => doPrint(), 400)
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
  margin: 0 0 16px;
  letter-spacing: 0.28em;
}
.party {
  line-height: 1.65;
  margin-bottom: 12px;
}
.party-name {
  font-size: 16px;
  font-weight: 700;
  margin: 0 0 4px;
}
.party strong {
  display: inline-block;
  min-width: 4em;
  color: #555;
  font-weight: 500;
}
.party.receive {
  margin: 4px 0 14px;
  padding-top: 4px;
}
.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 24px;
  margin: 10px 0 12px;
  line-height: 1.7;
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
}
.empty {
  text-align: center;
  color: #666;
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
