<template>
  <div class="partners-panel" :class="{ 'masters-readonly': !auth.hasPermission('btn.masters.write') }">
    <div class="admin-toolbar">
      <el-button type="primary" @click="openBrand">新增品牌</el-button>
      <span class="muted master-drag-hint">按住 ⋮⋮ 拖动排序</span>
    </div>
    <div ref="tableHostRef">
      <el-table
        :data="brands"
        row-key="id"
        stripe
        border
        style="width: 100%"
        :max-height="tableMaxHeight"
        :row-class-name="rowClass"
        @dragover="onDragOver"
        @drop="onDrop"
      >
        <el-table-column label="" width="44" align="center">
          <template #default="{ $index }">
            <span
              class="master-drag-handle"
              draggable="true"
              title="拖动排序"
              @dragstart="onDragStart($event, $index)"
              @dragover="onDragOver($event, $index)"
              @drop="onDrop($event, $index)"
              @dragend="onDragEnd"
            >⋮⋮</span>
          </template>
        </el-table-column>
        <el-table-column label="Logo" min-width="180">
          <template #default="{ row }">
            <div class="brand-logo-list">
              <el-image
                v-for="(url, index) in brandLogos(row)"
                :key="`${row.id}-${index}`"
                :src="url"
                :preview-src-list="brandLogos(row)"
                :initial-index="index"
                fit="contain"
                class="brand-master-logo"
                preview-teleported
              />
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="editBrand(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="visible" :title="form.id ? '编辑品牌' : '新增品牌'" width="640px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="form.name" maxlength="100" /></el-form-item>
        <el-form-item label="Logo">
          <div
            class="brand-logo-editor"
            :class="{ 'is-dragging': logoDragging, 'is-uploading': uploading }"
            @dragenter.prevent="onLogoDragEnter"
            @dragover.prevent="onLogoDragOver"
            @dragleave.prevent="onLogoDragLeave"
            @drop.prevent="onLogoDrop"
          >
            <div v-for="(url, index) in form.logo_urls" :key="`${url}-${index}`" class="brand-logo-item">
              <el-image
                :src="url"
                :preview-src-list="form.logo_urls"
                :initial-index="index"
                fit="contain"
                preview-teleported
              />
              <button type="button" class="brand-logo-remove" @click="form.logo_urls.splice(index, 1)">×</button>
            </div>
            <button type="button" class="brand-logo-add" :disabled="uploading" @click="pickLogo">
              {{ uploading ? '上传中…' : logoDragging ? '松开以上传' : '添加或拖入' }}
            </button>
          </div>
          <input ref="fileRef" type="file" accept="image/*" multiple hidden @change="onFile" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import { prepareImageForUpload } from '@/utils/imageUpload'

const auth = useAuthStore()
const { tableHostRef, tableMaxHeight } = useTableMaxHeight()
const brands = ref<any[]>([])
const visible = ref(false)
const uploading = ref(false)
const logoDragging = ref(false)
const fileRef = ref<HTMLInputElement | null>(null)
const form = reactive<any>({ id: null, name: '', logo_urls: [] as string[] })
const dragFrom = ref<number | null>(null)
const dropIndex = ref<number | null>(null)
let sortSaving = false
let logoDragDepth = 0

function brandLogos(row: any) {
  const urls = Array.isArray(row?.logo_urls) ? row.logo_urls.filter(Boolean) : []
  if (urls.length) return urls
  return row?.logo_url ? [row.logo_url] : []
}

async function load() {
  const res: any = await http.get('/brands')
  brands.value = res.data?.items || []
}

function openBrand() {
  Object.assign(form, { id: null, name: '', logo_urls: [] })
  resetLogoDrag()
  visible.value = true
}

function editBrand(row: any) {
  Object.assign(form, { id: row.id, name: row.name, logo_urls: [...brandLogos(row)] })
  resetLogoDrag()
  visible.value = true
}

function resetLogoDrag() {
  logoDragDepth = 0
  logoDragging.value = false
}

function pickLogo() {
  if (uploading.value) return
  fileRef.value?.click()
}

function onLogoDragEnter() {
  if (uploading.value) return
  logoDragDepth += 1
  logoDragging.value = true
}

function onLogoDragOver() {
  if (uploading.value) return
  logoDragging.value = true
}

function onLogoDragLeave() {
  logoDragDepth = Math.max(0, logoDragDepth - 1)
  if (logoDragDepth === 0) logoDragging.value = false
}

function onLogoDrop(event: DragEvent) {
  resetLogoDrag()
  if (uploading.value) return
  const files = Array.from(event.dataTransfer?.files || [])
  if (files.length) void uploadLogoFiles(files)
}

async function onFile(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (files.length) await uploadLogoFiles(files)
}

async function uploadLogoFiles(files: File[]) {
  const images = files.filter((file) => file.type.startsWith('image/'))
  if (!images.length) {
    ElMessage.warning('请上传图片')
    return
  }
  if (images.length < files.length) ElMessage.warning('已跳过非图片文件')
  uploading.value = true
  try {
    for (const file of images) {
      const prepared = await prepareImageForUpload(file)
      const body = new FormData()
      body.append('file', prepared)
      const res: any = await http.post('/supplier-products/upload', body, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const url = res.data?.url || ''
      if (url && !form.logo_urls.includes(url)) form.logo_urls.push(url)
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || 'Logo 上传失败')
  } finally {
    uploading.value = false
  }
}

async function save() {
  const name = String(form.name || '').trim()
  if (!name) {
    ElMessage.warning('请填写品牌名称')
    return
  }
  const payload = { name, logo_urls: form.logo_urls || [] }
  if (form.id) await http.patch(`/brands/${form.id}`, payload)
  else await http.post('/brands', { ...payload, sort_order: brands.value.length })
  ElMessage.success('已保存')
  visible.value = false
  await load()
}

function onDragStart(e: DragEvent, from: number) {
  dragFrom.value = from
  dropIndex.value = from
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(from))
  }
}

function rowIndexFromEvent(e: DragEvent) {
  const tr = (e.target as HTMLElement | null)?.closest?.('tbody tr')
  if (!tr?.parentElement) return null
  const rows = Array.from(tr.parentElement.querySelectorAll(':scope > tr'))
  const idx = rows.indexOf(tr as HTMLTableRowElement)
  return idx >= 0 ? idx : null
}

function onDragOver(e: DragEvent, to?: number) {
  if (dragFrom.value == null) return
  e.preventDefault()
  const idx = typeof to === 'number' ? to : rowIndexFromEvent(e)
  if (idx != null) dropIndex.value = idx
}

async function onDrop(e: DragEvent, to?: number) {
  e.preventDefault()
  const from = dragFrom.value
  const dropTo = typeof to === 'number' ? to : rowIndexFromEvent(e)
  dragFrom.value = null
  dropIndex.value = null
  if (from == null || dropTo == null || from === dropTo) return
  const next = [...brands.value]
  const [item] = next.splice(from, 1)
  next.splice(dropTo, 0, item)
  brands.value = next
  if (sortSaving) return
  sortSaving = true
  try {
    const jobs: Promise<unknown>[] = []
    brands.value.forEach((row, i) => {
      if (Number(row.sort_order) === i) return
      row.sort_order = i
      jobs.push(http.patch(`/brands/${row.id}`, { sort_order: i }))
    })
    if (jobs.length) await Promise.all(jobs)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '排序保存失败')
    await load()
  } finally {
    sortSaving = false
  }
}

function onDragEnd() {
  dragFrom.value = null
  dropIndex.value = null
}

function rowClass({ rowIndex }: { rowIndex: number }) {
  if (dragFrom.value == null) return ''
  if (dragFrom.value === rowIndex) return 'master-dragging-row'
  if (dropIndex.value === rowIndex) return 'master-drop-target'
  return ''
}

onMounted(() => {
  void load()
})
</script>

<style scoped>
.partners-panel {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.masters-readonly :deep(.el-button) {
  display: none;
}
.master-drag-hint {
  margin-left: 10px;
  font-size: 12px;
}
.master-drag-handle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  color: #94a3b8;
  cursor: grab;
  user-select: none;
  letter-spacing: -2px;
  font-size: 14px;
  font-weight: 700;
}
.master-drag-handle:active {
  cursor: grabbing;
  color: var(--el-color-primary);
}
:deep(.master-dragging-row > td) {
  background: #eff6ff !important;
  opacity: 0.75;
}
:deep(.master-drop-target > td) {
  box-shadow: inset 0 -2px 0 var(--el-color-primary);
}
.brand-logo-list,
.brand-logo-editor {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.brand-master-logo,
.brand-logo-item :deep(.el-image) {
  width: 36px;
  height: 36px;
}
.brand-master-logo {
  cursor: zoom-in;
}
.brand-logo-item {
  position: relative;
}
.brand-logo-remove {
  position: absolute;
  top: -6px;
  right: -6px;
  width: 16px;
  height: 16px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: #ef4444;
  color: #fff;
  line-height: 16px;
  cursor: pointer;
}
.brand-logo-editor {
  gap: 12px;
  min-height: 120px;
  padding: 8px;
  border: 1px dashed transparent;
  border-radius: 8px;
}
.brand-logo-editor.is-dragging {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.brand-logo-editor.is-uploading {
  opacity: 0.7;
}
.brand-logo-editor .brand-logo-item :deep(.el-image),
.brand-logo-add {
  width: 120px;
  height: 120px;
}
.brand-logo-add {
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
  color: var(--el-text-color-secondary);
  font-size: 14px;
  white-space: nowrap;
  cursor: pointer;
}
.brand-logo-add:disabled {
  cursor: not-allowed;
}
.brand-logo-editor .brand-logo-remove {
  width: 22px;
  height: 22px;
  line-height: 22px;
  font-size: 16px;
}
</style>
