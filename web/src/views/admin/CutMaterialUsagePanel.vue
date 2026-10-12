<template>
  <div class="cut-panel">
    <div v-if="showTitle" class="cut-panel-head">
      <h2 class="cut-panel-title">裁断用料情况</h2>
      <span class="cut-panel-hint">按工厂型号汇总 · 只计裁断段已签收领料和有效合格报工</span>
    </div>
    <p v-else class="cut-panel-hint cut-panel-hint-solo">按工厂型号汇总 · 只计裁断段已签收领料和有效合格报工</p>
    <div class="admin-toolbar">
      <div class="report-model-select-wrap" :class="{ 'has-thumb': selectedCutModel?.image_url }">
        <img
          v-if="selectedCutModel?.image_url"
          :src="selectedCutModel.image_url"
          alt=""
          class="cut-model-selected-thumb"
        />
        <el-select
          v-model="cutModel"
          class="report-model-select"
          clearable
          filterable
          placeholder="工厂型号"
          :fit-input-width="false"
          popper-class="cut-model-popper"
          @visible-change="onCutModelVisible"
        >
          <el-option
            v-for="item in cutModelOptions"
            :key="item.factory_model"
            :label="item.factory_model"
            :value="item.factory_model"
          >
            <span class="cut-model-option">
              <img
                v-if="item.image_url"
                :src="item.image_url"
                alt=""
                @mouseenter="onModelThumbEnter($event, item.image_url)"
                @mouseleave="onModelThumbLeave"
              />
              <span v-else class="cut-model-option-ph" />
              <span class="cut-model-option-name">{{ item.factory_model }}</span>
            </span>
          </el-option>
        </el-select>
      </div>
      <el-date-picker
        v-model="cutDateRange"
        class="report-date-range"
        type="daterange"
        value-format="YYYY-MM-DD"
        range-separator="至"
        start-placeholder="开始"
        end-placeholder="结束"
        unlink-panels
        clearable
      />
    </div>
    <div v-loading="cutLoading">
      <p v-if="!cutQueried" class="report-cut-empty">选择工厂型号或日期。</p>
      <p v-else-if="!cutLoading && !cutModels.length" class="report-cut-empty">没有裁断领料或报工</p>
      <CutMaterialUsageTable
        v-if="cutModels.length"
        :models="cutModels"
        :date-from="cutDateRange?.[0]"
        :date-to="cutDateRange?.[1]"
        @applied="loadCut"
      />
      <Teleport to="body">
        <img
          v-if="modelThumbZoom"
          :src="modelThumbZoom"
          alt=""
          class="cut-model-zoom"
          :style="{ left: `${modelThumbZoomPos.x}px`, top: `${modelThumbZoomPos.y}px` }"
        />
      </Teleport>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import http from '@/api/http'
import CutMaterialUsageTable, { type CutModel } from '@/views/admin/CutMaterialUsageTable.vue'

withDefaults(defineProps<{ showTitle?: boolean }>(), { showTitle: true })

const cutModel = ref('')
const cutDateRange = ref<[string, string] | null>(null)
const cutLoading = ref(false)
const cutQueried = ref(false)
const cutModels = ref<CutModel[]>([])
const cutModelOptions = ref<{ factory_model: string; image_url: string | null }[]>([])
const selectedCutModel = computed(
  () => cutModelOptions.value.find((item) => item.factory_model === cutModel.value) || null,
)
const modelThumbZoom = ref('')
const modelThumbZoomPos = ref({ x: 0, y: 0 })
const cutCanQuery = computed(() => Boolean(cutModel.value) || cutDateRange.value?.length === 2)
let cutRequest = 0

function onModelThumbEnter(event: MouseEvent, url: string) {
  const thumb = event.currentTarget as HTMLElement
  const dropdown = thumb.closest('.el-select-dropdown')
  const drop = dropdown?.getBoundingClientRect()
  const row = thumb.getBoundingClientRect()
  const size = 336
  const gap = 8
  let x = (drop?.right ?? row.right) + gap
  let y = row.top + row.height / 2 - size / 2
  if (x + size > window.innerWidth - 8) x = (drop?.left ?? row.left) - size - gap
  y = Math.max(8, Math.min(y, window.innerHeight - size - 8))
  modelThumbZoomPos.value = { x, y }
  modelThumbZoom.value = url
}

function onModelThumbLeave() {
  modelThumbZoom.value = ''
}

function onCutModelVisible(open: boolean) {
  if (!open) modelThumbZoom.value = ''
}

async function loadCutModels() {
  try {
    const res: any = await http.get('/business-report/cut-material-models')
    cutModelOptions.value = res.data || []
  } catch {
    cutModelOptions.value = []
  }
}

async function loadCut() {
  if (!cutCanQuery.value) {
    cutRequest += 1
    cutQueried.value = false
    cutModels.value = []
    cutLoading.value = false
    return
  }
  const request = ++cutRequest
  cutLoading.value = true
  try {
    const params: Record<string, string> = {}
    if (cutDateRange.value?.length === 2) {
      params.date_from = cutDateRange.value[0]
      params.date_to = cutDateRange.value[1]
    }
    if (cutModel.value) params.factory_model = cutModel.value
    const res: any = await http.get('/business-report/cut-material-usage', { params, timeout: 60000 })
    if (request !== cutRequest) return
    const models: CutModel[] = res.data?.models || []
    cutModels.value = cutModel.value
      ? models.filter((row) => row.factory_model === cutModel.value)
      : models
  } catch {
    if (request !== cutRequest) return
    cutModels.value = []
  } finally {
    if (request === cutRequest) {
      cutQueried.value = true
      cutLoading.value = false
    }
  }
}

watch([cutModel, cutDateRange], () => {
  void loadCut()
})

onMounted(() => {
  void loadCutModels()
})
</script>

<style scoped>
.cut-panel-head {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px 12px;
  margin: 0 0 12px;
}
.cut-panel-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}
.cut-panel-hint {
  font-size: 12px;
  color: #94a3b8;
  min-width: 0;
  line-height: 1.4;
}
.cut-panel-hint-solo {
  margin: 0 0 12px;
}
.report-cut-empty {
  margin: 0 0 12px;
  font-size: 13px;
  color: #94a3b8;
}
:deep(.report-date-range.el-date-editor) {
  flex: 0 0 240px;
  width: 240px;
  max-width: 240px;
  --el-date-editor-width: 240px;
}
:deep(.report-model-select) {
  flex: 0 0 220px;
  width: 220px;
}
.report-model-select-wrap {
  position: relative;
  flex: 0 0 220px;
  width: 220px;
}
.report-model-select-wrap :deep(.report-model-select) {
  width: 100%;
}
.cut-model-selected-thumb {
  position: absolute;
  left: 8px;
  top: 50%;
  z-index: 1;
  width: 22px;
  height: 22px;
  border-radius: 4px;
  object-fit: cover;
  transform: translateY(-50%);
  pointer-events: none;
}
.report-model-select-wrap.has-thumb :deep(.el-select__wrapper) {
  padding-left: 36px;
}
</style>

<style>
.cut-model-popper .el-select-dropdown__item {
  height: 36px;
  line-height: 36px;
}
.cut-model-option {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.cut-model-option img,
.cut-model-option-ph {
  width: 22px;
  height: 22px;
  border-radius: 4px;
  object-fit: cover;
  flex: 0 0 22px;
  background: #f1f5f9;
}
.cut-model-option img {
  cursor: zoom-in;
}
.cut-model-zoom {
  position: fixed;
  z-index: 5000;
  width: 336px;
  height: 336px;
  padding: 6px;
  object-fit: contain;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #fff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.18);
  pointer-events: none;
}
.cut-model-option-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
