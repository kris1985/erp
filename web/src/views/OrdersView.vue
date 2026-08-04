<template>
  <div class="page">
    <div class="page-title">订单</div>
    <van-button type="primary" block round style="margin-bottom: 12px" @click="openCreate">新建订单</van-button>
    <div v-for="o in items" :key="o.id" class="card-block" @click="toggle(o)">
      <div style="display: flex; justify-content: space-between">
        <strong>{{ o.order_no }}</strong>
        <span class="muted">{{ o.status }}</span>
      </div>
      <div>{{ o.customer_name }} · {{ o.total_qty }} 双</div>
      <div v-if="expanded === o.id" style="margin-top: 8px">
        <div v-for="p in o.processes" :key="p.id" class="muted">
          {{ p.process_name }}: {{ p.completed_qty }}/{{ p.plan_qty }}
        </div>
      </div>
    </div>

    <van-popup v-model:show="show" position="bottom" round :style="{ height: '70%', padding: '16px' }">
      <van-field v-model="form.order_no" label="订单号" placeholder="可空自动生成" />
      <van-field v-model="form.customer_name" label="客户" placeholder="陈姐" />
      <van-field v-model="form.style_id" is-link readonly label="款式" :model-value="styleLabel" @click="showStyles = true" />
      <van-field v-model="form.size_id" is-link readonly label="尺码" :model-value="sizeLabel" @click="showSizes = true" />
      <van-field v-model="form.color_id" is-link readonly label="颜色" :model-value="colorLabel" @click="showColors = true" />
      <van-field v-model="form.qty" type="digit" label="数量" />
      <van-button type="primary" block round style="margin-top: 16px" @click="create">创建并拆工序</van-button>
    </van-popup>

    <van-action-sheet v-model:show="showStyles" :actions="styleActions" @select="onPickStyle" />
    <van-action-sheet v-model:show="showSizes" :actions="sizeActions" @select="onPickSize" />
    <van-action-sheet v-model:show="showColors" :actions="colorActions" @select="onPickColor" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { showToast } from 'vant'
import http from '@/api/http'

const items = ref<any[]>([])
const styles = ref<any[]>([])
const sizes = ref<any[]>([])
const colors = ref<any[]>([])
const expanded = ref<number | null>(null)
const show = ref(false)
const showStyles = ref(false)
const showSizes = ref(false)
const showColors = ref(false)

const form = reactive({
  order_no: '',
  customer_name: '',
  style_id: 0,
  size_id: 0,
  color_id: 0,
  qty: '100',
})

const styleLabel = computed(() => styles.value.find((s) => s.id === form.style_id)?.style_name || '请选择')
const sizeLabel = computed(() => sizes.value.find((s) => s.id === form.size_id)?.size_value || '请选择')
const colorLabel = computed(() => colors.value.find((c) => c.id === form.color_id)?.name || '请选择')
const styleActions = computed(() => styles.value.map((s) => ({ name: s.style_name, id: s.id })))
const sizeActions = computed(() => sizes.value.map((s) => ({ name: s.size_value + '码', id: s.id })))
const colorActions = computed(() => colors.value.map((c) => ({ name: c.name, id: c.id })))

async function load() {
  const [o, s, sz, c]: any[] = await Promise.all([
    http.get('/orders'),
    http.get('/styles'),
    http.get('/sizes'),
    http.get('/colors'),
  ])
  items.value = o.data.items
  styles.value = s.data.items
  sizes.value = sz.data.items
  colors.value = c.data.items
}

function toggle(o: any) {
  expanded.value = expanded.value === o.id ? null : o.id
}

function openCreate() {
  if (styles.value[0]) form.style_id = styles.value[0].id
  if (sizes.value[0]) form.size_id = sizes.value[0].id
  if (colors.value[0]) form.color_id = colors.value[0].id
  show.value = true
}

function onPickStyle(a: any) {
  form.style_id = a.id
  showStyles.value = false
}
function onPickSize(a: any) {
  form.size_id = a.id
  showSizes.value = false
}
function onPickColor(a: any) {
  form.color_id = a.id
  showColors.value = false
}

async function create() {
  await http.post('/orders', {
    order_no: form.order_no || null,
    customer_name: form.customer_name,
    style_id: form.style_id,
    items: [{ color_id: form.color_id, size_id: form.size_id, qty: Number(form.qty) }],
  })
  showToast('订单已创建')
  show.value = false
  await load()
}

onMounted(load)
</script>
