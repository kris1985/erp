<template>
  <div class="ps-panel">
    <p v-if="loading" class="ps-empty">正在读取生产单…</p>
    <p v-else-if="!sheet" class="ps-empty">生产单内容加载失败</p>
    <div v-else class="ps-sheet">
      <header class="ps-head">
        <div class="ps-head-text">
          <h2>{{ sheet.is_recut ? '生产单-补' : '生产单' }}</h2>
          <p>
            {{ sheet.is_recut ? '补单号' : '单号' }}
            <strong>{{ displayNo }}</strong>
            <span v-if="sheet.status === 'cancelled'" class="ps-void">已取消</span>
          </p>
          <p v-if="sheet.is_recut">
            原生产单号 <strong>{{ sheet.original_header_no || '—' }}</strong>
            <span>码数 {{ recutSizeLines.length }} 个</span>
          </p>
        </div>
        <div v-if="flowQrSrc" class="ps-qr">
          <img :src="flowQrSrc" alt="流转卡二维码" />
          <small>扫码报工</small>
        </div>
      </header>

      <table v-if="sheet.is_recut" class="ps-table ps-recut-meta">
        <tbody>
          <tr>
            <th>原生产单号</th>
            <td>{{ sheet.original_header_no || '—' }}</td>
            <th>补生产单号</th>
            <td>{{ displayNo }}</td>
          </tr>
          <tr>
            <th>工厂型号</th>
            <td>{{ sheet.product_code || '—' }}</td>
            <th>颜色</th>
            <td>{{ sheet.color_name || '—' }}</td>
          </tr>
          <tr>
            <th>工艺起始</th>
            <td>{{ sheet.recut_detail?.process_start_name || '—' }}</td>
            <th>补做到</th>
            <td>{{ sheet.recut_detail?.process_end_name || '—' }}</td>
          </tr>
        </tbody>
      </table>

      <div v-if="sheet.is_recut" class="ps-scroll">
        <div class="ps-section">报废码数</div>
        <table class="ps-table ps-recut-sizes">
          <thead>
            <tr>
              <th
                v-for="(line, index) in recutSizeLines"
                :key="`size-${line.defect_event_id || line.size_id || index}`"
                colspan="2"
              >
                {{ line.size_value || '—' }}
              </th>
              <th rowspan="2">数量</th>
            </tr>
            <tr>
              <template
                v-for="(line, index) in recutSizeLines"
                :key="`side-${line.defect_event_id || line.size_id || index}`"
              >
                <th>左</th>
                <th>右</th>
              </template>
            </tr>
          </thead>
          <tbody>
            <tr>
              <template
                v-for="(line, index) in recutSizeLines"
                :key="`qty-${line.defect_event_id || line.size_id || index}`"
              >
                <td>{{ Number(line.left_qty || 0) ? `${Number(line.left_qty)}只` : '' }}</td>
                <td>{{ Number(line.right_qty || 0) ? `${Number(line.right_qty)}只` : '' }}</td>
              </template>
              <td><strong>{{ recutTotalPieces }}只</strong></td>
            </tr>
          </tbody>
        </table>
      </div>

      <table v-else class="ps-table ps-attrs">
        <thead>
          <tr>
            <th>工厂型号</th>
            <th>图片</th>
            <th>颜色</th>
            <th>鞋面</th>
            <th>内里/垫脚</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td class="ps-code">{{ sheet.product_code || '—' }}</td>
            <td class="ps-photo-cell">
              <el-image
                v-if="sheet.product_image_url"
                :src="sheet.product_image_url"
                :preview-src-list="[sheet.product_image_url]"
                fit="contain"
                class="ps-photo"
                preview-teleported
              />
            </td>
            <td>{{ sheet.color_name || '—' }}</td>
            <td>{{ sharedFabric }}</td>
            <td>{{ sharedLining }}</td>
          </tr>
        </tbody>
      </table>

      <div v-if="!sheet.is_recut" class="ps-scroll">
        <table class="ps-table ps-orders" :style="{ minWidth: orderTableMinWidth }">
          <thead>
            <tr>
              <th rowspan="2">订单号</th>
              <th rowspan="2">客户</th>
              <th rowspan="2">品牌</th>
              <th rowspan="2">客户型号</th>
              <th :colspan="assortmentSizeLines.length || 1">配码</th>
              <th rowspan="2">箱数</th>
              <th rowspan="2">数量</th>
              <th rowspan="2">交货日期</th>
              <th rowspan="2">备注</th>
            </tr>
            <tr>
              <th v-for="(size, idx) in assortmentSizeLines" :key="size.size_id || size.id || idx">
                {{ size.size_value || '—' }}
              </th>
              <th v-if="!assortmentSizeLines.length">—</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, rowIndex) in orderSummaryRows" :key="row.sales_order_line_id || rowIndex">
              <td class="ps-code">{{ row.sales_order_no || '—' }}</td>
              <td>{{ row.customer_name || '—' }}</td>
              <td>{{ row.brand_name || '—' }}</td>
              <td>{{ row.customer_sku || '—' }}</td>
              <td v-for="(size, idx) in assortmentSizeLines" :key="size.size_id || size.id || idx">
                {{ assortmentQty(row, size) }}
              </td>
              <td v-if="!assortmentSizeLines.length">—</td>
              <td>{{ row.carton_qty || '—' }}</td>
              <td>{{ row.total_qty ?? 0 }}</td>
              <td>{{ row.delivery_date || '—' }}</td>
              <td class="ps-notes">{{ row.line_notes || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <template v-if="sizeMatchBlocks.length">
        <div class="ps-section">码数配套</div>
        <div v-for="block in sizeMatchBlocks" :key="block.key" class="ps-match">
          <div v-if="sizeMatchBlocks.length > 1 && block.sales_order_no" class="ps-match-order">
            {{ block.sales_order_no }}
          </div>
          <div class="ps-scroll">
            <table class="ps-table" :style="{ minWidth: `${88 + block.sizes.length * 56}px` }">
              <thead>
                <tr>
                  <th class="ps-kind">订单码数</th>
                  <th v-for="size in block.sizes" :key="size.key">{{ size.label }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="kind in block.kinds" :key="kind.key">
                  <th class="ps-kind">{{ kind.label }}</th>
                  <td v-for="size in block.sizes" :key="size.key">
                    {{ kind.map[size.label] || size.label }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>

      <div class="ps-section">{{ sheet.is_recut ? '本次补做材料' : '物料明细' }}</div>
      <div class="ps-scroll">
        <table class="ps-table ps-materials" :style="{ minWidth: materialTableMinWidth }">
          <thead>
            <tr>
              <th :rowspan="materialSizeColumns.length ? 2 : 1">序</th>
              <th :rowspan="materialSizeColumns.length ? 2 : 1">物料编码</th>
              <th :rowspan="materialSizeColumns.length ? 2 : 1">物料名称</th>
              <th :rowspan="materialSizeColumns.length ? 2 : 1">颜色</th>
              <th :rowspan="materialSizeColumns.length ? 2 : 1">每双用量</th>
              <th v-if="materialSizeColumns.length" :colspan="materialSizeColumns.length">码数</th>
              <th :rowspan="materialSizeColumns.length ? 2 : 1">{{ sheet.is_recut ? '本次需用' : '需求量' }}</th>
              <th :rowspan="materialSizeColumns.length ? 2 : 1">单位</th>
              <th :rowspan="materialSizeColumns.length ? 2 : 1">使用部门</th>
            </tr>
            <tr v-if="materialSizeColumns.length">
              <th v-for="size in materialSizeColumns" :key="size">{{ size }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(material, idx) in materialRows" :key="material.key || idx">
              <td>{{ idx + 1 }}</td>
              <td class="ps-code">{{ material.code || '—' }}</td>
              <td class="ps-name">
                {{ material.name || '—' }}
                <span v-if="material.customerSupplied">（客供）</span>
              </td>
              <td>{{ material.color || '—' }}</td>
              <td>{{ material.usageLabel }}</td>
              <td v-for="size in materialSizeColumns" :key="size">
                <template v-if="material.sizeQty[size] != null">
                  {{ formatMaterialQty(material.sizeQty[size]) }}
                  <div v-if="material.usageLabel === '按码' && material.sizeUsage[size] != null" class="ps-usage">
                    {{ formatMaterialQty(material.sizeUsage[size]) }}/双
                  </div>
                </template>
              </td>
              <td>{{ formatMaterialQty(material.totalQty) }}</td>
              <td>{{ material.unit || '—' }}</td>
              <td>{{ material.department || '—' }}</td>
            </tr>
            <tr v-if="!materialRows.length">
              <td :colspan="materialColumnCount" class="ps-blank">（无物料明细，请先维护产品 BOM）</td>
            </tr>
          </tbody>
        </table>
      </div>

      <template v-if="!sheet.is_recut">
        <div class="ps-section">客户做货要求</div>
        <table v-if="workReqBlocks.length" class="ps-table ps-reqs">
          <thead>
            <tr>
              <th>做货要求</th>
              <th>品牌图片</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="block in workReqBlocks" :key="block.key">
              <td class="ps-req-copy">
                <div v-if="block.sales_order_no" class="ps-req-order">销售单 {{ block.sales_order_no }}</div>
                <p>{{ block.notes || '（未填文字要求）' }}</p>
                <el-image
                  v-if="block.image_url"
                  :src="block.image_url"
                  :preview-src-list="[block.image_url]"
                  fit="contain"
                  class="ps-req-img"
                  preview-teleported
                />
              </td>
              <td>
                <div v-if="!brandImageLines(block).length" class="ps-blank">—</div>
                <div v-for="(line, lineIndex) in brandImageLines(block)" :key="lineIndex" class="ps-logos">
                  <div v-if="line.brand_name" class="ps-brand">{{ line.brand_name }}</div>
                  <el-image
                    v-for="(url, logoIndex) in line.brand_logo_urls"
                    :key="`${lineIndex}-${logoIndex}`"
                    :src="url"
                    :preview-src-list="line.brand_logo_urls"
                    :initial-index="logoIndex"
                    fit="contain"
                    class="ps-logo"
                    preview-teleported
                  />
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="ps-blank">本单未填做货要求</p>
      </template>

      <div class="ps-section">工艺路线</div>
      <table class="ps-table ps-route">
        <thead>
          <tr>
            <th class="ps-seq">序</th>
            <th>工序段</th>
            <th>工序</th>
            <th>工艺要求</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(p, idx) in processRows" :key="p.id || idx">
            <td>{{ idx + 1 }}</td>
            <td v-if="p.segmentRowspan" :rowspan="p.segmentRowspan">{{ p.segmentLabel }}</td>
            <td class="ps-name">{{ p.label || p.process_name || '—' }}</td>
            <td class="ps-notes">{{ p.requirement_note || '—' }}</td>
          </tr>
          <tr v-if="!processRows.length">
            <td colspan="4" class="ps-blank">（无工序，请先在产品工艺维护后同步到生产单）</td>
          </tr>
        </tbody>
      </table>

      <p v-if="sheet.is_recut" class="ps-foot">
        本单仅用于补做，须按左右脚及码数生产；完成至 {{ sheet.recut_detail?.process_end_name || '指定工序' }} 后并入原生产单。
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, toRef } from 'vue'
import { useProductionSheet } from '@/composables/useProductionSheet'

const props = defineProps<{
  sheet: any
  loading?: boolean
}>()

const detail = toRef(props, 'sheet')
const {
  displayNo,
  assortmentSizeLines,
  recutSizeLines,
  recutTotalPieces,
  sharedFabric,
  sharedLining,
  assortmentQty,
  orderSummaryRows,
  processRows,
  formatMaterialQty,
  materialSizeColumns,
  materialRows,
  materialColumnCount,
  sizeMatchBlocks,
  workReqBlocks,
  brandImageLines,
} = useProductionSheet(detail)

const flowQrSrc = computed(() => {
  const id = Number(props.sheet?.header_id || props.sheet?.id)
  if (!id) return ''
  return `/api/v1/executions/headers/${id}/flow-card/qr.png`
})

const orderTableMinWidth = computed(
  () => `${640 + Math.max(1, assortmentSizeLines.value.length) * 48}px`,
)
const materialTableMinWidth = computed(
  () => `${720 + materialSizeColumns.value.length * 56}px`,
)
</script>

<style scoped>
.ps-panel {
  color: #1c2b30;
  font-size: 13px;
}
.ps-empty,
.ps-blank {
  margin: 0;
  color: #7d8d92;
}
.ps-sheet {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.ps-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
  padding-right: 36px;
}
.ps-head h2 {
  margin: 0;
  color: #17343c;
  font-size: 22px;
  font-weight: 750;
  letter-spacing: 0.18em;
}
.ps-head p {
  margin: 6px 0 0;
  color: #5d7076;
}
.ps-head strong {
  margin-left: 6px;
  color: #17343c;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing: 0;
}
.ps-head span {
  margin-left: 12px;
}
.ps-void {
  padding: 1px 8px;
  border-radius: 999px;
  background: #f3f4f5;
  color: #6d7c81;
  font-size: 12px;
  letter-spacing: 0;
}
.ps-qr {
  flex: none;
  text-align: center;
}
.ps-qr img {
  width: 96px;
  height: 96px;
  object-fit: contain;
}
.ps-qr small {
  display: block;
  color: #6d7c81;
  font-size: 12px;
}
.ps-section {
  margin: 16px 0 8px;
  color: #17343c;
  font-size: 14px;
  font-weight: 700;
}
.ps-scroll {
  overflow-x: auto;
}
.ps-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: auto;
}
.ps-table th,
.ps-table td {
  border: 1px solid #d5dee1;
  padding: 7px 8px;
  text-align: center;
  vertical-align: middle;
  line-height: 1.4;
}
.ps-table th {
  background: #f4f7f8;
  color: #3e555c;
  font-weight: 650;
  white-space: nowrap;
}
.ps-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  white-space: nowrap;
}
.ps-name,
.ps-notes,
.ps-req-copy {
  text-align: left;
  white-space: pre-wrap;
  word-break: break-word;
}
.ps-attrs .ps-photo-cell {
  width: 108px;
}
.ps-photo {
  width: 88px;
  height: 72px;
}
.ps-recut-meta th {
  width: 14%;
  white-space: nowrap;
}
.ps-recut-meta td {
  width: 36%;
}
.ps-orders th,
.ps-orders td,
.ps-materials th,
.ps-materials td,
.ps-recut-sizes th,
.ps-recut-sizes td {
  white-space: nowrap;
}
.ps-orders .ps-notes,
.ps-materials .ps-name {
  white-space: pre-wrap;
  min-width: 96px;
}
.ps-usage {
  color: #6d7c81;
  font-size: 11px;
}
.ps-kind {
  width: 88px;
}
.ps-match + .ps-match {
  margin-top: 8px;
}
.ps-match-order {
  margin-bottom: 4px;
  font-weight: 650;
}
.ps-reqs th:first-child,
.ps-reqs td:first-child {
  width: 62%;
}
.ps-req-order {
  margin-bottom: 4px;
  color: #3e555c;
  font-weight: 650;
}
.ps-req-copy p {
  margin: 0;
  white-space: pre-wrap;
}
.ps-req-img {
  width: 160px;
  height: 120px;
  margin-top: 8px;
}
.ps-logos + .ps-logos {
  margin-top: 8px;
}
.ps-brand {
  margin-bottom: 4px;
  font-weight: 650;
}
.ps-logo {
  width: 72px;
  height: 72px;
  margin: 4px;
}
.ps-route .ps-seq {
  width: 48px;
}
.ps-route .ps-notes {
  min-width: 180px;
}
.ps-foot {
  margin: 12px 0 0;
  color: #5d7076;
  line-height: 1.5;
}
</style>
