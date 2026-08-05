<template>
  <div class="progress-ring" :style="{ width: size + 'px' }">
    <van-circle
      :current-rate="rate"
      :rate="rate"
      :speed="60"
      :size="size"
      :stroke-width="strokeWidth"
      :color="color"
      layer-color="#ebedf0"
      :text="text"
    />
    <div v-if="label" class="progress-ring__label">{{ label }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    completed: number
    plan: number
    label?: string
    size?: number
    strokeWidth?: number
  }>(),
  { size: 56, strokeWidth: 60 },
)

const rate = computed(() => {
  if (!props.plan || props.plan <= 0) return 0
  return Math.min(100, Math.round((Number(props.completed) / Number(props.plan)) * 100))
})

const color = computed(() => {
  if (rate.value >= 100) return '#0076ff'
  if (rate.value >= 60) return '#1989fa'
  if (rate.value >= 30) return '#ff976a'
  return '#ee0a24'
})

const text = computed(() => `${rate.value}%`)
</script>

<style scoped>
.progress-ring {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.progress-ring__label {
  font-size: 11px;
  color: #888;
  text-align: center;
  max-width: 72px;
  line-height: 1.2;
}
</style>
