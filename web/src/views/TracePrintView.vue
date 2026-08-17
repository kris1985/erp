<template>
  <div class="print-page">
    <div v-if="error" class="err">{{ error }}</div>
    <template v-else-if="unit">
      <div class="no-print-hide">
        <div class="actions">
          <button type="button" @click="doPrint">打印</button>
          <button type="button" class="ghost" @click="$router.back()">返回</button>
        </div>
      </div>
      <div class="label-card">
        <div class="brand">铁玉兰管家 · 生产流转卡</div>
        <div class="code">{{ unit.code }}</div>
        <img class="qr" :src="qrSrc" alt="qr" />
        <div class="meta">
          <div><span>订单</span>{{ unit.order_no }}</div>
          <div><span>款号</span>{{ unit.product_code || '—' }}</div>
          <div>
            <span>色码</span>{{ [unit.color_name, unit.size_value].filter(Boolean).join(' / ') || '—' }}
          </div>
          <div><span>数量</span>{{ unit.qty }} 双</div>
          <div v-if="allocText"><span>来源</span>{{ allocText }}</div>
        </div>
        <p class="talk">流转卡：全工序扫此码报个人或代报。补打同码。</p>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'

const route = useRoute()
const unit = ref<any>(null)
const error = ref('')

const qrSrc = computed(() => {
  const code = unit.value?.code
  if (!code) return ''
  return `/api/v1/trace-units/by-code/${encodeURIComponent(code)}/qr.png`
})

const allocText = computed(() => {
  const src = unit.value?.allocation_sources
  if (!Array.isArray(src) || !src.length) return ''
  return src.map((s: any) => s.label || `${s.sales_order_no} ${s.qty}`).join(' / ')
})

function doPrint() {
  window.print()
}

onMounted(async () => {
  const code = String(route.params.code || '')
  try {
    const res = await axios.get(`/api/v1/trace-units/by-code/${encodeURIComponent(code)}`)
    if (!res.data?.ok) {
      error.value = '码不存在'
      return
    }
    unit.value = res.data.data
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '码不存在'
  }
})
</script>

<style scoped>
.print-page {
  min-height: 100vh;
  padding: 16px;
  background: #f5f5f5;
}
.err {
  color: #c00;
}
.actions {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.actions button {
  border: none;
  background: #1a73e8;
  color: #fff;
  padding: 8px 16px;
  border-radius: 6px;
}
.actions .ghost {
  background: #fff;
  color: #333;
  border: 1px solid #ddd;
}
.label-card {
  width: 280px;
  margin: 0 auto;
  background: #fff;
  border: 1px solid #ddd;
  padding: 16px;
  text-align: center;
}
.brand {
  font-size: 12px;
  color: #666;
}
.part {
  margin-top: 4px;
  font-size: 13px;
  font-weight: 600;
  color: #333;
}
.code {
  font-size: 20px;
  font-weight: 700;
  margin: 8px 0;
  letter-spacing: 0.04em;
}
.qr {
  width: 180px;
  height: 180px;
}
.meta {
  text-align: left;
  margin-top: 12px;
  font-size: 14px;
  line-height: 1.7;
}
.meta span {
  display: inline-block;
  width: 52px;
  color: #888;
}
.talk {
  margin: 10px 0 0;
  font-size: 12px;
  color: #444;
  text-align: left;
  line-height: 1.45;
}
@media print {
  .no-print-hide,
  .actions {
    display: none !important;
  }
  .print-page {
    background: #fff;
    padding: 0;
  }
  .label-card {
    border: none;
    width: 100%;
  }
}
</style>
