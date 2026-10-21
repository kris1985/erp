<template>
  <div class="h5-shell">
    <div class="page page--solo">
      <h1 class="page-title">确认领料</h1>
      <div v-if="error" class="card-block sign-error">{{ error }}</div>
      <template v-else-if="slip">
        <div class="card-block">
          <div class="sign-kind">备料码 {{ slip.slot }}</div>
          <div class="sign-doc">{{ slip.header_no }}</div>
          <div class="muted">{{ slip.pairs }} 双</div>
        </div>
        <div class="card-block">
          <div v-for="line in slip.lines || []" :key="line.id" class="sign-line">
            <div>
              <strong>{{ line.material_name }}</strong>
              <span class="muted">{{ line.material_code }}{{ line.color_name ? ` · ${line.color_name}` : '' }}</span>
            </div>
            <strong>{{ line.actual_qty }}{{ line.unit_name || '' }}</strong>
          </div>
        </div>
        <div v-if="slip.status === 'signed'" class="card-block">{{ slip.picker_name || '领料人' }} 已确认领料</div>
        <div v-else-if="slip.status === 'cancelled'" class="card-block sign-error">这张备料已取消</div>
        <div v-else class="card-block">
          <van-button block type="primary" :loading="submitting" @click="submit">确认领料</van-button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { showToast } from 'vant'
import http from '@/api/http'

const route = useRoute()
const slip = ref<any | null>(null)
const error = ref('')
const submitting = ref(false)

async function load() {
  const token = String(route.params.token || '')
  try {
    const res: any = await http.get(`/material-preps/by-token/${encodeURIComponent(token)}`)
    slip.value = res.data
    error.value = ''
  } catch {
    error.value = '备料码不存在，或当前账号看不到'
  }
}

async function submit() {
  if (submitting.value) return
  submitting.value = true
  try {
    const token = String(route.params.token || '')
    const res: any = await http.post(`/material-preps/by-token/${encodeURIComponent(token)}/sign`)
    slip.value = res.data
    showToast('已确认领料人')
  } catch {
    /* 接口失败时 http 已提示 */
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.sign-error { color: #c00; }
.sign-kind { color: #666; font-size: 13px; }
.sign-doc { margin-top: 4px; font-size: 20px; font-weight: 700; }
.sign-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
}
.muted { display: block; color: #888; font-size: 12px; }
</style>
