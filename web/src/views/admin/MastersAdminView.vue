<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">基础资料</h1>
        <p class="page-desc">颜色 · 尺码 · 分类 · 单位 · 职位</p>
      </div>
    </header>
  <div class="admin-card">
    <el-tabs v-model="tab">
      <el-tab-pane label="颜色" name="colors">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openColor">新增颜色</el-button>
        </div>
        <el-table :data="colors" stripe border>
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="code" label="编码" />
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button link type="primary" @click="editColor(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="尺码" name="sizes">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openSize">新增尺码</el-button>
        </div>
        <el-table :data="sizes" stripe border>
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="size_value" label="尺码" />
          <el-table-column prop="sort_order" label="排序" width="100" />
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button link type="primary" @click="editSize(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="物料分类" name="categories">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openCategory">新增分类</el-button>
          <el-button @click="seedCategories">导入常用分类</el-button>
        </div>
        <el-table :data="categories" stripe border>
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="sort_order" label="排序" width="100" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                {{ row.is_active ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button link type="primary" @click="editCategory(row)">编辑</el-button>
              <el-button link @click="toggleCategory(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="计价单位" name="units">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openUnit">新增单位</el-button>
          <el-button @click="seedUnits">导入常用单位</el-button>
        </div>
        <el-table :data="units" stripe border>
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="sort_order" label="排序" width="100" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                {{ row.is_active ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button link type="primary" @click="editUnit(row)">编辑</el-button>
              <el-button link @click="toggleUnit(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="职位" name="positions">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openPosition">新增职位</el-button>
          <el-button @click="seedPositions">导入常用职位</el-button>
        </div>
        <el-table :data="positions" stripe border>
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="sort_order" label="排序" width="100" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                {{ row.is_active ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button link type="primary" @click="editPosition(row)">编辑</el-button>
              <el-button link @click="togglePosition(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="colorVisible" :title="colorForm.id ? '编辑颜色' : '新增颜色'" width="420px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="colorForm.name" /></el-form-item>
        <el-form-item label="编码"><el-input v-model="colorForm.code" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="colorVisible = false">取消</el-button>
        <el-button type="primary" @click="saveColor">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="sizeVisible" :title="sizeForm.id ? '编辑尺码' : '新增尺码'" width="420px">
      <el-form label-width="80px">
        <el-form-item label="尺码"><el-input v-model="sizeForm.size_value" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="sizeForm.sort_order" :min="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="sizeVisible = false">取消</el-button>
        <el-button type="primary" @click="saveSize">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="categoryVisible" :title="categoryForm.id ? '编辑分类' : '新增分类'" width="420px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="categoryForm.name" placeholder="如：皮料" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="categoryForm.sort_order" :min="0" /></el-form-item>
        <el-form-item v-if="categoryForm.id" label="启用"><el-switch v-model="categoryForm.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="categoryVisible = false">取消</el-button>
        <el-button type="primary" @click="saveCategory">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="unitVisible" :title="unitForm.id ? '编辑单位' : '新增单位'" width="420px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="unitForm.name" placeholder="如：双" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="unitForm.sort_order" :min="0" /></el-form-item>
        <el-form-item v-if="unitForm.id" label="启用"><el-switch v-model="unitForm.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="unitVisible = false">取消</el-button>
        <el-button type="primary" @click="saveUnit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="positionVisible" :title="positionForm.id ? '编辑职位' : '新增职位'" width="420px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="positionForm.name" placeholder="如：针车" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="positionForm.sort_order" :min="0" /></el-form-item>
        <el-form-item v-if="positionForm.id" label="启用"><el-switch v-model="positionForm.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="positionVisible = false">取消</el-button>
        <el-button type="primary" @click="savePosition">保存</el-button>
      </template>
    </el-dialog>
  </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'

const DEFAULT_CATEGORIES = [
  '皮料',
  '面料网布',
  '超纤革',
  '鞋底中底',
  '鞋垫内里',
  '五金扣',
  '拉链',
  '线材',
  '胶水化工',
  '鞋带魔术贴',
  '装饰件',
  '包装材料',
  '模具楦头',
  '其他辅料',
]
const DEFAULT_UNITS = ['双', '米', '码', '公斤', '个', '套', '卷', '打', '片']
const DEFAULT_POSITIONS = ['裁剪', '针车', '成型', '质检', '包装', '仓管', '杂工']

const tab = ref('colors')
const colors = ref<any[]>([])
const sizes = ref<any[]>([])
const categories = ref<any[]>([])
const units = ref<any[]>([])
const positions = ref<any[]>([])

const colorVisible = ref(false)
const sizeVisible = ref(false)
const categoryVisible = ref(false)
const unitVisible = ref(false)
const positionVisible = ref(false)

const colorForm = reactive<any>({ id: null, name: '', code: '' })
const sizeForm = reactive<any>({ id: null, size_value: '', sort_order: 0 })
const categoryForm = reactive<any>({ id: null, name: '', sort_order: 0, is_active: true })
const unitForm = reactive<any>({ id: null, name: '', sort_order: 0, is_active: true })
const positionForm = reactive<any>({ id: null, name: '', sort_order: 0, is_active: true })

async function load() {
  const [c, s, cats, us, ps]: any[] = await Promise.all([
    http.get('/colors'),
    http.get('/sizes'),
    http.get('/material-categories'),
    http.get('/pricing-units'),
    http.get('/positions'),
  ])
  colors.value = c.data.items
  sizes.value = s.data.items
  categories.value = cats.data.items
  units.value = us.data.items
  positions.value = ps.data.items
}

function openColor() {
  Object.assign(colorForm, { id: null, name: '', code: '' })
  colorVisible.value = true
}
function editColor(row: any) {
  Object.assign(colorForm, row)
  colorVisible.value = true
}
async function saveColor() {
  if (colorForm.id) await http.patch(`/colors/${colorForm.id}`, { name: colorForm.name, code: colorForm.code })
  else await http.post('/colors', { name: colorForm.name, code: colorForm.code })
  ElMessage.success('已保存')
  colorVisible.value = false
  await load()
}

function openSize() {
  Object.assign(sizeForm, { id: null, size_value: '', sort_order: sizes.value.length })
  sizeVisible.value = true
}
function editSize(row: any) {
  Object.assign(sizeForm, row)
  sizeVisible.value = true
}
async function saveSize() {
  if (sizeForm.id)
    await http.patch(`/sizes/${sizeForm.id}`, { size_value: sizeForm.size_value, sort_order: sizeForm.sort_order })
  else await http.post('/sizes', { size_value: sizeForm.size_value, sort_order: sizeForm.sort_order })
  ElMessage.success('已保存')
  sizeVisible.value = false
  await load()
}

function openCategory() {
  Object.assign(categoryForm, {
    id: null,
    name: '',
    sort_order: categories.value.length,
    is_active: true,
  })
  categoryVisible.value = true
}
function editCategory(row: any) {
  Object.assign(categoryForm, { ...row })
  categoryVisible.value = true
}
async function saveCategory() {
  if (!categoryForm.name.trim()) {
    ElMessage.warning('请填写分类名称')
    return
  }
  const payload = {
    name: categoryForm.name.trim(),
    sort_order: categoryForm.sort_order,
    is_active: categoryForm.is_active,
  }
  if (categoryForm.id) await http.patch(`/material-categories/${categoryForm.id}`, payload)
  else await http.post('/material-categories', payload)
  ElMessage.success('已保存')
  categoryVisible.value = false
  await load()
}
async function toggleCategory(row: any) {
  await http.patch(`/material-categories/${row.id}`, { is_active: !row.is_active })
  await load()
}
async function seedCategories() {
  const existing = new Set(categories.value.map((x) => x.name))
  let n = 0
  for (let i = 0; i < DEFAULT_CATEGORIES.length; i++) {
    const name = DEFAULT_CATEGORIES[i]
    if (existing.has(name)) continue
    await http.post('/material-categories', { name, sort_order: i, is_active: true })
    n++
  }
  ElMessage.success(n ? `已导入 ${n} 个分类` : '常用分类已存在')
  await load()
}

function openUnit() {
  Object.assign(unitForm, { id: null, name: '', sort_order: units.value.length, is_active: true })
  unitVisible.value = true
}
function editUnit(row: any) {
  Object.assign(unitForm, { ...row })
  unitVisible.value = true
}
async function saveUnit() {
  if (!unitForm.name.trim()) {
    ElMessage.warning('请填写单位名称')
    return
  }
  const payload = {
    name: unitForm.name.trim(),
    sort_order: unitForm.sort_order,
    is_active: unitForm.is_active,
  }
  if (unitForm.id) await http.patch(`/pricing-units/${unitForm.id}`, payload)
  else await http.post('/pricing-units', payload)
  ElMessage.success('已保存')
  unitVisible.value = false
  await load()
}
async function toggleUnit(row: any) {
  await http.patch(`/pricing-units/${row.id}`, { is_active: !row.is_active })
  await load()
}
async function seedUnits() {
  const existing = new Set(units.value.map((x) => x.name))
  let n = 0
  for (let i = 0; i < DEFAULT_UNITS.length; i++) {
    const name = DEFAULT_UNITS[i]
    if (existing.has(name)) continue
    await http.post('/pricing-units', { name, sort_order: i, is_active: true })
    n++
  }
  ElMessage.success(n ? `已导入 ${n} 个单位` : '常用单位已存在')
  await load()
}

function openPosition() {
  Object.assign(positionForm, {
    id: null,
    name: '',
    sort_order: positions.value.length,
    is_active: true,
  })
  positionVisible.value = true
}
function editPosition(row: any) {
  Object.assign(positionForm, { ...row })
  positionVisible.value = true
}
async function savePosition() {
  if (!positionForm.name.trim()) {
    ElMessage.warning('请填写职位名称')
    return
  }
  const payload = {
    name: positionForm.name.trim(),
    sort_order: positionForm.sort_order,
    is_active: positionForm.is_active,
  }
  if (positionForm.id) await http.patch(`/positions/${positionForm.id}`, payload)
  else await http.post('/positions', payload)
  ElMessage.success('已保存')
  positionVisible.value = false
  await load()
}
async function togglePosition(row: any) {
  await http.patch(`/positions/${row.id}`, { is_active: !row.is_active })
  await load()
}
async function seedPositions() {
  const existing = new Set(positions.value.map((x) => x.name))
  let n = 0
  for (let i = 0; i < DEFAULT_POSITIONS.length; i++) {
    const name = DEFAULT_POSITIONS[i]
    if (existing.has(name)) continue
    await http.post('/positions', { name, sort_order: i, is_active: true })
    n++
  }
  ElMessage.success(n ? `已导入 ${n} 个职位` : '常用职位已存在')
  await load()
}

onMounted(load)
</script>
