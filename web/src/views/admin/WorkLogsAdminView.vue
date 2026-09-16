<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">考勤&报工</h1>
        <p class="page-desc">生产报工 · 员工考勤 · 报工考勤日志</p>
      </div>
  </header>
  <div class="admin-card">
    <el-tabs v-model="activeTab" class="record-tabs" @tab-change="onTabChange">
      <el-tab-pane label="报工流水" name="work_logs" />
      <el-tab-pane label="考勤记录" name="attendance" />
      <el-tab-pane label="报工考勤日志" name="daily_stats" />
    </el-tabs>
    <template v-if="activeTab === 'work_logs'">
    <div class="admin-toolbar">
      <el-select v-model="filters.worker_id" clearable placeholder="员工" style="width: 140px" @change="reloadFromFilter">
        <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
      </el-select>
      <el-input v-model="filters.order_no" clearable placeholder="订单号" style="width: 140px" @change="reloadFromFilter" />
      <el-select v-model="filters.segment_id" clearable placeholder="部门" style="width: 140px" @change="reloadFromFilter">
        <el-option v-for="segment in segments" :key="segment.id" :label="segment.name" :value="segment.id" />
      </el-select>
      <el-date-picker
        v-model="dateRange"
        type="daterange"
        value-format="YYYY-MM-DD"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        style="width: 240px"
        @change="reloadFromFilter"
      />
      <el-select v-model="filters.status" clearable placeholder="状态" style="width: 120px" @change="reloadFromFilter">
        <el-option label="有效" value="valid" />
        <el-option label="删除" value="void" />
        <el-option label="申诉" value="appealed" />
        <el-option label="更正" value="corrected" />
      </el-select>
      <el-button @click="load">刷新</el-button>
      <div class="spacer" />
      <el-button v-if="filters.status !== 'appealed'" @click="filters.status = 'appealed'; reloadFromFilter()">
        看待审申诉
      </el-button>
      <el-button :type="anomalyMode ? 'danger' : undefined" plain @click="toggleAnomalyMode">
        {{ anomalyMode ? '退出异常核对' : '异常核对' }}
      </el-button>
    </div>

    <template v-if="anomalyMode">
      <div class="admin-toolbar">
        <el-date-picker
          v-model="anomalyRange.date_from"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="起始日"
          style="width: 150px"
          @change="loadAnomalies"
        />
        <span class="muted">至</span>
        <el-date-picker
          v-model="anomalyRange.date_to"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="截止日"
          style="width: 150px"
          @change="loadAnomalies"
        />
        <el-button :loading="anomalyLoading" @click="loadAnomalies">刷新</el-button>
        <div class="spacer" />
        <span class="muted">{{ anomalyMessage }}</span>
      </div>
      <el-table
        ref="anomalyTableRef"
        v-loading="anomalyLoading"
        class="work-logs-table"
        :data="anomalyRows"
        stripe
        border
        style="width: 100%"
        @header-dragend="onAnomalyHeaderDragend"
      >
        <el-table-column prop="created_at" label="时间" :width="anomalyColWidth('created_at', 170)" show-overflow-tooltip resizable />
        <el-table-column prop="process_name" label="工序" :width="anomalyColWidth('process_name', 90)" show-overflow-tooltip resizable />
        <el-table-column prop="worker_name" label="员工" :width="anomalyColWidth('worker_name', 90)" show-overflow-tooltip resizable />
        <el-table-column prop="order_no" label="生产单" :width="anomalyColWidth('order_no', 100)" show-overflow-tooltip resizable />
        <el-table-column prop="product_code" label="工厂型号" :width="anomalyColWidth('product_code', 110)" show-overflow-tooltip resizable />
        <el-table-column
          column-key="product_image_url"
          label="图片"
          :width="anomalyColWidth('product_image_url', 64)"
          align="center"
          class-name="product-image-col"
          header-class-name="product-image-col"
          resizable
        >
          <template #default="{ row }">
            <el-image
              v-if="row.product_image_url"
              :src="row.product_image_url"
              :preview-src-list="[row.product_image_url]"
              preview-teleported
              fit="contain"
              class="product-thumb"
            />
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="qty" label="数量" :width="anomalyColWidth('qty', 70)" resizable />
        <el-table-column column-key="unit_price" label="单价" :width="anomalyColWidth('unit_price', 90)" resizable>
          <template #default="{ row }">{{ row.unit_price != null ? `¥${row.unit_price.toFixed(2)}` : '—' }}</template>
        </el-table-column>
        <el-table-column
          column-key="reasons"
          label="异常原因"
          :width="anomalyColWidth('reasons', 260)"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">
            <el-tag
              v-for="r in row.reasons"
              :key="r.code"
              :type="reasonTagType(r.code)"
              size="small"
              effect="plain"
              style="margin: 2px 4px 2px 0"
              :title="r.text"
            >
              {{ r.text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column column-key="actions" label="操作" width="90" :resizable="false">
          <template #default="{ row }">
            <el-button link type="primary" @click="locateInList(row)">定位</el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <template v-else>
    <div ref="tableHostRef">
    <el-table
      ref="tableRef"
      class="work-logs-table"
      :data="rows"
      stripe
      border
      show-summary
      :summary-method="getSummaries"
      :max-height="tableMaxHeight"
      style="width: 100%"
      @header-dragend="onHeaderDragend"
    >
      <el-table-column prop="created_at" label="时间" :width="colWidth('created_at', 170)" show-overflow-tooltip resizable />
      <el-table-column prop="segment_name" label="部门" :width="colWidth('segment_name', 90)" show-overflow-tooltip resizable />
      <el-table-column prop="process_name" label="工序" :width="colWidth('process_name', 90)" show-overflow-tooltip resizable />
      <el-table-column prop="worker_name" label="员工" :width="colWidth('worker_name', 90)" show-overflow-tooltip resizable />
      <el-table-column prop="order_no" label="生产单" :width="colWidth('order_no', 100)" show-overflow-tooltip resizable />
      <el-table-column prop="product_code" label="工厂型号" :width="colWidth('product_code', 110)" show-overflow-tooltip resizable />
      <el-table-column
        column-key="product_image_url"
        label="图片"
        :width="colWidth('product_image_url', 64)"
        align="center"
        class-name="product-image-col"
        header-class-name="product-image-col"
        resizable
      >
        <template #default="{ row }">
          <el-image
            v-if="row.product_image_url"
            :src="row.product_image_url"
            :preview-src-list="[row.product_image_url]"
            preview-teleported
            fit="contain"
            class="product-thumb"
          />
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="qualified_qty" label="合格" :width="colWidth('qualified_qty', 70)" resizable />
      <el-table-column column-key="unit_price" label="工序单价" :width="colWidth('unit_price', 90)" resizable>
        <template #default="{ row }">{{ row.unit_price != null ? `¥${Number(row.unit_price).toFixed(2)}` : '—' }}</template>
      </el-table-column>
      <el-table-column column-key="estimated_wage" label="工资" :width="colWidth('estimated_wage', 100)" resizable>
        <template #default="{ row }">
          {{ row.unit_price != null ? `¥${estimatedWage(row).toFixed(2)}` : '—' }}
        </template>
      </el-table-column>
      <el-table-column prop="review_note" label="备注" :width="colWidth('review_note', 120)" show-overflow-tooltip resizable />
      <el-table-column column-key="actions" label="操作" width="180" :resizable="false">
        <template #default="{ row }">
          <span v-if="row.system_generated" class="muted">系统生成</span>
          <template v-else-if="row.status === 'valid'">
            <el-button link type="primary" @click="openCorrect(row)">修改</el-button>
            <el-button link type="danger" @click="voidLog(row)">删除</el-button>
          </template>
          <template v-else-if="row.status === 'appealed'">
            <el-button link type="success" @click="rejectAppeal(row)">驳回</el-button>
            <el-button link type="primary" @click="openCorrect(row)">修改</el-button>
            <el-button link type="danger" @click="voidLog(row)">删除</el-button>
          </template>
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
    </template>
    </template>

    <template v-else-if="activeTab === 'attendance'">
      <div class="admin-toolbar">
        <el-select
          v-model="attendanceFilters.department_id"
          clearable
          placeholder="部门"
          style="width: 140px"
          @change="reloadAttendance"
        >
          <el-option v-for="department in departments" :key="department.id" :label="department.name" :value="department.id" />
        </el-select>
        <el-select
          v-model="attendanceFilters.employee_id"
          clearable
          placeholder="员工"
          style="width: 150px"
          @change="reloadAttendance"
        >
          <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
        </el-select>
        <el-date-picker
          v-model="attendanceDateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          style="width: 210px"
          @change="reloadAttendance"
        />
        <el-button :loading="attendanceLoading" @click="loadAttendance">刷新</el-button>
      </div>
      <div class="attendance-table-host">
        <el-table
          ref="attendanceTableRef"
          v-loading="attendanceLoading"
          class="attendance-table"
          :data="attendanceRows"
          border
          stripe
          style="width: 100%; max-width: 100%"
          @header-dragend="onAttendanceHeaderDragend"
        >
        <el-table-column prop="work_date" label="日期" :width="attendanceColWidth('work_date', 110)" resizable />
        <el-table-column prop="department_name" label="部门" :width="attendanceColWidth('department_name', 130)" show-overflow-tooltip resizable />
        <el-table-column prop="employee_name" label="员工" :width="attendanceColWidth('employee_name', 120)" show-overflow-tooltip resizable />
        <el-table-column prop="clock_in_at" label="上班打卡" :width="attendanceColWidth('clock_in_at', 180)" resizable>
          <template #default="{ row }">{{ row.clock_in_at || '—' }}</template>
        </el-table-column>
        <el-table-column prop="clock_out_at" label="下班打卡" :width="attendanceColWidth('clock_out_at', 180)" resizable>
          <template #default="{ row }">{{ row.clock_out_at || '—' }}</template>
        </el-table-column>
        <el-table-column column-key="work_minutes" label="出勤时长" :width="attendanceColWidth('work_minutes', 120)" resizable>
          <template #default="{ row }">{{ formatWorkMinutes(row.work_minutes) }}</template>
        </el-table-column>
        <el-table-column column-key="attendance_status" label="状态" :width="attendanceColWidth('attendance_status', 100)" resizable>
          <template #default="{ row }">{{ attendanceStatusLabel(row.status) }}</template>
        </el-table-column>
        </el-table>
      </div>
      <div class="admin-pagination">
        <el-pagination
          v-model:current-page="attendancePage"
          v-model:page-size="attendancePageSize"
          background
          layout="total, sizes, prev, pager, next"
          :total="attendanceTotal"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="loadAttendance"
          @size-change="onAttendancePageSizeChange"
        />
      </div>
    </template>

    <template v-else-if="activeTab === 'daily_stats'">
      <div class="admin-toolbar">
        <el-select
          v-model="dailyFilters.employee_id"
          clearable
          placeholder="员工"
          style="width: 140px"
          @change="reloadDailyStats"
        >
          <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
        </el-select>
        <el-select
          v-model="dailyFilters.department_id"
          clearable
          placeholder="部门"
          style="width: 140px"
          @change="reloadDailyStats"
        >
          <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
        <el-date-picker
          v-model="dailyWorkDate"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="日期"
          style="width: 160px"
          :clearable="false"
          @change="reloadDailyStats"
        />
        <el-button :loading="dailyLoading" @click="loadDailyStats">刷新</el-button>
        <div class="spacer" />
        <span class="muted">按日查询；效率：个人/单款/单款平均（双/小时）；单人平均（双/人/小时）；工序多人（双/N人/小时）</span>
      </div>
      <div ref="dailyTableHostRef" class="attendance-table-host">
        <el-table
          ref="dailyTableRef"
          v-loading="dailyLoading"
          class="attendance-table"
          :data="dailyRows"
          border
          stripe
          style="width: 100%; max-width: 100%"
          :max-height="dailyTableMaxHeight"
          :span-method="dailySpanMethod"
          show-summary
          :summary-method="getDailySummaries"
          @header-dragend="onDailyHeaderDragend"
        >
          <el-table-column
            prop="department_name"
            label="部门"
            :width="dailyColWidth('department_name', 100)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="process_name"
            label="工序"
            :width="dailyColWidth('process_name', 100)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="employee_name"
            label="员工"
            :width="dailyColWidth('employee_name', 90)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            column-key="work_minutes"
            label="出勤时长"
            :width="dailyColWidth('work_minutes', 100)"
            resizable
          >
            <template #default="{ row }">{{ formatWorkMinutes(row.work_minutes) }}</template>
          </el-table-column>
          <el-table-column
            prop="product_code"
            label="工厂型号"
            :width="dailyColWidth('product_code', 110)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="color_name"
            label="颜色"
            :width="dailyColWidth('color_name', 80)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.color_name || '—' }}</template>
          </el-table-column>
          <el-table-column column-key="unit_price" label="工价" :width="dailyColWidth('unit_price', 80)" resizable>
            <template #default="{ row }">{{ formatMoney(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column prop="qty" label="报工数量" :width="dailyColWidth('qty', 90)" resizable />
          <el-table-column column-key="wage" label="工资" :width="dailyColWidth('wage', 90)" resizable>
            <template #default="{ row }">{{ formatMoney(row.wage) }}</template>
          </el-table-column>
          <el-table-column column-key="loss" label="分担损失" :width="dailyColWidth('loss', 90)" resizable>
            <template #default="{ row }">{{ formatMoney(row.loss) }}</template>
          </el-table-column>
          <el-table-column
            column-key="personal_efficiency"
            label="个人效率"
            :width="dailyColWidth('personal_efficiency', 100)"
            resizable
          >
            <template #default="{ row }">{{ formatEff(row.personal_efficiency) }}</template>
          </el-table-column>
          <el-table-column
            column-key="model_efficiency"
            label="单款效率"
            :width="dailyColWidth('model_efficiency', 100)"
            resizable
          >
            <template #default="{ row }">{{ formatEff(row.model_efficiency) }}</template>
          </el-table-column>
          <el-table-column
            column-key="model_avg_efficiency"
            label="单款平均效率"
            :width="dailyColWidth('model_avg_efficiency', 120)"
            resizable
          >
            <template #default="{ row }">{{ formatEff(row.model_avg_efficiency) }}</template>
          </el-table-column>
          <el-table-column
            column-key="avg_efficiency"
            label="单人平均效率"
            :width="dailyColWidth('avg_efficiency', 120)"
            resizable
          >
            <template #default="{ row }">
              <template v-if="row.avg_efficiency != null">{{ formatEff(row.avg_efficiency, '双/人/小时') }}</template>
              <template v-else>—</template>
            </template>
          </el-table-column>
          <el-table-column
            column-key="process_efficiency"
            label="工序多人效率"
            :width="dailyColWidth('process_efficiency', 130)"
            resizable
          >
            <template #default="{ row }">
              <template v-if="row.process_efficiency != null">
                {{ formatEff(row.process_efficiency, `双/${row.process_worker_count}人/小时`) }}
              </template>
              <template v-else>—</template>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div class="admin-pagination">
        <el-pagination
          v-model:current-page="dailyPage"
          v-model:page-size="dailyPageSize"
          background
          layout="total, sizes, prev, pager, next"
          :total="dailyTotal"
          :page-sizes="[20, 50, 100, 200]"
          @current-change="loadDailyStats"
          @size-change="onDailyPageSizeChange"
        />
      </div>
    </template>

    <el-dialog v-model="correctVisible" title="修改报工" width="440px">
      <p class="muted" style="margin: 0 0 12px">
        原单 #{{ correctRow?.id }} 将标记为「更正」并回滚进度，再按新数量重新入账。
        <span v-if="correctRow?.group_id">集体报工会整组一并更正。</span>
      </p>
      <el-form label-width="90px">
        <el-form-item v-if="correctRow?.report_type === 'rework'" label="返修数量">
          <el-input-number v-model="correctForm.rework_qty" :min="1" />
        </el-form-item>
        <template v-else>
          <el-form-item label="合格数量">
            <el-input-number v-model="correctForm.qualified_qty" :min="0" />
          </el-form-item>
          <el-form-item label="次品数量">
            <el-input-number v-model="correctForm.defect_qty" :min="0" :precision="2" :step="0.01" @change="onCorrectDefectChange" />
          </el-form-item>
        </template>
        <el-form-item label="所占百分比">
          <el-input-number
            v-model="correctForm.loss_borne_percent"
            :min="0"
            :max="100"
            :precision="0"
            :step="1"
            :disabled="Number(correctForm.defect_qty || 0) <= 0"
          />
          <span style="margin-left: 6px">%</span>
        </el-form-item>
        <el-form-item label="损失金额">
          <el-input-number v-model="correctForm.loss_amount" :min="0" :precision="2" :step="0.01" />
        </el-form-item>
        <el-form-item label="工资联动">
          <span>
            本笔工资 ¥{{ correctGrossWage.toFixed(2) }} − 扣减 ¥{{ correctLossDeduction.toFixed(2) }}
            = <strong>¥{{ correctNetWage.toFixed(2) }}</strong>
          </span>
        </el-form-item>
        <el-form-item label="颜色">
          <el-input v-model="correctForm.color_name" placeholder="可空" />
        </el-form-item>
        <el-form-item label="尺码">
          <el-input v-model="correctForm.size_value" placeholder="可空，如 37" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="correctForm.review_note" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="correctVisible = false">取消</el-button>
        <el-button type="primary" :loading="correctSaving" @click="saveCorrect">确认更正</el-button>
      </template>
    </el-dialog>
  </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const tableRef = ref()
const anomalyTableRef = ref()
const attendanceTableRef = ref()
const dailyTableRef = ref()
const { colWidth, onHeaderDragend } = useTableColWidths('worklogs-list', tableRef, {
  flexKey: 'review_note',
  flexDefaultMin: 120,
  fitToContainer: true,
})
const { colWidth: anomalyColWidth, onHeaderDragend: onAnomalyHeaderDragend } = useTableColWidths(
  'worklogs-anomalies',
  anomalyTableRef,
  { flexKey: 'reasons', flexDefaultMin: 260, fitToContainer: true },
)
const {
  colWidth: attendanceColWidth,
  onHeaderDragend: onAttendanceHeaderDragend,
  relayoutTable: relayoutAttendanceTable,
} = useTableColWidths('attendance-list', attendanceTableRef, {
  flexKey: 'department_name',
  flexDefaultMin: 96,
  fitToContainer: true,
})
const {
  colWidth: dailyColWidth,
  onHeaderDragend: onDailyHeaderDragend,
  relayoutTable: relayoutDailyTable,
} = useTableColWidths('attendance-daily-stats', dailyTableRef, {
  flexKey: 'product_code',
  flexDefaultMin: 110,
  fitToContainer: true,
})
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const {
  tableHostRef: dailyTableHostRef,
  tableMaxHeight: dailyTableMaxHeight,
  measureTableHeight: measureDailyTableHeight,
} = useTableMaxHeight()
const workers = ref<any[]>([])
const departments = ref<any[]>([])
const activeTab = ref<'work_logs' | 'attendance' | 'daily_stats'>('work_logs')
const attendanceRows = ref<any[]>([])
const attendanceTotal = ref(0)
const attendancePage = ref(1)
const attendancePageSize = ref(20)
const attendanceLoading = ref(false)
const attendanceDateRange = ref<string[]>([])
const attendanceFilters = reactive<{ employee_id?: number; department_id?: number }>({})
const dailyRows = ref<any[]>([])
const dailySummary = ref<any>({})
const dailyTotal = ref(0)
const dailyPage = ref(1)
const dailyPageSize = ref(50)
const dailyLoading = ref(false)
const dailyWorkDate = ref('')
const dailyFilters = reactive<{ employee_id?: number; department_id?: number }>({})
const segments = ref<any[]>([])
const rows = ref<any[]>([])
const summary = ref<any>({})
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const dateRange = ref<string[]>([])
const filters = reactive<{ worker_id?: number; order_no?: string; segment_id?: number; status?: string }>({
  status: 'valid',
})
const anomalyMode = ref(false)
const anomalyLoading = ref(false)
const anomalyRows = ref<any[]>([])
const anomalyMessage = ref('')
const anomalyRange = reactive<{ date_from?: string; date_to?: string }>({})
const correctVisible = ref(false)
const correctSaving = ref(false)
const correctRow = ref<any>(null)
const correctForm = reactive({
  qualified_qty: 0,
  defect_qty: 0,
  rework_qty: 0,
  color_name: '',
  size_value: '',
  review_note: '',
  loss_borne_percent: 0,
  loss_amount: 0,
})
const correctGrossWage = computed(() => {
  const qty = correctRow.value?.report_type === 'rework'
    ? Number(correctForm.rework_qty || 0)
    : Number(correctForm.qualified_qty || 0)
  return Number(correctRow.value?.unit_price || 0) * qty
})
const correctLossDeduction = computed(() => {
  if (Number(correctForm.defect_qty || 0) <= 0) return 0
  return Math.round(
    Number(correctForm.loss_amount || 0) * Number(correctForm.loss_borne_percent || 0)
  ) / 100
})
const correctNetWage = computed(() => correctGrossWage.value - correctLossDeduction.value)

function estimatedWage(row: any) {
  if (row.system_generated) return -Number(row.wage_deduction || 0)
  const qty = row.report_type === 'rework' ? row.rework_qty : row.qualified_qty
  const gross = Number(row.unit_price || 0) * Number(qty || 0)
  const deduction = Number(row.defect_qty || 0) > 0
    ? Number(row.loss_amount || 0) * Number(row.loss_borne_percent || 0) / 100
    : 0
  return gross - deduction
}

function formatWorkMinutes(value: number) {
  const minutes = Number(value || 0)
  if (!minutes) return '—'
  return `${Math.floor(minutes / 60)}小时${minutes % 60}分`
}

function formatMoney(value: number | null | undefined) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return Number(value).toFixed(2)
}

function formatEff(value: number | null | undefined, unit = '双/小时') {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `${Number(value).toFixed(3)} ${unit}`
}

function attendanceStatusLabel(value: string) {
  return ({ normal: '正常', incomplete: '缺卡', not_clocked: '未打卡' } as Record<string, string>)[value] || value
}

const DAILY_DEPT_KEYS = new Set(['department_name'])
const DAILY_PROCESS_KEYS = new Set(['process_name', 'avg_efficiency', 'process_efficiency'])
const DAILY_EMP_KEYS = new Set(['employee_name', 'work_minutes', 'personal_efficiency'])

function dailySpanMethod({ row, column }: { row: any; column: any }) {
  const key = column.property || column.columnKey
  if (DAILY_DEPT_KEYS.has(key)) {
    return row._dept_span > 0 ? [row._dept_span, 1] : [0, 0]
  }
  if (DAILY_PROCESS_KEYS.has(key)) {
    return row._process_span > 0 ? [row._process_span, 1] : [0, 0]
  }
  if (DAILY_EMP_KEYS.has(key)) {
    return row._emp_span > 0 ? [row._emp_span, 1] : [0, 0]
  }
  return [1, 1]
}

function localDateText(d = new Date()) {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function ensureDailyWorkDate() {
  if (dailyWorkDate.value) return
  dailyWorkDate.value = localDateText()
}

async function loadAttendance() {
  attendanceLoading.value = true
  try {
    const res: any = await http.get('/attendance/records', {
      params: {
        employee_id: attendanceFilters.employee_id || undefined,
        department_id: attendanceFilters.department_id || undefined,
        date_from: attendanceDateRange.value?.[0] || undefined,
        date_to: attendanceDateRange.value?.[1] || undefined,
        page: attendancePage.value,
        page_size: attendancePageSize.value,
      },
    })
    attendanceRows.value = res.data.items || []
    attendanceTotal.value = res.data.total || 0
    await nextTick()
    relayoutAttendanceTable()
  } finally {
    attendanceLoading.value = false
  }
}

function reloadAttendance() {
  attendancePage.value = 1
  void loadAttendance()
}

function onAttendancePageSizeChange() {
  attendancePage.value = 1
  void loadAttendance()
}

async function loadDailyStats() {
  ensureDailyWorkDate()
  dailyLoading.value = true
  try {
    const res: any = await http.get('/attendance/daily-stats', {
      params: {
        employee_id: dailyFilters.employee_id || undefined,
        department_id: dailyFilters.department_id || undefined,
        work_date: dailyWorkDate.value || undefined,
        page: dailyPage.value,
        page_size: dailyPageSize.value,
      },
    })
    dailyRows.value = res.data.items || []
    dailySummary.value = res.data.summary || {}
    dailyTotal.value = res.data.total || 0
    await nextTick()
    relayoutDailyTable()
    measureDailyTableHeight()
  } finally {
    dailyLoading.value = false
  }
}

function reloadDailyStats() {
  dailyPage.value = 1
  void loadDailyStats()
}

function onDailyPageSizeChange() {
  dailyPage.value = 1
  void loadDailyStats()
}

async function onTabChange(name: string | number) {
  if (name === 'attendance') {
    await nextTick()
    relayoutAttendanceTable()
    await loadAttendance()
    return
  }
  if (name === 'daily_stats') {
    ensureDailyWorkDate()
    await nextTick()
    relayoutDailyTable()
    await loadDailyStats()
  }
}

function getSummaries({ columns }: { columns: any[] }) {
  return columns.map((column, index) => {
    if (index === 0) return '汇总'
    const key = column.property || column.columnKey || column.rawColumnKey
    if (key === 'estimated_wage') {
      return `¥${Number(summary.value.estimated_wage_total || 0).toFixed(2)}`
    }
    if (key === 'qualified_qty') return Number(summary.value.qualified_qty_total || 0)
    return ''
  })
}

function getDailySummaries({ columns }: { columns: any[] }) {
  return columns.map((column, index) => {
    if (index === 0) return '汇总'
    const key = column.property || column.columnKey || column.rawColumnKey
    if (key === 'work_minutes') return formatWorkMinutes(dailySummary.value.work_minutes_total || 0)
    if (key === 'qty') return Number(dailySummary.value.qty_total || 0)
    if (key === 'wage') return formatMoney(dailySummary.value.wage_total)
    if (key === 'loss') return formatMoney(dailySummary.value.loss_total)
    return ''
  })
}

function reasonTagType(code: string) {
  return (
    ({
      qty_over_plan: 'danger',
      process_over_plan: 'danger',
      void_in_locked_month: 'danger',
      price_outlier: 'warning',
    } as any)[code] || 'warning'
  )
}

function defaultAnomalyRange() {
  const now = new Date()
  const first = new Date(now.getFullYear(), now.getMonth(), 1)
  const pad = (n: number) => String(n).padStart(2, '0')
  const fmt = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  anomalyRange.date_from = fmt(first)
  anomalyRange.date_to = fmt(now)
}

async function loadAnomalies() {
  anomalyLoading.value = true
  try {
    const res: any = await http.get('/work-logs/anomalies', {
      params: {
        date_from: anomalyRange.date_from || undefined,
        date_to: anomalyRange.date_to || undefined,
      },
    })
    anomalyRows.value = res.data.items || []
    anomalyMessage.value = res.data.message || ''
  } finally {
    anomalyLoading.value = false
  }
}

async function toggleAnomalyMode() {
  anomalyMode.value = !anomalyMode.value
  if (anomalyMode.value) {
    if (!anomalyRange.date_from) defaultAnomalyRange()
    await loadAnomalies()
  }
}

function locateInList(row: any) {
  anomalyMode.value = false
  filters.order_no = row.order_no || undefined
  filters.worker_id = row.worker_id || undefined
  filters.status = undefined
  reloadFromFilter()
}

async function load() {
  const res: any = await http.get('/work-logs', {
    params: {
      worker_id: filters.worker_id || undefined,
      order_no: filters.order_no || undefined,
      segment_id: filters.segment_id || undefined,
      date_from: dateRange.value?.[0] || undefined,
      date_to: dateRange.value?.[1] || undefined,
      status: filters.status || undefined,
      page: page.value,
      page_size: pageSize.value,
    },
  })
  rows.value = res.data.items
  summary.value = res.data.summary || {}
  total.value = res.data.total || 0
  if (!rows.value.length && page.value > 1 && total.value > 0) {
    page.value = Math.max(1, Math.ceil(total.value / pageSize.value))
    await load()
  }
}

function onPageSizeChange() {
  page.value = 1
  void load()
}

function reloadFromFilter() {
  page.value = 1
  void load()
}

async function voidLog(row: any) {
  const tip = row.group_id
    ? `确认删除报工 #${row.id}？集体报工会整组删除，回滚工序进度且不计工资。`
    : `确认删除报工 #${row.id}？将回滚工序进度且不计工资。`
  await ElMessageBox.confirm(tip, '删除确认')
  await http.patch(`/work-logs/${row.id}`, { status: 'void', review_note: '管理端删除' })
  ElMessage.success('已删除并回滚进度')
  await load()
}

async function rejectAppeal(row: any) {
  await ElMessageBox.confirm(`驳回申诉 #${row.id}，恢复为有效并计薪？`, '驳回申诉')
  const res: any = await http.patch(`/work-logs/${row.id}`, {
    status: 'valid',
    review_note: '申诉驳回，维持原报工',
  })
  ElMessage.success(res.data?.message || '已驳回')
  await load()
}

function openCorrect(row: any) {
  correctRow.value = row
  const total =
    row.group_id && row.group_total_qty != null ? Number(row.group_total_qty) : Number(row.qualified_qty || 0)
  correctForm.qualified_qty = row.report_type === 'rework' ? 0 : total
  correctForm.defect_qty = row.defect_qty || 0
  correctForm.rework_qty = row.rework_qty || (row.report_type === 'rework' ? total : 0)
  correctForm.color_name = row.color_name || ''
  correctForm.size_value = row.size_value || ''
  correctForm.review_note = ''
  correctForm.loss_borne_percent = Number(row.defect_qty || 0) > 0
    ? Math.round(Number(row.loss_borne_percent || 0))
    : 0
  correctForm.loss_amount = Number(row.loss_amount || 0)
  correctVisible.value = true
}

function onCorrectDefectChange(value: number | undefined) {
  if (Number(value || 0) <= 0) correctForm.loss_borne_percent = 0
}

async function saveCorrect() {
  if (!correctRow.value) return
  correctSaving.value = true
  try {
    const res: any = await http.post(`/work-logs/${correctRow.value.id}/correct`, {
      qualified_qty: correctForm.qualified_qty,
      defect_qty: correctForm.defect_qty,
      rework_qty: correctForm.rework_qty,
      color_name: correctForm.color_name || null,
      size_value: correctForm.size_value || null,
      review_note: correctForm.review_note || null,
      loss_borne_percent: Number(correctForm.defect_qty || 0) > 0
        ? Math.round(Number(correctForm.loss_borne_percent || 0))
        : 0,
      loss_amount: Number(correctForm.loss_amount || 0).toFixed(2),
    })
    ElMessage.success(res.data?.message || '已更正')
    correctVisible.value = false
    await load()
  } finally {
    correctSaving.value = false
  }
}

onMounted(async () => {
  const [w, segmentRes, departmentRes]: any[] = await Promise.all([
    http.get('/workers', { params: { page_size: 200 } }),
    http.get('/process-segments', { params: { active_only: true } }),
    http.get('/departments'),
  ])
  workers.value = w.data.items
  segments.value = segmentRes.data.items || []
  departments.value = departmentRes.data.items || []
  await load()
  measureTableHeight()
})
</script>

<style scoped>
.attendance-table-host {
  width: 100%;
  max-width: 100%;
  min-width: 0;
}

.attendance-table {
  width: 100% !important;
  max-width: 100%;
}

.product-thumb {
  width: 100%;
  aspect-ratio: 1 / 1;
  height: auto;
  display: block;
  border-radius: 4px;
}

.product-thumb :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

:deep(td.product-image-col) {
  padding: 2px !important;
}

:deep(th.product-image-col) {
  padding: 8px 2px !important;
}
</style>
