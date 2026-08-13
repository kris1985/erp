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
        <span class="detail-dialog-title">产品详情</span>
      </div>
    </template>
    <div v-loading="loading" class="detail-body">
      <div v-if="detailRow" class="dev-layout">
        <section class="dev-panel shoe-panel">
          <div class="shoe-image-box">
            <el-image
              v-if="detailRow.image_url"
              :src="detailRow.image_url"
              fit="contain"
              class="shoe-preview"
              :preview-src-list="[detailRow.image_url]"
              preview-teleported
            />
            <div v-else class="shoe-preview empty">暂无产品图</div>
          </div>
          <div class="detail-meta">
            <div class="detail-meta-row">
              <span>产品编号</span>
              <b>{{ detailRow.product_code }}</b>
            </div>
            <div class="detail-meta-row">
              <span>颜色</span>
              <b>
                {{
                  detailRow.colors?.length
                    ? detailRow.colors.map((c: any) => c.name).join('、')
                    : '未绑颜色'
                }}
              </b>
            </div>
            <div class="detail-meta-row">
              <span>面料</span>
              <b>{{ detailRow.fabric || '—' }}</b>
            </div>
            <div class="detail-meta-row">
              <span>内里</span>
              <b>{{ detailRow.lining || '—' }}</b>
            </div>
            <div class="detail-meta-row">
              <span>订单量</span>
              <b>{{ detailRow.order_qty ?? 0 }}</b>
            </div>
            <div class="detail-meta-row">
              <span>录入日期</span>
              <b>{{ formatDate(detailRow.created_at) }}</b>
            </div>
            <div class="detail-meta-row">
              <span>总成本</span>
              <b class="detail-total-cost">¥{{ formatPrice(totalCost(detailRow)) }}</b>
            </div>
            <div class="detail-meta-row">
              <span>统一报价</span>
              <b>
                {{
                  detailRow.quote_price != null && detailRow.quote_price !== ''
                    ? `¥${formatPrice(detailRow.quote_price)}`
                    : '—'
                }}
              </b>
            </div>
            <div class="detail-meta-row detail-meta-quotes">
              <span class="detail-quotes-heading">客户报价</span>
              <div v-if="detailRow.quotes?.length" class="quote-list">
                <div v-for="q in detailRow.quotes" :key="q.id" class="quote-item">
                  <span class="quote-customer">{{ q.partner_short_name || q.partner_name }}</span>
                  <strong class="quote-value">¥{{ formatPrice(q.quote_price) }}</strong>
                </div>
              </div>
              <b v-else class="detail-quotes-empty">—</b>
            </div>
          </div>
        </section>

        <section class="dev-panel materials-panel">
          <div class="panel-title-row">
            <div class="panel-title">物料明细</div>
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
              resizable
            >
              <template #default="{ row: m }">
                <el-image
                  v-if="m.image_url"
                  :src="m.image_url"
                  :preview-src-list="[m.image_url]"
                  fit="contain"
                  class="material-thumb"
                  preview-teleported
                />
                <span v-else class="muted">—</span>
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
              column-key="consume_process"
              label="消耗工序"
              :width="colWidth4('consume_process', 110)"
              resizable
            >
              <template #default="{ row: m }">
                <span v-if="m.consume_process_name">{{ m.consume_process_name }}</span>
                <span v-else class="muted">未标注</span>
                <el-tag
                  v-if="m.consume_source === 'category'"
                  size="small"
                  type="info"
                  style="margin-left: 4px"
                >
                  分类
                </el-tag>
                <el-tag
                  v-else-if="m.consume_source === 'bom'"
                  size="small"
                  style="margin-left: 4px"
                >
                  覆盖
                </el-tag>
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
              <template #default="{ row: m }">{{ formatPrice(m.qty) }}</template>
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

          <div class="panel-title-row labor-title">
            <div class="panel-title">人工成本</div>
            <span class="section-count">{{ (detailRow.labors || []).length }} 道工序</span>
          </div>
          <el-table
            ref="laborsTableRef"
            border
            :data="detailRow.labors || []"
            size="small"
            class="soft-table"
            empty-text="暂无工序"
            @header-dragend="onHeaderDragend5"
          >
            <el-table-column
              column-key="process_name"
              label="工序"
              :min-width="flexColMinWidth5('process_name', 120)"
              show-overflow-tooltip
              resizable
            >
              <template #default="{ row: l }">{{ l.process_name || '—' }}</template>
            </el-table-column>
            <el-table-column column-key="type" label="类型" :width="colWidth5('type', 72)" resizable>
              <template #default="{ row: l }">
                <el-tag v-if="l.process_type === 'group'" size="small" type="warning">集体</el-tag>
                <span v-else class="muted">个人</span>
              </template>
            </el-table-column>
            <el-table-column
              column-key="price"
              label="价格"
              :width="colWidth5('price', 100)"
              align="right"
              resizable
            >
              <template #default="{ row: l }">
                <span class="money">¥{{ formatPrice(l.unit_price) }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div class="cost-summary-line">
            <span>人工成本</span>
            <strong>¥{{ formatPrice(detailRow.labor_cost) }}</strong>
          </div>

          <div class="panel-title-row labor-title">
            <div class="panel-title">其它成本</div>
            <span class="section-count">{{ (detailRow.other_costs || []).length }} 项</span>
          </div>
          <el-table
            ref="overheadTableRef"
            border
            :data="detailRow.other_costs || []"
            size="small"
            class="soft-table"
            empty-text="暂无其它成本"
            @header-dragend="onHeaderDragend6"
          >
            <el-table-column
              column-key="item"
              label="项目"
              :min-width="flexColMinWidth6('item', 140)"
              show-overflow-tooltip
              resizable
            >
              <template #default="{ row: o }">{{ o.name || '—' }}</template>
            </el-table-column>
            <el-table-column
              column-key="amount"
              label="金额"
              :width="colWidth6('amount', 100)"
              align="right"
              resizable
            >
              <template #default="{ row: o }">
                <span class="money">¥{{ formatPrice(o.amount) }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div class="cost-summary-line">
            <span>其它成本</span>
            <strong>¥{{ formatPrice(detailRow.other_cost) }}</strong>
          </div>
        </section>
      </div>
      <el-empty v-else-if="!loading" description="未找到产品" />
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'

const props = defineProps<{
  modelValue: boolean
  productId?: number | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const loading = ref(false)
const detailRow = ref<any>(null)

const materialsTableRef = ref()
const laborsTableRef = ref()
const overheadTableRef = ref()

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
const {
  colWidth: colWidth6,
  flexColMinWidth: flexColMinWidth6,
  onHeaderDragend: onHeaderDragend6,
  relayoutTable: relayoutOverhead,
} = useTableColWidths('own-products-detail-overhead', overheadTableRef, {
  flexKey: 'item',
  flexDefaultMin: 140,
  fitToContainer: true,
})

function formatDate(v?: string) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 10)
}

function formatPrice(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(2)
}

function totalCost(row: any) {
  return Number(row.material_cost || 0) + Number(row.labor_cost || 0) + Number(row.other_cost || 0)
}

async function loadProduct(id: number) {
  loading.value = true
  detailRow.value = null
  try {
    const res: any = await http.get(`/own-products/${id}`)
    detailRow.value = res.data
  } catch {
    detailRow.value = null
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.modelValue, props.productId] as const,
  ([visible, id]) => {
    if (visible && id) {
      void loadProduct(id)
    }
  },
)

function onOpened() {
  relayoutMaterials()
  relayoutLabors()
  relayoutOverhead()
}

function onClosed() {
  detailRow.value = null
}
</script>

<style scoped>
.detail-body {
  min-height: 240px;
}

.dev-layout {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 16px;
  min-height: 520px;
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
  padding: 14px 16px 16px;
  min-width: 0;
}

.panel-title {
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 12px;
  color: var(--ink);
}

.panel-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
}

.panel-title-row .panel-title {
  margin-bottom: 0;
}

.labor-title {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px dashed var(--line);
}

.cost-summary-line {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 10px;
  font-size: 13px;
  color: #606266;
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
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.detail-meta-row {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 10px;
  align-items: start;
  font-size: 13px;
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

.detail-meta-row > b.detail-total-cost {
  color: var(--accent);
  font-weight: 750;
  font-variant-numeric: tabular-nums;
}

.detail-meta-quotes {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 4px;
  padding-top: 12px;
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

.shoe-image-box {
  position: relative;
  width: 100%;
  border-radius: 12px;
}

.shoe-preview {
  width: 100%;
  aspect-ratio: 1;
  border-radius: 12px;
  border: 1px dashed var(--line);
  background: #fff;
  display: block;
}

.shoe-preview.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  font-size: 13px;
  background:
    repeating-linear-gradient(
      -45deg,
      #fff,
      #fff 8px,
      #f1f5f9 8px,
      #f1f5f9 16px
    );
}

.shoe-preview :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.materials-panel {
  background: #fff;
}

.material-thumb {
  width: 48px;
  height: 48px;
  border-radius: 6px;
  border: 1px solid var(--line);
  background: #fff;
  display: block;
}

.material-thumb :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

@media (max-width: 960px) {
  .dev-layout {
    grid-template-columns: 1fr;
  }
}
</style>
