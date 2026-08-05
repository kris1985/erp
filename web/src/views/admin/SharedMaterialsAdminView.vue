<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">库存池</h1>
        <p class="page-desc">材料唯一库存余额 · 到货余量与停单释放进池 · 齐套按急单/交期拆分承诺</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-button type="primary" @click="adjustVisible = true">调整库存</el-button>
        <el-button @click="load">刷新</el-button>
      </div>
      <el-table :data="rows" stripe border style="width: 100%">
        <el-table-column label="图片" width="72" align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.image_url"
              :src="row.image_url"
              :preview-src-list="[row.image_url]"
              preview-teleported
              fit="cover"
              class="product-thumb"
            />
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="supplier_product_code" label="物料编码" min-width="120" />
        <el-table-column prop="supplier_product_name" label="物料名称" min-width="180" />
        <el-table-column prop="qty" label="库存" min-width="100" />
        <el-table-column prop="avg_unit_cost" label="均价" min-width="100" />
        <el-table-column prop="updated_at" label="更新时间" min-width="180" />
      </el-table>
    </div>

    <el-dialog v-model="adjustVisible" title="调整库存池" width="420px">
      <el-form label-width="100px">
        <el-form-item label="供应商产品ID">
          <el-input-number v-model="form.supplier_product_id" :min="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="增减数量">
          <el-input-number v-model="form.qty_delta" style="width: 100%" />
        </el-form-item>
        <el-form-item label="单价(入库)">
          <el-input-number v-model="form.unit_cost" :min="0" :step="0.01" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="adjustVisible = false">取消</el-button>
        <el-button type="primary" @click="doAdjust">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'

const rows = ref<any[]>([])
const adjustVisible = ref(false)
const form = reactive({
  supplier_product_id: 0,
  qty_delta: 0,
  unit_cost: undefined as number | undefined,
  note: '',
})

async function load() {
  const res: any = await http.get('/shared-materials')
  rows.value = res.data || []
}

async function doAdjust() {
  await http.post('/shared-materials/adjust', {
    supplier_product_id: form.supplier_product_id,
    qty_delta: form.qty_delta,
    unit_cost: form.unit_cost,
    note: form.note || undefined,
  })
  ElMessage.success('已调整')
  adjustVisible.value = false
  load()
}

onMounted(load)
</script>

<style scoped>
.product-thumb {
  width: 40px;
  height: 40px;
  border-radius: 4px;
}
.product-thumb :deep(.el-image__inner) {
  border-radius: 4px;
}
.muted {
  color: var(--el-text-color-secondary);
}
</style>
