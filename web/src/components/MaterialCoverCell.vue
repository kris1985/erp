<script setup lang="ts">
const props = defineProps<{
  required?: number | string | null
  pool?: number | string | null
  transit?: number | string | null
  draft?: number | string | null
  toBuy?: number | string | null
}>()

function num(v: unknown) {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

function fmt(v: unknown) {
  const n = num(v)
  if (!n) return '0'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

const open = () => num(props.toBuy) > 0
</script>

<template>
  <div class="cover" :class="{ 'is-open': open() }">
    <div class="cover-need">要用 {{ fmt(required) }}</div>
    <div class="cover-meta">池 {{ fmt(pool) }} · 在途 {{ fmt(transit) }} · 草稿 {{ fmt(draft) }}</div>
    <div class="cover-buy">{{ open() ? `还要买 ${fmt(toBuy)}` : '不用买' }}</div>
  </div>
</template>

<style scoped>
.cover {
  line-height: 1.35;
  font-size: 12px;
}
.cover-need {
  color: var(--el-text-color-regular);
}
.cover-meta {
  color: var(--el-text-color-secondary);
}
.cover-buy {
  font-weight: 600;
  color: var(--el-text-color-secondary);
}
.cover.is-open .cover-buy {
  color: var(--el-color-danger);
}
</style>
