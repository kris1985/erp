<template>
  <div class="print-page">
    <div class="no-print actions">
      <button type="button" :disabled="!qrs.length" @click="doPrint">打印</button>
      <button type="button" class="ghost" @click="closeOrBack">关闭</button>
      <span v-if="qrs.length" class="hint">{{ qrs.length }} 张 · 贴在物料上循环使用</span>
    </div>

    <div v-if="error" class="err">{{ error }}</div>
    <div v-else-if="loading" class="empty">加载备料码…</div>
    <div v-else class="sheet">
      <div v-for="qr in qrs" :key="qr.slot" class="prep-label">
        <div class="prep-label__slot">备料码 {{ qr.slot }}</div>
        <img v-if="qr.qr_png" :src="qr.qr_png" alt="" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import http from '@/api/http'

const qrs = ref<any[]>([])
const loading = ref(true)
const error = ref('')
let printed = false

async function load() {
  try {
    const origin = typeof location !== 'undefined' ? location.origin : ''
    const res: any = await http.get('/material-preps/qrs', { params: { origin }, silent: true } as any)
    qrs.value = Array.isArray(res?.data) ? res.data : []
    if (!qrs.value.length) {
      error.value = '没有备料码'
      return
    }
    document.title = '备料码'
    if (!printed) {
      printed = true
      setTimeout(doPrint, 400)
    }
  } catch {
    error.value = '备料码加载失败'
  } finally {
    loading.value = false
  }
}

function doPrint() {
  document.title = '备料码'
  window.print()
}

function closeOrBack() {
  window.close()
}

onMounted(load)
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
  margin-bottom: 16px;
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
.sheet {
  display: grid;
  grid-template-columns: repeat(2, 90mm);
  gap: 8mm;
}
.prep-label {
  box-sizing: border-box;
  width: 90mm;
  height: 100mm;
  padding: 6mm;
  border: 1px solid #222;
  text-align: center;
  break-inside: avoid;
  page-break-inside: avoid;
}
.prep-label__slot {
  margin-bottom: 4mm;
  font-size: 18px;
  font-weight: 700;
}
.prep-label img {
  width: 72mm;
  height: 72mm;
  object-fit: contain;
}
@media print {
  .no-print {
    display: none !important;
  }
  .print-page {
    padding: 0;
  }
  .prep-label {
    border-color: #000;
  }
}
</style>

<style>
@page {
  size: A4;
  margin: 10mm;
}
body:has(.print-page) #app {
  max-width: none;
  margin: 0;
  background: #fff;
}
</style>
