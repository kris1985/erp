<template>
  <div class="page">
    <div class="page-title">针车分活</div>
    <div v-if="error" class="card-block" style="color: #c00">{{ error }}</div>
    <template v-else-if="board">
      <div class="card-block">
        <div style="font-weight: 700; font-size: 17px">{{ board.basket?.code }}</div>
        <div class="muted" style="margin-top: 4px">
          生产流转卡 · {{ board.basket?.qty }} 双 ·
          {{ [board.basket?.color_name, board.basket?.size_value].filter(Boolean).join(' / ') || '—' }}
        </div>
        <div class="muted">生产单 {{ board.basket?.header_no || board.basket?.order_no || '—' }} · 款 {{ board.basket?.product_code }}</div>
        <div class="muted">
          收料
          {{
            board.basket?.received_at
              ? formatTime(board.basket.received_at)
              : '未收（打开本页可自动收料）'
          }}
        </div>
      </div>

      <div class="card-block">
        <div style="font-weight: 600; margin-bottom: 8px">针车工序</div>
        <van-field
          :model-value="processLabel"
          is-link
          readonly
          label="工序"
          placeholder="选择针车工序"
          @click="processPicker = true"
        />
      </div>

      <div class="card-block">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px">
          <div style="font-weight: 600">派工到筐</div>
          <van-button size="mini" type="primary" :loading="saving" :disabled="!processId" @click="saveAssign">
            保存派工
          </van-button>
        </div>
        <p class="muted" style="margin-bottom: 8px">
          把整筐（{{ board.basket?.qty || 0 }} 双）派给工人；可多人分拆一筐。报工扫流转卡即扣对应配额。
        </p>
        <div v-for="(row, idx) in rows" :key="idx" class="bundle-row">
          <van-field
            :model-value="workerName(row.worker_id)"
            is-link
            readonly
            label="工人"
            placeholder="选择工人"
            @click="openWorkerPicker(idx)"
          />
          <div class="quota-line">
            <span class="muted">配额</span>
            <van-field
              v-model="row.quota_qty"
              type="digit"
              placeholder="自动均分"
              style="flex: 1"
            />
          </div>
          <van-button
            plain
            size="mini"
            type="danger"
            style="margin-top: 6px"
            @click="rows.splice(idx, 1)"
          >
            移除
          </van-button>
        </div>
        <van-button
          plain
          round
          block
          size="small"
          style="margin-top: 10px"
          :disabled="!processId"
          @click="addWorkerRow"
        >
          + 添加工人
        </van-button>
      </div>

      <div class="card-block" style="display: flex; gap: 8px">
        <van-button plain round block style="flex: 1" @click="$router.back()">返回</van-button>
        <van-button plain round block style="flex: 1" @click="reload">刷新</van-button>
      </div>
    </template>

    <van-popup v-model:show="processPicker" position="bottom" round>
      <van-picker
        :columns="processColumns"
        @confirm="onProcessConfirm"
        @cancel="processPicker = false"
      />
    </van-popup>
    <van-popup v-model:show="workerPicker" position="bottom" round>
      <van-picker
        :columns="workerColumns"
        @confirm="onWorkerConfirm"
        @cancel="workerPicker = false"
      />
    </van-popup>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import axios from 'axios'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const error = ref('')
const board = ref<any>(null)
const basketId = ref<number | null>(null)
const orderId = ref<number | null>(null)
const headerId = ref<number | null>(null)
const processId = ref<number | null>(null)
const orderProcesses = ref<any[]>([])
const workers = ref<any[]>([])
const rows = ref<any[]>([])
const saving = ref(false)
const processPicker = ref(false)
const workerPicker = ref(false)
const editingIdx = ref<number | null>(null)

const processLabel = computed(() => {
  const p = orderProcesses.value.find((x) => x.id === processId.value)
  return p?.process_name || ''
})
const processColumns = computed(() =>
  orderProcesses.value.map((p) => ({ text: p.process_name, value: p.id })),
)
const workerColumns = computed(() =>
  workers.value.map((w) => ({ text: w.name, value: w.id })),
)

function workerName(id: number | null | undefined) {
  if (!id) return ''
  return workers.value.find((w) => w.id === id)?.name || ''
}

function formatTime(v?: string | null) {
  if (!v) return ''
  return String(v).replace('T', ' ').slice(0, 19)
}

function openWorkerPicker(idx: number) {
  editingIdx.value = idx
  workerPicker.value = true
}

function onProcessConfirm({ selectedOptions }: any) {
  processId.value = selectedOptions?.[0]?.value ?? null
  processPicker.value = false
  void reload()
}

function onWorkerConfirm({ selectedOptions }: any) {
  const wid = selectedOptions?.[0]?.value ?? null
  if (editingIdx.value != null && wid != null) {
    rows.value[editingIdx.value].worker_id = wid
  }
  workerPicker.value = false
}

function addWorkerRow() {
  rows.value.push({ worker_id: null, quota_qty: '' as any })
}

async function ensureLogin() {
  if (!auth.token) {
    router.push({ path: '/login', query: { redirect: route.fullPath } })
    return false
  }
  return true
}

async function loadBasketByCode() {
  const code = String(route.params.code || '')
  const res = await axios.get(`/api/v1/trace-units/by-code/${encodeURIComponent(code)}`)
  if (!res.data?.ok) {
    error.value = '流转卡不存在'
    return null
  }
  const unit = res.data.data
  if (unit.unit_type !== 'basket') {
    error.value = '请扫生产流转卡（筐）打开分活看板'
    return null
  }
  basketId.value = unit.id
  orderId.value = unit.order_id
  headerId.value = unit.header_id || null
  orderProcesses.value = (unit.order_processes || [])
    .filter((p: any) => p.process_type !== 'group')
    .map((p: any, idx: number) => ({
      id: p.order_process_id || p.id || idx,
      process_id: p.process_id,
      process_name: p.process_name,
      process_type: p.process_type,
    }))
  return unit
}

async function loadOrderProcesses() {
  if (orderProcesses.value.length) {
    if (!processId.value) processId.value = orderProcesses.value[0].id
    return
  }
  if (headerId.value) {
    const res: any = await http.get(`/executions/headers/${headerId.value}/processes`)
    const procs = res.data?.items || []
    orderProcesses.value = procs
      .filter((p: any) => p.process_type !== 'group')
      .map((p: any) => ({
        id: p.id,
        process_id: p.process_id,
        process_name: p.process_name,
        process_type: p.process_type,
      }))
  } else if (orderId.value) {
    const res: any = await http.get(`/orders/${orderId.value}`)
    const procs = res.data?.processes || []
    orderProcesses.value = procs
      .filter((p: any) => p.process_type !== 'group')
      .map((p: any) => ({
        id: p.id,
        process_id: p.process_id,
        process_name: p.process_name,
        process_type: p.process_type,
      }))
  }
  if (!processId.value && orderProcesses.value.length) {
    processId.value = orderProcesses.value[0].id
  }
}

async function loadWorkers() {
  try {
    if (auth.isLeader) {
      const mine: any = await http.get('/teams/mine')
      const teamWorkers = (mine.data?.items || []).flatMap((t: any) => t.members || [])
      if (teamWorkers.length) {
        workers.value = teamWorkers
        return
      }
      const res: any = await http.get('/shop-floor-settings/workers')
      workers.value = Array.isArray(res.data) ? res.data : res.data?.items || []
      return
    }
    const res: any = await http.get('/workers', { params: { page_size: 200, is_active: true } })
    workers.value = res.data?.items || []
  } catch {
    workers.value = []
  }
}

async function reload() {
  if (!(await ensureLogin()) || !basketId.value) return
  error.value = ''
  try {
    const res: any = await http.get(`/trace-units/${basketId.value}/stitch-board`, {
      params: processId.value ? { process_id: processId.value } : undefined,
    })
    board.value = res.data
    rows.value = (res.data?.assignments || []).map((a: any) => ({
      worker_id: a.worker_id || null,
      quota_qty: a.quota_qty ?? ('' as any),
    }))
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '加载分活看板失败'
  }
}

async function saveAssign() {
  if (!processId.value || !basketId.value) {
    showToast('请先选择工序')
    return
  }
  const items = rows.value
    .filter((r) => r.worker_id)
    .map((r) => ({
      worker_id: r.worker_id,
      quota_qty:
        r.quota_qty !== '' && Number(r.quota_qty) > 0 ? Number(r.quota_qty) : null,
    }))
  if (!items.length) {
    showToast('请至少为一只筐选择工人')
    return
  }
  saving.value = true
  try {
    const endpoint =
      auth.isWorker && auth.isLeader
        ? `/trace-units/${basketId.value}/assign-basket/field`
        : `/trace-units/${basketId.value}/assign-basket`
    await http.post(endpoint, {
      process_id: processId.value,
      items,
    })
    showToast('已保存派工')
    await reload()
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  if (!(await ensureLogin())) return
  const unit = await loadBasketByCode()
  if (!unit) return
  await loadOrderProcesses()
  await loadWorkers()
  await reload()
})
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 12px 12px 24px;
  background: #f6f7f9;
}
.page-title {
  font-size: 18px;
  font-weight: 700;
  margin: 4px 4px 12px;
}
.card-block {
  background: #fff;
  border-radius: 12px;
  padding: 14px;
  margin-bottom: 12px;
}
.muted {
  color: #888;
  font-size: 13px;
  line-height: 1.5;
}
.bundle-row {
  border-top: 1px solid #f0f0f0;
  padding-top: 8px;
  margin-top: 8px;
}
.quota-line {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
}
</style>
