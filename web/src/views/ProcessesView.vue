<template>
  <div class="page">
    <div class="page-title">工序</div>
    <van-button type="primary" block round style="margin-bottom: 12px" @click="show = true">新增工序</van-button>
    <van-cell-group inset>
      <van-cell
        v-for="p in items"
        :key="p.id"
        :title="p.name"
        :label="`编码 ${p.code}`"
        :value="`¥${p.default_price}`"
      />
    </van-cell-group>

    <van-popup v-model:show="show" position="bottom" round :style="{ padding: '16px' }">
      <van-field v-model="form.name" label="名称" placeholder="针车" />
      <van-field v-model="form.code" label="编码" placeholder="ZC" />
      <van-field v-model="form.default_price" type="number" label="默认单价" />
      <van-button type="primary" block round style="margin-top: 12px" @click="create">保存</van-button>
    </van-popup>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { showToast } from 'vant'
import http from '@/api/http'

const items = ref<any[]>([])
const show = ref(false)
const form = reactive({ name: '', code: '', default_price: '0.5' })

async function load() {
  const res: any = await http.get('/processes')
  items.value = res.data.items
}

async function create() {
  await http.post('/processes', {
    name: form.name,
    code: form.code,
    default_price: Number(form.default_price),
  })
  showToast('已保存')
  show.value = false
  await load()
}

onMounted(load)
</script>
