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
      <el-table ref="tableRef" :data="rows" stripe border style="width: 100%" :max-height="tableMaxHeight" @header-dragend="onHeaderDragend">
        <el-table-column prop="shipment_no" label="出货单号" :width="colWidth('shipment_no', 130)" resizable />
        <el-table-column prop="order_no" label="订单" :width="colWidth('order_no', 110)" resizable />
        <el-table-column prop="customer_name" label="客户" :width="colWidth('customer_name', 120)" resizable />
        <el-table-column prop="ship_date" label="出货日" :width="colWidth('ship_date', 110)" resizable />
        <el-table-column prop="total_qty" label="数量" :width="colWidth('total_qty', 80)" resizable />
        <el-table-column prop="amount" label="金额" :width="colWidth('amount', 100)" resizable />
        <el-table-column column-key="status" label="状态" :width="colWidth('status', 90)" resizable>
          <template #default="{ row }">{{ shipmentStatusLabel(row.status) }}</template>
        </el-table-column>
        <el-table-column prop="tracking_no" label="运单" :min-width="flexColMinWidth('tracking_no', 120)" resizable />
        <el-table-column column-key="actions" label="操作" :width="colWidth('actions', 160)" resizable>
          <template #default="{ row }">
            <el-button v-if="row.status === 'draft'" link type="primary" @click="confirm(row)">确认出货</el-button>
            <el-button v-if="row.status === 'shipped'" link type="danger" @click="voidSh(row)">作废</el-button>
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

    <el-dialog v-model="createVisible" title="新建出货" width="640px">
      <el-form label-width="90px">
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
        <el-table :data="form.lines" border size="small" style="width: 100%" @header-dragend="onHeaderDragend1">
          <el-table-column column-key="color_size" label="色码" :width="colWidth1('color_size', 200)" resizable>
            <template #default="{ row }">#{{ row.order_item_id }} · 计划{{ row.plan_qty }} · 已出{{ row.shipped_qty }}</template>
          </el-table-column>
          <el-table-column column-key="ship_qty" label="本次出货" :width="colWidth1('ship_qty', 140)" resizable>
            <template #default="{ row }">
              <el-input-number v-model="row.qty" :min="0" :max="row.backlog_qty" size="small" />
            </template>
          </el-table-column>
        </el-table>
        <el-form-item label="物流" style="margin-top: 12px">
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
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, flexColMinWidth, onHeaderDragend } = useTableColWidths('shipments-list', tableRef)
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths('shipments-lines')
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const orders = ref<any[]>([])
const createVisible = ref(false)
const delivery = ref<any>(null)

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
  return n.toFixed(2)
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
  createVisible.value = true
}

async function loadDelivery() {
  if (!form.order_id) return
  const res: any = await http.get(`/orders/${form.order_id}/delivery`)
  delivery.value = res.data
  form.lines = (res.data?.items || []).map((it: any) => ({
    order_item_id: it.order_item_id,
    plan_qty: it.plan_qty,
    shipped_qty: it.shipped_qty,
    backlog_qty: it.backlog_qty,
    qty: it.backlog_qty,
  }))
}

async function create(confirm: boolean) {
  await http.post('/shipments', {
    order_id: form.order_id,
    lines: form.lines.filter((l: any) => l.qty > 0).map((l: any) => ({
      order_item_id: l.order_item_id,
      qty: l.qty,
    })),
    logistics_company: form.logistics_company || undefined,
    tracking_no: form.tracking_no || undefined,
    confirm,
  })
  ElMessage.success(confirm ? '已出货并生成应收' : '草稿已保存')
  createVisible.value = false
  load()
}

async function confirm(row: any) {
  await http.post(`/shipments/${row.id}/confirm`)
  ElMessage.success('已确认出货')
  load()
}

async function voidSh(row: any) {
  await http.post(`/shipments/${row.id}/void`)
  ElMessage.success('已作废')
  load()
}

onMounted(async () => {
  await load()
  measureTableHeight()
})
</script>
