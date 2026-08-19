<template>
  <div class="page">
    <van-button type="primary" block round style="margin-bottom: 12px" @click="show = true">新增工序</van-button>
    <!-- 工序段重构（31.1）：按段分组折叠展示（D18 未分段兜底） -->
    <van-collapse v-model="activeNames" v-if="groups.length">
      <van-collapse-item v-for="g in groups" :key="g.key" :name="g.key" :title="`${g.label}（${g.items.length}）`">
        <van-cell-group inset>
          <van-cell
            v-for="p in g.items"
            :key="p.id"
            :title="p.name"
            :value="p.type === 'group' ? '集体' : '个人'"
          />
        </van-cell-group>
      </van-collapse-item>
    </van-collapse>
    <van-empty v-else description="暂无工序" />

    <van-popup v-model:show="show" position="bottom" round :style="{ padding: '16px' }">
      <van-field v-model="form.name" label="名称" placeholder="针车" />
      <van-button type="primary" block round style="margin-top: 12px" @click="create">保存</van-button>
    </van-popup>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { showToast } from 'vant'
import http from '@/api/http'

const items = ref<any[]>([])
const show = ref(false)
const form = reactive({ name: '' })
const activeNames = ref<string[]>([])

const groups = computed(() => {
  const bySeg = new Map<string, { label: string; items: any[] }>()
  for (const p of items.value) {
    const key = p.segment_id != null ? `seg-${p.segment_id}` : 'unlabeled'
    const label = p.segment_name || '未分段'
    if (!bySeg.has(key)) bySeg.set(key, { label, items: [] })
    bySeg.get(key)!.items.push(p)
  }
  return [...bySeg.values()].map((g, i) => ({ key: String(i), ...g }))
})

async function load() {
  const res: any = await http.get('/processes')
  items.value = res.data.items
  activeNames.value = groups.value.map((g) => g.key)
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
