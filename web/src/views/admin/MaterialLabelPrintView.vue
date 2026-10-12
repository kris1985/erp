<template>
  <div class="print-page label-mode">
    <div class="no-print actions">
      <button type="button" :disabled="!labels.length" @click="doPrint">打印</button>
      <button type="button" class="ghost" @click="closeOrBack">关闭</button>
      <span v-if="labels.length" class="hint">{{ labels.length }} 张 · 请选标签打印机 · 建议纸张 60×40mm</span>
    </div>

    <div v-if="error" class="err">{{ error }}</div>
    <div v-else-if="loading" class="empty">加载标签…</div>
    <div v-else class="label-stack">
      <div v-for="item in labels" :key="item.id" class="mat-label">
        <div class="ml-body">
          <div class="ml-kind">物料</div>
          <div class="ml-code">{{ item.product_code }}</div>
          <div class="ml-name">{{ item.name || '—' }}</div>
          <div class="ml-meta">{{ metaLine(item) }}</div>
          <div class="ml-meta">{{ item.partner_name || '—' }}</div>
        </div>
        <img v-if="qrMap[item.id]" class="ml-qr" :src="qrMap[item.id]" :alt="item.product_code" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import http from '@/api/http'

const MAX_LABELS = 200

const route = useRoute()
const labels = ref<any[]>([])
const qrMap = reactive<Record<number, string>>({})
const loading = ref(true)
const error = ref('')
let printed = false

function metaLine(item: any) {
  return [item.color_name, item.category_name].filter(Boolean).join(' · ') || '—'
}

function parseIds() {
  return [...new Set(
    String(route.query.ids || '')
      .split(',')
      .map((part) => Number(part))
      .filter((id) => Number.isInteger(id) && id > 0),
  )]
}

async function fetchQr(id: number) {
  const blob: any = await http.get(`/supplier-products/${id}/qr.png`, {
    responseType: 'blob',
    silent: true,
  } as any)
  const file = blob instanceof Blob ? blob : new Blob([blob], { type: 'image/png' })
  qrMap[id] = URL.createObjectURL(file)
}

async function load() {
  const ids = parseIds()
  if (!ids.length) {
    error.value = '请先在物料色卡勾选要打印的物料'
    loading.value = false
    return
  }
  if (ids.length > MAX_LABELS) {
    error.value = `一次最多打印 ${MAX_LABELS} 张`
    loading.value = false
    return
  }
  try {
    const rows = await Promise.all(ids.map(async (id) => {
      try {
        const res: any = await http.get(`/supplier-products/${id}`, { silent: true } as any)
        return res.data
      } catch {
        return null
      }
    }))
    labels.value = rows.filter(Boolean)
    if (!labels.value.length) {
      error.value = '物料不存在或无权查看'
      return
    }
    await Promise.all(labels.value.map(async (item) => {
      try {
        await fetchQr(item.id)
      } catch {
        // 文字仍可打印；二维码缺失时留空。
      }
    }))
    document.title = ''
    if (!printed) {
      printed = true
      setTimeout(doPrint, 400)
    }
  } catch {
    error.value = '标签加载失败'
  } finally {
    loading.value = false
  }
}

function doPrint() {
  document.title = ''
  window.print()
}

function closeOrBack() {
  window.close()
}

onMounted(load)

onUnmounted(() => {
  Object.values(qrMap).forEach((url) => URL.revokeObjectURL(url))
})
</script>

<style scoped>
.print-page {
  min-height: 100vh;
  padding: 20px;
  background: #fff;
  color: #111;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
}
.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.actions button {
  padding: 6px 12px;
  border: 1px solid #ccc;
  background: #0076ff;
  color: #fff;
  border-radius: 6px;
  cursor: pointer;
}
.actions button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.actions .ghost {
  background: #fff;
  color: #333;
}
.hint,
.empty,
.err {
  color: #555;
  font-size: 13px;
}
.err {
  color: #c45656;
}
.label-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}
.mat-label {
  width: 60mm;
  height: 40mm;
  box-sizing: border-box;
  border: 1px solid #222;
  padding: 2.5mm 3mm;
  display: grid;
  grid-template-columns: 1fr 24mm;
  gap: 2mm;
  align-items: center;
  overflow: hidden;
  break-inside: avoid;
  page-break-inside: avoid;
  page-break-after: always;
}
.mat-label:last-child {
  page-break-after: auto;
}
.ml-kind {
  font-size: 9px;
  color: #555;
  letter-spacing: 0.12em;
}
.ml-code {
  font-size: 13px;
  font-weight: 700;
  line-height: 1.2;
  margin: 1px 0 2px;
  word-break: break-all;
}
.ml-name,
.ml-meta {
  font-size: 11px;
  line-height: 1.35;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.ml-qr {
  width: 24mm;
  height: 24mm;
  object-fit: contain;
}
@media print {
  .no-print {
    display: none !important;
  }
  .print-page {
    padding: 0;
  }
  .label-stack {
    gap: 0;
  }
  .mat-label {
    border: none;
  }
}
</style>

<style>
@page {
  size: 60mm 40mm;
  margin: 0;
}
body:has(.print-page) #app {
  max-width: none;
  margin: 0;
  background: #fff;
}
body:has(.print-page.label-mode) {
  margin: 0;
}
</style>
