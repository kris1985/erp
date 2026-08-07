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

const auth = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const cfg = ref<ReportingConfig>({
  allow_unassigned_report: true,
  rework_pays: true,
  allow_over_plan: true,
  over_plan_requires_confirm: true,
})

const isAdmin = computed(() => auth.role === 'admin' || auth.baseRole === 'admin')

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/reporting-settings')
    cfg.value = {
      allow_unassigned_report: !!res.data?.allow_unassigned_report,
      rework_pays: !!res.data?.rework_pays,
      allow_over_plan: !!res.data?.allow_over_plan,
      over_plan_requires_confirm: !!res.data?.over_plan_requires_confirm,
    }
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const res: any = await http.patch('/reporting-settings', { ...cfg.value })
    cfg.value = {
      allow_unassigned_report: !!res.data?.allow_unassigned_report,
      rework_pays: !!res.data?.rework_pays,
      allow_over_plan: !!res.data?.allow_over_plan,
      over_plan_requires_confirm: !!res.data?.over_plan_requires_confirm,
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
        <p class="page-desc">未派可否报 · 返修是否计薪 · 超计划怎么处理</p>
      </div>
    </header>

    <div class="admin-card">
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
