<template>
  <div class="wizard-page">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">车间初始化向导</h1>
        <p class="page-desc">无部门数据时出现：按「小厂直管 / 班组管理」一键生成组织树（P5/35，D6/D7）</p>
      </div>
    </header>

    <div class="admin-card wizard-card">
      <el-steps :active="step" align-center finish-status="success" style="margin-bottom: 24px">
        <el-step title="模式" description="有无班组" />
        <el-step title="叫法" description="车间单位" />
        <el-step title="工艺" description="铲皮段" />
        <el-step title="负责人" description="按段指定" />
      </el-steps>

      <!-- 步骤1：模式 -->
      <div v-if="step === 0" class="wizard-step">
        <div class="section-label">车间是否有独立负责的班组 / 线组？</div>
        <div class="wizard-options">
          <div
            class="wizard-option"
            :class="{ active: form.mode === 'simple' }"
            @click="form.mode = 'simple'"
          >
            <div class="wizard-option__title">小厂直管（无班组）</div>
            <div class="wizard-option__desc">
              工人直接归部门/工序段，按个人计件；界面不出现班组（D6 隐身默认组，数据层照常）
            </div>
          </div>
          <div
            class="wizard-option"
            :class="{ active: form.mode === 'teams' }"
            @click="form.mode = 'teams'"
          >
            <div class="wizard-option__title">班组管理</div>
            <div class="wizard-option__desc">
              段部门下建班组，集体计件按技能系数分；成型段由组长按线报产量（D22）
            </div>
          </div>
        </div>
      </div>

      <!-- 步骤2：术语 -->
      <div v-if="step === 1" class="wizard-step">
        <div class="section-label">车间单位叫什么？</div>
        <div class="wizard-options">
          <div
            v-for="o in teamLabelOptions"
            :key="o.value"
            class="wizard-option"
            :class="{ active: form.team_label === o.value }"
            @click="form.team_label = o.value"
          >
            <div class="wizard-option__title">{{ o.label }}</div>
            <div class="wizard-option__desc">{{ o.desc }}</div>
          </div>
        </div>
      </div>

      <!-- 步骤3：工艺 -->
      <div v-if="step === 2" class="wizard-step">
        <div class="section-label">是否需要铲皮工序段？</div>
        <div class="wizard-options">
          <div class="wizard-option" :class="{ active: !form.skiving_enabled }" @click="form.skiving_enabled = false">
            <div class="wizard-option__title">不需要（默认）</div>
            <div class="wizard-option__desc">工艺路线默认 4 段：截断 / 针车 / 成型 / 包装</div>
          </div>
          <div class="wizard-option" :class="{ active: form.skiving_enabled }" @click="form.skiving_enabled = true">
            <div class="wizard-option__title">需要铲皮段</div>
            <div class="wizard-option__desc">工艺路线预填含第 5 段（铲皮，is_optional）</div>
          </div>
        </div>
      </div>

      <!-- 步骤4：负责人（可选） -->
      <div v-if="step === 3" class="wizard-step">
        <div class="section-label">按段指定负责人（可选，未导入员工可跳过）</div>
        <div class="leader-map">
          <div v-for="seg in segments" :key="seg.code" class="leader-row">
            <span class="leader-row__name">{{ seg.name }}段</span>
            <el-select
              v-model="leaderMap[seg.code]"
              clearable
              filterable
              placeholder="不指定"
              style="width: 220px"
            >
              <el-option v-for="e in employees" :key="e.id" :label="e.name" :value="e.id" />
            </el-select>
          </div>
        </div>
      </div>

      <div class="wizard-actions">
        <el-button v-if="step > 0" @click="step -= 1">上一步</el-button>
        <el-button v-if="step < 3" type="primary" @click="step += 1">下一步</el-button>
        <el-button v-else type="primary" :loading="submitting" @click="submit">完成初始化</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '@/api/http'

const router = useRouter()
const step = ref(0)
const submitting = ref(false)
const segments = ref<any[]>([])
const employees = ref<any[]>([])

const teamLabelOptions = [
  { value: '班组', label: '班组', desc: '常见叫法，适合车间班组制' },
  { value: '部', label: '部', desc: '按部门称谓，如"针车部"' },
  { value: '产线', label: '产线', desc: '流水线称谓，如"成型A线"' },
  { value: '班', label: '班', desc: '简洁称谓，如"针车一班"' },
]

const form = reactive<any>({
  mode: 'simple',
  team_label: '班组',
  skiving_enabled: false,
})
const leaderMap = reactive<Record<string, number | null>>({})

async function load() {
  try {
    const [segRes, empRes, setupRes]: any[] = await Promise.all([
      http.get('/process-segments'),
      http.get('/employees', { params: { page_size: 500, is_active: true } }),
      http.post('/org/setup', { mode: 'simple' }).catch(() => null),
    ])
    segments.value = segRes.data?.items || []
    employees.value = empRes.data?.items || []
    for (const seg of segments.value) leaderMap[seg.code] = null
    // 已有组织数据则跳过本页
    if (setupRes?.data?.skipped) {
      ElMessage.info('已存在组织数据，无需初始化')
      void router.replace('/admin/teams')
    }
  } catch {
    // 未登录等：保持页面
  }
}

async function submit() {
  submitting.value = true
  try {
    const res: any = await http.post('/org/setup', {
      mode: form.mode,
      team_label: form.team_label,
      skiving_enabled: form.skiving_enabled,
      leader_map: Object.fromEntries(
        Object.entries(leaderMap).filter(([, v]) => v != null),
      ),
    })
    if (res.data?.skipped) {
      ElMessage.info('已存在组织数据')
    } else {
      ElMessage.success(`初始化完成：${res.data?.departments ?? 0} 个段部门`)
    }
    void router.replace('/admin/teams')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '初始化失败')
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.wizard-card {
  max-width: 720px;
  margin: 0 auto;
}
.wizard-step {
  padding: 8px 4px;
}
.section-label {
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
}
.wizard-options {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}
.wizard-option {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  padding: 14px;
  cursor: pointer;
  transition: all 0.15s;
}
.wizard-option.active {
  border-color: var(--el-color-primary);
  background: rgba(64, 158, 255, 0.06);
}
.wizard-option__title {
  font-weight: 600;
  margin-bottom: 4px;
}
.wizard-option__desc {
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
}
.leader-map {
  display: grid;
  gap: 10px;
}
.leader-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.leader-row__name {
  width: 90px;
  font-size: 13px;
}
.wizard-actions {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
