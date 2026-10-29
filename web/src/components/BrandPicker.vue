<template>
  <div class="brand-picker">
    <el-select
      :model-value="modelValue"
      filterable
      clearable
      :size="size"
      placeholder="品牌"
      style="flex: 1; min-width: 0"
      @update:model-value="onSelect"
    >
      <el-option v-for="brand in brands" :key="brand.id" :label="brand.name" :value="brand.id" />
    </el-select>
    <el-popover v-if="canWrite" v-model:visible="visible" placement="bottom-end" :width="240" trigger="click">
      <template #reference>
        <el-button link type="primary" :size="size" class="brand-add" title="新增品牌">+</el-button>
      </template>
      <div class="brand-quick">
        <div class="brand-quick-title">新增品牌</div>
        <el-input v-model="name" maxlength="100" placeholder="品牌名称" @keyup.enter="create" />
        <div class="brand-quick-actions">
          <el-button size="small" @click="visible = false">取消</el-button>
          <el-button type="primary" size="small" :loading="creating" @click="create">保存</el-button>
        </div>
      </div>
    </el-popover>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

type Brand = { id: number; name: string }

withDefaults(
  defineProps<{
    modelValue?: number | null
    size?: 'small' | 'default' | 'large'
  }>(),
  { modelValue: null, size: 'small' },
)
const emit = defineEmits<{
  'update:modelValue': [value: number | null]
  change: [brand: Brand | null]
}>()

const auth = useAuthStore()
const canWrite = computed(() => auth.hasPermission('btn.brands.write'))
const brands = ref<Brand[]>([])
const visible = ref(false)
const name = ref('')
const creating = ref(false)

async function load() {
  const res: any = await http.get('/brands')
  brands.value = res.data?.items || []
}

function onSelect(value: number | null | undefined) {
  const id = value || null
  emit('update:modelValue', id)
  emit('change', brands.value.find((brand) => brand.id === id) || null)
}

async function create() {
  const brandName = name.value.trim()
  if (!brandName) {
    ElMessage.warning('请填写品牌名称')
    return
  }
  creating.value = true
  try {
    const res: any = await http.post('/brands', { name: brandName })
    const brand = res.data as Brand
    if (!brands.value.some((item) => item.id === brand.id)) brands.value.push(brand)
    visible.value = false
    name.value = ''
    emit('update:modelValue', brand.id)
    emit('change', brand)
    ElMessage.success(`已添加品牌「${brand.name}」`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '新增品牌失败')
  } finally {
    creating.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<style scoped>
.brand-picker {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
}
.brand-add {
  flex: none;
  font-size: 16px;
}
.brand-quick-title {
  margin-bottom: 8px;
  font-weight: 600;
}
.brand-quick-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}
</style>
