<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">物料色卡</h1>
        <p class="page-desc">物料目录与报价 · 列表内直接编辑</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-input
          v-model="keyword"
          clearable
          :disabled="editing"
          placeholder="搜名称 / 物料编号 / 供应商 / 颜色"
          style="width: 280px"
          @clear="reloadList"
          @keyup.enter="reloadList"
        />
        <el-select
          v-model="partnerFilter"
          clearable
          filterable
          :disabled="editing"
          placeholder="全部供应商"
          style="width: 200px"
          @change="reloadList"
        >
          <el-option v-for="s in suppliers" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <div class="spacer" />
        <template v-if="editing">
          <span class="edit-hint muted">{{ modKey }}+S 保存 · Esc 取消</span>
          <el-button @click="requestCancelEdit">取消</el-button>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        </template>
        <el-button v-else type="primary" @click="startCreate">新增物料</el-button>
      </div>

      <div class="category-filter">
        <button
          type="button"
          class="cat-chip"
          :class="{ active: categoryFilter === null }"
          :disabled="editing"
          @click="setCategoryFilter(null)"
        >
          全部
        </button>
        <button
          v-for="c in activeCategories"
          :key="c.id"
          type="button"
          class="cat-chip"
          :class="{ active: categoryFilter === c.id }"
          :disabled="editing"
          @click="setCategoryFilter(c.id)"
        >
          {{ c.name }}
        </button>
      </div>

      <div ref="tableHostRef">
      <el-table
        ref="tableRef"
        :data="displayRows"
        stripe
        border
        row-key="_key"
        :max-height="tableMaxHeight"
        :row-class-name="rowClassName"
        @header-dragend="onHeaderDragend"
      >
        <el-table-column
          column-key="image"
          label="物料图片"
          :width="colWidth('image', 72)"
          align="center"
          class-name="mat-image-col"
          header-class-name="mat-image-col"
          resizable
        >
          <template #default="{ row }">
            <div
              v-if="row._editing"
              class="inline-image-box"
              :class="{ 'is-dragging': imageDragging, 'is-uploading': uploading }"
              tabindex="0"
              @dragenter.prevent="onImageDragEnter"
              @dragover.prevent="onImageDragOver"
              @dragleave.prevent="onImageDragLeave"
              @drop.prevent="onImageDrop"
              @paste="onImagePaste"
              @click="onImageZoneClick"
            >
              <el-image
                v-if="draft.image_url"
                :src="draft.image_url"
                fit="contain"
                class="product-thumb"
              />
              <span v-else class="muted mat-image-empty">{{ uploading ? '…' : '上传' }}</span>
              <div v-if="imageDragging" class="inline-drop-mask">松开</div>
              <button
                v-if="draft.image_url && !uploading"
                type="button"
                class="inline-clear-btn"
                title="清除"
                @click.stop="draft.image_url = ''"
              >
                ×
              </button>
              <input
                ref="imageFileInputRef"
                type="file"
                class="product-file-input"
                accept="image/jpeg,image/png,image/gif,image/webp"
                @change="onImageFileChange"
              />
            </div>
            <template v-else>
              <el-image
                v-if="row.image_url"
                :src="row.image_url"
                :preview-src-list="[row.image_url]"
                fit="contain"
                class="product-thumb"
                preview-teleported
              />
              <span v-else class="muted mat-image-empty"></span>
            </template>
          </template>
        </el-table-column>
        <el-table-column prop="product_code" label="物料编号" :width="colWidth('product_code', 120)" resizable>
          <template #default="{ row }">
            <el-input
              v-if="row._editing"
              v-model="draft.product_code"
              size="small"
              placeholder="如 SP-001"
            />
            <span v-else>{{ row.product_code || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" :width="colWidth('name', 140)" resizable>
          <template #default="{ row }">
            <el-input
              v-if="row._editing"
              v-model="draft.name"
              size="small"
              placeholder="物料名称"
            />
            <span v-else>{{ row.name || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="category_name" label="分类" :width="colWidth('category_name', 130)" resizable>
          <template #default="{ row }">
            <div v-if="row._editing" class="cell-select-row">
              <el-select
                v-model="draft.category_id"
                clearable
                filterable
                size="small"
                placeholder="分类"
                style="flex: 1; min-width: 0"
              >
                <el-option v-for="c in activeCategories" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
              <el-popover
                v-model:visible="categoryQuickVisible"
                placement="bottom-end"
                :width="300"
                trigger="click"
                @show="onQuickShow('category')"
              >
                <template #reference>
                  <el-button size="small" link type="primary">+</el-button>
                </template>
                <div class="quick-add">
                  <div class="quick-add-title">新增分类</div>
                  <el-input
                    ref="categoryQuickInputRef"
                    v-model="newCategoryName"
                    placeholder="如：皮料、网布"
                    maxlength="40"
                    size="small"
                    @keyup.enter="createCategoryQuick"
                  />
                  <div class="quick-add-label">默认消耗工序（可选）</div>
                  <el-select
                    v-model="newCategoryConsumeProcessId"
                    clearable
                    filterable
                    size="small"
                    placeholder="空=未标注（算首道）"
                    style="width: 100%"
                    :teleported="false"
                    :disabled="!processOptions.length"
                  >
                    <el-option
                      v-for="p in processOptions"
                      :key="p.id"
                      :label="p.name"
                      :value="p.id"
                    />
                  </el-select>
                  <div v-if="!processOptions.length" class="quick-add-hint">
                    暂无工序，请先在「工序」主数据维护
                  </div>
                  <div class="quick-add-actions">
                    <el-button size="small" @click="categoryQuickVisible = false">取消</el-button>
                    <el-button
                      type="primary"
                      size="small"
                      :loading="creatingCategory"
                      @click="createCategoryQuick"
                    >
                      添加
                    </el-button>
                  </div>
                </div>
              </el-popover>
            </div>
            <span v-else>{{ row.category_name || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="color_name" label="颜色" :width="colWidth('color_name', 120)" resizable>
          <template #default="{ row }">
            <div v-if="row._editing" class="cell-select-row">
              <el-select
                v-model="draft.color_id"
                clearable
                filterable
                size="small"
                placeholder="色码"
                style="flex: 1; min-width: 0"
              >
                <el-option v-for="c in colors" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
              <el-popover
                v-model:visible="colorQuickVisible"
                placement="bottom-end"
                :width="260"
                trigger="click"
                @show="onQuickShow('color')"
              >
                <template #reference>
                  <el-button size="small" link type="primary">+</el-button>
                </template>
                <div class="quick-add">
                  <div class="quick-add-title">新增颜色</div>
                  <el-input
                    ref="colorQuickInputRef"
                    v-model="newColorName"
                    placeholder="如：黑、白、卡其"
                    maxlength="20"
                    size="small"
                    @keyup.enter="createColorQuick"
                  />
                  <div class="quick-add-actions">
                    <el-button size="small" @click="colorQuickVisible = false">取消</el-button>
                    <el-button
                      type="primary"
                      size="small"
                      :loading="creatingColor"
                      @click="createColorQuick"
                    >
                      添加
                    </el-button>
                  </div>
                </div>
              </el-popover>
            </div>
            <span v-else>{{ row.color_name || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column column-key="unit_price" label="单价" :width="colWidth('unit_price', 110)" align="right" resizable>
          <template #default="{ row }">
            <el-input-number
              v-if="row._editing"
              v-model="draft.unit_price"
              :min="0"
              :precision="4"
              :step="0.1"
              controls-position="right"
              size="small"
              style="width: 100%"
            />
            <span v-else>{{ formatPrice(row.unit_price) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="pricing_unit_name" label="计价单位" :width="colWidth('pricing_unit_name', 120)" resizable>
          <template #default="{ row }">
            <div v-if="row._editing" class="cell-select-row">
              <el-select
                v-model="draft.pricing_unit_id"
                clearable
                filterable
                size="small"
                placeholder="单位"
                style="flex: 1; min-width: 0"
              >
                <el-option v-for="u in activeUnits" :key="u.id" :label="u.name" :value="u.id" />
              </el-select>
              <el-popover
                v-model:visible="unitQuickVisible"
                placement="bottom-end"
                :width="260"
                trigger="click"
                @show="onQuickShow('unit')"
              >
                <template #reference>
                  <el-button size="small" link type="primary">+</el-button>
                </template>
                <div class="quick-add">
                  <div class="quick-add-title">新增计价单位</div>
                  <el-input
                    ref="unitQuickInputRef"
                    v-model="newUnitName"
                    placeholder="如：双、码、米"
                    maxlength="20"
                    size="small"
                    @keyup.enter="createUnitQuick"
                  />
                  <div class="quick-add-actions">
                    <el-button size="small" @click="unitQuickVisible = false">取消</el-button>
                    <el-button
                      type="primary"
                      size="small"
                      :loading="creatingUnit"
                      @click="createUnitQuick"
                    >
                      添加
                    </el-button>
                  </div>
                </div>
              </el-popover>
            </div>
            <span v-else>{{ row.pricing_unit_name || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="partner_name" label="供应商" :width="colWidth('partner_name', 150)" resizable>
          <template #default="{ row }">
            <el-select
              v-if="row._editing"
              v-model="draft.partner_id"
              filterable
              size="small"
              placeholder="选择供应商"
              style="width: 100%"
            >
              <el-option v-for="s in suppliers" :key="s.id" :label="s.name" :value="s.id" />
            </el-select>
            <template v-else>
              <el-button
                v-if="row.partner_id"
                link
                type="primary"
                @click.stop="openSupplier(row.partner_id)"
              >
                {{ row.partner_name || '—' }}
              </el-button>
              <span v-else class="muted">—</span>
            </template>
          </template>
        </el-table-column>
        <el-table-column column-key="created_at" label="录入时间" :width="colWidth('created_at', 150)" resizable>
          <template #default="{ row }">
            {{ row._editing && editingKey === NEW_KEY ? '—' : formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column column-key="actions" label="操作" width="140" fixed="right" :resizable="false">
          <template #default="{ row }">
            <template v-if="row._editing">
              <el-button link type="primary" :loading="saving" @click="save">保存</el-button>
              <el-button link @click="requestCancelEdit">取消</el-button>
            </template>
            <template v-else>
              <el-button link type="primary" :disabled="editing" @click="startEdit(row)">编辑</el-button>
              <el-button link type="danger" :disabled="editing" @click="remove(row)">删除</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
      </div>

      <div v-if="!editing" class="admin-pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="loadProducts"
          @size-change="onPageSizeChange"
        />
      </div>

      <el-dialog
        v-model="supplierVisible"
        :title="supplierDetail?.name || '供应商信息'"
        width="560px"
      >
        <div v-loading="supplierLoading">
          <el-descriptions v-if="supplierDetail" :column="1" border>
            <el-descriptions-item label="公司名称">{{ supplierDetail.name }}</el-descriptions-item>
            <el-descriptions-item label="公司地址">
              {{ supplierDetail.address || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="主营业务">
              {{ supplierDetail.notes || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag :type="supplierDetail.is_active ? 'success' : 'info'" size="small">
                {{ supplierDetail.is_active ? '启用' : '停用' }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>

          <div class="supplier-contacts-title">联系人</div>
          <el-table
            ref="supplierContactsTableRef"
            :data="supplierContacts"
            stripe
            border
            size="small"
            empty-text="暂无联系人"
            @header-dragend="onHeaderDragend1"
          >
            <el-table-column prop="title" label="职务" :width="colWidth1('title', 90)" resizable>
              <template #default="{ row }">{{ row.title || '—' }}</template>
            </el-table-column>
            <el-table-column prop="name" label="姓名" :width="colWidth1('name', 100)" resizable />
            <el-table-column
              prop="mobile"
              label="联系方式"
              :width="colWidth1('mobile', 140)"
              resizable
            >
              <template #default="{ row }">{{ row.mobile || '—' }}</template>
            </el-table-column>
            <el-table-column column-key="is_primary" label="主" :width="colWidth1('is_primary', 60)" resizable>
              <template #default="{ row }">
                <el-tag v-if="row.is_primary" size="small" type="success">主</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <template #footer>
          <el-button type="primary" @click="supplierVisible = false">关闭</el-button>
        </template>
      </el-dialog>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const NEW_KEY = 'new' as const

const tableRef = ref<{ doLayout?: () => void } | null>(null)
const supplierContactsTableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths(
  'supplier-products-list',
  tableRef,
  {
    flexKey: 'name',
    flexDefaultMin: 140,
    fitToContainer: true,
  },
)
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1, relayoutTable: relayoutContactsTable } =
  useTableColWidths('supplier-contacts', supplierContactsTableRef, {
    flexKey: 'mobile',
    flexDefaultMin: 140,
    fitToContainer: true,
  })

const rows = ref<any[]>([])
const suppliers = ref<any[]>([])
const colors = ref<any[]>([])
const categories = ref<any[]>([])
const units = ref<any[]>([])
const processes = ref<any[]>([])
const processOptions = computed(() =>
  (processes.value || []).filter((x: any) => x && x.id && x.is_active !== false),
)
const keyword = ref('')
const categoryFilter = ref<number | null>(null)
const partnerFilter = ref<number | null>(null)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const saving = ref(false)
const uploading = ref(false)
const imageDragging = ref(false)
const imageDragDepth = ref(0)
const imageFileInputRef = ref<HTMLInputElement | null>(null)
const categoryQuickVisible = ref(false)
const unitQuickVisible = ref(false)
const colorQuickVisible = ref(false)
const creatingCategory = ref(false)
const creatingUnit = ref(false)
const creatingColor = ref(false)
const newCategoryName = ref('')
const newCategoryConsumeProcessId = ref<number | null>(null)
const newUnitName = ref('')
const newColorName = ref('')
const categoryQuickInputRef = ref<any>(null)
const unitQuickInputRef = ref<any>(null)
const colorQuickInputRef = ref<any>(null)
const supplierVisible = ref(false)
const supplierLoading = ref(false)
const supplierDetail = ref<any>(null)

const editingKey = ref<number | typeof NEW_KEY | null>(null)
const draft = reactive<any>({
  id: null,
  product_code: '',
  name: '',
  category_id: null,
  image_url: '',
  pricing_unit_id: null,
  unit_price: null,
  color_id: null,
  partner_id: null,
  created_at: null,
})

const editing = computed(() => editingKey.value != null)
const modKey = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl'

const supplierContacts = computed(() =>
  (supplierDetail.value?.contacts || []).filter((c: any) => c.is_active !== false),
)

const activeCategories = computed(() => categories.value.filter((c) => c.is_active !== false))
const activeUnits = computed(() => units.value.filter((u) => u.is_active !== false))

const displayRows = computed(() => {
  if (editingKey.value === NEW_KEY) {
    return [{ ...draft, _editing: true, _key: NEW_KEY }, ...rows.value.map(mapReadonlyRow)]
  }
  if (editingKey.value != null) {
    return rows.value.map((r) => {
      if (r.id === editingKey.value) {
        return {
          ...draft,
          id: r.id,
          created_at: r.created_at,
          _editing: true,
          _key: r.id,
        }
      }
      return mapReadonlyRow(r)
    })
  }
  return rows.value.map(mapReadonlyRow)
})

function mapReadonlyRow(r: any) {
  return { ...r, _editing: false, _key: r.id }
}

function rowClassName({ row }: { row: any }) {
  return row._editing ? 'row-editing' : ''
}

function emptyDraft(partial?: Partial<typeof draft>) {
  Object.assign(draft, {
    id: null,
    product_code: '',
    name: '',
    category_id: categoryFilter.value,
    image_url: '',
    pricing_unit_id: null,
    unit_price: null,
    color_id: null,
    partner_id: partnerFilter.value || suppliers.value[0]?.id || null,
    created_at: null,
    ...partial,
  })
}

function setCategoryFilter(id: number | null) {
  if (editing.value) return
  categoryFilter.value = id
  reloadList()
}

function reloadList() {
  if (editing.value) return
  page.value = 1
  void loadProducts()
}

function onPageSizeChange() {
  page.value = 1
  void loadProducts()
}

async function loadProducts() {
  const products: any = await http.get('/supplier-products', {
    params: {
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim() || undefined,
      partner_id: partnerFilter.value || undefined,
      category_id: categoryFilter.value || undefined,
    },
  })
  rows.value = products.data.items
  total.value = products.data.total || 0
  if (!rows.value.length && page.value > 1 && total.value > 0) {
    page.value = Math.max(1, Math.ceil(total.value / pageSize.value))
    await loadProducts()
  }
  void nextTick(() => {
    measureTableHeight()
    relayoutTable()
  })
}

function formatTime(v?: string) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 19)
}

function formatPrice(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(2)
}

async function loadProcesses() {
  const procRes: any = await http.get('/processes')
  const items = procRes?.data?.items ?? procRes?.items ?? []
  processes.value = Array.isArray(items) ? items : []
}

async function load() {
  const [partners, colorRes, catRes, unitRes]: any[] = await Promise.all([
    http.get('/partners', { params: { role: 'supplier', active_only: true, page_size: 200 } }),
    http.get('/colors'),
    http.get('/material-categories'),
    http.get('/pricing-units'),
  ])
  suppliers.value = partners.data.items
  colors.value = colorRes.data.items
  categories.value = catRes.data.items
  units.value = unitRes.data.items
  try {
    await loadProcesses()
  } catch {
    processes.value = []
  }
  await loadProducts()
}

async function openSupplier(partnerId: number) {
  supplierVisible.value = true
  supplierLoading.value = true
  supplierDetail.value = null
  try {
    const res: any = await http.get(`/partners/${partnerId}`)
    supplierDetail.value = res.data
  } finally {
    supplierLoading.value = false
    await nextTick()
    relayoutContactsTable()
  }
}

function startCreate() {
  if (editing.value) {
    ElMessage.warning('请先保存或取消当前编辑')
    return
  }
  emptyDraft()
  editingKey.value = NEW_KEY
}

function startEdit(row: any) {
  if (editing.value) {
    ElMessage.warning('请先保存或取消当前编辑')
    return
  }
  emptyDraft({
    id: row.id,
    product_code: row.product_code || '',
    name: row.name || '',
    category_id: row.category_id,
    image_url: row.image_url || '',
    pricing_unit_id: row.pricing_unit_id,
    unit_price: row.unit_price != null ? Number(row.unit_price) : null,
    color_id: row.color_id,
    partner_id: row.partner_id,
    created_at: row.created_at,
  })
  editingKey.value = row.id
}

function cancelEdit() {
  editingKey.value = null
  emptyDraft()
  imageDragging.value = false
  imageDragDepth.value = 0
}

async function requestCancelEdit() {
  try {
    await ElMessageBox.confirm('放弃未保存的修改？', '取消编辑', {
      type: 'warning',
      confirmButtonText: '放弃',
      cancelButtonText: '继续编辑',
    })
  } catch {
    return
  }
  cancelEdit()
}

async function uploadImageFile(file: File) {
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('请选择图片文件')
    return
  }
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res: any = await http.post('/supplier-products/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    draft.image_url = res.data.url
    ElMessage.success('图片已上传')
  } catch {
    ElMessage.error('图片上传失败')
  } finally {
    uploading.value = false
  }
}

function pickImageFromDataTransfer(dt: DataTransfer | null): File | null {
  if (!dt) return null
  const files = Array.from(dt.files || [])
  const img = files.find((f) => f.type.startsWith('image/'))
  if (img) return img
  const items = Array.from(dt.items || [])
  for (const item of items) {
    if (item.kind === 'file' && item.type.startsWith('image/')) {
      const f = item.getAsFile()
      if (f) return f
    }
  }
  return null
}

function onImageDragEnter() {
  imageDragDepth.value += 1
  imageDragging.value = true
}

function onImageDragOver() {
  imageDragging.value = true
}

function onImageDragLeave() {
  imageDragDepth.value = Math.max(0, imageDragDepth.value - 1)
  if (imageDragDepth.value === 0) imageDragging.value = false
}

function onImageDrop(e: DragEvent) {
  imageDragDepth.value = 0
  imageDragging.value = false
  const file = pickImageFromDataTransfer(e.dataTransfer)
  if (file) void uploadImageFile(file)
  else ElMessage.warning('请拖入图片文件')
}

function onImagePaste(e: ClipboardEvent) {
  const file = pickImageFromDataTransfer(e.clipboardData as unknown as DataTransfer)
  if (file) {
    e.preventDefault()
    void uploadImageFile(file)
  }
}

function onImageZoneClick() {
  if (uploading.value) return
  imageFileInputRef.value?.click()
}

function onImageFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) void uploadImageFile(file)
}

function onGlobalPaste(e: ClipboardEvent) {
  if (!editing.value || uploading.value) return
  const target = e.target as HTMLElement | null
  if (target) {
    const tag = target.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable) return
  }
  const file = pickImageFromDataTransfer(e.clipboardData as unknown as DataTransfer)
  if (file) {
    e.preventDefault()
    void uploadImageFile(file)
  }
}

watch(editing, (open) => {
  if (open) {
    imageDragging.value = false
    imageDragDepth.value = 0
    window.addEventListener('paste', onGlobalPaste)
  } else {
    window.removeEventListener('paste', onGlobalPaste)
  }
  void nextTick(() => {
    measureTableHeight()
    relayoutTable()
  })
})

async function onQuickShow(kind: 'category' | 'unit' | 'color') {
  if (kind === 'category') {
    newCategoryName.value = ''
    newCategoryConsumeProcessId.value = null
    if (!processOptions.value.length) {
      try {
        await loadProcesses()
      } catch {
        /* ignore */
      }
    }
    await nextTick()
    categoryQuickInputRef.value?.focus?.()
  } else if (kind === 'unit') {
    newUnitName.value = ''
    await nextTick()
    unitQuickInputRef.value?.focus?.()
  } else {
    newColorName.value = ''
    await nextTick()
    colorQuickInputRef.value?.focus?.()
  }
}

async function createCategoryQuick() {
  const name = newCategoryName.value.trim()
  if (!name) {
    ElMessage.warning('请输入分类名称')
    return
  }
  creatingCategory.value = true
  try {
    const res: any = await http.post('/material-categories', {
      name,
      sort_order: categories.value.length,
      is_active: true,
      default_consume_process_id: newCategoryConsumeProcessId.value || null,
    })
    const c = res.data
    if (!categories.value.find((x) => x.id === c.id)) categories.value.push(c)
    draft.category_id = c.id
    newCategoryName.value = ''
    newCategoryConsumeProcessId.value = null
    categoryQuickVisible.value = false
    ElMessage.success(`已添加分类「${c.name}」`)
  } finally {
    creatingCategory.value = false
  }
}

async function createUnitQuick() {
  const name = newUnitName.value.trim()
  if (!name) {
    ElMessage.warning('请输入单位名称')
    return
  }
  creatingUnit.value = true
  try {
    const res: any = await http.post('/pricing-units', {
      name,
      sort_order: units.value.length,
      is_active: true,
    })
    const u = res.data
    if (!units.value.find((x) => x.id === u.id)) units.value.push(u)
    draft.pricing_unit_id = u.id
    newUnitName.value = ''
    unitQuickVisible.value = false
    ElMessage.success(`已添加单位「${u.name}」`)
  } finally {
    creatingUnit.value = false
  }
}

async function createColorQuick() {
  const name = newColorName.value.trim()
  if (!name) {
    ElMessage.warning('请输入颜色名称')
    return
  }
  creatingColor.value = true
  try {
    const res: any = await http.post('/colors', { name })
    const c = res.data
    if (!colors.value.find((x) => x.id === c.id)) colors.value.push(c)
    draft.color_id = c.id
    newColorName.value = ''
    colorQuickVisible.value = false
    ElMessage.success(`已添加颜色「${c.name}」`)
  } finally {
    creatingColor.value = false
  }
}

async function save() {
  if (!String(draft.product_code || '').trim()) {
    ElMessage.warning('请填写物料编号')
    return
  }
  if (!draft.partner_id) {
    ElMessage.warning('请选择供应商')
    return
  }
  saving.value = true
  try {
    const payload = {
      product_code: String(draft.product_code).trim(),
      name: draft.name?.trim() || null,
      category_id: draft.category_id || null,
      image_url: draft.image_url || null,
      pricing_unit_id: draft.pricing_unit_id || null,
      unit_price: draft.unit_price != null && draft.unit_price !== '' ? draft.unit_price : null,
      color_id: draft.color_id || null,
      partner_id: draft.partner_id,
    }
    if (draft.id) {
      await http.patch(`/supplier-products/${draft.id}`, payload)
    } else {
      await http.post('/supplier-products', payload)
    }
    ElMessage.success('已保存')
    cancelEdit()
    await load()
  } finally {
    saving.value = false
  }
}

async function remove(row: any) {
  await ElMessageBox.confirm(`删除物料「${row.product_code}」？`, '确认')
  await http.delete(`/supplier-products/${row.id}`)
  ElMessage.success('已删除')
  await load()
}

function onEditHotkey(e: KeyboardEvent) {
  if (!editing.value) return
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
    e.preventDefault()
    void save()
    return
  }
  if (e.key === 'Escape') {
    if (
      document.querySelector(
        '.el-select__popper:not([aria-hidden="true"]), .el-popover:not([aria-hidden="true"])',
      )
    ) {
      return
    }
    e.preventDefault()
    void requestCancelEdit()
  }
}

onMounted(async () => {
  window.addEventListener('keydown', onEditHotkey)
  await load()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onEditHotkey)
  window.removeEventListener('paste', onGlobalPaste)
})
</script>

<style scoped>
.edit-hint {
  margin-right: 8px;
  font-size: 12px;
  line-height: 32px;
}

.cell-select-row {
  display: flex;
  align-items: center;
  gap: 2px;
  min-width: 0;
}

.quick-add-title {
  font-size: 13px;
  font-weight: 600;
  color: #111827;
  margin-bottom: 8px;
}

.quick-add-label {
  font-size: 12px;
  color: #6b7280;
  margin: 10px 0 6px;
}

.quick-add-hint {
  margin-top: 6px;
  font-size: 12px;
  color: #f59e0b;
  line-height: 1.4;
}

.quick-add-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}

.inline-image-box {
  position: relative;
  width: 100%;
  aspect-ratio: 1 / 1;
  height: auto;
  margin: 0;
  cursor: pointer;
  outline: none;
  border-radius: 4px;
  border: 1px dashed #d1d5db;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.inline-image-box:hover {
  border-color: var(--el-color-primary);
}

.inline-image-box.is-dragging {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 2px rgba(0, 118, 255, 0.2);
}

.inline-image-box.is-uploading {
  pointer-events: none;
  opacity: 0.7;
}

.inline-drop-mask {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 118, 255, 0.12);
  color: var(--el-color-primary);
  font-size: 12px;
  font-weight: 650;
  pointer-events: none;
}

.inline-clear-btn {
  position: absolute;
  top: 0;
  right: 0;
  z-index: 2;
  border: none;
  width: 18px;
  height: 18px;
  line-height: 16px;
  padding: 0;
  font-size: 14px;
  color: #fff;
  background: rgba(17, 24, 39, 0.65);
  cursor: pointer;
  border-radius: 0 0 0 4px;
}

.inline-clear-btn:hover {
  background: rgba(220, 38, 38, 0.85);
}

.product-file-input {
  display: none;
}

.supplier-contacts-title {
  margin: 16px 0 10px;
  font-weight: 600;
}

.category-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.cat-chip {
  border: 1px solid #dcdfe6;
  background: #fff;
  color: #606266;
  border-radius: 4px;
  padding: 4px 12px;
  font-size: 13px;
  line-height: 1.4;
  cursor: pointer;
}

.cat-chip:hover:not(:disabled) {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}

.cat-chip.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary);
  color: #fff;
}

.cat-chip:disabled {
  opacity: 0.55;
  cursor: not-allowed;
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
.mat-image-empty {
  line-height: 1.45;
  display: inline-block;
  font-size: 12px;
}

:deep(.el-table .row-editing > td.el-table__cell) {
  background: #f5f9ff;
}

:deep(.el-table--enable-row-hover .row-editing:hover > td.el-table__cell) {
  background: #eef5ff;
}
</style>
