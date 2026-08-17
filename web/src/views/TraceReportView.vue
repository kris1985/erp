<template>
  <div class="page">
    <div class="page-title">报本工序</div>
    <div v-if="error" class="card-block" style="color: #c00">{{ error }}</div>
    <template v-else>
      <div v-if="unit" class="card-block">
        <div style="font-weight: 600">{{ unit.code }}</div>
        <div class="muted">
          {{ unit.header_no || unit.order_no }} ·
          {{ [unit.color_name, unit.size_value].filter(Boolean).join(' / ') || '—' }} ·
          {{ unit.qty }} 双
        </div>
        <div class="muted" style="margin-top: 6px">
          {{ talkText }}
        </div>
        <div v-if="processLocked" class="muted" style="margin-top: 6px">
          本工序由工位锁定：{{ processName }}
        </div>
      </div>

      <div v-if="!auth.token" class="card-block">
        <p class="muted">请先用员工账号登录后再报工</p>
        <van-button type="primary" block round @click="goLogin">去登录</van-button>
      </div>

      <van-form v-else @submit="onSubmit">
        <van-cell-group inset>
          <van-field v-model="orderNo" label="订单号" readonly />
          <van-field v-model="colorName" label="颜色" placeholder="可选" />
          <van-field v-model="sizeValue" label="尺码" placeholder="可选" />
          <van-field
            :model-value="processName || '请选择工序'"
            :is-link="!processLocked"
            readonly
            label="工序"
            required
            @click="!processLocked && (processPicker = true)"
          />
          <van-field v-model="qty" type="digit" label="数量" required />
          <van-cell v-if="canProxy" center title="组长代报">
            <template #right-icon>
              <van-switch v-model="proxy" size="20" />
            </template>
          </van-cell>
          <van-field
            v-if="canProxy && proxy"
            :model-value="beneficiaryLabel || '请选择工人（可多选）'"
            is-link
            readonly
            label="工资记谁"
            required
            @click="workerPicker = true"
          />
          <div v-if="canProxy && proxy && beneficiaryIds.length > 1" class="muted" style="padding: 0 16px 8px">
            数量将均分给所选 {{ beneficiaryIds.length }} 人
          </div>
          <van-field
            :model-value="reportTypeLabel"
            is-link
            readonly
            label="类型"
            @click="typePicker = true"
          />
        </van-cell-group>
        <div class="big-btn" style="margin: 16px">
          <van-button round block type="primary" native-type="submit" :loading="loading">
            {{ canProxy && proxy ? '代报本工序' : '报本工序' }}
          </van-button>
        </div>
        <div v-if="lastReport" class="card-block report-success">
          <div style="font-weight: 600; color: #389e0d">报工成功</div>
          <div class="muted" style="margin-top: 6px">{{ lastReport.message }}</div>
          <van-button
            v-if="lastReport.print_trace_label && lastReport.trace_code"
            style="margin-top: 10px"
            block
            type="primary"
            plain
            @click="$router.push(`/trace-print/${lastReport.trace_code}`)"
          >
            打印捆标
          </van-button>
        </div>
      </van-form>
    </template>

    <van-popup v-model:show="processPicker" position="bottom" round>
      <van-picker
        :columns="processColumns"
        @confirm="onPickProcess"
        @cancel="processPicker = false"
      />
    </van-popup>
    <van-popup v-model:show="workerPicker" position="bottom" round :style="{ height: '60%', padding: '12px' }">
      <div style="font-weight: 600; margin-bottom: 8px">选择代报工人（可多选）</div>
      <van-checkbox-group v-model="beneficiaryIds">
        <van-cell-group inset>
          <van-cell
            v-for="w in workers.filter((x: any) => x.id !== auth.workerId)"
            :key="w.id"
            clickable
            :title="w.name"
            @click="toggleWorker(w.id)"
          >
            <template #right-icon>
              <van-checkbox :name="w.id" @click.stop />
            </template>
          </van-cell>
        </van-cell-group>
      </van-checkbox-group>
      <p class="muted" style="margin: 12px 0 0; font-size: 12px">多人时数量均分，工资记所选工人</p>
      <van-button type="primary" block round style="margin-top: 16px" @click="workerPicker = false">
        确定
      </van-button>
    </van-popup>
    <van-popup v-model:show="typePicker" position="bottom" round>
      <van-radio-group v-model="reportType">
        <van-cell-group>
          <van-cell
            v-for="t in reportTypes"
            :key="t.value"
            :title="t.label"
            :label="t.hint"
            clickable
            @click="reportType = t.value; typePicker = false"
          >
            <template #right-icon>
              <van-radio :name="t.value" />
            </template>
          </van-cell>
        </van-cell-group>
      </van-radio-group>
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

const unit = ref<any>(null)
const error = ref('')
const orderNo = ref('')
const colorName = ref('')
const sizeValue = ref('')
const processName = ref('')
const qty = ref('')
const loading = ref(false)
const lastReport = ref<any>(null)
const processPicker = ref(false)
const typePicker = ref(false)
const workerPicker = ref(false)
const processLocked = ref(false)
const processes = ref<any[]>([])
const workers = ref<any[]>([])
const proxy = ref(false)
const beneficiaryIds = ref<number[]>([])
const proxyEnabled = ref(true)
const reportType = ref('normal')
const reportTypes = [
  { value: 'normal', label: '正常', hint: '常规计件' },
  { value: 'rework', label: '返修', hint: '返修计件' },
  { value: 'supplement', label: '补数', hint: '补数' },
  { value: 'tail', label: '尾数', hint: '尾数' },
]
const reportTypeLabel = computed(
  () => reportTypes.find((t) => t.value === reportType.value)?.label || '正常',
)
const talkText = computed(() => {
  if (unit.value?.unit_type === 'basket') {
    return '全工序扫此流转卡报个人或组长代报。'
  }
  return '旧扎捆：合帮前扫此码报个人或组长代报。'
})
const processColumns = computed(() =>
  processes.value.map((p) => ({ text: p.process_name || p.name, value: p.process_name || p.name })),
)
const canProxy = computed(() => {
  if (!auth.isLeader || !proxyEnabled.value) return false
  return unit.value?.unit_type === 'basket' || unit.value?.unit_type === 'bundle'
})
const beneficiaryLabel = computed(() =>
  workers.value
    .filter((w) => beneficiaryIds.value.includes(w.id))
    .map((w) => w.name)
    .join('、'),
)

function goLogin() {
  router.push({ path: '/login', query: { redirect: route.fullPath } })
}

function onPickProcess({ selectedOptions }: any) {
  processName.value = selectedOptions[0]?.value || ''
  processPicker.value = false
}

function toggleWorker(id: number) {
  const i = beneficiaryIds.value.indexOf(id)
  if (i >= 0) beneficiaryIds.value = beneficiaryIds.value.filter((x) => x !== id)
  else beneficiaryIds.value = [...beneficiaryIds.value, id]
}

async function load() {
  const code = String(route.query.code || '')
  if (!code) {
    error.value = '缺少捆标码'
    return
  }
  const res = await axios.get(`/api/v1/trace-units/by-code/${encodeURIComponent(code)}`)
  if (!res.data?.ok) {
    error.value = '捆标不存在'
    return
  }
  unit.value = res.data.data
  const st = String(unit.value.status || '')
  if (st && !['open', 'in_process'].includes(st)) {
    error.value = '该主码已作废或结束，不可报工'
    return
  }
  orderNo.value = String(route.query.order_no || unit.value.header_no || unit.value.order_no || '')
  colorName.value = String(route.query.color_name || unit.value.color_name || '')
  sizeValue.value = String(route.query.size_value || unit.value.size_value || '')
  qty.value = String(route.query.qty || unit.value.qty || '')

  // B2h-M1：工位只定工序（query / 本机记住）
  const stationCode =
    String(route.query.station || localStorage.getItem('erp_station_code') || '').trim()
  processLocked.value = false
  if (stationCode) {
    try {
      const sRes = await axios.get(
        `/api/v1/stations/by-code/${encodeURIComponent(stationCode)}`,
      )
      const stn = sRes.data?.data || sRes.data
      if (stn?.process_name) {
        processName.value = stn.process_name
        processLocked.value = true
        localStorage.setItem('erp_station_code', stationCode)
      }
    } catch {
      /* 工位无效则回落手选 */
    }
  }
  if (!processName.value) {
    processName.value = String(route.query.process_name || '')
  }

  const procs = unit.value.order_processes || []
  processes.value = procs
  if (!processName.value && procs.length) {
    const next = procs.find((p: any) => p.status !== 'completed') || procs[0]
    processName.value = next.process_name
  }
  if (auth.isLeader) {
    try {
      const sf: any = await http.get('/shop-floor-settings')
      proxyEnabled.value = sf.data?.stitch_leader_proxy_report !== false
      let list: any[] = []
      try {
        const mine: any = await http.get('/teams/mine')
        const teams = mine.data?.items || []
        list = teams.flatMap((t: any) => t.members || [])
      } catch {
        list = []
      }
      if (!list.length) {
        const wr: any = await http.get('/shop-floor-settings/workers')
        list = Array.isArray(wr.data) ? wr.data : wr.data?.items || []
      }
      workers.value = list
    } catch {
      proxyEnabled.value = true
    }
  }
}

async function onSubmit() {
  if (!auth.workerId || !unit.value) return
  const n = Number(qty.value)
  if (!orderNo.value || !processName.value || !n) {
    showToast('请填写工序和数量')
    return
  }
  if (canProxy.value && proxy.value && !beneficiaryIds.value.length) {
    showToast('代报请指定工人')
    return
  }
  loading.value = true
  lastReport.value = null
  try {
    const res: any = await http.post('/reports', {
      worker_id: auth.workerId,
      order_no: orderNo.value,
      header_id: unit.value.header_id || undefined,
      process_name: processName.value,
      color_name: colorName.value || null,
      size_value: sizeValue.value || null,
      qualified_qty: n,
      source: 'qrcode',
      confirm_over_plan: true,
      report_type: reportType.value,
      trace_unit_id: unit.value.id,
      create_trace_bundle: false,
      proxy: canProxy.value && proxy.value,
      beneficiary_worker_id:
        canProxy.value && proxy.value ? beneficiaryIds.value[0] : undefined,
      beneficiary_worker_ids:
        canProxy.value && proxy.value ? beneficiaryIds.value : undefined,
    })
    lastReport.value = res.data
    showToast('报工成功')
    qty.value = ''
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '报工失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load().catch((e: any) => {
    error.value = e?.response?.data?.detail || '加载失败'
  })
})
</script>

<style scoped>
.report-success {
  border: 1px solid #b7eb8f;
  background: #f6ffed;
}
</style>
