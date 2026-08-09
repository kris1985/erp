<template>
  <div class="admin-card">
    <div class="admin-toolbar">
      <el-button type="primary" @click="openCreate">新增工序</el-button>
    </div>
    <div ref="tableHostRef">
    <el-table :data="rows" stripe border :max-height="tableMaxHeight" @header-dragend="onHeaderDragend">
      <el-table-column prop="id" label="ID" :width="colWidth('id', 70)" resizable />
      <el-table-column prop="name" label="名称" resizable />
      <el-table-column prop="type" label="类型" :width="colWidth('type', 100)" resizable />
      <el-table-column prop="sort_order" label="排序" :width="colWidth('sort_order', 80)" resizable />
      <el-table-column column-key="status" label="状态" :width="colWidth('status', 90)" resizable>
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column column-key="actions" label="操作" :width="colWidth('actions', 220)" resizable>
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link @click="toggleActive(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    </div>

    <el-dialog v-model="visible" :title="form.id ? '编辑工序' : '新增工序'" width="480px">
      <el-form label-width="90px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type" style="width: 100%">
            <el-option label="个人" value="personal" />
            <el-option label="集体" value="group" />
          </el-select>
        </el-form-item>
        <el-form-item label="排序"><el-input-number v-model="form.sort_order" :min="0" /></el-form-item>
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
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { colWidth, onHeaderDragend } = useTableColWidths('processes-list')
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const rows = ref<any[]>([])
const visible = ref(false)
const form = reactive<any>({
  id: null,
  name: '',
  type: 'personal',
  sort_order: 0,
})

async function load() {
  const res: any = await http.get('/processes')
  rows.value = res.data.items
}

function openCreate() {
  Object.assign(form, { id: null, name: '', type: 'personal', sort_order: rows.value.length + 1 })
  visible.value = true
}

function openEdit(row: any) {
  Object.assign(form, {
    id: row.id,
    name: row.name,
    type: row.type,
    sort_order: row.sort_order,
  })
  visible.value = true
}

function genCode() {
  return `P${Date.now().toString(36).toUpperCase()}`
}

async function save() {
  if (!String(form.name || '').trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  if (form.id) {
    await http.patch(`/processes/${form.id}`, {
      name: form.name,
      sort_order: form.sort_order,
      type: form.type,
    })
  } else {
    await http.post('/processes', {
      name: form.name.trim(),
      code: genCode(),
      default_price: 0,
      default_days: 1,
      sort_order: form.sort_order,
      type: form.type,
    })
  }
  ElMessage.success('已保存')
  visible.value = false
  await load()
}

async function toggleActive(row: any) {
  await http.patch(`/processes/${row.id}`, { is_active: !row.is_active })
  ElMessage.success('已更新')
  await load()
}

async function remove(row: any) {
  try {
    await ElMessageBox.confirm(
      `硬删工序「${row.name}」。若仍被订单/产品/报工等引用会失败，可改用停用。`,
      '删除工序',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await http.delete(`/processes/${row.id}`)
    ElMessage.success('已删除')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '删除失败')
  }
}

onMounted(async () => {
  await load()
  measureTableHeight()
})
</script>
