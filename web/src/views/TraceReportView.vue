<template>
  <div class="page">
    <div class="page-title">本捆报工</div>
    <div v-if="error" class="card-block" style="color: #c00">{{ error }}</div>
    <template v-else>
      <div v-if="unit" class="card-block">
        <div style="font-weight: 600">{{ unit.code }}</div>
        <div class="muted">
          订单 {{ unit.order_no }} ·
          {{ [unit.color_name, unit.size_value].filter(Boolean).join(' / ') || '—' }} ·
          {{ unit.qty }} 双
        </div>
      </div>

      <div v-if="!auth.token || auth.actor !== 'worker'" class="card-block">
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
            is-link
            readonly
            label="工序"
            required
            @click="processPicker = true"
          />
          <van-field v-model="qty" type="digit" label="数量" required />
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
            提交报工
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
const processes = ref<any[]>([])
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
const processColumns = computed(() =>
  processes.value.map((p) => ({ text: p.process_name || p.name, value: p.process_name || p.name })),
)

function goLogin() {
  router.push({ path: '/login', query: { redirect: route.fullPath } })
}

function onPickProcess({ selectedOptions }: any) {
  processName.value = selectedOptions[0]?.value || ''
  processPicker.value = false
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
  orderNo.value = String(route.query.order_no || unit.value.order_no || '')
  colorName.value = String(route.query.color_name || unit.value.color_name || '')
  sizeValue.value = String(route.query.size_value || unit.value.size_value || '')
  qty.value = String(route.query.qty || unit.value.qty || '')
  processName.value = String(route.query.process_name || '')

  const procs = unit.value.order_processes || []
  processes.value = procs
  if (!processName.value && procs.length) {
    const next = procs.find((p: any) => p.status !== 'completed') || procs[0]
    processName.value = next.process_name
  }
}

async function onSubmit() {
  if (!auth.workerId || !unit.value) return
  const n = Number(qty.value)
  if (!orderNo.value || !processName.value || !n) {
    showToast('请填写工序和数量')
    return
  }
  loading.value = true
  lastReport.value = null
  try {
    const res: any = await http.post('/reports', {
      worker_id: auth.workerId,
      order_no: orderNo.value,
      process_name: processName.value,
      color_name: colorName.value || null,
      size_value: sizeValue.value || null,
      qualified_qty: n,
      source: 'qrcode',
      confirm_over_plan: true,
      report_type: reportType.value,
      trace_unit_id: unit.value.id,
      create_trace_bundle: false,
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
