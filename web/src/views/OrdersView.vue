<template>
  <div class="page">
    <div class="h5-filter">
      <van-icon name="search" class="h5-filter__icon" />
      <input
        v-model="keyword"
        class="h5-filter__input"
        type="text"
        inputmode="search"
        enterkeyhint="search"
        placeholder="订单号 / 客户 / 货号"
      />
      <button
        v-if="keyword"
        type="button"
        class="h5-filter__clear"
        aria-label="清除"
        @click="keyword = ''"
      >
        <van-icon name="cross" />
      </button>
    </div>
    <van-button type="primary" block round style="margin-bottom: 12px" @click="openCreate">新建订单</van-button>

    <div v-if="teamEmpty" class="h5-empty">
      <div class="h5-empty__mark">◎</div>
      尚未配置班组，请联系管理员
    </div>
    <div v-else-if="!filteredItems.length" class="h5-empty">
      <div class="h5-empty__mark">◎</div>
      {{ keyword.trim() ? '无匹配订单' : '暂无订单' }}
    </div>

    <div v-for="o in filteredItems" :key="o.id" class="h5-list-card order-card">
      <div class="h5-list-card__head" @click="toggle(o)">
        <div class="h5-list-card__title">{{ o.order_no }}</div>
        <span class="h5-pill" :class="orderStatusPill(o.status)">{{ orderStatusLabel(o.status) }}</span>
      </div>
      <div class="order-card__meta">{{ o.customer_name }} · {{ o.product_code || '—' }} · {{ o.total_qty }} 双</div>

      <div v-if="o.processes?.length" class="process-rings">
        <ProgressRing
          v-for="p in o.processes"
          :key="p.id"
          :completed="p.completed_qty"
          :plan="p.plan_qty"
          :label="p.process_name"
          :size="52"
        />
      </div>

      <div v-if="expanded === o.id" style="margin-top: 10px">
        <div style="font-weight: 600; margin-bottom: 4px">色码明细</div>
        <div v-for="it in o.items || []" :key="it.id" class="muted">
          {{ colorName(it.color_id) }} {{ sizeName(it.size_id) }}码：{{ it.completed_qty }}/{{ it.qty }}
        </div>
        <div style="font-weight: 600; margin: 10px 0 4px">派工</div>
        <div
          v-for="p in o.processes"
          :key="`a-${p.id}`"
          class="dispatch-row"
        >
          <div class="dispatch-row__info">
            <div class="dispatch-row__name">{{ p.process_name }}</div>
            <div class="dispatch-row__workers muted">
              <template v-if="p.assigned_worker_names?.length">{{ p.assigned_worker_names.join('、') }}</template>
              <template v-else>未派工</template>
            </div>
          </div>
          <van-button
            v-if="canDispatch"
            class="dispatch-row__btn"
            type="primary"
            plain
            round
            @click.stop="openDispatchProcess(o, p)"
          >
            派工
          </van-button>
        </div>
      </div>
      <van-button size="small" plain type="primary" round block style="margin-top: 10px" @click.stop="toggle(o)">
        {{ expanded === o.id ? '收起' : '查看明细' }}
      </van-button>
    </div>

    <van-popup v-model:show="dispatchShow" position="bottom" round :style="{ height: '75%', padding: '16px' }">
      <div style="font-weight: 600; margin-bottom: 4px">
        派工 · {{ dispatchOrder?.order_no }} · {{ dispatchProcess?.process_name }}
      </div>
      <p class="muted" style="margin: 0 0 12px; font-size: 12px">
        计划 {{ dispatchProcess?.plan_qty }}
        <template v-if="dispatchProcess && livePool(dispatchProcess) !== null">
          · 池 {{ livePool(dispatchProcess) }}
        </template>
        · 配额空=不限
      </p>
      <template v-if="dispatchProcess">
        <van-field
          :model-value="workerLabels(dispatchProcess.id)"
          is-link
          readonly
          label="工人"
          placeholder="选择工人"
          @click="openWorkerPicker(dispatchProcess.id)"
        />
        <div
          v-for="wid in dispatchMap[dispatchProcess.id] || []"
          :key="`${dispatchProcess.id}-${wid}`"
          style="display: flex; align-items: center; gap: 8px; margin: 8px 0; flex-wrap: wrap"
        >
          <span style="width: 64px">{{ workerName(wid) }}</span>
          <van-field
            v-model="dispatchQuota[quotaKey(dispatchProcess.id, wid)]"
            type="digit"
            label="配额"
            placeholder="不限"
            style="flex: 1; padding: 0"
          />
          <van-field
            v-if="dispatchProcess.process_type === 'group'"
            v-model="dispatchWeight[quotaKey(dispatchProcess.id, wid)]"
            type="digit"
            label="权重"
            placeholder="1"
            style="width: 110px; padding: 0"
          />
          <span class="muted" style="font-size: 12px">已报 {{ reportedOf(dispatchProcess, wid) }}</span>
          <van-button size="mini" plain type="warning" @click="reclaimToPool(dispatchProcess, wid)">
            收回剩余
          </van-button>
        </div>
        <p v-if="dispatchProcess.process_type === 'group'" class="muted" style="margin: 4px 0 0; font-size: 12px">
          集体权重默认 1（均分）；如 2 与 1 则按比例拆账
        </p>
      </template>
      <van-button type="primary" block round :loading="dispatchSaving" style="margin-top: 16px" @click="saveDispatch">
        保存派工
      </van-button>
    </van-popup>

    <van-popup v-model:show="workerPickerShow" position="bottom" round :style="{ height: '60%', padding: '12px' }">
      <div style="font-weight: 600; margin-bottom: 8px">选择工人</div>
      <van-checkbox-group v-model="pickerSelected">
        <van-cell-group inset>
          <van-cell
            v-for="w in workers"
            :key="w.id"
            clickable
            :title="w.name"
            @click="togglePickerWorker(w.id)"
          >
            <template #right-icon>
              <van-checkbox :name="w.id" @click.stop />
            </template>
          </van-cell>
        </van-cell-group>
      </van-checkbox-group>
      <van-button type="primary" block round style="margin-top: 16px" @click="confirmWorkerPicker">确定</van-button>
    </van-popup>

    <van-popup v-model:show="show" position="bottom" round :style="{ height: '70%', padding: '16px' }">
      <van-field v-model="form.order_no" label="订单号" placeholder="可空自动生成" />
      <van-field
        v-model="form.customer_label"
        is-link
        readonly
        label="客户"
        placeholder="选择或手填"
        @click="showCustomers = true"
      />
      <van-field
        v-if="!form.customer_id"
        v-model="form.customer_name"
        label="客户名"
        placeholder="手填客户名"
      />
      <van-field
        is-link
        readonly
        label="产品"
        :model-value="productLabel"
        @click="showProducts = true"
      />
      <van-field
        is-link
        readonly
        label="尺码"
        :model-value="sizeLabel"
        @click="showSizes = true"
      />
      <van-field
        is-link
        readonly
        label="颜色"
        :model-value="colorLabel"
        @click="showColors = true"
      />
      <van-field v-model="form.qty" type="digit" label="数量" />
      <van-button type="primary" block round style="margin-top: 16px" @click="create">创建并拆工序</van-button>
    </van-popup>

    <van-action-sheet v-model:show="showProducts" :actions="productActions" @select="onPickProduct" />
    <van-action-sheet v-model:show="showCustomers" :actions="customerActions" @select="onPickCustomer" />
    <van-action-sheet v-model:show="showSizes" :actions="sizeActions" @select="onPickSize" />
    <van-action-sheet v-model:show="showColors" :actions="colorActions" @select="onPickColor" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { showToast } from 'vant'
import http from '@/api/http'
import ProgressRing from '@/components/ProgressRing.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canDispatch = computed(
  () => auth.actor !== 'worker' && auth.hasPermission('btn.orders.dispatch'),
)

const items = ref<any[]>([])
const keyword = ref('')
const teamEmpty = ref(false)

const filteredItems = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return items.value
  return items.value.filter((o) => {
    const hay = [o.order_no, o.customer_name, o.product_code, o.style_code]
      .map((x) => String(x || '').toLowerCase())
      .join(' ')
    return hay.includes(q)
  })
})

const products = ref<any[]>([])
const customers = ref<any[]>([])
const sizes = ref<any[]>([])
const colors = ref<any[]>([])
const workers = ref<any[]>([])
const expanded = ref<number | null>(null)
const show = ref(false)
const showProducts = ref(false)
const showCustomers = ref(false)
const showSizes = ref(false)
const showColors = ref(false)

const dispatchShow = ref(false)
const dispatchSaving = ref(false)
const dispatchOrder = ref<any>(null)
const dispatchProcess = ref<any>(null)
const dispatchMap = reactive<Record<number, number[]>>({})
const dispatchQuota = reactive<Record<string, string>>({})
const dispatchWeight = reactive<Record<string, string>>({})
const workerPickerShow = ref(false)
const pickerProcessId = ref<number | null>(null)
const pickerSelected = ref<number[]>([])

const form = reactive({
  order_no: '',
  customer_id: 0 as number | null,
  customer_name: '',
  customer_label: '',
  own_product_id: 0,
  size_id: 0,
  color_id: 0,
  qty: '100',
})

const productLabel = computed(
  () => products.value.find((p) => p.id === form.own_product_id)?.product_code || '请选择',
)
const sizeLabel = computed(() => sizes.value.find((s) => s.id === form.size_id)?.size_value || '请选择')
const colorLabel = computed(() => colors.value.find((c) => c.id === form.color_id)?.name || '请选择')
const productActions = computed(() => products.value.map((p) => ({ name: p.product_code, id: p.id })))
const customerActions = computed(() => [
  { name: '手填客户名', id: 0 },
  ...customers.value.map((c) => ({ name: c.short_name || c.name, id: c.id })),
])
const sizeActions = computed(() => sizes.value.map((s) => ({ name: s.size_value + '码', id: s.id })))
const colorActions = computed(() => colors.value.map((c) => ({ name: c.name, id: c.id })))

const ORDER_STATUS_LABEL: Record<string, string> = {
  draft: '草稿',
  confirmed: '已确认',
  in_progress: '生产中',
  completed: '已完成',
  cancelled: '已取消',
}

function orderStatusLabel(status: string) {
  return ORDER_STATUS_LABEL[status] || status
}

function orderStatusPill(status: string) {
  return (
    ({
      draft: 'h5-pill--mute',
      confirmed: 'h5-pill--warn',
      in_progress: '',
      completed: 'h5-pill--ok',
      cancelled: 'h5-pill--danger',
    } as Record<string, string>)[status] || 'h5-pill--mute'
  )
}
function colorName(id: number | null | undefined) {
  if (!id) return '—'
  return colors.value.find((c) => c.id === id)?.name || String(id)
}

function sizeName(id: number | null | undefined) {
  if (!id) return '—'
  return sizes.value.find((s) => s.id === id)?.size_value || String(id)
}

async function load() {
  const [o, p, sz, c, cust]: any[] = await Promise.all([
    http.get('/orders', { params: { page_size: 200 } }),
    http.get('/own-products', { params: { page_size: 200 } }),
    http.get('/sizes'),
    http.get('/colors'),
    http.get('/partners', { params: { role: 'customer_brand' } }),
  ])
  items.value = o.data.items
  teamEmpty.value = !!o.data.team_empty
  products.value = p.data.items
  sizes.value = sz.data.items
  colors.value = c.data.items
  customers.value = cust.data.items
  if (canDispatch.value) {
    try {
      const w: any = await http.get('/workers')
      workers.value = w.data.items || []
    } catch {
      workers.value = []
    }
  }
}

function workerName(id: number) {
  return workers.value.find((w) => w.id === id)?.name || String(id)
}

function quotaKey(processId: number, workerId: number) {
  return `${processId}:${workerId}`
}

function reportedOf(p: any, workerId: number) {
  const a = (p.assignments || []).find(
    (x: any) => x.worker_id === workerId && !x.color_id && !x.size_id && !x.trace_unit_id,
  )
  return a ? Number(a.reported_qty || 0) : 0
}

function livePool(p: any): number | null {
  const ids = dispatchMap[p.id] || []
  if (!ids.length) return Number(p.plan_qty)
  const quotas = ids.map((wid) => dispatchQuota[quotaKey(p.id, wid)])
  if (quotas.some((q) => q === '' || q === undefined || q === null)) return null
  const allocated = quotas.reduce((s, q) => s + Number(q), 0)
  return Number(p.plan_qty) - allocated
}

function workerLabels(processId: number) {
  const ids = dispatchMap[processId] || []
  if (!ids.length) return ''
  return ids.map((id) => workerName(id)).join('、')
}

function openDispatchProcess(o: any, p: any) {
  dispatchOrder.value = JSON.parse(JSON.stringify(o))
  const process =
    (dispatchOrder.value.processes || []).find((x: any) => x.id === p.id) || JSON.parse(JSON.stringify(p))
  for (const key of Object.keys(dispatchMap)) delete dispatchMap[Number(key)]
  for (const key of Object.keys(dispatchQuota)) delete dispatchQuota[key]
  for (const key of Object.keys(dispatchWeight)) delete dispatchWeight[key]
  const processAssigns = (process.assignments || []).filter(
    (a: any) => !a.color_id && !a.size_id && !a.trace_unit_id,
  )
  const ids = processAssigns.length
    ? processAssigns.map((a: any) => a.worker_id)
    : [...(process.assigned_worker_ids || [])]
  dispatchMap[process.id] = [...new Set(ids)]
  for (const a of processAssigns) {
    const qk = quotaKey(process.id, a.worker_id)
    dispatchQuota[qk] = a.quota_qty === null || a.quota_qty === undefined ? '' : String(a.quota_qty)
    dispatchWeight[qk] = a.share_weight && a.share_weight > 0 ? String(a.share_weight) : '1'
  }
  for (const wid of dispatchMap[process.id]) {
    const qk = quotaKey(process.id, wid)
    if (!dispatchWeight[qk]) dispatchWeight[qk] = '1'
  }
  dispatchProcess.value = process
  dispatchShow.value = true
}

function openWorkerPicker(processId: number) {
  pickerProcessId.value = processId
  pickerSelected.value = [...(dispatchMap[processId] || [])]
  workerPickerShow.value = true
}

function togglePickerWorker(id: number) {
  const set = new Set(pickerSelected.value)
  if (set.has(id)) set.delete(id)
  else set.add(id)
  pickerSelected.value = [...set]
}

function confirmWorkerPicker() {
  const pid = pickerProcessId.value
  if (pid == null) return
  dispatchMap[pid] = [...pickerSelected.value]
  for (const key of Object.keys(dispatchQuota)) {
    if (key.startsWith(`${pid}:`)) {
      const wid = Number(key.split(':')[1])
      if (!dispatchMap[pid].includes(wid)) {
        delete dispatchQuota[key]
        delete dispatchWeight[key]
      }
    }
  }
  for (const wid of dispatchMap[pid]) {
    const qk = quotaKey(pid, wid)
    if (!dispatchWeight[qk]) dispatchWeight[qk] = '1'
  }
  workerPickerShow.value = false
}

function reclaimToPool(p: any, workerId: number) {
  const reported = reportedOf(p, workerId)
  dispatchQuota[quotaKey(p.id, workerId)] = String(reported)
  showToast(`${workerName(workerId)} 已锁到已报 ${reported}`)
}

async function saveDispatch() {
  if (!dispatchOrder.value || !dispatchProcess.value) return
  const p = dispatchProcess.value
  const pool = livePool(p)
  if (pool !== null && pool < 0) {
    showToast('配额超过计划')
    return
  }
  dispatchSaving.value = true
  try {
    const ids = dispatchMap[p.id] || []
    const isGroup = p.process_type === 'group'
    await http.patch(`/orders/${dispatchOrder.value.id}/processes/${p.id}`, {
      assignments: ids.map((wid) => {
        const qk = quotaKey(p.id, wid)
        const raw = dispatchQuota[qk]
        const q = raw === '' || raw === undefined || raw === null ? null : Number(raw)
        const row: any = { worker_id: wid, quota_qty: q === null || Number.isNaN(q) ? null : q }
        if (isGroup) {
          const w = Number(dispatchWeight[qk] || 1)
          row.share_weight = !w || Number.isNaN(w) || w <= 0 ? 1 : w
        }
        return row
      }),
    })
    showToast(`${p.process_name}已保存`)
    dispatchShow.value = false
    await load()
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '保存失败')
  } finally {
    dispatchSaving.value = false
  }
}

function toggle(o: any) {
  expanded.value = expanded.value === o.id ? null : o.id
}

function openCreate() {
  form.order_no = ''
  form.customer_id = customers.value[0]?.id || null
  form.customer_name = ''
  form.customer_label = customers.value[0]
    ? customers.value[0].short_name || customers.value[0].name
    : '手填客户名'
  form.own_product_id = products.value[0]?.id || 0
  form.size_id = sizes.value[0]?.id || 0
  form.color_id = colors.value[0]?.id || 0
  form.qty = '100'
  show.value = true
}

function onPickProduct(a: any) {
  form.own_product_id = a.id
  showProducts.value = false
}
function onPickCustomer(a: any) {
  if (!a.id) {
    form.customer_id = null
    form.customer_label = '手填客户名'
    form.customer_name = ''
  } else {
    form.customer_id = a.id
    form.customer_label = a.name
    form.customer_name = a.name
  }
  showCustomers.value = false
}
function onPickSize(a: any) {
  form.size_id = a.id
  showSizes.value = false
}
function onPickColor(a: any) {
  form.color_id = a.id
  showColors.value = false
}

async function create() {
  const name = form.customer_name || form.customer_label
  if ((!form.customer_id && !form.customer_name) || !form.own_product_id || !form.size_id || !form.qty) {
    showToast('请填写完整')
    return
  }
  await http.post('/orders', {
    order_no: form.order_no || undefined,
    customer_id: form.customer_id || null,
    customer_name: name === '手填客户名' ? form.customer_name : name,
    own_product_id: form.own_product_id,
    items: [{ color_id: form.color_id || null, size_id: form.size_id, qty: Number(form.qty) }],
  })
  showToast('已创建')
  show.value = false
  await load()
}

onMounted(async () => {
  if (auth.actor !== 'worker') {
    await auth.refreshPermissions()
  }
  await load()
})
</script>

<style scoped>
.order-card__meta {
  font-size: 14px;
  color: var(--ws-ink-secondary, #3a3a3c);
  margin-top: 2px;
}

.process-rings {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 12px;
  justify-content: flex-start;
}

.dispatch-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--ws-line);
}

.dispatch-row:last-child {
  border-bottom: none;
}

.dispatch-row__info {
  flex: 1;
  min-width: 0;
}

.dispatch-row__name {
  font-size: 15px;
  font-weight: 600;
  color: var(--ws-ink);
}

.dispatch-row__workers {
  margin-top: 2px;
  font-size: 13px;
}

.dispatch-row__btn {
  flex-shrink: 0;
  height: 36px;
  min-width: 72px;
  padding: 0 16px;
  font-size: 15px;
  font-weight: 600;
}
</style>
