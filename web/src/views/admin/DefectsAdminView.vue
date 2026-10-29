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
              label="数量(只)"
              :width="colWidth('qty', 56)"
              align="center"
              resizable
            >
              <template #default="{ row }">{{ row.qty ?? '—' }}</template>
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
                <el-dropdown v-if="defectActions(row).length" trigger="click" @command="handleDefectAction(row, $event)">
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
                      <el-dropdown-item
                        v-for="action in defectActions(row)"
                        :key="action.command"
                        :command="action.command"
                        :disabled="action.disabled"
                        :divided="action.divided"
                      >
                        {{ action.label }}
                      </el-dropdown-item>
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

    <el-dialog v-model="editVisible" title="编辑报废记录" width="980px" class="defect-edit-dialog">
      <el-form v-loading="editLoading" class="defect-edit-form" label-width="88px">
        <el-form-item label="生产单号">
          <el-input :model-value="editForm.order_no" disabled />
        </el-form-item>
        <el-form-item label="发现工序" required>
          <el-select
            v-model="editForm.found_process_id"
            filterable
            style="width: 100%"
            :disabled="editForm.responsible_party_type === 'subcontractor'"
            @change="onEditFoundProcessChange"
          >
            <el-option v-for="p in editRouteProcesses" :key="p.id" :label="p.label || p.process_name" :value="p.process_id" />
          </el-select>
          <span v-if="editForm.responsible_party_type === 'subcontractor'" class="muted">外发厂报废默认外发第一道工序</span>
        </el-form-item>
        <el-form-item label="码数">
          <div class="scrap-grid scrap-grid--sizes" :style="scrapGridStyle">
            <span class="scrap-grid__corner" />
            <span v-for="size in editSizeColumns" :key="size.size_id" class="scrap-grid__head">{{ size.size_value }}</span>
            <span class="scrap-grid__axis">左脚</span>
            <el-input-number
              v-for="size in editSizeColumns"
              :key="`left-${size.size_id}`"
              :model-value="sizeLine(size).left_qty"
              :min="0"
              :precision="0"
              :controls="false"
              @update:model-value="value => setSizeQty(size, 'left_qty', value)"
            />
            <span class="scrap-grid__axis">右脚</span>
            <el-input-number
              v-for="size in editSizeColumns"
              :key="`right-${size.size_id}`"
              :model-value="sizeLine(size).right_qty"
              :min="0"
              :precision="0"
              :controls="false"
              @update:model-value="value => setSizeQty(size, 'right_qty', value)"
            />
          </div>
        </el-form-item>
        <el-form-item v-if="editSupervisorReport" label="主管报工">
          <div class="edit-supervisor">
            <div class="edit-supervisor__head">
              <span>报废 {{ editTotalQty }} 只，最多 {{ editReportMax }} 双</span>
              <el-input-number v-model="editSupervisorReport.qualified_qty" :min="0" :precision="2" :step="0.5" :disabled="editSupervisorApplied" />
              <span>双</span>
            </div>
            <div v-for="process in editSupervisorReport.processes" :key="process.order_process_id" class="edit-supervisor__process">
              <strong>{{ process.process_name }}</strong>
              <div v-for="share in process.shares" :key="share.worker_id" class="edit-supervisor__person">
                <span>{{ workerName(share.worker_id) }}</span>
                <el-input-number v-model="share.pairs" :min="0" :precision="2" :step="0.5" :disabled="editSupervisorApplied" />
                <span>双</span>
              </div>
            </div>
          </div>
        </el-form-item>
        <el-form-item v-if="editForm.responsible_party_type !== 'subcontractor' && editCurrentMaterials.length" label="物料报损">
          <div class="edit-materials">
            <button type="button" class="scrap-toggle" @click="editMaterialsOpen = !editMaterialsOpen">{{ editMaterialsOpen ? '收起' : '展开' }}</button>
            <div v-if="editMaterialsOpen" class="scrap-material-list">
              <div v-for="row in editCurrentMaterials" :key="row.supplier_product_id" class="scrap-grid scrap-grid--material" :style="scrapGridStyle">
                <div class="scrap-material__name">
                  <strong>{{ row.name }}</strong>
                  <span>{{ row.unit_name }}</span>
                </div>
                <template v-if="row.sizes?.length">
                  <template v-for="size in editSizeColumns" :key="size.size_id">
                    <el-input
                      v-if="row.sizes.some(item => Number(item.size_id) === Number(size.size_id))"
                      :model-value="manualQty(row, size.size_id)"
                      @update:model-value="value => setManualQty(row, value, size.size_id)"
                    />
                    <span v-else />
                  </template>
                </template>
                <el-input
                  v-else
                  class="scrap-material__single"
                  :model-value="manualQty(row)"
                  @update:model-value="value => setManualQty(row, value)"
                />
              </div>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="损失金额">
          <div class="edit-loss-head">
            <strong>共 {{ formatMoney(editTotalLoss) }}</strong>
            <el-button link type="primary" @click="editLossOpen = !editLossOpen">{{ editLossOpen ? '收起' : '明细' }}</el-button>
          </div>
          <div v-if="editLossOpen" class="edit-loss-detail">
            <div>
              <div class="edit-loss-head"><span>材料</span><span>{{ formatMoney(editMaterialLoss) }}</span></div>
              <el-table v-if="editMaterialGroups.length" :data="editMaterialRows" border size="small" :span-method="materialSpan">
                <el-table-column prop="segmentName" label="工序段" width="120" />
                <el-table-column prop="name" label="材料" />
                <el-table-column prop="money" label="金额" width="110" align="right" />
              </el-table>
              <span v-else class="muted">暂无前段材料</span>
            </div>
            <div>
              <div class="edit-loss-head"><span>计件工资</span><span>{{ formatMoney(editLaborLoss) }}</span></div>
              <el-table v-if="editLaborGroups.length" :data="editLaborRows" border size="small" :span-method="laborSpan">
                <el-table-column prop="segmentName" label="工序段" width="120" />
                <el-table-column prop="name" label="工序" />
                <el-table-column prop="money" label="金额" width="110" align="right" />
              </el-table>
              <span v-else class="muted">暂无计件工资</span>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="公司承担">
          <el-input-number
            v-if="editForm.responsible_party_type === 'subcontractor'"
            v-model="editForm.company_amount"
            :min="0"
            :precision="2"
            :controls="false"
          />
          <strong v-else>{{ formatMoney(editCompanyShare) }}</strong>
        </el-form-item>
        <el-form-item v-if="editSubcontractOrders.length" label="责任人">
          <el-radio-group v-model="editForm.responsible_party_type" @change="changeEditResponsibleParty">
            <el-radio-button value="employee">员工</el-radio-button>
            <el-radio-button value="subcontractor">外发厂</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <template v-if="editForm.responsible_party_type === 'subcontractor'">
          <el-form-item v-if="editSubcontractOrders.length" label="外加工厂" required>
            <el-select v-model="editSubcontractPartnerId" filterable style="width: 100%" @change="changeEditSubcontractPartner">
              <el-option v-for="partner in editSubcontractPartners" :key="partner.id" :label="partner.name" :value="partner.id" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="editSubcontractOrders.length" label="外发单" required>
            <el-select v-model="editForm.subcontract_order_id" filterable style="width: 100%" @change="applyEditFactoryProcess">
              <el-option
                v-for="order in editSubcontractOrdersForPartner"
                :key="order.id"
                :label="`${order.subcontract_no} · ${order.total_qty || 0}`"
                :value="order.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="外发厂承担">
            <strong>{{ formatMoney(Math.max(0, editTotalLoss - Number(editForm.company_amount || 0))) }}</strong>
          </el-form-item>
        </template>
        <el-form-item v-else label="选择责任人">
          <div class="edit-responsibilities">
            <el-select v-model="editWorkerIds" multiple filterable placeholder="支持多选" style="width: 100%">
              <el-option v-for="worker in workers" :key="worker.id" :label="worker.name" :value="worker.id" />
            </el-select>
            <div v-for="item in editForm.responsibilities" :key="item.key" class="edit-responsibility-row">
              <span class="edit-responsibility-name">{{ workerName(item.worker_id) }}</span>
              <el-input-number v-model="item.share_amount" :min="0" :precision="2" :controls="false" />
              <el-button link type="danger" @click="removeEditResponsibility(item.worker_id)">删除</el-button>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="现场照片">
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
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const auth = useAuthStore()
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
  responsibilities: [] as Array<{ key: number; worker_id: number | null; share_amount: number }>,
  note: '',
})
const editSizeOptions = ref<any[]>([])
const editRouteProcesses = ref<any[]>([])
const editLossQuote = ref<any>(null)
const editMaterialsOpen = ref(false)
const editLossOpen = ref(false)
const editManualQty = ref<Record<string, string>>({})
const editManualTouched = ref<Record<string, boolean>>({})
const editSupervisorReport = ref<any>(null)
const editSupervisorApplied = ref(false)
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
const editSizeColumns = computed(() => [...editSizeOptions.value].sort((a, b) => Number(a.size_value) - Number(b.size_value)))
const scrapGridStyle = computed(() => ({
  gridTemplateColumns: `96px repeat(${Math.max(editSizeColumns.value.length, 1)}, minmax(0, 1fr))`,
}))
const editTotalQty = computed(() => editForm.lines.reduce((sum, line) => sum + Number(line.left_qty || 0) + Number(line.right_qty || 0), 0))
const editReportMax = computed(() => (editTotalQty.value / 2).toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1'))
const editCurrentMaterials = computed(() => editLossQuote.value?.current_material_lines || [])
const editCompanyShare = computed(() => {
  const personal = editForm.responsibilities.reduce((sum, row) => sum + Number(row.share_amount || 0), 0)
  return Math.max(0, Number((editTotalLoss.value - personal).toFixed(2)))
})
const editWorkerIds = computed({
  get: () => editForm.responsibilities.map(row => Number(row.worker_id || 0)).filter(Boolean),
  set: (ids: number[]) => {
    const previous = new Map(editForm.responsibilities.map(row => [Number(row.worker_id), Number(row.share_amount || 0)]))
    editForm.responsibilities = ids.map(id => ({
      key: ++editResponsibilityKey,
      worker_id: id,
      share_amount: previous.get(id) ?? 0,
    }))
  },
})
function workerName(workerId: number | null) {
  return workers.value.find(worker => Number(worker.id) === Number(workerId))?.name || '员工'
}
function sizeLine(size: { size_id: number; size_value?: string }) {
  let line = editForm.lines.find(row => Number(row.size_id) === Number(size.size_id))
  if (!line) {
    line = { id: null, size_id: Number(size.size_id), size_value: size.size_value || '', left_qty: 0, right_qty: 0, loss_amount: 0 }
    editForm.lines.push(line)
  }
  return line
}
function setSizeQty(size: { size_id: number; size_value?: string }, side: 'left_qty' | 'right_qty', value: number | undefined) {
  sizeLine(size)[side] = Number(value || 0)
  syncEditManualDefaults()
}
function manualKey(productId: number, sizeId?: number) {
  return sizeId ? `${productId}:${sizeId}` : String(productId)
}
function manualQty(row: any, sizeId?: number) {
  return editManualQty.value[manualKey(row.supplier_product_id, sizeId)] || ''
}
function setManualQty(row: any, value: string, sizeId?: number) {
  const key = manualKey(row.supplier_product_id, sizeId)
  editManualTouched.value[key] = true
  editManualQty.value = { ...editManualQty.value, [key]: value }
}
function pieceRate(row: any, sizeId: number | null) {
  if (sizeId != null && row?.by_size && row.by_size[String(sizeId)] != null) return Number(row.by_size[String(sizeId)] || 0)
  return Number(row?.amount_per_piece || 0)
}
const editMaterialGroups = computed(() => {
  if (editForm.responsible_party_type === 'subcontractor') {
    const order = editSubcontractOrders.value.find((item: any) => Number(item.id) === Number(editForm.subcontract_order_id))
    const unit = Number(order?.material_unit_price || 0) / 2
    return [{ key: 'sub', segmentName: '', lines: [{ name: '外发材料', money: formatMoney(unit * editTotalQty.value) }] }]
  }
  const groups: Array<{ key: string; segmentName: string; lines: Array<{ name: string; money: string }> }> = []
  for (const row of editLossQuote.value?.material_lines || []) {
    const amount = editForm.lines.reduce((sum, line) => sum + pieceRate(row, line.size_id) * (Number(line.left_qty || 0) + Number(line.right_qty || 0)), 0)
    const key = String(row.segment_id || 0)
    const line = { name: row.name || '材料', money: formatMoney(amount) }
    const last = groups[groups.length - 1]
    if (last && last.key === key) last.lines.push(line)
    else groups.push({ key, segmentName: row.segment_name || '未分段', lines: [line] })
  }
  const currentName = editLossQuote.value?.current_segment_name || '本段'
  const filled = editCurrentMaterials.value.flatMap((row: any) => {
    if (row.sizes?.length) {
      return row.sizes.map((size: any) => ({
        name: `${row.name} ${size.size_value}`,
        amount: Number(manualQty(row, size.size_id) || 0) * Number(row.unit_price || 0),
      })).filter((item: any) => item.amount > 0)
    }
    const amount = Number(manualQty(row) || 0) * Number(row.unit_price || 0)
    return amount > 0 ? [{ name: row.name, amount }] : []
  })
  if (filled.length) {
    groups.push({
      key: 'current',
      segmentName: currentName,
      lines: filled.map((item: any) => ({ name: item.name, money: formatMoney(item.amount) })),
    })
  }
  return groups
})
const editMaterialRows = computed(() => editMaterialGroups.value.flatMap(group => group.lines.map((line, index) => ({
  ...line,
  segmentName: group.segmentName,
  span: index === 0 ? group.lines.length : 0,
}))))
function editReportedPairs(orderProcessId: number) {
  const report = editSupervisorReport.value
  if (!report?.processes) return null
  const process = report.processes.find((row: any) => Number(row.order_process_id) === Number(orderProcessId))
  if (!process) return null
  return (process.shares || []).reduce((sum: number, share: any) => sum + Number(share.pairs || 0), 0)
}
function editLaborMoney(row: any) {
  const pairs = editReportedPairs(Number(row.order_process_id || 0))
  if (pairs != null) {
    if (pairs <= 0) return null
    const price = Number(row.unit_price || 0) || Number(row.amount_per_piece || 0) * 2
    return price * pairs
  }
  const unit = row.amount_per_piece != null ? Number(row.amount_per_piece || 0) : Number(row.unit_price || 0) / 2
  return unit * editTotalQty.value
}
const editLaborGroups = computed(() => {
  const groups: Array<{ key: string; segmentName: string; lines: Array<{ name: string; money: string }> }> = []
  for (const row of editLossQuote.value?.labor_lines || []) {
    const amount = editLaborMoney(row)
    if (amount == null) continue
    const line = { name: row.process_name || row.name || '工序', money: formatMoney(amount) }
    const key = String(row.segment_id || 0)
    const last = groups[groups.length - 1]
    if (last && last.key === key) last.lines.push(line)
    else groups.push({ key, segmentName: row.segment_name || '未分段', lines: [line] })
  }
  return groups
})
const editLaborRows = computed(() => editLaborGroups.value.flatMap(group => group.lines.map((line, index) => ({
  ...line,
  segmentName: group.segmentName,
  span: index === 0 ? group.lines.length : 0,
}))))
function materialSpan({ row, columnIndex }: { row: any; columnIndex: number }) {
  if (columnIndex !== 0) return [1, 1]
  return row.span ? [row.span, 1] : [0, 0]
}
const laborSpan = materialSpan
const editMaterialLoss = computed(() => {
  if (editForm.responsible_party_type === 'subcontractor') {
    const order = editSubcontractOrders.value.find((item: any) => Number(item.id) === Number(editForm.subcontract_order_id))
    return Number(order?.material_unit_price || 0) / 2 * editTotalQty.value
  }
  const prior = (editLossQuote.value?.material_lines || []).reduce((sum: number, row: any) => (
    sum + editForm.lines.reduce((lineSum, line) => lineSum + pieceRate(row, line.size_id) * (Number(line.left_qty || 0) + Number(line.right_qty || 0)), 0)
  ), 0)
  const manual = editCurrentMaterials.value.reduce((sum: number, row: any) => {
    if (row.sizes?.length) {
      return sum + row.sizes.reduce((sizeSum: number, size: any) => sizeSum + Number(manualQty(row, size.size_id) || 0) * Number(row.unit_price || 0), 0)
    }
    return sum + Number(manualQty(row) || 0) * Number(row.unit_price || 0)
  }, 0)
  return prior + manual
})
const editLaborLoss = computed(() => (editLossQuote.value?.labor_lines || []).reduce((sum: number, row: any) => {
  return sum + Number(editLaborMoney(row) || 0)
}, 0))
const editTotalLoss = computed(() => Number((editMaterialLoss.value + editLaborLoss.value).toFixed(2)))
/** 当前列表出现的码数，用作两行表头第一行 */
const listSizeHeaders = computed(() => {
  const set = new Set<string>()
  for (const row of rows.value) {
    const sizes = Array.isArray(row.sizes) && row.sizes.length ? row.sizes : [row]
    for (const size of sizes) {
      if (size.size_value == null || size.size_value === '') continue
      if (Number(size.left_qty || 0) <= 0 && Number(size.right_qty || 0) <= 0) continue
      set.add(String(size.size_value))
    }
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
  const lines = Array.isArray(row.sizes) && row.sizes.length ? row.sizes : [row]
  const match = lines.find((item: any) => String(item.size_value ?? '') === size)
  if (!match) return ''
  const qty = Number(side === 'left' ? match.left_qty || 0 : match.right_qty || 0)
  return qty > 0 ? qty : ''
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
        share_amount: Number(item.deduction_amount || 0),
      }))
    const report = detail.pending_supervisor_report
    editSupervisorApplied.value = Boolean(report?.applied)
    editSupervisorReport.value = report
      ? {
        qualified_qty: Number(report.qualified_qty || 0),
        processes: (report.processes || []).map((process: any) => ({
          order_process_id: process.order_process_id,
          process_name: process.process_name,
          shares: (process.shares || []).map((share: any) => ({
            worker_id: Number(share.worker_id),
            pairs: Number(share.pairs || 0),
          })),
        })),
      }
      : null
    editManualQty.value = {}
    editManualTouched.value = {}
    for (const item of items) {
      const lines = item.manual_materials?.lines || []
      for (const line of lines) {
        const key = line.size_id
          ? `${line.supplier_product_id}:${line.size_id}`
          : String(line.supplier_product_id)
        const next = Number(editManualQty.value[key] || 0) + Number(line.qty || 0)
        if (next > 0) {
          editManualQty.value[key] = String(next)
          editManualTouched.value[key] = true
        }
      }
    }
    editMaterialsOpen.value = false
    editLossOpen.value = false
    editRouteProcesses.value = []
    editSizeOptions.value = editForm.lines.map(line => ({ size_id: line.size_id, size_value: line.size_value }))
    editSubcontractOrders.value = []
    editSubcontractPartnerId.value = detail.subcontract_partner_id ? Number(detail.subcontract_partner_id) : null
    if (editForm.header_id) {
      const headerRes: any = await http.get(`/executions/headers/${editForm.header_id}`)
      editSizeOptions.value = headerRes.data?.size_lines || editSizeOptions.value
      for (const size of editSizeOptions.value) sizeLine(size)
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
  if (!editRouteProcesses.value.length) {
    const routeRes: any = await http.get(`/executions/headers/${editForm.header_id}/processes`)
    editRouteProcesses.value = routeRes.data?.items || []
  }
  const route = editRouteProcesses.value.find(
    (item: any) => Number(item.process_id) === Number(editForm.found_process_id),
  )
  if (!route) return
  const quoteRes: any = await http.get('/defect-events/loss-quote', {
    params: {
      header_id: editForm.header_id,
      order_process_id: route.id,
      department_segment_id: route.segment_id || undefined,
    },
  })
  editLossQuote.value = quoteRes.data || null
  syncEditManualDefaults()
}
function onEditFoundProcessChange() {
  editManualQty.value = {}
  editManualTouched.value = {}
  void refreshEditLossQuote()
}
function syncEditManualDefaults() {
  if (editForm.responsible_party_type === 'subcontractor') return
  const next = { ...editManualQty.value }
  const pieces = editTotalQty.value
  for (const row of editCurrentMaterials.value) {
    if (row.sizes?.length) {
      for (const size of row.sizes) {
        const key = manualKey(row.supplier_product_id, size.size_id)
        if (editManualTouched.value[key]) continue
        const line = editForm.lines.find(item => Number(item.size_id) === Number(size.size_id))
        const fill = Math.max(Number(line?.left_qty || 0), Number(line?.right_qty || 0))
        if (fill > 0) next[key] = String(fill)
        else delete next[key]
      }
    } else {
      const key = manualKey(row.supplier_product_id)
      if (editManualTouched.value[key]) continue
      if (pieces > 0) next[key] = String(pieces)
      else delete next[key]
    }
  }
  editManualQty.value = next
}
function removeEditResponsibility(workerId: number | null) {
  editForm.responsibilities = editForm.responsibilities.filter(row => Number(row.worker_id) !== Number(workerId))
}

function changeEditResponsibleParty() {
  if (editForm.responsible_party_type === 'subcontractor') {
    editForm.scrap_source = 'subcontract'
    editForm.responsibilities = []
    editForm.company_amount = 0
    editManualQty.value = {}
    editManualTouched.value = {}
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
    editForm.company_amount = 0
    void refreshEditLossQuote()
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
  const total = Number(editTotalLoss.value || 0)
  if (total <= 0) return { company: 100, workers: [] as Array<{ worker_id: number; share_percent: number; share_amount: number }> }
  const companyAmount = editForm.responsible_party_type === 'subcontractor'
    ? Number(editForm.company_amount || 0)
    : editCompanyShare.value
  const entries = [
    { kind: 'company', amount: companyAmount, worker_id: 0 },
    ...editForm.responsibilities.map(row => ({ kind: 'worker', amount: Number(row.share_amount || 0), worker_id: Number(row.worker_id || 0) })),
  ].filter(row => row.amount > 0 && (row.kind === 'company' || row.worker_id > 0))
  const allocated = entries.map(row => {
    const exact = row.amount / total * 100
    return { ...row, percent: Math.floor(exact), remainder: exact - Math.floor(exact) }
  })
  let remaining = 100 - allocated.reduce((sum, row) => sum + row.percent, 0)
  for (const row of [...allocated].sort((a, b) => b.remainder - a.remainder)) {
    if (remaining <= 0) break
    row.percent += 1
    remaining -= 1
  }
  return {
    company: allocated.find(row => row.kind === 'company')?.percent || 0,
    workers: allocated.filter(row => row.kind === 'worker').map(row => ({
      worker_id: row.worker_id,
      share_percent: row.percent,
      share_amount: Number(row.amount.toFixed(2)),
    })),
  }
}
function manualLinesForSize(sizeId: number, pieces: number, isLast: boolean, allocated: Record<number, number>) {
  const lines: Array<{ supplier_product_id: number; qty: number; size_id?: number }> = []
  for (const row of editCurrentMaterials.value) {
    if (row.sizes?.length) {
      const qty = Number(manualQty(row, sizeId) || 0)
      if (qty > 0) lines.push({ supplier_product_id: Number(row.supplier_product_id), size_id: sizeId, qty })
      continue
    }
    const total = Number(manualQty(row) || 0)
    if (total <= 0 || pieces <= 0) continue
    const productId = Number(row.supplier_product_id)
    const used = allocated[productId] || 0
    const sizePieces = Number(sizeLine({ size_id: sizeId }).left_qty || 0) + Number(sizeLine({ size_id: sizeId }).right_qty || 0)
    const part = isLast ? Number((total - used).toFixed(4)) : Number((total * sizePieces / pieces).toFixed(4))
    allocated[productId] = used + part
    if (part > 0) lines.push({ supplier_product_id: productId, qty: part })
  }
  return lines
}

async function saveEdit() {
  if (!editForm.found_process_id) {
    ElMessage.warning('请选择发现工序')
    return
  }
  const activeLines = editForm.lines.filter(line => line.size_id && Number(line.left_qty || 0) + Number(line.right_qty || 0) > 0)
  const removedLines = editForm.lines.filter(line => line.id && Number(line.left_qty || 0) + Number(line.right_qty || 0) <= 0)
  if (!activeLines.length) {
    ElMessage.warning('请至少填写一个码数的左脚或右脚数量')
    return
  }
  if (editForm.responsible_party_type === 'subcontractor' && Number(editForm.company_amount || 0) > editTotalLoss.value) {
    ElMessage.warning('公司承担不能大于总损失')
    return
  }
  if (editForm.responsible_party_type === 'employee' && editCompanyShare.value < -0.01) {
    ElMessage.warning('责任人承担不能大于损失金额')
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
    const pieces = activeLines.reduce((sum, line) => sum + Number(line.left_qty || 0) + Number(line.right_qty || 0), 0)
    const allocated: Record<number, number> = {}
    const lossTotal = activeLines.reduce((sum, line) => sum + Number(line.loss_amount || 0), 0)
    const shareSpent: Record<number, number> = {}
    const segmentId = editLossQuote.value?.current_segment_id || undefined
    const payloads: Array<{ sizeId: number; payload: Record<string, unknown> }> = []
    for (const [index, line] of activeLines.entries()) {
      const materials = editForm.responsible_party_type === 'subcontractor'
        ? []
        : manualLinesForSize(Number(line.size_id), pieces, index === activeLines.length - 1, allocated)
      const isLastLine = index === activeLines.length - 1
      const lineLoss = Number(line.loss_amount || 0)
      const responsibilities = allocation.workers.map(row => {
        const totalCents = Math.round(Number(row.share_amount || 0) * 100)
        const used = shareSpent[row.worker_id] || 0
        let partCents = isLastLine || lossTotal <= 0 ? totalCents - used : Math.round(totalCents * lineLoss / lossTotal)
        if (!isLastLine && used + partCents > totalCents) partCents = totalCents - used
        if (!isLastLine) shareSpent[row.worker_id] = used + partCents
        return { ...row, share_amount: partCents / 100 }
      })
      const payload = {
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
        company_share_percent: allocation.company,
        ...(editForm.responsible_party_type === 'employee' ? { responsibilities } : {}),
        department_segment_id: segmentId,
        manual_materials: materials,
        note: editForm.note,
        ...(index === 0 && editSupervisorReport.value && !editSupervisorApplied.value
          ? { supervisor_report: editSupervisorReport.value }
          : {}),
      }
      if (line.id) await http.patch(`/defect-events/${line.id}`, payload)
      else payloads.push({ sizeId: Number(line.size_id), payload })
    }
    const newLines = activeLines.filter(line => !line.id)
    if (newLines.length) {
      await http.post(`/defect-events/${editForm.id}/size-lines`, {
        size_lines: newLines.map(line => ({
          size_id: line.size_id,
          left_qty: Number(line.left_qty || 0),
          right_qty: Number(line.right_qty || 0),
        })),
      })
      const created: any = await http.get(`/defect-events/${editForm.id}`)
      const items = created.data?.registration_items?.length ? created.data.registration_items : [created.data]
      for (const pending of payloads) {
        const match = items.find((item: any) => Number(item.size_id) === pending.sizeId)
        if (match?.id) await http.patch(`/defect-events/${match.id}`, pending.payload)
      }
    }
    await Promise.all(removedLines.map(line => http.delete(`/defect-events/${line.id}`)))
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

function defectActions(row: any) {
  const actions: { command: string; label: string; disabled?: boolean; divided?: boolean }[] = []
  if (
    auth.hasPermission('btn.defects.print')
    && row.disposition === 'scrap'
    && row.replacement_source !== 'subcontract'
  ) {
    actions.push({
      command: 'print',
      label: row.status === 'closed' ? '打印生产单-补' : '打印生产单-补（确认后）',
      disabled: row.status !== 'closed',
    })
  }
  if (auth.hasPermission('btn.defects.confirm') && row.status !== 'closed') {
    actions.push({ command: 'confirm', label: '确认' })
  }
  if (auth.hasPermission('btn.defects.edit')) {
    actions.push({ command: 'edit', label: '编辑' })
  }
  if (auth.hasPermission('btn.defects.delete')) {
    actions.push({ command: 'delete', label: '删除', divided: actions.length > 0 })
  }
  return actions
}

function handleDefectAction(row: any, command: string | number | object) {
  if (!defectActions(row).some(action => action.command === command)) return
  if (command === 'print') void printRecutOrder(row)
  else if (command === 'confirm') void confirmDefect(row)
  else if (command === 'edit') void openEdit(row)
  else if (command === 'delete') void deleteDefect(row)
}

async function confirmDefect(row: any) {
  try {
    await ElMessageBox.confirm(
      '确认后，报工会入账，材料计入仓库生产需求，然后才能打印补单。',
      '确认报废',
      { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' },
    )
    await http.post(`/defect-events/${row.id}/supervisor-confirm`)
    ElMessage.success('已确认')
    await load()
  } catch (e: any) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(e?.response?.data?.detail || e?.message || '确认失败')
  }
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
}

async function loadMeta() {
  const wRes: any = await http.get('/workers', { params: { page_size: 200 } })
  workers.value = (wRes.data?.items || []).filter((x: any) => x.is_active !== false)
}

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
.edit-responsibility-row {
  display: grid;
  grid-template-columns: 96px 160px 48px;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
.edit-responsibility-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.edit-responsibility-row :deep(.el-input-number) { width: 160px; }
.edit-responsibilities { display: flex; flex-direction: column; width: 100%; min-width: 0; }
.defect-edit-form :deep(.el-form-item__label) { white-space: nowrap; }
.defect-edit-form :deep(.el-form-item__content) { min-width: 0; }
.scrap-grid {
  display: grid;
  gap: 8px;
  align-items: center;
  width: 100%;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f3f7fc;
}
.scrap-grid__corner,
.scrap-grid__axis,
.scrap-grid__head { white-space: nowrap; }
.scrap-grid__head { color: var(--el-text-color-secondary); text-align: center; font-size: 13px; }
.scrap-grid__axis { color: var(--el-text-color-regular); }
.scrap-grid :deep(.el-input-number),
.scrap-grid :deep(.el-input) { width: 100%; min-width: 0; }
.scrap-grid :deep(.el-input__wrapper) { padding: 0 8px; }
.scrap-toggle {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--el-color-primary);
  cursor: pointer;
}
.scrap-material-list { display: grid; gap: 8px; width: 100%; margin-top: 8px; }
.scrap-material__name { display: flex; min-width: 0; align-items: baseline; gap: 6px; }
.scrap-material__name strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.scrap-material__name span { flex: none; color: var(--el-text-color-secondary); font-size: 12px; }
.scrap-grid--material { padding: 8px 12px; background: #fff; border: 1px solid #e6eef6; }
.scrap-material__single { width: 100%; max-width: 120px; }
.edit-materials { width: 100%; min-width: 0; }
.edit-loss-head { display: flex; align-items: center; gap: 12px; }
.edit-loss-detail { display: grid; gap: 12px; width: 100%; margin-top: 8px; }
.edit-supervisor__head,
.edit-supervisor__person { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.edit-supervisor__person > span:first-child { width: 96px; flex: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.edit-supervisor :deep(.el-input-number) { width: 120px; flex: none; }
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
.defect-more-button {
  min-width: 32px;
  color: var(--el-text-color-regular);
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 1px;
}
</style>
