<template>
  <div class="page">
    <div class="page-title">款式与路线</div>
    <van-button type="primary" block round style="margin-bottom: 12px" @click="showStyle = true">新增款式</van-button>
    <van-cell-group inset>
      <van-cell
        v-for="s in styles"
        :key="s.id"
        :title="s.style_name"
        :label="s.style_code"
        is-link
        @click="selectStyle(s)"
      />
    </van-cell-group>

    <div v-if="currentStyle" class="card-block" style="margin-top: 16px">
      <div style="font-weight: 600; margin-bottom: 8px">{{ currentStyle.style_name }} 工艺单价</div>
      <van-cell
        v-for="r in routes"
        :key="r.id"
        :title="processName(r.process_id)"
        :value="`¥${r.price}`"
        :label="`顺序 ${r.seq}`"
      />
      <van-button size="small" type="primary" style="margin-top: 8px" @click="showRoute = true">加路线</van-button>
    </div>

    <van-popup v-model:show="showStyle" position="bottom" round :style="{ padding: '16px' }">
      <van-field v-model="styleForm.style_code" label="款号" />
      <van-field v-model="styleForm.style_name" label="名称" />
      <van-button type="primary" block round style="margin-top: 12px" @click="createStyle">保存</van-button>
    </van-popup>

    <van-popup v-model:show="showRoute" position="bottom" round :style="{ padding: '16px' }">
      <van-field v-model="routeForm.process_id" type="digit" label="工序ID" />
      <van-field v-model="routeForm.seq" type="digit" label="顺序" />
      <van-field v-model="routeForm.price" type="number" label="单价" />
      <van-button type="primary" block round style="margin-top: 12px" @click="createRoute">保存</van-button>
    </van-popup>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { showToast } from 'vant'
import http from '@/api/http'

const styles = ref<any[]>([])
const processes = ref<any[]>([])
const routes = ref<any[]>([])
const currentStyle = ref<any>(null)
const showStyle = ref(false)
const showRoute = ref(false)
const styleForm = reactive({ style_code: '', style_name: '' })
const routeForm = reactive({ process_id: '', seq: '1', price: '0.5' })

function processName(id: number) {
  return processes.value.find((p) => p.id === id)?.name || String(id)
}

async function load() {
  const [s, p]: any[] = await Promise.all([http.get('/styles'), http.get('/processes')])
  styles.value = s.data.items
  processes.value = p.data.items
}

async function selectStyle(s: any) {
  currentStyle.value = s
  const res: any = await http.get('/routes', { params: { style_id: s.id } })
  routes.value = res.data.items
}

async function createStyle() {
  await http.post('/styles', styleForm)
  showToast('已保存')
  showStyle.value = false
  await load()
}

async function createRoute() {
  if (!currentStyle.value) return
  await http.post('/routes', {
    style_id: currentStyle.value.id,
    process_id: Number(routeForm.process_id),
    seq: Number(routeForm.seq),
    price: Number(routeForm.price),
  })
  showToast('已保存')
  showRoute.value = false
  await selectStyle(currentStyle.value)
}

onMounted(load)
</script>
