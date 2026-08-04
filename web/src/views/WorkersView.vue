<template>
  <div class="page">
    <div class="page-title">员工</div>
    <van-button type="primary" block round class="big-btn" style="margin-bottom: 12px" @click="show = true">
      新增员工
    </van-button>
    <van-cell-group inset>
      <van-cell v-for="w in items" :key="w.id" :title="w.name" :label="w.mobile || '无手机号'" :value="w.role" />
    </van-cell-group>

    <van-popup v-model:show="show" position="bottom" round :style="{ padding: '16px' }">
      <van-field v-model="form.name" label="姓名" placeholder="张三" />
      <van-field v-model="form.mobile" label="手机" placeholder="138..." />
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
const form = reactive({ name: '', mobile: '' })

async function load() {
  const res: any = await http.get('/workers')
  items.value = res.data.items
}

async function create() {
  await http.post('/workers', form)
  showToast('已保存')
  show.value = false
  form.name = ''
  form.mobile = ''
  await load()
}

onMounted(load)
</script>
