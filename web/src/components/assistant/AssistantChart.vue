<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
])

export type ChartSpec = {
  type?: string
  title?: string
  subtitle?: string
  metric_id?: string
  x?: (string | number)[]
  series?: { name?: string; data?: any[] }[]
  unit?: string | null
}

const props = defineProps<{
  spec: ChartSpec
}>()

const el = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
let ro: ResizeObserver | null = null

/** 围绕品牌蓝的克制色板，避免彩虹堆叠 */
const PALETTE = ['#0076ff', '#0ea5e9', '#38bdf8', '#0284c7', '#f59e0b', '#10b981']

const displayTitle = computed(() => cleanTitle(props.spec?.title, props.spec?.unit))

function cleanTitle(title?: string, unit?: string | null): string {
  let t = (title || '').trim()
  if (!t) return '图表'
  const u = (unit || '').trim()
  if (u) {
    t = t.replace(new RegExp(`[（(]\\s*${escapeReg(u)}\\s*[）)]$`), '').trim()
  }
  return t || '图表'
}

function escapeReg(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function barColor(index: number) {
  const base = PALETTE[index % PALETTE.length]
  return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: lighten(base, 0.22) },
    { offset: 0.55, color: base },
    { offset: 1, color: darken(base, 0.06) },
  ])
}

function lineArea(index: number) {
  const base = PALETTE[index % PALETTE.length]
  return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: withAlpha(base, 0.22) },
    { offset: 1, color: withAlpha(base, 0.01) },
  ])
}

function lighten(hex: string, amount: number): string {
  const n = hex.replace('#', '')
  const r = Math.min(255, parseInt(n.slice(0, 2), 16) + Math.round(255 * amount))
  const g = Math.min(255, parseInt(n.slice(2, 4), 16) + Math.round(255 * amount))
  const b = Math.min(255, parseInt(n.slice(4, 6), 16) + Math.round(255 * amount))
  return `#${[r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('')}`
}

function darken(hex: string, amount: number): string {
  const n = hex.replace('#', '')
  const r = Math.max(0, parseInt(n.slice(0, 2), 16) - Math.round(255 * amount))
  const g = Math.max(0, parseInt(n.slice(2, 4), 16) - Math.round(255 * amount))
  const b = Math.max(0, parseInt(n.slice(4, 6), 16) - Math.round(255 * amount))
  return `#${[r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('')}`
}

function withAlpha(hex: string, alpha: number): string {
  const n = hex.replace('#', '')
  const r = parseInt(n.slice(0, 2), 16)
  const g = parseInt(n.slice(2, 4), 16)
  const b = parseInt(n.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${alpha})`
}

function tooltipBase(): echarts.EChartsCoreOption['tooltip'] {
  return {
    backgroundColor: '#fff',
    borderColor: '#e6ebf2',
    borderWidth: 1,
    padding: [10, 12],
    extraCssText:
      'border-radius:10px;box-shadow:0 8px 24px rgba(15,23,42,0.08),0 1px 2px rgba(15,23,42,0.04);',
    textStyle: { color: '#0f172a', fontSize: 12, fontWeight: 500 },
  }
}

function buildOption(spec: ChartSpec): echarts.EChartsCoreOption {
  const type = (spec.type || 'bar').toLowerCase()
  const seriesIn = spec.series || []
  const unit = (spec.unit || '').trim()
  const multi = seriesIn.length > 1

  if (type === 'pie') {
    const raw = seriesIn[0]?.data || []
    const data = raw.map((d: any) => {
      if (d && typeof d === 'object' && 'value' in d) {
        return { name: String(d.name ?? ''), value: Number(d.value) || 0 }
      }
      return { name: '', value: Number(d) || 0 }
    })
    return {
      color: PALETTE,
      animationDuration: 520,
      animationEasing: 'cubicOut',
      tooltip: {
        ...tooltipBase(),
        trigger: 'item',
        formatter: (p: any) =>
          `<div style="font-size:11px;color:#64748b;margin-bottom:4px">${p.name}</div>` +
          `<div style="font-variant-numeric:tabular-nums"><b style="font-size:15px">${p.value}</b>` +
          `${unit ? `<span style="color:#94a3b8;margin-left:4px">${unit}</span>` : ''}` +
          `<span style="color:#94a3b8;margin-left:8px">${p.percent}%</span></div>`,
      },
      legend: {
        bottom: 2,
        type: 'scroll',
        icon: 'circle',
        itemWidth: 7,
        itemHeight: 7,
        itemGap: 14,
        textStyle: { color: '#64748b', fontSize: 11 },
      },
      series: [
        {
          type: 'pie',
          radius: ['44%', '70%'],
          center: ['50%', '45%'],
          data,
          padAngle: 1.5,
          itemStyle: {
            borderRadius: 5,
            borderColor: '#fff',
            borderWidth: 2,
          },
          label: {
            color: '#64748b',
            fontSize: 11,
            formatter: '{b}\n{d}%',
            lineHeight: 15,
          },
          labelLine: {
            length: 10,
            length2: 8,
            lineStyle: { color: '#cbd5e1' },
          },
          emphasis: {
            scale: true,
            scaleSize: 4,
            itemStyle: {
              shadowBlur: 8,
              shadowColor: 'rgba(15, 23, 42, 0.12)',
            },
          },
        },
      ],
    }
  }

  const x = (spec.x || []).map(String)
  const rotate = x.some((v) => v.length > 6) ? 26 : 0
  const series = seriesIn.map((s, i) => {
    const values = (s.data || []).map((v: any) => Number(v) || 0)
    if (type === 'line') {
      return {
        name: s.name || '数值',
        type: 'line' as const,
        data: values,
        smooth: 0.35,
        symbol: 'circle',
        symbolSize: 6,
        showSymbol: values.length <= 12,
        lineStyle: { width: 2.25, color: PALETTE[i % PALETTE.length] },
        itemStyle: {
          color: '#fff',
          borderColor: PALETTE[i % PALETTE.length],
          borderWidth: 2,
        },
        areaStyle: { color: lineArea(i) },
      }
    }
    return {
      name: s.name || '数值',
      type: 'bar' as const,
      data: values,
      barMaxWidth: multi ? 20 : 32,
      barGap: '32%',
      itemStyle: {
        color: barColor(i),
        borderRadius: [6, 6, 2, 2],
      },
      emphasis: {
        focus: 'series' as const,
        itemStyle: {
          shadowBlur: 8,
          shadowColor: withAlpha(PALETTE[i % PALETTE.length], 0.28),
        },
      },
      label:
        !multi && values.length <= 10
          ? {
              show: true,
              position: 'top' as const,
              color: '#94a3b8',
              fontSize: 10,
              fontWeight: 550,
              distance: 4,
              formatter: (p: any) => {
                const n = Number(p.value)
                if (!n) return ''
                return unit === '%' ? `${n}%` : String(n)
              },
            }
          : undefined,
    }
  })

  return {
    color: PALETTE,
    animationDuration: 560,
    animationEasing: 'cubicOut',
    tooltip: {
      ...tooltipBase(),
      trigger: 'axis',
      axisPointer: {
        type: type === 'line' ? 'line' : 'shadow',
        lineStyle: { color: withAlpha('#0076ff', 0.35), width: 1 },
        shadowStyle: { color: withAlpha('#0076ff', 0.05) },
      },
      formatter: (items: any) => {
        const arr = Array.isArray(items) ? items : [items]
        if (!arr.length) return ''
        const axis = arr[0]?.axisValueLabel ?? arr[0]?.name ?? ''
        const rows = arr
          .map((p: any) => {
            const n = Number(p.value)
            const val = Number.isNaN(n) ? String(p.value ?? '') : String(n)
            const u = unit ? ` <span style="color:#94a3b8">${unit}</span>` : ''
            return (
              `<div style="display:flex;align-items:center;justify-content:space-between;gap:16px;margin-top:6px">` +
              `<span style="display:inline-flex;align-items:center;gap:6px;color:#64748b">` +
              `<span style="width:7px;height:7px;border-radius:2px;background:${p.color}"></span>` +
              `${p.seriesName || ''}</span>` +
              `<span style="font-variant-numeric:tabular-nums;font-weight:650;color:#0f172a">${val}${u}</span>` +
              `</div>`
            )
          })
          .join('')
        return (
          `<div style="font-size:11px;color:#64748b;margin-bottom:2px">${axis}</div>` + rows
        )
      },
    },
    legend: multi
      ? {
          top: 0,
          right: 0,
          icon: 'roundRect',
          itemWidth: 9,
          itemHeight: 9,
          itemGap: 12,
          textStyle: { color: '#64748b', fontSize: 11 },
        }
      : undefined,
    grid: {
      left: 4,
      right: 10,
      top: multi ? 34 : 22,
      bottom: rotate ? 22 : 4,
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: x,
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: {
        color: '#94a3b8',
        fontSize: 11,
        hideOverlap: true,
        rotate,
        margin: 12,
      },
    },
    yAxis: {
      type: 'value',
      splitNumber: 3,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: '#cbd5e1',
        fontSize: 10,
        formatter: (v: number) => (unit === '%' ? `${v}%` : String(v)),
      },
      splitLine: {
        lineStyle: { color: '#f1f5f9', type: 'solid', width: 1 },
      },
    },
    series,
  }
}

async function render() {
  if (!el.value || !props.spec) return
  await nextTick()
  chart = chart || echarts.init(el.value, undefined, { renderer: 'canvas' })
  chart.setOption(buildOption(props.spec), true)
  chart.resize()
}

onMounted(() => {
  void render()
  if (el.value && typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => chart?.resize())
    ro.observe(el.value)
  }
})

watch(
  () => props.spec,
  () => void render(),
  { deep: true },
)

onBeforeUnmount(() => {
  ro?.disconnect()
  ro = null
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="sa-chart-card" :title="spec.metric_id || undefined">
    <div class="sa-chart-head">
      <div class="sa-chart-title-row">
        <span class="sa-chart-mark" aria-hidden="true" />
        <div class="sa-chart-title">{{ displayTitle }}</div>
      </div>
      <div v-if="spec.unit" class="sa-chart-unit">{{ spec.unit }}</div>
    </div>
    <div v-if="spec.subtitle" class="sa-chart-subtitle">{{ spec.subtitle }}</div>
    <div ref="el" class="sa-chart-canvas" />
  </div>
</template>

<style scoped>
.sa-chart-card {
  width: 100%;
  margin-top: 8px;
  border: 1px solid #e6ebf2;
  border-radius: 12px;
  background: #fff;
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 0 0 1px rgba(255, 255, 255, 0.8) inset;
  overflow: hidden;
}

.sa-chart-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 11px 14px 0;
}

.sa-chart-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.sa-chart-mark {
  width: 3px;
  height: 12px;
  border-radius: 2px;
  flex-shrink: 0;
  background: linear-gradient(180deg, #38bdf8, #0076ff);
}

.sa-chart-title {
  font-size: 13px;
  font-weight: 650;
  color: #0f172a;
  letter-spacing: 0.01em;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sa-chart-subtitle {
  padding: 2px 14px 0;
  font-size: 12px;
  color: #94a3b8;
  letter-spacing: 0.01em;
}

.sa-chart-unit {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 550;
  color: #94a3b8;
  letter-spacing: 0.02em;
}

.sa-chart-canvas {
  width: 100%;
  height: min(280px, 42vw);
  min-height: 200px;
  max-height: 300px;
  padding: 2px 6px 10px;
  box-sizing: border-box;
}

@media (max-width: 640px) {
  .sa-chart-canvas {
    height: 220px;
    min-height: 180px;
  }
}
</style>
