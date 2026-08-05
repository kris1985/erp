<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">工位二维码</h1>
        <p class="page-desc">车位码 · 扫码报工</p>
      </div>
    </header>
  <div class="admin-card">
    <div class="admin-toolbar">
      <el-button type="primary" @click="openCreate">新增工位</el-button>
      <span class="muted">生成二维码后打印贴在车位；工人扫码进入报工页</span>
    </div>
    <el-table :data="rows" stripe border>
      <el-table-column prop="code" label="编码" width="100" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="process_name" label="工序" width="100" />
      <el-table-column prop="location" label="位置" width="140" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="二维码" width="120">
        <template #default="{ row }">
          <img
            v-if="row.is_active"
            :src="qrSrc(row)"
            alt="qr"
            style="width: 72px; height: 72px; cursor: pointer"
            @click="preview(row)"
          />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="downloadQr(row)">下载</el-button>
          <el-button link @click="copyLink(row)">复制链接</el-button>
          <el-button link @click="toggle(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="visible" title="新增工位" width="480px">
      <el-form label-width="90px">
        <el-form-item label="编码"><el-input v-model="form.code" placeholder="如 ZC-01" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="工序">
          <el-select v-model="form.process_id" style="width: 100%" filterable>
            <el-option v-for="p in processes" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="位置"><el-input v-model="form.location" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewVisible" :title="previewRow?.name" width="360px">
      <div style="text-align: center">
        <img v-if="previewRow" :src="qrSrc(previewRow)" style="width: 220px; height: 220px" />
        <div class="muted" style="margin-top: 8px">{{ previewRow?.scan_path }}</div>
      </div>
    </el-dialog>
  </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const rows = ref<any[]>([])
const processes = ref<any[]>([])
const visible = ref(false)
const previewVisible = ref(false)
const previewRow = ref<any>(null)
const form = reactive<any>({ code: '', name: '', process_id: null, location: '' })

function qrSrc(row: any) {
  return `/api/v1/stations/by-code/${encodeURIComponent(row.code)}/qr.png`
}

async function load() {
  const [s, p]: any[] = await Promise.all([http.get('/stations'), http.get('/processes')])
  rows.value = s.data.items
  processes.value = p.data.items.filter((x: any) => x.is_active)
}

function openCreate() {
  Object.assign(form, {
    code: '',
    name: '',
    process_id: processes.value[0]?.id || null,
    location: '',
  })
  visible.value = true
}

async function save() {
  await http.post('/stations', {
    code: form.code,
    name: form.name,
    process_id: form.process_id,
    location: form.location || null,
  })
  ElMessage.success('已保存')
  visible.value = false
  await load()
}

async function toggle(row: any) {
  await http.patch(`/stations/${row.id}`, { is_active: !row.is_active })
  await load()
}

function preview(row: any) {
  previewRow.value = row
  previewVisible.value = true
}

async function downloadQr(row: any) {
  const res = await fetch(`/api/v1/stations/${row.id}/qr.png`, {
    headers: { Authorization: `Bearer ${auth.token}` },
  })
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `station_${row.code}.png`
  a.click()
  URL.revokeObjectURL(url)
}

async function copyLink(row: any) {
  const link = `${location.origin}${row.scan_path}`
  await navigator.clipboard.writeText(link)
  ElMessage.success(`已复制 ${link}`)
}

onMounted(load)
</script>
