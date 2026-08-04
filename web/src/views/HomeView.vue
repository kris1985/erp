<template>
  <div class="page">
    <div class="page-title">工作台</div>
    <div class="card-block" v-if="today">
      <div style="font-weight: 600; margin-bottom: 8px">今日产量</div>
      <div>合格 {{ today.total_qualified }} · 不良 {{ today.total_defect }}</div>
      <pre class="muted" style="white-space: pre-wrap; margin-top: 8px">{{ today.message }}</pre>
    </div>
    <van-grid :column-num="2" clickable>
      <van-grid-item icon="orders-o" text="订单管理" to="/orders" />
      <van-grid-item icon="chat-o" text="DevChat 联调" to="/chat" />
      <van-grid-item icon="friends-o" text="员工" to="/workers" />
      <van-grid-item icon="setting-o" text="工序单价" to="/processes" />
      <van-grid-item icon="label-o" text="款式路线" to="/styles" />
    </van-grid>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import http from '@/api/http'

const today = ref<any>(null)

onMounted(async () => {
  const res: any = await http.get('/progress/today')
  today.value = res.data
})
</script>
