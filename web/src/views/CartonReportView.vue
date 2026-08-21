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
          <div class="report-success__title">报工成功</div>
          <div class="report-success__wage">¥{{ Number(result.amount || 0).toFixed(2) }}</div>
          <div class="muted" style="margin-top: 6px">
            {{ result.process_name }} · {{ result.qualified_qty }} 双 · 单价 ¥{{ Number(result.unit_price || 0).toFixed(3) }}
          </div>
          <div class="muted" style="margin-top: 8px; white-space: pre-wrap">{{ result.message }}</div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import http from '@/api/http'

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
}

const route = useRoute()
const carton = ref<Carton | null>(null)
const error = ref('')
const submitting = ref(false)
const result = ref<any>(null)

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
