<template>
  <div class="print-page">
    <div class="no-print actions">
      <button type="button" @click="doPrint">打印</button>
      <button type="button" class="ghost" @click="exportExcel">导出 Excel</button>
      <button type="button" class="ghost" @click="closeOrBack">关闭</button>
      <span v-if="isCustomer && pdfUrl">PDF 打印（与 Excel 一致）</span>
      <span v-else-if="isCustomer && pdfLoading">PDF 加载中…</span>
      <span v-else>建议纸张：A4 纵向</span>
    </div>

    <div v-if="error" class="error">{{ error }}</div>
    <template v-else-if="detail">
      <!-- 客户对账单：PDF 打印（与 Excel 样式完全一致） -->
      <div v-if="isCustomer && pdfUrl" class="pdf-container">
        <iframe ref="pdfFrame" :src="pdfUrl" class="pdf-frame" />
      </div>

      <!-- 其他对账单 或 PDF 不可用时：HTML 渲染 -->
      <template v-else>
        <div v-if="detail.status === 'draft'" class="watermark">草稿</div>
        <div v-else-if="detail.status === 'void'" class="watermark muted">作废</div>

        <main class="sheet">
          <header class="doc-header">
            <div class="issuer">
              <span>{{ detail.issuer_address || '' }}</span>
            </div>
            <div class="title-block">
              <h1>客户对账单</h1>
              <div class="statement-no">{{ detail.statement_no }}</div>
            </div>
          </header>

          <section class="party-grid">
            <div><label>{{ isCustomer ? '客户' : '往来单位' }}</label><strong>{{ detail.partner_full_name || detail.partner_name }}</strong></div>
            <div><label>月份</label><span>{{ periodLabel }}</span></div>
            <div><label>联系人</label><span>{{ detail.partner_contact_name || '—' }} {{ detail.partner_contact_mobile || '' }}</span></div>
            <div><label>客户地址</label><span>{{ detail.partner_address || '—' }}</span></div>
          </section>

          <table v-if="isCustomer">
            <thead>
              <tr>
                <th class="date">出货日期</th>
                <th class="shipment-no">出货单号</th>
                <th class="doc-no">订单号</th>
                <th class="goods-factory">工厂型号</th>
                <th class="goods-image">图片</th>
                <th class="goods-color">颜色</th>
                <th class="goods-sku">客户型号</th>
                <th class="goods-brand">客户品牌</th>
                <th class="goods-num">箱数</th>
                <th class="goods-num">数量</th>
                <th class="goods-price">单价</th>
                <th class="amount">总价</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(line, index) in customerStatementLines" :key="`${line.id || index}-${line.item_index || 0}`">
                  <td class="center">{{ line.first_item ? line.business_date : '' }}</td>
                  <td class="center">{{ line.first_item ? (line.business_item?.shipment_no || '—') : '' }}</td>
                  <td class="center">{{ line.first_item ? displayDocumentNo(line) : '' }}</td>
                  <td class="center">{{ line.business_item?.product_code || '—' }}</td>
                  <td class="center">
                    <img v-if="line.business_item?.image_url" :src="line.business_item.image_url" class="item-thumb" alt="" />
                    <span v-else>—</span>
                  </td>
                  <td class="center">{{ line.business_item?.color_name || '—' }}</td>
                  <td class="center strong">{{ line.business_item?.customer_sku || '—' }}</td>
                  <td class="center">{{ line.business_item?.brand_name || '—' }}</td>
                  <td class="number center">{{ line.business_item?.carton_count ?? '—' }}</td>
                  <td class="number center">{{ line.business_item?.qty ?? '—' }}</td>
                  <td class="number center">{{ line.business_item ? money(line.business_item.unit_price) : '—' }}</td>
                  <td class="number center strong">{{ signedAmount(line) }}</td>
              </tr>
              <tr v-if="!customerStatementLines.length">
                <td :colspan="12" class="empty">本期无明细</td>
              </tr>
            </tbody>
            <tfoot>
              <tr>
                <td :colspan="11" class="right strong">本期货款合计</td>
                <td class="number strong">¥{{ money(netTotal) }}</td>
              </tr>
            </tfoot>
          </table>

          <table v-else-if="!isSubcontractor" class="supplier-table">
            <thead>
              <tr>
                <th class="seq">序号</th>
                <th class="date">到货日期</th>
                <th class="doc-no">采购单号</th>
                <th class="supplier-project">物料名称</th>
                <th class="supplier-code">物料编码</th>
                <th class="supplier-spec">颜色/规格</th>
                <th class="supplier-unit">单位</th>
                <th class="supplier-qty">到货数量</th>
                <th class="goods-price">采购单价</th>
                <th class="amount">应付/付款金额</th>
                <th class="remark">备注/差异</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(line, index) in supplierStatementLines" :key="`${line.id || index}-${line.item_index || 0}`">
                  <td class="center">{{ line.first_item ? line.sequence : '' }}</td>
                  <td class="center">{{ line.first_item ? line.business_date : '' }}</td>
                  <td>{{ line.first_item ? displayDocumentNo(line) : '' }}</td>
                  <td class="strong">{{ materialProject(line) }}</td>
                  <td>{{ line.business_item?.item_code || '—' }}</td>
                  <td>{{ supplierSpecification(line.business_item) }}</td>
                  <td class="center">{{ line.business_item?.unit_name || '—' }}</td>
                  <td class="number">{{ line.business_item?.qty ?? '—' }}</td>
                  <td class="number">{{ line.business_item ? money(line.business_item.unit_price) : '—' }}</td>
                  <td class="number strong">{{ signedAmount(line) }}</td>
                  <td>{{ Number(line.disputed_amount || 0) ? `差异 ¥${money(line.disputed_amount)}` : '' }}</td>
              </tr>
              <tr v-if="!supplierStatementLines.length">
                <td colspan="11" class="empty">本期无明细</td>
              </tr>
            </tbody>
            <tfoot>
              <tr>
                <td colspan="9" class="right strong">本期合计</td>
                <td class="number strong">{{ money(netTotal) }}</td>
                <td />
              </tr>
            </tfoot>
          </table>

          <table v-else class="supplier-table subcontract-table">
            <thead>
              <tr>
                <th class="seq">序号</th>
                <th class="date">验收日期</th>
                <th class="doc-no">外协单号</th>
                <th class="supplier-project">加工工序</th>
                <th class="supplier-code">鞋款/客户型号</th>
                <th class="supplier-spec">颜色/码数</th>
                <th class="supplier-unit">单位</th>
                <th class="supplier-qty">合格验收数量</th>
                <th class="goods-price">加工单价</th>
                <th class="amount">应付/付款金额</th>
                <th class="remark">备注/差异</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(line, index) in subcontractStatementLines" :key="`${line.id || index}-${line.item_index || 0}`">
                  <td class="center">{{ line.first_item ? line.sequence : '' }}</td>
                  <td class="center">{{ line.first_item ? line.business_date : '' }}</td>
                  <td>{{ line.first_item ? displayDocumentNo(line) : '' }}</td>
                  <td class="strong">{{ subcontractProcess(line) }}</td>
                  <td>{{ subcontractStyle(line.business_item) }}</td>
                  <td>{{ supplierSpecification(line.business_item) }}</td>
                  <td class="center">{{ line.business_item?.unit_name || '—' }}</td>
                  <td class="number">{{ line.business_item?.qty ?? '—' }}</td>
                  <td class="number">{{ line.business_item ? money(line.business_item.unit_price) : '—' }}</td>
                  <td class="number strong">{{ signedAmount(line) }}</td>
                  <td>{{ Number(line.disputed_amount || 0) ? `差异 ¥${money(line.disputed_amount)}` : '' }}</td>
              </tr>
              <tr v-if="!subcontractStatementLines.length">
                <td colspan="11" class="empty">本期无明细</td>
              </tr>
            </tbody>
            <tfoot>
              <tr>
                <td colspan="9" class="right strong">本期合计</td>
                <td class="number strong">{{ money(netTotal) }}</td>
                <td />
              </tr>
            </tfoot>
          </table>

          <section class="summary">
            <div><span>上期欠款</span><strong>¥{{ money(detail.opening_balance) }}</strong></div>
            <div><span>退货/扣款</span><strong>¥{{ money(detail.adjustment_amount) }}</strong></div>
            <div class="formula-row">
              <span>本期货款合计 + 上期欠款 − 退货/扣款 = {{ remainingLabel }}</span>
              <strong>¥{{ money(detail.remaining_amount) }}</strong>
            </div>
          </section>

          <section class="amount-upper">
            <span>货款总计（大写）</span>
            <strong>{{ moneyToChineseUpper(detail.remaining_amount) }}</strong>
          </section>

          <section v-if="isCustomer" class="bank-info">
            <span><label>收款人</label>{{ detail.issuer_bank_account_name || detail.issuer_name || '—' }}</span>
            <span><label>收款账号</label>{{ detail.issuer_bank_account || '—' }}</span>
            <span><label>开户行</label>{{ detail.issuer_bank_name || '—' }}</span>
          </section>

          <section class="confirmation">
            <div>
              <strong>{{ partnerSignatureLabel }}</strong>
              <p class="sign-line">签字/盖章：</p>
              <p class="sign-date">日期：______年____月____日</p>
            </div>
            <div>
              <strong>{{ issuerSignatureLabel }}</strong>
              <p class="sign-line">签字/盖章：</p>
              <p class="sign-date">日期：______年____月____日</p>
            </div>
          </section>
        </main>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const detail = ref<any>(null)
const error = ref('')
const pdfUrl = ref('')
const pdfLoading = ref(false)
const pdfFrame = ref<HTMLIFrameElement | null>(null)

const isCustomer = computed(() => detail.value?.direction === 'customer')
const isSubcontractor = computed(() => detail.value?.partner_type === 'subcontractor')
const periodLabel = computed(() => {
  const start = String(detail.value?.period_start || '')
  const end = String(detail.value?.period_end || '')
  const startParts = start.split('-').map(Number)
  const endParts = end.split('-').map(Number)
  if (startParts.length === 3 && endParts.length === 3) {
    const [startYear, startMonth, startDay] = startParts
    const [endYear, endMonth, endDay] = endParts
    const monthLastDay = new Date(startYear, startMonth, 0).getDate()
    if (startYear === endYear && startMonth === endMonth && startDay === 1 && endDay === monthLastDay) {
      return `${startYear}年${startMonth}月`
    }
    if (startYear === endYear) {
      return `${String(startMonth).padStart(2, '0')}/${String(startDay).padStart(2, '0')}–${String(endMonth).padStart(2, '0')}/${String(endDay).padStart(2, '0')}`
    }
  }
  return start && end ? `${start}–${end}` : start || end || '—'
})
const currentLabel = computed(() => isCustomer.value ? '本期货款' : '本期应付')
const remainingLabel = computed(() => isCustomer.value ? '当前待收货款总计' : '当前待付货款总计')
const issuerSignatureLabel = computed(() => {
  const name = detail.value?.issuer_name
  return isCustomer.value ? `供方（${name || '本厂'}）确认` : '采购方（本厂）确认'
})
const partnerSignatureLabel = computed(() => {
  const name = detail.value?.partner_full_name || detail.value?.partner_name
  return isCustomer.value ? `客户（${name || '客户'}）确认` : '供应商确认'
})

function flattenLines(itemKey: 'shipment_items' | 'supplier_items') {
  const rows: any[] = []
  for (const [lineIndex, line] of (detail.value?.lines || []).entries()) {
    const sourceItems = line[itemKey]
    const items = sourceItems?.length ? sourceItems : [null]
    let allocatedDebit = 0
    items.forEach((item: any, itemIndex: number) => {
      const isLast = itemIndex === items.length - 1
      const lineDebit = Number(line.debit_amount || 0)
      const debit = item
        ? (isLast ? lineDebit - allocatedDebit : Math.min(Number(item.amount || 0), lineDebit - allocatedDebit))
        : lineDebit
      allocatedDebit += debit
      const credit = itemIndex === 0 ? Number(line.credit_amount || 0) : 0
      rows.push({
        ...line,
        document_no: itemIndex === 0 && itemKey === 'supplier_items'
          ? (item?.source_document_no || line.document_no)
          : line.document_no,
        debit_amount: debit,
        credit_amount: credit,
        business_item: item,
        item_index: itemIndex,
        sequence: lineIndex + 1,
        first_item: itemIndex === 0,
      })
    })
  }
  return rows
}
const customerStatementLines = computed(() => flattenLines('shipment_items'))
const supplierStatementLines = computed(() => flattenLines('supplier_items'))
const subcontractStatementLines = computed(() => supplierStatementLines.value)
const activeStatementLines = computed(() => isCustomer.value
  ? customerStatementLines.value
  : isSubcontractor.value ? subcontractStatementLines.value : supplierStatementLines.value)
const netTotal = computed(() => activeStatementLines.value.reduce(
  (sum: number, line: any) => sum + Number(line.debit_amount || 0) - Number(line.credit_amount || 0),
  0,
))

function displayDocumentNo(line: any) {
  const value = String(line.document_no || '').trim()
  if (line.source_type === 'opening_balance') return '期初余额'
  if (/^(AR|AP)-\d+$/i.test(value)) return '—'
  if (/^SK-\d+$/i.test(value)) return '收款记录'
  if (/^FK-\d+$/i.test(value)) return '付款记录'
  return value || (line.source_type === 'payment' ? '收款记录' : line.source_type === 'supplier_payment' ? '付款记录' : '—')
}

function money(value: any) {
  const amount = Number(value || 0)
  return amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function signedAmount(line: any) {
  const amount = Number(line.debit_amount || 0) - Number(line.credit_amount || 0)
  return amount ? money(amount) : ''
}

function materialProject(line: any) {
  const item = line?.business_item
  if (item?.item_name) return item.item_name
  if (line?.source_type === 'supplier_payment') return '本期付款'
  if (line?.source_type === 'opening_balance') return '上期余额'
  return line?.description || '历史应付'
}

function subcontractProcess(line: any) {
  const item = line?.business_item
  if (item?.process_name) return item.process_name
  if (line?.source_type === 'supplier_payment') return '本期付款'
  if (line?.source_type === 'opening_balance') return '上期余额'
  return line?.description || '历史外协应付'
}

function subcontractStyle(item: any) {
  return item?.customer_sku || item?.item_code || '—'
}

function supplierSpecification(item: any) {
  if (!item) return '—'
  const sizes = (item.size_breakdown || [])
    .map((entry: any) => entry?.size_value)
    .filter(Boolean)
  return [item.color_name, ...sizes].filter(Boolean).join(' / ') || '—'
}

function integerToChinese(value: number) {
  const digits = ['零', '壹', '贰', '叁', '肆', '伍', '陆', '柒', '捌', '玖']
  const units = ['', '拾', '佰', '仟']
  const groupUnits = ['', '万', '亿', '兆']
  let number = Math.floor(value)
  let result = ''
  let groupIndex = 0
  let needZero = false
  while (number > 0) {
    const section = number % 10000
    if (section === 0) {
      if (result) needZero = true
    } else {
      let sectionValue = section
      let sectionText = ''
      let unitIndex = 0
      let zeroPending = false
      while (sectionValue > 0) {
        const digit = sectionValue % 10
        if (digit === 0) {
          if (sectionText) zeroPending = true
        } else {
          sectionText = `${digits[digit]}${units[unitIndex]}${zeroPending ? '零' : ''}${sectionText}`
          zeroPending = false
        }
        unitIndex += 1
        sectionValue = Math.floor(sectionValue / 10)
      }
      if (needZero && result) result = `零${result}`
      result = `${sectionText}${groupUnits[groupIndex]}${result}`
      needZero = section < 1000
    }
    number = Math.floor(number / 10000)
    groupIndex += 1
  }
  return result || '零'
}

function moneyToChineseUpper(value: any) {
  const raw = Number(value || 0)
  if (!Number.isFinite(raw)) return '人民币零元整'
  const prefix = raw < 0 ? '负' : ''
  const fixed = Math.abs(raw).toFixed(2)
  const [integerPart, decimalPart] = fixed.split('.')
  const integerText = integerToChinese(Number(integerPart))
  const digits = ['零', '壹', '贰', '叁', '肆', '伍', '陆', '柒', '捌', '玖']
  const jiao = Number(decimalPart[0])
  const fen = Number(decimalPart[1])
  const fraction = `${jiao ? `${digits[jiao]}角` : ''}${fen ? `${digits[fen]}分` : ''}` || '整'
  return `人民币${prefix}${integerText}元${fraction}`
}

function doPrint() {
  if (pdfUrl.value && pdfFrame.value) {
    pdfFrame.value.contentWindow?.print()
  } else {
    window.print()
  }
}

async function exportExcel() {
  const statementId = detail.value?.id
  if (!statementId) return
  try {
    const res = await fetch(`/api/v1/account-statements/${statementId}/export`, {
      headers: auth.token ? { Authorization: `Bearer ${auth.token}` } : {},
    })
    if (!res.ok) {
      let msg = '导出失败'
      try {
        const body = await res.json()
        msg = body.detail || body.error?.message || msg
      } catch {
        /* ignore */
      }
      ElMessage.error(msg)
      return
    }
    const blob = await res.blob()
    const cd = res.headers.get('Content-Disposition') || ''
    let filename = `${detail.value.statement_no || 'statement'}.xlsx`
    const starMatch = cd.match(/filename\*=UTF-8''([^;]+)/i)
    const plainMatch = cd.match(/filename="?([^";]+)"?/i)
    if (starMatch?.[1]) filename = decodeURIComponent(starMatch[1])
    else if (plainMatch?.[1]) filename = plainMatch[1]
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
    URL.revokeObjectURL(url)
    ElMessage.success('已导出 Excel')
  } catch {
    ElMessage.error('导出失败')
  }
}

function closeOrBack() {
  if (window.opener) window.close()
  else router.back()
}

async function loadPdf(statementId: number) {
  pdfLoading.value = true
  try {
    const res = await fetch(`/api/v1/account-statements/${statementId}/export-pdf`, {
      headers: auth.token ? { Authorization: `Bearer ${auth.token}` } : {},
    })
    if (!res.ok) {
      pdfUrl.value = ''
      return
    }
    const blob = await res.blob()
    pdfUrl.value = URL.createObjectURL(blob)
    await nextTick()
  } catch {
    pdfUrl.value = ''
  } finally {
    pdfLoading.value = false
  }
}

async function load() {
  const id = Number(route.params.id)
  if (!id) {
    error.value = '对账单无效'
    return
  }
  try {
    const res: any = await http.get(`/account-statements/${id}`)
    detail.value = res.data
    document.title = res.data?.statement_no || '对账单'
    if (res.data?.direction === 'customer') {
      loadPdf(id)
    }
  } catch {
    error.value = '对账单不存在或无权查看'
  }
}

onMounted(load)
onUnmounted(() => {
  if (pdfUrl.value) URL.revokeObjectURL(pdfUrl.value)
})
</script>

<style scoped>
.print-page { min-height: 100vh; padding: 18px; background: #fff; color: #111; font: 12px/1.45 'PingFang SC', 'Microsoft YaHei', sans-serif; position: relative; }
.actions { max-width: 1180px; margin: 0 auto 12px; display: flex; align-items: center; gap: 8px; color: #666; }
.actions button { padding: 6px 14px; border: 1px solid #bbb; border-radius: 5px; background: #1468c3; color: #fff; cursor: pointer; }
.actions .ghost { background: #fff; color: #333; }
.error { color: #b42318; max-width: 1180px; margin: 20px auto; }
.pdf-container { width: 100%; height: calc(100vh - 80px); }
.pdf-frame { width: 100%; height: 100%; border: 1px solid #ddd; border-radius: 4px; }
.sheet { max-width: 1180px; margin: 0 auto; position: relative; }
.doc-header { display: grid; grid-template-columns: 1fr 1.2fr 1fr; align-items: end; border-bottom: 2px solid #111; padding-bottom: 9px; }
.issuer { display: flex; flex-direction: column; gap: 3px; }
.issuer span { color: #555; font-size: 11px; }
.title-block { text-align: center; }
h1 { margin: 0; font-size: 24px; letter-spacing: .24em; }
.statement-no { margin-top: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.party-grid { display: grid; grid-template-columns: 1fr 1fr; border: 1px solid #333; border-top: 0; }
.party-grid > div { display: grid; grid-template-columns: 78px 1fr; min-height: 30px; align-items: center; padding: 3px 8px; border-bottom: 1px solid #aaa; }
.party-grid > div:nth-child(odd) { border-right: 1px solid #aaa; }
.party-grid > div:nth-last-child(-n + 2) { border-bottom: 0; }
.party-grid label { color: #555; }
.bank-info { display: grid; grid-template-columns: 1fr 1fr 1fr; border: 1px solid #333; border-top: 0; font-size: 12px; }
.bank-info > span { display: flex; gap: 6px; padding: 4px 8px; border-right: 1px solid #aaa; align-items: baseline; }
.bank-info > span:last-child { border-right: 0; }
.bank-info label { color: #555; white-space: nowrap; }
.bank-info label::after { content: '：'; }
.summary { display: grid; grid-template-columns: 1fr; border: 1px solid #333; border-top: 0; }
.summary > div { padding: 6px 10px; border-bottom: 1px solid #aaa; display: flex; justify-content: flex-end; align-items: center; gap: 12px; }
.summary > div:last-child { border-bottom: 0; }
.summary span { color: #555; font-size: 11px; }
.summary strong { font-size: 14px; text-align: right; }
.summary .formula-row { justify-content: flex-end; }
.summary .formula-row span { font-size: 12px; color: #333; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
th, td { border: 1px solid #333; padding: 5px 6px; vertical-align: middle; word-break: break-all; }
th { background: #eee; font-weight: 600; }
thead { display: table-header-group; }
tfoot { display: table-row-group; }
tr { break-inside: avoid; }
.seq { width: 28px; }.date { width: 68px; }.doc-no { width: 90px; }.amount { width: 68px; }.remark { width: 65px; }
.goods-image { width: 46px; }.goods-factory { width: 70px; }.goods-sku { width: 74px; }.goods-color { width: 45px; }.goods-num { width: 40px; }.goods-price { width: 58px; }.shipment-no { width: 90px; }.goods-brand { width: 66px; }
.supplier-project { width: 112px; }.supplier-code { width: 86px; }.supplier-spec { width: 82px; }.supplier-unit { width: 42px; }.supplier-qty { width: 68px; }
.number { text-align: right; font-variant-numeric: tabular-nums; }.center { text-align: center; }.right { text-align: right; }.strong { font-weight: 700; }.empty { text-align: center; padding: 20px; color: #666; }
.item-thumb { width: 34px; height: 34px; object-fit: cover; border: 1px solid #ddd; border-radius: 3px; vertical-align: middle; }
.amount-upper { border: 1px solid #333; border-top: 0; display: flex; justify-content: flex-end; align-items: center; gap: 10px; min-height: 34px; padding: 0 8px; }
.amount-upper strong { letter-spacing: .06em; }
.confirmation { display: grid; grid-template-columns: 1fr 1fr; border: 1px solid #333; border-top: 0; break-inside: avoid; }
.confirmation > div { min-height: 160px; padding: 9px 12px; text-align: left; }
.confirmation > div:first-child { border-right: 1px solid #333; }
.confirmation p { margin: 9px 0 0; }.sign-line { margin-top: 24px; }.sign-date { margin-top: 40px; }
.watermark { position: fixed; inset: 0; z-index: 0; display: flex; align-items: center; justify-content: center; pointer-events: none; opacity: .1; font-size: 90px; font-weight: 700; transform: rotate(-24deg); color: #b42318; }
.watermark.muted { color: #666; }.sheet > * { position: relative; z-index: 1; }
@media print { .no-print { display: none !important; }.print-page { padding: 0; }.sheet { max-width: none; width: 100%; }.pdf-container { height: 100vh; }.pdf-frame { border: 0; } }
</style>

<style>
@page { size: A4 portrait; margin: 9mm 10mm; }
body:has(.print-page) #app { max-width: none; margin: 0; background: #fff; }
</style>
