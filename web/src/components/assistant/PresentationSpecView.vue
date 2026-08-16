<script setup lang="ts">
/**
 * PresentationSpecView —— 后端展示语义协议渲染器（架构定稿）。
 *
 * 边界：后端决定「数据语义与推荐展示类型」，前端决定「视觉样式与交互」。
 * 本组件是前端组件注册表：
 *   - 协议类型（schema_version=1.0）→ 对应渲染器
 *   - 未知类型 → FallbackTable（通用表格）→ 降级为确定性 reply 文本
 * 后端升级协议时旧前端不会白屏。
 */
import { computed, defineComponent, h, resolveComponent, type Component } from 'vue'

export type FormatSpec = {
  style?: 'currency' | 'number' | 'percent' | 'date' | 'string'
  scale?: number
  scale_label?: string
  precision?: number
}

export type ColumnSpec = {
  key: string
  label: string
  data_type?: 'string' | 'number' | 'date' | 'boolean'
  unit?: string
  format?: FormatSpec
}

export type PresentationSpec = {
  schema_version: '1.0'
  type: string
  title: string
  recommended_visual?: 'line' | 'bar' | 'horizontal_bar' | 'table' | 'kpi' | null
  value?: number | null
  unit?: string | null
  format?: FormatSpec | null
  context?: Record<string, unknown> | null
  comparison?: {
    label?: string
    previous_value?: number
    delta?: number
    change_rate?: number
    direction?: 'up' | 'down' | 'flat'
  } | null
  columns?: ColumnSpec[] | null
  rows?: Record<string, unknown>[] | null
  pagination?: { total: number; returned: number; truncated: boolean } | null
  category_key?: string | null
  value_key?: string | null
  items?: Record<string, unknown>[] | null
  x?: ColumnSpec | null
  series?: { key: string; label: string; unit?: string; format?: FormatSpec }[] | null
  points?: Record<string, unknown>[] | null
  sections?: { id: string; presentation: PresentationSpec }[] | null
}

const props = defineProps<{ spec: PresentationSpec; reply?: string }>()

// ---------------------------------------------------------------- 数值格式化

function formatValue(value: unknown, format?: FormatSpec | null): string {
  const num = Number(value)
  if (!Number.isFinite(num)) return String(value ?? '')
  const style = format?.style ?? 'number'
  const scale = format?.scale ?? 1
  const precision = format?.precision ?? 2
  const scaled = num / scale
  const opts: Intl.NumberFormatOptions = {
    maximumFractionDigits: precision,
    minimumFractionDigits: 0,
  }
  if (style === 'currency') {
    opts.style = 'currency'
    opts.currency = 'CNY'
    opts.maximumFractionDigits = precision
  }
  let text = scaled.toLocaleString('zh-CN', opts)
  if (format?.scale_label) text += ` ${format.scale_label}`
  return text
}

// ---------------------------------------------------------------- 通用片段

const head = (title: string) =>
  h('div', { class: 'ps-head' }, [h('span', title)])

// ---------------------------------------------------------------- 渲染器

const MetricCard = defineComponent({
  name: 'PsMetricCard',
  props: { spec: { type: Object as () => PresentationSpec, required: true } },
  setup(props) {
    return () => {
      const spec = props.spec
      const unit = spec.unit && spec.unit !== 'CNY' ? spec.unit : ''
      const children = [
        head(spec.title),
        h('div', { class: 'ps-metric-value' }, [
          formatValue(spec.value, spec.format),
          unit ? h('small', unit) : null,
        ]),
      ]
      if (spec.context?.time_range) {
        children.push(h('div', { class: 'ps-metric-context' }, String(spec.context.time_range)))
      }
      return h('section', { class: 'ps-metric', 'aria-label': spec.title }, children)
    }
  },
})

const MetricDeltaCard = defineComponent({
  name: 'PsMetricDeltaCard',
  props: { spec: { type: Object as () => PresentationSpec, required: true } },
  setup(props) {
    return () => {
      const spec = props.spec
      const cmp = spec.comparison
      const direction = cmp?.direction ?? 'flat'
      const unit = spec.unit && spec.unit !== 'CNY' ? spec.unit : ''
      const children = [
        head(spec.title),
        h('div', { class: 'ps-metric-value' }, [
          formatValue(spec.value, spec.format),
          unit ? h('small', unit) : null,
        ]),
      ]
      if (cmp) {
        const deltaText = `${direction === 'up' ? '+' : ''}${formatValue(cmp.delta, spec.format)}`
        const rateText = cmp.change_rate != null
          ? ` · ${cmp.change_rate >= 0 ? '+' : ''}${(cmp.change_rate * 100).toFixed(1)}%`
          : ''
        children.push(
          h('div', { class: 'ps-delta', 'data-direction': direction }, [
            h('span', cmp.label ?? '较上期'),
            h('strong', `${deltaText}${rateText}`),
          ]),
        )
      }
      return h('section', { class: 'ps-metric', 'aria-label': spec.title }, children)
    }
  },
})

const MetricTableView = defineComponent({
  name: 'PsMetricTable',
  props: { spec: { type: Object as () => PresentationSpec, required: true } },
  setup(props) {
    return () => {
      const spec = props.spec
      const columns = spec.columns ?? []
      const rows = spec.rows ?? []
      const thead = h('tr', columns.map((c) => h('th', { key: c.key }, c.label)))
      const tbody = rows.map((row, i) =>
        h('tr', { key: i }, columns.map((c) => {
          const raw = row[c.key]
          const text = c.data_type === 'number' || c.format ? formatValue(raw, c.format) : String(raw ?? '-')
          return h('td', { key: c.key }, text)
        })),
      )
      const children = [
        head(spec.title),
        h('div', { class: 'ps-table-scroll' }, h('table', [h('thead', thead), h('tbody', tbody)])),
      ]
      if (spec.pagination?.truncated) {
        children.push(
          h('div', { class: 'ps-pagination' },
            `共 ${spec.pagination.total} 条，仅显示前 ${spec.pagination.returned} 条`),
        )
      }
      return h('section', { class: 'ps-table', 'aria-label': spec.title }, children)
    }
  },
})

const RankingView = defineComponent({
  name: 'PsRanking',
  props: { spec: { type: Object as () => PresentationSpec, required: true } },
  setup(props) {
    return () => {
      const spec = props.spec
      const items = spec.items ?? []
      const categoryKey = spec.category_key ?? 'label'
      const valueKey = spec.value_key ?? 'value'
      const values = items.map((it) => Number(it[valueKey]) || 0)
      const max = Math.max(...values, 1)
      const rows = items.map((item, index) =>
        h('li', { key: index }, [
          h('i', String(index + 1)),
          h('span', { class: 'ps-rank-label' }, String(item[categoryKey] ?? '')),
          h('div', { class: 'ps-rank-bar' }, [
            h('i', { style: `width: ${Math.max(2, (Number(item[valueKey]) / max) * 100)}%` }),
          ]),
          h('strong', formatValue(item[valueKey], spec.format)),
        ]),
      )
      return h('section', { class: 'ps-ranking', 'aria-label': spec.title }, [
        head(spec.title),
        h('ol', rows),
      ])
    }
  },
})

const TimeseriesView = defineComponent({
  name: 'PsTimeseries',
  props: { spec: { type: Object as () => PresentationSpec, required: true } },
  setup(props) {
    return () => {
      const spec = props.spec
      const points = spec.points ?? []
      const series = spec.series ?? []
      const xKey = spec.x?.key ?? 'period'
      const valueKey = series[0]?.key ?? 'value'
      const width = 320
      const height = 120
      const pad = 8
      const values = points.map((p) => Number(p[valueKey]) || 0)
      const max = Math.max(...values, 1)
      const stepX = points.length > 1 ? (width - pad * 2) / (points.length - 1) : 0
      const poly = points
        .map((p, i) => {
          const x = pad + i * stepX
          const y = height - pad - (Number(p[valueKey]) / max) * (height - pad * 2)
          return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
        })
        .join(' ')
      const children = [head(spec.title)]
      if (points.length > 1) {
        children.push(
          h('svg', { viewBox: `0 0 ${width} ${height}`, class: 'ps-chart' },
            h('polyline', { points: poly, fill: 'none', stroke: 'currentColor', 'stroke-width': 2 })),
        )
      }
      children.push(
        h('ul', points.map((p, i) =>
          h('li', { key: i }, [
            h('span', String(p[xKey] ?? '')),
            h('strong', formatValue(p[valueKey], series[0]?.format)),
          ]))),
      )
      return h('section', { class: 'ps-timeseries', 'aria-label': spec.title }, children)
    }
  },
})

const FallbackTable = defineComponent({
  name: 'PsFallback',
  props: { spec: { type: Object as () => PresentationSpec, required: true }, reply: { type: String, default: '' } },
  setup(props) {
    return () => {
      const spec = props.spec
      const rows = spec.rows ?? []
      const keys = Object.keys(rows[0] ?? {})
      const children = [head(spec.title || '结果')]
      if (rows.length) {
        const thead = h('tr', keys.map((k) => h('th', { key: k }, k)))
        const tbody = rows.map((row, i) =>
          h('tr', { key: i }, keys.map((k) => h('td', { key: k }, String(row[k] ?? '-')))),
        )
        children.push(h('div', { class: 'ps-table-scroll' }, h('table', [h('thead', thead), h('tbody', tbody)])))
      } else if (spec.value != null) {
        children.push(h('div', { class: 'ps-metric-value' }, formatValue(spec.value, spec.format)))
      } else {
        children.push(h('div', { class: 'ps-fallback-text' }, props.reply ?? '（无可展示的结构化结果）'))
      }
      return h('section', { class: 'ps-fallback', 'aria-label': spec.title }, children)
    }
  },
})

const SectionsView = defineComponent({
  name: 'PsSections',
  props: { spec: { type: Object as () => PresentationSpec, required: true } },
  setup(props) {
    return () => {
      const spec = props.spec
      const child = resolveComponent('PresentationSpecView') as Component
      return h('section', { class: 'ps-sections', 'aria-label': spec.title }, [
        head(spec.title),
        ...(spec.sections ?? []).map((sec) => h(child, { key: sec.id, spec: sec.presentation })),
      ])
    }
  },
})

const ComparisonView = defineComponent({
  name: 'PsComparison',
  props: { spec: { type: Object as () => PresentationSpec, required: true } },
  setup(props) {
    return () =>
      h('section', { class: 'ps-comparison', 'aria-label': props.spec.title }, [
        head(props.spec.title),
        h(FallbackTable, { spec: props.spec }),
      ])
  },
})

// ---------------------------------------------------------------- 注册表

const renderers: Record<string, Component> = {
  metric: MetricCard,
  metric_delta: MetricDeltaCard,
  table: MetricTableView,
  ranking: RankingView,
  timeseries: TimeseriesView,
  comparison: ComparisonView,
  sections: SectionsView,
}

const activeRenderer = computed(() => renderers[props.spec.type] ?? FallbackTable)
</script>

<template>
  <component :is="activeRenderer" :spec="spec" :reply="reply" />
</template>

<style scoped>
.ps-head { display: flex; align-items: center; gap: 6px; font-weight: 600; color: var(--sa-text, #303133); margin-bottom: 8px; font-size: 14px; }
.ps-metric { padding: 10px 12px; border-radius: 8px; background: var(--sa-surface, #f7f8fa); }
.ps-metric-value { font-size: 22px; font-weight: 700; color: var(--sa-text, #1f2329); font-variant-numeric: tabular-nums; }
.ps-metric-value small { font-size: 12px; font-weight: 400; color: #909399; margin-left: 4px; }
.ps-metric-context { font-size: 12px; color: #909399; margin-top: 2px; }
.ps-delta { display: flex; gap: 8px; align-items: baseline; font-size: 12px; color: #909399; margin-top: 6px; }
.ps-delta[data-direction='up'] strong { color: #d4380d; }
.ps-delta[data-direction='down'] strong { color: #237804; }
.ps-delta[data-direction='flat'] strong { color: #909399; }
.ps-table, .ps-ranking, .ps-timeseries, .ps-comparison, .ps-sections, .ps-fallback { padding: 10px 12px; border-radius: 8px; background: var(--sa-surface, #f7f8fa); }
.ps-table-scroll { overflow-x: auto; }
.ps-table table, .ps-fallback table { width: 100%; border-collapse: collapse; font-size: 13px; }
.ps-table th, .ps-fallback th { text-align: left; color: #909399; font-weight: 500; padding: 4px 8px; border-bottom: 1px solid #e5e6eb; white-space: nowrap; }
.ps-table td, .ps-fallback td { padding: 5px 8px; border-bottom: 1px solid #f0f1f3; font-variant-numeric: tabular-nums; }
.ps-pagination { font-size: 12px; color: #909399; margin-top: 6px; }
.ps-ranking ol { list-style: none; margin: 0; padding: 0; }
.ps-ranking li { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 13px; }
.ps-ranking li > i { width: 18px; height: 18px; border-radius: 4px; background: #e5e6eb; color: #606266; font-style: normal; font-size: 12px; display: inline-flex; align-items: center; justify-content: center; }
.ps-ranking .ps-rank-label { flex: 0 0 auto; max-width: 40%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ps-ranking .ps-rank-bar { flex: 1; height: 10px; background: #eef0f2; border-radius: 5px; overflow: hidden; }
.ps-ranking .ps-rank-bar i { display: block; height: 100%; background: #409eff; border-radius: 5px; }
.ps-ranking strong { font-variant-numeric: tabular-nums; }
.ps-chart { width: 100%; color: #409eff; margin: 4px 0; }
.ps-timeseries ul { list-style: none; margin: 6px 0 0; padding: 0; max-height: 140px; overflow-y: auto; }
.ps-timeseries li { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; padding: 3px 0; border-bottom: 1px dashed #f0f1f3; }
.ps-timeseries li span { color: #606266; }
.ps-sections > :deep(section) { margin-bottom: 8px; }
.ps-fallback-text { font-size: 13px; color: #606266; }
</style>
