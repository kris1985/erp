<template>
  <div>
    <header v-if="!embedded" class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">{{ mode === 'supplier' ? '供应商' : '客户' }}</h1>
        <p class="page-desc">{{ mode === 'supplier' ? '供应商档案与联系人' : '客户档案与联系人' }}</p>
      </div>
    </header>
  <div :class="embedded ? 'partners-panel' : 'admin-card'">
    <div class="admin-toolbar">
      <el-input
        v-model="keyword"
        clearable
        :placeholder="searchPlaceholder"
        style="width: 280px"
        @keyup.enter="search"
      />
      <el-button @click="search">查询</el-button>
      <div class="spacer" />
      <el-button type="primary" @click="openPartner()">新增{{ modeLabel }}</el-button>
    </div>

    <div ref="tableHostRef">
    <el-table
      v-if="mode === 'supplier'"
      ref="supplierTableRef"
      class="supplier-table"
      :data="supplierRows"
      stripe
      border
      style="width: 100%"
      :max-height="tableMaxHeight"
      :span-method="supplierSpanMethod"
      :row-class-name="supplierRowClass"
      @row-click="selectRow"
      @cell-mouse-enter="onSupplierCellEnter"
      @cell-mouse-leave="onSupplierCellLeave"
      @header-dragend="onSupplierHeaderDragend"
    >
      <el-table-column prop="id" label="ID" :width="colWidth('id', 70)" resizable />
      <el-table-column
        prop="name"
        column-key="company_name"
        label="公司名称"
        :width="colWidth('company_name', 140)"
        resizable
      />
      <el-table-column prop="address" label="公司地址" :width="colWidth('address', 160)" resizable>
        <template #default="{ row }">
          <span v-if="row.address">{{ row.address }}</span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="notes" label="主营业务" :width="colWidth('notes', 140)" resizable>
        <template #default="{ row }">
          <span v-if="row.notes">{{ row.notes }}</span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column column-key="title" label="职务" :width="colWidth('title', 100)" resizable>
        <template #default="{ row }">
          <span v-if="row._contact?.title">{{ row._contact.title }}</span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column column-key="contact_name" label="姓名" :width="colWidth('contact_name', 100)" resizable>
        <template #default="{ row }">
          <span v-if="row._contact?.name">{{ row._contact.name }}</span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column column-key="contact" label="联系方式" :min-width="flexColMinWidth('contact', 140)" resizable>
        <template #default="{ row }">
          <span v-if="contactPhone(row._contact)">{{ contactPhone(row._contact) }}</span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column column-key="actions" label="操作" :width="colWidth('actions', 120)" resizable>
        <template #default="{ row }">
          <el-button link type="primary" @click.stop="openPartner(row._partner)">编辑</el-button>
          <el-button link @click.stop="openContacts(row._partner)">联系人</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-table
      v-else
      ref="customerTableRef"
      :data="filteredRows"
      stripe
      border
      style="width: 100%"
      :max-height="tableMaxHeight"
      @row-click="selectRow"
      @header-dragend="onCustomerHeaderDragend"
    >
      <el-table-column prop="id" label="ID" :width="colWidth1('id', 70)" resizable />
      <el-table-column prop="name" label="名称" :width="colWidth1('name', 140)" resizable />
      <el-table-column prop="short_name" label="简称" :width="colWidth1('short_name', 100)" resizable />
      <el-table-column column-key="primary_contact" label="主联系人" :min-width="flexColMinWidth1('primary_contact', 160)" resizable>
        <template #default="{ row }">
          <span v-if="row.primary_contact">
            {{ row.primary_contact.name }}
            <span v-if="row.primary_contact.title" class="muted"> · {{ row.primary_contact.title }}</span>
            <span v-if="row.primary_contact.mobile" class="muted"> {{ row.primary_contact.mobile }}</span>
          </span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="contacts_count" label="联系人" :width="colWidth1('contacts_count', 80)" resizable />
      <el-table-column column-key="status" label="状态" :width="colWidth1('status', 80)" resizable>
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column column-key="actions" label="操作" :width="colWidth1('actions', 120)" resizable>
        <template #default="{ row }">
          <el-button link type="primary" @click.stop="openPartner(row)">编辑</el-button>
          <el-button link @click.stop="openContacts(row)">联系人</el-button>
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
        :page-sizes="[10, 20, 50, 100]"
        @current-change="load"
        @size-change="onPageSizeChange"
      />
    </div>

    <el-dialog
      v-model="partnerVisible"
      :title="partnerDialogTitle"
      width="520px"
    >
      <el-form label-width="90px">
        <el-form-item :label="mode === 'supplier' ? '公司名称' : '名称'" required>
          <el-input v-model="partnerForm.name" placeholder="公司全称" />
        </el-form-item>
        <el-form-item v-if="mode !== 'supplier'" label="简称">
          <el-input v-model="partnerForm.short_name" placeholder="下拉显示用" />
        </el-form-item>
        <el-form-item label="地址"><el-input v-model="partnerForm.address" /></el-form-item>
        <el-form-item :label="mode === 'supplier' ? '主营业务' : '备注'">
          <el-input
            v-model="partnerForm.notes"
            type="textarea"
            :rows="2"
            :placeholder="mode === 'supplier' ? '如：鞋底、中底 / 网布、超纤' : ''"
          />
        </el-form-item>
        <el-form-item v-if="partnerForm.id" label="启用">
          <el-switch v-model="partnerForm.is_active" />
        </el-form-item>
        <template v-if="!partnerForm.id">
          <el-divider content-position="left">首个联系人（可选）</el-divider>
          <el-form-item label="职务"><el-input v-model="initContact.title" placeholder="业务/跟单/财务" /></el-form-item>
          <el-form-item label="姓名"><el-input v-model="initContact.name" /></el-form-item>
          <el-form-item label="联系方式"><el-input v-model="initContact.mobile" placeholder="手机号" /></el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="partnerVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="savePartner">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="contactDrawer" :title="`联系人 · ${current?.short_name || current?.name || ''}`" size="520px">
      <div class="admin-toolbar" style="margin-bottom: 12px">
        <el-button type="primary" @click="openContact()">新增联系人</el-button>
      </div>
      <el-table :data="contacts" stripe border size="small" @header-dragend="onHeaderDragend2">
        <el-table-column prop="title" label="职务" :width="colWidth2('title', 80)" resizable />
        <el-table-column prop="name" label="姓名" :width="colWidth2('name', 90)" resizable />
        <el-table-column prop="mobile" label="联系方式" :width="colWidth2('mobile', 120)" resizable />
        <el-table-column column-key="is_primary" label="主" :width="colWidth2('is_primary', 60)" resizable>
          <template #default="{ row }">
            <el-tag v-if="row.is_primary" size="small" type="success">主</el-tag>
          </template>
        </el-table-column>
        <el-table-column column-key="actions" label="操作" :width="colWidth2('actions', 140)" resizable>
          <template #default="{ row }">
            <el-button link type="primary" @click="openContact(row)">编辑</el-button>
            <el-button link type="danger" @click="removeContact(row)">删</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-drawer>

    <el-dialog v-model="contactVisible" :title="contactForm.id ? '编辑联系人' : '新增联系人'" width="440px" append-to-body>
      <el-form label-width="80px">
        <el-form-item label="职务"><el-input v-model="contactForm.title" placeholder="业务/跟单/财务" /></el-form-item>
        <el-form-item label="姓名" required><el-input v-model="contactForm.name" /></el-form-item>
        <el-form-item label="联系方式"><el-input v-model="contactForm.mobile" placeholder="手机号" /></el-form-item>
        <el-form-item label="主联系人"><el-switch v-model="contactForm.is_primary" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="contactForm.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="contactVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveContact">保存</el-button>
      </template>
    </el-dialog>
  </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const supplierTableRef = ref<{ doLayout?: () => void } | null>(null)
const customerTableRef = ref<{ doLayout?: () => void } | null>(null)

const { colWidth, flexColMinWidth, onHeaderDragend: onSupplierHeaderDragend } =
  useTableColWidths('partners-suppliers', supplierTableRef)
const { colWidth: colWidth1, flexColMinWidth: flexColMinWidth1, onHeaderDragend: onCustomerHeaderDragend } =
  useTableColWidths('partners-customers', customerTableRef)
const { colWidth: colWidth2, onHeaderDragend: onHeaderDragend2 } = useTableColWidths('partners-contacts')
const props = withDefaults(
  defineProps<{
    mode?: 'customer_brand' | 'supplier'
    /** 嵌在「合作商」页 Tab 内时隐藏独立页头/卡片壳 */
    embedded?: boolean
  }>(),
  { mode: 'customer_brand', embedded: false },
)

const modeLabel = computed(() => (props.mode === 'supplier' ? '供应商' : '客户'))
const partnerDialogTitle = computed(() => {
  const noun = props.mode === 'supplier' ? '供应商' : '客户'
  return partnerForm.id ? `编辑${noun}` : `新增${noun}`
})
const searchPlaceholder = computed(() =>
  props.mode === 'supplier'
    ? '搜公司名称 / 地址 / 主营 / 联系人'
    : '搜名称 / 简称 / 联系人',
)
const keyword = ref('')
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const contacts = ref<any[]>([])
const current = ref<any>(null)
const partnerVisible = ref(false)
const contactDrawer = ref(false)
const contactVisible = ref(false)
const saving = ref(false)
const hoveredSupplierId = ref<number | null>(null)
let supplierHoverLeaveTimer: ReturnType<typeof setTimeout> | null = null

const partnerForm = reactive<any>({
  id: null,
  name: '',
  short_name: '',
  is_customer: false,
  is_brand: false,
  is_supplier: false,
  address: '',
  notes: '',
  is_active: true,
})
const initContact = reactive({ name: '', title: '', mobile: '' })
const contactForm = reactive<any>({
  id: null,
  name: '',
  title: '',
  mobile: '',
  is_primary: false,
  is_active: true,
})

function activeContacts(row: any) {
  return (row.contacts || []).filter((c: any) => c.is_active !== false)
}

function contactPhone(c: any) {
  if (!c) return ''
  return c.mobile || c.email || ''
}

function partnerSearchText(p: any) {
  const parts = [
    p.name,
    p.short_name,
    p.address,
    p.notes,
    p.primary_contact?.name,
    p.primary_contact?.title,
    p.primary_contact?.mobile,
  ]
  for (const c of p.contacts || []) {
    parts.push(c.name, c.title, c.mobile, c.email)
  }
  return parts.filter(Boolean).join(' ').toLowerCase()
}

const filteredRows = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((p) => partnerSearchText(p).includes(q))
})

/** 供应商列表：一个联系人一行，公司信息行合并；按公司隔行换色 */
const supplierRows = computed(() => {
  const out: any[] = []
  filteredRows.value.forEach((p, groupIdx) => {
    const stripe = groupIdx % 2 === 1
    const list = activeContacts(p)
    if (!list.length) {
      out.push({ ...p, _partner: p, _contact: null, _rowSpan: 1, _stripe: stripe })
      return
    }
    list.forEach((c: any, i: number) => {
      out.push({
        ...p,
        _partner: p,
        _contact: c,
        _rowSpan: i === 0 ? list.length : 0,
        _stripe: stripe,
      })
    })
  })
  return out
})

function supplierRowClass({ row }: { row: any }) {
  const classes = [row._stripe ? 'supplier-row--stripe' : 'supplier-row--plain']
  const pid = row._partner?.id ?? row.id
  if (hoveredSupplierId.value != null && pid === hoveredSupplierId.value) {
    classes.push('supplier-row--group-hover')
  }
  return classes.join(' ')
}

function onSupplierCellEnter(row: any) {
  if (supplierHoverLeaveTimer) {
    clearTimeout(supplierHoverLeaveTimer)
    supplierHoverLeaveTimer = null
  }
  hoveredSupplierId.value = row._partner?.id ?? row.id ?? null
}

function onSupplierCellLeave() {
  if (supplierHoverLeaveTimer) clearTimeout(supplierHoverLeaveTimer)
  supplierHoverLeaveTimer = setTimeout(() => {
    hoveredSupplierId.value = null
    supplierHoverLeaveTimer = null
  }, 40)
}

function supplierSpanMethod({ row, columnIndex }: { row: any; columnIndex: number }) {
  // 合并：ID / 公司名称 / 公司地址 / 主营业务 / 操作
  if (columnIndex === 0 || columnIndex === 1 || columnIndex === 2 || columnIndex === 3 || columnIndex === 7) {
    if (row._rowSpan > 0) return [row._rowSpan, 1]
    return [0, 0]
  }
  return [1, 1]
}

async function load() {
  const role = props.mode === 'supplier' ? 'supplier' : 'customer'
  const q = keyword.value.trim()
  const res: any = await http.get('/partners', {
    params: {
      role,
      active_only: false,
      page: q ? 1 : page.value,
      page_size: q ? 500 : pageSize.value,
    },
  })
  rows.value = res.data?.items || []
  if (q) {
    total.value = filteredRows.value.length
  } else {
    total.value = res.data?.total ?? rows.value.length
  }
  void nextTick(measureTableHeight)
}

watch(
  () => props.mode,
  () => void nextTick(measureTableHeight),
)

function search() {
  page.value = 1
  void load()
}

function onPageSizeChange() {
  page.value = 1
  void load()
}

function openPartner(row?: any) {
  if (row) {
    Object.assign(partnerForm, {
      id: row.id,
      name: row.name,
      short_name: row.short_name || '',
      is_customer: row.is_customer,
      is_brand: row.is_brand,
      is_supplier: row.is_supplier,
      address: row.address || '',
      notes: row.notes || '',
      is_active: row.is_active,
    })
  } else {
    Object.assign(partnerForm, {
      id: null,
      name: '',
      short_name: '',
      is_customer: props.mode !== 'supplier',
      is_brand: false,
      is_supplier: props.mode === 'supplier',
      address: '',
      notes: '',
      is_active: true,
    })
    Object.assign(initContact, { name: '', title: '', mobile: '' })
  }
  partnerVisible.value = true
}

async function savePartner() {
  if (!partnerForm.name.trim()) {
    ElMessage.warning(props.mode === 'supplier' ? '请填写公司名称' : '请填写名称')
    return
  }
  if (props.mode === 'supplier') {
    partnerForm.is_supplier = true
    partnerForm.is_customer = false
    partnerForm.is_brand = false
  } else {
    partnerForm.is_customer = true
    partnerForm.is_brand = false
    partnerForm.is_supplier = false
  }
  saving.value = true
  try {
    if (partnerForm.id) {
      await http.patch(`/partners/${partnerForm.id}`, {
        name: partnerForm.name,
        short_name: partnerForm.short_name || null,
        is_customer: partnerForm.is_customer,
        is_brand: partnerForm.is_brand,
        is_supplier: partnerForm.is_supplier,
        address: partnerForm.address || null,
        notes: partnerForm.notes || null,
        is_active: partnerForm.is_active,
      })
    } else {
      const contactsPayload = initContact.name.trim()
        ? [
            {
              name: initContact.name.trim(),
              title: initContact.title || null,
              mobile: initContact.mobile || null,
              is_primary: true,
            },
          ]
        : []
      await http.post('/partners', {
        name: partnerForm.name,
        short_name: partnerForm.short_name || null,
        is_customer: partnerForm.is_customer,
        is_brand: partnerForm.is_brand,
        is_supplier: partnerForm.is_supplier,
        address: partnerForm.address || null,
        notes: partnerForm.notes || null,
        contacts: contactsPayload,
      })
    }
    ElMessage.success('已保存')
    partnerVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

function selectRow(row: any) {
  openContacts(row._partner || row)
}

async function openContacts(row: any) {
  current.value = row
  const res: any = await http.get(`/partners/${row.id}/contacts`)
  contacts.value = res.data.items
  contactDrawer.value = true
}

function openContact(row?: any) {
  if (row) {
    Object.assign(contactForm, {
      id: row.id,
      name: row.name,
      title: row.title || '',
      mobile: row.mobile || '',
      is_primary: row.is_primary,
      is_active: row.is_active,
    })
  } else {
    Object.assign(contactForm, {
      id: null,
      name: '',
      title: '',
      mobile: '',
      is_primary: contacts.value.length === 0,
      is_active: true,
    })
  }
  contactVisible.value = true
}

async function saveContact() {
  if (!current.value || !contactForm.name.trim()) {
    ElMessage.warning('请填写联系人姓名')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: contactForm.name,
      title: contactForm.title || null,
      mobile: contactForm.mobile || null,
      is_primary: contactForm.is_primary,
      is_active: contactForm.is_active,
    }
    if (contactForm.id) {
      await http.patch(`/partners/${current.value.id}/contacts/${contactForm.id}`, payload)
    } else {
      await http.post(`/partners/${current.value.id}/contacts`, payload)
    }
    ElMessage.success('已保存')
    contactVisible.value = false
    await openContacts(current.value)
    await load()
  } finally {
    saving.value = false
  }
}

async function removeContact(row: any) {
  if (!current.value) return
  await ElMessageBox.confirm(`删除联系人「${row.name}」？`, '确认')
  await http.delete(`/partners/${current.value.id}/contacts/${row.id}`)
  ElMessage.success('已删除')
  await openContacts(current.value)
  await load()
}

onMounted(load)
</script>

<style scoped>
/* 按公司隔行换色：合并主单元格与联系人子行同色 */
.supplier-table :deep(.supplier-row--plain > td.el-table__cell),
.supplier-table :deep(.el-table__fixed-right .supplier-row--plain > td.el-table__cell) {
  background: #fff !important;
}
.supplier-table :deep(.supplier-row--stripe > td.el-table__cell),
.supplier-table :deep(.el-table__fixed-right .supplier-row--stripe > td.el-table__cell) {
  background: var(--el-fill-color-lighter, #fafbfd) !important;
}

/* 单行 :hover 保持原底色，避免只亮一行 */
.supplier-table :deep(.el-table__body tr.supplier-row--plain:hover > td.el-table__cell),
.supplier-table :deep(.el-table__fixed-right .supplier-row--plain:hover > td.el-table__cell) {
  background: #fff !important;
}
.supplier-table :deep(.el-table__body tr.supplier-row--stripe:hover > td.el-table__cell),
.supplier-table :deep(.el-table__fixed-right .supplier-row--stripe:hover > td.el-table__cell) {
  background: var(--el-fill-color-lighter, #fafbfd) !important;
}

/* 同一供应商多行统一高亮 */
.supplier-table :deep(.el-table__body tr.supplier-row--group-hover > td.el-table__cell),
.supplier-table :deep(.el-table__body tr.supplier-row--group-hover:hover > td.el-table__cell),
.supplier-table :deep(.el-table__fixed-right .supplier-row--group-hover > td.el-table__cell),
.supplier-table :deep(.el-table__fixed-right .supplier-row--group-hover:hover > td.el-table__cell) {
  background: var(--el-table-row-hover-bg-color, #f0f7ff) !important;
}
.partners-panel {
  min-width: 0;
}
</style>
