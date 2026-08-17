<template>
  <div class="basket-chips">
    <div
      v-for="(u, i) in units"
      :key="i"
      class="basket-chip"
      :style="chipStyle(u)"
      :title="chipTitle(u)"
    >
      <span class="basket-chip-qty">{{ u.qty }}</span>
      <span class="basket-chip-unit">双</span>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 开裁预览：拟物化「筐」图块。
 * 每个流转卡(筐)一块，块内显示双数；同一来源销售订单（品牌）同色，
 * 不同订单不同色——一眼看出分几筐、每筐多少双、哪些筐同属一单。
 */
import { computed } from 'vue'

const props = defineProps<{ units: any[] }>()

// 拟物化筐色调板（按来源订单轮换）
const palette = [
  { top: '#3d6ea8', bottom: '#22476f', border: '#16324f' },
  { top: '#a4653f', bottom: '#6f3d22', border: '#4f2a16' },
  { top: '#3f9d6b', bottom: '#226b44', border: '#164f30' },
  { top: '#8f5bb8', bottom: '#63398a', border: '#472866' },
  { top: '#b3813f', bottom: '#7a5422', border: '#573b16' },
  { top: '#4f8f8f', bottom: '#2f6464', border: '#1e4949' },
]

function soKey(u: any) {
  return u && u.sales_order_id != null ? `so:${u.sales_order_id}` : 'plain'
}

const soOrder = computed(() => {
  const seen: string[] = []
  for (const u of props.units || []) {
    const k = soKey(u)
    if (!seen.includes(k)) seen.push(k)
  }
  return seen
})

function chipStyle(u: any) {
  const idx = Math.max(0, soOrder.value.indexOf(soKey(u)))
  const c = palette[idx % palette.length]
  return {
    background: `linear-gradient(160deg, ${c.top} 0%, ${c.bottom} 100%)`,
    borderColor: c.border,
  }
}

function chipTitle(u: any) {
  if (u && u.sales_order_id != null) {
    return `来源销售单 #${u.sales_order_id} · 每筐 ${u.qty} 双`
  }
  return `每筐 ${u.qty} 双`
}
</script>

<style scoped>
.basket-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.basket-chip {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 7px;
  border: 1px solid;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.35),
    inset 0 -2px 3px rgba(0, 0, 0, 0.22),
    0 1px 3px rgba(15, 23, 42, 0.18);
  cursor: default;
  user-select: none;
}
.basket-chip-qty {
  font-size: 13px;
  font-weight: 700;
  line-height: 1;
  color: #fff;
  text-shadow: 0 1px 1px rgba(0, 0, 0, 0.35);
}
.basket-chip-unit {
  font-size: 9px;
  margin-top: 2px;
  color: rgba(255, 255, 255, 0.85);
}
</style>
