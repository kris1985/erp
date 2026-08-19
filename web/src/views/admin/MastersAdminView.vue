<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">基础资料</h1>
        <p class="page-desc">颜色 · 尺码 · 用量码表 · 分类 · 单位 · 职位 · 工序 · 部件 · 其它成本</p>
      </div>
    </header>
  <div class="admin-card">
    <div ref="tableHostRef">
    <el-tabs v-model="tab">
      <el-tab-pane label="颜色" name="colors">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openColor">新增颜色</el-button>
        </div>
        <el-table :data="colors" stripe border :max-height="tableMaxHeight" @header-dragend="onHeaderDragend">
          <el-table-column prop="id" label="ID" :width="colWidth('id', 70)" resizable />
          <el-table-column prop="name" label="名称" resizable />
          <el-table-column prop="code" label="编码" resizable />
          <el-table-column column-key="actions" label="操作" :width="colWidth('actions', 100)" resizable>
            <template #default="{ row }">
              <el-button link type="primary" @click="editColor(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="尺码" name="sizes">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openSize">新增尺码</el-button>
        </div>
        <el-table :data="sizes" stripe border :max-height="tableMaxHeight" @header-dragend="onHeaderDragend1">
          <el-table-column prop="id" label="ID" :width="colWidth1('id', 70)" resizable />
          <el-table-column prop="size_value" label="尺码" resizable />
          <el-table-column prop="sort_order" label="排序" :width="colWidth1('sort_order', 100)" resizable />
          <el-table-column column-key="is_active" label="启用" :width="colWidth1('is_active', 80)" align="center" resizable>
            <template #default="{ row }">
              <el-tag :type="row.is_active !== false ? 'success' : 'info'" size="small">
                {{ row.is_active !== false ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" :width="colWidth1('actions', 140)" resizable>
            <template #default="{ row }">
              <el-button link type="primary" @click="editSize(row)">编辑</el-button>
              <el-button link @click="toggleSize(row)">
                {{ row.is_active !== false ? '停用' : '启用' }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="用量码表" name="size-usage">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openSizeUsage">新增码表</el-button>
          <el-button @click="seedSizeUsageDefaults">导入默认码表</el-button>
        </div>
        <el-table :data="sizeUsageTables" stripe border :max-height="tableMaxHeight" @header-dragend="onHeaderDragendSu">
          <el-table-column prop="id" label="ID" :width="colWidthSu('id', 70)" resizable />
          <el-table-column prop="name" label="名称" resizable />
          <el-table-column column-key="coeff_n" label="系数行数" :width="colWidthSu('coeff_n', 100)" resizable>
            <template #default="{ row }">{{ (row.coeffs || []).length }}</template>
          </el-table-column>
          <el-table-column prop="notes" label="备注" show-overflow-tooltip resizable />
          <el-table-column column-key="actions" label="操作" :width="colWidthSu('actions', 160)" resizable>
            <template #default="{ row }">
              <el-button link type="primary" @click="editSizeUsage(row)">编辑</el-button>
              <el-button link @click="fillSizeUsage(row)">补全尺码</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="物料分类" name="categories">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openCategory">新增分类</el-button>
          <el-button @click="seedCategories">导入常用分类</el-button>
        </div>
        <el-table :data="categories" stripe border :max-height="tableMaxHeight" @header-dragend="onHeaderDragend2">
          <el-table-column prop="id" label="ID" :width="colWidth2('id', 70)" resizable />
          <el-table-column prop="name" label="名称" resizable />
          <el-table-column column-key="consume_process" label="默认消耗工序" :width="colWidth2('consume_process', 140)" resizable>
            <template #default="{ row }">
              {{ row.default_consume_process_name || '—' }}
            </template>
          </el-table-column>
          <el-table-column column-key="suggest_size" label="建议按码" :width="colWidth2('suggest_size', 100)" align="center" resizable>
            <template #default="{ row }">
              <el-tag :type="row.suggest_usage_by_size ? 'success' : 'info'" size="small">
                {{ row.suggest_usage_by_size ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column column-key="size_table" label="默认码表" :width="colWidth2('size_table', 120)" resizable>
            <template #default="{ row }">{{ row.default_size_usage_table_name || '—' }}</template>
          </el-table-column>
          <el-table-column prop="sort_order" label="排序" :width="colWidth2('sort_order', 100)" resizable />
          <el-table-column column-key="status" label="状态" :width="colWidth2('status', 90)" resizable>
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                {{ row.is_active ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" :width="colWidth2('actions', 160)" resizable>
            <template #default="{ row }">
              <el-button link type="primary" @click="editCategory(row)">编辑</el-button>
              <el-button link @click="toggleCategory(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="计价单位" name="units">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openUnit">新增单位</el-button>
          <el-button @click="seedUnits">导入常用单位</el-button>
        </div>
        <el-table :data="units" stripe border :max-height="tableMaxHeight" @header-dragend="onHeaderDragend3">
          <el-table-column prop="id" label="ID" :width="colWidth3('id', 70)" resizable />
          <el-table-column prop="name" label="名称" resizable />
          <el-table-column prop="sort_order" label="排序" :width="colWidth3('sort_order', 100)" resizable />
          <el-table-column column-key="status" label="状态" :width="colWidth3('status', 90)" resizable>
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                {{ row.is_active ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" :width="colWidth3('actions', 160)" resizable>
            <template #default="{ row }">
              <el-button link type="primary" @click="editUnit(row)">编辑</el-button>
              <el-button link @click="toggleUnit(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="职位" name="positions">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openPosition">新增职位</el-button>
          <el-button @click="seedPositions">导入常用职位</el-button>
        </div>
        <el-table :data="positions" stripe border :max-height="tableMaxHeight" @header-dragend="onHeaderDragend4">
          <el-table-column prop="id" label="ID" :width="colWidth4('id', 70)" resizable />
          <el-table-column prop="name" label="名称" show-overflow-tooltip resizable />
          <el-table-column prop="sort_order" label="排序" :width="colWidth4('sort_order', 100)" resizable />
          <el-table-column column-key="status" label="状态" :width="colWidth4('status', 90)" resizable>
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                {{ row.is_active ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" :width="colWidth4('actions', 160)" resizable>
            <template #default="{ row }">
              <el-button link type="primary" @click="editPosition(row)">编辑</el-button>
              <el-button link @click="togglePosition(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="工序段管理" name="segments">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openSegment">新增工序段</el-button>
          <span class="muted" style="margin-left: 8px">段 = 截断/针车/成型/包装/铲皮；工序归属段（D14）</span>
        </div>
        <el-table :data="segments" stripe border :max-height="tableMaxHeight" @header-dragend="onHeaderDragendSegments">
          <el-table-column prop="id" label="ID" :width="colWidthSegments('id', 70)" resizable />
          <el-table-column prop="name" label="名称" show-overflow-tooltip resizable />
          <el-table-column prop="code" label="编码" :width="colWidthSegments('code', 110)" resizable />
          <el-table-column column-key="optional" label="可选段" :width="colWidthSegments('optional', 90)" resizable>
            <template #default="{ row }">
              <el-tag v-if="row.is_optional" type="warning" size="small">铲皮等</el-tag>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column prop="sort_order" label="排序" :width="colWidthSegments('sort_order', 90)" resizable />
          <el-table-column column-key="status" label="状态" :width="colWidthSegments('status', 90)" resizable>
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                {{ row.is_active ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" :width="colWidthSegments('actions', 170)" resizable>
            <template #default="{ row }">
              <el-button link type="primary" @click="editSegment(row)">编辑</el-button>
              <el-button link @click="toggleSegment(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
              <el-button link type="danger" @click="deleteSegment(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="工序" name="processes">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openProcess">新增工序</el-button>
          <el-button @click="seedProcesses">导入常用工序</el-button>
        </div>
        <el-table :data="processes" stripe border :max-height="tableMaxHeight" @header-dragend="onHeaderDragend5">
          <el-table-column prop="id" label="ID" :width="colWidth5('id', 70)" resizable />
          <el-table-column prop="name" label="名称" show-overflow-tooltip resizable />
          <el-table-column column-key="segment" label="所属工序段" :width="colWidth5('segment', 110)" resizable>
            <template #default="{ row }">
              <el-tag v-if="row.segment_name" size="small">{{ row.segment_name }}</el-tag>
              <span v-else class="muted">未分段</span>
            </template>
          </el-table-column>
          <el-table-column column-key="type" label="类型" :width="colWidth5('type', 90)" resizable>
            <template #default="{ row }">
              {{ row.type === 'group' ? '集体' : '个人' }}
            </template>
          </el-table-column>
          <el-table-column column-key="per_worker_capacity" label="单人日产能" :width="colWidth5('per_worker_capacity', 120)" resizable>
            <template #default="{ row }">
              <span v-if="row.per_worker_capacity != null && Number(row.per_worker_capacity) > 0">
                {{ row.per_worker_capacity }} 双/人/天
              </span>
              <el-tag v-else type="warning" size="small">未配置</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="standard_workers" label="标准人力" :width="colWidth5('standard_workers', 90)" resizable>
            <template #default="{ row }">
              {{ row.standard_workers ?? 1 }} 人
            </template>
          </el-table-column>
          <el-table-column prop="sort_order" label="排序" :width="colWidth5('sort_order', 90)" resizable />
          <el-table-column column-key="status" label="状态" :width="colWidth5('status', 90)" resizable>
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                {{ row.is_active ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" :width="colWidth5('actions', 160)" resizable>
            <template #default="{ row }">
              <el-button link type="primary" @click="editProcess(row)">编辑</el-button>
              <el-button link @click="toggleProcess(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="部件" name="parts">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openPart">新增部件</el-button>
          <el-button @click="seedParts">导入常用部件</el-button>
          <span class="muted" style="margin-left: 8px"
            >合帮前并行加工部件（前帮/后帮等）；自有产品「部件清单」从此选用</span
          >
        </div>
        <el-table :data="parts" stripe border :max-height="tableMaxHeight" @header-dragend="onHeaderDragendParts">
          <el-table-column prop="id" label="ID" :width="colWidthParts('id', 70)" resizable />
          <el-table-column prop="code" label="编码" :width="colWidthParts('code', 120)" resizable />
          <el-table-column prop="name" label="名称" show-overflow-tooltip resizable />
          <el-table-column prop="source" label="来源" :width="colWidthParts('source', 100)" resizable />
          <el-table-column column-key="status" label="状态" :width="colWidthParts('status', 90)" resizable>
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                {{ row.is_active ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" :width="colWidthParts('actions', 160)" resizable>
            <template #default="{ row }">
              <el-button link type="primary" @click="editPart(row)">编辑</el-button>
              <el-button link @click="togglePart(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="其它成本" name="otherCosts">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openOtherCost">新增项目</el-button>
          <el-button @click="seedOtherCosts">导入常用项目</el-button>
        </div>
        <el-table :data="otherCostItems" stripe border :max-height="tableMaxHeight" @header-dragend="onHeaderDragend6">
          <el-table-column prop="id" label="ID" :width="colWidth6('id', 70)" resizable />
          <el-table-column prop="name" label="名称" show-overflow-tooltip resizable />
          <el-table-column prop="sort_order" label="排序" :width="colWidth6('sort_order', 100)" resizable />
          <el-table-column column-key="status" label="状态" :width="colWidth6('status', 90)" resizable>
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                {{ row.is_active ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" :width="colWidth6('actions', 160)" resizable>
            <template #default="{ row }">
              <el-button link type="primary" @click="editOtherCost(row)">编辑</el-button>
              <el-button link @click="toggleOtherCost(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
    </div>

    <el-dialog v-model="sizeUsageVisible" :title="sizeUsageForm.id ? '编辑用量码表' : '新增用量码表'" width="560px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="sizeUsageForm.name" placeholder="如：大底通用" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="sizeUsageForm.notes" /></el-form-item>
        <el-form-item label="系数">
          <el-table :data="sizeUsageForm.coeffs" size="small" border max-height="280">
            <el-table-column label="尺码" width="120">
              <template #default="{ row }">{{ row.size_value || row.size_id }}</template>
            </el-table-column>
            <el-table-column label="系数">
              <template #default="{ row }">
                <el-input-number v-model="row.coeff" :min="0" :precision="4" :step="0.01" controls-position="right" style="width: 100%" />
              </template>
            </el-table-column>
          </el-table>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="sizeUsageVisible = false">取消</el-button>
        <el-button type="primary" @click="saveSizeUsage">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="colorVisible" :title="colorForm.id ? '编辑颜色' : '新增颜色'" width="420px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="colorForm.name" /></el-form-item>
        <el-form-item label="编码"><el-input v-model="colorForm.code" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="colorVisible = false">取消</el-button>
        <el-button type="primary" @click="saveColor">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="sizeVisible" :title="sizeForm.id ? '编辑尺码' : '新增尺码'" width="420px">
      <el-form label-width="80px">
        <el-form-item label="尺码"><el-input v-model="sizeForm.size_value" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="sizeForm.sort_order" :min="0" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="sizeForm.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="sizeVisible = false">取消</el-button>
        <el-button type="primary" @click="saveSize">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="categoryVisible" :title="categoryForm.id ? '编辑分类' : '新增分类'" width="420px">
      <el-form label-width="110px">
        <el-form-item label="名称"><el-input v-model="categoryForm.name" placeholder="如：皮料" /></el-form-item>
        <el-form-item label="默认消耗工序">
          <el-select
            v-model="categoryForm.default_consume_process_id"
            clearable
            filterable
            placeholder="空=未标注（算首道）"
            style="width: 100%"
          >
            <el-option
              v-for="p in processes.filter((x: any) => x.is_active !== false)"
              :key="p.id"
              :label="p.name"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="建议按码">
          <el-switch v-model="categoryForm.suggest_usage_by_size" />
          <span class="muted" style="margin-left: 8px; font-size: 12px">选料时预填 BOM，可改</span>
        </el-form-item>
        <el-form-item v-if="categoryForm.suggest_usage_by_size" label="默认码表">
          <el-select
            v-model="categoryForm.default_size_usage_table_id"
            clearable
            filterable
            placeholder="空则用「大底通用」"
            style="width: 100%"
          >
            <el-option v-for="t in sizeUsageTables" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="排序"><el-input-number v-model="categoryForm.sort_order" :min="0" /></el-form-item>
        <el-form-item v-if="categoryForm.id" label="启用"><el-switch v-model="categoryForm.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="categoryVisible = false">取消</el-button>
        <el-button type="primary" @click="saveCategory">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="unitVisible" :title="unitForm.id ? '编辑单位' : '新增单位'" width="420px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="unitForm.name" placeholder="如：双" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="unitForm.sort_order" :min="0" /></el-form-item>
        <el-form-item v-if="unitForm.id" label="启用"><el-switch v-model="unitForm.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="unitVisible = false">取消</el-button>
        <el-button type="primary" @click="saveUnit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="positionVisible" :title="positionForm.id ? '编辑职位' : '新增职位'" width="420px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="positionForm.name" placeholder="如：针车" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="positionForm.sort_order" :min="0" /></el-form-item>
        <el-form-item v-if="positionForm.id" label="启用"><el-switch v-model="positionForm.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="positionVisible = false">取消</el-button>
        <el-button type="primary" @click="savePosition">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="segmentVisible" :title="segmentForm.id ? '编辑工序段' : '新增工序段'" width="440px">
      <el-form label-width="90px">
        <el-form-item label="名称"><el-input v-model="segmentForm.name" placeholder="如：截断" /></el-form-item>
        <el-form-item label="编码"><el-input v-model="segmentForm.code" placeholder="如：cut" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="segmentForm.sort_order" :min="0" /></el-form-item>
        <el-form-item label="可选段">
          <el-switch v-model="segmentForm.is_optional" />
          <span class="muted" style="font-size: 12px; margin-left: 8px">如铲皮段，按开关显示</span>
        </el-form-item>
        <el-form-item v-if="segmentForm.id" label="启用"><el-switch v-model="segmentForm.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="segmentVisible = false">取消</el-button>
        <el-button type="primary" @click="saveSegment">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="processVisible" :title="processForm.id ? '编辑工序' : '新增工序'" width="480px">
      <el-form label-width="90px">
        <el-form-item label="名称"><el-input v-model="processForm.name" placeholder="如：裁断" /></el-form-item>
        <el-form-item label="所属工序段">
          <el-select v-model="processForm.segment_id" clearable placeholder="未分段" style="width: 100%">
            <el-option v-for="seg in segments" :key="seg.id" :label="seg.name" :value="seg.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="processForm.type" style="width: 100%">
            <el-option label="个人" value="personal" />
            <el-option label="集体" value="group" />
          </el-select>
        </el-form-item>
        <el-form-item label="单人日产能">
          <el-input-number
            v-model="processForm.per_worker_capacity"
            :min="0"
            :precision="2"
            placeholder="双/人/天"
            style="width: 100%"
          />
          <div class="muted" style="font-size: 12px; line-height: 1.4; margin-top: 2px">
            排产天数 = ⌈数量 ÷ (单人日产能 × 标准人力)⌉；不配则无法排产
          </div>
        </el-form-item>
        <el-form-item label="标准人力">
          <el-input-number v-model="processForm.standard_workers" :min="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="排序"><el-input-number v-model="processForm.sort_order" :min="0" /></el-form-item>
        <el-form-item v-if="processForm.id" label="启用"><el-switch v-model="processForm.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="processVisible = false">取消</el-button>
        <el-button type="primary" @click="saveProcess">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="partVisible" :title="partForm.id ? '编辑部件' : '新增部件'" width="480px">
      <el-form label-width="90px">
        <el-form-item label="编码"><el-input v-model="partForm.code" placeholder="如：UPPER" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="partForm.name" placeholder="如：鞋面" /></el-form-item>
        <el-form-item label="来源">
          <el-select v-model="partForm.source" style="width: 100%">
            <el-option label="裁断" value="裁断" />
            <el-option label="外购" value="外购" />
            <el-option label="其他" value="其他" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="partForm.id" label="启用"><el-switch v-model="partForm.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="partVisible = false">取消</el-button>
        <el-button type="primary" @click="savePart">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="otherCostVisible" :title="otherCostForm.id ? '编辑其它成本' : '新增其它成本'" width="420px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="otherCostForm.name" placeholder="如：包装辅料" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="otherCostForm.sort_order" :min="0" /></el-form-item>
        <el-form-item v-if="otherCostForm.id" label="启用"><el-switch v-model="otherCostForm.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="otherCostVisible = false">取消</el-button>
        <el-button type="primary" @click="saveOtherCost">保存</el-button>
      </template>
    </el-dialog>
  </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const route = useRoute()
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const { colWidth, onHeaderDragend } = useTableColWidths('masters-colors')
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths('masters-sizes')
const { colWidth: colWidth2, onHeaderDragend: onHeaderDragend2 } = useTableColWidths('masters-categories')
const { colWidth: colWidth3, onHeaderDragend: onHeaderDragend3 } = useTableColWidths('masters-units')
const { colWidth: colWidth4, onHeaderDragend: onHeaderDragend4 } = useTableColWidths('masters-positions')
const { colWidth: colWidth5, onHeaderDragend: onHeaderDragend5 } = useTableColWidths('masters-processes')
const { colWidth: colWidthSegments, onHeaderDragend: onHeaderDragendSegments } = useTableColWidths('masters-segments')
const { colWidth: colWidth6, onHeaderDragend: onHeaderDragend6 } = useTableColWidths('masters-other-costs')
const { colWidth: colWidthSu, onHeaderDragend: onHeaderDragendSu } = useTableColWidths('masters-size-usage')
const { colWidth: colWidthParts, onHeaderDragend: onHeaderDragendParts } = useTableColWidths('masters-parts')
const DEFAULT_CATEGORIES = [
  '皮料',
  '面料网布',
  '超纤革',
  '内里',
  '鞋垫',
  '大底',
  '中底',
  '泡棉海绵',
  '五金扣',
  '拉链',
  '线材',
  '补强胶膜',
  '胶水化工',
  '鞋带魔术贴',
  '装饰件',
  '包装材料',
  '模具楦头',
  '其他辅料',
]
/** 建议按码 + 默认挂「大底通用」的分类（与后端 DEFAULT_SUGGEST_SIZE_USAGE_CATEGORIES 对齐） */
const DEFAULT_SUGGEST_SIZE_CATEGORIES = new Set(['大底', '中底', '鞋垫'])
/** 常用分类 → 默认消耗工序（与后端 DEFAULT_CATEGORY_CONSUME_PROCESS 对齐） */
const DEFAULT_CATEGORY_CONSUME: Record<string, string> = {
  皮料: '裁断',
  面料网布: '裁断',
  超纤革: '裁断',
  内里: '裁断',
  鞋垫: '成型',
  大底: '成型',
  中底: '成型',
  泡棉海绵: '裁断',
  五金扣: '针车',
  拉链: '针车',
  线材: '针车',
  补强胶膜: '裁断',
  胶水化工: '成型',
  鞋带魔术贴: '成型',
  装饰件: '成型',
  包装材料: '包装',
  模具楦头: '成型',
  其他辅料: '成型',
}
const DEFAULT_UNITS = ['双', '米', '码', '公斤', '个', '套', '卷', '打', '片']
const DEFAULT_POSITIONS = ['裁剪', '针车', '成型', '质检', '包装', '仓管', '杂工']
const DEFAULT_PROCESSES = [
  { name: '裁断', type: 'personal' },
  { name: '针车', type: 'personal' },
  { name: '成型', type: 'group' },
  { name: '质检', type: 'personal' },
  { name: '包装', type: 'personal' },
]
const DEFAULT_OTHER_COSTS = ['包装辅料', '运输摊销', '模具摊销', '样品费', '杂费']
const DEFAULT_PARTS = [
  // 合帮前离散并行加工的部件（扎捆码载体）；大底/中底等走物料 BOM，不进部件字典
  { code: 'QB', name: '前帮', source: '裁断' },
  { code: 'HB', name: '后帮', source: '裁断' },
  { code: 'SX', name: '鞋舌', source: '裁断' },
  { code: 'CB', name: '侧帮', source: '裁断' },
  { code: 'BT', name: '包头', source: '裁断' },
  { code: 'HZ', name: '护踵', source: '裁断' },
]

const MASTER_TABS = new Set([
  'colors',
  'sizes',
  'size-usage',
  'categories',
  'units',
  'positions',
  'processes',
  'parts',
  'otherCosts',
])
const tab = ref('colors')
const colors = ref<any[]>([])
const sizes = ref<any[]>([])
const sizeUsageTables = ref<any[]>([])
const categories = ref<any[]>([])
const units = ref<any[]>([])
const positions = ref<any[]>([])
const processes = ref<any[]>([])
const parts = ref<any[]>([])
const otherCostItems = ref<any[]>([])

const colorVisible = ref(false)
const sizeVisible = ref(false)
const categoryVisible = ref(false)
const unitVisible = ref(false)
const positionVisible = ref(false)
const segmentVisible = ref(false)
const processVisible = ref(false)
const partVisible = ref(false)
const otherCostVisible = ref(false)

const colorForm = reactive<any>({ id: null, name: '', code: '' })
const sizeForm = reactive<any>({ id: null, size_value: '', sort_order: 0, is_active: true })
const categoryForm = reactive<any>({
  id: null,
  name: '',
  sort_order: 0,
  is_active: true,
  default_consume_process_id: null as number | null,
})
const unitForm = reactive<any>({ id: null, name: '', sort_order: 0, is_active: true })
const positionForm = reactive<any>({ id: null, name: '', sort_order: 0, is_active: true })
const segmentForm = reactive<any>({
  id: null,
  name: '',
  code: '',
  sort_order: 0,
  is_optional: false,
  is_active: true,
})
const segments = ref<any[]>([])
const processForm = reactive<any>({
  id: null,
  name: '',
  type: 'personal',
  per_worker_capacity: null,
  standard_workers: 1,
  sort_order: 0,
  is_active: true,
  segment_id: null as number | null,
})
const partForm = reactive<any>({
  id: null,
  code: '',
  name: '',
  source: '裁断',
  is_active: true,
})
const otherCostForm = reactive<any>({ id: null, name: '', sort_order: 0, is_active: true })

function genProcessCode() {
  return `P${Date.now().toString(36).toUpperCase()}`
}

async function load() {
  const [c, s, cats, us, ps, procs, ocs, sut, pts, segs]: any[] = await Promise.all([
    http.get('/colors'),
    http.get('/sizes'),
    http.get('/material-categories'),
    http.get('/pricing-units'),
    http.get('/positions'),
    http.get('/processes'),
    http.get('/other-cost-items'),
    http.get('/material-size-usage-tables'),
    http.get('/part-definitions'),
    http.get('/process-segments'),
  ])
  colors.value = c.data.items
  sizes.value = s.data.items
  categories.value = cats.data.items
  units.value = us.data.items
  positions.value = ps.data.items
  processes.value = procs.data?.items || []
  otherCostItems.value = ocs.data?.items || []
  sizeUsageTables.value = sut.data?.items || []
  parts.value = pts.data?.items || []
  segments.value = segs.data?.items || []

  // 旧合并分类若仍在，自动拆分（就地改名 + 补半边），避免只改种子清单而库数据未动
  const hasLegacy = categories.value.some(
    (x: any) => x.name === '鞋底中底' || x.name === '鞋垫内里',
  )
  if (hasLegacy) {
    await http.post('/material-size-usage-tables/seed-defaults')
    const cats2: any = await http.get('/material-categories')
    categories.value = cats2.data.items
    const sut2: any = await http.get('/material-size-usage-tables')
    sizeUsageTables.value = sut2.data?.items || []
  }

  void nextTick(measureTableHeight)
}

watch(tab, () => void nextTick(measureTableHeight))

function openSegment() {
  Object.assign(segmentForm, {
    id: null,
    name: '',
    code: '',
    sort_order: segments.value.length * 10,
    is_optional: false,
    is_active: true,
  })
  segmentVisible.value = true
}
function editSegment(row: any) {
  Object.assign(segmentForm, {
    id: row.id,
    name: row.name,
    code: row.code,
    sort_order: row.sort_order,
    is_optional: row.is_optional !== false,
    is_active: row.is_active !== false,
  })
  segmentVisible.value = true
}
async function saveSegment() {
  if (!String(segmentForm.name || '').trim()) {
    ElMessage.warning('请填写工序段名称')
    return
  }
  if (segmentForm.id) {
    await http.patch(`/process-segments/${segmentForm.id}`, {
      name: segmentForm.name.trim(),
      code: segmentForm.code,
      sort_order: segmentForm.sort_order,
      is_optional: segmentForm.is_optional,
      is_active: segmentForm.is_active,
    })
  } else {
    await http.post('/process-segments', {
      name: segmentForm.name.trim(),
      code: segmentForm.code,
      sort_order: segmentForm.sort_order,
      is_optional: segmentForm.is_optional,
    })
  }
  ElMessage.success('已保存')
  segmentVisible.value = false
  await load()
}
async function toggleSegment(row: any) {
  await http.patch(`/process-segments/${row.id}`, { is_active: !row.is_active })
  await load()
}
async function deleteSegment(row: any) {
  const res: any = await http.delete(`/process-segments/${row.id}`)
  const d = res?.data || {}
  if (d.deactivated) ElMessage.warning(d.message || '被引用，已改为停用')
  else ElMessage.success('已删除')
  await load()
}
function openColor() {
  Object.assign(colorForm, { id: null, name: '', code: '' })
  colorVisible.value = true
}
function editColor(row: any) {
  Object.assign(colorForm, row)
  colorVisible.value = true
}
async function saveColor() {
  if (colorForm.id) await http.patch(`/colors/${colorForm.id}`, { name: colorForm.name, code: colorForm.code })
  else await http.post('/colors', { name: colorForm.name, code: colorForm.code })
  ElMessage.success('已保存')
  colorVisible.value = false
  await load()
}

function openSize() {
  Object.assign(sizeForm, { id: null, size_value: '', sort_order: sizes.value.length, is_active: true })
  sizeVisible.value = true
}
function editSize(row: any) {
  Object.assign(sizeForm, { ...row, is_active: row.is_active !== false })
  sizeVisible.value = true
}
async function saveSize() {
  const payload = {
    size_value: sizeForm.size_value,
    sort_order: sizeForm.sort_order,
    is_active: sizeForm.is_active !== false,
  }
  if (sizeForm.id) await http.patch(`/sizes/${sizeForm.id}`, payload)
  else await http.post('/sizes', payload)
  ElMessage.success('已保存')
  sizeVisible.value = false
  await load()
}
async function toggleSize(row: any) {
  await http.patch(`/sizes/${row.id}`, { is_active: !(row.is_active !== false) })
  await load()
}

const sizeUsageVisible = ref(false)
const sizeUsageForm = reactive<any>({ id: null, name: '', notes: '', coeffs: [] as any[] })

function openSizeUsage() {
  Object.assign(sizeUsageForm, {
    id: null,
    name: '',
    notes: '',
    coeffs: sizes.value.map((s: any) => ({ size_id: s.id, size_value: s.size_value, coeff: 1 })),
  })
  sizeUsageVisible.value = true
}
function editSizeUsage(row: any) {
  const byId = new Map((row.coeffs || []).map((c: any) => [c.size_id, c]))
  Object.assign(sizeUsageForm, {
    id: row.id,
    name: row.name,
    notes: row.notes || '',
    coeffs: sizes.value.map((s: any) => {
      const hit = byId.get(s.id)
      return {
        size_id: s.id,
        size_value: s.size_value,
        coeff: hit ? Number(hit.coeff) : 1,
      }
    }),
  })
  sizeUsageVisible.value = true
}
async function saveSizeUsage() {
  if (!String(sizeUsageForm.name || '').trim()) {
    ElMessage.warning('请填写码表名称')
    return
  }
  const payload = {
    name: sizeUsageForm.name.trim(),
    notes: sizeUsageForm.notes || null,
    coeffs: (sizeUsageForm.coeffs || []).map((c: any) => ({
      size_id: c.size_id,
      coeff: c.coeff ?? 1,
    })),
  }
  if (sizeUsageForm.id) await http.patch(`/material-size-usage-tables/${sizeUsageForm.id}`, payload)
  else await http.post('/material-size-usage-tables', payload)
  ElMessage.success('已保存')
  sizeUsageVisible.value = false
  await load()
}
async function fillSizeUsage(row: any) {
  const res: any = await http.post(`/material-size-usage-tables/${row.id}/fill-missing`)
  ElMessage.success(`已补全 ${res.data?.added ?? 0} 个尺码`)
  await load()
}
async function seedSizeUsageDefaults() {
  const res: any = await http.post('/material-size-usage-tables/seed-defaults')
  const base = `已导入「${res.data?.name || '大底通用'}」· ${res.data?.coeff_count ?? 0} 个尺码系数`
  const linked = (res.data?.linked_categories || []).filter((n: string) =>
    ['大底', '中底', '鞋垫'].includes(n),
  )
  const consumeN = Number(res.data?.consume_process_updated || 0)
  const bits = [base]
  if (linked.length) bits.push(`建议按码：${linked.join('、')}`)
  if (consumeN) bits.push(`补消耗工序 ${consumeN}`)
  ElMessage.success(bits.join('；'))
  await load()
}

function openCategory() {
  Object.assign(categoryForm, {
    id: null,
    name: '',
    sort_order: categories.value.length,
    is_active: true,
    default_consume_process_id: null,
    suggest_usage_by_size: false,
    default_size_usage_table_id: null,
  })
  categoryVisible.value = true
}
function editCategory(row: any) {
  Object.assign(categoryForm, {
    ...row,
    default_consume_process_id: row.default_consume_process_id ?? null,
    suggest_usage_by_size: !!row.suggest_usage_by_size,
    default_size_usage_table_id: row.default_size_usage_table_id ?? null,
  })
  categoryVisible.value = true
}
async function saveCategory() {
  if (!categoryForm.name.trim()) {
    ElMessage.warning('请填写分类名称')
    return
  }
  const payload = {
    name: categoryForm.name.trim(),
    sort_order: categoryForm.sort_order,
    is_active: categoryForm.is_active,
    default_consume_process_id: categoryForm.default_consume_process_id || null,
    suggest_usage_by_size: !!categoryForm.suggest_usage_by_size,
    default_size_usage_table_id: categoryForm.suggest_usage_by_size
      ? categoryForm.default_size_usage_table_id || null
      : null,
  }
  if (categoryForm.id) await http.patch(`/material-categories/${categoryForm.id}`, payload)
  else await http.post('/material-categories', payload)
  ElMessage.success('已保存')
  categoryVisible.value = false
  await load()
}
async function toggleCategory(row: any) {
  await http.patch(`/material-categories/${row.id}`, { is_active: !row.is_active })
  await load()
}
async function seedCategories() {
  // 先拆旧名再补新类，避免先建空「大底」挡住「鞋底中底」就地改名
  const seedRes: any = await http.post('/material-size-usage-tables/seed-defaults')
  await load()

  const existing = new Set(categories.value.map((x) => x.name))
  const processByName = Object.fromEntries(
    processes.value.filter((p: any) => p.is_active !== false).map((p: any) => [p.name, p.id]),
  )
  const fallbackPid = processByName['成型'] || processes.value.find((p: any) => p.is_active !== false)?.id
  let n = 0
  for (let i = 0; i < DEFAULT_CATEGORIES.length; i++) {
    const name = DEFAULT_CATEGORIES[i]
    if (existing.has(name)) continue
    const want = DEFAULT_CATEGORY_CONSUME[name]
    const suggestSize = DEFAULT_SUGGEST_SIZE_CATEGORIES.has(name)
    await http.post('/material-categories', {
      name,
      sort_order: i,
      is_active: true,
      default_consume_process_id: (want && processByName[want]) || fallbackPid || null,
      suggest_usage_by_size: suggestSize,
      default_size_usage_table_id: null,
    })
    n++
  }
  if (n) {
    // 新类补完后再挂一次默认码表/消耗工序
    await http.post('/material-size-usage-tables/seed-defaults')
  }
  const consumeN = Number(seedRes?.data?.consume_process_updated || 0)
  const split = seedRes?.data?.legacy_split || {}
  const splitN = Number(split.renamed || 0) + Number(split.created || 0)
  const parts: string[] = []
  if (splitN) parts.push(`拆分旧分类 ${splitN} 项`)
  if (n) parts.push(`导入 ${n} 个分类`)
  if (consumeN) parts.push(`补默认消耗工序 ${consumeN} 个`)
  ElMessage.success(parts.length ? parts.join('，') : '常用分类已存在（默认码表/消耗工序已同步）')
  await load()
}

function openUnit() {
  Object.assign(unitForm, { id: null, name: '', sort_order: units.value.length, is_active: true })
  unitVisible.value = true
}
function editUnit(row: any) {
  Object.assign(unitForm, { ...row })
  unitVisible.value = true
}
async function saveUnit() {
  if (!unitForm.name.trim()) {
    ElMessage.warning('请填写单位名称')
    return
  }
  const payload = {
    name: unitForm.name.trim(),
    sort_order: unitForm.sort_order,
    is_active: unitForm.is_active,
  }
  if (unitForm.id) await http.patch(`/pricing-units/${unitForm.id}`, payload)
  else await http.post('/pricing-units', payload)
  ElMessage.success('已保存')
  unitVisible.value = false
  await load()
}
async function toggleUnit(row: any) {
  await http.patch(`/pricing-units/${row.id}`, { is_active: !row.is_active })
  await load()
}
async function seedUnits() {
  const existing = new Set(units.value.map((x) => x.name))
  let n = 0
  for (let i = 0; i < DEFAULT_UNITS.length; i++) {
    const name = DEFAULT_UNITS[i]
    if (existing.has(name)) continue
    await http.post('/pricing-units', { name, sort_order: i, is_active: true })
    n++
  }
  ElMessage.success(n ? `已导入 ${n} 个单位` : '常用单位已存在')
  await load()
}

function openPosition() {
  Object.assign(positionForm, {
    id: null,
    name: '',
    sort_order: positions.value.length,
    is_active: true,
  })
  positionVisible.value = true
}
function editPosition(row: any) {
  Object.assign(positionForm, { ...row })
  positionVisible.value = true
}
async function savePosition() {
  if (!positionForm.name.trim()) {
    ElMessage.warning('请填写职位名称')
    return
  }
  const payload = {
    name: positionForm.name.trim(),
    sort_order: positionForm.sort_order,
    is_active: positionForm.is_active,
  }
  if (positionForm.id) await http.patch(`/positions/${positionForm.id}`, payload)
  else await http.post('/positions', payload)
  ElMessage.success('已保存')
  positionVisible.value = false
  await load()
}
async function togglePosition(row: any) {
  await http.patch(`/positions/${row.id}`, { is_active: !row.is_active })
  await load()
}
async function seedPositions() {
  const existing = new Set(positions.value.map((x) => x.name))
  let n = 0
  for (let i = 0; i < DEFAULT_POSITIONS.length; i++) {
    const name = DEFAULT_POSITIONS[i]
    if (existing.has(name)) continue
    await http.post('/positions', { name, sort_order: i, is_active: true })
    n++
  }
  ElMessage.success(n ? `已导入 ${n} 个职位` : '常用职位已存在')
  await load()
}

function openProcess() {
  Object.assign(processForm, {
    id: null,
    name: '',
    type: 'personal',
    per_worker_capacity: null,
    standard_workers: 1,
    sort_order: processes.value.length,
    is_active: true,
    segment_id: null,
  })
  processVisible.value = true
}
function editProcess(row: any) {
  Object.assign(processForm, {
    id: row.id,
    name: row.name,
    type: row.type === 'group' ? 'group' : 'personal',
    per_worker_capacity: row.per_worker_capacity ?? null,
    standard_workers: row.standard_workers ?? 1,
    sort_order: row.sort_order,
    is_active: row.is_active !== false,
    segment_id: row.segment_id ?? null,
  })
  processVisible.value = true
}
async function saveProcess() {
  if (!String(processForm.name || '').trim()) {
    ElMessage.warning('请填写工序名称')
    return
  }
  const capacityPayload = {
    per_worker_capacity:
      processForm.per_worker_capacity != null && Number(processForm.per_worker_capacity) > 0
        ? Number(processForm.per_worker_capacity)
        : null,
    standard_workers: Math.max(1, Number(processForm.standard_workers || 1)),
  }
  const segmentPayload = { segment_id: processForm.segment_id ?? null }
  if (processForm.id) {
    await http.patch(`/processes/${processForm.id}`, {
      name: processForm.name.trim(),
      type: processForm.type,
      sort_order: processForm.sort_order,
      is_active: processForm.is_active,
      ...capacityPayload,
      ...segmentPayload,
    })
  } else {
    await http.post('/processes', {
      name: processForm.name.trim(),
      code: genProcessCode(),
      default_price: 0,
      sort_order: processForm.sort_order,
      type: processForm.type,
      ...capacityPayload,
      ...segmentPayload,
    })
  }
  ElMessage.success('已保存')
  processVisible.value = false
  await load()
}
async function toggleProcess(row: any) {
  await http.patch(`/processes/${row.id}`, { is_active: !row.is_active })
  await load()
}
async function seedProcesses() {
  const existing = new Set(processes.value.map((x) => x.name))
  let n = 0
  for (let i = 0; i < DEFAULT_PROCESSES.length; i++) {
    const item = DEFAULT_PROCESSES[i]
    if (existing.has(item.name)) continue
    await http.post('/processes', {
      name: item.name,
      code: `P${Date.now().toString(36).toUpperCase()}${i}`,
      default_price: 0,
      sort_order: i,
      type: item.type,
    })
    n++
  }
  ElMessage.success(n ? `已导入 ${n} 个工序` : '常用工序已存在')
  await load()
}

function openOtherCost() {
  Object.assign(otherCostForm, {
    id: null,
    name: '',
    sort_order: otherCostItems.value.length,
    is_active: true,
  })
  otherCostVisible.value = true
}
function editOtherCost(row: any) {
  Object.assign(otherCostForm, { ...row })
  otherCostVisible.value = true
}
async function saveOtherCost() {
  if (!String(otherCostForm.name || '').trim()) {
    ElMessage.warning('请填写项目名称')
    return
  }
  const payload = {
    name: otherCostForm.name.trim(),
    sort_order: otherCostForm.sort_order,
    is_active: otherCostForm.is_active,
  }
  if (otherCostForm.id) await http.patch(`/other-cost-items/${otherCostForm.id}`, payload)
  else await http.post('/other-cost-items', payload)
  ElMessage.success('已保存')
  otherCostVisible.value = false
  await load()
}
async function toggleOtherCost(row: any) {
  await http.patch(`/other-cost-items/${row.id}`, { is_active: !row.is_active })
  await load()
}
async function seedOtherCosts() {
  const existing = new Set(otherCostItems.value.map((x) => x.name))
  let n = 0
  for (let i = 0; i < DEFAULT_OTHER_COSTS.length; i++) {
    const name = DEFAULT_OTHER_COSTS[i]
    if (existing.has(name)) continue
    await http.post('/other-cost-items', { name, sort_order: i, is_active: true })
    n++
  }
  ElMessage.success(n ? `已导入 ${n} 个项目` : '常用项目已存在')
  await load()
}

function openPart() {
  Object.assign(partForm, {
    id: null,
    code: '',
    name: '',
    source: '裁断',
    is_active: true,
  })
  partVisible.value = true
}
function editPart(row: any) {
  Object.assign(partForm, {
    id: row.id,
    code: row.code,
    name: row.name,
    source: row.source || '裁断',
    is_active: row.is_active !== false,
  })
  partVisible.value = true
}
async function savePart() {
  if (!String(partForm.code || '').trim()) {
    ElMessage.warning('请填写部件编码')
    return
  }
  if (!String(partForm.name || '').trim()) {
    ElMessage.warning('请填写部件名称')
    return
  }
  const payload = {
    code: String(partForm.code).trim().toUpperCase(),
    name: String(partForm.name).trim(),
    source: partForm.source || '裁断',
    is_active: partForm.is_active !== false,
  }
  if (partForm.id) await http.patch(`/part-definitions/${partForm.id}`, payload)
  else await http.post('/part-definitions', payload)
  ElMessage.success('已保存')
  partVisible.value = false
  await load()
}
async function togglePart(row: any) {
  await http.patch(`/part-definitions/${row.id}`, { is_active: !row.is_active })
  await load()
}
async function seedParts() {
  const existing = new Set(parts.value.map((x) => String(x.code || '').toUpperCase()))
  let n = 0
  for (const p of DEFAULT_PARTS) {
    if (existing.has(p.code)) continue
    await http.post('/part-definitions', {
      code: p.code,
      name: p.name,
      source: p.source,
      is_active: true,
    })
    n++
  }
  ElMessage.success(n ? `已导入 ${n} 个部件` : '常用部件已存在')
  await load()
}

onMounted(() => {
  const q = String(route.query.tab || '')
  if (MASTER_TABS.has(q)) tab.value = q
  void load()
})
</script>
