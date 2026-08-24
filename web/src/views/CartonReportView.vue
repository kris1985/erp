<template>
  <div class="h5-shell">
    <div class="page page--solo">
      <h1 class="page-title">扫箱唛报工</h1>

      <div v-if="error" class="card-block" style="color: #c00">{{ error }}</div>

      <template v-else-if="carton">
        <div class="card-block">
          <div style="display: flex; justify-content: space-between; align-items: center">
            <div style="font-weight: 600">{{ carton.code }}</div>
            <span class="muted">共 {{ carton.total_qty }} 双</span>
          </div>
          <div class="muted">{{ carton.header_no || carton.order_no }}</div>
          <div class="muted">
            {{ carton.product_code || '—' }}
            <template v-if="carton.customer_name"> · {{ carton.customer_name }}</template>
          </div>
          <div class="carton-statuses">
            <span :class="['carton-status', carton.reported_work_log_id ? 'is-done' : '']">
              包装报工：{{ carton.reported_work_log_id ? '已完成' : '待完成' }}
            </span>
            <span :class="['carton-status', carton.warehoused_at ? 'is-done' : '']">
              成品入库：{{ carton.warehoused_at ? '已完成' : '待入库' }}
            </span>
            <span :class="['carton-status', carton.shipment_id ? 'is-done' : '']">
              销售出库：{{ carton.shipment_id ? '已完成' : '待出库' }}
            </span>
          </div>
        </div>

        <div v-if="carton.reported_work_log_id" class="card-block" style="background: rgba(255,153,0,0.1)">
          <van-icon name="warning-o" />
          该箱已报工，请勿重复扫
        </div>

        <template v-else>
          <div class="card-block muted" style="font-size: 13px">
            装完一箱扫一下箱唛，系统自动按箱内双数记包装计件（<b>不逐双验箱</b>；验箱由 QC/仓管出货时做）。
          </div>

          <div class="big-btn" style="margin: 16px 16px 24px">
            <van-button round block type="primary" :loading="submitting" @click="onSubmit">
              确认报工 {{ carton.total_qty }} 双
            </van-button>
          </div>
        </template>

        <div v-if="result" class="card-block report-success">
          <div class="report-success__title">{{ resultTitle }}</div>
          <div v-if="result.amount != null" class="report-success__wage">¥{{ Number(result.amount || 0).toFixed(2) }}</div>
          <div v-if="result.process_name" class="muted" style="margin-top: 6px">
            {{ result.process_name }} · {{ result.qualified_qty }} 双 · 单价 ¥{{ Number(result.unit_price || 0).toFixed(3) }}
          </div>
          <div v-if="result.shipment_no" class="muted" style="margin-top: 6px">
            出货单 {{ result.shipment_no }} · {{ result.total_qty }} 双
          </div>
          <div class="muted" style="margin-top: 8px; white-space: pre-wrap">{{ result.message }}</div>
        </div>

        <div v-if="canWarehouse" class="card-block carton-actions">
          <div style="font-weight: 600">仓库操作</div>
          <van-button
            v-if="carton.reported_work_log_id && !carton.warehoused_at"
            round block type="primary" :loading="submitting" @click="onWarehouse"
          >确认本箱入库 {{ carton.total_qty }} 双</van-button>
          <van-button
            v-if="carton.warehoused_at && !carton.shipment_id"
            round block type="danger" :loading="submitting" @click="onShip"
          >验箱并确认出库 {{ carton.total_qty }} 双</van-button>
          <div v-if="carton.shipment_id" class="muted">该箱已出库，禁止重复扫描。</div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

type Carton = {
  id: number
  code: string
  total_qty: number
  order_no?: string | null
  header_no?: string | null
  customer_name?: string | null
  product_code?: string | null
  reported_work_log_id?: number | null
  warehoused_at?: string | null
  shipment_id?: number | null
}

const route = useRoute()
const auth = useAuthStore()
const carton = ref<Carton | null>(null)
const error = ref('')
const submitting = ref(false)
const result = ref<any>(null)
const resultTitle = ref('操作成功')
const canWarehouse = computed(() => {
  const allowed = new Set(['admin', 'manager', 'leader', 'warehouse'])
  return allowed.has(auth.role) || allowed.has(auth.baseRole) || auth.roles.some((x) => allowed.has(x))
})

async function loadCarton() {
  const code = String(route.params.code || '').trim()
  if (!code) {
    error.value = '箱码为空'
    return
  }
  try {
    const res: any = await http.get(`/packing-cartons/by-code/${encodeURIComponent(code)}`)
    carton.value = res.data
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '箱码不存在'
  }
}

async function doSubmit(confirmOverPlan: boolean) {
  if (!carton.value) return
  submitting.value = true
  result.value = null
  try {
    const res: any = await http.post('/carton-reports', {
      carton_code: carton.value.code,
      confirm_over_plan: confirmOverPlan,
    })
    if (res.data?.need_confirm) {
      showConfirmDialog({
        title: '将超计划',
        message: res.data.message || '本次报工将超过计划数，确认继续？',
      })
        .then(() => doSubmit(true))
        .catch(() => {})
      return
    }
    result.value = res.data
    resultTitle.value = '报工成功'
    showToast('报工成功')
    // 刷新箱子状态（已报工）
    carton.value = { ...carton.value, reported_work_log_id: res.data.work_log_id }
  } finally {
    submitting.value = false
  }
}

function onSubmit() {
  doSubmit(false)
}

async function onWarehouse() {
  if (!carton.value) return
  await showConfirmDialog({ title: '确认入库', message: `确认将 ${carton.value.code} 共 ${carton.value.total_qty} 双入成品仓？` })
  submitting.value = true
  try {
    const res: any = await http.post(`/packing-cartons/${carton.value.id}/warehouse`, {})
    carton.value = { ...carton.value, warehoused_at: res.data.warehoused_at }
    result.value = res.data
    resultTitle.value = '入库成功'
    showToast('入库成功')
  } finally {
    submitting.value = false
  }
}

async function onShip() {
  if (!carton.value) return
  await showConfirmDialog({ title: '确认出库', message: `已核对本箱箱唛与实物？确认后将扣减成品库存并生成出货单。` })
  submitting.value = true
  try {
    const res: any = await http.post(`/packing-cartons/${carton.value.id}/ship`, {})
    carton.value = { ...carton.value, shipment_id: res.data.shipment_id }
    result.value = res.data
    resultTitle.value = '出库成功'
    showToast('出库成功')
  } finally {
    submitting.value = false
  }
}

onMounted(loadCarton)
</script>

<style scoped>
.report-success {
  background: rgba(52, 199, 89, 0.1);
  box-shadow: none;
}
.report-success__title {
  font-weight: 600;
  color: #248a3d;
}
.report-success__wage {
  margin-top: 8px;
  font-family: var(--ws-font-num);
  font-size: 32px;
  font-weight: 700;
  color: var(--ws-primary);
  letter-spacing: -0.03em;
}
.carton-actions {
  display: grid;
  gap: 12px;
}
.carton-statuses {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.carton-status {
  padding: 4px 9px;
  border-radius: 999px;
  background: rgba(142, 142, 147, 0.12);
  color: var(--ws-muted);
  font-size: 12px;
}
.carton-status.is-done {
  background: rgba(52, 199, 89, 0.12);
  color: #248a3d;
}
</style>
