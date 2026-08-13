# Shared UI components

The product relies primarily on Element Plus and Vant primitives. Project-specific reusable components include the following.

## ProgressRing
- Path: `web/src/components/ProgressRing.vue`
- Description: SVG-free conic-gradient progress indicator used in production views.

```vue
<template>
  <div class="progress-ring" :style="ringStyle"><span><slot /></span></div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
const props = withDefaults(defineProps<{ value: number; color?: string }>(), { color: 'var(--ws-primary)' })
const ringStyle = computed(() => ({ '--progress': `${Math.max(0, Math.min(100, props.value))}%`, '--ring-color': props.color }))
</script>
<style scoped>
.progress-ring { width: 42px; height: 42px; border-radius: 50%; display:grid; place-items:center; background:conic-gradient(var(--ring-color) var(--progress), var(--ws-line) 0); }
.progress-ring::before { content:''; position:absolute; width:34px; height:34px; border-radius:50%; background:var(--ws-bg-elevated); }
.progress-ring span { position:relative; font-size:11px; }
</style>
```

## QrScanSheet
- Path: `web/src/components/QrScanSheet.vue`
- Description: Mobile scan bottom sheet; invoked globally by `MainLayout`.
- Props: `show` (`v-model` boolean).

## BossOverview
- Path: `web/src/components/BossOverview.vue`
- Description: Role-aware dashboard summary with risks, KPI and focus-order sections.

The rest of the shared visual primitives are supplied by `element-plus` and `vant`; do not reproduce them as custom components unless a draft specifically needs their presentation.
