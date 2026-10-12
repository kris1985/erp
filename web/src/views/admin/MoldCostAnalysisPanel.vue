<template>
  <div ref="tableHostRef">
    <el-table
      v-if="rows.length"
      ref="tableRef"
      class="mold-cost-table"
      :data="rows"
      stripe
      border
      style="width: 100%"
      :span-method="spanMethod"
      :max-height="tableMaxHeight"
      v-loading="loading"
      @header-dragend="onHeaderDragend"
    >
      <el-table-column label="楦" align="center">
        <el-table-column prop="last_code" label="型号" :width="colWidth('last_code', 100)" show-overflow-tooltip resizable>
          <template #default="{ row }">{{ text(row.last_code) }}</template>
        </el-table-column>
        <el-table-column prop="last_qty" label="数量" :width="colWidth('last_qty', 72)" align="right" resizable>
          <template #default="{ row }">{{ num(row.last_qty) }}</template>
        </el-table-column>
        <el-table-column prop="last_amount" label="金额" :width="colWidth('last_amount', 90)" align="right" resizable>
          <template #default="{ row }">{{ num(row.last_amount) }}</template>
        </el-table-column>
        <el-table-column prop="last_share" label="分摊" :width="colWidth('last_share', 100)" align="right" resizable>
          <template #default="{ row }">{{ text(row.last_share) }}</template>
        </el-table-column>
      </el-table-column>
      <el-table-column label="鞋底模具" align="center">
        <el-table-column prop="sole_code" label="型号" :width="colWidth('sole_code', 100)" show-overflow-tooltip resizable>
          <template #default="{ row }">{{ text(row.sole_code) }}</template>
        </el-table-column>
        <el-table-column prop="sole_qty" label="数量" :width="colWidth('sole_qty', 72)" align="right" resizable>
          <template #default="{ row }">{{ num(row.sole_qty) }}</template>
        </el-table-column>
        <el-table-column prop="sole_amount" label="金额" :width="colWidth('sole_amount', 90)" align="right" resizable>
          <template #default="{ row }">{{ num(row.sole_amount) }}</template>
        </el-table-column>
        <el-table-column prop="sole_share" label="分摊" :width="colWidth('sole_share', 100)" align="right" resizable>
          <template #default="{ row }">{{ text(row.sole_share) }}</template>
        </el-table-column>
      </el-table-column>
      <el-table-column label="鞋跟模具" align="center">
        <el-table-column prop="heel_code" label="型号" :width="colWidth('heel_code', 110)" show-overflow-tooltip resizable>
          <template #default="{ row }">{{ text(row.heel_code) }}</template>
        </el-table-column>
        <el-table-column prop="heel_qty" label="数量" :width="colWidth('heel_qty', 72)" align="right" resizable>
          <template #default="{ row }">{{ num(row.heel_qty) }}</template>
        </el-table-column>
        <el-table-column prop="heel_amount" label="金额" :width="colWidth('heel_amount', 90)" align="right" resizable>
          <template #default="{ row }">{{ num(row.heel_amount) }}</template>
        </el-table-column>
        <el-table-column prop="heel_share" label="分摊" :width="colWidth('heel_share', 100)" align="right" resizable>
          <template #default="{ row }">{{ text(row.heel_share) }}</template>
        </el-table-column>
      </el-table-column>
      <el-table-column label="刀模" align="center">
        <el-table-column prop="knife_code" label="型号" :width="colWidth('knife_code', 110)" show-overflow-tooltip resizable>
          <template #default="{ row }">{{ text(row.knife_code) }}</template>
        </el-table-column>
        <el-table-column prop="knife_qty" label="数量" :width="colWidth('knife_qty', 72)" align="right" resizable>
          <template #default="{ row }">{{ num(row.knife_qty) }}</template>
        </el-table-column>
        <el-table-column prop="knife_amount" label="金额" :width="colWidth('knife_amount', 90)" align="right" resizable>
          <template #default="{ row }">{{ num(row.knife_amount) }}</template>
        </el-table-column>
        <el-table-column prop="knife_share" label="分摊" :width="colWidth('knife_share', 100)" align="right" resizable>
          <template #default="{ row }">{{ text(row.knife_share) }}</template>
        </el-table-column>
      </el-table-column>
      <el-table-column label="鞋面" align="center">
        <el-table-column
          prop="factory_model"
          label="工厂型号"
          :width="colWidth('factory_model', 120)"
          show-overflow-tooltip
          resizable
        />
        <el-table-column prop="shipped_qty" label="出货数量" :width="colWidth('shipped_qty', 90)" align="right" resizable>
          <template #default="{ row }">{{ row.shipped_qty || '—' }}</template>
        </el-table-column>
      </el-table-column>
    </el-table>
    <div v-else-if="!loading" class="cost-empty muted">暂无模具成本数据。楦、鞋底模具、鞋跟模具或刀模至少有一项生产部到货金额时，才会按出货数量分摊。</div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const loading = ref(false)
const rows = ref<any[]>([])
const tableRef = ref()
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths('mold-cost-analysis', tableRef, {
  flexKey: 'factory_model',
  flexDefaultMin: 100,
  fitToContainer: true,
})
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()

const spanKeys = ['last_key', 'sole_key', 'heel_key']

function text(value: unknown) {
  const raw = String(value ?? '').trim()
  return raw || '—'
}

function num(value: unknown) {
  if (value === null || value === undefined || value === '') return '—'
  return value
}

function spanMethod({ rowIndex, column }: { rowIndex: number; column: { property?: string } }) {
  const prop = column.property || ''
  const group = prop.startsWith('last_') ? 'last_key' : prop.startsWith('sole_') ? 'sole_key' : prop.startsWith('heel_') ? 'heel_key' : ''
  if (!group || !spanKeys.includes(group)) return [1, 1]
  const key = rows.value[rowIndex]?.[group]
  if (rowIndex > 0 && rows.value[rowIndex - 1]?.[group] === key) return [0, 0]
  let span = 1
  while (rowIndex + span < rows.value.length && rows.value[rowIndex + span]?.[group] === key) span += 1
  return [span, 1]
}

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/mold-cost-analysis')
    rows.value = res.data?.rows || []
  } catch {
    rows.value = []
  } finally {
    loading.value = false
  }
  void Promise.resolve().then(() => {
    measureTableHeight()
    relayoutTable()
  })
}

onMounted(() => {
  void load()
})
</script>

<style scoped>
.mold-cost-table :deep(.el-table__header th) {
  text-align: center;
}
.mold-cost-table :deep(.el-table__cell) {
  vertical-align: middle;
}
.cost-empty {
  padding: 24px 8px;
  font-size: 13px;
}
</style>
