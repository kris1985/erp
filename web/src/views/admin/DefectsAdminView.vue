<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">报废记录</h1>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
          <el-input
            v-model="filters.order_no"
            clearable
            placeholder="生产单号"
            style="width: 140px"
            @change="reload"
          />
          <el-select
            v-model="filters.responsible_worker_id"
            clearable
            filterable
            placeholder="责任员工"
            style="width: 150px"
            @change="reload"
          >
            <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
          <el-select
            v-model="filters.status"
            clearable
            placeholder="状态"
            style="width: 110px"
            @change="reload"
          >
            <el-option label="待确认" value="open" />
            <el-option label="已确认" value="closed" />
          </el-select>
          <el-date-picker
            v-model="filters.date_range"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            style="width: 240px"
            @change="reload"
          />
          <el-checkbox v-model="filters.pending_rework" @change="reload">未完成返修</el-checkbox>
          <el-button @click="load">刷新</el-button>
        </div>

        <div ref="tableHostRef" class="admin-table-host defects-table-host">
          <el-table
            ref="defectTableRef"
            class="defects-table"
            :data="displayRows"
            row-key="_rowKey"
            border
            fit
            table-layout="fixed"
            show-summary
            :summary-method="tableSummaries"
            :span-method="tableSpanMethod"
            :row-class-name="tableRowClassName"
            style="width: 100%"
            :max-height="tableMaxHeight"
            @header-dragend="onHeaderDragend"
          >
            <el-table-column
              prop="created_at"
              label="登记时间"
              :width="colWidth('created_at', 136)"
              resizable
              show-overflow-tooltip
            >
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column
              prop="order_no"
              label="生产单号"
              :width="colWidth('order_no', 120)"
              resizable
              show-overflow-tooltip
            />
            <el-table-column
              prop="product_code"
              label="工厂型号"
              :width="colWidth('product_code', 110)"
              resizable
              show-overflow-tooltip
            >
              <template #default="{ row }">{{ row.product_code || '—' }}</template>
            </el-table-column>
            <el-table-column
              column-key="product_image"
              label="图片"
              :width="colWidth('product_image', 64)"
              align="center"
              resizable
            >
              <template #default="{ row }">
                <el-image
                  v-if="row.product_image_url"
                  :src="row.product_image_url"
                  :preview-src-list="[row.product_image_url]"
                  fit="cover"
                  class="defect-product-thumb"
                  preview-teleported
                />
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column
              prop="color_name"
              label="颜色"
              :width="colWidth('color_name', 72)"
              resizable
              show-overflow-tooltip
            >
              <template #default="{ row }">{{ row.color_name || '—' }}</template>
            </el-table-column>
            <el-table-column
              prop="brand_name"
              label="品牌"
              :width="colWidth('brand_name', 80)"
              resizable
              show-overflow-tooltip
            >
              <template #default="{ row }">{{ row.brand_name || '—' }}</template>
            </el-table-column>
            <el-table-column
              v-for="size in listSizeHeaders"
              :key="`size-${size}`"
              :label="size"
              align="center"
            >
              <el-table-column
                :column-key="`size_${size}_left`"
                label="左"
                :width="colWidth(`size_${size}_left`, 44)"
                align="center"
                resizable
              >
                <template #default="{ row }">
                  {{ sizeSideQty(row, size, 'left') }}
                </template>
              </el-table-column>
              <el-table-column
                :column-key="`size_${size}_right`"
                label="右"
                :width="colWidth(`size_${size}_right`, 44)"
                align="center"
                resizable
              >
                <template #default="{ row }">
                  {{ sizeSideQty(row, size, 'right') }}
                </template>
              </el-table-column>
            </el-table-column>
            <el-table-column
              prop="qty"
              label="数量"
              :width="colWidth('qty', 56)"
              align="center"
              resizable
            >
              <template #default="{ row }">{{ row.qty ?? '—' }}</template>
            </el-table-column>
            <el-table-column
              column-key="warehouse"
              label="仓库"
              :width="colWidth('warehouse', 92)"
              align="center"
              resizable
            >
              <template #default="{ row }">
                <el-popover
                  v-if="row.id && row.header_id"
                  placement="bottom"
                  :width="640"
                  trigger="hover"
                  :show-after="200"
                  :hide-after="200"
                  popper-class="defect-warehouse-popper"
                  @show="loadWarehouseMaterials(row)"
                >
                  <template #reference>
                    <el-tag
                      size="small"
                      :type="warehouseStatusType(row)"
                      effect="plain"
                      class="defect-warehouse-tag"
                    >
                      {{ warehouseStatusLabel(row) }}
                    </el-tag>
                  </template>
                  <div
                    v-loading="isWarehouseLoading(row)"
                    class="defect-warehouse-detail"
                  >
                    <div class="defect-warehouse-head">
                      <strong>本次补做材料 · {{ row.order_no || '生产单' }}</strong>
                      <span v-if="warehouseKitOf(row)" class="muted">
                        {{ warehouseKitOf(row)?.qty }}只 ·
                        {{ warehouseKitOf(row)?.process_start_name || '首道' }} →
                        {{ warehouseKitOf(row)?.process_end_name || '发现工序' }}
                      </span>
                    </div>
                    <div v-if="!warehouseSegments(row).length" class="defect-warehouse-empty muted">
                      {{ isWarehouseLoading(row) ? '加载中…' : '暂无用料' }}
                    </div>
                    <section
                      v-for="segment in warehouseSegments(row)"
                      :key="segment.label"
                      class="defect-warehouse-segment"
                    >
                      <div class="defect-warehouse-segment-head">
                        <strong>{{ segment.label }}</strong>
                        <el-tag size="small" :type="segment.shortageCount ? 'danger' : 'success'" effect="plain">
                          {{ segment.shortageCount ? `缺 ${segment.shortageCount} 项` : '齐套' }}
                        </el-tag>
                      </div>
                      <el-table
                        :data="segment.lines"
                        size="small"
                        border
                        :row-class-name="warehouseMaterialRowClass"
                      >
                        <el-table-column prop="supplier_product_code" label="物料" min-width="105" show-overflow-tooltip />
                        <el-table-column prop="supplier_product_name" label="名称" min-width="120" show-overflow-tooltip />
                        <el-table-column label="尺码" width="58" align="center">
                          <template #default="{ row: material }">{{ material.size_value || '—' }}</template>
                        </el-table-column>
                        <el-table-column label="补做需用" width="82" align="right">
                          <template #default="{ row: material }">{{ formatMaterialQty(material.required_qty) }}</template>
                        </el-table-column>
                        <el-table-column label="可用" width="72" align="right">
                          <template #default="{ row: material }">{{ formatMaterialQty(material.available_qty) }}</template>
                        </el-table-column>
                        <el-table-column label="缺口" width="72" align="right">
                          <template #default="{ row: material }">
                            <strong :class="Number(material.shortage_qty) > 0 ? 'shortage-text' : 'muted'">
                              {{ formatMaterialQty(material.shortage_qty) }}
                            </strong>
                          </template>
                        </el-table-column>
                      </el-table>
                    </section>
                  </div>
                </el-popover>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column
              prop="found_process_name"
              label="发现工序"
              :width="colWidth('found_process_name', 80)"
              resizable
              show-overflow-tooltip
            >
              <template #default="{ row }">{{ row.found_process_name || '—' }}</template>
            </el-table-column>
            <el-table-column
              prop="loss_amount"
              label="损失金额"
              :width="colWidth('loss_amount', 92)"
              align="right"
              resizable
            >
              <template #default="{ row }">
                <el-tooltip
                  :content="`材料 ${formatMoney(row.material_loss_amount)} · 工资 ${formatMoney(row.labor_loss_amount)}`"
                  placement="top"
                >
                  <span>{{ formatMoney(row.loss_amount) }}</span>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column
              column-key="company_loss"
              label="公司承担"
              :width="colWidth('company_loss', 100)"
              align="right"
              resizable
              show-overflow-tooltip
            >
              <template #default="{ row }">{{ companyLossText(row) }}</template>
            </el-table-column>
            <el-table-column
              column-key="responsibility_workers"
              label="责任人"
              :width="colWidth('responsibility_workers', 90)"
              resizable
              show-overflow-tooltip
            >
              <template #default="{ row }">
                {{ row._responsibility.name }}
              </template>
            </el-table-column>
            <el-table-column
              column-key="responsibility_loss"
              label="分担损失"
              :width="colWidth('responsibility_loss', 90)"
              align="right"
              resizable
            >
              <template #default="{ row }">
                {{ row._responsibility.amount }}
              </template>
            </el-table-column>
            <el-table-column
              prop="status"
              label="状态"
              :width="colWidth('status', 72)"
              align="center"
              resizable
            >
              <template #default="{ row }">{{ row.status === 'closed' ? '已确认' : '待确认' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="56" align="center" :resizable="false">
              <template #default="{ row }">
                <el-dropdown trigger="click" @command="handleDefectAction(row, $event)">
                  <el-button
                    link
                    class="defect-more-button"
                    :loading="recutPrintingId === Number(row.id)"
                    aria-label="更多操作"
                  >
                    ···
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item v-if="row.disposition === 'scrap' && row.replacement_source !== 'subcontract'" command="print">
                        打印生产单-补
                      </el-dropdown-item>
                      <el-dropdown-item command="edit">编辑</el-dropdown-item>
                      <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="admin-pagination">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            background
            layout="total, sizes, prev, pager, next"
            :total="total"
            :page-sizes="[10, 20, 50]"
            @current-change="load"
            @size-change="
              () => {
                page = 1
                load()
              }
            "
          />
        </div>
    </div>

    <el-dialog v-model="editVisible" title="编辑报废记录" width="760px">
      <el-form v-loading="editLoading" label-width="88px">
        <el-form-item label="生产单号">
          <el-input :model-value="editForm.order_no" disabled />
        </el-form-item>
        <el-form-item label="图片">
          <div class="edit-photo-list">
            <div v-for="(url, index) in editForm.photo_urls" :key="url" class="edit-photo-item">
              <el-image :src="url" :preview-src-list="editForm.photo_urls" fit="cover" />
              <button type="button" @click="editForm.photo_urls.splice(index, 1)">×</button>
            </div>
            <label class="edit-photo-add">
              <input type="file" accept="image/*" multiple @change="uploadEditPhotos" />
              <span>{{ editPhotoUploading ? '上传中…' : '+ 添加' }}</span>
            </label>
          </div>
        </el-form-item>
        <el-form-item label="品牌">
          <el-input v-model="editForm.brand_name" maxlength="100" />
        </el-form-item>
        <el-form-item label="发现工序" required>
          <el-select
            v-model="editForm.found_process_id"
            filterable
            style="width: 100%"
            :disabled="editForm.responsible_party_type === 'subcontractor'"
            @change="refreshEditLossQuote"
          >
            <el-option v-for="p in processes" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
          <span v-if="editForm.responsible_party_type === 'subcontractor'" class="muted" style="margin-left: 10px">外发厂报废默认外发第一道工序</span>
        </el-form-item>
        <el-form-item label="码数数量" required>
          <el-table :data="editForm.lines" border size="small" style="width: 100%">
            <el-table-column label="码数" min-width="120">
              <template #default="{ row }">
                <el-select v-model="row.size_id" filterable style="width: 100%">
                  <el-option v-for="size in editSizeOptions" :key="size.size_id" :label="size.size_value" :value="size.size_id" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="左脚" width="110" align="center">
              <template #default="{ row }"><el-input-number v-model="row.left_qty" :min="0" :precision="0" :controls="false" /></template>
            </el-table-column>
            <el-table-column label="右脚" width="110" align="center">
              <template #default="{ row }"><el-input-number v-model="row.right_qty" :min="0" :precision="0" :controls="false" /></template>
            </el-table-column>
            <el-table-column label="数量" width="70" align="center">
              <template #default="{ row }">{{ Number(row.left_qty || 0) + Number(row.right_qty || 0) }}</template>
            </el-table-column>
            <el-table-column label="损失金额" width="130" align="right">
              <template #default="{ row }">{{ formatMoney(calculatedEditLineLoss(row)) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="64" align="center">
              <template #default="{ row }">
                <el-button v-if="!row.id" link type="danger" @click="removeNewEditSize(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="edit-size-actions">
            <el-button :disabled="editForm.lines.length >= editSizeOptions.length" @click="addEditSize">+ 增加码数</el-button>
            <span class="edit-loss-total">总数量 {{ editTotalQty }}　总损失 {{ formatMoney(editTotalLoss) }}</span>
          </div>
        </el-form-item>
        <el-form-item label="责任人">
          <el-radio-group v-model="editForm.responsible_party_type" @change="changeEditResponsibleParty">
            <el-radio-button value="employee">员工</el-radio-button>
            <el-radio-button value="subcontractor" :disabled="!editSubcontractOrders.length">外发厂</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="editForm.responsible_party_type === 'subcontractor' && editSubcontractOrders.length" label="外加工厂" required>
          <el-select v-model="editSubcontractPartnerId" filterable style="width: 100%" @change="changeEditSubcontractPartner">
            <el-option v-for="partner in editSubcontractPartners" :key="partner.id" :label="partner.name" :value="partner.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="editForm.responsible_party_type === 'subcontractor' && editSubcontractOrders.length" label="外发单" required>
          <el-select v-model="editForm.subcontract_order_id" filterable style="width: 100%" @change="applyEditFactoryProcess">
            <el-option
              v-for="order in editSubcontractOrdersForPartner"
              :key="order.id"
              :label="`${order.subcontract_no} · ${order.total_qty || 0}`"
              :value="order.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="公司承担">
          <el-input-number v-model="editForm.company_amount" :min="0" :precision="2" :controls="false" />
        </el-form-item>
        <el-form-item v-if="editForm.responsible_party_type === 'subcontractor'" label="外发厂承担">
          <strong>{{ formatMoney(Math.max(0, editTotalLoss - Number(editForm.company_amount || 0))) }}</strong>
        </el-form-item>
        <el-form-item v-else label="责任员工">
          <div class="edit-responsibilities">
            <div v-for="(item, index) in editForm.responsibilities" :key="item.key" class="edit-responsibility-row">
              <el-select v-model="item.worker_id" filterable placeholder="选择人员">
                <el-option v-for="worker in workers" :key="worker.id" :label="worker.name" :value="worker.id" />
              </el-select>
              <span class="edit-auto-allocation">自动分摊 {{ formatMoney(editResponsibilityAmount(index)) }}</span>
              <el-button link type="danger" @click="editForm.responsibilities.splice(index, 1)">删除</el-button>
            </div>
            <el-button @click="addEditResponsibility">+ 选择责任人</el-button>
            <span :class="['edit-allocation-total', { invalid: !editAllocationBalanced }]">分摊合计 {{ formatMoney(editAllocationTotal) }}</span>
          </div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editForm.note" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" :disabled="editLoading || editPhotoUploading" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const defectTableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, onHeaderDragend } = useTableColWidths('defects-list', defectTableRef, {
  flexKey: 'responsibility_workers',
  flexDefaultMin: 120,
  fitToContainer: true,
})

const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const workers = ref<any[]>([])
const processes = ref<any[]>([])
const emptySummary = () => ({ total_qty: 0, total_loss_amount: 0, company_loss_amount: 0, employee_loss_amount: 0 })
const summary = ref(emptySummary())
const filters = reactive({
  order_no: '',
  responsible_worker_id: null as number | null,
  status: '',
  pending_rework: false,
  date_range: [] as string[],
})
const editVisible = ref(false)
const editSaving = ref(false)
const editLoading = ref(false)
const editPhotoUploading = ref(false)
const recutPrintingId = ref<number | null>(null)
const warehouseKitCache = ref<Record<string, any>>({})
const warehouseLoadingKeys = ref<string[]>([])
const editForm = reactive({
  id: 0,
  order_no: '',
  header_id: null as number | null,
  brand_name: '',
  defect_type: '',
  scrap_source: 'internal',
  subcontract_order_id: null as number | null,
  responsible_party_type: 'employee' as 'employee' | 'subcontractor',
  replacement_source: 'internal',
  found_process_id: null as number | null,
  photo_urls: [] as string[],
  lines: [] as Array<{ id: number | null; size_id: number | null; size_value: string; left_qty: number; right_qty: number; loss_amount: number }>,
  company_amount: 0,
  responsibilities: [] as Array<{ key: number; worker_id: number | null }>,
  note: '',
})
const editSizeOptions = ref<any[]>([])
const editLossQuote = ref<any>(null)
const editSubcontractOrders = ref<any[]>([])
const editSubcontractPartnerId = ref<number | null>(null)
const editSubcontractPartners = computed(() => {
  const seen = new Map<number, { id: number; name: string }>()
  for (const row of editSubcontractOrders.value) {
    const partnerId = Number(row.partner_id || 0)
    if (!partnerId || seen.has(partnerId)) continue
    seen.set(partnerId, { id: partnerId, name: row.partner_name || `工厂${partnerId}` })
  }
  return [...seen.values()]
})
const editSubcontractOrdersForPartner = computed(() => {
  if (!editSubcontractPartnerId.value) return []
  return editSubcontractOrders.value.filter((row: any) => Number(row.partner_id) === Number(editSubcontractPartnerId.value))
})
let editResponsibilityKey = 0
const editTotalQty = computed(() => editForm.lines.reduce((sum, line) => sum + Number(line.left_qty || 0) + Number(line.right_qty || 0), 0))
function calculatedEditLineLoss(line: { size_id: number | null; left_qty: number; right_qty: number }) {
  const qty = Number(line.left_qty || 0) + Number(line.right_qty || 0)
  if (editForm.responsible_party_type === 'subcontractor') {
    const order = editSubcontractOrders.value.find((item: any) => Number(item.id) === Number(editForm.subcontract_order_id))
    const unit = Number(order?.material_unit_price || 0) / 2
    return Number((qty * unit).toFixed(2))
  }
  const sizeQuote = editLossQuote.value?.by_size?.[String(line.size_id)] || {}
  const material = Number(sizeQuote.material_per_piece ?? editLossQuote.value?.material_per_piece ?? 0)
  const labor = editForm.scrap_source === 'internal'
    ? Number(editLossQuote.value?.labor_per_piece || 0)
    : Number(editLossQuote.value?.labor_before_process_per_piece || 0)
  return Number((qty * (material + labor)).toFixed(2))
}
const editTotalLoss = computed(() => editForm.lines.reduce((sum, line) => sum + calculatedEditLineLoss(line), 0))
const editAllocationTotal = computed(() => {
  if (editForm.responsible_party_type === 'subcontractor') {
    return Number(editForm.company_amount || 0) + Math.max(0, editTotalLoss.value - Number(editForm.company_amount || 0))
  }
  const company = Number(editForm.company_amount || 0)
  return company + (editForm.responsibilities.length ? Math.max(0, editTotalLoss.value - company) : 0)
})
const editAllocationBalanced = computed(() => {
  const company = Number(editForm.company_amount || 0)
  const remaining = editTotalLoss.value - company
  if (company < 0 || remaining < -0.01) return false
  if (editForm.responsible_party_type === 'subcontractor' || remaining <= 0.01) return true
  return editForm.responsibilities.length > 0 && editForm.responsibilities.every(item => item.worker_id)
})
function editResponsibilityAmount(index: number) {
  const count = editForm.responsibilities.length
  if (!count) return 0
  const remainingCents = Math.max(0, Math.round((editTotalLoss.value - Number(editForm.company_amount || 0)) * 100))
  const base = Math.floor(remainingCents / count)
  return (base + (index < remainingCents % count ? 1 : 0)) / 100
}
/** 当前列表出现的码数，用作两行表头第一行 */
const listSizeHeaders = computed(() => {
  const set = new Set<string>()
  for (const row of rows.value) {
    if (row.size_value == null || row.size_value === '') continue
    set.add(String(row.size_value))
  }
  return [...set].sort((a, b) => {
    const na = Number(a)
    const nb = Number(b)
    if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb
    return a.localeCompare(b, 'zh')
  })
})

const displayRows = computed(() => rows.value.flatMap((row, groupIndex) => {
  const responsibilities = responsibilityRows(row)
  return responsibilities.map((responsibility, index) => ({
    ...row,
    _rowKey: `${row.id}-${index}`,
    _responsibility: responsibility,
    _isFirst: index === 0,
    _span: responsibilities.length,
    _groupIndex: groupIndex,
  }))
}))

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value).slice(0, 16).replace('T', ' ')
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function formatMoney(value: number | string | null | undefined) {
  const n = Number(value || 0)
  if (!Number.isFinite(n)) return '—'
  return `¥${n.toFixed(2)}`
}

function sizeSideQty(row: any, size: string, side: 'left' | 'right') {
  if (String(row.size_value ?? '') !== size) return ''
  return Number(side === 'left' ? row.left_qty || 0 : row.right_qty || 0)
}

function companyLossText(row: any) {
  const percent = Number(row.company_share_percent ?? 100)
  const amount =
    row.company_loss_amount != null
      ? Number(row.company_loss_amount)
      : (Number(row.loss_amount || 0) * percent) / 100
  if (!Number.isFinite(amount)) return '—'
  return formatMoney(amount)
}

function warehouseCacheKey(row: any) {
  return row?.id ? `defect:${Number(row.id)}` : ''
}

function warehouseKitOf(row: any) {
  return warehouseKitCache.value[warehouseCacheKey(row)] || null
}

function isWarehouseLoading(row: any) {
  return warehouseLoadingKeys.value.includes(warehouseCacheKey(row))
}

function warehouseStatusLabel(row: any) {
  if (isWarehouseLoading(row)) return '加载中'
  const kit = warehouseKitOf(row)
  if (!kit) return '查看用料'
  if (kit.empty_bom) return '无用料'
  return kit.kit_ok ? '齐套' : '缺材料'
}

function warehouseStatusType(row: any): 'info' | 'success' | 'danger' {
  const kit = warehouseKitOf(row)
  if (!kit || kit.empty_bom) return 'info'
  return kit.kit_ok ? 'success' : 'danger'
}

function warehouseSegments(row: any) {
  const lines = Array.isArray(warehouseKitOf(row)?.lines) ? warehouseKitOf(row).lines : []
  const grouped = new Map<string, any[]>()
  for (const line of lines) {
    const label = String(line.consume_segment_name || '').trim() || '未分段'
    if (!grouped.has(label)) grouped.set(label, [])
    grouped.get(label)!.push(line)
  }
  return [...grouped.entries()].map(([label, segmentLines]) => ({
    label,
    shortageCount: segmentLines.filter(line => Number(line.shortage_qty) > 0).length,
    lines: [...segmentLines].sort((a, b) => {
      const shortageOrder = Number(b.shortage_qty || 0) - Number(a.shortage_qty || 0)
      return shortageOrder || Number(a.sort_order || 0) - Number(b.sort_order || 0)
    }),
  }))
}

function warehouseMaterialRowClass({ row }: { row: any }) {
  return Number(row.shortage_qty) > 0 ? 'defect-material-shortage' : ''
}

function formatMaterialQty(value: unknown) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return Number.isInteger(number) ? String(number) : number.toFixed(4).replace(/\.?0+$/, '')
}

async function loadWarehouseMaterials(row: any, silent = false) {
  const key = warehouseCacheKey(row)
  if (!key || warehouseKitCache.value[key] || warehouseLoadingKeys.value.includes(key)) return
  warehouseLoadingKeys.value = [...warehouseLoadingKeys.value, key]
  try {
    const res: any = await http.get(`/defect-events/${Number(row.id)}/materials`)
    warehouseKitCache.value = { ...warehouseKitCache.value, [key]: res.data || {} }
  } catch (e: any) {
    if (!silent) ElMessage.error(e?.response?.data?.detail || e?.message || '加载用料失败')
  } finally {
    warehouseLoadingKeys.value = warehouseLoadingKeys.value.filter(item => item !== key)
  }
}

async function preloadWarehouseMaterials(sourceRows: any[]) {
  const pending = sourceRows.filter(row => row?.id && row?.header_id)
  for (let index = 0; index < pending.length; index += 6) {
    await Promise.allSettled(pending.slice(index, index + 6).map(row => loadWarehouseMaterials(row, true)))
  }
}

function tableSummaries({ columns }: { columns: any[] }) {
  return columns.map((column, index) => {
    const key = column.property || column.columnKey
    if (index === 0) return '汇总'
    if (key === 'qty') return summary.value.total_qty
    if (key === 'loss_amount') return formatMoney(summary.value.total_loss_amount)
    if (key === 'company_loss') return formatMoney(summary.value.company_loss_amount)
    if (key === 'responsibility_loss') return formatMoney(summary.value.employee_loss_amount)
    return ''
  })
}

function tableSpanMethod({ row, column }: { row: any; column: any }) {
  const key = column.property || column.columnKey
  if (key === 'responsibility_workers' || key === 'responsibility_loss') return [1, 1]
  return row._isFirst ? [row._span, 1] : [0, 0]
}

function tableRowClassName({ row }: { row: any }) {
  return row._groupIndex % 2 === 1 ? 'defect-group-stripe' : ''
}

function responsibilityRows(row: any) {
  const items = (row.responsibilities || []).map((item: any) => ({
    name: item.partner_name || item.worker_name || (item.party_type === 'subcontractor' ? '外发厂' : '员工'),
    amount: formatMoney(item.deduction_amount),
  }))
  if (items.length) return items
  if (row.responsible_party_type === 'subcontractor') {
    return [{
      name: row.subcontract_partner_name || '外发厂',
      amount: formatMoney(row.factory_loss_amount ?? row.employee_loss_amount),
    }]
  }
  if (row.responsible_worker_name) {
    const amount = Number(row.employee_loss_amount ?? row.loss_amount ?? 0)
    return [{ name: row.responsible_worker_name, amount: formatMoney(amount) }]
  }
  return [{ name: '—', amount: '—' }]
}

function reload() {
  page.value = 1
  void load()
}

async function openEdit(row: any) {
  editForm.id = Number(row.id)
  editVisible.value = true
  editLoading.value = true
  try {
    const res: any = await http.get(`/defect-events/${row.id}`)
    const detail = res.data || row
    const items = detail.registration_items?.length ? detail.registration_items : [detail]
    editForm.order_no = detail.order_no || ''
    editForm.header_id = detail.header_id ? Number(detail.header_id) : null
    editForm.brand_name = detail.brand_name || ''
    editForm.scrap_source = detail.scrap_source || 'internal'
    editForm.subcontract_order_id = detail.subcontract_order_id ? Number(detail.subcontract_order_id) : null
    editForm.responsible_party_type = detail.responsible_party_type === 'subcontractor' ? 'subcontractor' : 'employee'
    editForm.replacement_source = detail.replacement_source || 'internal'
    editForm.found_process_id = detail.found_process_id ? Number(detail.found_process_id) : null
    editForm.photo_urls = [...(detail.photo_urls || [])]
    editForm.note = detail.note || ''
    editForm.lines = items.map((item: any) => ({
      id: Number(item.id),
      size_id: item.size_id ? Number(item.size_id) : null,
      size_value: item.size_value || '',
      left_qty: Number(item.left_qty || 0),
      right_qty: Number(item.right_qty || 0),
      loss_amount: Number(item.loss_amount || 0),
    }))
    const totalLoss = editForm.lines.reduce((sum, line) => sum + line.loss_amount, 0)
    editForm.company_amount = Number((totalLoss * Number(detail.company_share_percent ?? 100) / 100).toFixed(2))
    editForm.responsibilities = (detail.responsibilities || [])
      .filter((item: any) => item.party_type !== 'subcontractor' && item.worker_id)
      .map((item: any) => ({
        key: ++editResponsibilityKey,
        worker_id: Number(item.worker_id),
      }))
    editSizeOptions.value = editForm.lines.map(line => ({ size_id: line.size_id, size_value: line.size_value }))
    editSubcontractOrders.value = []
    editSubcontractPartnerId.value = detail.subcontract_partner_id ? Number(detail.subcontract_partner_id) : null
    if (editForm.header_id) {
      const headerRes: any = await http.get(`/executions/headers/${editForm.header_id}`)
      editSizeOptions.value = headerRes.data?.size_lines || editSizeOptions.value
      const orderRes: any = await http.get('/subcontract-orders', {
        params: { header_id: editForm.header_id, page_size: 50 },
      })
      editSubcontractOrders.value = (orderRes.data?.items || []).filter((item: any) => item.status !== 'cancelled')
      if (editForm.subcontract_order_id) {
        const linked = editSubcontractOrders.value.find((item: any) => Number(item.id) === Number(editForm.subcontract_order_id))
        if (linked) editSubcontractPartnerId.value = Number(linked.partner_id)
      }
    }
    await refreshEditLossQuote()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载报废记录失败')
    editVisible.value = false
  } finally { editLoading.value = false }
}

async function refreshEditLossQuote() {
  if (!editForm.header_id || !editForm.found_process_id) {
    editLossQuote.value = null
    return
  }
  const routeRes: any = await http.get(`/executions/headers/${editForm.header_id}/processes`)
  const route = (routeRes.data?.items || []).find(
    (item: any) => Number(item.process_id) === Number(editForm.found_process_id),
  )
  if (!route) return
  const quoteRes: any = await http.get('/defect-events/loss-quote', {
    params: { header_id: editForm.header_id, order_process_id: route.id },
  })
  editLossQuote.value = quoteRes.data || null
}

function changeEditResponsibleParty() {
  if (editForm.responsible_party_type === 'subcontractor') {
    editForm.scrap_source = 'subcontract'
    editForm.responsibilities = []
    editForm.company_amount = 0
    if (!editForm.subcontract_order_id && editSubcontractOrders.value.length) {
      const first = editSubcontractOrders.value[0]
      editSubcontractPartnerId.value = Number(first.partner_id)
      editForm.subcontract_order_id = Number(first.id)
    }
    applyEditFactoryProcess()
  } else {
    editForm.scrap_source = 'internal'
    editForm.replacement_source = 'internal'
    editForm.subcontract_order_id = null
    editSubcontractPartnerId.value = null
    editForm.responsibilities = []
    editForm.company_amount = editTotalLoss.value
  }
}

function changeEditSubcontractPartner() {
  const orders = editSubcontractOrdersForPartner.value
  editForm.subcontract_order_id = orders.length === 1 ? Number(orders[0].id) : null
  applyEditFactoryProcess()
}

function applyEditFactoryProcess() {
  if (editForm.responsible_party_type !== 'subcontractor') return
  const order = editSubcontractOrders.value.find((item: any) => Number(item.id) === Number(editForm.subcontract_order_id))
  if (order?.process_id) editForm.found_process_id = Number(order.process_id)
}

function addEditResponsibility() {
  editForm.responsibilities.push({ key: ++editResponsibilityKey, worker_id: null })
}

function addEditSize() {
  const used = new Set(editForm.lines.map(line => Number(line.size_id || 0)))
  const option = editSizeOptions.value.find((size: any) => !used.has(Number(size.size_id)))
  if (!option) return
  editForm.lines.push({
    id: null,
    size_id: Number(option.size_id),
    size_value: option.size_value || '',
    left_qty: 0,
    right_qty: 0,
    loss_amount: 0,
  })
}

function removeNewEditSize(row: { id: number | null }) {
  if (row.id) return
  editForm.lines = editForm.lines.filter(line => line !== row)
}

async function uploadEditPhotos(event: Event) {
  const input = event.target as HTMLInputElement
  const files = [...(input.files || [])]
  if (!files.length) return
  editPhotoUploading.value = true
  try {
    for (const file of files) {
      const data = new FormData()
      data.append('file', file)
      const res: any = await http.post('/defect-events/upload-photo', data)
      if (res.data?.url) editForm.photo_urls.push(res.data.url)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '图片上传失败')
  } finally {
    editPhotoUploading.value = false
    input.value = ''
  }
}

function editAllocationPercentages() {
  const total = Math.round(editTotalLoss.value * 100)
  if (total <= 0) return { company: 100, workers: [] as Array<{ worker_id: number; share_percent: number }> }
  const company = Math.min(100, Math.max(0, Math.round(Number(editForm.company_amount || 0) * 10000 / total)))
  if (editForm.responsible_party_type === 'subcontractor') {
    return { company, workers: [] }
  }
  const workerIds = editForm.responsibilities.map(item => Number(item.worker_id || 0)).filter(Boolean)
  const employeeShare = 100 - company
  const baseShare = workerIds.length ? Math.floor(employeeShare / workerIds.length) : 0
  const remainder = workerIds.length ? employeeShare % workerIds.length : 0
  return {
    company,
    workers: workerIds.map((workerId, index) => ({
      worker_id: workerId,
      share_percent: baseShare + (index < remainder ? 1 : 0),
    })),
  }
}

async function saveEdit() {
  if (!editForm.found_process_id) {
    ElMessage.warning('请选择发现工序')
    return
  }
  if (!editForm.lines.length || editForm.lines.some(line => !line.size_id || Number(line.left_qty || 0) + Number(line.right_qty || 0) <= 0)) {
    ElMessage.warning('每个码数的左右脚合计必须大于 0')
    return
  }
  if (new Set(editForm.lines.map(line => line.size_id)).size !== editForm.lines.length) {
    ElMessage.warning('同一码数不能重复')
    return
  }
  if (Number(editForm.company_amount || 0) > editTotalLoss.value) {
    ElMessage.warning('公司承担不能大于总损失')
    return
  }
  if (editForm.responsible_party_type === 'employee' && editForm.responsibilities.some(item => !item.worker_id)) {
    ElMessage.warning('请选择责任人')
    return
  }
  if (editForm.responsible_party_type === 'employee' && Number(editForm.company_amount || 0) < editTotalLoss.value && !editForm.responsibilities.length) {
    ElMessage.warning('请选择责任人')
    return
  }
  const responsibilityWorkerIds = editForm.responsibilities.map(item => item.worker_id).filter(Boolean)
  if (new Set(responsibilityWorkerIds).size !== responsibilityWorkerIds.length) {
    ElMessage.warning('责任人不能重复')
    return
  }
  if (
    editForm.responsible_party_type === 'subcontractor'
    && editSubcontractOrders.value.length
    && !editForm.subcontract_order_id
  ) {
    ElMessage.warning('请选择对应的外发单')
    return
  }
  editSaving.value = true
  try {
    const allocation = editAllocationPercentages()
    const existingLines = editForm.lines.filter(line => line.id)
    const newLines = editForm.lines.filter(line => !line.id)
    await Promise.all(existingLines.map(line => http.patch(`/defect-events/${line.id}`, {
      brand_name: editForm.brand_name,
      found_process_id: editForm.found_process_id,
      size_id: line.size_id,
      left_qty: Number(line.left_qty || 0),
      right_qty: Number(line.right_qty || 0),
      qty: Number(line.left_qty || 0) + Number(line.right_qty || 0),
      photo_urls: editForm.photo_urls,
      scrap_source: editForm.scrap_source,
      subcontract_order_id: editForm.responsible_party_type === 'subcontractor' ? editForm.subcontract_order_id : 0,
      responsible_party_type: editForm.responsible_party_type,
      replacement_source: editForm.replacement_source,
      loss_amount: calculatedEditLineLoss(line),
      company_share_percent: allocation.company,
      ...(editForm.responsible_party_type === 'employee' ? { responsibilities: allocation.workers } : {}),
      note: editForm.note,
    })))
    if (newLines.length) {
      await http.post(`/defect-events/${editForm.id}/size-lines`, {
        size_lines: newLines.map(line => ({
          size_id: line.size_id,
          left_qty: Number(line.left_qty || 0),
          right_qty: Number(line.right_qty || 0),
        })),
      })
    }
    ElMessage.success('已保存')
    editVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    editSaving.value = false
  }
}

async function deleteDefect(row: any) {
  try {
    const materialDocWarning = row.material_doc_no
      ? `，并删除关联补料单 ${row.material_doc_no}`
      : ''
    await ElMessageBox.confirm(
      `确认删除这条报废记录（${row.order_no || '未关联生产单'} · ${row.size_value || '无码数'}）${materialDocWarning}？`,
      '删除报废记录',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await http.delete(`/defect-events/${row.id}`)
    ElMessage.success('已删除')
    if (rows.value.length === 1 && page.value > 1) page.value -= 1
    await load()
  } catch (e: any) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(e?.response?.data?.detail || e?.message || '删除失败')
  }
}

function handleDefectAction(row: any, command: string | number | object) {
  if (command === 'print') void printRecutOrder(row)
  else if (command === 'edit') void openEdit(row)
  else if (command === 'delete') void deleteDefect(row)
}

async function printRecutOrder(row: any) {
  const defectId = Number(row.id)
  if (!defectId || recutPrintingId.value) return
  let headerId = Number(row.recut_header_id || 0)
  let printWindow: Window | null = null
  if (!headerId) {
    printWindow = window.open('', '_blank')
    if (printWindow) {
      printWindow.document.title = '正在生成生产单-补'
      printWindow.document.body.textContent = '正在生成生产单-补，请稍候…'
    }
  }
  recutPrintingId.value = defectId
  try {
    if (!headerId) {
      const res: any = await http.post(`/defect-events/${defectId}/recut`, {
        qty: Number(row.qty || 0),
        size_id: row.size_id ? Number(row.size_id) : undefined,
      })
      headerId = Number(res.data?.id || res.data?.header_id || 0)
      if (!headerId) throw new Error('生成后未返回补生产单编号')
      row.recut_header_id = headerId
      row.recut_header_no = res.data?.header_no || ''
      ElMessage.success(`已生成生产单-补 ${row.recut_header_no || ''}`)
    }
    const url = `${window.location.origin}/admin/executions/print/${headerId}?mode=flow-card`
    if (printWindow && !printWindow.closed) printWindow.location.href = url
    else window.open(url, '_blank')
  } catch (e: any) {
    if (printWindow && !printWindow.closed) printWindow.close()
    ElMessage.error(e?.response?.data?.detail || e?.message || '生成生产单-补失败')
  } finally {
    recutPrintingId.value = null
  }
}

async function load() {
  const res: any = await http.get('/defect-events', {
    params: {
      page: page.value,
      page_size: pageSize.value,
      order_no: filters.order_no || undefined,
      responsible_worker_id: filters.responsible_worker_id || undefined,
      status: filters.status || undefined,
      pending_rework: filters.pending_rework || undefined,
      date_from: filters.date_range?.[0] || undefined,
      date_to: filters.date_range?.[1] || undefined,
    },
  })
  rows.value = res.data?.items || []
  total.value = res.data?.total || 0
  summary.value = { ...emptySummary(), ...(res.data?.summary || {}) }
  void preloadWarehouseMaterials(rows.value)
}

async function loadMeta() {
  const [wRes, pRes]: any[] = await Promise.all([
    http.get('/workers', { params: { page_size: 200 } }),
    http.get('/processes'),
  ])
  workers.value = (wRes.data?.items || []).filter((x: any) => x.is_active !== false)
  processes.value = (pRes.data?.items || pRes.data || []).filter((x: any) => x.is_active !== false)
}

watch(editTotalLoss, total => {
  if (!editForm.responsibilities.length) editForm.company_amount = Number(total.toFixed(2))
})

onMounted(async () => {
  await loadMeta()
  await load()
  measureTableHeight()
})
</script>

<style scoped>
.responsibility-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.edit-photo-list, .edit-responsibilities {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.edit-photo-item { position: relative; width: 64px; height: 64px; }
.edit-photo-item :deep(.el-image) { width: 64px; height: 64px; border-radius: 6px; }
.edit-photo-item button { position: absolute; top: -7px; right: -7px; width: 20px; height: 20px; padding: 0; border: 0; border-radius: 50%; background: #d33; color: #fff; cursor: pointer; }
.edit-photo-add { display: grid; width: 64px; height: 64px; place-items: center; border: 1px dashed var(--el-border-color); border-radius: 6px; color: var(--el-color-primary); cursor: pointer; }
.edit-photo-add input { display: none; }
.edit-loss-total { margin-top: 8px; color: var(--el-text-color-secondary); text-align: right; }
.edit-size-actions { display: flex; width: 100%; align-items: center; justify-content: space-between; margin-top: 10px; }
.edit-size-actions .edit-loss-total { margin-top: 0; }
.edit-responsibilities { width: 100%; align-items: flex-start; flex-direction: column; }
.edit-responsibility-row { display: grid; width: 100%; grid-template-columns: 1fr 150px 48px; align-items: center; gap: 8px; }
.edit-auto-allocation { color: var(--el-text-color-secondary); text-align: right; }
.edit-responsibility-row :deep(.el-input-number), .edit-form :deep(.el-input-number) { width: 100%; }
.edit-allocation-total { color: var(--el-text-color-secondary); }
.edit-allocation-total.invalid { color: var(--el-color-danger); }
.edit-form {
  width: 100%;
}
.defects-table-host,
.defects-table {
  width: 100%;
  max-width: 100%;
  min-width: 0;
}
.defects-table :deep(.el-table__inner-wrapper) {
  width: 100%;
}
.defects-table :deep(td.el-table__cell),
.defects-table :deep(th.el-table__cell) {
  min-width: 0;
}
.defects-table :deep(.cell) {
  padding-right: 3px;
  padding-left: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.defects-table :deep(.defect-group-stripe > td.el-table__cell) {
  background: var(--el-fill-color-lighter);
}
.defects-table :deep(.el-table__header-wrapper th.el-table__cell) {
  height: 30px;
  padding: 2px 0;
}
.defects-table :deep(.el-table__header-wrapper th.el-table__cell > .cell) {
  line-height: 20px;
}
.defects-table :deep(.el-scrollbar__bar.is-horizontal) {
  display: none;
}
.defect-product-thumb {
  width: 40px;
  height: 40px;
  border-radius: 6px;
  display: block;
  margin: 0 auto;
}
.defect-warehouse-tag { cursor: help; }
.defect-more-button {
  min-width: 32px;
  color: var(--el-text-color-regular);
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 1px;
}
</style>

<style>
.defect-warehouse-popper.el-popover {
  max-width: min(92vw, 580px);
  padding: 10px 12px;
}
.defect-warehouse-detail {
  max-height: min(60vh, 420px);
  overflow-y: auto;
  padding-right: 2px;
}
.defect-warehouse-head,
.defect-warehouse-segment-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.defect-warehouse-head { margin-bottom: 10px; font-size: 13px; }
.defect-warehouse-segment + .defect-warehouse-segment { margin-top: 10px; }
.defect-warehouse-segment-head { margin-bottom: 4px; font-size: 12px; }
.defect-warehouse-empty { padding: 14px 0; text-align: center; }
.defect-warehouse-popper .defect-material-shortage td { background: var(--el-color-danger-light-9) !important; }
.defect-warehouse-popper .shortage-text { color: var(--el-color-danger); }
.defect-warehouse-popper .muted { color: var(--el-text-color-placeholder); }
</style>
