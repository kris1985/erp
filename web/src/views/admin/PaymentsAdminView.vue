<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">回款登记</h1>
        <p class="page-desc">收款并核销到应收（禁止超额）</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-button type="primary" @click="openCreate">登记回款</el-button>
        <el-button @click="load">刷新</el-button>
      </div>
      <div ref="tableHostRef">
      <el-table ref="tableRef" :data="rows" stripe border style="width: 100%" :max-height="tableMaxHeight" @header-dragend="onHeaderDragend">
        <el-table-column prop="payment_date" label="日期" :width="colWidth('payment_date', 110)" resizable />
        <el-table-column prop="customer_name" label="客户" :width="colWidth('customer_name', 120)" resizable />
        <el-table-column prop="amount" label="金额" :width="colWidth('amount', 100)" resizable />
        <el-table-column column-key="方式" label="方式" :width="colWidth('方式', 90)" resizable>
          <template #default="{ row }">{{ methodLabel(row.method) }}</template>
        </el-table-column>
        <el-table-column prop="voucher_no" label="凭证号" :width="colWidth('voucher_no', 120)" resizable />
        <el-table-column column-key="status" label="状态" :width="colWidth('status', 90)" resizable>
          <template #default="{ row }">{{ paymentStatusLabel(row.status) }}</template>
        </el-table-column>
        <el-table-column column-key="核销" label="核销" :min-width="flexColMinWidth('核销', 180)" resizable>
          <template #default="{ row }">
            <div v-for="a in row.allocations" :key="a.id" class="muted">
              应收#{{ a.receivable_id }} · {{ a.amount }}
            </div>
          </template>
        </el-table-column>
        <el-table-column column-key="actions" label="操作" :width="colWidth('actions', 100)" resizable>
          <template #default="{ row }">
            <el-button v-if="row.status === 'posted'" link type="danger" @click="voidPay(row)">作废</el-button>
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

    <el-dialog v-model="visible" title="登记回款" width="640px">
      <el-form label-width="90px">
        <el-form-item label="客户名">
          <el-input v-model="form.customer_name" />
        </el-form-item>
        <el-form-item label="金额">
          <el-input-number v-model="form.amount" :min="0" :step="1" />
        </el-form-item>
        <el-form-item label="日期">
          <el-date-picker v-model="form.payment_date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="方式">
          <el-select v-model="form.method">
            <el-option label="微信" value="wechat" />
            <el-option label="支付宝" value="alipay" />
            <el-option label="银行" value="bank" />
            <el-option label="现金" value="cash" />
            <el-option label="其它" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="凭证号">
          <el-input v-model="form.voucher_no" />
        </el-form-item>
        <div style="font-weight: 600; margin-bottom: 8px">核销到应收（未收）</div>
        <el-table :data="openAr" border size="small" style="width: 100%" @selection-change="onSel" @header-dragend="onHeaderDragend1">
          <el-table-column type="selection" :width="colWidth1('col', 48)" />
          <el-table-column prop="id" label="应收ID" :width="colWidth1('id', 80)" resizable />
          <el-table-column prop="customer_name" label="客户" :width="colWidth1('customer_name', 100)" resizable />
          <el-table-column prop="balance" label="未收" :width="colWidth1('balance', 90)" resizable />
          <el-table-column column-key="本次核销" label="本次核销" :width="colWidth1('本次核销', 140)" resizable>
            <template #default="{ row }">
              <el-input-number v-model="row.alloc" :min="0" :max="Number(row.balance)" size="small" />
            </template>
          </el-table-column>
        </el-table>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="submit">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const { colWidth, flexColMinWidth, onHeaderDragend } = useTableColWidths('payments-list', tableRef)
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths('payments-detail')
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const openAr = ref<any[]>([])
const selected = ref<any[]>([])
const visible = ref(false)
const form = reactive({
  customer_name: '',
  amount: 0,
  payment_date: new Date().toISOString().slice(0, 10),
  method: 'wechat',
  voucher_no: '',
})

const PAYMENT_STATUS: Record<string, string> = {
  posted: '已入账',
  void: '已作废',
}

const METHOD_LABEL: Record<string, string> = {
  wechat: '微信',
  alipay: '支付宝',
  bank: '银行',
  cash: '现金',
  other: '其它',
}

function paymentStatusLabel(s: string) {
  return PAYMENT_STATUS[s] || s || '—'
}

function methodLabel(s: string) {
  return METHOD_LABEL[s] || s || '—'
}

async function load() {
  const res: any = await http.get('/payments', {
    params: { page: page.value, page_size: pageSize.value },
  })
  const payload = res.data
  rows.value = payload?.items || (Array.isArray(payload) ? payload : [])
  total.value = payload?.total ?? rows.value.length
}

function onPageSizeChange() {
  page.value = 1
  void load()
}

function onSel(v: any[]) {
  selected.value = v
}

async function openCreate() {
  const res: any = await http.get('/receivables', { params: { page: 1, page_size: 200 } })
  const items = res.data?.items || (Array.isArray(res.data) ? res.data : [])
  openAr.value = items
    .filter((r: any) => r.status === 'open' || r.status === 'partial')
    .map((r: any) => ({ ...r, alloc: Number(r.balance) }))
  visible.value = true
}

async function submit() {
  const allocations = (selected.value.length ? selected.value : openAr.value.filter((r) => r.alloc > 0))
    .filter((r) => Number(r.alloc) > 0)
    .map((r) => ({ receivable_id: r.id, amount: r.alloc }))
  const sum = allocations.reduce((s, a) => s + Number(a.amount), 0)
  form.amount = sum
  await http.post('/payments', {
    customer_name: form.customer_name || allocations[0] && openAr.value.find((x) => x.id === allocations[0].receivable_id)?.customer_name,
    amount: form.amount,
    payment_date: form.payment_date,
    method: form.method,
    voucher_no: form.voucher_no || undefined,
    allocations,
  })
  ElMessage.success('回款已登记')
  visible.value = false
  load()
}

async function voidPay(row: any) {
  await http.post(`/payments/${row.id}/void`)
  ElMessage.success('已作废')
  load()
}

onMounted(async () => {
  await load()
  measureTableHeight()
})
</script>
