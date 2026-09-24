<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">往来对账</h1>
      </div>
    </header>

    <div class="admin-card">
      <div class="admin-toolbar">
        <el-select
          v-model="filters.partner_type"
          clearable
          placeholder="往来单位类型"
          style="width: 140px"
          @change="onPartnerTypeChange"
        >
          <el-option label="客户应收" value="customer" />
          <el-option label="外加工厂应付" value="subcontractor" />
        </el-select>
        <el-select
          v-model="filters.partner_id"
          clearable
          filterable
          :disabled="!filters.partner_type"
          :placeholder="partnerPlaceholder"
          style="width: 180px"
          @change="search"
        >
          <el-option
            v-for="partner in partners"
            :key="partner.id"
            :label="partner.short_name || partner.name"
            :value="partner.id"
          />
        </el-select>
        <el-date-picker
          v-model="filters.month"
          type="month"
          value-format="YYYY-MM"
          format="YYYY年M月"
          placeholder="对账月份"
          clearable
          style="width: 150px"
          @change="search"
        />
        <el-select
          v-model="filters.status"
          clearable
          placeholder="全部状态"
          style="width: 130px"
          @change="search"
        >
          <el-option label="草稿" value="draft" />
          <el-option label="已确认" value="confirmed" />
          <el-option label="部分收付" value="partial" />
          <el-option label="已结清" value="settled" />
          <el-option label="有争议" value="disputed" />
          <el-option label="已作废" value="void" />
        </el-select>
        <div class="spacer" />
        <el-button @click="openTemplates">结算模板</el-button>
        <el-button :disabled="!filters.partner_id" @click="openPolicy">结算政策</el-button>
        <el-button @click="load">查询</el-button>
        <el-button type="primary" @click="openGenerate">生成对账单</el-button>
      </div>

      <el-table :data="rows" border stripe size="small" table-layout="fixed" class="statement-list-table">
        <el-table-column prop="statement_no" label="对账单号" min-width="100" show-overflow-tooltip />
        <el-table-column prop="partner_name" label="往来单位" min-width="80" show-overflow-tooltip />
        <el-table-column label="对账期间" min-width="80" align="center" show-overflow-tooltip>
          <template #default="{ row }">{{ statementPeriodLabel(row) }}</template>
        </el-table-column>
        <el-table-column prop="opening_balance" label="上期余额" min-width="68" align="right" show-overflow-tooltip>
          <template #default="{ row }">{{ money(row.opening_balance) }}</template>
        </el-table-column>
        <el-table-column prop="current_amount" :label="listCurrentLabel" min-width="68" align="right" show-overflow-tooltip>
          <template #default="{ row }">{{ money(row.current_amount) }}</template>
        </el-table-column>
        <el-table-column prop="adjustment_amount" label="退货/扣款/调整" min-width="88" align="right" show-overflow-tooltip>
          <template #default="{ row }">{{ money(row.adjustment_amount) }}</template>
        </el-table-column>
        <el-table-column prop="period_settlement_amount" :label="listSettlementLabel" min-width="68" align="right" show-overflow-tooltip>
          <template #default="{ row }">{{ money(row.period_settlement_amount) }}</template>
        </el-table-column>
        <el-table-column prop="closing_balance" label="对账后余额" min-width="68" align="right" show-overflow-tooltip>
          <template #default="{ row }"><strong>{{ money(row.closing_balance) }}</strong></template>
        </el-table-column>
        <el-table-column prop="remaining_amount" :label="listRemainingLabel" min-width="68" align="right" show-overflow-tooltip>
          <template #default="{ row }">{{ money(row.remaining_amount) }}</template>
        </el-table-column>
        <el-table-column prop="due_date" label="到期日" min-width="75" align="center" show-overflow-tooltip />
        <el-table-column label="状态" min-width="65" align="center" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="light" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="145" align="center">
          <template #default="{ row }">
            <div class="statement-actions">
              <el-button link type="primary" @click="openDetail(row)">明细</el-button>
              <el-button v-if="canSettle(row)" link type="success" @click="registerSettlement(row)">
                {{ row.direction === 'customer' ? '收款' : '付款' }}
              </el-button>
              <el-button link @click="printStatement(row)">打印</el-button>
              <el-dropdown v-if="hasMoreActions(row)" trigger="click" @command="handleStatementCommand($event, row)">
                <el-button link>更多</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-if="row.status === 'draft'" command="confirm">确认</el-dropdown-item>
                    <el-dropdown-item v-if="row.status !== 'void' && Number(row.settled_amount) === 0" command="void" :divided="row.status === 'draft'">作废</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
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
          @current-change="load"
          @size-change="onPageSizeChange"
        />
      </div>
    </div>

    <el-dialog v-model="generateVisible" title="生成周期对账单" width="560px">
      <el-form label-width="100px">
        <el-form-item label="对账对象">
          <el-radio-group v-model="generateForm.partner_type" @change="onGeneratePartnerTypeChange">
            <el-radio-button value="subcontractor">外加工厂应付</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="往来单位">
          <el-select v-model="generateForm.partner_id" filterable style="width: 100%" @change="syncGeneratePeriod">
            <el-option
              v-for="partner in generatePartners"
              :key="partner.id"
              :label="partner.short_name || partner.name"
              :value="partner.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="generateIsMonthly" label="对账月份">
          <el-date-picker
            v-model="generateForm.month"
            type="month"
            value-format="YYYY-MM"
            format="YYYY年M月"
            placeholder="选择月份"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item v-else label="对账周期">
          <el-date-picker
            v-model="generateForm.period"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            style="width: 100%"
          />
          <div class="cycle-hint">当前结算规则：{{ generateCycleLabel }}</div>
        </el-form-item>
        <el-form-item label="指定到期日">
          <el-date-picker
            v-model="generateForm.due_date"
            type="date"
            value-format="YYYY-MM-DD"
            clearable
            placeholder="留空则按结算政策计算"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="generateForm.notes" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="generateVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="generateStatement">生成草稿</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" :title="detailDialogTitle" width="95%">
      <el-descriptions v-if="detail" :column="4" border style="margin-bottom: 16px">
        <el-descriptions-item label="单号">{{ detail.statement_no }}</el-descriptions-item>
        <el-descriptions-item label="上期余额">{{ money(detail.opening_balance) }}</el-descriptions-item>
        <el-descriptions-item :label="detailCurrentLabel">{{ money(detail.current_amount) }}</el-descriptions-item>
        <el-descriptions-item label="退货/扣款/调整">{{ money(detail.adjustment_amount) }}</el-descriptions-item>
        <el-descriptions-item :label="detailSettlementLabel">{{ money(detail.period_settlement_amount) }}</el-descriptions-item>
        <el-descriptions-item label="对账后余额"><strong>{{ money(detail.closing_balance) }}</strong></el-descriptions-item>
        <el-descriptions-item :label="detailRemainingLabel"><strong>{{ money(detail.remaining_amount) }}</strong></el-descriptions-item>
      </el-descriptions>
      <el-table v-if="detail?.direction === 'customer'" :data="customerDetailRows" border max-height="480">
        <el-table-column label="出货日期" width="105">
          <template #default="{ row }">{{ row.business_item ? (row.business_date || '—') : (row.business_date || '—') }}</template>
        </el-table-column>
        <el-table-column label="出货单号" min-width="120">
          <template #default="{ row }">{{ row.business_item?.shipment_no || '—' }}</template>
        </el-table-column>
        <el-table-column label="订单号" min-width="130">
          <template #default="{ row }">{{ displayDocumentNo(row) }}</template>
        </el-table-column>
        <el-table-column label="工厂型号" min-width="110">
          <template #default="{ row }">{{ row.business_item?.product_code || '—' }}</template>
        </el-table-column>
        <el-table-column label="图片" width="76" align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.business_item?.image_url"
              :src="row.business_item.image_url"
              fit="cover"
              :preview-src-list="[row.business_item.image_url]"
              preview-teleported
              style="width: 40px; height: 40px; border-radius: 4px"
            />
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="颜色" width="80">
          <template #default="{ row }">{{ row.business_item?.color_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="客户型号" min-width="130">
          <template #default="{ row }">
            <strong>{{ row.business_item?.customer_sku || '—' }}</strong>
          </template>
        </el-table-column>
        <el-table-column label="客户品牌" min-width="100">
          <template #default="{ row }">{{ row.business_item?.brand_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="箱数" width="80" align="right">
          <template #default="{ row }">{{ row.business_item?.carton_count ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="数量" width="90" align="right">
          <template #default="{ row }">{{ row.business_item?.qty ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="单价" width="100" align="right">
          <template #default="{ row }">{{ row.business_item ? money(row.business_item.unit_price) : '—' }}</template>
        </el-table-column>
        <el-table-column label="总价" width="120" align="right">
          <template #default="{ row }"><strong>{{ lineAmount(row) }}</strong></template>
        </el-table-column>
      </el-table>
      <el-table v-else-if="detail?.partner_type !== 'subcontractor'" :data="supplierDetailRows" border max-height="480">
        <el-table-column prop="business_date" label="到货日期" width="115" />
        <el-table-column label="采购单号" min-width="140">
          <template #default="{ row }">{{ displayDocumentNo(row) }}</template>
        </el-table-column>
        <el-table-column label="物料名称" min-width="150">
          <template #default="{ row }"><strong>{{ materialProject(row) }}</strong></template>
        </el-table-column>
        <el-table-column label="物料编码" min-width="135">
          <template #default="{ row }">{{ row.business_item?.item_code || '—' }}</template>
        </el-table-column>
        <el-table-column label="颜色/规格" min-width="115">
          <template #default="{ row }">{{ supplierSpecification(row.business_item) }}</template>
        </el-table-column>
        <el-table-column label="单位" width="75" align="center">
          <template #default="{ row }">{{ row.business_item?.unit_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="到货数量" width="105" align="right">
          <template #default="{ row }">{{ row.business_item?.qty ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="采购单价" width="105" align="right">
          <template #default="{ row }">{{ row.business_item ? money(row.business_item.unit_price) : '—' }}</template>
        </el-table-column>
        <el-table-column label="应付/付款金额" width="125" align="right">
          <template #default="{ row }"><strong>{{ lineAmount(row) }}</strong></template>
        </el-table-column>
      </el-table>
      <el-table v-else :data="subcontractDetailRows" border max-height="480">
        <el-table-column prop="business_date" label="验收日期" width="115" />
        <el-table-column label="外协单号" min-width="140">
          <template #default="{ row }">{{ displayDocumentNo(row) }}</template>
        </el-table-column>
        <el-table-column label="加工工序" min-width="125">
          <template #default="{ row }"><strong>{{ subcontractProcess(row) }}</strong></template>
        </el-table-column>
        <el-table-column label="鞋款/客户型号" min-width="145">
          <template #default="{ row }">{{ subcontractStyle(row.business_item) }}</template>
        </el-table-column>
        <el-table-column label="颜色/码数" min-width="115">
          <template #default="{ row }">{{ supplierSpecification(row.business_item) }}</template>
        </el-table-column>
        <el-table-column label="单位" width="75" align="center">
          <template #default="{ row }">{{ row.business_item?.unit_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="合格验收数量" width="115" align="right">
          <template #default="{ row }">{{ row.business_item?.qty ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="加工单价" width="105" align="right">
          <template #default="{ row }">{{ row.business_item ? money(row.business_item.unit_price) : '—' }}</template>
        </el-table-column>
        <el-table-column label="应付/付款金额" width="125" align="right">
          <template #default="{ row }"><strong>{{ lineAmount(row) }}</strong></template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button v-if="canSettle(detail)" type="success" @click="registerSettlement(detail)">
          {{ detail?.direction === 'customer' ? '登记收款' : '登记付款' }}
        </el-button>
        <el-button type="primary" @click="printStatement(detail)">打印对账单</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="policyVisible" title="结算政策" width="620px">
      <el-form label-width="120px">
        <el-form-item label="核销口径">
          <el-select v-model="policyForm.settlement_mode" style="width: 100%">
            <el-option label="余额结转制" value="balance_forward" />
            <el-option label="逐单核销制" value="open_item" />
            <el-option label="混合模式" value="mixed" />
          </el-select>
        </el-form-item>
        <el-form-item label="结算周期">
          <el-select v-model="policyForm.cycle_type" style="width: 100%">
            <el-option label="自然月/月结" value="monthly" />
            <el-option label="半月结" value="semimonthly" />
            <el-option label="旬结" value="ten_day" />
            <el-option label="逐笔" value="per_transaction" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="policyForm.cycle_type === 'monthly'" label="截账日">
          <el-select v-model="policyForm.cutoff_day" style="width: 180px">
            <el-option label="月底" :value="31" />
            <el-option v-for="day in dayOptions" :key="day" :label="`每月${day}日`" :value="day" />
          </el-select>
        </el-form-item>
        <el-form-item label="付款时间">
          <el-select v-model="policyForm.due_rule" style="width: 150px">
            <el-option :label="filters.direction === 'customer' ? '出货后' : '收货/验收后'" value="transaction_days" />
            <el-option label="截账后" value="cutoff_days" />
            <el-option label="按月固定日" value="fixed_day" />
          </el-select>
          <template v-if="policyForm.due_rule !== 'fixed_day'">
            <el-input-number v-model="policyForm.term_days" :min="0" :max="365" style="width: 120px; margin-left: 8px" />
            <span style="margin-left: 6px">天</span>
          </template>
          <template v-else>
            <el-input-number v-model="policyForm.due_months" :min="0" :max="12" style="width: 110px; margin-left: 8px" />
            <span style="margin: 0 6px">个月后</span>
            <el-select v-model="policyForm.fixed_due_day" style="width: 120px">
              <el-option label="月底" :value="31" />
              <el-option v-for="day in dayOptions" :key="day" :label="`${day}日`" :value="day" />
            </el-select>
          </template>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="policyForm.notes" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="policyVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="savePolicy">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="templatesVisible" title="结算模板" width="860px">
      <div class="admin-toolbar" style="margin-bottom: 12px">
        <span class="muted">模板按客户、供应商分别管理；默认模板会自动用于新建往来单位。</span>
        <div class="spacer" />
        <el-button @click="newTemplate('customer')">新增客户模板</el-button>
        <el-button type="primary" @click="newTemplate('supplier')">新增供应商模板</el-button>
      </div>
      <el-table :data="policyTemplates" border stripe max-height="300">
        <el-table-column prop="name" label="模板名称" min-width="130" />
        <el-table-column label="适用对象" width="100">
          <template #default="{ row }">{{ row.direction === 'customer' ? '客户' : '供应商' }}</template>
        </el-table-column>
        <el-table-column label="规则" min-width="280">
          <template #default="{ row }">{{ templateRuleLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="默认" width="80">
          <template #default="{ row }"><el-tag v-if="row.is_default" type="success" size="small">默认</el-tag></template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">{{ row.is_active ? '启用' : '停用' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130">
          <template #default="{ row }">
            <el-button link type="primary" @click="editTemplate(row)">编辑</el-button>
            <el-button link type="danger" @click="removeTemplate(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <template v-if="templateEditing">
        <el-divider content-position="left">{{ templateForm.id ? '编辑模板' : '新增模板' }}</el-divider>
        <el-form label-width="110px">
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="模板名称" required><el-input v-model="templateForm.name" /></el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="适用对象">
                <el-radio-group v-model="templateForm.direction">
                  <el-radio-button value="customer">客户</el-radio-button>
                  <el-radio-button value="supplier">供应商</el-radio-button>
                </el-radio-group>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="对账周期">
                <el-select v-model="templateForm.cycle_type" style="width: 100%">
                  <el-option label="月结" value="monthly" />
                  <el-option label="半月结" value="semimonthly" />
                  <el-option label="旬结" value="ten_day" />
                  <el-option label="逐笔" value="per_transaction" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col v-if="templateForm.cycle_type === 'monthly'" :span="12">
              <el-form-item label="截账日">
                <el-select v-model="templateForm.cutoff_day" style="width: 100%">
                  <el-option label="月底" :value="31" />
                  <el-option v-for="day in dayOptions" :key="day" :label="`每月${day}日`" :value="day" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="24">
              <el-form-item label="付款时间">
                <el-select v-model="templateForm.due_rule" style="width: 150px">
                  <el-option label="截账后" value="cutoff_days" />
                  <el-option :label="templateForm.direction === 'customer' ? '出货后' : '收货/验收后'" value="transaction_days" />
                  <el-option label="按月固定日" value="fixed_day" />
                </el-select>
                <template v-if="templateForm.due_rule !== 'fixed_day'">
                  <el-input-number v-model="templateForm.term_days" :min="0" :max="365" style="width: 120px; margin-left: 8px" />
                  <span style="margin-left: 6px">天</span>
                </template>
                <template v-else>
                  <el-input-number v-model="templateForm.due_months" :min="0" :max="12" style="width: 110px; margin-left: 8px" />
                  <span style="margin: 0 6px">个月后</span>
                  <el-select v-model="templateForm.fixed_due_day" style="width: 120px">
                    <el-option label="月底" :value="31" />
                    <el-option v-for="day in dayOptions" :key="day" :label="`${day}日`" :value="day" />
                  </el-select>
                </template>
              </el-form-item>
            </el-col>
            <el-col :span="12"><el-form-item label="设为默认"><el-switch v-model="templateForm.is_default" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="启用"><el-switch v-model="templateForm.is_active" /></el-form-item></el-col>
          </el-row>
        </el-form>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <el-button @click="templateEditing = false">取消编辑</el-button>
          <el-button type="primary" :loading="saving" @click="saveTemplate">保存模板</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const rows = ref<any[]>([])
const partners = ref<any[]>([])
const generatePartners = ref<any[]>([])
const detail = ref<any>(null)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const saving = ref(false)
const generateVisible = ref(false)
const detailVisible = ref(false)
const policyVisible = ref(false)
const templatesVisible = ref(false)
const templateEditing = ref(false)
const policyTemplates = ref<any[]>([])
const dayOptions = Array.from({ length: 30 }, (_, index) => index + 1)
const detailDialogTitle = computed(() => detail.value?.direction === 'customer'
  ? '客户对账单明细'
  : detail.value?.partner_type === 'subcontractor' ? '外加工厂对账单明细' : '供应商对账单明细')

const detailCurrentLabel = computed(() => detail.value?.direction === 'customer' ? '本期货款' : '本期应付')
const detailSettlementLabel = computed(() => detail.value?.direction === 'customer' ? '本期回款' : '本期付款')
const detailRemainingLabel = computed(() => detail.value?.direction === 'customer' ? '当前待收' : '当前待付')

const filters = reactive({
  partner_type: '',
  direction: '',
  partner_id: null as number | null,
  status: '',
  month: currentMonth() as string | null,
})

const listCurrentLabel = computed(() => filters.partner_type
  ? (filters.partner_type === 'customer' ? '本期货款' : '本期应付')
  : '本期发生')
const listSettlementLabel = computed(() => filters.partner_type
  ? (filters.partner_type === 'customer' ? '本期回款' : '本期付款')
  : '本期收付')
const listRemainingLabel = computed(() => filters.partner_type
  ? (filters.partner_type === 'customer' ? '当前待收' : '当前待付')
  : '当前余额')

const partnerPlaceholder = computed(() => ({
  customer: '全部客户',
  supplier: '全部供应商',
  subcontractor: '全部外加工厂',
} as Record<string, string>)[filters.partner_type] || '全部往来单位')

function directionForPartnerType(partnerType: string) {
  return partnerType === 'customer' ? 'customer' : 'supplier'
}

function currentMonth() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

function monthPeriod(monthValue = currentMonth()): [string, string] {
  const [year, month] = monthValue.split('-').map(Number)
  const last = new Date(year, month, 0).getDate()
  const prefix = `${year}-${String(month).padStart(2, '0')}`
  return [`${prefix}-01`, `${prefix}-${String(last).padStart(2, '0')}`]
}

const generateForm = reactive({
  partner_type: 'subcontractor',
  direction: 'supplier',
  partner_id: null as number | null,
  month: currentMonth() as string,
  period: monthPeriod() as [string, string] | null,
  due_date: '' as string,
  notes: '',
})

const selectedGeneratePartner = computed(() => generatePartners.value.find(
  (partner: any) => partner.id === generateForm.partner_id,
))
const selectedGeneratePolicy = computed(() => generateForm.direction === 'customer'
  ? selectedGeneratePartner.value?.customer_settlement_policy
  : selectedGeneratePartner.value?.supplier_settlement_policy)
const generateCycleType = computed(() => selectedGeneratePolicy.value?.cycle_type || 'monthly')
const generateIsMonthly = computed(() => generateCycleType.value === 'monthly')
const generateCycleLabel = computed(() => ({
  semimonthly: '半月结',
  ten_day: '旬结',
  per_transaction: '逐笔结算',
} as Record<string, string>)[generateCycleType.value] || '自定义周期')

const policyForm = reactive({
  settlement_mode: 'balance_forward',
  cycle_type: 'monthly',
  cutoff_day: 31,
  reconciliation_day: null as number | null,
  due_rule: 'cutoff_days',
  term_days: 0,
  due_months: 0,
  fixed_due_day: 30 as number | null,
  basis_type: 'business_date',
  holiday_rule: 'none',
  is_active: true,
  notes: '',
})

const emptyTemplate = (direction = 'customer') => ({
  id: null as number | null,
  name: '',
  direction,
  settlement_mode: 'balance_forward',
  cycle_type: 'monthly',
  cutoff_day: 31,
  reconciliation_day: null as number | null,
  due_rule: 'cutoff_days',
  term_days: 30,
  due_months: 1,
  fixed_due_day: 30 as number | null,
  basis_type: 'business_date',
  holiday_rule: 'none',
  is_default: false,
  is_active: true,
  notes: '',
})
const templateForm = reactive<any>(emptyTemplate())

const STATUS_LABEL: Record<string, string> = {
  draft: '草稿',
  confirmed: '已确认',
  disputed: '有争议',
  partial: '部分收付',
  settled: '已结清',
  void: '已作废',
}

function statusLabel(value: string) {
  return STATUS_LABEL[value] || value || '—'
}

function statusType(value: string): '' | 'success' | 'warning' | 'info' | 'danger' {
  if (value === 'settled') return 'success'
  if (value === 'confirmed' || value === 'partial') return 'warning'
  if (value === 'disputed') return 'danger'
  if (value === 'void') return 'info'
  return ''
}

function canSettle(row: any) {
  if (!row || !['confirmed', 'partial'].includes(row.status)) return false
  if (Number(row.remaining_amount || 0) <= 0) return false
  return row.direction === 'customer'
    ? auth.hasPermission('menu.payments')
    : auth.hasPermission('menu.supplier_payments')
}

function statementPeriodLabel(row: any) {
  const start = String(row?.period_start || '')
  const end = String(row?.period_end || '')
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
}

function hasMoreActions(row: any) {
  return row?.status === 'draft' || (row?.status !== 'void' && Number(row?.settled_amount) === 0)
}

async function handleStatementCommand(command: string, row: any) {
  if (command === 'confirm') await confirmRow(row)
  if (command === 'void') await voidRow(row)
}

function money(value: any) {
  const amount = Number(value || 0)
  return amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function lineAmount(row: any) {
  return money(Number(row?.debit_amount || 0) - Number(row?.credit_amount || 0))
}

function displayDocumentNo(row: any) {
  const value = String(row?.document_no || '').trim()
  if (row?.source_type === 'opening_balance') return '期初余额'
  if (/^(AR|AP)-\d+$/i.test(value)) return '—'
  if (/^SK-\d+$/i.test(value)) return '收款记录'
  if (/^FK-\d+$/i.test(value)) return '付款记录'
  return value || (row?.source_type === 'payment' ? '收款记录' : row?.source_type === 'supplier_payment' ? '付款记录' : '—')
}

const customerDetailRows = computed(() => {
  const rows: any[] = []
  for (const line of detail.value?.lines || []) {
    const items = line.shipment_items?.length ? line.shipment_items : [null]
    let allocatedDebit = 0
    items.forEach((item: any, itemIndex: number) => {
      const lineDebit = Number(line.debit_amount || 0)
      const isLast = itemIndex === items.length - 1
      const debit = item
        ? (isLast ? lineDebit - allocatedDebit : Math.min(Number(item.amount || 0), lineDebit - allocatedDebit))
        : lineDebit
      allocatedDebit += debit
      rows.push({
        ...line,
        business_date: itemIndex === 0 ? line.business_date : '',
        document_no: itemIndex === 0 ? line.document_no : '',
        debit_amount: debit,
        credit_amount: itemIndex === 0 ? Number(line.credit_amount || 0) : 0,
        business_item: item,
      })
    })
  }
  return rows
})
const supplierDetailRows = computed(() => {
  const rows: any[] = []
  for (const line of detail.value?.lines || []) {
    const items = line.supplier_items?.length ? line.supplier_items : [null]
    let allocatedDebit = 0
    items.forEach((item: any, itemIndex: number) => {
      const lineDebit = Number(line.debit_amount || 0)
      const isLast = itemIndex === items.length - 1
      const debit = item
        ? (isLast ? lineDebit - allocatedDebit : Math.min(Number(item.amount || 0), lineDebit - allocatedDebit))
        : lineDebit
      allocatedDebit += debit
      rows.push({
        ...line,
        business_date: itemIndex === 0 ? line.business_date : '',
        document_no: itemIndex === 0 ? (item?.source_document_no || line.document_no) : '',
        debit_amount: debit,
        credit_amount: itemIndex === 0 ? Number(line.credit_amount || 0) : 0,
        business_item: item,
      })
    })
  }
  return rows
})
const subcontractDetailRows = computed(() => supplierDetailRows.value)

function materialProject(row: any) {
  const item = row?.business_item
  if (item?.item_name) return item.item_name
  if (row?.source_type === 'supplier_payment') return '本期付款'
  if (row?.source_type === 'opening_balance') return '上期余额'
  return row?.description || '历史应付'
}

function subcontractProcess(row: any) {
  const item = row?.business_item
  if (item?.process_name) return item.process_name
  if (row?.source_type === 'supplier_payment') return '本期付款'
  if (row?.source_type === 'opening_balance') return '上期余额'
  return row?.description || '历史外协应付'
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

function cyclePeriod(monthValue: string, cycleType: string): [string, string] {
  const [year, month] = monthValue.split('-').map(Number)
  const now = new Date()
  const isCurrentMonth = year === now.getFullYear() && month === now.getMonth() + 1
  const day = isCurrentMonth ? now.getDate() : 1
  const lastDay = new Date(year, month, 0).getDate()
  const dateValue = (value: number) => `${year}-${String(month).padStart(2, '0')}-${String(value).padStart(2, '0')}`
  if (cycleType === 'semimonthly') return day <= 15 ? [dateValue(1), dateValue(15)] : [dateValue(16), dateValue(lastDay)]
  if (cycleType === 'ten_day') {
    if (day <= 10) return [dateValue(1), dateValue(10)]
    if (day <= 20) return [dateValue(11), dateValue(20)]
    return [dateValue(21), dateValue(lastDay)]
  }
  if (cycleType === 'per_transaction') return [dateValue(day), dateValue(day)]
  return monthPeriod(monthValue)
}

function syncGeneratePeriod() {
  generateForm.period = cyclePeriod(generateForm.month || currentMonth(), generateCycleType.value)
}

async function loadPartners(partnerType = filters.partner_type) {
  if (!partnerType) {
    partners.value = []
    return
  }
  const role = partnerType === 'customer'
    ? 'customer_brand'
    : partnerType === 'subcontractor' ? 'subcontractor' : 'material_supplier'
  const res: any = await http.get('/partners', {
    params: { role, active_only: true, page: 1, page_size: 500 },
  })
  partners.value = res.data?.items || []
}

async function loadGeneratePartners() {
  const role = generateForm.partner_type === 'customer'
    ? 'customer_brand'
    : generateForm.partner_type === 'subcontractor' ? 'subcontractor' : 'material_supplier'
  const res: any = await http.get('/partners', {
    params: { role, active_only: true, page: 1, page_size: 500 },
  })
  generatePartners.value = res.data?.items || []
  generateForm.partner_id = null
}

async function load() {
  const queryPeriod = filters.month ? monthPeriod(filters.month) : null
  const res: any = await http.get('/account-statements', {
    params: {
      direction: filters.direction || undefined,
      partner_type: filters.partner_type || undefined,
      partner_id: filters.partner_id || undefined,
      status: filters.status || undefined,
      date_from: queryPeriod?.[0] || undefined,
      date_to: queryPeriod?.[1] || undefined,
      page: page.value,
      page_size: pageSize.value,
    },
  })
  rows.value = res.data?.items || []
  total.value = res.data?.total || 0
}

function search() {
  page.value = 1
  void load()
}

async function onPartnerTypeChange() {
  filters.direction = filters.partner_type ? directionForPartnerType(filters.partner_type) : ''
  filters.partner_id = null
  await loadPartners()
  search()
}

async function onGeneratePartnerTypeChange() {
  generateForm.direction = directionForPartnerType(generateForm.partner_type)
  await loadGeneratePartners()
  syncGeneratePeriod()
}

function onPageSizeChange() {
  page.value = 1
  void load()
}

async function openGenerate() {
  generateForm.partner_type = 'subcontractor'
  generateForm.direction = directionForPartnerType(generateForm.partner_type)
  generateForm.partner_id = filters.partner_id
  generateForm.month = filters.month || currentMonth()
  generateForm.period = monthPeriod(generateForm.month)
  generateForm.due_date = ''
  generateForm.notes = ''
  await loadGeneratePartners()
  generateForm.partner_id = filters.partner_id
  syncGeneratePeriod()
  generateVisible.value = true
}

async function generateStatement() {
  const period = generateIsMonthly.value
    ? (generateForm.month ? monthPeriod(generateForm.month) : null)
    : generateForm.period
  if (!generateForm.partner_id || !period?.length) {
    ElMessage.warning(generateIsMonthly.value ? '请选择往来单位和对账月份' : '请选择往来单位和对账周期')
    return
  }
  saving.value = true
  try {
    await http.post('/account-statements/generate', {
      partner_id: generateForm.partner_id,
      direction: generateForm.direction,
      period_start: period[0],
      period_end: period[1],
      due_date: generateForm.due_date || undefined,
      notes: generateForm.notes || undefined,
    })
    ElMessage.success('对账单草稿已生成')
    generateVisible.value = false
    // 生成弹窗可以临时切换客户/供应商；成功后列表必须跟随本次生成方向，
    // 否则草稿已入库却仍被原列表筛选条件隐藏。
    filters.partner_type = generateForm.partner_type
    filters.direction = generateForm.direction
    filters.partner_id = generateForm.partner_id
    filters.status = ''
    page.value = 1
    await loadPartners(filters.partner_type)
    await load()
  } finally {
    saving.value = false
  }
}

async function openDetail(row: any) {
  const res: any = await http.get(`/account-statements/${row.id}`)
  detail.value = res.data
  detailVisible.value = true
}

function registerSettlement(row: any) {
  if (!canSettle(row)) return
  detailVisible.value = false
  void router.replace({
    path: '/admin/settlements',
    query: {
      section: row.direction === 'customer'
        ? 'customers'
        : row.partner_type === 'subcontractor'
          ? 'subcontractors'
          : 'suppliers',
      partner_id: String(row.partner_id || ''),
      partner_name: String(row.partner_name || ''),
      statement_id: String(row.id || ''),
      remaining_amount: String(row.remaining_amount || ''),
      open: '1',
    },
  })
}

function printStatement(row: any) {
  if (!row?.id) return
  const url = `/admin/account-statements/print/${row.id}`
  const opened = window.open(url, '_blank', 'noopener,noreferrer')
  if (!opened) ElMessage.warning('请允许弹出窗口以打开打印预览')
}

async function confirmRow(row: any) {
  await http.post(`/account-statements/${row.id}/confirm`)
  ElMessage.success('对账单已确认，可关联收付款')
  await load()
}

async function voidRow(row: any) {
  await ElMessageBox.confirm('确认作废该对账单？业务来源单据不会删除。', '作废对账单', {
    type: 'warning',
  })
  await http.post(`/account-statements/${row.id}/void`)
  ElMessage.success('对账单已作废')
  await load()
}

async function openPolicy() {
  if (!filters.partner_id) return
  const res: any = await http.get(
    `/settlement-policies/${filters.partner_id}/${filters.direction}`,
  )
  Object.assign(policyForm, res.data)
  policyVisible.value = true
}

async function savePolicy() {
  if (!filters.partner_id) return
  saving.value = true
  try {
    await http.put(
      `/settlement-policies/${filters.partner_id}/${filters.direction}`,
      { ...policyForm },
    )
    ElMessage.success('结算政策已保存')
    policyVisible.value = false
  } finally {
    saving.value = false
  }
}

function templateRuleLabel(row: any) {
  const mode = row.settlement_mode === 'open_item' ? '逐单' : row.settlement_mode === 'mixed' ? '混合' : '余额结转'
  const cycle = row.cycle_type === 'monthly'
    ? (Number(row.cutoff_day) === 31 ? '月末截账' : `每月${row.cutoff_day}日截账`)
    : ({ semimonthly: '半月结', ten_day: '旬结', per_transaction: '逐笔' } as Record<string, string>)[row.cycle_type]
  const due = row.due_rule === 'fixed_day'
    ? `${Number(row.due_months) === 1 ? '次月' : `${row.due_months}个月后`}${Number(row.fixed_due_day) === 31 ? '月底' : `${row.fixed_due_day}日`}`
    : `${row.due_rule === 'transaction_days' ? (row.direction === 'customer' ? '出货' : '收货/验收') : '截账'}后${row.term_days}天`
  return `${mode === '余额结转' ? '' : `${mode} · `}${cycle} · ${due}`
}

async function loadPolicyTemplates() {
  const res: any = await http.get('/settlement-policy-templates')
  policyTemplates.value = res.data || []
}

async function openTemplates() {
  templateEditing.value = false
  await loadPolicyTemplates()
  templatesVisible.value = true
}

function newTemplate(direction: string) {
  Object.assign(templateForm, emptyTemplate(direction))
  templateEditing.value = true
}

function editTemplate(row: any) {
  Object.assign(templateForm, emptyTemplate(row.direction), row)
  templateEditing.value = true
}

async function saveTemplate() {
  if (!templateForm.name.trim()) {
    ElMessage.warning('请填写模板名称')
    return
  }
  saving.value = true
  try {
    const payload = { ...templateForm }
    delete payload.id
    if (templateForm.id) {
      await http.put(`/settlement-policy-templates/${templateForm.id}`, payload)
    } else {
      await http.post('/settlement-policy-templates', payload)
    }
    ElMessage.success('结算模板已保存')
    templateEditing.value = false
    await loadPolicyTemplates()
  } finally {
    saving.value = false
  }
}

async function removeTemplate(row: any) {
  await ElMessageBox.confirm(`删除结算模板「${row.name}」？已套用到往来单位的政策不会受影响。`, '删除模板', { type: 'warning' })
  await http.delete(`/settlement-policy-templates/${row.id}`)
  ElMessage.success('模板已删除')
  await loadPolicyTemplates()
}

onMounted(async () => {
  const requestedType = String(route.query.partner_type || '')
  if (['customer', 'supplier', 'subcontractor'].includes(requestedType)) {
    filters.partner_type = requestedType
    filters.direction = directionForPartnerType(requestedType)
  }
  const requestedPartnerId = Number(route.query.partner_id || 0)
  if (requestedPartnerId > 0) filters.partner_id = requestedPartnerId
  const requestedStatus = String(route.query.status || '')
  if (Object.prototype.hasOwnProperty.call(STATUS_LABEL, requestedStatus)) {
    filters.status = requestedStatus
  }
  if (route.query.all_periods === '1') filters.month = null
  const requestedMonth = String(route.query.month || '')
  if (/^\d{4}-\d{2}$/.test(requestedMonth)) filters.month = requestedMonth
  await loadPartners(filters.partner_type)
  await load()
  if (route.query.generate === '1' && filters.partner_id) {
    await openGenerate()
    const { generate: _generate, partner_type: _partnerType, partner_id: _partnerId, ...query } = route.query
    void router.replace({ path: route.path, query })
  }
})
</script>

<style scoped>
.statement-list-table {
  width: 100%;
}

.cycle-hint {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.4;
}

.statement-list-table :deep(.cell) {
  padding-right: 4px;
  padding-left: 4px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.statement-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: nowrap;
  gap: 4px;
}

.statement-actions :deep(.el-button + .el-button),
.statement-actions :deep(.el-dropdown) {
  margin-left: 0;
}
</style>
