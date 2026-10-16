<template>
  <div :class="{ 'masters-readonly': !auth.hasPermission('btn.masters.write') }">
  <div class="admin-card">
    <div ref="tableHostRef">
    <el-tabs v-model="tab" class="masters-tabs">
      <el-tab-pane label="颜色" name="colors">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openColor">新增颜色</el-button>
          <span class="muted master-drag-hint">按住 ⋮⋮ 拖动排序</span>
        </div>
        <el-table
          ref="colorsTableRef"
          :data="colors"
          row-key="id"
          stripe
          border
          style="width: 100%"
          :max-height="tableMaxHeight"
          :row-class-name="(p) => masterRowClass('colors', p)"
          @dragover="onMasterDragOver($event, 'colors')"
          @drop="onMasterDrop($event, 'colors')"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column column-key="drag" label="" width="44" align="center" :resizable="false">
            <template #default="{ $index }">
              <span
                class="master-drag-handle"
                draggable="true"
                title="拖动排序"
                @dragstart="onMasterDragStart($event, 'colors', $index)"
                @dragover="onMasterDragOver($event, 'colors', $index)"
                @drop="onMasterDrop($event, 'colors', $index)"
                @dragend="onMasterDragEnd"
              >⋮⋮</span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" :width="colWidth('name', 200)" show-overflow-tooltip resizable />
          <el-table-column column-key="actions" label="操作" width="90" fixed="right" :resizable="false">
            <template #default="{ row }">
              <el-button link type="primary" @click="editColor(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="尺码" name="sizes">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openSize">新增尺码</el-button>
          <span class="muted master-drag-hint">按住 ⋮⋮ 拖动排序</span>
        </div>
        <el-table
          ref="sizesTableRef"
          :data="sizes"
          row-key="id"
          stripe
          border
          style="width: 100%"
          :max-height="tableMaxHeight"
          :row-class-name="(p) => masterRowClass('sizes', p)"
          @dragover="onMasterDragOver($event, 'sizes')"
          @drop="onMasterDrop($event, 'sizes')"
          @header-dragend="onHeaderDragend1"
        >
          <el-table-column column-key="drag" label="" width="44" align="center" :resizable="false">
            <template #default="{ $index }">
              <span
                class="master-drag-handle"
                draggable="true"
                title="拖动排序"
                @dragstart="onMasterDragStart($event, 'sizes', $index)"
                @dragover="onMasterDragOver($event, 'sizes', $index)"
                @drop="onMasterDrop($event, 'sizes', $index)"
                @dragend="onMasterDragEnd"
              >⋮⋮</span>
            </template>
          </el-table-column>
          <el-table-column prop="size_value" label="尺码" :width="colWidth1('size_value', 160)" show-overflow-tooltip resizable />
          <el-table-column column-key="actions" label="操作" width="90" fixed="right" :resizable="false">
            <template #default="{ row }">
              <el-button link type="primary" @click="editSize(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="物料分类" name="categories">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openCategory">新增分类</el-button>
          <el-button @click="seedCategories">导入常用分类</el-button>
          <span class="muted master-drag-hint">按住 ⋮⋮ 拖动排序</span>
        </div>
        <el-table
          ref="categoriesTableRef"
          :data="categories"
          row-key="id"
          stripe
          border
          style="width: 100%"
          :max-height="tableMaxHeight"
          :row-class-name="(p) => masterRowClass('categories', p)"
          @dragover="onMasterDragOver($event, 'categories')"
          @drop="onMasterDrop($event, 'categories')"
          @header-dragend="onHeaderDragend2"
        >
          <el-table-column column-key="drag" label="" width="44" align="center" :resizable="false">
            <template #default="{ $index }">
              <span
                class="master-drag-handle"
                draggable="true"
                title="拖动排序"
                @dragstart="onMasterDragStart($event, 'categories', $index)"
                @dragover="onMasterDragOver($event, 'categories', $index)"
                @drop="onMasterDrop($event, 'categories', $index)"
                @dragend="onMasterDragEnd"
              >⋮⋮</span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" :width="colWidth2('name', 140)" show-overflow-tooltip resizable />
          <el-table-column column-key="consume_segment" label="默认消耗工序段" :width="colWidth2('consume_segment', 140)" show-overflow-tooltip resizable>
            <template #default="{ row }">
              {{ row.default_consume_segment_name || '—' }}
            </template>
          </el-table-column>
          <el-table-column column-key="suggest_size" label="按码" :width="colWidth2('suggest_size', 80)" align="center" resizable>
            <template #default="{ row }">
              <el-tag :type="row.suggest_usage_by_size ? 'success' : 'info'" size="small">
                {{ row.suggest_usage_by_size ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column column-key="is_auxiliary" label="辅料" :width="colWidth2('is_auxiliary', 80)" align="center" resizable>
            <template #default="{ row }">
              <el-tag :type="row.is_auxiliary ? 'success' : 'info'" size="small">
                {{ row.is_auxiliary ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" width="140" fixed="right" :resizable="false">
            <template #default="{ row }">
              <el-button link type="primary" @click="editCategory(row)">编辑</el-button>
              <el-button
                v-if="!categoryRowLocked(row)"
                link
                type="danger"
                @click="deleteCategory(row)"
              >
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="计价单位" name="units">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openUnit">新增单位</el-button>
          <el-button @click="seedUnits">导入常用单位</el-button>
          <span class="muted master-drag-hint">按住 ⋮⋮ 拖动排序</span>
        </div>
        <el-table
          ref="unitsTableRef"
          :data="units"
          row-key="id"
          stripe
          border
          style="width: 100%"
          :max-height="tableMaxHeight"
          :row-class-name="(p) => masterRowClass('units', p)"
          @dragover="onMasterDragOver($event, 'units')"
          @drop="onMasterDrop($event, 'units')"
          @header-dragend="onHeaderDragend3"
        >
          <el-table-column column-key="drag" label="" width="44" align="center" :resizable="false">
            <template #default="{ $index }">
              <span
                class="master-drag-handle"
                draggable="true"
                title="拖动排序"
                @dragstart="onMasterDragStart($event, 'units', $index)"
                @dragover="onMasterDragOver($event, 'units', $index)"
                @drop="onMasterDrop($event, 'units', $index)"
                @dragend="onMasterDragEnd"
              >⋮⋮</span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" :width="colWidth3('name', 200)" show-overflow-tooltip resizable />
          <el-table-column column-key="actions" label="操作" width="90" fixed="right" :resizable="false">
            <template #default="{ row }">
              <el-button link type="primary" @click="editUnit(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="工序段管理" name="segments">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openSegment">新增工序段</el-button>
          <span class="muted" style="margin-left: 8px">段 = 截断/针车/成型/包装/铲皮；工序归属段（D14）</span>
          <span class="muted master-drag-hint">按住 ⋮⋮ 拖动排序</span>
        </div>
        <el-table
          ref="segmentsTableRef"
          :data="segments"
          row-key="id"
          stripe
          border
          style="width: 100%"
          :max-height="tableMaxHeight"
          :row-class-name="(p) => masterRowClass('segments', p)"
          @dragover="onMasterDragOver($event, 'segments')"
          @drop="onMasterDrop($event, 'segments')"
          @header-dragend="onHeaderDragendSegments"
        >
          <el-table-column column-key="drag" label="" width="44" align="center" :resizable="false">
            <template #default="{ $index }">
              <span
                class="master-drag-handle"
                draggable="true"
                title="拖动排序"
                @dragstart="onMasterDragStart($event, 'segments', $index)"
                @dragover="onMasterDragOver($event, 'segments', $index)"
                @drop="onMasterDrop($event, 'segments', $index)"
                @dragend="onMasterDragEnd"
              >⋮⋮</span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" :width="colWidthSegments('name', 160)" show-overflow-tooltip resizable />
          <el-table-column column-key="actions" label="操作" width="140" fixed="right" :resizable="false">
            <template #default="{ row }">
              <el-button link type="primary" @click="editSegment(row)">编辑</el-button>
              <el-button link type="danger" @click="deleteSegment(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="工序" name="processes">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openProcess">新增工序</el-button>
          <span class="muted master-drag-hint">按住 ⋮⋮ 拖动排序</span>
        </div>
        <el-table
          ref="processesTableRef"
          :data="processes"
          row-key="id"
          border
          style="width: 100%"
          :max-height="tableMaxHeight"
          :span-method="processSpanMethod"
          :row-class-name="(p) => masterRowClass('processes', p)"
          @dragover="onMasterDragOver($event, 'processes')"
          @drop="onMasterDrop($event, 'processes')"
          @header-dragend="onHeaderDragend5"
        >
          <el-table-column column-key="drag" label="" width="44" align="center" :resizable="false">
            <template #default="{ $index }">
              <span
                class="master-drag-handle"
                draggable="true"
                title="拖动排序"
                @dragstart="onMasterDragStart($event, 'processes', $index)"
                @dragover="onMasterDragOver($event, 'processes', $index)"
                @drop="onMasterDrop($event, 'processes', $index)"
                @dragend="onMasterDragEnd"
              >⋮⋮</span>
            </template>
          </el-table-column>
          <el-table-column column-key="segment" label="工序段" :width="colWidth5('segment', 110)" align="center" resizable>
            <template #default="{ row }">
              <span v-if="row.segment_name">{{ row.segment_name }}</span>
              <span v-else class="muted">未分段</span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="工序名称" :width="colWidth5('name', 120)" show-overflow-tooltip resizable />
          <el-table-column column-key="worker_count" label="人数统计" :width="colWidth5('worker_count', 88)" align="center" resizable>
            <template #default="{ row }">
              <span>{{ Number(row.worker_count) || 0 }}</span>
            </template>
          </el-table-column>
          <el-table-column column-key="worker_names" label="人员名称" :width="colWidth5('worker_names', 180)" show-overflow-tooltip resizable>
            <template #default="{ row }">
              <span v-if="(row.worker_names || []).length">{{ row.worker_names.join('、') }}</span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" width="90" fixed="right" :resizable="false">
            <template #default="{ row }">
              <el-button link type="primary" @click="editProcess(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="其它成本" name="otherCosts">
        <div class="admin-toolbar">
          <el-button type="primary" @click="openOtherCost">新增项目</el-button>
          <el-button @click="seedOtherCosts">导入常用项目</el-button>
          <span class="muted master-drag-hint">按住 ⋮⋮ 拖动排序</span>
        </div>
        <el-table
          ref="otherCostsTableRef"
          :data="otherCostItems"
          row-key="id"
          stripe
          border
          style="width: 100%"
          :max-height="tableMaxHeight"
          :row-class-name="(p) => masterRowClass('otherCosts', p)"
          @dragover="onMasterDragOver($event, 'otherCosts')"
          @drop="onMasterDrop($event, 'otherCosts')"
          @header-dragend="onHeaderDragend6"
        >
          <el-table-column column-key="drag" label="" width="44" align="center" :resizable="false">
            <template #default="{ $index }">
              <span
                class="master-drag-handle"
                draggable="true"
                title="拖动排序"
                @dragstart="onMasterDragStart($event, 'otherCosts', $index)"
                @dragover="onMasterDragOver($event, 'otherCosts', $index)"
                @drop="onMasterDrop($event, 'otherCosts', $index)"
                @dragend="onMasterDragEnd"
              >⋮⋮</span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" :width="colWidth6('name', 200)" show-overflow-tooltip resizable />
          <el-table-column column-key="actions" label="操作" width="90" fixed="right" :resizable="false">
            <template #default="{ row }">
              <el-button link type="primary" @click="editOtherCost(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
    </div>

    <el-dialog v-model="basketVisible" :title="basketForm.id ? '编辑框码' : '新增框码'" width="460px">
      <el-form label-width="90px">
        <el-form-item label="框号"><el-input v-model="basketForm.basket_code" :disabled="Boolean(basketForm.id)" placeholder="如 K001" /></el-form-item>
        <el-form-item label="位置"><el-input v-model="basketForm.location" placeholder="如 裁断区" /></el-form-item>
        <el-form-item v-if="basketForm.id && !basketForm.current_journey_id" label="状态">
          <el-select v-model="basketForm.status" style="width: 100%">
            <el-option label="空闲" value="idle" />
            <el-option label="维修" value="maintenance" />
            <el-option label="丢失" value="lost" />
            <el-option label="停用" value="disabled" />
          </el-select>
        </el-form-item>
        <el-alert v-if="basketForm.current_journey_id" type="info" :closable="false" title="该框正在流转，只能修改位置，状态由扫码业务自动更新。" />
      </el-form>
      <template #footer>
        <el-button @click="basketVisible = false">取消</el-button>
        <el-button type="primary" @click="saveBasket">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="basketQrVisible" :title="`框码 ${basketQrRow?.basket_code || ''}`" width="380px" @closed="clearBasketQr">
      <div style="text-align: center">
        <img v-if="basketQrUrl" :src="basketQrUrl" alt="框码二维码" style="width: 240px; height: 240px" />
        <p class="muted">此二维码永久对应框号，可重复打印和使用。</p>
      </div>
      <template #footer><el-button type="primary" @click="downloadBasketQr(basketQrRow)">下载二维码</el-button></template>
    </el-dialog>

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
      </el-form>
      <template #footer>
        <el-button @click="colorVisible = false">取消</el-button>
        <el-button type="primary" @click="saveColor">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="sizeVisible" :title="sizeForm.id ? '编辑尺码' : '新增尺码'" width="420px">
      <el-form label-width="80px">
        <el-form-item label="尺码"><el-input v-model="sizeForm.size_value" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="sizeVisible = false">取消</el-button>
        <el-button type="primary" @click="saveSize">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="categoryVisible" :title="categoryForm.id ? '编辑分类' : '新增分类'" width="420px">
      <el-form label-width="110px">
        <el-form-item label="名称">
          <el-input
            v-model="categoryForm.name"
            placeholder="如：皮料"
            :disabled="categoryNameLocked"
          />
          <p v-if="categoryNameLocked" class="muted" style="margin: 4px 0 0; font-size: 12px">
            {{
              categoryLastLocked
                ? '楦头为系统分类，不可修改；采购到货入模具仓（生产部）'
                : '系统分类，不可修改、不可删除'
            }}
          </p>
        </el-form-item>
        <el-form-item label="默认消耗工序段">
          <el-select
            v-model="categoryForm.default_consume_segment_id"
            clearable
            filterable
            :disabled="categoryNameLocked"
            placeholder="空=未标注（算首段）"
            style="width: 100%"
          >
            <el-option
              v-for="seg in segments.filter((x: any) => x.is_active !== false)"
              :key="seg.id"
              :label="seg.name"
              :value="seg.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="按码">
          <el-switch v-model="categoryForm.suggest_usage_by_size" :disabled="categorySuggestLocked" />
          <span class="muted" style="margin-left: 8px; font-size: 12px">
            {{ categorySuggestLocked ? '系统分类固定按码' : '产品开发物料明细直接跟分类' }}
          </span>
        </el-form-item>
        <el-form-item label="是否辅料">
          <el-switch v-model="categoryForm.is_auxiliary" :disabled="categoryNameLocked" />
          <span class="muted" style="margin-left: 8px; font-size: 12px">
            打开后，仓库领辅料只列出该分类
          </span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="categoryVisible = false">取消</el-button>
        <el-button type="primary" @click="saveCategory">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="unitVisible" :title="unitForm.id ? '编辑单位' : '新增单位'" width="420px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="unitForm.name" placeholder="如：双" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="unitVisible = false">取消</el-button>
        <el-button type="primary" @click="saveUnit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="positionVisible" :title="positionForm.id ? '编辑工种' : '新增工种'" width="420px">
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
      </el-form>
      <template #footer>
        <el-button @click="segmentVisible = false">取消</el-button>
        <el-button type="primary" @click="saveSegment">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="processVisible" :title="processForm.id ? '编辑工序' : '新增工序'" width="480px">
      <el-form label-width="90px">
        <el-form-item label="工序名称"><el-input v-model="processForm.name" placeholder="如：裁断" /></el-form-item>
        <el-form-item label="所属工序段">
          <el-select v-model="processForm.segment_id" clearable placeholder="未分段" style="width: 100%">
            <el-option v-for="seg in segments" :key="seg.id" :label="seg.name" :value="seg.id" />
          </el-select>
        </el-form-item>
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
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const colorsTableRef = ref()
const sizesTableRef = ref()
const categoriesTableRef = ref()
const unitsTableRef = ref()
const segmentsTableRef = ref()
const processesTableRef = ref()
const otherCostsTableRef = ref()
const { colWidth, onHeaderDragend } = useTableColWidths('masters-colors', colorsTableRef, {
  flexKey: 'name',
  flexDefaultMin: 160,
})
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths(
  'masters-sizes',
  sizesTableRef,
  { flexKey: 'size_value', flexDefaultMin: 120 },
)
const { colWidth: colWidth2, onHeaderDragend: onHeaderDragend2 } = useTableColWidths(
  'masters-categories',
  categoriesTableRef,
  { flexKey: 'name', flexDefaultMin: 120 },
)
const { colWidth: colWidth3, onHeaderDragend: onHeaderDragend3 } = useTableColWidths(
  'masters-units',
  unitsTableRef,
  { flexKey: 'name', flexDefaultMin: 160 },
)
const { colWidth: colWidth4, onHeaderDragend: onHeaderDragend4 } = useTableColWidths('masters-positions')
const { colWidth: colWidth5, onHeaderDragend: onHeaderDragend5 } = useTableColWidths(
  'masters-processes',
  processesTableRef,
  { flexKey: 'name', flexDefaultMin: 100 },
)
const { colWidth: colWidthSegments, onHeaderDragend: onHeaderDragendSegments } = useTableColWidths(
  'masters-segments',
  segmentsTableRef,
  { flexKey: 'name', flexDefaultMin: 120 },
)
const { colWidth: colWidth6, onHeaderDragend: onHeaderDragend6 } = useTableColWidths(
  'masters-other-costs',
  otherCostsTableRef,
  { flexKey: 'name', flexDefaultMin: 160 },
)
const { colWidth: colWidthSu, onHeaderDragend: onHeaderDragendSu } = useTableColWidths('masters-size-usage')
const { colWidth: colWidthParts, onHeaderDragend: onHeaderDragendParts } = useTableColWidths('masters-parts')
const { colWidth: colWidthBaskets, onHeaderDragend: onHeaderDragendBaskets } = useTableColWidths('masters-baskets')
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
  '楦头',
  '鞋跟',
  '其他辅料',
]
/** 按码 + 默认挂「大底通用」的分类（与后端 DEFAULT_SUGGEST_SIZE_USAGE_CATEGORIES 对齐） */
const DEFAULT_SUGGEST_SIZE_CATEGORIES = new Set(['大底', '中底', '鞋垫', '楦头', '鞋底', '鞋跟'])
const LOCKED_LAST_CATEGORY_NAMES = new Set(['楦头'])
const LOCKED_SYSTEM_CATEGORY_NAMES = new Set(['大底', '楦头', '中底', '鞋跟'])
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
  楦头: '成型',
  鞋底: '成型',
  鞋跟: '成型',
  其他辅料: '成型',
}
const DEFAULT_UNITS = ['双', '米', '码', '公斤', '个', '套', '卷', '打', '片']
const DEFAULT_POSITIONS = ['裁剪', '针车', '成型', '质检', '包装', '仓管', '杂工']
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
  'categories',
  'units',
  'segments',
  'processes',
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
const baskets = ref<any[]>([])
const otherCostItems = ref<any[]>([])

const colorVisible = ref(false)
const sizeVisible = ref(false)
const categoryVisible = ref(false)
const unitVisible = ref(false)
const positionVisible = ref(false)
const segmentVisible = ref(false)
const processVisible = ref(false)
const partVisible = ref(false)
const basketVisible = ref(false)
const basketQrVisible = ref(false)
const basketQrRow = ref<any>(null)
const basketQrUrl = ref('')
const otherCostVisible = ref(false)

const colorForm = reactive<any>({ id: null, name: '' })
const sizeForm = reactive<any>({ id: null, size_value: '' })
const categoryForm = reactive<any>({
  id: null,
  name: '',
  name_locked: false,
  default_consume_process_id: null as number | null,
  default_consume_segment_id: null as number | null,
  suggest_usage_by_size: false,
  default_size_usage_table_id: null as number | null,
  is_auxiliary: false,
})
const unitForm = reactive<any>({ id: null, name: '' })
const positionForm = reactive<any>({ id: null, name: '', sort_order: 0, is_active: true })
const segmentForm = reactive<any>({
  id: null,
  name: '',
})
const segments = ref<any[]>([])
const processForm = reactive<any>({
  id: null,
  name: '',
  segment_id: null as number | null,
})
const partForm = reactive<any>({
  id: null,
  code: '',
  name: '',
  source: '裁断',
  is_active: true,
})
const basketForm = reactive<any>({
  id: null,
  basket_code: '',
  location: '',
  status: 'idle',
  current_journey_id: null,
})
const otherCostForm = reactive<any>({ id: null, name: '' })

function genProcessCode() {
  return `P${Date.now().toString(36).toUpperCase()}`
}

type MasterDragKey =
  | 'colors'
  | 'sizes'
  | 'categories'
  | 'units'
  | 'segments'
  | 'processes'
  | 'otherCosts'

const masterLists: Record<MasterDragKey, typeof colors> = {
  colors,
  sizes,
  categories,
  units,
  segments,
  processes,
  otherCosts: otherCostItems,
}

const masterPatchPath: Record<MasterDragKey, (id: number) => string> = {
  colors: (id) => `/colors/${id}`,
  sizes: (id) => `/sizes/${id}`,
  categories: (id) => `/material-categories/${id}`,
  units: (id) => `/pricing-units/${id}`,
  segments: (id) => `/process-segments/${id}`,
  processes: (id) => `/processes/${id}`,
  otherCosts: (id) => `/other-cost-items/${id}`,
}

const masterDrag = ref<{ key: MasterDragKey; from: number } | null>(null)
const masterDropIndex = ref<number | null>(null)
let masterSortSaving = false

function onMasterDragStart(e: DragEvent, key: MasterDragKey, from: number) {
  masterDrag.value = { key, from }
  masterDropIndex.value = from
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(from))
  }
}

function masterRowIndexFromEvent(e: DragEvent): number | null {
  const tr = (e.target as HTMLElement | null)?.closest?.('tbody tr')
  if (!tr?.parentElement) return null
  const rows = Array.from(tr.parentElement.querySelectorAll(':scope > tr'))
  const idx = rows.indexOf(tr as HTMLTableRowElement)
  return idx >= 0 ? idx : null
}

function onMasterDragOver(e: DragEvent, key: MasterDragKey, to?: number) {
  if (!masterDrag.value || masterDrag.value.key !== key) return
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
  const idx = typeof to === 'number' ? to : masterRowIndexFromEvent(e)
  if (idx != null) masterDropIndex.value = idx
}

async function onMasterDrop(e: DragEvent, key: MasterDragKey, to?: number) {
  e.preventDefault()
  const state = masterDrag.value
  const dropTo = typeof to === 'number' ? to : masterRowIndexFromEvent(e)
  masterDrag.value = null
  masterDropIndex.value = null
  if (!state || state.key !== key || dropTo == null) return
  const from = state.from
  if (from === dropTo) return
  const list = masterLists[key]
  if (key === 'processes') {
    const fromKey = list.value[from]?.segment_id ?? null
    const toKey = list.value[dropTo]?.segment_id ?? null
    if (fromKey !== toKey) {
      ElMessage.warning('只能在同一工序段内调整顺序')
      return
    }
  }
  const next = [...list.value]
  const [item] = next.splice(from, 1)
  next.splice(dropTo, 0, item)
  list.value = next
  await persistMasterSort(key)
}

function onMasterDragEnd() {
  masterDrag.value = null
  masterDropIndex.value = null
}

function masterRowClass(key: MasterDragKey, { rowIndex }: { row?: any; rowIndex: number }) {
  if (!masterDrag.value || masterDrag.value.key !== key) return ''
  if (masterDrag.value.from === rowIndex) return 'master-dragging-row'
  if (masterDropIndex.value === rowIndex) return 'master-drop-target'
  return ''
}

async function persistMasterSort(key: MasterDragKey) {
  if (masterSortSaving) return
  masterSortSaving = true
  try {
    const list = masterLists[key].value
    const jobs: Promise<unknown>[] = []
    list.forEach((row: any, i: number) => {
      if (Number(row.sort_order) === i) return
      row.sort_order = i
      jobs.push(http.patch(masterPatchPath[key](row.id), { sort_order: i }))
    })
    if (jobs.length) await Promise.all(jobs)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '排序保存失败')
    await load()
  } finally {
    masterSortSaving = false
  }
}

function processSegmentRank(segmentId: number | null | undefined) {
  if (segmentId == null) return 1_000_000
  const idx = segments.value.findIndex((seg) => seg.id === segmentId)
  return idx >= 0 ? idx : 999_999
}

function sortProcessesBySegment(list: any[]) {
  return [...list].sort((a, b) => {
    const bySegment = processSegmentRank(a.segment_id) - processSegmentRank(b.segment_id)
    if (bySegment) return bySegment
    const byOrder = Number(a.sort_order ?? 0) - Number(b.sort_order ?? 0)
    if (byOrder) return byOrder
    return Number(a.id) - Number(b.id)
  })
}

function processSpanMethod({
  rowIndex,
  column,
}: {
  rowIndex: number
  column?: { columnKey?: string; property?: string }
}) {
  const key = String(column?.columnKey || column?.property || '')
  if (key !== 'segment') return { rowspan: 1, colspan: 1 }
  const data = processes.value
  const current = data[rowIndex]
  if (!current) return { rowspan: 1, colspan: 1 }
  const key = current.segment_id ?? null
  const prev = data[rowIndex - 1]
  if (prev && (prev.segment_id ?? null) === key) return { rowspan: 0, colspan: 0 }
  let span = 1
  for (let i = rowIndex + 1; i < data.length; i += 1) {
    if ((data[i].segment_id ?? null) !== key) break
    span += 1
  }
  return { rowspan: span, colspan: 1 }
}

async function load() {
  const [c, s, cats, us, ps, procs, ocs, sut, pts, segs, basketRes]: any[] = await Promise.all([
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
    http.get('/reusable-baskets'),
  ])
  colors.value = c.data.items
  sizes.value = s.data.items
  categories.value = cats.data.items
  units.value = us.data.items
  positions.value = ps.data.items
  otherCostItems.value = ocs.data?.items || []
  sizeUsageTables.value = sut.data?.items || []
  parts.value = pts.data?.items || []
  segments.value = segs.data?.items || []
  processes.value = sortProcessesBySegment(procs.data?.items || [])
  baskets.value = basketRes.data?.items || []

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

watch(tab, () => {
  void nextTick(() => {
    measureTableHeight()
    const tables: Record<string, { value?: { doLayout?: () => void } | null }> = {
      colors: colorsTableRef,
      sizes: sizesTableRef,
      categories: categoriesTableRef,
      units: unitsTableRef,
      segments: segmentsTableRef,
      processes: processesTableRef,
      otherCosts: otherCostsTableRef,
    }
    tables[tab.value]?.value?.doLayout?.()
  })
})

function openSegment() {
  Object.assign(segmentForm, {
    id: null,
    name: '',
  })
  segmentVisible.value = true
}
function editSegment(row: any) {
  Object.assign(segmentForm, {
    id: row.id,
    name: row.name,
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
      is_optional: false,
      is_active: true,
    })
  } else {
    await http.post('/process-segments', {
      name: segmentForm.name.trim(),
      sort_order: segments.value.length,
      is_optional: false,
      is_active: true,
    })
  }
  ElMessage.success('已保存')
  segmentVisible.value = false
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
  Object.assign(colorForm, { id: null, name: '' })
  colorVisible.value = true
}
function editColor(row: any) {
  Object.assign(colorForm, { id: row.id, name: row.name })
  colorVisible.value = true
}
async function saveColor() {
  if (!String(colorForm.name || '').trim()) {
    ElMessage.warning('请填写颜色名称')
    return
  }
  if (colorForm.id) await http.patch(`/colors/${colorForm.id}`, { name: colorForm.name.trim() })
  else await http.post('/colors', { name: colorForm.name.trim(), sort_order: colors.value.length })
  ElMessage.success('已保存')
  colorVisible.value = false
  await load()
}

function openSize() {
  Object.assign(sizeForm, { id: null, size_value: '' })
  sizeVisible.value = true
}
function editSize(row: any) {
  Object.assign(sizeForm, { id: row.id, size_value: row.size_value })
  sizeVisible.value = true
}
async function saveSize() {
  if (!String(sizeForm.size_value || '').trim()) {
    ElMessage.warning('请填写尺码')
    return
  }
  const payload = {
    size_value: sizeForm.size_value.trim(),
    is_active: true,
  }
  if (sizeForm.id) await http.patch(`/sizes/${sizeForm.id}`, payload)
  else await http.post('/sizes', { ...payload, sort_order: sizes.value.length })
  ElMessage.success('已保存')
  sizeVisible.value = false
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
  if (linked.length) bits.push(`按码：${linked.join('、')}`)
  if (consumeN) bits.push(`补消耗工序 ${consumeN}`)
  ElMessage.success(bits.join('；'))
  await load()
}

const categoryNameLocked = computed(
  () =>
    !!categoryForm.id &&
    (!!categoryForm.name_locked || LOCKED_SYSTEM_CATEGORY_NAMES.has(String(categoryForm.name || '').trim())),
)
const categoryLastLocked = computed(() =>
  LOCKED_LAST_CATEGORY_NAMES.has(String(categoryForm.name || '').trim()),
)
const categorySuggestLocked = computed(
  () =>
    categoryNameLocked.value ||
    LOCKED_SYSTEM_CATEGORY_NAMES.has(String(categoryForm.name || '').trim()),
)

function openCategory() {
  Object.assign(categoryForm, {
    id: null,
    name: '',
    name_locked: false,
    default_consume_process_id: null,
    default_consume_segment_id: null,
    suggest_usage_by_size: false,
    default_size_usage_table_id: null,
    is_auxiliary: false,
  })
  categoryVisible.value = true
}
function categoryRowLocked(row: any) {
  return (
    !!row?.name_locked ||
    LOCKED_SYSTEM_CATEGORY_NAMES.has(String(row?.name || '').trim())
  )
}

async function deleteCategory(row: any) {
  if (categoryRowLocked(row)) {
    ElMessage.warning('系统分类不可删除')
    return
  }
  try {
    await ElMessageBox.confirm(`删除分类「${row.name}」？`, '删除分类', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await http.delete(`/material-categories/${row.id}`)
  ElMessage.success('已删除')
  await load()
}

function editCategory(row: any) {
  const locked =
    !!row.name_locked ||
    !!row.suggest_usage_by_size_locked ||
    LOCKED_SYSTEM_CATEGORY_NAMES.has(String(row.name || '').trim())
  Object.assign(categoryForm, {
    id: row.id,
    name: row.name,
    name_locked: locked,
    default_consume_process_id: row.default_consume_process_id ?? null,
    default_consume_segment_id: row.default_consume_segment_id ?? null,
    suggest_usage_by_size: locked ? true : !!row.suggest_usage_by_size,
    default_size_usage_table_id: row.default_size_usage_table_id ?? null,
    is_auxiliary: !!row.is_auxiliary,
  })
  categoryVisible.value = true
}
async function saveCategory() {
  if (!categoryForm.name.trim()) {
    ElMessage.warning('请填写分类名称')
    return
  }
  const name = categoryForm.name.trim()
  const forceSuggest = LOCKED_SYSTEM_CATEGORY_NAMES.has(name)
  if (forceSuggest) categoryForm.suggest_usage_by_size = true
  const payload = {
    name,
    is_active: true,
    default_consume_process_id: categoryForm.default_consume_process_id || null,
    default_consume_segment_id: categoryForm.default_consume_segment_id || null,
    suggest_usage_by_size: forceSuggest ? true : !!categoryForm.suggest_usage_by_size,
    default_size_usage_table_id: (forceSuggest || categoryForm.suggest_usage_by_size)
      ? categoryForm.default_size_usage_table_id || null
      : null,
    is_auxiliary: !!categoryForm.is_auxiliary,
  }
  if (categoryForm.id) await http.patch(`/material-categories/${categoryForm.id}`, payload)
  else await http.post('/material-categories', { ...payload, sort_order: categories.value.length })
  ElMessage.success('已保存')
  categoryVisible.value = false
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
  Object.assign(unitForm, { id: null, name: '' })
  unitVisible.value = true
}
function editUnit(row: any) {
  Object.assign(unitForm, { id: row.id, name: row.name })
  unitVisible.value = true
}
async function saveUnit() {
  if (!unitForm.name.trim()) {
    ElMessage.warning('请填写单位名称')
    return
  }
  const payload = {
    name: unitForm.name.trim(),
    is_active: true,
  }
  if (unitForm.id) await http.patch(`/pricing-units/${unitForm.id}`, payload)
  else await http.post('/pricing-units', { ...payload, sort_order: units.value.length })
  ElMessage.success('已保存')
  unitVisible.value = false
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
    ElMessage.warning('请填写工种名称')
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
  ElMessage.success(n ? `已导入 ${n} 个工种` : '常用工种已存在')
  await load()
}

function openProcess() {
  Object.assign(processForm, {
    id: null,
    name: '',
    segment_id: null,
  })
  processVisible.value = true
}
function editProcess(row: any) {
  Object.assign(processForm, {
    id: row.id,
    name: row.name,
    segment_id: row.segment_id ?? null,
  })
  processVisible.value = true
}
async function saveProcess() {
  if (!String(processForm.name || '').trim()) {
    ElMessage.warning('请填写工序名称')
    return
  }
  const segmentPayload = { segment_id: processForm.segment_id ?? null }
  if (processForm.id) {
    await http.patch(`/processes/${processForm.id}`, {
      name: processForm.name.trim(),
      is_active: true,
      ...segmentPayload,
    })
  } else {
    await http.post('/processes', {
      name: processForm.name.trim(),
      code: genProcessCode(),
      default_price: 0,
      sort_order: processes.value.length,
      ...segmentPayload,
    })
  }
  ElMessage.success('已保存')
  processVisible.value = false
  await load()
}

const basketStatusLabel = (status: string) => ({
  idle: '空闲',
  bound: '装框中',
  in_transit: '待接收',
  on_line: '产线上',
  waiting_qc: '待质检',
  maintenance: '维修',
  lost: '丢失',
  disabled: '停用',
} as Record<string, string>)[status] || status || '—'

const basketStatusType = (status: string) => ({
  idle: 'success',
  maintenance: 'warning',
  lost: 'danger',
  disabled: 'info',
} as Record<string, string>)[status] || 'primary'

function openBasket() {
  Object.assign(basketForm, {
    id: null,
    basket_code: '',
    location: '',
    status: 'idle',
    current_journey_id: null,
  })
  basketVisible.value = true
}

function editBasket(row: any) {
  Object.assign(basketForm, {
    id: row.id,
    basket_code: row.basket_code,
    location: row.location || '',
    status: row.status,
    current_journey_id: row.current_journey_id,
  })
  basketVisible.value = true
}

async function saveBasket() {
  const code = String(basketForm.basket_code || '').trim().toUpperCase()
  if (!code) return ElMessage.warning('请填写框号')
  const payload: Record<string, unknown> = {
    location: String(basketForm.location || '').trim(),
  }
  if (basketForm.id) {
    if (!basketForm.current_journey_id) payload.status = basketForm.status
    await http.patch(`/reusable-baskets/${basketForm.id}`, payload)
  } else {
    await http.post('/reusable-baskets', { basket_code: code, ...payload })
  }
  ElMessage.success('框码已保存')
  basketVisible.value = false
  await load()
}

async function toggleBasket(row: any) {
  await http.patch(`/reusable-baskets/${row.id}`, { is_active: !row.is_active })
  ElMessage.success(row.is_active ? '框码已停用' : '框码已启用')
  await load()
}

async function fetchBasketQr(row: any) {
  const blob: any = await http.get(`/reusable-baskets/${row.id}/qr.png`, { responseType: 'blob' })
  return blob instanceof Blob ? blob : new Blob([blob], { type: 'image/png' })
}

async function previewBasketQr(row: any) {
  clearBasketQr()
  basketQrRow.value = row
  basketQrUrl.value = URL.createObjectURL(await fetchBasketQr(row))
  basketQrVisible.value = true
}

async function downloadBasketQr(row: any) {
  if (!row) return
  const url = URL.createObjectURL(await fetchBasketQr(row))
  const link = document.createElement('a')
  link.href = url
  link.download = `basket_${row.basket_code}.png`
  link.click()
  URL.revokeObjectURL(url)
}

function clearBasketQr() {
  if (basketQrUrl.value) URL.revokeObjectURL(basketQrUrl.value)
  basketQrUrl.value = ''
}

function openOtherCost() {
  Object.assign(otherCostForm, {
    id: null,
    name: '',
  })
  otherCostVisible.value = true
}
function editOtherCost(row: any) {
  Object.assign(otherCostForm, { id: row.id, name: row.name })
  otherCostVisible.value = true
}
async function saveOtherCost() {
  if (!String(otherCostForm.name || '').trim()) {
    ElMessage.warning('请填写项目名称')
    return
  }
  const payload = {
    name: otherCostForm.name.trim(),
    is_active: true,
  }
  if (otherCostForm.id) await http.patch(`/other-cost-items/${otherCostForm.id}`, payload)
  else await http.post('/other-cost-items', { ...payload, sort_order: otherCostItems.value.length })
  ElMessage.success('已保存')
  otherCostVisible.value = false
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

function pickMasterTab() {
  const q = String(route.query.tab || '')
  if (q === 'brands') return 'colors'
  return MASTER_TABS.has(q) ? q : 'colors'
}

function syncTabQuery(next: string) {
  if (route.path !== '/admin/masters') return
  if (String(route.query.tab || '') === next) return
  void router.replace({ path: '/admin/masters', query: { ...route.query, tab: next } })
}

watch(
  () => route.query.tab,
  () => {
    if (route.path !== '/admin/masters') return
    if (String(route.query.tab || '') === 'brands') {
      void router.replace({ path: '/admin/partners', query: { tab: 'brands' } })
      return
    }
    const next = pickMasterTab()
    if (next !== tab.value) tab.value = next
  },
)

onMounted(() => {
  if (String(route.query.tab || '') === 'brands') {
    void router.replace({ path: '/admin/partners', query: { tab: 'brands' } })
    return
  }
  tab.value = pickMasterTab()
  syncTabQuery(tab.value)
  void load()
})
</script>

<style scoped>
.masters-tabs :deep(.el-tabs__header) {
  display: none;
}
.masters-readonly :deep(.el-button) {
  display: none;
}
.master-drag-hint {
  margin-left: 10px;
  font-size: 12px;
}
.master-drag-handle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  color: #94a3b8;
  cursor: grab;
  user-select: none;
  letter-spacing: -2px;
  font-size: 14px;
  font-weight: 700;
}
.master-drag-handle:active {
  cursor: grabbing;
  color: var(--el-color-primary);
}
:deep(.master-dragging-row > td) {
  background: #eff6ff !important;
  opacity: 0.75;
}
:deep(.master-drop-target > td) {
  box-shadow: inset 0 -2px 0 var(--el-color-primary);
}
</style>
