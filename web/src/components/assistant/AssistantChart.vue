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

const PALETTE = ['#0076ff', '#0ea5e9', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6']

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
    { offset: 0, color: lighten(base, 0.18) },
    { offset: 1, color: base },
  ])
}

function lineArea(index: number) {
  const base = PALETTE[index % PALETTE.length]
  return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: withAlpha(base, 0.28) },
    { offset: 1, color: withAlpha(base, 0.02) },
  ])
}

function lighten(hex: string, amount: number): string {
  const n = hex.replace('#', '')
  const r = Math.min(255, parseInt(n.slice(0, 2), 16) + Math.round(255 * amount))
  const g = Math.min(255, parseInt(n.slice(2, 4), 16) + Math.round(255 * amount))
  const b = Math.min(255, parseInt(n.slice(4, 6), 16) + Math.round(255 * amount))
  return `#${[r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('')}`
}

function withAlpha(hex: string, alpha: number): string {
  const n = hex.replace('#', '')
  const r = parseInt(n.slice(0, 2), 16)
  const g = parseInt(n.slice(2, 4), 16)
  const b = parseInt(n.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${alpha})`
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
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(15, 23, 42, 0.92)',
        borderWidth: 0,
        padding: [8, 12],
        textStyle: { color: '#f8fafc', fontSize: 12 },
        formatter: (p: any) =>
          `${p.name}<br/><b>${p.value}</b>${unit ? ` ${unit}` : ''}（${p.percent}%）`,
      },
      legend: {
        bottom: 4,
        type: 'scroll',
        icon: 'circle',
        itemWidth: 8,
        itemHeight: 8,
        textStyle: { color: '#64748b', fontSize: 12 },
      },
      series: [
        {
          type: 'pie',
          radius: ['42%', '68%'],
          center: ['50%', '46%'],
          data,
          padAngle: 2,
          itemStyle: {
            borderRadius: 6,
            borderColor: '#fff',
            borderWidth: 2,
          },
          label: {
            color: '#475569',
            fontSize: 11,
            formatter: '{b}\n{d}%',
          },
          emphasis: {
            scale: true,
            scaleSize: 6,
            itemStyle: { shadowBlur: 12, shadowColor: 'rgba(15, 23, 42, 0.18)' },
          },
        },
      ],
    }
  }

  const x = (spec.x || []).map(String)
  const rotate = x.some((v) => v.length > 6) ? 28 : 0
  const series = seriesIn.map((s, i) => {
    const values = (s.data || []).map((v: any) => Number(v) || 0)
    if (type === 'line') {
      return {
        name: s.name || '数值',
        type: 'line' as const,
        data: values,
        smooth: true,
        symbol: 'circle',
        symbolSize: 7,
        showSymbol: values.length <= 14,
        lineStyle: { width: 2.5 },
        itemStyle: { color: PALETTE[i % PALETTE.length] },
        areaStyle: { color: lineArea(i) },
      }
    }
    return {
      name: s.name || '数值',
      type: 'bar' as const,
      data: values,
      barMaxWidth: multi ? 22 : 36,
      barGap: '28%',
      itemStyle: {
        color: barColor(i),
        borderRadius: [7, 7, 2, 2],
      },
      emphasis: {
        itemStyle: {
          shadowBlur: 10,
          shadowColor: 'rgba(0, 118, 255, 0.25)',
        },
      },
      label:
        !multi && values.length <= 12
          ? {
              show: true,
              position: 'top' as const,
              color: '#64748b',
              fontSize: 11,
              formatter: (p: any) => {
                const n = Number(p.value)
                if (!n) return ''
                return unit ? `${n}${unit === '%' ? '%' : ''}` : String(n)
              },
            }
          : undefined,
    }
  })

  return {
    color: PALETTE,
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: type === 'line' ? 'line' : 'shadow',
        shadowStyle: { color: 'rgba(0, 118, 255, 0.06)' },
      },
      backgroundColor: 'rgba(15, 23, 42, 0.92)',
      borderWidth: 0,
      padding: [8, 12],
      textStyle: { color: '#f8fafc', fontSize: 12 },
      valueFormatter: (v: any) => {
        const n = Number(v)
        if (Number.isNaN(n)) return String(v ?? '')
        return unit ? `${n} ${unit}` : String(n)
      },
    },
    legend: multi
      ? {
          top: 0,
          right: 0,
          icon: 'roundRect',
          itemWidth: 10,
          itemHeight: 10,
          textStyle: { color: '#64748b', fontSize: 12 },
        }
      : undefined,
    grid: {
      left: 8,
      right: 12,
      top: multi ? 36 : 18,
      bottom: rotate ? 28 : 8,
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: x,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: {
        color: '#64748b',
        fontSize: 11,
        hideOverlap: true,
        rotate,
        margin: 10,
      },
    },
    yAxis: {
      type: 'value',
      splitNumber: 4,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: '#94a3b8',
        fontSize: 11,
        formatter: (v: number) => (unit === '%' ? `${v}%` : String(v)),
      },
      splitLine: {
        lineStyle: { color: '#eef2f7', type: 'dashed' },
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
      <div class="sa-chart-title">{{ displayTitle }}</div>
      <div v-if="spec.unit" class="sa-chart-unit">单位 {{ spec.unit }}</div>
    </div>
    <div ref="el" class="sa-chart-canvas" />
  </div>
</template>

<style scoped>
.sa-chart-card {
  width: 100%;
  margin-top: 10px;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background:
    linear-gradient(180deg, #fbfdff 0%, #ffffff 42%),
    #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  overflow: hidden;
}

.sa-chart-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px 0;
}

.sa-chart-title {
  font-size: 13px;
  font-weight: 650;
  color: #0f172a;
  letter-spacing: 0.01em;
  line-height: 1.35;
}

.sa-chart-unit {
  flex-shrink: 0;
  font-size: 11px;
  color: #94a3b8;
  background: #f1f5f9;
  border-radius: 999px;
  padding: 2px 8px;
}

.sa-chart-canvas {
  width: 100%;
  height: 300px;
  padding: 4px 4px 8px;
  box-sizing: border-box;
}
</style>
