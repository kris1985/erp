<template>
  <div class="after-sales-page">
    <header class="page-hero after-sales-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">售后服务</h1>
        <p class="page-desc">客户退货登记 · 退款、修复与按码重做跟进</p>
      </div>
      <el-button type="primary" @click="openCreate">新增退货售后</el-button>
    </header>

    <div class="admin-card">
      <div class="admin-toolbar">
        <el-input v-model="filters.keyword" clearable placeholder="单号 / 客户 / 品牌 / 型号" style="width: 240px" @keyup.enter="reload" />
        <el-select v-model="filters.progress" clearable placeholder="处理进度" style="width: 130px" @change="reload">
          <el-option v-for="item in progressOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-date-picker v-model="filters.dates" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="退货开始日期" end-placeholder="退货结束日期" style="width: 260px" @change="reload" />
        <el-button @click="reload">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </div>

      <div ref="tableHostRef" class="admin-table-host">
        <el-table
          ref="afterSalesTableRef"
          v-loading="loading"
          :data="rows"
          border
          stripe
          row-key="id"
          class="after-sales-table"
          style="width: 100%"
          :max-height="tableMaxHeight"
          @header-dragend="onHeaderDragend"
        >
        <el-table-column prop="return_date" column-key="return_date" label="退货日期" :width="colWidth('return_date', 108)" resizable />
        <el-table-column prop="return_no" column-key="return_no" label="退货单号" :width="colWidth('return_no', 140)" show-overflow-tooltip resizable />
        <el-table-column prop="customer_name" column-key="customer_name" label="客户" :width="colWidth('customer_name', 120)" show-overflow-tooltip resizable />
        <el-table-column prop="customer_brand" column-key="customer_brand" label="客户品牌" :width="colWidth('customer_brand', 110)" show-overflow-tooltip resizable />
        <el-table-column prop="customer_model" column-key="customer_model" label="客户型号" :width="colWidth('customer_model', 110)" show-overflow-tooltip resizable />
        <el-table-column prop="factory_model" column-key="factory_model" label="工厂型号" :width="colWidth('factory_model', 110)" show-overflow-tooltip resizable />
        <el-table-column column-key="product_image" label="图片" :width="colWidth('product_image', 70)" align="center" resizable>
          <template #default="{ row }"><el-image v-if="row.product_image_url" :src="row.product_image_url" :preview-src-list="[row.product_image_url]" preview-teleported fit="cover" class="table-thumb" /><span v-else class="muted">—</span></template>
        </el-table-column>
        <el-table-column prop="color" column-key="color" label="颜色" :width="colWidth('color', 82)" show-overflow-tooltip resizable />
        <el-table-column label="码数" align="center">
          <el-table-column v-for="size in sizeHeaders" :key="size" :column-key="`size_${size}`" :label="size" :width="colWidth(`size_${size}`, 62)" align="center" resizable>
            <template #default="{ row }">{{ sizeQuantity(row, size) }}</template>
          </el-table-column>
        </el-table-column>
        <el-table-column prop="carton_count" column-key="carton_count" label="箱数" :width="colWidth('carton_count', 65)" align="right" resizable />
        <el-table-column prop="quantity" column-key="quantity" label="总数量(双)" :width="colWidth('quantity', 98)" align="right" resizable />
        <el-table-column column-key="unit_price" label="单价" :width="colWidth('unit_price', 90)" align="right" resizable><template #default="{ row }">¥{{ money(row.unit_price) }}</template></el-table-column>
        <el-table-column column-key="total_price" label="总价" :width="colWidth('total_price', 105)" align="right" resizable><template #default="{ row }">¥{{ money(row.total_price) }}</template></el-table-column>
        <el-table-column column-key="return_photos" label="退货图" :width="colWidth('return_photos', 76)" align="center" resizable>
          <template #default="{ row }"><el-image v-if="row.return_photo_urls?.length" :src="row.return_photo_urls[0]" :preview-src-list="row.return_photo_urls" preview-teleported fit="cover" class="table-thumb" /><span v-else class="muted">—</span></template>
        </el-table-column>
        <el-table-column prop="return_reason" column-key="return_reason" label="退货原因" :width="colWidth('return_reason', 150)" show-overflow-tooltip resizable />
        <el-table-column label="处理方案" align="center">
          <template #header>
            <div class="handling-group-header">
              <span>处理方案</span>
              <span class="group-resize-handle" title="拖动调整处理方案宽度" @mousedown.stop.prevent="startHandlingGroupResize" />
            </div>
          </template>
          <el-table-column prop="return_quantity" column-key="return_quantity" label="退款(双)" :width="colWidth('return_quantity', 88)" align="right" resizable />
          <el-table-column prop="repair_quantity" column-key="repair_quantity" label="返修(双)" :width="colWidth('repair_quantity', 86)" align="right" resizable />
          <el-table-column prop="remake_quantity" column-key="remake_quantity" label="重做(双)" :width="colWidth('remake_quantity', 86)" align="right" resizable />
        </el-table-column>
        <el-table-column column-key="warehouse" label="仓库" :width="colWidth('warehouse', 92)" align="center" resizable>
          <template #default="{ row }">
            <el-popover
              v-if="row.remake_execution_header_id"
              placement="bottom"
              :width="580"
              trigger="hover"
              :show-after="200"
              :hide-after="200"
              popper-class="after-sales-warehouse-popper"
              @show="onWarehouseKitShow(row)"
            >
              <template #reference>
                <el-tag
                  size="small"
                  :type="materialStatusTag(row)"
                  effect="plain"
                  class="after-sales-warehouse-tag"
                >
                  {{ materialStatusText(row) }}
                </el-tag>
              </template>
              <div v-loading="warehouseKitLoadingId === Number(row.remake_execution_header_id)" class="as-wh-kit">
                <div class="as-wh-kit-head">
                  <strong>重做用料 · {{ warehouseKitOf(row)?.header_no || row.return_no }}</strong>
                  <span v-if="warehouseKitOf(row)?.kit_ready_date" class="muted">
                    预计齐套 {{ warehouseKitOf(row)?.kit_ready_date }}
                  </span>
                </div>
                <div class="as-wh-kit-body">
                  <div v-if="!warehouseKitSegments(row).length" class="muted as-wh-kit-empty">
                    {{ warehouseKitLoadingId === Number(row.remake_execution_header_id) ? '加载中…' : '暂无用料' }}
                  </div>
                  <div v-for="seg in warehouseKitSegments(row)" :key="seg.key" class="as-wh-kit-seg">
                    <div class="as-wh-kit-seg-head">
                      <strong>{{ seg.label }}</strong>
                      <el-tag size="small" :type="seg.shortageCount ? 'danger' : 'success'" effect="plain">
                        {{ seg.shortageCount ? `缺 ${seg.shortageCount} 项` : '齐套' }}
                      </el-tag>
                    </div>
                    <el-table :data="seg.lines" size="small" border :row-class-name="warehouseKitRowClass">
                      <el-table-column prop="supplier_product_code" label="物料" min-width="100" show-overflow-tooltip />
                      <el-table-column prop="supplier_product_name" label="名称" min-width="110" show-overflow-tooltip />
                      <el-table-column label="尺码" width="56" align="center">
                        <template #default="{ row: ln }">{{ ln.size_value || '—' }}</template>
                      </el-table-column>
                      <el-table-column label="需求" width="64" align="right">
                        <template #default="{ row: ln }">{{ formatMatQty(ln.required_qty) }}</template>
                      </el-table-column>
                      <el-table-column label="缺口" width="64" align="right">
                        <template #default="{ row: ln }">
                          <strong :class="Number(ln.shortage_qty) > 0 ? 'shortage-text' : 'muted'">
                            {{ formatMatQty(ln.shortage_qty) }}
                          </strong>
                        </template>
                      </el-table-column>
                      <el-table-column label="预计到货" width="100" align="center">
                        <template #default="{ row: ln }">
                          <span v-if="Number(ln.shortage_qty) > 0">{{ ln.expected_ready_date || '—' }}</span>
                          <span v-else class="muted">—</span>
                        </template>
                      </el-table-column>
                    </el-table>
                  </div>
                </div>
              </div>
            </el-popover>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column column-key="progress" label="处理进度" :width="colWidth('progress', 100)" align="center" resizable>
          <template #default="{ row }"><el-tag :type="progressType(row.progress)" effect="plain">{{ progressLabel(row.progress) }}</el-tag></template>
        </el-table-column>
        <el-table-column column-key="actual_refund_amount" label="实际退款" :width="colWidth('actual_refund_amount', 100)" align="right" resizable>
          <template #default="{ row }">¥{{ money(row.actual_refund_amount) }}</template>
        </el-table-column>
        <el-table-column column-key="loss_amount" label="损失金额" :width="colWidth('loss_amount', 110)" align="right" resizable><template #default="{ row }">¥{{ money(row.loss_amount) }}</template></el-table-column>
        <el-table-column column-key="actions" label="操作" width="72" fixed="right" align="center" :resizable="false">
          <template #default="{ row }">
            <el-dropdown trigger="click" @command="handleRowCommand($event, row)">
              <el-button link class="more-action" aria-label="更多操作">•••</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="refund">退款</el-dropdown-item>
                  <el-dropdown-item command="repair">返修</el-dropdown-item>
                  <el-dropdown-item command="remake">{{ row.remake_execution_header_id ? '查看重做生产单' : '重做' }}</el-dropdown-item>
                  <el-dropdown-item divided command="edit">编辑</el-dropdown-item>
                  <el-dropdown-item command="delete">删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
        </el-table>
      </div>

      <div class="admin-pagination">
        <el-pagination
          v-model:current-page="filters.page"
          v-model:page-size="filters.page_size"
          background
          layout="total, sizes, prev, pager, next"
          :page-sizes="[20, 50, 100]"
          :total="total"
          @current-change="load"
          @size-change="() => { filters.page = 1; void load() }"
        />
      </div>
    </div>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑退货售后' : '新增退货售后'" width="920px" destroy-on-close append-to-body>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="92px" @submit.prevent>
        <div class="form-grid">
          <el-form-item label="退货日期" prop="return_date"><el-date-picker v-model="form.return_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" /></el-form-item>
          <el-form-item label="退货单号"><el-input v-model="form.return_no" disabled placeholder="保存后系统自动生成" /></el-form-item>
          <el-form-item label="客户" prop="customer_id">
            <el-select v-model="form.customer_id" filterable placeholder="选择客户" style="width: 100%" @change="onCustomerChange">
              <el-option v-for="item in customers" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="工厂型号" prop="source_sales_order_line_id">
            <el-select v-model="form.source_sales_order_line_id" filterable placeholder="先选择客户" style="width: 100%" :disabled="!form.customer_id" @change="onModelChange">
              <el-option v-for="item in modelOptions" :key="item.source_sales_order_line_id" :label="modelOptionLabel(item)" :value="item.source_sales_order_line_id" :disabled="!item.sizes?.length" />
            </el-select>
          </el-form-item>
          <el-form-item label="客户品牌"><el-input v-model="form.customer_brand" disabled placeholder="选择工厂型号后自动带出" /></el-form-item>
          <el-form-item label="客户型号"><el-input v-model="form.customer_model" disabled placeholder="选择工厂型号后自动带出" /></el-form-item>
          <el-form-item label="颜色"><el-input v-model="form.color" disabled placeholder="选择工厂型号后自动带出" /></el-form-item>
          <el-form-item label="产品图片">
            <el-image v-if="form.product_image_url" :src="form.product_image_url" :preview-src-list="[form.product_image_url]" preview-teleported fit="cover" class="product-preview" />
            <span v-else class="muted">选择工厂型号后自动带出</span>
          </el-form-item>
          <el-form-item label="单价"><el-input-number v-model="form.unit_price" :min="0" :precision="2" controls-position="right" style="width: 100%" disabled /></el-form-item>
          <el-form-item v-if="editingId" label="处理进度"><el-select v-model="form.progress" style="width: 100%"><el-option v-for="item in progressOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
        </div>
        <el-form-item label="退货图片">
          <div class="return-photo-editor">
            <div class="return-photo-list">
              <div v-for="(url, index) in form.return_photo_urls" :key="url" class="return-photo-item">
                <el-image :src="url" :preview-src-list="form.return_photo_urls" :initial-index="index" preview-teleported fit="cover" />
                <button type="button" class="photo-remove" title="移除图片" @click="removeReturnPhoto(index)">×</button>
              </div>
              <el-upload v-if="form.return_photo_urls.length < 9" multiple :show-file-list="false" :http-request="uploadReturnPhoto" accept="image/jpeg,image/png,image/gif,image/webp">
                <div class="return-photo-add" v-loading="uploading">+ 上传图片</div>
              </el-upload>
            </div>
            <span class="muted">最多 9 张，单张不超过 5MB</span>
          </div>
        </el-form-item>
        <el-form-item label="退货原因"><el-input v-model="form.return_reason" type="textarea" :rows="2" /></el-form-item>

        <section class="size-section">
          <div class="size-section-head">
            <div><strong>配码与箱数</strong><span class="muted">每箱配码 × 箱数 = 总数量</span></div>
          </div>
          <el-table :data="form.sizes.length ? [{}] : []" border size="small" empty-text="选择工厂型号后自动带出码数" class="size-matrix">
            <el-table-column v-for="size in formSizeHeaders" :key="size" :label="size" width="72" align="center">
              <template #default>
                <el-input-number
                  :model-value="perCartonQty(size)"
                  :min="0"
                  :controls="false"
                  size="small"
                  class="matrix-number"
                  @update:model-value="setPerCartonQty(size, $event)"
                />
              </template>
            </el-table-column>
            <el-table-column label="箱数" width="92" align="center" fixed="right">
              <template #default>
                <el-input-number v-model="form.carton_count" :min="1" :precision="0" :controls="false" size="small" class="matrix-number" @change="recalculateFromCartons" />
              </template>
            </el-table-column>
            <el-table-column label="总数量(双)" width="104" align="right" fixed="right">
              <template #default><strong>{{ form.quantity }}</strong></template>
            </el-table-column>
          </el-table>
        </section>
        <div v-if="form.quantity > 0" class="total-price-row">
          <span>总价</span>
          <strong>¥{{ money(formTotal) }}</strong>
          <small>{{ form.quantity || 0 }} 双 × ¥{{ money(form.unit_price) }}</small>
        </div>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="methodDialogVisible" :title="`${methodLabel}处理`" width="720px" append-to-body>
      <div class="method-dialog-head">
        <span>选择各码数的{{ methodLabel }}数量</span>
        <el-button v-if="activeMethod === 'return'" type="primary" plain @click="selectAllReturn">全部退款</el-button>
      </div>
      <el-table :data="methodDraft" border size="small">
        <el-table-column prop="size" label="码数" min-width="100" />
        <el-table-column prop="available" label="该码总数(双)" width="120" align="right" />
        <el-table-column label="数量(双)" width="180" align="center">
          <template #default="{ row }"><el-input-number v-model="row.quantity" :min="0" :max="row.available" :precision="0" controls-position="right" /></template>
        </el-table-column>
      </el-table>
      <el-form-item v-if="activeMethod === 'return'" label="退款金额" class="method-refund-row">
        <span class="amount-currency">¥</span>
        <el-input-number :model-value="draftRefundAmount" :precision="2" controls-position="right" disabled />
        <span class="refund-formula">数量 × 单价</span>
      </el-form-item>
      <el-form-item v-if="activeMethod === 'return'" label="实际退款" class="method-refund-row">
        <span class="amount-currency">¥</span>
        <el-input-number
          :model-value="draftActualRefundAmount"
          :min="0"
          :precision="2"
          controls-position="right"
          @update:model-value="onActualRefundInput"
        />
        <span class="refund-formula">可改；损失按此计算</span>
      </el-form-item>
      <template v-if="activeMethod === 'repair'">
        <el-form-item label="返修单价" class="method-refund-row">
          <el-input-number v-model="draftRepairUnitPrice" :min="0" :precision="2" controls-position="right" />
        </el-form-item>
        <div class="method-cost-summary"><span>返修金额</span><strong>¥{{ money(draftRepairAmount) }}</strong><small>{{ draftMethodQuantity }} 双 × ¥{{ money(draftRepairUnitPrice) }}</small></div>
      </template>
      <div v-if="activeMethod === 'remake'" class="remake-cost-summary">
        <div><span>材料成本</span><strong>¥{{ money(draftRemakeMaterialCost) }}</strong><small>{{ draftMethodQuantity }} 双 × ¥{{ money(form.remake_material_unit_cost) }}</small></div>
        <div><span>人工成本</span><strong>¥{{ money(draftRemakeLaborCost) }}</strong><small>{{ draftMethodQuantity }} 双 × ¥{{ money(form.remake_labor_unit_cost) }}</small></div>
        <div class="remake-cost-total"><span>重做金额</span><strong>¥{{ money(draftRemakeAmount) }}</strong></div>
      </div>
      <template #footer><el-button @click="methodDialogVisible = false">取消</el-button><el-button type="primary" :loading="methodSaving" @click="confirmMethod">确定</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules, type TableInstance, type UploadRequestOptions } from 'element-plus'
import { useRouter } from 'vue-router'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

type MethodKey = 'return' | 'repair' | 'remake'
type SizeRow = { size: string; quantity: number; return_quantity: number; repair_quantity: number; remake_quantity: number; per_carton_quantity?: number }
type ReturnRow = Record<string, any> & { id: number; sizes: SizeRow[] }

const progressOptions = [{ value: 'pending', label: '待处理' }, { value: 'processing', label: '处理中' }, { value: 'completed', label: '已完成' }, { value: 'cancelled', label: '已取消' }]
const router = useRouter()
const filters = reactive({ keyword: '', progress: '', dates: [] as string[], page: 1, page_size: 20 })
const rows = ref<ReturnRow[]>([])
const customers = ref<any[]>([])
const modelOptions = ref<any[]>([])
const total = ref(0)
const loading = ref(false)
const afterSalesTableRef = ref<TableInstance>()
const { colWidth, onHeaderDragend } = useTableColWidths(
  'after-sales-returns',
  afterSalesTableRef,
  { flexKey: 'return_reason', flexDefaultMin: 150, fitToContainer: true },
)
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
let stopHandlingGroupResize: (() => void) | null = null
const saving = ref(false)
const uploadPending = ref(0)
const uploading = computed(() => uploadPending.value > 0)
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref<FormInstance>()
const methodDialogVisible = ref(false)
const methodSaving = ref(false)
const methodTargetId = ref<number | null>(null)
const activeMethod = ref<MethodKey>('return')
const methodDraft = ref<Array<{ size: string; quantity: number; available: number }>>([])
const draftRepairUnitPrice = ref(0)
const draftActualRefundAmount = ref(0)
const actualRefundTouched = ref(false)
const replaceAllWithReturn = ref(false)

const blankForm = (): any => ({ return_date: new Date().toLocaleDateString('sv-SE'), return_no: '', customer_id: null, customer_name: '', source_sales_order_line_id: null, own_product_id: null, customer_brand: '', customer_model: '', factory_model: '', product_image_url: '', return_photo_urls: [] as string[], color: '', carton_count: 1, quantity: 0, return_quantity: 0, unit_price: 0, return_reason: '', refund_amount: 0, actual_refund_amount: 0, repair_quantity: 0, repair_unit_price: 0, repair_amount: 0, remake_material_unit_cost: 0, remake_labor_unit_cost: 0, remake_material_cost: 0, remake_labor_cost: 0, remake_amount: 0, loss_amount: 0, progress: 'pending', sizes: [] as SizeRow[] })
const form = reactive<any>(blankForm())
const rules: FormRules = { return_date: [{ required: true, message: '请选择退货日期', trigger: 'change' }], customer_id: [{ required: true, message: '请选择客户', trigger: 'change' }], source_sales_order_line_id: [{ required: true, message: '请选择工厂型号', trigger: 'change' }], quantity: [{ required: true, message: '请填写数量', trigger: 'change' }] }

const formTotal = computed(() => Number(form.quantity || 0) * Number(form.unit_price || 0))
const sizeTotal = computed(() => form.sizes.reduce((sum, item) => sum + Number(item.quantity || 0), 0))
const returnTotal = computed(() => form.sizes.reduce((sum, item) => sum + Number(item.return_quantity || 0), 0))
const repairTotal = computed(() => form.sizes.reduce((sum, item) => sum + Number(item.repair_quantity || 0), 0))
const methodLabel = computed(() => ({ return: '退款', repair: '返修', remake: '重做' })[activeMethod.value])
const draftMethodQuantity = computed(() => methodDraft.value.reduce((sum, item) => sum + Number(item.quantity || 0), 0))
const draftRefundAmount = computed(() => methodDraft.value.reduce((sum, item) => sum + Number(item.quantity || 0), 0) * Number(form.unit_price || 0))
const draftRepairAmount = computed(() => draftMethodQuantity.value * Number(draftRepairUnitPrice.value || 0))
const draftRemakeMaterialCost = computed(() => draftMethodQuantity.value * Number(form.remake_material_unit_cost || 0))
const draftRemakeLaborCost = computed(() => draftMethodQuantity.value * Number(form.remake_labor_unit_cost || 0))
const draftRemakeAmount = computed(() => draftRemakeMaterialCost.value + draftRemakeLaborCost.value)
const sizeHeaders = computed(() => Array.from(new Set(rows.value.flatMap(row => (row.sizes || []).map(item => item.size)))).sort((a, b) => a.localeCompare(b, 'zh', { numeric: true })))
const formSizeHeaders = computed(() => form.sizes.map((item: SizeRow) => item.size))

watch(draftRefundAmount, value => {
  if (activeMethod.value === 'return' && !actualRefundTouched.value) {
    draftActualRefundAmount.value = Number(Number(value || 0).toFixed(2))
  }
})

function onActualRefundInput(value: number | undefined) {
  actualRefundTouched.value = true
  draftActualRefundAmount.value = Number(Number(value || 0).toFixed(2))
}
function money(value: unknown) { return Number(value || 0).toFixed(2) }
function progressLabel(value: string) { return progressOptions.find(item => item.value === value)?.label || value }
function progressType(value: string) { return value === 'completed' ? 'success' : value === 'processing' ? 'warning' : value === 'cancelled' ? 'info' : 'danger' }
function sizeQuantity(row: ReturnRow, size: string) { const value = row.sizes?.find(item => item.size === size)?.quantity || 0; return value > 0 ? value : '—' }

const warehouseKitCache = ref<Record<number, any>>({})
const warehouseKitLoadingId = ref<number | null>(null)

function materialStatusText(row: ReturnRow) {
  const status = row?.kit?.material_status
  if (status === 'kit_ok') return '齐套'
  if (status === 'purchasing') return '采购中'
  if (status === 'short') return '缺材料'
  if (row?.kit?.empty_bom) return '无 BOM'
  if (row?.kit?.kit_ok) return '齐套'
  if (Number(row?.kit?.shortage_lines) > 0) return '缺材料'
  return '查看用料'
}

function materialStatusTag(row: ReturnRow): 'success' | 'warning' | 'danger' | 'info' {
  const status = row?.kit?.material_status
  if (status === 'kit_ok' || row?.kit?.kit_ok) return 'success'
  if (status === 'purchasing') return 'warning'
  if (status === 'short' || Number(row?.kit?.shortage_lines) > 0) return 'danger'
  return 'info'
}

function warehouseKitOf(row: ReturnRow) {
  const hid = Number(row.remake_execution_header_id)
  return hid ? warehouseKitCache.value[hid] || null : null
}

function warehouseKitSegments(row: ReturnRow) {
  const lines = Array.isArray(warehouseKitOf(row)?.lines) ? warehouseKitOf(row).lines : []
  if (!lines.length) return [] as Array<{ key: string; label: string; shortageCount: number; lines: any[] }>
  const groups = new Map<string, any[]>()
  for (const line of lines) {
    const label = String(line.consume_segment_name || '').trim() || '未分段'
    if (!groups.has(label)) groups.set(label, [])
    groups.get(label)!.push(line)
  }
  return [...groups.entries()].map(([label, seglines]) => {
    const sorted = [...seglines].sort((a, b) => {
      const shortageOrder = Number(b.shortage_qty || 0) - Number(a.shortage_qty || 0)
      return shortageOrder || Number(a.sort_order || 0) - Number(b.sort_order || 0)
    })
    return {
      key: label,
      label,
      shortageCount: sorted.filter(item => Number(item.shortage_qty) > 0).length,
      lines: sorted,
    }
  })
}

function warehouseKitRowClass({ row }: { row: any }) {
  return Number(row.shortage_qty) > 0 ? 'as-wh-kit-shortage' : ''
}

function formatMatQty(value: unknown) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return Number.isInteger(number) ? String(number) : number.toFixed(4).replace(/\.?0+$/, '')
}

async function onWarehouseKitShow(row: ReturnRow) {
  const hid = Number(row.remake_execution_header_id)
  if (!hid) return
  warehouseKitLoadingId.value = hid
  try {
    const res: any = await http.get(`/executions/headers/${hid}/materials`)
    warehouseKitCache.value = { ...warehouseKitCache.value, [hid]: res.data || {} }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载用料失败')
  } finally {
    if (warehouseKitLoadingId.value === hid) warehouseKitLoadingId.value = null
  }
}

function startHandlingGroupResize(event: MouseEvent) {
  stopHandlingGroupResize?.()
  const columns = (afterSalesTableRef.value as any)?.store?.states?.columns?.value || []
  const column = columns.find((item: any) => String(item.columnKey || item.property || '') === 'remake_quantity')
  if (!column) return
  const oldWidth = Number(column.realWidth || column.width || 86)
  const startX = event.clientX
  document.body.style.cursor = 'col-resize'
  const onMouseMove = () => { document.body.style.cursor = 'col-resize' }
  const cleanup = () => {
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
    document.body.style.cursor = ''
    stopHandlingGroupResize = null
  }
  const onMouseUp = (upEvent: MouseEvent) => {
    const newWidth = Math.max(32, oldWidth + upEvent.clientX - startX)
    onHeaderDragend(newWidth, oldWidth, column)
    cleanup()
  }
  stopHandlingGroupResize = cleanup
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
}

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/after-sales', { params: { keyword: filters.keyword || undefined, progress: filters.progress || undefined, date_from: filters.dates?.[0], date_to: filters.dates?.[1], page: filters.page, page_size: filters.page_size } })
    rows.value = res.data?.items || []
    total.value = res.data?.total || 0
    measureTableHeight()
  } finally { loading.value = false }
}
function reload() { filters.page = 1; void load() }
function resetFilters() { Object.assign(filters, { keyword: '', progress: '', dates: [], page: 1 }); void load() }
function openCreate() { editingId.value = null; modelOptions.value = []; Object.assign(form, blankForm()); dialogVisible.value = true }
async function openEdit(row: ReturnRow) { const boxes = Math.max(1, Number(row.carton_count) || 1); editingId.value = row.id; Object.assign(form, blankForm(), JSON.parse(JSON.stringify(row)), { sizes: (row.sizes || []).map(item => ({ ...item, return_quantity: Number(item.return_quantity || 0), repair_quantity: Number(item.repair_quantity || 0), remake_quantity: Number(item.remake_quantity || 0), per_carton_quantity: Number(item.quantity || 0) / boxes })) }); dialogVisible.value = true; await loadModelOptions(Number(row.customer_id), false) }

async function loadCustomers() {
  const res: any = await http.get('/partners', { params: { role: 'customer', active_only: true, page_size: 500 } })
  customers.value = res.data?.items || []
}
async function loadModelOptions(customerId: number, clear = true) {
  if (clear) Object.assign(form, { source_sales_order_line_id: null, own_product_id: null, factory_model: '', customer_brand: '', customer_model: '', color: '', product_image_url: '', unit_price: 0, remake_material_unit_cost: 0, remake_labor_unit_cost: 0, quantity: 0, sizes: [] })
  modelOptions.value = []
  if (!customerId) return
  const res: any = await http.get('/after-sales/options', { params: { customer_id: customerId } })
  modelOptions.value = res.data?.items || []
  if (modelOptions.value.some(item => !item.sizes?.length)) await hydrateSizesFromOrders(customerId)
  if (!modelOptions.value.some(item => item.sizes?.length)) ElMessage.warning('该客户的订单型号尚未录入配码，请先在订单管理中补充码数')
}
async function hydrateSizesFromOrders(customerId: number) {
  const res: any = await http.get('/sales-orders', { params: { customer_id: customerId, page: 1, page_size: 200 } })
  const lines = (res.data?.items || []).flatMap((order: any) => order.lines || [])
  const lineMap = new Map(lines.map((line: any) => [Number(line.id), line]))
  for (const option of modelOptions.value) {
    if (option.sizes?.length) continue
    const line: any = lineMap.get(Number(option.source_sales_order_line_id))
    if (!line) continue
    const boxes = Math.max(1, Number(line.carton_qty) || 1)
    option.sizes = (line.items || [])
      .filter((item: any) => Number(item.qty) > 0 && Number(item.qty) % boxes === 0)
      .map((item: any) => ({ size: item.size_value || String(item.size_id), quantity_per_carton: Number(item.qty) / boxes }))
  }
}
function onCustomerChange(value: number) { void loadModelOptions(Number(value)) }
function onModelChange(value: number) {
  const option = modelOptions.value.find(item => item.source_sales_order_line_id === value)
  if (!option?.sizes?.length) {
    ElMessage.warning('该型号没有配码，请先在订单管理中录入码数')
    Object.assign(form, { source_sales_order_line_id: null, quantity: 0, sizes: [] })
    return
  }
  Object.assign(form, { own_product_id: option.own_product_id, factory_model: option.factory_model || '', customer_brand: option.customer_brand || '', customer_model: option.customer_model || '', color: option.color || '', product_image_url: option.image_url || '', unit_price: Number(option.unit_price || 0), remake_material_unit_cost: Number(option.material_cost || 0), remake_labor_unit_cost: Number(option.labor_cost || 0) })
  form.sizes = option.sizes.map((item: any) => ({ size: item.size, per_carton_quantity: Number(item.quantity_per_carton || 0), quantity: 0, return_quantity: 0, repair_quantity: 0, remake_quantity: 0 }))
  recalculateFromCartons()
}
function modelOptionLabel(item: any) { return [item.factory_model, item.color, item.customer_model && `客户款 ${item.customer_model}`, item.customer_brand].filter(Boolean).join(' · ') }
function recalculateFromCartons() {
  const boxes = Math.max(1, Math.trunc(Number(form.carton_count) || 1))
  form.carton_count = boxes
  form.sizes.forEach((item: SizeRow) => {
    item.quantity = Math.max(0, Math.trunc(Number(item.per_carton_quantity) || 0)) * boxes
    let remaining = item.quantity
    item.return_quantity = Math.min(remaining, Number(item.return_quantity || 0)); remaining -= item.return_quantity
    item.repair_quantity = Math.min(remaining, Number(item.repair_quantity || 0)); remaining -= item.repair_quantity
    item.remake_quantity = Math.min(remaining, Number(item.remake_quantity || 0))
  })
  form.quantity = form.sizes.reduce((sum: number, item: SizeRow) => sum + Number(item.quantity || 0), 0)
}
function sizeItem(size: string) { return form.sizes.find((item: SizeRow) => item.size === size) as SizeRow | undefined }
function perCartonQty(size: string) { return Number(sizeItem(size)?.per_carton_quantity || 0) }
function setPerCartonQty(size: string, value: number | undefined) {
  const item = sizeItem(size)
  if (!item) return
  item.per_carton_quantity = Math.max(0, Math.trunc(Number(value) || 0))
  recalculateFromCartons()
}
function methodField(method: MethodKey) { return `${method}_quantity` as 'return_quantity' | 'repair_quantity' | 'remake_quantity' }
function openMethod(method: MethodKey) {
  activeMethod.value = method
  replaceAllWithReturn.value = false
  actualRefundTouched.value = false
  const field = methodField(method)
  methodDraft.value = form.sizes.map((item: SizeRow) => {
    const others = Number(item.return_quantity || 0) + Number(item.repair_quantity || 0) + Number(item.remake_quantity || 0) - Number(item[field] || 0)
    return { size: item.size, quantity: Number(item[field] || 0), available: Math.max(0, item.quantity - others) }
  })
  draftRepairUnitPrice.value = Number(form.repair_unit_price || 0)
  methodDialogVisible.value = true
  void nextTick(() => {
    if (method !== 'return') return
    const calculated = Number(Number(draftRefundAmount.value || 0).toFixed(2))
    const existingActual = Number(form.actual_refund_amount || 0)
    const existingRefund = Number(form.refund_amount || 0)
    if (Math.abs(existingActual - existingRefund) > 0.009) {
      draftActualRefundAmount.value = existingActual
      actualRefundTouched.value = true
    } else {
      draftActualRefundAmount.value = calculated
    }
  })
}
function openRowMethod(row: ReturnRow, method: MethodKey) {
  const boxes = Math.max(1, Number(row.carton_count) || 1)
  methodTargetId.value = row.id
  Object.assign(form, blankForm(), JSON.parse(JSON.stringify(row)), {
    sizes: (row.sizes || []).map(item => ({
      ...item,
      return_quantity: Number(item.return_quantity || 0),
      repair_quantity: Number(item.repair_quantity || 0),
      remake_quantity: Number(item.remake_quantity || 0),
      per_carton_quantity: Number(item.quantity || 0) / boxes,
    })),
  })
  openMethod(method)
}
function handleRowCommand(command: string, row: ReturnRow) {
  if (command === 'refund') openRowMethod(row, 'return')
  else if (command === 'repair') openRowMethod(row, 'repair')
  else if (command === 'remake' && row.remake_execution_header_id) void router.push({ path: '/admin/executions', query: { header_id: row.remake_execution_header_id } })
  else if (command === 'remake') openRowMethod(row, 'remake')
  else if (command === 'edit') void openEdit(row)
  else if (command === 'delete') void removeRow(row)
}
function selectAllReturn() {
  replaceAllWithReturn.value = true
  methodDraft.value.forEach(row => { row.available = Number(sizeItem(row.size)?.quantity || 0); row.quantity = row.available })
}
async function confirmMethod() {
  const field = methodField(activeMethod.value)
  for (const row of methodDraft.value) {
    const item = sizeItem(row.size)
    if (!item) continue
    if (replaceAllWithReturn.value) { item.repair_quantity = 0; item.remake_quantity = 0 }
    const others = Number(item.return_quantity || 0) + Number(item.repair_quantity || 0) + Number(item.remake_quantity || 0) - Number(item[field] || 0)
    const quantity = Math.max(0, Math.trunc(Number(row.quantity) || 0))
    if (quantity + others > item.quantity) return ElMessage.warning(`${item.size} 码的处理数量超过该码总数`)
    item[field] = quantity
  }
  if (activeMethod.value === 'return') {
    form.refund_amount = Number(draftRefundAmount.value || 0)
    form.actual_refund_amount = Number(draftActualRefundAmount.value || 0)
  }
  if (activeMethod.value === 'repair') form.repair_unit_price = Number(draftRepairUnitPrice.value || 0)
  if (!methodTargetId.value) return
  methodSaving.value = true
  try {
    const res: any = activeMethod.value === 'remake'
      ? await http.post(`/after-sales/${methodTargetId.value}/remake-production`, buildPayload())
      : await http.put(`/after-sales/${methodTargetId.value}`, buildPayload())
    const production = res.data?.production_order
    ElMessage.success(production ? `已生成重做生产单 ${production.header_no}` : `${methodLabel.value}处理已保存`)
    methodDialogVisible.value = false
    methodTargetId.value = null
    await load()
    if (production?.id) await router.push({ path: '/admin/executions', query: { header_id: production.id } })
  } finally { methodSaving.value = false }
}

async function uploadReturnPhoto(options: UploadRequestOptions) {
  if (form.return_photo_urls.length + uploadPending.value >= 9) {
    ElMessage.warning('退货图片最多上传 9 张')
    options.onError(new Error('退货图片最多上传 9 张'))
    return
  }
  uploadPending.value += 1
  try {
    const data = new FormData()
    data.append('file', options.file)
    const res: any = await http.post('/after-sales/upload', data)
    const url = res.data?.url
    if (url && !form.return_photo_urls.includes(url)) form.return_photo_urls.push(url)
    options.onSuccess(res)
  } catch (error) {
    options.onError(error as Error)
  } finally {
    uploadPending.value -= 1
  }
}
function removeReturnPhoto(index: number) { form.return_photo_urls.splice(index, 1) }

async function save() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  if (Number(form.quantity) <= 0) return ElMessage.warning('总数量必须大于 0')
  const names = form.sizes.map(item => item.size.trim()).filter(Boolean)
  if (!names.length) return ElMessage.warning('请至少添加一个码数')
  if (names.length !== form.sizes.length) return ElMessage.warning('请填写完整的码数')
  if (new Set(names).size !== names.length) return ElMessage.warning('同一码数只能填写一次')
  if (sizeTotal.value !== Number(form.quantity)) return ElMessage.warning(`各码数合计 ${sizeTotal.value} 双，与总数量 ${form.quantity} 双不一致`)
  saving.value = true
  try {
    const payload = buildPayload()
    if (editingId.value) await http.put(`/after-sales/${editingId.value}`, payload)
    else await http.post('/after-sales', payload)
    ElMessage.success('售后退货单已保存'); dialogVisible.value = false; await load()
  } finally { saving.value = false }
}

function buildPayload() {
  return { ...form, return_quantity: returnTotal.value, repair_quantity: repairTotal.value, sizes: form.sizes.map(({ size, quantity, return_quantity, repair_quantity, remake_quantity }) => ({ size: size.trim(), quantity, return_quantity, repair_quantity, remake_quantity })) }
}

async function removeRow(row: ReturnRow) { await ElMessageBox.confirm(`确定删除退货单 ${row.return_no}？`, '删除确认', { type: 'warning' }); await http.delete(`/after-sales/${row.id}`); ElMessage.success('已删除'); await load() }

onMounted(() => { void Promise.all([load(), loadCustomers()]) })
onUnmounted(() => stopHandlingGroupResize?.())
</script>

<style scoped>
.after-sales-page { min-width: 0; }
.after-sales-hero { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.admin-toolbar { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
.after-sales-table { width: 100%; }
.more-action { padding: 4px 10px; color: var(--el-text-color-primary); font-size: 18px; font-weight: 700; letter-spacing: 2px; }
.handling-group-header { position: relative; display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; }
.group-resize-handle { position: absolute; top: -12px; right: -12px; bottom: -12px; width: 10px; cursor: col-resize; }
.group-resize-handle:hover::after { position: absolute; top: 0; bottom: 0; left: 4px; width: 2px; background: var(--el-color-primary); content: ''; }
.table-thumb { width: 42px; height: 42px; border-radius: 6px; }
.product-preview { width: 92px; height: 68px; border-radius: 8px; }
.muted { color: var(--el-text-color-secondary); }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; }
.unit-hint { margin-left: 8px; color: var(--el-text-color-secondary); }
.size-section { margin-left: 92px; padding: 14px; border-radius: 10px; background: var(--el-fill-color-lighter); }
.size-section-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.size-section-head { margin-bottom: 12px; }
.size-section-head .muted { margin-left: 12px; font-size: 12px; }
.size-matrix { width: 100%; }
.matrix-number { width: 58px; }
.matrix-number :deep(.el-input__inner) { padding: 0 4px; text-align: center; }
.method-dialog-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.method-refund-row { margin-top: 18px; margin-bottom: 0; }
.method-refund-row :deep(.el-form-item__content) { display: flex; align-items: center; flex-wrap: wrap; gap: 0; }
.amount-currency { margin-right: 4px; color: var(--el-text-color-regular); font-weight: 600; }
.refund-formula { margin-left: 10px; color: var(--el-text-color-secondary); font-size: 12px; }
.method-cost-summary { display: flex; align-items: baseline; justify-content: flex-end; gap: 10px; margin-top: 12px; padding: 12px 16px; border-radius: 8px; background: var(--el-fill-color-lighter); }
.method-cost-summary strong, .remake-cost-summary strong { color: var(--el-color-primary); font-size: 18px; }
.method-cost-summary small, .remake-cost-summary small { color: var(--el-text-color-secondary); }
.remake-cost-summary { display: grid; gap: 8px; margin-top: 18px; padding: 14px 16px; border-radius: 8px; background: var(--el-fill-color-lighter); }
.remake-cost-summary > div { display: flex; align-items: baseline; gap: 10px; }
.remake-cost-summary > div strong { margin-left: auto; }
.remake-cost-total { margin-top: 4px; padding-top: 10px; border-top: 1px solid var(--el-border-color-lighter); font-weight: 700; }
.return-photo-editor { width: 100%; }
.return-photo-list { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 6px; }
.return-photo-item { position: relative; width: 88px; height: 72px; overflow: hidden; border-radius: 8px; }
.return-photo-item :deep(.el-image) { width: 100%; height: 100%; }
.photo-remove { position: absolute; top: 3px; right: 3px; width: 22px; height: 22px; padding: 0; border: 0; border-radius: 50%; background: rgb(0 0 0 / 58%); color: #fff; cursor: pointer; line-height: 22px; }
.return-photo-add { width: 88px; height: 72px; display: grid; place-items: center; border: 1px dashed var(--el-border-color); border-radius: 8px; color: var(--el-text-color-secondary); cursor: pointer; }
.return-photo-add:hover { border-color: var(--el-color-primary); color: var(--el-color-primary); }
.total-price-row { display: flex; align-items: baseline; justify-content: flex-end; gap: 12px; margin-top: 18px; padding: 14px 18px; border-radius: 10px; background: var(--el-fill-color-lighter); }
.total-price-row > span { color: var(--el-text-color-regular); font-weight: 600; }
.total-price-row > strong { color: var(--el-color-primary); font-size: 24px; }
.total-price-row > small { color: var(--el-text-color-secondary); }
@media (max-width: 780px) { .form-grid { grid-template-columns: 1fr; } .size-section { margin-left: 0; } }
.after-sales-warehouse-tag { cursor: help; }
</style>

<style>
.after-sales-warehouse-popper.el-popover {
  max-width: min(92vw, 600px);
  padding: 10px 12px;
}
.as-wh-kit-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 13px;
}
.as-wh-kit-body {
  max-height: min(60vh, 420px);
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 2px;
}
.as-wh-kit-empty { padding: 12px 0; text-align: center; }
.as-wh-kit-seg + .as-wh-kit-seg { margin-top: 10px; }
.as-wh-kit-seg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
  font-size: 12px;
}
.after-sales-warehouse-popper .as-wh-kit-shortage td {
  background: var(--el-color-danger-light-9) !important;
}
.after-sales-warehouse-popper .shortage-text { color: var(--el-color-danger); }
.after-sales-warehouse-popper .muted { color: var(--el-text-color-placeholder); }
</style>
