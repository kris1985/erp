<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

type ReportingConfig = {
  allow_unassigned_report: boolean
  rework_pays: boolean
  allow_over_plan: boolean
  over_plan_requires_confirm: boolean
}

type ShopFloorConfig = {
  stitch_leader_proxy_report: boolean
}

const auth = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const cfg = ref<ReportingConfig>({
  allow_unassigned_report: true,
  rework_pays: true,
  allow_over_plan: true,
  over_plan_requires_confirm: true,
})
const shop = ref<ShopFloorConfig>({
  stitch_leader_proxy_report: true,
})

const isAdmin = computed(() => auth.role === 'admin' || auth.baseRole === 'admin')

// 工序段重构（28.2-28.4）：组织与车间配置（走 /org/settings）
const org = ref({
  enable_teams: false,
  team_label: '班组',
  skiving_enabled: false,
})
const teamLabelOptions = [
  { value: '班组', label: '班组' },
  { value: '产线', label: '产线' },
  { value: '班', label: '班' },
]

async function load() {
  loading.value = true
  try {
    const [rep, sf, ors]: any[] = await Promise.all([
      http.get('/reporting-settings'),
      http.get('/shop-floor-settings'),
      http.get('/org/settings'),
    ])
    cfg.value = {
      allow_unassigned_report: !!rep.data?.allow_unassigned_report,
      rework_pays: !!rep.data?.rework_pays,
      allow_over_plan: !!rep.data?.allow_over_plan,
      over_plan_requires_confirm: !!rep.data?.over_plan_requires_confirm,
    }
    shop.value = {
      stitch_leader_proxy_report: sf.data?.stitch_leader_proxy_report !== false,
    }
    org.value = {
      enable_teams: !!ors.data?.enable_teams,
      team_label: ors.data?.team_label || '班组',
      skiving_enabled: !!ors.data?.skiving_enabled,
    }
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const [rep, sf, ors]: any[] = await Promise.all([
      http.patch('/reporting-settings', { ...cfg.value }),
      http.patch('/shop-floor-settings', { ...shop.value }),
      http.put('/org/settings', {
        enable_teams: org.value.enable_teams,
        team_label: org.value.team_label,
        skiving_enabled: org.value.skiving_enabled,
      }),
    ])
    cfg.value = {
      allow_unassigned_report: !!rep.data?.allow_unassigned_report,
      rework_pays: !!rep.data?.rework_pays,
      allow_over_plan: !!rep.data?.allow_over_plan,
      over_plan_requires_confirm: !!rep.data?.over_plan_requires_confirm,
    }
    shop.value = {
      stitch_leader_proxy_report: sf.data?.stitch_leader_proxy_report !== false,
    }
    ElMessage.success('已保存')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">报工规则</h1>
        <p class="page-desc">未派可否报 · 代报 / 防冒领 · 返修是否计薪 · 超计划怎么处理</p>
      </div>
    </header>

    <div class="admin-card">
      <div class="section-label">针车现场</div>
      <div class="switch-row">
        <div class="switch-copy">
          <div class="switch-name">组长代报</div>
          <div class="switch-hint">
            默认开。组长扫码后可批量选人一起报，数量均分，工资记所选工人。工人不持机时用。
          </div>
        </div>
        <el-switch v-if="isAdmin" v-model="shop.stitch_leader_proxy_report" />
        <el-tag v-else :type="shop.stitch_leader_proxy_report ? 'success' : 'info'" size="small">
          {{ shop.stitch_leader_proxy_report ? '开' : '关' }}
        </el-tag>
      </div>
      <div class="section-label">组织与车间（工序段重构 28.2-28.4）</div>
      <div class="switch-row">
        <div class="switch-copy">
          <div class="switch-name">启用生产单位</div>
          <div class="switch-hint">
            开启后，已挂工序段的部门下可建班组或产线（由下方叫法决定）。开启 30 天内可回退（隐藏默认单位不删数据）。
          </div>
        </div>
        <el-switch v-if="isAdmin" v-model="org.enable_teams" />
        <el-tag v-else :type="org.enable_teams ? 'success' : 'info'" size="small">
          {{ org.enable_teams ? '开' : '关' }}
        </el-tag>
      </div>
      <div class="switch-row">
        <div class="switch-copy">
          <div class="switch-name">车间单位叫法</div>
          <div class="switch-hint">界面上的生产单位叫什么：班组 / 产线 / 班。与部门是两层，不要用「部」。</div>
        </div>
        <el-select v-if="isAdmin" v-model="org.team_label" style="width: 140px">
          <el-option v-for="o in teamLabelOptions" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
        <el-tag v-else size="small">{{ org.team_label }}</el-tag>
      </div>
      <div class="switch-row">
        <div class="switch-copy">
          <div class="switch-name">铲皮工序段</div>
          <div class="switch-hint">工艺路线默认预填是否含第 5 段（铲皮段，is_optional）。</div>
        </div>
        <el-switch v-if="isAdmin" v-model="org.skiving_enabled" />
        <el-tag v-else :type="org.skiving_enabled ? 'success' : 'info'" size="small">
          {{ org.skiving_enabled ? '开' : '关' }}
        </el-tag>
      </div>

      <div class="section-label">通用</div>
      <div class="switch-row">
        <div class="switch-copy">
          <div class="switch-name">未派工也可报</div>
          <div class="switch-hint">关闭后：工序还没派人时，个人报工会被拦住（集体工序仍须先派至少 2 人）。</div>
        </div>
        <el-switch v-if="isAdmin" v-model="cfg.allow_unassigned_report" />
        <el-tag v-else :type="cfg.allow_unassigned_report ? 'success' : 'info'" size="small">
          {{ cfg.allow_unassigned_report ? '开' : '关' }}
        </el-tag>
      </div>

      <div class="switch-row">
        <div class="switch-copy">
          <div class="switch-name">返修计入计件工资</div>
          <div class="switch-hint">关闭后：返修仍记报工账，但金额按 0，工资汇总也不计返修。</div>
        </div>
        <el-switch v-if="isAdmin" v-model="cfg.rework_pays" />
        <el-tag v-else :type="cfg.rework_pays ? 'success' : 'info'" size="small">
          {{ cfg.rework_pays ? '开' : '关' }}
        </el-tag>
      </div>

      <div class="switch-row">
        <div class="switch-copy">
          <div class="switch-name">允许超额报工</div>
          <div class="switch-hint">关闭后：完成量超过计划直接拒绝，即使点确认也不放行。</div>
        </div>
        <el-switch v-if="isAdmin" v-model="cfg.allow_over_plan" />
        <el-tag v-else :type="cfg.allow_over_plan ? 'success' : 'info'" size="small">
          {{ cfg.allow_over_plan ? '开' : '关' }}
        </el-tag>
      </div>

      <div class="switch-row">
        <div class="switch-copy">
          <div class="switch-name">超额需二次确认</div>
          <div class="switch-hint">仅在「允许超额」打开时生效。关闭后超额会直接写入，不再弹确认。</div>
        </div>
        <el-switch
          v-if="isAdmin"
          v-model="cfg.over_plan_requires_confirm"
          :disabled="!cfg.allow_over_plan"
        />
        <el-tag v-else :type="cfg.over_plan_requires_confirm ? 'success' : 'info'" size="small">
          {{ cfg.over_plan_requires_confirm ? '开' : '关' }}
        </el-tag>
      </div>

      <div v-if="isAdmin" class="admin-toolbar" style="margin-top: 16px">
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.section-label {
  margin: 4px 0 0;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  letter-spacing: 0.04em;
}
.switch-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.switch-row:last-of-type {
  border-bottom: none;
}
.switch-copy {
  min-width: 0;
  flex: 1;
}
.switch-name {
  font-weight: 600;
  color: #0f172a;
}
.switch-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
}
</style>
