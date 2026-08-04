<template>
  <div class="page">
    <div class="page-title">DevChat</div>
    <van-field v-model="workerLabel" is-link readonly label="工人" placeholder="选择工人" @click="showWorkers = true" />
    <div class="card-block" style="min-height: 320px; max-height: 55vh; overflow: auto">
      <div v-for="(m, i) in messages" :key="i" class="chat-bubble" :class="m.role">{{ m.text }}</div>
    </div>
    <van-field v-model="text" rows="2" autosize type="textarea" placeholder="例如：230711 红 37码 针车 做了100双" />
    <div style="display: flex; gap: 8px; margin-top: 8px">
      <van-button type="primary" block round :disabled="!workerId" @click="send(false)">发送</van-button>
      <van-button block round @click="send(true)">确认</van-button>
    </div>
    <van-action-sheet v-model:show="showWorkers" :actions="workerActions" @select="onPickWorker" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import http from '@/api/http'

const workers = ref<any[]>([])
const workerId = ref<number | null>(null)
const workerLabel = ref('')
const showWorkers = ref(false)
const text = ref('')
const messages = ref<{ role: string; text: string }[]>([
  { role: 'bot', text: '选择工人后，可用自然语言报工 / 查工资 / 查进度。' },
])

const workerActions = computed(() => workers.value.map((w) => ({ name: `${w.name} ${w.mobile || ''}`, id: w.id })))

onMounted(async () => {
  const res: any = await http.get('/workers')
  workers.value = res.data.items
})

function onPickWorker(a: any) {
  workerId.value = a.id
  workerLabel.value = a.name
  showWorkers.value = false
}

async function send(confirm: boolean) {
  if (!workerId.value) return
  const payloadText = confirm ? '确认' : text.value
  if (!confirm) {
    messages.value.push({ role: 'user', text: payloadText })
  } else {
    messages.value.push({ role: 'user', text: '确认' })
  }
  const res: any = await http.post('/chat', {
    text: payloadText,
    worker_id: workerId.value,
    confirm,
  })
  messages.value.push({ role: 'bot', text: res.data.reply })
  if (!confirm) text.value = ''
}
</script>
