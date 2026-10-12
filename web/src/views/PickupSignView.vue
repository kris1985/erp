<template>
  <div class="h5-shell">
    <div class="page page--solo">
      <h1 class="page-title">{{ returning ? '退料确认' : '领料确认' }}</h1>
      <div v-if="error" class="card-block sign-error">{{ error }}</div>
      <template v-else-if="slip">
        <div class="card-block">
          <div class="sign-kind">{{ slip.kind_label }}</div>
          <div class="sign-doc">{{ slip.doc_no }}</div>
          <div v-if="slip.header_no" class="muted">生产单 {{ slip.header_no }}</div>
        </div>
        <div class="card-block">
          <div v-for="line in slip.lines || []" :key="line.id" class="sign-line">
            <div>
              <strong>{{ line.material_name }}</strong>
              <span class="muted">{{ line.material_code }}{{ line.size_value ? ` · ${line.size_value}` : '' }}</span>
            </div>
            <strong>{{ line.qty }}{{ line.unit_name || '' }}</strong>
          </div>
        </div>
        <div v-if="slip.status === 'signed'" class="card-block">{{ slip.picker_name || (returning ? '退料人' : '领料人') }} 已确认{{ returning ? '退料' : '领料' }}</div>
        <div v-else-if="slip.status === 'cancelled'" class="card-block sign-error">这张{{ returning ? '退料单' : '领料单' }}已取消</div>
        <div v-else class="card-block">
          <van-button block type="primary" :loading="submitting" @click="submit">确认{{ returning ? '退料' : '领料' }}</van-button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { showToast } from 'vant'
import http from '@/api/http'

const route = useRoute()
const slip = ref<any | null>(null)
const error = ref('')
const submitting = ref(false)
const returning = computed(() => String(slip.value?.kind || '').includes('return'))

async function load() {
  const token = String(route.params.token || '')
  try {
    const res: any = await http.get(`/warehouse-pickups/by-token/${encodeURIComponent(token)}`)
    slip.value = res.data
    error.value = ''
  } catch {
    error.value = '单据不存在，或当前账号看不到这张单'
  }
}

async function submit() {
  if (submitting.value) return
  submitting.value = true
  try {
    const token = String(route.params.token || '')
    const res: any = await http.post(`/warehouse-pickups/by-token/${encodeURIComponent(token)}/sign`)
    slip.value = res.data
    showToast(returning.value ? '已确认退料' : '已确认领料')
  } catch {
    /* 接口失败时 http 已提示 */
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.sign-error {
  color: #c00;
}
.sign-kind {
  color: var(--van-text-color-2, #666);
  font-size: 13px;
}
.sign-doc {
  margin: 4px 0;
  font-size: 20px;
  font-weight: 700;
}
.sign-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
}
.sign-line + .sign-line {
  border-top: 1px solid #eee;
}
.sign-line span {
  display: block;
  margin-top: 2px;
}
</style>
