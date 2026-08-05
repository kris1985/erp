<template>
  <div class="page">
    <van-button type="primary" block round style="margin-bottom: 12px" @click="show = true">新增工序</van-button>
    <van-cell-group inset>
      <van-cell
        v-for="p in items"
        :key="p.id"
        :title="p.name"
        :value="p.type === 'group' ? '集体' : '个人'"
      />
    </van-cell-group>

    <van-popup v-model:show="show" position="bottom" round :style="{ padding: '16px' }">
      <van-field v-model="form.name" label="名称" placeholder="针车" />
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
const form = reactive({ name: '' })

async function load() {
  const res: any = await http.get('/processes')
  items.value = res.data.items
}

async function create() {
  if (!form.name.trim()) {
    showToast('请填写名称')
    return
  }
  await http.post('/processes', {
    name: form.name.trim(),
    code: `P${Date.now().toString(36).toUpperCase()}`,
    default_price: 0,
  })
  showToast('已保存')
  show.value = false
  form.name = ''
  await load()
}

onMounted(load)
</script>
