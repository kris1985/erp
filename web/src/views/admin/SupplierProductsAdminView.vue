<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">物料档案</h1>
        <p class="page-desc">物料目录与报价</p>
      </div>
    </header>
  <div class="admin-card">
    <div class="admin-toolbar">
      <el-input
        v-model="keyword"
        clearable
        placeholder="搜名称 / 商品编号 / 供应商 / 颜色"
        style="width: 280px"
        @clear="reloadList"
        @keyup.enter="reloadList"
      />
      <el-select
        v-model="partnerFilter"
        clearable
        filterable
        placeholder="全部供应商"
        style="width: 200px"
        @change="reloadList"
      >
        <el-option v-for="s in suppliers" :key="s.id" :label="s.name" :value="s.id" />
      </el-select>
      <div class="spacer" />
      <el-button type="primary" @click="openForm()">新增产品</el-button>
    </div>

    <div class="category-filter">
      <button
        type="button"
        class="cat-chip"
        :class="{ active: categoryFilter === null }"
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
        @click="setCategoryFilter(c.id)"
      >
        {{ c.name }}
      </button>
    </div>

    <el-table :data="rows" stripe border>
      <el-table-column label="商品图片" width="120">
        <template #default="{ row }">
          <el-image
            v-if="row.image_url"
            :src="row.image_url"
            :preview-src-list="[row.image_url]"
            fit="contain"
            class="product-thumb"
            preview-teleported
          />
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="名称" min-width="140">
        <template #default="{ row }">
          {{ row.name || '—' }}
        </template>
      </el-table-column>
      <el-table-column prop="color_name" label="颜色" width="90">
        <template #default="{ row }">
          {{ row.color_name || '—' }}
        </template>
      </el-table-column>
      <el-table-column prop="product_code" label="商品编号" min-width="120" />
      <el-table-column label="单价" width="100" align="right">
        <template #default="{ row }">
          {{ formatPrice(row.unit_price) }}
        </template>
      </el-table-column>
      <el-table-column prop="pricing_unit_name" label="计价单位" width="100">
        <template #default="{ row }">
          {{ row.pricing_unit_name || '—' }}
        </template>
      </el-table-column>
      <el-table-column prop="partner_name" label="供应商" min-width="140">
        <template #default="{ row }">
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
      </el-table-column>
      <el-table-column label="录入时间" width="170">
        <template #default="{ row }">
          {{ formatTime(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openForm(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="admin-pagination">
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

    <el-dialog v-model="visible" :title="form.id ? '编辑物料档案' : '新增物料档案'" width="520px">
      <el-form label-width="90px">
        <el-form-item label="商品编号" required>
          <el-input v-model="form.product_code" placeholder="如 SP-001" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="商品名称" />
        </el-form-item>
        <el-form-item label="分类">
          <div class="quick-select-row">
            <el-select
              v-model="form.category_id"
              clearable
              filterable
              style="flex: 1; min-width: 0"
              placeholder="选分类"
            >
              <el-option v-for="c in activeCategories" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
            <el-popover
              v-model:visible="categoryQuickVisible"
              placement="bottom-end"
              :width="280"
              trigger="click"
              @show="onQuickShow('category')"
            >
              <template #reference>
                <el-button>新增</el-button>
              </template>
              <div class="quick-add">
                <div class="quick-add-title">新增分类</div>
                <el-input
                  ref="categoryQuickInputRef"
                  v-model="newCategoryName"
                  placeholder="如：皮料、网布"
                  maxlength="40"
                  @keyup.enter="createCategoryQuick"
                />
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
        </el-form-item>
        <el-form-item label="商品图片">
          <div
            class="product-image-box"
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
              v-if="form.image_url"
              :src="form.image_url"
              fit="contain"
              class="product-preview"
            />
            <div v-else class="product-preview empty">
              <span>{{ uploading ? '上传中…' : '拖拽 / 粘贴 / 点击上传' }}</span>
            </div>
            <div v-if="imageDragging" class="product-drop-mask">松开以上传</div>
            <div v-else-if="form.image_url && !uploading" class="product-hover-hint">点击更换图片</div>
            <button
              v-if="form.image_url && !uploading"
              type="button"
              class="product-clear-btn"
              @click.stop="form.image_url = ''"
            >
              清除
            </button>
            <input
              ref="imageFileInputRef"
              type="file"
              class="product-file-input"
              accept="image/jpeg,image/png,image/gif,image/webp"
              @change="onImageFileChange"
            />
          </div>
        </el-form-item>
        <el-form-item label="单价">
          <el-input-number
            v-model="form.unit_price"
            :min="0"
            :precision="4"
            :step="0.1"
            controls-position="right"
            style="width: 100%"
            placeholder="元"
          />
        </el-form-item>
        <el-form-item label="计价单位">
          <div class="quick-select-row">
            <el-select
              v-model="form.pricing_unit_id"
              clearable
              filterable
              style="flex: 1; min-width: 0"
              placeholder="选单位"
            >
              <el-option v-for="u in activeUnits" :key="u.id" :label="u.name" :value="u.id" />
            </el-select>
            <el-popover
              v-model:visible="unitQuickVisible"
              placement="bottom-end"
              :width="280"
              trigger="click"
              @show="onQuickShow('unit')"
            >
              <template #reference>
                <el-button>新增</el-button>
              </template>
              <div class="quick-add">
                <div class="quick-add-title">新增计价单位</div>
                <el-input
                  ref="unitQuickInputRef"
                  v-model="newUnitName"
                  placeholder="如：双、码、米"
                  maxlength="20"
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
        </el-form-item>
        <el-form-item label="颜色">
          <div class="quick-select-row">
            <el-select
              v-model="form.color_id"
              clearable
              filterable
              style="flex: 1; min-width: 0"
              placeholder="选色码"
            >
              <el-option v-for="c in colors" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
            <el-popover
              v-model:visible="colorQuickVisible"
              placement="bottom-end"
              :width="280"
              trigger="click"
              @show="onQuickShow('color')"
            >
              <template #reference>
                <el-button>新增</el-button>
              </template>
              <div class="quick-add">
                <div class="quick-add-title">新增颜色</div>
                <el-input
                  ref="colorQuickInputRef"
                  v-model="newColorName"
                  placeholder="如：黑、白、卡其"
                  maxlength="20"
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
        </el-form-item>
        <el-form-item label="供应商" required>
          <el-select v-model="form.partner_id" filterable style="width: 100%" placeholder="选择供应商">
            <el-option v-for="s in suppliers" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

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
          :data="supplierContacts"
          stripe
          border
          size="small"
          empty-text="暂无联系人"
        >
          <el-table-column prop="title" label="职务" width="90">
            <template #default="{ row }">{{ row.title || '—' }}</template>
          </el-table-column>
          <el-table-column prop="name" label="姓名" width="100" />
          <el-table-column prop="mobile" label="联系方式" min-width="120">
            <template #default="{ row }">{{ row.mobile || '—' }}</template>
          </el-table-column>
          <el-table-column label="主" width="60">
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

const rows = ref<any[]>([])
const suppliers = ref<any[]>([])
const colors = ref<any[]>([])
const categories = ref<any[]>([])
const units = ref<any[]>([])
const keyword = ref('')
const categoryFilter = ref<number | null>(null)
const partnerFilter = ref<number | null>(null)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const visible = ref(false)
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
const newUnitName = ref('')
const newColorName = ref('')
const categoryQuickInputRef = ref<any>(null)
const unitQuickInputRef = ref<any>(null)
const colorQuickInputRef = ref<any>(null)
const supplierVisible = ref(false)
const supplierLoading = ref(false)
const supplierDetail = ref<any>(null)

const supplierContacts = computed(() =>
  (supplierDetail.value?.contacts || []).filter((c: any) => c.is_active !== false),
)

const form = reactive<any>({
  id: null,
  product_code: '',
  name: '',
  category_id: null,
  image_url: '',
  pricing_unit_id: null,
  unit_price: null,
  color_id: null,
  partner_id: null,
})

const activeCategories = computed(() => categories.value.filter((c) => c.is_active !== false))
const activeUnits = computed(() => units.value.filter((u) => u.is_active !== false))

function setCategoryFilter(id: number | null) {
  categoryFilter.value = id
  reloadList()
}

function reloadList() {
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

async function load() {
  const [partners, colorRes, catRes, unitRes]: any[] = await Promise.all([
    http.get('/partners', { params: { role: 'supplier', active_only: true } }),
    http.get('/colors'),
    http.get('/material-categories'),
    http.get('/pricing-units'),
  ])
  suppliers.value = partners.data.items
  colors.value = colorRes.data.items
  categories.value = catRes.data.items
  units.value = unitRes.data.items
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
  }
}

function openForm(row?: any) {
  if (row) {
    Object.assign(form, {
      id: row.id,
      product_code: row.product_code,
      name: row.name || '',
      category_id: row.category_id,
      image_url: row.image_url || '',
      pricing_unit_id: row.pricing_unit_id,
      unit_price: row.unit_price != null ? Number(row.unit_price) : null,
      color_id: row.color_id,
      partner_id: row.partner_id,
    })
  } else {
    Object.assign(form, {
      id: null,
      product_code: '',
      name: '',
      category_id: null,
      image_url: '',
      pricing_unit_id: null,
      unit_price: null,
      color_id: null,
      partner_id: suppliers.value[0]?.id || null,
    })
  }
  visible.value = true
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
    form.image_url = res.data.url
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
  if (!visible.value || uploading.value) return
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

watch(visible, (open) => {
  if (open) {
    imageDragging.value = false
    imageDragDepth.value = 0
    window.addEventListener('paste', onGlobalPaste)
  } else {
    window.removeEventListener('paste', onGlobalPaste)
  }
})

onUnmounted(() => {
  window.removeEventListener('paste', onGlobalPaste)
})

async function onQuickShow(kind: 'category' | 'unit' | 'color') {
  if (kind === 'category') {
    newCategoryName.value = ''
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
    })
    const c = res.data
    if (!categories.value.find((x) => x.id === c.id)) categories.value.push(c)
    form.category_id = c.id
    newCategoryName.value = ''
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
    form.pricing_unit_id = u.id
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
    form.color_id = c.id
    newColorName.value = ''
    colorQuickVisible.value = false
    ElMessage.success(`已添加颜色「${c.name}」`)
  } finally {
    creatingColor.value = false
  }
}

async function save() {
  if (!form.product_code.trim()) {
    ElMessage.warning('请填写商品编号')
    return
  }
  if (!form.partner_id) {
    ElMessage.warning('请选择供应商')
    return
  }
  saving.value = true
  try {
    const payload = {
      product_code: form.product_code.trim(),
      name: form.name?.trim() || null,
      category_id: form.category_id || null,
      image_url: form.image_url || null,
      pricing_unit_id: form.pricing_unit_id || null,
      unit_price: form.unit_price != null && form.unit_price !== '' ? form.unit_price : null,
      color_id: form.color_id || null,
      partner_id: form.partner_id,
    }
    if (form.id) {
      await http.patch(`/supplier-products/${form.id}`, payload)
    } else {
      await http.post('/supplier-products', payload)
    }
    ElMessage.success('已保存')
    visible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function remove(row: any) {
  await ElMessageBox.confirm(`删除产品「${row.product_code}」？`, '确认')
  await http.delete(`/supplier-products/${row.id}`)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>

<style scoped>
.quick-select-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
}

.quick-add-title {
  font-size: 13px;
  font-weight: 600;
  color: #111827;
  margin-bottom: 8px;
}

.quick-add-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}

.product-image-box {
  position: relative;
  width: 100%;
  max-width: 220px;
  cursor: pointer;
  outline: none;
  border-radius: 12px;
}

.product-image-box:hover .product-preview {
  border-color: #80baff;
  box-shadow: 0 8px 22px rgba(0, 118, 255, 0.14);
}

.product-image-box:hover .product-preview.empty {
  color: #0076ff;
  background:
    repeating-linear-gradient(
      -45deg,
      #f8fbff,
      #f8fbff 8px,
      #eef6ff 8px,
      #eef6ff 16px
    );
}

.product-image-box:hover .product-hover-hint {
  opacity: 1;
}

.product-image-box.is-dragging .product-preview {
  border-color: #0076ff;
  box-shadow: 0 0 0 2px rgba(0, 118, 255, 0.25);
}

.product-image-box.is-uploading {
  pointer-events: none;
  opacity: 0.75;
}

.product-preview {
  width: 100%;
  aspect-ratio: 1;
  border-radius: 12px;
  border: 1px dashed #d1d5db;
  background: #fff;
  display: block;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease, color 0.2s ease;
}

.product-preview.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6b7280;
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

.product-preview :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.product-drop-mask {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: rgba(0, 118, 255, 0.12);
  color: #0076ff;
  font-size: 14px;
  font-weight: 650;
  pointer-events: none;
}

.product-hover-hint {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: rgba(17, 24, 39, 0.42);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  opacity: 0;
  transition: opacity 0.2s ease;
  pointer-events: none;
}

.product-clear-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 2;
  border: none;
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 12px;
  color: #fff;
  background: rgba(17, 24, 39, 0.65);
  cursor: pointer;
}

.product-clear-btn:hover {
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
.cat-chip:hover {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}
.cat-chip.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary);
  color: #fff;
}
.product-thumb {
  width: 100%;
  aspect-ratio: 1;
  display: block;
  border-radius: 4px;
}
.product-thumb :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
</style>
