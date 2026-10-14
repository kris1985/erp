<script setup lang="ts">
/**
 * 物料下拉：展开后显示图片、名称、编号、颜色、单价、分类和供应商，收起后仍显示物料编号。
 * 每个下拉自己按编码、名称、分类或供应商过滤，避免互相影响已选值。
 */
import { computed, ref } from 'vue'

const props = defineProps<{
  options: any[]
  remoteOptions?: any[]
  placeholder?: string
  loading?: boolean
}>()

const model = defineModel<number | null>()
const query = ref('')

const emit = defineEmits<{
  filter: [query: string]
  openChange: [open: boolean]
  change: [value: number | null | undefined]
}>()

function optionLabel(sp: any) {
  return String(sp?.product_code || sp?.name || sp?.id || '')
}

function showCode(sp: any) {
  const code = String(sp?.product_code || '').trim()
  const name = String(sp?.name || '').trim()
  return !!code && !!name && code !== name
}

function colorText(sp: any) {
  return String(sp?.color_name || '').trim()
}

function priceText(sp: any) {
  if (sp?.unit_price == null || sp?.unit_price === '') return ''
  const n = Number(sp.unit_price)
  if (!Number.isFinite(n)) return ''
  return `¥${n.toFixed(2)}`
}

function optionLine(sp: any) {
  return [showCode(sp) ? sp.product_code : '', colorText(sp), priceText(sp)]
    .map((part) => String(part || '').trim())
    .filter(Boolean)
    .join(' · ')
}

function optionExtra(sp: any) {
  return [sp?.category_name, sp?.partner_name]
    .map((part) => String(part || '').trim())
    .filter(Boolean)
    .join(' · ')
}

function matches(sp: any, keyword: string) {
  const code = String(sp?.product_code || '').toLowerCase()
  const name = String(sp?.name || '').toLowerCase()
  const category = String(sp?.category_name || '').toLowerCase()
  const supplier = String(sp?.partner_name || '').toLowerCase()
  const color = colorText(sp).toLowerCase()
  const price = priceText(sp).toLowerCase()
  return (
    code.includes(keyword) ||
    name.includes(keyword) ||
    category.includes(keyword) ||
    supplier.includes(keyword) ||
    color.includes(keyword) ||
    price.includes(keyword)
  )
}

const shownOptions = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  const map = new Map<number, any>()
  for (const sp of props.options || []) {
    if (sp?.id == null) continue
    if (!keyword || matches(sp, keyword)) map.set(Number(sp.id), sp)
  }
  if (keyword) {
    for (const sp of props.remoteOptions || []) {
      if (sp?.id == null || !matches(sp, keyword)) continue
      map.set(Number(sp.id), sp)
    }
  }
  return [...map.values()]
})

const showLoading = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!props.loading || !keyword) return false
  return !(props.options || []).some((sp) => matches(sp, keyword))
})

function onFilter(value: string) {
  query.value = value
  emit('filter', value)
}

function onVisible(open: boolean) {
  if (!open) query.value = ''
  emit('openChange', open)
}
</script>

<template>
  <el-select
    v-model="model"
    filterable
    clearable
    size="small"
    style="width: 100%"
    :placeholder="placeholder || '选择'"
    :loading="showLoading"
    :fit-input-width="false"
    :filter-method="onFilter"
    popper-class="mat-pick-popper"
    @visible-change="onVisible"
    @change="(value) => emit('change', value)"
  >
    <el-option
      v-for="sp in shownOptions"
      :key="sp.id"
      :label="optionLabel(sp)"
      :value="sp.id"
    >
      <span class="mat-pick-option">
        <img v-if="sp.image_url" :src="sp.image_url" alt="" class="mat-pick-thumb" />
        <span v-else class="mat-pick-thumb mat-pick-thumb--empty" />
        <span class="mat-pick-meta">
          <span class="mat-pick-name">{{ sp.name || sp.product_code || '未命名' }}</span>
          <span v-if="optionLine(sp)" class="mat-pick-code">{{ optionLine(sp) }}</span>
          <span v-if="optionExtra(sp)" class="mat-pick-extra">{{ optionExtra(sp) }}</span>
        </span>
      </span>
    </el-option>
  </el-select>
</template>

<style scoped>
.mat-pick-option {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 240px;
  max-width: 420px;
  padding: 2px 0;
}

.mat-pick-thumb {
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  border-radius: 4px;
  object-fit: contain;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.mat-pick-thumb--empty {
  display: block;
  background:
    repeating-linear-gradient(-45deg, #f8fafc, #f8fafc 4px, #eef2f7 4px, #eef2f7 8px);
}

.mat-pick-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
  gap: 1px;
}

.mat-pick-name,
.mat-pick-code,
.mat-pick-extra {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mat-pick-name {
  font-size: 13px;
  line-height: 1.3;
  color: inherit;
}

.mat-pick-code,
.mat-pick-extra {
  font-size: 12px;
  line-height: 1.2;
  color: var(--el-text-color-secondary);
}
</style>

<style>
.mat-pick-popper .el-select-dropdown__item {
  height: auto;
  line-height: 1.3;
  padding-top: 4px;
  padding-bottom: 4px;
}
</style>
