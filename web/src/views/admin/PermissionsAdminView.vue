<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">权限</h1>
        <p class="page-desc">当前各角色已授权矩阵 · 请在「角色」中编辑</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-select v-model="moduleFilter" clearable placeholder="模块" style="width: 140px">
          <el-option v-for="m in modules" :key="m" :label="m" :value="m" />
        </el-select>
        <el-select v-model="kindFilter" clearable placeholder="类型" style="width: 120px">
          <el-option label="菜单" value="menu" />
          <el-option label="按钮" value="button" />
        </el-select>
        <el-button type="primary" @click="$router.push('/admin/roles')">去编辑角色</el-button>
        <el-button @click="load" :loading="loading">刷新</el-button>
      </div>
      <div ref="tableHostRef">
      <el-table :data="filtered" stripe border style="width: 100%" v-loading="loading" :max-height="tableMaxHeight" @header-dragend="onHeaderDragend">
        <el-table-column prop="module" label="模块" :width="colWidth('module', 110)" resizable />
        <el-table-column column-key="type" label="类型" :width="colWidth('type', 80)" resizable>
          <template #default="{ row }">{{ row.kind === 'menu' ? '菜单' : '按钮' }}</template>
        </el-table-column>
        <el-table-column prop="name" label="权限" :width="colWidth('name', 140)" resizable />
        <el-table-column prop="code" label="编码" :width="colWidth('code', 180)" resizable />
        <el-table-column
          column-key="r_name" v-for="r in roles"
          :key="r.code"
          :label="r.name"
          :width="colWidth('r_name', 100)"
          align="center" resizable>
          <template #default="{ row }">
            <el-tag v-if="row.roles?.[r.code]" size="small" type="success">有</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { colWidth, onHeaderDragend } = useTableColWidths('permissions-list')
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const loading = ref(false)
const roles = ref<{ code: string; name: string }[]>([])
const items = ref<any[]>([])
const moduleFilter = ref('')
const kindFilter = ref('')

const modules = computed(() => {
  const set = new Set(items.value.map((i) => i.module).filter(Boolean))
  return [...set]
})

const filtered = computed(() => {
  return items.value.filter((i) => {
    if (moduleFilter.value && i.module !== moduleFilter.value) return false
    if (kindFilter.value && i.kind !== kindFilter.value) return false
    return true
  })
})

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/permissions')
    roles.value = res.data?.roles || []
    items.value = res.data?.items || []
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await load()
  measureTableHeight()
})
</script>
