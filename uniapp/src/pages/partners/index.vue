<template>
  <view class="page h5-pt" :class="{ 'h5-pt--sub': mode !== 'list' }">
    <view v-if="!canSee" class="h5-pt-empty">没有合作商权限</view>

    <template v-else-if="mode === 'list'">
      <scroll-view class="h5-pt-tabs" scroll-x :show-scrollbar="false">
        <text v-for="item in tabs" :key="item.key" :class="{ on: tab === item.key }" @click="selectTab(item.key)">{{ item.label }}</text>
      </scroll-view>
      <view class="card h5-pt-search">
        <input :value="keyword" confirm-type="search" :placeholder="searchPlaceholder" @input="onKeyword" @confirm="reload" />
        <text v-if="keyword" @click="clearKeyword">清除</text>
      </view>

      <view v-if="tab === 'brand'">
        <view v-if="!brands.length && !loading" class="h5-pt-empty">{{ keyword ? '没有匹配的品牌' : '还没有品牌' }}</view>
        <view v-for="row in brands" :key="row.id" class="card h5-pt-card h5-pt-card--brand" @click="openBrand(row)">
          <image v-if="row.logo_urls?.[0]" class="h5-pt-logo" :src="displayImageUrl(row.logo_urls[0])" mode="aspectFill" />
          <view v-else class="h5-pt-logo h5-pt-logo--empty">标</view>
          <view class="h5-pt-card__main">
            <text class="h5-pt-card__name">{{ row.name }}</text>
            <text class="h5-pt-card__meta">{{ (row.logo_urls || []).length ? `${row.logo_urls.length} 个标志` : '还没有标志' }}</text>
          </view>
        </view>
      </view>

      <view v-else>
        <view v-if="!rows.length && !loading" class="h5-pt-empty">{{ keyword ? '没有匹配的合作商' : `还没有${tabLabel}` }}</view>
        <view v-for="row in rows" :key="row.id" class="card h5-pt-card" @click="openDetail(row)">
          <view class="h5-pt-card__main">
            <view class="h5-pt-card__title">
              <text class="h5-pt-card__name">{{ row.name }}</text>
              <text v-if="row.short_name" class="h5-pt-card__short">{{ row.short_name }}</text>
              <text v-if="row.is_active === false" class="h5-defect-status pending">停用</text>
            </view>
            <text v-if="row.address" class="h5-pt-card__meta">{{ row.address }}</text>
            <text v-else-if="row.notes" class="h5-pt-card__meta">{{ row.notes }}</text>
            <text v-if="contactLabel(row)" class="h5-pt-card__meta">{{ contactLabel(row) }}</text>
          </view>
          <view v-if="callNumber(row)" class="h5-pt-dial" @click.stop="callPhone(callNumber(row))">
            <text>打电话</text>
            <strong>{{ callNumber(row) }}</strong>
          </view>
        </view>
        <view v-if="loadingMore" class="h5-pt-more">加载中…</view>
      </view>
    </template>

    <template v-else-if="mode === 'detail' && current">
      <view class="card h5-pt-detail">
        <view class="h5-pt-card__title">
          <text class="h5-pt-card__name">{{ current.name }}</text>
          <text v-if="current.is_active === false" class="h5-defect-status pending">停用</text>
        </view>
        <text v-if="current.short_name" class="h5-pt-line">简称 {{ current.short_name }}</text>
        <text v-if="current.address" class="h5-pt-line">地址 {{ current.address }}</text>
        <text v-if="current.notes" class="h5-pt-line">{{ tab === 'supplier' ? '主营' : '备注' }} {{ current.notes }}</text>
      </view>

      <view class="h5-pt-section">联系人</view>
      <view v-if="!(current.contacts || []).length" class="h5-pt-empty">还没有联系人</view>
      <view v-for="person in current.contacts" :key="person.id" class="card h5-pt-person">
        <view class="h5-pt-person__head">
          <text class="h5-pt-card__name">{{ person.name }}</text>
          <text v-if="person.title" class="h5-pt-card__short">{{ person.title }}</text>
          <text v-if="person.is_primary" class="h5-defect-status confirmed">主联系人</text>
        </view>
        <text v-if="person.wechat" class="h5-pt-line">微信 {{ person.wechat }}</text>
        <view v-if="callable(person.mobile)" class="h5-pt-dial" @click="callPhone(person.mobile)">
          <text>打电话</text>
          <strong>{{ person.mobile }}</strong>
        </view>
        <view v-if="canWrite" class="h5-pt-person__ops">
          <text @click="openContact(person)">编辑</text>
          <text class="danger" @click="removeContact(person)">删除</text>
        </view>
      </view>
    </template>

    <template v-else-if="mode === 'form'">
      <view class="card h5-pt-form">
        <text class="h5-pt-label">{{ tab === 'supplier' ? '公司名称' : '名称' }}</text>
        <input v-model="form.name" :placeholder="tab === 'supplier' ? '公司名称' : '名称'" />
        <template v-if="tab !== 'supplier'">
          <text class="h5-pt-label">简称</text>
          <input v-model="form.short_name" placeholder="选填" />
        </template>
        <text class="h5-pt-label">地址</text>
        <input v-model="form.address" placeholder="选填" />
        <text class="h5-pt-label">{{ tab === 'supplier' ? '主营业务' : '备注' }}</text>
        <textarea v-model="form.notes" auto-height placeholder="选填" />
        <view v-if="form.id" class="h5-pt-check" @click="form.is_active = !form.is_active">
          <text :class="{ on: form.is_active }">{{ form.is_active ? '启用中' : '已停用' }}</text>
        </view>
        <template v-if="!form.id">
          <text class="h5-pt-label">首位联系人</text>
          <input v-model="form.contact_name" placeholder="姓名，选填" />
          <input v-model="form.contact_title" placeholder="职务，选填" />
          <input v-model="form.contact_mobile" placeholder="电话，选填" />
        </template>
      </view>
    </template>

    <template v-else-if="mode === 'contact'">
      <view class="card h5-pt-form">
        <text class="h5-pt-label">姓名</text>
        <input v-model="contact.name" placeholder="联系人姓名" />
        <text class="h5-pt-label">职务</text>
        <input v-model="contact.title" placeholder="选填" />
        <text class="h5-pt-label">电话</text>
        <input v-model="contact.mobile" placeholder="手机号" />
        <text class="h5-pt-label">微信</text>
        <input v-model="contact.wechat" placeholder="选填" />
        <view class="h5-pt-check" @click="contact.is_primary = !contact.is_primary">
          <text :class="{ on: contact.is_primary }">{{ contact.is_primary ? '主联系人' : '设为主联系人' }}</text>
        </view>
      </view>
    </template>

    <template v-else-if="mode === 'brandForm'">
      <view class="card h5-pt-form">
        <text class="h5-pt-label">品牌名称</text>
        <input v-model="brandForm.name" placeholder="品牌名称" />
        <text class="h5-pt-label">标志</text>
        <view class="h5-pt-logos">
          <view v-for="(url, index) in brandForm.logo_urls" :key="url + index" class="h5-pt-logos__item">
            <image :src="displayImageUrl(url)" mode="aspectFill" @click="previewImage(url)" />
            <text @click="brandForm.logo_urls.splice(index, 1)">清除</text>
          </view>
        </view>
        <view class="h5-pt-photo">
          <text @click="chooseLogo('camera')">拍照</text>
          <text @click="chooseLogo('album')">从相册选择</text>
        </view>
      </view>
    </template>

    <view v-if="canSee && mode === 'list' && canWrite" class="cut-sticky-bar h5-pt-bar">
      <button class="primary-button h5-pt-primary" @click="tab === 'brand' ? openBrand() : openForm()">{{ tab === 'brand' ? '新增品牌' : `新增${tabLabel}` }}</button>
    </view>
    <view v-else-if="canSee && mode === 'detail' && canWrite" class="cut-sticky-bar h5-pt-bar">
      <button class="h5-pt-ghost" @click="openContact()">添加联系人</button>
      <button class="h5-pt-ghost" @click="openForm(current)">编辑</button>
      <button class="h5-pt-ghost h5-pt-ghost--danger" @click="removePartner">删除</button>
    </view>
    <view v-else-if="canSee && (mode === 'form' || mode === 'contact' || mode === 'brandForm')" class="cut-sticky-bar h5-pt-bar">
      <button class="h5-pt-ghost" @click="cancelSub">取消</button>
      <button v-if="mode === 'brandForm' && brandForm.id" class="h5-pt-ghost h5-pt-ghost--danger" @click="stopBrand">停用</button>
      <button class="primary-button h5-pt-primary" :disabled="saving" @click="saveSub">{{ saving ? '保存中…' : '保存' }}</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { onBackPress, onPullDownRefresh, onReachBottom, onShow } from '@dcloudio/uni-app'
import { del, get, patch, post, uploadFile } from '../../services/http'
import { getProfile } from '../../services/storage'

type TabKey = 'customer' | 'supplier' | 'subcontractor' | 'brand'
type Mode = 'list' | 'detail' | 'form' | 'contact' | 'brandForm'

const tabs: { key: TabKey; label: string }[] = [
  { key: 'customer', label: '客户' },
  { key: 'supplier', label: '供应商' },
  { key: 'subcontractor', label: '外加工厂' },
  { key: 'brand', label: '品牌' },
]

const profile = ref(getProfile())
const mode = ref<Mode>('list')
const tab = ref<TabKey>('customer')
const keyword = ref('')
const rows = ref<any[]>([])
const brands = ref<any[]>([])
const current = ref<any>(null)
const loading = ref(false)
const loadingMore = ref(false)
const saving = ref(false)
const page = ref(1)
let listFinished = false
let listSeq = 0
let searchTimer: ReturnType<typeof setTimeout> | null = null

const form = reactive({
  id: 0,
  name: '',
  short_name: '',
  address: '',
  notes: '',
  is_active: true,
  contact_name: '',
  contact_title: '',
  contact_mobile: '',
})
const contact = reactive({
  id: 0,
  name: '',
  title: '',
  mobile: '',
  wechat: '',
  is_primary: false,
})
const brandForm = reactive({
  id: 0,
  name: '',
  logo_urls: [] as string[],
})

const features = computed(() => profile.value?.featurePermissions || [])
const canSee = computed(() => features.value.includes('partners') || features.value.includes('partners_write'))
const canWrite = computed(() => features.value.includes('partners_write'))
const tabLabel = computed(() => tabs.find(item => item.key === tab.value)?.label || '合作商')
const searchPlaceholder = computed(() => (tab.value === 'brand' ? '搜品牌' : '搜名称、电话、地址'))

function toast(title: string) {
  uni.showToast({ title, icon: 'none' })
}
function ask(title: string, content: string) {
  return new Promise<boolean>(resolve => {
    uni.showModal({ title, content, success: result => resolve(!!result.confirm) })
  })
}
function displayImageUrl(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw || /^(https?:|data:|blob:)/i.test(raw)) return raw
  const path = raw.startsWith('/') ? raw : `/${raw}`
  const apiOrigin = String(import.meta.env.VITE_API_BASE_URL || '').match(/^https?:\/\/[^/]+/i)?.[0]
  return apiOrigin ? `${apiOrigin}${path}` : path
}
function previewImage(url: string) {
  const resolved = displayImageUrl(url)
  if (resolved) uni.previewImage({ urls: [resolved], current: resolved })
}
function callable(raw: unknown) {
  const text = String(raw || '').trim()
  if (!text || text.includes('@')) return ''
  const phone = text.replace(/[^\d+]/g, '')
  return phone.length >= 5 ? phone : ''
}
function callNumber(row: any) {
  const people = Array.isArray(row?.contacts) ? row.contacts : []
  const primary = people.find((item: any) => item?.is_primary && item?.is_active !== false) || row?.primary_contact
  for (const person of [primary, ...people]) {
    const phone = callable(person?.mobile)
    if (phone) return phone
  }
  return ''
}
function contactLabel(row: any) {
  const people = (row?.contacts || []).filter((item: any) => item?.is_active !== false)
  const primary = people.find((item: any) => item?.is_primary) || people[0] || row?.primary_contact
  if (!primary?.name) return people.length ? `${people.length} 位联系人` : ''
  const extra = Math.max(people.length - 1, 0)
  return extra ? `${primary.name} 等 ${people.length} 人` : primary.name
}
function callPhone(raw: unknown) {
  const phone = callable(raw)
  if (!phone) {
    toast('没有可拨打的电话')
    return
  }
  uni.makePhoneCall({
    phoneNumber: phone,
    fail(err) {
      const message = String((err as { errMsg?: string })?.errMsg || '')
      if (message.includes('cancel')) return
      toast('无法拨打电话')
    },
  })
}
function roleFlags() {
  return {
    is_customer: tab.value === 'customer',
    is_supplier: tab.value === 'supplier',
    is_subcontractor: tab.value === 'subcontractor',
    is_brand: false,
  }
}
function matches(row: any) {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return true
  const people = row.contacts || []
  const blob = [row.name, row.short_name, row.address, row.notes, ...people.flatMap((item: any) => [item.name, item.title, item.mobile, item.wechat])]
    .join(' ')
    .toLowerCase()
  return blob.includes(q)
}

async function loadList(reset = false) {
  if (!reset && (loading.value || loadingMore.value || listFinished || tab.value === 'brand' || keyword.value.trim())) return
  const seq = ++listSeq
  const searching = !!keyword.value.trim()
  if (reset) {
    page.value = 1
    listFinished = false
    loading.value = true
  } else {
    loadingMore.value = true
    page.value += 1
  }
  try {
    if (tab.value === 'brand') {
      const result: any = await get('/brands')
      if (seq !== listSeq) return
      const q = keyword.value.trim().toLowerCase()
      brands.value = (result?.items || []).filter((row: any) => !q || String(row.name || '').toLowerCase().includes(q))
      listFinished = true
      return
    }
    const result: any = await get('/partners', {
      role: tab.value,
      active_only: false,
      page: searching ? 1 : page.value,
      page_size: searching ? 200 : 30,
    })
    if (seq !== listSeq) return
    const items = (result?.items || []).filter(matches)
    rows.value = reset || searching ? items : rows.value.concat(items)
    const total = Number(result?.total || 0)
    listFinished = searching || rows.value.length >= total || (result?.items || []).length < 30
  } catch (error: any) {
    if (!reset) page.value = Math.max(1, page.value - 1)
    toast(error?.message || '加载失败')
  } finally {
    if (seq === listSeq) {
      loading.value = false
      loadingMore.value = false
    }
    uni.stopPullDownRefresh()
  }
}
function reload() {
  loadList(true)
}
function selectTab(key: TabKey) {
  if (tab.value === key) return
  tab.value = key
  keyword.value = ''
  rows.value = []
  brands.value = []
  loadList(true)
}
function onKeyword(event: any) {
  keyword.value = String(event?.detail?.value || '')
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => loadList(true), 300)
}
function clearKeyword() {
  keyword.value = ''
  loadList(true)
}

function openDetail(row: any) {
  current.value = row
  mode.value = 'detail'
}
async function refreshCurrent(id: number) {
  const result: any = await get(`/partners/${id}`)
  current.value = result
  const index = rows.value.findIndex(row => row.id === id)
  if (index >= 0) rows.value.splice(index, 1, result)
}
function openForm(row?: any) {
  form.id = row?.id || 0
  form.name = row?.name || ''
  form.short_name = row?.short_name || ''
  form.address = row?.address || ''
  form.notes = row?.notes || ''
  form.is_active = row ? row.is_active !== false : true
  form.contact_name = ''
  form.contact_title = ''
  form.contact_mobile = ''
  mode.value = 'form'
}
function openContact(person?: any) {
  contact.id = person?.id || 0
  contact.name = person?.name || ''
  contact.title = person?.title || ''
  contact.mobile = person?.mobile || ''
  contact.wechat = person?.wechat || ''
  contact.is_primary = person ? !!person.is_primary : !(current.value?.contacts || []).some((item: any) => item.is_primary)
  mode.value = 'contact'
}
function openBrand(row?: any) {
  brandForm.id = row?.id || 0
  brandForm.name = row?.name || ''
  brandForm.logo_urls = [...(row?.logo_urls || [])]
  mode.value = 'brandForm'
}
function cancelSub() {
  if (mode.value === 'contact') mode.value = 'detail'
  else if (mode.value === 'form' && form.id && current.value?.id === form.id) mode.value = 'detail'
  else mode.value = 'list'
}

async function savePartner() {
  const name = form.name.trim()
  if (!name) {
    toast(tab.value === 'supplier' ? '请填写公司名称' : '请填写名称')
    return
  }
  if (form.contact_mobile.trim() && !form.contact_name.trim()) {
    toast('请填写联系人姓名')
    return
  }
  const payload: any = {
    name,
    short_name: tab.value === 'supplier' ? '' : form.short_name.trim(),
    address: form.address.trim(),
    notes: form.notes.trim(),
    is_active: form.is_active,
    ...roleFlags(),
  }
  saving.value = true
  try {
    if (form.id) {
      const saved: any = await patch(`/partners/${form.id}`, payload)
      current.value = saved
      mode.value = 'detail'
      toast('已保存')
      loadList(true)
      return
    }
    if (form.contact_name.trim()) {
      payload.contacts = [{
        name: form.contact_name.trim(),
        title: form.contact_title.trim(),
        mobile: form.contact_mobile.trim(),
        is_primary: true,
        is_active: true,
      }]
    }
    const saved: any = await post('/partners', payload)
    current.value = saved
    mode.value = 'detail'
    toast('已新增')
    loadList(true)
  } catch (error: any) {
    toast(error?.message || '保存失败')
  } finally {
    saving.value = false
  }
}
async function saveContact() {
  if (!current.value?.id) return
  const name = contact.name.trim()
  if (!name) {
    toast('请填写联系人姓名')
    return
  }
  const payload = {
    name,
    title: contact.title.trim(),
    mobile: contact.mobile.trim(),
    wechat: contact.wechat.trim(),
    is_primary: contact.is_primary,
    is_active: true,
  }
  saving.value = true
  try {
    if (contact.id) await patch(`/partners/${current.value.id}/contacts/${contact.id}`, payload)
    else await post(`/partners/${current.value.id}/contacts`, payload)
    await refreshCurrent(current.value.id)
    mode.value = 'detail'
    toast('已保存')
  } catch (error: any) {
    toast(error?.message || '保存失败')
  } finally {
    saving.value = false
  }
}
async function saveBrand() {
  const name = brandForm.name.trim()
  if (!name) {
    toast('请填写品牌名称')
    return
  }
  saving.value = true
  try {
    const payload = { name, logo_urls: brandForm.logo_urls }
    if (brandForm.id) await patch(`/brands/${brandForm.id}`, payload)
    else await post('/brands', { ...payload, sort_order: brands.value.length })
    mode.value = 'list'
    toast('已保存')
    loadList(true)
  } catch (error: any) {
    toast(error?.message || '保存失败')
  } finally {
    saving.value = false
  }
}
function saveSub() {
  if (mode.value === 'form') savePartner()
  else if (mode.value === 'contact') saveContact()
  else if (mode.value === 'brandForm') saveBrand()
}
async function removePartner() {
  if (!current.value?.id) return
  if (!await ask('删除合作商', `确定删除「${current.value.name}」？`)) return
  try {
    await del(`/partners/${current.value.id}`)
    mode.value = 'list'
    toast('已删除')
    loadList(true)
  } catch (error: any) {
    toast(error?.message || '删除失败')
  }
}
async function removeContact(person: any) {
  if (!current.value?.id || !person?.id) return
  if (!await ask('删除联系人', `确定删除「${person.name}」？`)) return
  try {
    await del(`/partners/${current.value.id}/contacts/${person.id}`)
    await refreshCurrent(current.value.id)
    toast('已删除')
  } catch (error: any) {
    toast(error?.message || '删除失败')
  }
}
async function stopBrand() {
  if (!brandForm.id) return
  if (!await ask('停用品牌', `确定停用「${brandForm.name}」？`)) return
  try {
    await patch(`/brands/${brandForm.id}`, { is_active: false })
    mode.value = 'list'
    toast('已停用')
    loadList(true)
  } catch (error: any) {
    toast(error?.message || '停用失败')
  }
}
function chooseLogo(source: 'camera' | 'album') {
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: [source],
    success: async result => {
      const filePath = result.tempFilePaths?.[0]
      if (!filePath) return
      try {
        const uploaded: any = await uploadFile('/supplier-products/upload', filePath)
        if (uploaded?.url) brandForm.logo_urls.push(uploaded.url)
      } catch (error: any) {
        toast(error?.message || '上传失败')
      }
    },
  })
}

onBackPress(() => {
  if (mode.value === 'list') return false
  cancelSub()
  return true
})
onPullDownRefresh(() => {
  if (mode.value !== 'list') {
    uni.stopPullDownRefresh()
    return
  }
  loadList(true)
})
onReachBottom(() => {
  if (mode.value === 'list') loadList(false)
})
onShow(() => {
  profile.value = getProfile()
  if (!canSee.value) {
    toast('没有合作商权限')
    setTimeout(() => uni.navigateBack(), 400)
    return
  }
  if (mode.value === 'list') loadList(true)
})
</script>

<style scoped>
.h5-pt--sub { padding-bottom: calc(180rpx + env(safe-area-inset-bottom)); }
.h5-pt-empty { padding: 80rpx 0; color: #414755; font-size: 24rpx; text-align: center; }
.h5-pt-tabs { width: 100%; margin: 8rpx 0 12rpx; white-space: nowrap; }
.h5-pt-tabs text,
.h5-pt-check text,
.h5-pt-photo text {
  display: inline-flex;
  align-items: center;
  height: 60rpx;
  margin-right: 12rpx;
  padding: 0 22rpx;
  border-radius: 999rpx;
  background: #fff;
  color: #414755;
  font-size: 24rpx;
}
.h5-pt-tabs text.on,
.h5-pt-check text.on { background: rgba(0, 87, 194, 0.12); color: #0057c2; font-weight: 700; }
.h5-pt-search,
.h5-pt-card,
.h5-pt-detail,
.h5-pt-person,
.h5-pt-form { margin-bottom: 16rpx; }
.h5-pt-search { display: flex; align-items: center; gap: 16rpx; padding: 8rpx 8rpx 8rpx 24rpx; }
.h5-pt-search input,
.h5-pt-form input,
.h5-pt-form textarea { min-width: 0; color: #181b23; font-size: 28rpx; }
.h5-pt-search input { flex: 1; height: 72rpx; }
.h5-pt-search text,
.h5-pt-person__ops text,
.h5-pt-logos__item text { color: #0057c2; font-size: 26rpx; }
.h5-pt-card,
.h5-pt-detail,
.h5-pt-person,
.h5-pt-form { padding: 20rpx 24rpx; }
.h5-pt-card__title,
.h5-pt-person__head { display: flex; align-items: center; flex-wrap: wrap; gap: 12rpx; }
.h5-pt-card__name { color: #181b23; font-size: 30rpx; font-weight: 750; }
.h5-pt-card__short,
.h5-pt-card__meta,
.h5-pt-line { display: block; margin-top: 8rpx; color: #414755; font-size: 22rpx; }
.h5-pt-dial { display: flex; align-items: center; justify-content: space-between; margin-top: 16rpx; padding: 18rpx 22rpx; border-radius: 16rpx; background: #0057c2; color: #fff; }
.h5-pt-dial strong { font-size: 30rpx; font-weight: 750; letter-spacing: 1rpx; }
.h5-pt-card--brand { display: flex; align-items: center; }
.h5-pt-logo { display: flex; flex: none; align-items: center; justify-content: center; width: 112rpx; height: 112rpx; margin-right: 16rpx; border-radius: 20rpx; background: #f5f7fa; color: #414755; }
.h5-pt-more,
.h5-pt-section { color: #414755; font-size: 24rpx; }
.h5-pt-more { padding: 12rpx 0 24rpx; text-align: center; }
.h5-pt-section { margin: 8rpx 8rpx 12rpx; }
.h5-pt-person__ops { display: flex; gap: 28rpx; margin-top: 16rpx; }
.h5-pt-person__ops .danger { color: #ba1a1a; }
.h5-pt-form input,
.h5-pt-form textarea { box-sizing: border-box; width: 100%; margin: 8rpx 0 20rpx; padding: 0 20rpx; border-radius: 16rpx; background: #f5f7fa; }
.h5-pt-form input { height: 72rpx; }
.h5-pt-form textarea { min-height: 88rpx; padding-top: 18rpx; padding-bottom: 18rpx; }
.h5-pt-label { color: #414755; font-size: 24rpx; }
.h5-pt-check { margin: 8rpx 0 12rpx; }
.h5-pt-logos { display: flex; flex-wrap: wrap; gap: 16rpx; margin: 12rpx 0; }
.h5-pt-logos__item image { width: 160rpx; height: 160rpx; border-radius: 24rpx; background: #f5f7fa; }
.h5-pt-photo { display: flex; gap: 12rpx; margin: 8rpx 0 12rpx; }
.h5-pt-photo text { height: 80rpx; margin: 0; padding: 0 24rpx; border-radius: 16rpx; background: #f5f7fa; color: #181b23; font-size: 28rpx; font-weight: 700; }
.h5-pt-bar { display: flex; align-items: center; gap: 12rpx; }
.h5-pt-ghost,
.h5-pt-primary { flex: 1; height: 84rpx; margin: 0; border: 0; border-radius: 16rpx; font-size: 28rpx; font-weight: 750; line-height: 84rpx; }
.h5-pt-ghost { background: #f5f7fa; color: #181b23; }
.h5-pt-ghost--danger { color: #ba1a1a; }
.h5-pt-ghost::after,
.h5-pt-primary::after { border: 0; }
.h5-pt-primary[disabled] { background: #8eb6e8; color: rgba(255, 255, 255, 0.9); }
</style>
