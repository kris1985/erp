<template>
  <el-dialog
    :model-value="modelValue"
    width="92vw"
    top="3vh"
    class="dev-dialog detail-dialog"
    destroy-on-close
    append-to-body
    @update:model-value="emit('update:modelValue', $event)"
    @opened="onOpened"
    @closed="onClosed"
  >
    <template #header>
      <div class="detail-dialog-header">
        <div class="detail-dialog-heading">
          <span class="detail-dialog-title">{{ dialogTitle }}</span>
        </div>
        <div v-if="detailRow && !isSnapshotMode" class="detail-dialog-actions">
          <el-button :loading="versionsLoading" @click="openVersionList">修改记录</el-button>
        </div>
      </div>
    </template>
    <div v-loading="loading" class="detail-body">
      <div v-if="detailRow" class="dev-layout">
        <div
          v-if="isSnapshotMode"
          class="version-change-banner"
          :class="{ 'is-empty': !changedSectionLabels.length || onlyCreateSection }"
        >
          <template v-if="onlyCreateSection">本版为新建档案</template>
          <template v-else-if="changedSectionLabels.length">
            本版相对上一版变更：
            <span
              v-for="label in changedSectionLabels"
              :key="label"
              class="product-version-tag"
            >{{ label }}</span>
          </template>
          <template v-else>本版相对上一版无实质变更</template>
        </div>
        <section
          class="dev-panel shoe-panel"
          :class="{ 'is-section-changed': sectionChanged('info') || sectionChanged('quotes') || sectionChanged('brand_quotes') || sectionChanged('create') }"
        >
          <div v-if="sectionChanged('info')" class="section-changed-inline">
            <span class="section-changed-badge">产品信息已改</span>
          </div>
          <el-table
            ref="productInfoTableRef"
            border
            :data="productInfoRows"
            size="small"
            class="soft-table product-info-table"
            @header-dragend="onHeaderDragendInfo"
          >
            <el-table-column
              column-key="image"
              label="图片"
              :width="colWidthInfo('image', 72)"
              align="center"
              class-name="mat-image-col"
              header-class-name="mat-image-col"
              resizable
            >
              <template #default>
                <el-image
                  v-if="detailRow.image_url"
                  :src="detailRow.image_url"
                  fit="contain"
                  class="product-thumb"
                  :preview-src-list="[detailRow.image_url]"
                  preview-teleported
                />
                <span v-else class="muted mat-image-empty"></span>
              </template>
            </el-table-column>
            <el-table-column column-key="product_code" label="工厂型号" :width="colWidthInfo('product_code', 120)" show-overflow-tooltip resizable>
              <template #default>{{ detailRow.product_code }}</template>
            </el-table-column>
            <el-table-column column-key="color" label="颜色" :width="colWidthInfo('color', 100)" show-overflow-tooltip resizable>
              <template #default>
                {{
                  detailRow.colors?.length
                    ? detailRow.colors.map((c: any) => c.name).join('、')
                    : '未绑颜色'
                }}
              </template>
            </el-table-column>
            <el-table-column column-key="fabric" label="面料" :width="colWidthInfo('fabric', 100)" show-overflow-tooltip resizable>
              <template #default>{{ detailRow.fabric || '—' }}</template>
            </el-table-column>
            <el-table-column column-key="lining" label="内里" :width="colWidthInfo('lining', 100)" show-overflow-tooltip resizable>
              <template #default>{{ detailRow.lining || '—' }}</template>
            </el-table-column>
            <el-table-column label="楦" align="center">
              <el-table-column column-key="shoe_last" label="型号" :width="colWidthInfo('shoe_last', 120)" show-overflow-tooltip resizable>
                <template #default>
                  {{ detailRow.shoe_last_name || detailRow.shoe_last_code || '—' }}
                </template>
              </el-table-column>
              <el-table-column
                column-key="shoe_last_hours"
                label="楦头占用时间(小时/双)"
                :width="colWidthInfo('shoe_last_hours', 160)"
                align="right"
                resizable
              >
                <template #default>
                  {{
                    detailRow.shoe_last_hours != null && detailRow.shoe_last_hours !== ''
                      ? Number(detailRow.shoe_last_hours).toFixed(1)
                      : '—'
                  }}
                </template>
              </el-table-column>
            </el-table-column>
            <el-table-column column-key="product_year" label="年份" :width="colWidthInfo('product_year', 88)" resizable>
              <template #default>{{ detailRow.product_year ? `${detailRow.product_year}年` : '—' }}</template>
            </el-table-column>
            <el-table-column column-key="season" label="季节" :width="colWidthInfo('season', 80)" resizable>
              <template #default>{{ seasonLabel(detailRow.season) }}</template>
            </el-table-column>
            <el-table-column column-key="total_cost" label="总成本" :width="colWidthInfo('total_cost', 100)" align="right" resizable>
              <template #default>
                <b class="detail-total-cost">¥{{ formatPrice(totalCost(detailRow)) }}</b>
              </template>
            </el-table-column>
            <el-table-column column-key="quote_price" label="统一报价" :width="colWidthInfo('quote_price', 100)" align="right" resizable>
              <template #default>
                {{
                  detailRow.quote_price != null && detailRow.quote_price !== ''
                    ? `¥${formatPrice(detailRow.quote_price)}`
                    : '—'
                }}
              </template>
            </el-table-column>
          </el-table>

          <div class="quotes-side-by-side">
            <div class="product-quotes-block">
              <div class="panel-title-row quote-toolbar">
                <span class="panel-title" style="margin-bottom: 0">特殊客户报价</span>
                <span v-if="sectionChanged('quotes')" class="section-changed-badge">已改</span>
              </div>
              <div v-if="detailRow.quotes?.length" class="quote-list">
                <div v-for="q in detailRow.quotes" :key="q.id" class="quote-item">
                  <span class="quote-customer">{{ q.partner_short_name || q.partner_name }}</span>
                  <strong class="quote-value">¥{{ formatPrice(q.quote_price) }}</strong>
                </div>
              </div>
              <div v-else class="muted">暂无特殊客户报价</div>
            </div>
            <div class="product-quotes-block">
              <div class="panel-title-row quote-toolbar">
                <span class="panel-title" style="margin-bottom: 0">特殊品牌报价</span>
                <span v-if="sectionChanged('brand_quotes')" class="section-changed-badge">已改</span>
              </div>
              <div v-if="detailRow.brand_quotes?.length" class="quote-list">
                <div v-for="q in detailRow.brand_quotes" :key="q.id" class="quote-item">
                  <span class="quote-customer">{{ q.brand_name }}</span>
                  <strong class="quote-value">¥{{ formatPrice(q.quote_price) }}</strong>
                </div>
              </div>
              <div v-else class="muted">暂无特殊品牌报价</div>
            </div>
          </div>
        </section>

        <section
          class="dev-panel materials-panel"
          :class="{ 'is-section-changed': sectionChanged('materials') || sectionChanged('parts') }"
        >
          <div class="panel-title-row">
            <div class="panel-title">物料明细</div>
            <span v-if="sectionChanged('materials') || sectionChanged('parts')" class="section-changed-badge">已改</span>
            <span class="section-count">{{ (detailRow.materials || []).length }} 项</span>
          </div>
          <el-table
            ref="materialsTableRef"
            border
            :data="detailRow.materials || []"
            size="small"
            class="soft-table"
            empty-text="暂无物料"
            @header-dragend="onHeaderDragend4"
          >
            <el-table-column
              column-key="material_image"
              label="物料图片"
              :width="colWidth4('material_image', 72)"
              align="center"
              class-name="mat-image-col"
              header-class-name="mat-image-col"
              resizable
            >
              <template #default="{ row: m }">
                <el-image
                  v-if="m.image_url"
                  :src="m.image_url"
                  :preview-src-list="[m.image_url]"
                  fit="contain"
                  class="product-thumb"
                  preview-teleported
                />
                <span v-else class="muted mat-image-empty"></span>
              </template>
            </el-table-column>
            <el-table-column
              column-key="name"
              label="名称"
              :min-width="flexColMinWidth4('name', 110)"
              show-overflow-tooltip
              resizable
            >
              <template #default="{ row: m }">{{ m.supplier_product_name || '—' }}</template>
            </el-table-column>
            <el-table-column column-key="color" label="颜色" :width="colWidth4('color', 72)" resizable>
              <template #default="{ row: m }">{{ m.color_name || '—' }}</template>
            </el-table-column>
            <el-table-column
              column-key="material_code"
              label="物料编号"
              :width="colWidth4('material_code', 100)"
              show-overflow-tooltip
              resizable
            >
              <template #default="{ row: m }">{{ m.supplier_product_code || '—' }}</template>
            </el-table-column>
            <el-table-column
              column-key="consume_segment"
              label="消耗部门"
              :width="colWidth4('consume_segment', 110)"
              resizable
            >
              <template #default="{ row: m }">
                <span v-if="m.consume_segment_name">{{ m.consume_segment_name }}</span>
                <span v-else class="muted">未标注</span>
              </template>
            </el-table-column>
            <el-table-column
              column-key="unit_price"
              label="单价"
              :width="colWidth4('unit_price', 80)"
              align="right"
              resizable
            >
              <template #default="{ row: m }">{{ formatPrice(m.unit_price) }}</template>
            </el-table-column>
            <el-table-column
              column-key="qty"
              label="用量"
              :width="colWidth4('qty', 70)"
              align="right"
              resizable
            >
              <template #default="{ row: m }">{{ formatQty(m.qty) }}</template>
            </el-table-column>
            <el-table-column column-key="unit" label="单位" :width="colWidth4('unit', 72)" resizable>
              <template #default="{ row: m }">{{ m.pricing_unit_name || '—' }}</template>
            </el-table-column>
            <el-table-column
              column-key="supplier"
              label="供应商"
              :width="colWidth4('supplier', 110)"
              show-overflow-tooltip
              resizable
            >
              <template #default="{ row: m }">{{ m.partner_name || '—' }}</template>
            </el-table-column>
            <el-table-column
              column-key="material_total"
              label="材料总价"
              :width="colWidth4('material_total', 90)"
              align="right"
              resizable
            >
              <template #default="{ row: m }">
                <span class="money">{{ formatPrice(m.line_total) }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div class="cost-summary-line">
            <span>材料成本</span>
            <strong>¥{{ formatPrice(detailRow.material_cost) }}</strong>
          </div>
        </section>

        <section
          class="dev-panel labors-panel"
          :class="{ 'is-section-changed': sectionChanged('labors') }"
        >
          <div class="panel-title-row">
            <div class="panel-title">工艺路线</div>
            <span v-if="sectionChanged('labors')" class="section-changed-badge">已改</span>
            <span class="section-count">{{ (detailRow.labors || []).length }} 道工序</span>
          </div>
          <!-- 工序段重构（20.2）：工艺路线按段分组展示 -->
          <div class="detail-labor-groups">
            <div v-for="g in laborGroups" :key="g.key" class="detail-labor-group">
              <div class="detail-labor-group-head">
                <span class="detail-labor-group-name">{{ segmentDepartmentName(g.name) }}</span>
                <div class="detail-labor-group-meta muted">
                  <span>参考价 ¥{{ formatPrice(g.refPrice) }}</span>
                  <span>小计 ¥{{ formatPrice(g.effectiveCost) }}</span>
                </div>
              </div>
              <div
                v-for="l in g.items"
                :key="l.id ?? l.process_name"
                class="detail-labor-row"
              >
                <div class="detail-labor-line">
                  <span class="detail-labor-name">{{ l.process_name || '—' }}</span>
                  <span v-if="isHourlyLabor(l)" class="money">计时</span>
                  <span v-else class="money">¥{{ formatPrice(l.unit_price) }}</span>
                  <el-tooltip
                    v-if="laborHasPriceHistory(l)"
                    placement="top"
                    :show-after="120"
                    effect="light"
                    popper-class="detail-price-history-popper"
                  >
                    <template #content>
                      <div class="detail-price-history-tip">
                        <div class="detail-price-history-tip-title">改价记录</div>
                        <div
                          v-for="item in laborPriceHistory(l)"
                          :key="item.id"
                          class="detail-price-history-tip-row"
                        >
                          <span class="detail-price-history-tip-price">
                            {{ formatProcessHistoryPrice(item, isHourlyLabor(l)) }}
                          </span>
                          <span class="detail-price-history-tip-meta">
                            <template v-if="!isHourlyHistoryZero(item) && item.old_price != null && item.old_price !== ''">
                              原 ¥{{ formatPrice(item.old_price) }} ·
                            </template>
                            {{ item.changed_by_name || '—' }}
                            <template v-if="item.changed_at">
                              · {{ formatHistoryTime(item.changed_at) }}
                            </template>
                          </span>
                        </div>
                      </div>
                    </template>
                    <el-icon class="detail-price-history-icon" :size="14"><Clock /></el-icon>
                  </el-tooltip>
                  <span v-if="!isHourlyLabor(l)" class="muted detail-labor-unit">元/双</span>
                </div>
                <div v-if="l.requirement_note" class="detail-labor-note muted">
                  <div class="detail-labor-note-label">工艺要求：</div>
                  <div class="detail-labor-note-body">{{ l.requirement_note }}</div>
                </div>
              </div>
              <div v-if="!g.items.length" class="muted" style="padding: 8px 10px; font-size: 12px">
                暂无工序
              </div>
            </div>
          </div>
          <div v-if="!laborGroups.length" class="muted" style="padding: 12px">暂无工序段</div>
          <div class="cost-summary-line">
            <span>人工成本</span>
            <strong>¥{{ formatPrice(detailRow.labor_cost) }}</strong>
          </div>
        </section>

        <section
          class="dev-panel commissions-panel"
          :class="{ 'is-section-changed': sectionChanged('commissions') }"
        >
          <div class="panel-title-row">
            <div class="panel-title">提成</div>
            <span v-if="sectionChanged('commissions')" class="section-changed-badge">已改</span>
            <span class="section-count">{{ (detailRow.commissions || []).length }} 项</span>
          </div>
          <el-table
            v-if="(detailRow.commissions || []).length"
            border
            :data="commissionOneRow"
            size="small"
            class="soft-table other-cost-one-row-table"
          >
            <el-table-column
              v-for="(c, idx) in detailRow.commissions"
              :key="c.id ?? `cm-d-${idx}`"
              :column-key="`dcm-${c.id ?? idx}`"
              :label="c.employee_name || '（未选人）'"
              min-width="120"
              align="right"
              show-overflow-tooltip
            >
              <template #default>
                <span class="money">¥{{ formatPrice(c.amount) }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div v-else class="muted" style="padding: 12px">暂无提成</div>
          <div class="cost-summary-line">
            <span>提成</span>
            <strong>¥{{ formatPrice(detailRow.commission_cost) }}</strong>
          </div>
        </section>

        <section
          class="dev-panel other-costs-panel"
          :class="{ 'is-section-changed': sectionChanged('other_costs') }"
        >
          <div class="panel-title-row">
            <div class="panel-title">其它成本</div>
            <span v-if="sectionChanged('other_costs')" class="section-changed-badge">已改</span>
            <span class="section-count">{{ (detailRow.other_costs || []).length }} 项</span>
          </div>
          <el-table
            v-if="(detailRow.other_costs || []).length"
            border
            :data="otherCostOneRow"
            size="small"
            class="soft-table other-cost-one-row-table"
          >
            <el-table-column
              v-for="(o, idx) in detailRow.other_costs"
              :key="o.id ?? `${o.name}-${idx}`"
              :column-key="`doc-${o.id ?? idx}`"
              :label="o.name || '—'"
              min-width="120"
              align="right"
              show-overflow-tooltip
            >
              <template #default>
                <span class="money">¥{{ formatPrice(o.amount) }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div v-else class="muted" style="padding: 12px">暂无其它成本</div>
          <div class="cost-summary-line">
            <span>其它成本</span>
            <strong>¥{{ formatPrice(detailRow.other_cost) }}</strong>
          </div>
        </section>
      </div>
      <el-empty v-else-if="!loading" description="未找到产品" />
    </div>

    <el-dialog
      v-model="versionsVisible"
      title="产品历史版本"
      width="560px"
      append-to-body
      destroy-on-close
      class="product-version-list-dialog"
    >
      <div v-loading="versionsLoading">
        <el-empty v-if="!versions.length && !versionsLoading" description="暂无历史版本" />
        <div v-else class="product-version-list">
          <button
            v-for="v in versions"
            :key="v.id"
            type="button"
            class="product-version-item"
            :disabled="versionOpeningId === v.id"
            @click="openVersion(v)"
          >
            <div class="product-version-main">
              <span class="product-version-no">v{{ v.version_no }}</span>
              <span class="product-version-meta">
                {{ v.changed_by_name || '—' }}
                · {{ formatDateTime(v.changed_at) }}
                · {{ v.source === 'product_create' ? '创建' : '保存' }}
              </span>
            </div>
            <div class="product-version-changes">
              <template v-if="(v.changed_section_labels || []).length">
                <span
                  v-for="label in v.changed_section_labels"
                  :key="label"
                  class="product-version-tag"
                >{{ label }}</span>
              </template>
              <span v-else class="product-version-tag is-muted">无变更</span>
            </div>
          </button>
        </div>
      </div>
    </el-dialog>

    <OwnProductDetailDialog
      v-if="historyVisible && historySnapshot"
      v-model="historyVisible"
      :snapshot="historySnapshot"
      :version-meta="historyMeta"
    />
  </el-dialog>
</template>

<script setup lang="ts">
defineOptions({ name: 'OwnProductDetailDialog' })

import { computed, ref, watch } from 'vue'
import { Clock } from '@element-plus/icons-vue'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'

const props = defineProps<{
  modelValue: boolean
  productId?: number | null
  /** 只读历史快照；有值时不拉当前产品 */
  snapshot?: Record<string, any> | null
  versionMeta?: {
    version_no?: number
    changed_by_name?: string | null
    changed_at?: string | null
    source?: string
    changed_sections?: string[]
    changed_section_labels?: string[]
  } | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const loading = ref(false)
const detailRow = ref<any>(null)
const detailPriceHistoryMap = ref<Record<string, any[]>>({})
const segments = ref<any[]>([])
const orgSkiving = ref(false)

const versionsVisible = ref(false)
const versionsLoading = ref(false)
const versions = ref<any[]>([])
const versionOpeningId = ref<number | null>(null)
const historyVisible = ref(false)
const historySnapshot = ref<Record<string, any> | null>(null)
const historyMeta = ref<{
  version_no?: number
  changed_by_name?: string | null
  changed_at?: string | null
  source?: string
  changed_sections?: string[]
  changed_section_labels?: string[]
} | null>(null)

const isSnapshotMode = computed(() => !!props.snapshot)
const changedSections = computed(() => props.versionMeta?.changed_sections || [])
const changedSectionLabels = computed(() => {
  const labels = props.versionMeta?.changed_section_labels
  if (labels?.length) return labels
  return []
})
const onlyCreateSection = computed(
  () => changedSections.value.length === 1 && changedSections.value[0] === 'create',
)
function sectionChanged(key: string) {
  return isSnapshotMode.value && changedSections.value.includes(key)
}
const dialogTitle = computed(() => {
  if (!isSnapshotMode.value) return '产品详情'
  const meta = props.versionMeta || {}
  const parts = [`历史版本 v${meta.version_no ?? '—'}`]
  if (meta.changed_by_name) parts.push(String(meta.changed_by_name))
  if (meta.changed_at) parts.push(formatDateTime(meta.changed_at))
  return parts.join(' · ')
})

const DEFAULT_SEGMENT_CODES = ['cut', 'stitch', 'forming', 'packing']
function segmentDepartmentName(name: string) {
  return name === '未分段' || name.endsWith('部') ? name : `${name}部`
}

// 工艺路线按段分组；段顺序跟工序段基础数据 sort_order，不随工序出现顺序变化
const laborGroups = computed(() => {
  const labors = detailRow.value?.labors || []
  const refPrices = detailRow.value?.segment_ref_prices || null
  const wanted = [...DEFAULT_SEGMENT_CODES]
  if (orgSkiving.value) wanted.push('skiving')
  const order = segments.value
    .filter((seg) => wanted.includes(seg.code) && seg.is_active !== false)
    .slice()
    .sort(
      (a, b) =>
        Number(a.sort_order || 0) - Number(b.sort_order || 0) || Number(a.id) - Number(b.id),
    )
    .map((seg) => ({ key: seg.id, name: seg.name }))
  const refOf = (segKey: number) => {
    if (!refPrices || typeof refPrices !== 'object') return null
    const raw = refPrices[String(segKey)] ?? (refPrices as any)[segKey]
    const n = Number(raw)
    return !Number.isNaN(n) && n > 0 ? n : null
  }
  const groups = order.map((seg) => ({
    key: seg.key,
    name: seg.name,
    items: [] as any[],
    subtotal: 0,
    refPrice: null as number | null,
    effectiveCost: null as number | null,
  }))
  const byKey = new Map(groups.map((g) => [Number(g.key), g]))
  const unlabeled: any[] = []
  for (const l of labors) {
    const g = l.segment_id != null ? byKey.get(Number(l.segment_id)) : undefined
    if (g) {
      g.items.push(l)
      g.subtotal += Number(l.unit_price || 0)
    } else {
      unlabeled.push(l)
    }
  }
  for (const g of groups) {
    const ref = refOf(Number(g.key))
    g.refPrice = ref
    g.effectiveCost = g.subtotal > 0 ? g.subtotal : ref
  }
  if (unlabeled.length) {
    const sub = unlabeled.reduce((sum: number, l: any) => sum + Number(l.unit_price || 0), 0)
    groups.push({
      key: 'unlabeled',
      name: '未分段',
      items: unlabeled,
      subtotal: sub,
      refPrice: null,
      effectiveCost: sub > 0 ? sub : null,
    })
  }
  return groups
})

const materialsTableRef = ref()
const laborsTableRef = ref()
const productInfoTableRef = ref()
const productInfoRows = computed(() => (detailRow.value ? [detailRow.value] : []))
const otherCostOneRow = computed(() => [{}])
const commissionOneRow = computed(() => [{}])

const {
  colWidth: colWidthInfo,
  onHeaderDragend: onHeaderDragendInfo,
  relayoutTable: relayoutProductInfo,
} = useTableColWidths('own-product-detail-info', productInfoTableRef, {
  flexKey: 'fabric',
  flexDefaultMin: 100,
  fitToContainer: true,
})
const {
  colWidth: colWidth4,
  flexColMinWidth: flexColMinWidth4,
  onHeaderDragend: onHeaderDragend4,
  relayoutTable: relayoutMaterials,
} = useTableColWidths('own-products-detail-materials', materialsTableRef, {
  flexKey: 'name',
  flexDefaultMin: 110,
  fitToContainer: true,
})
const {
  colWidth: colWidth5,
  flexColMinWidth: flexColMinWidth5,
  onHeaderDragend: onHeaderDragend5,
  relayoutTable: relayoutLabors,
} = useTableColWidths('own-products-detail-labors', laborsTableRef, {
  flexKey: 'process_name',
  flexDefaultMin: 120,
  fitToContainer: true,
})

const seasonOptions = [
  { value: 'SS', label: '春夏' },
  { value: 'FW', label: '秋冬' },
  { value: 'ALL', label: '全年' },
]

function seasonLabel(value: string | null | undefined) {
  return seasonOptions.find((item) => item.value === value)?.label || '未设置'
}

function formatDate(v?: string) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 10)
}

function formatDateTime(v?: string | null) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 19)
}

/** 工序改价历史：精确到分钟 */
function formatHistoryTime(v?: string | null) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 16)
}

function formatPrice(v: any, digits = 2) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(digits)
}

/** 用量：整数不补小数；有小数最多保留 4 位并去掉尾随 0 */
function formatQty(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  if (Number.isInteger(n)) return String(n)
  return String(Number(n.toFixed(4)))
}

function totalCost(row: any) {
  return (
    Number(row.material_cost || 0) +
    Number(row.labor_cost || 0) +
    Number(row.commission_cost || 0) +
    Number(row.other_cost || 0)
  )
}

function laborPriceHistoryKey(l: any) {
  if (l?.process_id != null) return `id:${l.process_id}`
  const name = String(l?.process_name || '').trim()
  return name ? `name:${name}` : ''
}

function laborPriceHistory(l: any) {
  const key = laborPriceHistoryKey(l)
  return key ? detailPriceHistoryMap.value[key] || [] : []
}

function laborHasPriceHistory(l: any) {
  return laborPriceHistory(l).some((i) => i.old_price != null && i.old_price !== '')
}

function isHourlyLabor(l: any) {
  return l?.pay_mode === 'hourly'
}

function isHourlyHistoryZero(item: any) {
  const price = Number(item?.new_price)
  return !Number.isFinite(price) || price <= 0
}

function formatProcessHistoryPrice(item: any, hourly = false) {
  if (hourly && isHourlyHistoryZero(item)) return '计时'
  // 切到计时：原价 → 0，展示为「计时」；切回计件：0 → 恢复价，走下方金额
  if (
    item?.source === 'process_pay_mode_change' &&
    isHourlyHistoryZero(item) &&
    Number(item?.old_price) > 0
  ) {
    return '计时'
  }
  return `¥${formatPrice(item?.new_price)}`
}

async function loadDetailPriceHistories(labors: any[]) {
  const tasks = new Map<string, { process_id?: number; process_name?: string }>()
  for (const l of labors || []) {
    const key = laborPriceHistoryKey(l)
    if (!key || tasks.has(key)) continue
    if (l.process_id != null) tasks.set(key, { process_id: Number(l.process_id) })
    else tasks.set(key, { process_name: String(l.process_name || '').trim() })
  }
  const next: Record<string, any[]> = {}
  await Promise.all(
    [...tasks.entries()].map(async ([key, params]) => {
      try {
        const res: any = await http.get('/own-products/process-price-history', {
          params: { ...params, limit: 15 },
        })
        next[key] = res.data?.items || []
      } catch {
        next[key] = []
      }
    }),
  )
  detailPriceHistoryMap.value = next
}

async function ensureSegments() {
  if (segments.value.length) return
  try {
    const [segRes, orgRes]: any[] = await Promise.all([
      http.get('/process-segments'),
      http.get('/org/settings'),
    ])
    segments.value = segRes.data?.items || []
    orgSkiving.value = !!orgRes.data?.skiving_enabled
  } catch {
    /* 段信息拉取失败不影响产品展示 */
  }
}

async function loadProduct(id: number) {
  await ensureSegments()

  loading.value = true
  detailRow.value = null
  detailPriceHistoryMap.value = {}
  try {
    const res: any = await http.get(`/own-products/${id}`)
    detailRow.value = res.data
    await loadDetailPriceHistories(res.data?.labors || [])
  } catch {
    detailRow.value = null
  } finally {
    loading.value = false
  }
}

async function loadSnapshot(snap: Record<string, any>) {
  detailRow.value = snap
  detailPriceHistoryMap.value = {}
  loading.value = true
  try {
    await ensureSegments()
  } finally {
    loading.value = false
  }
}

async function openVersionList() {
  const id = props.productId ?? detailRow.value?.id
  if (!id) return
  versionsVisible.value = true
  versionsLoading.value = true
  versions.value = []
  try {
    const res: any = await http.get(`/own-products/${id}/versions`)
    versions.value = res.data?.items || []
  } catch {
    versions.value = []
  } finally {
    versionsLoading.value = false
  }
}

async function openVersion(v: any) {
  const id = props.productId ?? detailRow.value?.id
  if (!id || !v?.id) return
  versionOpeningId.value = v.id
  try {
    const res: any = await http.get(`/own-products/${id}/versions/${v.id}`)
    historySnapshot.value = res.data?.snapshot || null
    historyMeta.value = {
      version_no: res.data?.version_no ?? v.version_no,
      changed_by_name: res.data?.changed_by_name ?? v.changed_by_name,
      changed_at: res.data?.changed_at ?? v.changed_at,
      source: res.data?.source ?? v.source,
      changed_sections: res.data?.changed_sections ?? v.changed_sections ?? [],
      changed_section_labels:
        res.data?.changed_section_labels ?? v.changed_section_labels ?? [],
    }
    historyVisible.value = true
  } catch {
    /* 打开失败保持列表 */
  } finally {
    versionOpeningId.value = null
  }
}

watch(
  () => [props.modelValue, props.productId, props.snapshot] as const,
  ([visible, id, snap]) => {
    if (!visible) return
    if (snap) {
      void loadSnapshot(snap)
      return
    }
    if (id) void loadProduct(id)
  },
  { immediate: true },
)

function onOpened() {
  relayoutProductInfo()
  relayoutMaterials()
  relayoutLabors()
}

function onClosed() {
  detailRow.value = null
  detailPriceHistoryMap.value = {}
  versionsVisible.value = false
  versions.value = []
  historyVisible.value = false
  historySnapshot.value = null
  historyMeta.value = null
}
</script>

<style scoped>
.detail-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  padding-right: 28px;
}
.detail-dialog-heading {
  min-width: 0;
}
.detail-dialog-title {
  font-size: 16px;
  font-weight: 600;
  color: #0f172a;
}
.detail-dialog-actions {
  display: flex;
  flex-shrink: 0;
  gap: 8px;
}
.product-version-list {
  display: grid;
  gap: 6px;
  max-height: 60vh;
  overflow: auto;
}
.product-version-item {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  text-align: left;
  cursor: pointer;
}
.product-version-item:hover:not(:disabled) {
  border-color: var(--el-color-primary-light-5);
  background: #f8fafc;
}
.product-version-item:disabled {
  opacity: 0.6;
  cursor: wait;
}
.product-version-main {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}
.product-version-no {
  flex-shrink: 0;
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}
.product-version-meta {
  min-width: 0;
  color: #64748b;
  font-size: 13px;
}
.product-version-changes {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.product-version-tag {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: 999px;
  background: #fff7ed;
  color: #c2410c;
  border: 1px solid #fed7aa;
  font-size: 12px;
  line-height: 1.5;
}
.product-version-tag.is-muted {
  background: #f1f5f9;
  color: #64748b;
  border-color: #e2e8f0;
}
.version-change-banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 8px;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  color: #9a3412;
  font-size: 13px;
}
.version-change-banner.is-empty {
  background: #f8fafc;
  border-color: #e2e8f0;
  color: #64748b;
}
.section-changed-badge {
  display: inline-flex;
  align-items: center;
  padding: 0 6px;
  border-radius: 999px;
  background: #fff7ed;
  color: #c2410c;
  border: 1px solid #fed7aa;
  font-size: 11px;
  line-height: 1.6;
  font-weight: 600;
}
.section-changed-inline {
  margin-bottom: 8px;
}
.dev-panel.is-section-changed {
  outline: 1px solid #fdba74;
  box-shadow: 0 0 0 2px rgba(251, 146, 60, 0.12);
}
.is-section-changed-block .panel-title {
  color: #c2410c;
}
.detail-body {
  min-height: 240px;
}

.dev-layout {
  display: grid;
  grid-template-columns: 1fr;
  gap: 20px;
  min-height: 0;
}

.detail-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-right: 28px;
  width: 100%;
}

.detail-dialog-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--ink);
  line-height: 1.3;
}

.dev-panel {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
  padding: 10px 12px;
  min-width: 0;
}

.panel-kicker {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--accent);
  margin-bottom: 8px;
}

.product-info-table :deep(.el-table__cell) {
  vertical-align: middle;
  padding: 6px 8px;
}

.product-info-table :deep(.el-table__header th.el-table__cell) {
  padding: 2px 6px !important;
  height: auto;
  line-height: 1.15;
}

.product-info-table :deep(.el-table__header th.is-group) {
  padding: 0 6px !important;
  font-size: 11px;
  letter-spacing: 0.08em;
}

.product-info-table :deep(.el-table__header .cell) {
  line-height: 1.15;
  padding-top: 0;
  padding-bottom: 0;
  white-space: nowrap;
}

.product-info-table :deep(.el-table__header th.is-group > .cell) {
  line-height: 1.1;
  padding: 1px 0;
}

.product-quotes-block {
  margin-top: 10px;
}

.quotes-side-by-side {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 48px;
  margin-top: 10px;
  align-items: start;
}

.quotes-side-by-side .product-quotes-block {
  margin-top: 0;
  min-width: 0;
}

@media (max-width: 900px) {
  .quotes-side-by-side {
    grid-template-columns: 1fr;
  }
}

.panel-title {
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 8px;
  color: var(--ink);
}

.panel-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.panel-title-row .panel-title {
  margin-bottom: 0;
}

.labor-title {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed var(--line);
}

.cost-summary-line {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 8px;
  font-size: 13px;
  color: #606266;
}

.other-cost-one-row-table :deep(.el-table__header .cell) {
  padding: 6px 8px;
}

.cost-summary-line strong {
  font-size: 16px;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

.section-count {
  font-size: 12px;
  color: var(--muted);
  background: var(--panel);
  border-radius: 999px;
  padding: 2px 9px;
}

.soft-table {
  --el-table-border-color: #d0d7e2;
  --el-table-header-bg-color: #f7f9fc;
  --el-table-header-text-color: #64748b;
  --el-table-row-hover-bg-color: #f0f7ff;
  border-radius: 12px;
  overflow: hidden;
  border: none;
  box-shadow:
    0 0 0 1px rgba(15, 23, 42, 0.06),
    0 1px 2px rgba(15, 23, 42, 0.03),
    0 8px 24px rgba(15, 23, 42, 0.04);
}

.soft-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}

.soft-table :deep(.el-table__header-wrapper) {
  border-bottom: none;
  box-shadow: none !important;
}

.soft-table :deep(th.el-table__cell) {
  background: #f7f9fc !important;
  font-weight: 600;
  color: #64748b;
  font-size: 12px;
  letter-spacing: 0.04em;
  border-bottom: 1px solid #d0d7e2 !important;
  box-shadow: none !important;
}

.soft-table :deep(td.el-table__cell) {
  border-bottom: 1px solid #dce3ed !important;
  box-shadow: none !important;
}

.money {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: var(--ink);
}

.muted {
  color: var(--muted);
}

.detail-meta {
  margin-top: 0;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px 12px;
  align-content: start;
}

.detail-meta-row {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px;
  align-items: start;
  font-size: 13px;
  min-width: 0;
}

.detail-meta-row > span {
  color: var(--muted);
  font-weight: 600;
  line-height: 1.5;
}

.detail-meta-row > b {
  color: var(--ink);
  font-weight: 650;
  line-height: 1.5;
  word-break: break-all;
}

.detail-meta-row > b.detail-total-cost,
.detail-total-cost {
  color: var(--accent);
  font-weight: 750;
  font-variant-numeric: tabular-nums;
}

.detail-meta-quotes {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 2px;
  padding-top: 8px;
  border-top: 1px dashed var(--line);
}

.detail-quotes-heading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  width: 100%;
  color: var(--ink);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.12em;
  line-height: 1.2;
  text-align: center;
}

.detail-quotes-heading::before,
.detail-quotes-heading::after {
  content: '';
  flex: 1;
  max-width: 56px;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--line), transparent);
}

.detail-quotes-heading::before {
  background: linear-gradient(90deg, transparent, rgba(100, 116, 139, 0.45));
}

.detail-quotes-heading::after {
  background: linear-gradient(90deg, rgba(100, 116, 139, 0.45), transparent);
}

.detail-quotes-empty {
  display: block;
  text-align: center;
  color: var(--muted);
  font-weight: 500;
}

.quote-list {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.quote-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid var(--line);
}

.quote-customer {
  font-size: 13px;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.quote-value {
  color: var(--accent);
  font-size: 14px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.shoe-panel-body {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}

:deep(td.mat-image-col) {
  padding: 2px !important;
}

:deep(th.mat-image-col) {
  padding: 8px 2px !important;
}

:deep(td.mat-image-col .cell) {
  padding: 2px !important;
  line-height: 0;
  width: 100%;
}

:deep(th.mat-image-col .cell) {
  padding: 0 2px !important;
}

.product-thumb {
  width: 100%;
  aspect-ratio: 1 / 1;
  height: auto;
  display: block;
  margin: 0;
  border-radius: 4px;
}

.product-thumb :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.mat-image-empty {
  line-height: 1.45;
  display: inline-block;
}

.materials-panel {
  background: #fff;
}

@media (max-width: 1100px) {
  .detail-meta {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 960px) {
  .shoe-panel-body {
    grid-template-columns: 1fr;
  }

  .detail-meta {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>

<style scoped>
.detail-labor-groups {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  align-items: start;
}
.detail-labor-group {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  overflow: hidden;
  min-width: 0;
}
.detail-labor-group-head {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 6px 10px;
  background: #f8fafc;
  font-size: 12px;
  font-weight: 600;
}
.detail-labor-group-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  font-weight: 500;
  width: 100%;
}
.detail-labor-row {
  display: grid;
  gap: 2px;
  padding: 6px 10px;
  border-top: 1px solid var(--el-border-color-lighter);
  font-size: 13px;
}
.detail-labor-line {
  display: flex;
  align-items: baseline;
  gap: 4px;
  min-width: 0;
  width: 100%;
}
.detail-labor-name {
  flex: 1;
  min-width: 0;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.detail-labor-line .money {
  flex-shrink: 0;
  margin-left: auto;
  text-align: right;
}
.detail-price-history-icon {
  flex-shrink: 0;
  color: #64748b;
  cursor: help;
  margin-left: 2px;
  outline: none;
  vertical-align: middle;
}
.detail-price-history-icon:hover {
  color: var(--el-color-primary);
}
.detail-labor-unit {
  flex-shrink: 0;
  font-size: 12px;
  white-space: nowrap;
}
.detail-labor-note {
  margin-top: 6px;
  font-size: 12px;
}
.detail-labor-note-label {
  line-height: 1.4;
}
.detail-labor-note-body {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.45;
}
</style>

<style>
.dev-dialog.el-dialog {
  border-radius: 16px;
  overflow: hidden;
  background: #b8c2ce;
}
.dev-dialog .el-dialog__header {
  margin-right: 0;
  padding: 12px 14px 10px;
  border-bottom: none;
  background: #b8c2ce;
}
.dev-dialog .el-dialog__body {
  padding: 8px 10px 10px;
  background: #b8c2ce;
}
.dev-dialog .el-dialog__footer {
  padding: 10px 14px 14px;
  border-top: 1px solid #eef2f7;
  background: #b8c2ce;
}
.detail-price-history-popper {
  max-width: 320px;
  padding: 8px 10px !important;
}
.detail-price-history-tip-title {
  font-size: 12px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 6px;
}
.detail-price-history-tip-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 0;
  border-top: 1px solid #eef2f7;
  font-size: 12px;
  line-height: 1.4;
}
.detail-price-history-tip-row:first-of-type {
  border-top: none;
  padding-top: 0;
}
.detail-price-history-tip-price {
  font-weight: 600;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}
.detail-price-history-tip-meta {
  color: #64748b;
}
</style>
