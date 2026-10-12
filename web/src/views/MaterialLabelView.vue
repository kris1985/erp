<template>
  <div class="material-page">
    <div v-if="error" class="material-card material-error">{{ error }}</div>
    <div v-else-if="item" class="material-card">
      <div class="kind">物料</div>
      <div class="code">{{ item.product_code }}</div>
      <div class="name">{{ item.name || '—' }}</div>
      <div class="row"><span>颜色</span><b>{{ item.color_name || '—' }}</b></div>
      <div class="row"><span>分类</span><b>{{ item.category_name || '—' }}</b></div>
      <div class="row"><span>供应商</span><b>{{ item.partner_name || '—' }}</b></div>
      <div class="row"><span>单位</span><b>{{ item.pricing_unit_name || '—' }}</b></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import http from '@/api/http'

const route = useRoute()
const item = ref<any>(null)
const error = ref('')

onMounted(async () => {
  const code = String(route.query.code || '').trim()
  if (!code) {
    error.value = '缺少物料编号'
    return
  }
  document.title = code
  try {
    const res: any = await http.get('/supplier-products/by-code', { params: { code } })
    item.value = res.data
  } catch {
    error.value = '物料不存在或无权查看'
  }
})
</script>

<style scoped>
.material-page {
  min-height: 100vh;
  padding: 24px 16px;
  background: #f5f7fa;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
  color: #111;
}
.material-card {
  max-width: 420px;
  margin: 0 auto;
  background: #fff;
  border-radius: 12px;
  padding: 20px 18px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.05);
}
.kind {
  font-size: 12px;
  letter-spacing: 0.14em;
  color: #666;
}
.code {
  margin-top: 6px;
  font-size: 22px;
  font-weight: 700;
  word-break: break-all;
}
.name {
  margin: 4px 0 14px;
  font-size: 16px;
}
.row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
  border-top: 1px solid #eee;
  font-size: 14px;
}
.row span {
  color: #666;
}
.material-error {
  color: #c45656;
}
</style>
