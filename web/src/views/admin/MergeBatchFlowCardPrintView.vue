<template>
  <div class="print-page">
    <div class="no-print actions">
      <button type="button" @click="doPrint">打印</button>
      <button type="button" class="ghost" @click="closeOrBack">关闭</button>
    </div>

    <div v-if="error" class="err">{{ error }}</div>
    <template v-else-if="detail">
      <div class="sheet">
        <h1 class="doc-title">合 批 流 转 卡</h1>
        <p class="doc-sub">开裁 / 配码 · 合批（领料报工仍分生产单）</p>

        <div class="meta-grid">
          <div><strong>合批号：</strong>{{ detail.batch_no }}</div>
          <div><strong>货号：</strong>{{ detail.product_code || '—' }}</div>
          <div><strong>颜色：</strong>{{ detail.color_name || '多色/未锁定' }}</div>
          <div><strong>总数量：</strong>{{ detail.total_qty ?? 0 }} 双</div>
          <div><strong>成员单数：</strong>{{ detail.member_count ?? 0 }}</div>
          <div><strong>状态：</strong>{{ statusLabel }}</div>
        </div>

        <div class="section-title">成员生产单</div>
        <table>
          <thead>
            <tr>
              <th class="seq">序号</th>
              <th>生产单号</th>
              <th>客户</th>
              <th>交期</th>
              <th class="num">数量</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(m, idx) in detail.members || []" :key="m.order_id || idx">
              <td class="seq">{{ idx + 1 }}</td>
              <td>{{ m.order_no }}</td>
              <td>{{ m.customer_name || '—' }}</td>
              <td>{{ m.delivery_date || '—' }}</td>
              <td class="num">{{ m.total_qty }}</td>
            </tr>
            <tr v-if="!(detail.members || []).length">
              <td colspan="5" class="empty">（无成员）</td>
            </tr>
          </tbody>
        </table>

        <div class="section-title">汇总色码</div>
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
            <tr v-for="(it, idx) in detail.size_summary || []" :key="`${it.color_id}-${it.size_id}-${idx}`">
              <td class="seq">{{ idx + 1 }}</td>
              <td>{{ it.color_name || '—' }}</td>
              <td>{{ it.size_value || '—' }}</td>
              <td class="num">{{ it.qty }}</td>
            </tr>
            <tr v-if="!(detail.size_summary || []).length">
              <td colspan="4" class="empty">（无汇总色码）</td>
            </tr>
          </tbody>
        </table>
        <div class="totals">
          <strong>合计：{{ itemsTotal }} 双</strong>
        </div>

        <div class="section-title">工序流转（纸面参考，报工仍分单）</div>
        <table>
          <thead>
            <tr>
              <th class="seq">序</th>
              <th>工序</th>
              <th class="num">计划合计</th>
              <th class="chk">完成</th>
              <th>签字/日期</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(p, idx) in detail.processes || []" :key="p.process_id || idx">
              <td class="seq">{{ idx + 1 }}</td>
              <td>{{ p.process_name || '—' }}</td>
              <td class="num">{{ p.plan_qty ?? '—' }}</td>
              <td class="chk">□</td>
              <td class="sign-cell" />
            </tr>
            <tr v-if="!(detail.processes || []).length">
              <td colspan="5" class="empty">（成员尚无工序，可仅作开裁色码参考）</td>
            </tr>
          </tbody>
        </table>

        <div class="note">备注：{{ detail.note || '无' }}</div>

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
  (detail.value?.size_summary || []).reduce((s: number, it: any) => s + Number(it.qty || 0), 0),
)

const statusLabel = computed(() => {
  const s = detail.value?.status
  if (s === 'open') return '进行中'
  if (s === 'closed') return '已关闭'
  if (s === 'void') return '已作废'
  return s || '—'
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
    error.value = '合批无效'
    return
  }
  try {
    const res: any = await http.get(`/merge-batches/${id}`)
    detail.value = res.data
  } catch {
    error.value = '合批不存在或无权查看'
    return
  }
  document.title = detail.value?.batch_no ? `合批卡 ${detail.value.batch_no}` : ''
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
  gap: 6px 16px;
  margin-bottom: 14px;
  line-height: 1.5;
}
.section-title {
  margin: 14px 0 6px;
  font-weight: 700;
  border-bottom: 1px solid #333;
  padding-bottom: 2px;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  border: 1px solid #333;
  padding: 4px 6px;
  text-align: left;
}
th {
  background: #f3f3f3;
}
.seq {
  width: 44px;
  text-align: center;
}
.num {
  width: 72px;
  text-align: right;
}
.chk {
  width: 48px;
  text-align: center;
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
  margin: 6px 0 0;
}
.note {
  margin-top: 14px;
}
.sign {
  display: flex;
  gap: 48px;
  margin-top: 28px;
}
.sign .line {
  border-bottom: 1px solid #333;
  height: 28px;
  min-width: 160px;
}
.sign .date {
  margin-top: 8px;
  color: #555;
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
