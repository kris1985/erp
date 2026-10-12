<template>
  <div>
    <header v-if="!embedded" class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">物料仓</h1>
      </div>
    </header>
    <div :class="embedded ? 'inv-panel' : 'admin-card'">
      <div class="admin-toolbar">
        <el-input
          v-model="keyword"
          clearable
          placeholder="编号 / 名称 / 颜色 / 尺码 / 供应商"
          style="width: 280px"
          @clear="search"
          @keyup.enter="search"
        />
        <template v-if="selectMode === 'return'">
          <el-button
            v-permission="'btn.shared_materials.write'"
            type="primary"
            :disabled="!selectedRows.length"
            @click="openReturn"
          >
            确认退货{{ selectedRows.length ? ` · ${selectedRows.length}` : '' }}
          </el-button>
          <el-button link type="danger" @click="cancelSelect">取消</el-button>
        </template>
        <el-button
          v-if="!selectMode"
          v-permission="'btn.shared_materials.write'"
          type="primary"
          @click="openManualInbound"
        >
          手工入库
        </el-button>
        <el-button
          v-if="!picking && selectMode !== 'return'"
          v-permission="'btn.shared_materials.write'"
          @click="startSelect('return')"
        >
          退货
        </el-button>
        <el-button @click="load">刷新</el-button>
        <div class="spacer" />
        <template v-if="picking">
          <el-button
            v-permission="'btn.shared_materials.write'"
            type="primary"
            :disabled="!selectedRows.length"
            @click="confirmPickup"
          >
            确认{{ returningPool ? '退料' : '领料' }}{{ selectedRows.length ? ` · ${selectedRows.length}` : '' }}
          </el-button>
          <el-button link type="danger" @click="cancelSelect">取消</el-button>
        </template>
        <div v-else-if="selectMode !== 'return'" v-permission="'btn.shared_materials.write'" class="slip-groups">
          <el-button-group>
            <el-button type="primary" @click="pickupRef?.open('production')">生产领主料</el-button>
            <el-button title="生产退主料" @click="pickupRef?.open('production_return')">退料</el-button>
          </el-button-group>
          <el-button-group>
            <el-button type="primary" @click="startSelect('aux')">生产领辅料耗材</el-button>
            <el-button title="生产退辅料" @click="startSelect('aux_return')">退料</el-button>
          </el-button-group>
          <el-button-group>
            <el-button type="primary" @click="startSelect('dev')">开发部领料</el-button>
            <el-button title="开发部退料" @click="startSelect('dev_return')">退料</el-button>
          </el-button-group>
        </div>
        <el-button @click="pickupRef?.openHistory()">领退记录</el-button>
      </div>
      <div class="category-filter">
        <button
          type="button"
          class="cat-chip"
          :class="{ active: categoryFilter === null }"
          @click="setCategoryFilter(null)"
        >
          全部
        </button>
        <button
          v-for="c in activeCategories"
          :key="c.id"
          type="button"
          class="cat-chip"
          :class="{ active: categoryFilter === c.id }"
          @click="setCategoryFilter(c.id)"
        >
          {{ c.name }}
        </button>
      </div>
      <p v-if="selectMode" class="select-hint">
        {{
          selectMode === 'return'
            ? '勾选要退的物料，一次只能退同一个供应商。'
            : returningPool
              ? '勾选要退回仓库的物料，确认后填写数量。'
              : '勾选要领的物料，确认后填写数量。'
        }}
      </p>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          class="pool-table"
          :data="pagedRows"
          row-key="pool_row_key"
          stripe
          border
          v-loading="loading"
          :max-height="tableMaxHeight"
          @header-dragend="onHeaderDragend"
          @select="onReturnSelect"
          @select-all="onReturnSelectAll"
          @selection-change="onReturnSelectionChange"
        >
          <el-table-column
            v-if="selectMode"
            type="selection"
            width="42"
            align="center"
            :selectable="canSelectRow"
            :reserve-selection="true"
          />
          <el-table-column
            column-key="image"
            label="物料图片"
            :width="colWidth('image', 72)"
            align="center"
            header-align="center"
            class-name="mat-image-col"
            header-class-name="mat-image-col"
            resizable
          >
            <template #default="{ row }">
              <el-image
                v-if="row.image_url"
                :src="row.image_url"
                :preview-src-list="[row.image_url]"
                preview-teleported
                fit="contain"
                class="product-thumb"
              />
              <span v-else class="muted mat-image-empty"></span>
            </template>
          </el-table-column>
          <el-table-column
            prop="supplier_product_code"
            label="物料编号"
            :width="colWidth('supplier_product_code', 120)"
            align="center"
            header-align="center"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="supplier_product_name"
            label="名称"
            :width="colWidth('supplier_product_name', 140)"
            align="center"
            header-align="center"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="category_name"
            label="分类"
            :width="colWidth('category_name', 110)"
            align="center"
            header-align="center"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.category_name || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="color_name"
            label="颜色"
            :width="colWidth('color_name', 90)"
            align="center"
            header-align="center"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.color_name || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="size_value"
            label="尺码"
            :width="colWidth('size_value', 72)"
            align="center"
            header-align="center"
            resizable
          >
            <template #default="{ row }">{{ row.size_value || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="unit_price"
            label="单价"
            :width="colWidth('unit_price', 88)"
            align="center"
            header-align="center"
            resizable
          >
            <template #default="{ row }">{{ formatNum(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column
            prop="pricing_unit_name"
            label="计价单位"
            :width="colWidth('pricing_unit_name', 90)"
            align="center"
            header-align="center"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="partner_name"
            label="供应商"
            :width="colWidth('partner_name', 130)"
            align="center"
            header-align="center"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.partner_name || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="on_hand"
            :width="colWidth('on_hand', 100)"
            align="center"
            header-align="center"
            resizable
          >
            <template #header>
              <span class="col-h">
                现存量
                <el-tooltip
                  content="还没领出车间的实物，不含采购在途"
                  placement="top"
                >
                  <el-icon class="col-h-tip" @click.stop><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
            <template #default="{ row }">
              <strong>{{ formatNum(onHandQty(row)) }}</strong>
            </template>
          </el-table-column>
          <el-table-column
            column-key="actual_demand"
            :width="colWidth('actual_demand', 120)"
            align="center"
            header-align="center"
            resizable
          >
            <template #header>
              <span class="col-h">
                实际需求
                <el-tooltip
                  content="按生产单：生产需求 − 车间剩余，再汇总。车间剩余领料加、退料减，报工可改。"
                  placement="top"
                >
                  <el-icon class="col-h-tip" @click.stop><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
            <template #default="{ row }">
              <el-popover
                v-if="row.alert_orders?.length"
                placement="bottom"
                :width="1000"
                trigger="hover"
                :show-after="180"
              >
                <template #reference>
                  <span :class="Number(row.actual_demand_qty) > 0 ? 'qty-hover warn' : ''">{{ formatActual(row) }}</span>
                </template>
                <el-table :data="row.alert_orders" size="small" border max-height="280">
                  <el-table-column prop="header_no" label="生产单号" min-width="110" show-overflow-tooltip />
                  <el-table-column label="图片" width="56" align="center">
                    <template #default="{ row: order }">
                      <el-image
                        v-if="order.product_image_url"
                        :src="order.product_image_url"
                        fit="contain"
                        class="demand-order-img"
                      />
                      <span v-else class="muted">—</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="product_code" label="工厂型号" min-width="90" show-overflow-tooltip />
                  <el-table-column prop="color_name" label="颜色" width="72" show-overflow-tooltip />
                  <el-table-column prop="plan_qty" label="数量" width="64" align="right" />
                  <el-table-column label="报工" width="72" align="right">
                    <template #default="{ row: order }">
                      {{ order.reported_qty }}<template v-if="order.usage_by_size">*</template>
                    </template>
                  </el-table-column>
                  <el-table-column prop="qty_per_pair" label="每双用量" width="80" align="right" />
                  <el-table-column prop="required_qty" label="总用量" width="72" align="right" />
                  <el-table-column label="领料累计" width="80" align="right">
                    <template #default="{ row: order }">{{ formatNum(order.issued_qty) }}</template>
                  </el-table-column>
                  <el-table-column label="车间剩余" width="88" align="right">
                    <template #default="{ row: order }">{{ formatNum(order.workshop_qty) }}</template>
                  </el-table-column>
                  <el-table-column prop="demand_qty" label="生产需求" width="80" align="right" />
                </el-table>
                <p v-if="row.alert_orders.some((order: any) => order.usage_by_size)" class="demand-size-note">
                  * 报工未按码，这一列是该工序的总双数。分码的生产需求按该码用量全额计入；车间剩余按生产单，领料加、退料减，报工可改。
                </p>
              </el-popover>
              <span v-else :class="Number(row.actual_demand_qty) > 0 ? 'qty-hover warn' : ''">{{ formatActual(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column
            column-key="in_transit"
            :width="colWidth('in_transit', 88)"
            align="center"
            header-align="center"
            resizable
          >
            <template #header>
              <span class="col-h">
                在途
                <el-tooltip
                  content="采购已下单/在运/部分到货的未收量；不计入现存量"
                  placement="top"
                >
                  <el-icon class="col-h-tip" @click.stop><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
            <template #default="{ row }">
              <el-popover
                v-if="Number(row.in_transit_qty) > 0"
                placement="bottom"
                :width="620"
                trigger="hover"
                :show-after="180"
                popper-class="pool-detail-popper"
                @show="loadInTransit(row)"
              >
                <template #reference>
                  <span class="qty-hover warn">{{ formatNum(row.in_transit_qty) }}</span>
                </template>
                <div v-loading="detailLoadingKey === detailKey(row, 'tr')" class="pool-detail-panel">
                  <div class="pool-detail-title">在途采购明细</div>
                  <el-table
                    :data="inTransitCache[detailKey(row, 'tr')] || []"
                    size="small"
                    border
                    stripe
                    max-height="260"
                    empty-text="暂无在途"
                  >
                    <el-table-column prop="po_no" label="采购单号" min-width="110" show-overflow-tooltip />
                    <el-table-column prop="supplier_name" label="供应商" min-width="100" show-overflow-tooltip />
                    <el-table-column prop="status_label" label="状态" width="88" align="center" />
                    <el-table-column prop="qty" label="采购量" width="72" align="center">
                      <template #default="{ row: r }">{{ formatNum(r.qty) }}</template>
                    </el-table-column>
                    <el-table-column prop="received_qty" label="已收" width="64" align="center">
                      <template #default="{ row: r }">{{ formatNum(r.received_qty) }}</template>
                    </el-table-column>
                    <el-table-column prop="open_qty" label="在途" width="64" align="center">
                      <template #default="{ row: r }">{{ formatNum(r.open_qty) }}</template>
                    </el-table-column>
                    <el-table-column prop="expected_date" label="协商交货日期" width="120" align="center">
                      <template #default="{ row: r }">{{ r.expected_date || '—' }}</template>
                    </el-table-column>
                    <el-table-column prop="order_no" label="关联生产单" min-width="100" show-overflow-tooltip>
                      <template #default="{ row: r }">{{ r.header_no || r.order_no || '—' }}</template>
                    </el-table-column>
                  </el-table>
                </div>
              </el-popover>
              <span v-else>{{ formatNum(row.in_transit_qty) }}</span>
            </template>
          </el-table-column>
          <el-table-column
            column-key="alert_qty"
            label="预警"
            :width="colWidth('alert_qty', 88)"
            align="center"
            header-align="center"
            resizable
          >
            <template #default="{ row }">
              <span :class="alertClass(row)">{{ formatAlert(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column
            column-key="actions"
            label="操作"
            width="140"
            align="center"
            header-align="center"
            fixed="right"
            :resizable="false"
          >
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openLedger(row)">流水</el-button>
              <el-button v-permission="'btn.shared_materials.write'" link size="small" @click="openAdjust(row)">调整</el-button>
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
          :total="filteredTotal"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="onPageChange"
          @size-change="onPageSizeChange"
        />
      </div>
    </div>

    <el-drawer
      v-model="ledgerVisible"
      class="ledger-drawer"
      :title="ledgerTitle"
      size="1040px"
      destroy-on-close
    >
      <div class="ledger-drawer-body">
        <el-table
          ref="ledgerTableRef"
          v-loading="ledgerLoading"
          :data="pagedLedgers"
          stripe
          border
          size="small"
          empty-text="暂无出入记录"
          height="100%"
          @header-dragend="onHeaderDragend1"
        >
          <el-table-column column-key="time" label="时间" :width="colWidth1('time', 160)" resizable>
            <template #default="{ row }">
              {{ String(row.created_at || '').replace('T', ' ').slice(0, 19) || '—' }}
            </template>
          </el-table-column>
          <el-table-column column-key="type" label="类型" :width="colWidth1('type', 110)" resizable>
            <template #default="{ row }">
              <el-tag size="small" :type="ledgerTagType(row.ledger_type)" effect="plain">
                {{ row.ledger_type_label || row.ledger_type }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column column-key="order" label="生产单号" :width="colWidth1('order', 140)" show-overflow-tooltip resizable>
            <template #default="{ row }">{{ row.header_no || row.order_no || '—' }}</template>
          </el-table-column>
          <el-table-column column-key="po_no" label="采购单" :width="colWidth1('po_no', 140)" show-overflow-tooltip resizable>
            <template #default="{ row }">{{ row.po_no || '—' }}</template>
          </el-table-column>
          <el-table-column column-key="qty" label="数量" :width="colWidth1('qty', 90)" align="center" resizable>
            <template #default="{ row }">
              <span :class="Number(row.qty_delta) >= 0 ? 'in' : 'out'">
                {{ Number(row.qty_delta) >= 0 ? '+' : '' }}{{ formatNum(row.qty_delta) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column
            column-key="balance_after"
            label="余数"
            :width="colWidth1('balance_after', 88)"
            align="center"
            resizable
          >
            <template #default="{ row }">{{ formatNum(row.balance_after) }}</template>
          </el-table-column>
          <el-table-column
            column-key="picker_name"
            label="领/退料人"
            :width="colWidth1('picker_name', 110)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.picker_name || '—' }}</template>
          </el-table-column>
        </el-table>
        <div class="ledger-pagination">
          <el-pagination
            v-model:current-page="ledgerPage"
            v-model:page-size="ledgerPageSize"
            background
            small
            layout="total, sizes, prev, pager, next"
            :total="ledgers.length"
            :page-sizes="[20, 50, 100]"
            @size-change="onLedgerPageSizeChange"
          />
        </div>
      </div>
    </el-drawer>

    <el-dialog v-model="inboundVisible" title="手工入库" width="720px">
      <p class="select-hint">保存后计入物料仓，并同步到物料色卡和供应商。编号已存在时更新色卡并累加数量。</p>
      <el-form label-width="88px">
        <el-form-item label="物料图片">
          <div class="inbound-image">
            <el-image
              v-if="inboundForm.image_url"
              :src="inboundForm.image_url"
              fit="contain"
              class="inbound-thumb"
              :preview-src-list="[inboundForm.image_url]"
              preview-teleported
            />
            <span v-else class="inbound-thumb inbound-thumb-empty">{{ inboundUploading ? '上传中' : '未上传' }}</span>
            <div class="inbound-image-actions">
              <el-button :disabled="inboundUploading" @click="inboundFileRef?.click()">上传</el-button>
              <el-button :disabled="inboundUploading" @click="inboundCameraRef?.click()">拍照</el-button>
              <el-button v-if="inboundForm.image_url" link type="danger" @click="inboundForm.image_url = ''">清除</el-button>
            </div>
            <input
              ref="inboundFileRef"
              class="product-file-input"
              type="file"
              accept="image/jpeg,image/png,image/gif,image/webp"
              @change="onInboundImage"
            />
            <input
              ref="inboundCameraRef"
              class="product-file-input"
              type="file"
              accept="image/*"
              capture="environment"
              @change="onInboundImage"
            />
          </div>
        </el-form-item>
        <div class="inbound-grid">
          <el-form-item label="物料编号" required>
            <el-input v-model="inboundForm.product_code" maxlength="50" placeholder="手填编号" />
          </el-form-item>
          <el-form-item label="名称" required>
            <el-input v-model="inboundForm.name" maxlength="100" placeholder="物料名称" />
          </el-form-item>
          <el-form-item label="分类">
            <el-select v-model="inboundForm.category_id" clearable filterable placeholder="选择分类" style="width: 100%">
              <el-option v-for="c in activeCategories" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="颜色">
            <el-select v-model="inboundForm.color_id" clearable filterable placeholder="选择颜色" style="width: 100%">
              <el-option v-for="c in colors" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="尺码">
            <el-select v-model="inboundForm.size_id" clearable filterable placeholder="未按码留空" style="width: 100%">
              <el-option v-for="s in activeSizes" :key="s.id" :label="s.size_value" :value="s.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="单价">
            <el-input-number
              v-model="inboundForm.unit_price"
              :min="0"
              :precision="4"
              :step="0.1"
              controls-position="right"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item label="计价单位">
            <el-select
              v-model="inboundForm.pricing_unit_id"
              clearable
              filterable
              placeholder="选择单位"
              style="width: 100%"
            >
              <el-option v-for="u in activeUnits" :key="u.id" :label="u.name" :value="u.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="供应商" required>
            <el-autocomplete
              v-model="inboundForm.supplier_name"
              :fetch-suggestions="querySupplierSuggestions"
              clearable
              maxlength="100"
              placeholder="手填，已有名称会直接使用"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item label="数量" required>
            <el-input-number
              v-model="inboundForm.qty"
              :min="0"
              :precision="4"
              :step="1"
              controls-position="right"
              style="width: 100%"
            />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="inboundVisible = false">取消</el-button>
        <el-button
          v-permission="'btn.shared_materials.write'"
          type="primary"
          :loading="inboundSaving"
          @click="submitInbound"
        >
          确定入库
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="adjustVisible" title="调整物料仓" width="440px">
      <el-form label-width="100px">
        <el-form-item label="物料">
          <el-select
            v-model="form.supplier_product_id"
            filterable
            remote
            clearable
            placeholder="搜索物料"
            style="width: 100%"
            :remote-method="searchProducts"
            :loading="productLoading"
          >
            <el-option
              v-for="p in productOptions"
              :key="p.id"
              :label="`${p.product_code} · ${p.name || ''}`"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="尺码">
          <el-select
            v-model="form.size_id"
            clearable
            filterable
            placeholder="未按码留空"
            style="width: 100%"
          >
            <el-option v-for="s in sizes" :key="s.id" :label="s.size_value" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="增减数量">
          <el-input-number v-model="form.qty_delta" style="width: 100%" />
        </el-form-item>
        <el-form-item label="单价(入库)">
          <el-input-number v-model="form.unit_cost" :min="0" :step="0.01" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注" required>
          <el-input v-model="form.note" placeholder="盘盈/盘亏原因（必填）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="adjustVisible = false">取消</el-button>
        <el-button v-permission="'btn.shared_materials.write'" type="primary" @click="doAdjust">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="returnVisible" :title="returnTitle" width="860px">
      <el-table :data="returnLines" border size="small">
        <el-table-column prop="item_code" label="物料编号" min-width="110" show-overflow-tooltip />
        <el-table-column prop="item_name" label="名称" min-width="120" show-overflow-tooltip />
        <el-table-column prop="size_value" label="尺码" width="72" align="center">
          <template #default="{ row }">{{ row.size_value || '—' }}</template>
        </el-table-column>
        <el-table-column prop="returnable_qty" label="可退" width="80" align="right">
          <template #default="{ row }">{{ formatReturnQty(row.returnable_qty) }}</template>
        </el-table-column>
        <el-table-column label="本次数量" width="140" align="center">
          <template #default="{ row }">
            <el-input-number
              v-model="row.qty"
              :min="0"
              :max="Number(row.returnable_qty)"
              :precision="2"
              :step="1"
              controls-position="right"
              style="width: 120px"
            />
          </template>
        </el-table-column>
        <el-table-column label="单价" width="140" align="center">
          <template #default="{ row }">
            <el-input-number
              v-model="row.unit_price"
              :min="0"
              :precision="2"
              :step="0.01"
              controls-position="right"
              style="width: 120px"
            />
          </template>
        </el-table-column>
        <el-table-column label="金额" width="100" align="right">
          <template #default="{ row }">{{ formatReturnAmount(row) }}</template>
        </el-table-column>
      </el-table>
      <el-input v-model="returnNote" class="return-note" placeholder="备注（可选）" maxlength="255" />
      <template #footer>
        <el-button @click="returnVisible = false">取消</el-button>
        <el-button v-permission="'btn.shared_materials.write'" type="primary" :loading="returning" @click="submitReturn">
          确定
        </el-button>
      </template>
    </el-dialog>
    <WarehousePickupDialog ref="pickupRef" @posted="onPickupPosted" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { QuestionFilled } from '@element-plus/icons-vue'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import { prepareImageForUpload } from '@/utils/imageUpload'
import WarehousePickupDialog from '@/views/admin/WarehousePickupDialog.vue'

withDefaults(
  defineProps<{
    /** 嵌在「库存」页 Tab 内时隐藏独立页头/卡片壳 */
    embedded?: boolean
  }>(),
  { embedded: false },
)

const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, onHeaderDragend } = useTableColWidths('shared-materials-list', tableRef, {
  flexKey: 'supplier_product_name',
  flexDefaultMin: 140,
  fitToContainer: true,
})
const ledgerTableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths(
  'shared-materials-ledger',
  ledgerTableRef,
  { flexKey: 'po_no', flexDefaultMin: 120, fitToContainer: true },
)
const rows = ref<any[]>([])
const categories = ref<any[]>([])
const sizes = ref<any[]>([])
const colors = ref<any[]>([])
const units = ref<any[]>([])
const supplierNames = ref<string[]>([])
const loading = ref(false)
const keyword = ref('')
const categoryFilter = ref<number | null>(null)
const page = ref(1)
const pageSize = ref(20)
const adjustVisible = ref(false)
const inboundVisible = ref(false)
const inboundSaving = ref(false)
const inboundUploading = ref(false)
const inboundFileRef = ref<HTMLInputElement | null>(null)
const inboundCameraRef = ref<HTMLInputElement | null>(null)
const inboundForm = reactive({
  image_url: '',
  product_code: '',
  name: '',
  category_id: null as number | null,
  color_id: null as number | null,
  size_id: null as number | null,
  unit_price: undefined as number | undefined,
  pricing_unit_id: null as number | null,
  supplier_name: '',
  qty: undefined as number | undefined,
})
const selectMode = ref<'return' | 'dev' | 'aux' | 'dev_return' | 'aux_return' | null>(null)
const picking = computed(
  () =>
    selectMode.value === 'dev' ||
    selectMode.value === 'aux' ||
    selectMode.value === 'dev_return' ||
    selectMode.value === 'aux_return',
)
const returningPool = computed(
  () => selectMode.value === 'dev_return' || selectMode.value === 'aux_return',
)
const selectedRows = ref<any[]>([])
const returnVisible = ref(false)
const returnLines = ref<any[]>([])
const returnNote = ref('')
const returning = ref(false)
const returnTitle = ref('退货')
let fixingReturnSelection = false
const ledgerVisible = ref(false)
const ledgerLoading = ref(false)
const ledgers = ref<any[]>([])
const ledgerTitle = ref('出入流水')
const ledgerPage = ref(1)
const ledgerPageSize = ref(20)
const productOptions = ref<any[]>([])
const productLoading = ref(false)
const pickupRef = ref<InstanceType<typeof WarehousePickupDialog> | null>(null)
const occupancyCache = reactive<Record<string, any[]>>({})
const inTransitCache = reactive<Record<string, any[]>>({})
const detailLoadingKey = ref('')
const form = reactive({
  supplier_product_id: null as number | null,
  size_id: null as number | null,
  qty_delta: 0,
  unit_cost: undefined as number | undefined,
  note: '',
})

const activeCategories = computed(() => categories.value.filter((c) => c.is_active !== false))
const activeSizes = computed(() => sizes.value.filter((s) => s.is_active !== false))
const activeUnits = computed(() => units.value.filter((u) => u.is_active !== false))

function detailKey(row: any, kind: 'occ' | 'tr') {
  return `${kind}:${row.supplier_product_id}:${row.size_id ?? 'n'}`
}

async function loadOccupancy(row: any) {
  const key = detailKey(row, 'occ')
  if (occupancyCache[key]) return
  detailLoadingKey.value = key
  try {
    const res: any = await http.get('/shared-materials/occupancy', {
      params: {
        supplier_product_id: row.supplier_product_id,
        size_id: row.size_id ?? undefined,
      },
    })
    occupancyCache[key] = res.data?.items || []
  } catch {
    occupancyCache[key] = []
  } finally {
    if (detailLoadingKey.value === key) detailLoadingKey.value = ''
  }
}

async function loadInTransit(row: any) {
  const key = detailKey(row, 'tr')
  if (inTransitCache[key]) return
  detailLoadingKey.value = key
  try {
    const res: any = await http.get('/shared-materials/in-transit', {
      params: {
        supplier_product_id: row.supplier_product_id,
        size_id: row.size_id ?? undefined,
      },
    })
    inTransitCache[key] = res.data?.items || []
  } catch {
    inTransitCache[key] = []
  } finally {
    if (detailLoadingKey.value === key) detailLoadingKey.value = ''
  }
}

const filteredRows = computed(() => {
  let list = rows.value
  if (categoryFilter.value != null) {
    list = list.filter((r) => Number(r.category_id) === Number(categoryFilter.value))
  }
  const q = keyword.value.trim().toLowerCase()
  if (!q) return list
  return list.filter((r) => {
    const hay = [
      r.supplier_product_code,
      r.supplier_product_name,
      r.category_name,
      r.color_name,
      r.size_value,
      r.pricing_unit_name,
      r.partner_name,
    ]
      .map((x) => String(x || ''))
      .join(' ')
      .toLowerCase()
    return hay.includes(q)
  })
})

const filteredTotal = computed(() => filteredRows.value.length)

const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredRows.value.slice(start, start + pageSize.value)
})

const pagedLedgers = computed(() => {
  const start = (ledgerPage.value - 1) * ledgerPageSize.value
  return ledgers.value.slice(start, start + ledgerPageSize.value)
})

function onLedgerPageSizeChange() {
  ledgerPage.value = 1
}

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

function onHandQty(row: any) {
  if (row.on_hand_qty != null && row.on_hand_qty !== '') return row.on_hand_qty
  return Number(row.pool_qty ?? row.qty ?? 0) + Number(row.occupied_qty || 0)
}

function formatActual(row: any) {
  return formatNum(row.actual_demand_qty)
}

function formatWorkshop(row: any) {
  return formatNum(row.workshop_qty)
}

function formatAlert(row: any) {
  return formatNum(row.alert_qty)
}

function alertClass(row: any) {
  return Number(row.alert_qty) < 0 ? 'alert-short' : ''
}

function ledgerTagType(t: string) {
  if (
    t === 'unallocated_receive' ||
    t === 'receive_surplus' ||
    t === 'release_from_order' ||
    t === 'dev_return' ||
    t === 'aux_return' ||
    t === 'manual_receive'
  )
    return 'success'
  if (t === 'allocate_to_order' || t === 'issue_to_order' || t === 'purchase_return' || t === 'misc_issue' || t === 'dev_issue' || t === 'aux_issue') return 'warning'
  return 'info'
}

function canSelectRow(row: any) {
  if (returningPool.value) return true
  if (picking.value) return Number(row.pool_qty ?? row.qty) > 0
  return Number(row.returnable_qty) > 0
}

function startSelect(mode: 'return' | 'dev' | 'aux' | 'dev_return' | 'aux_return') {
  selectMode.value = mode
  selectedRows.value = []
  void nextTick(() => (tableRef.value as any)?.clearSelection?.())
}

function cancelSelect() {
  selectMode.value = null
  selectedRows.value = []
  void nextTick(() => (tableRef.value as any)?.clearSelection?.())
}

function confirmPickup() {
  if (!selectedRows.value.length) return
  if (selectMode.value === 'aux') pickupRef.value?.openAux(selectedRows.value)
  else if (selectMode.value === 'dev_return') void pickupRef.value?.openDevReturn(selectedRows.value)
  else if (selectMode.value === 'aux_return') void pickupRef.value?.openAuxReturn(selectedRows.value)
  else pickupRef.value?.openDev(selectedRows.value)
}

function onPickupPosted() {
  cancelSelect()
  void load()
}

function onReturnSelectionChange(selection: any[]) {
  if (fixingReturnSelection) return
  selectedRows.value = selection
}

function onReturnSelect(selection: any[], row: any) {
  if (fixingReturnSelection || selectMode.value !== 'return') return
  const supplierId = selection.find((item) => item !== row)?.partner_id
  if (supplierId != null && row.partner_id !== supplierId) {
    fixingReturnSelection = true
    ;(tableRef.value as any)?.toggleRowSelection(row, false)
    fixingReturnSelection = false
    selectedRows.value = selection.filter((item) => item !== row)
    ElMessage.warning('一次只能退同一个供应商')
  }
}

function onReturnSelectAll(selection: any[]) {
  if (selectMode.value !== 'return') return
  const supplierIds = [...new Set(selection.map((row) => row.partner_id))]
  if (supplierIds.length <= 1) return
  const keep = selection[0]?.partner_id
  fixingReturnSelection = true
  for (const row of selection) {
    if (row.partner_id !== keep) (tableRef.value as any)?.toggleRowSelection(row, false)
  }
  fixingReturnSelection = false
  selectedRows.value = selection.filter((row) => row.partner_id === keep)
  ElMessage.warning('一次只能退同一个供应商')
}

function formatReturnQty(value: any) {
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatReturnAmount(row: any) {
  const amount = -(Number(row.qty) || 0) * Number(row.unit_price || 0)
  return amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

async function openReturn() {
  if (!selectedRows.value.length) return
  const res: any = await http.post('/shared-materials/purchase-return-quote', {
    lines: selectedRows.value.map((row) => ({
      supplier_product_id: row.supplier_product_id,
      size_id: row.size_id ?? null,
    })),
  })
  const data = res.data || {}
  returnTitle.value = data.supplier_name ? `退货 · ${data.supplier_name}` : '退货'
  returnLines.value = (data.lines || []).map((line: any) => {
    const cap = Number(line.returnable_qty || 0)
    return {
      ...line,
      qty: Math.floor(cap * 100 + 1e-6) / 100,
      unit_price: Math.round(Number(line.unit_price || 0) * 100) / 100,
    }
  })
  returnNote.value = ''
  returnVisible.value = true
}

async function submitReturn() {
  if (
    returnLines.value.some(
      (line) => !line.qty || Number(line.qty) <= 0 || Number(line.qty) > Number(line.returnable_qty),
    )
  ) {
    ElMessage.warning('退货数量须大于 0，且不能超过可退数量')
    return
  }
  if (returnLines.value.some((line) => line.unit_price == null || Number(line.unit_price) < 0)) {
    ElMessage.warning('单价不能为负')
    return
  }
  returning.value = true
  try {
    await http.post('/shared-materials/purchase-returns', {
      note: returnNote.value.trim() || null,
      lines: returnLines.value.map((line) => ({
        supplier_product_id: line.supplier_product_id,
        size_id: line.size_id ?? null,
        qty: line.qty,
        unit_price: line.unit_price,
      })),
    })
    ElMessage.success('已退货')
    returnVisible.value = false
    cancelSelect()
    await load()
  } finally {
    returning.value = false
  }
}

function setCategoryFilter(id: number | null) {
  categoryFilter.value = id
  page.value = 1
  void nextTick(measureTableHeight)
}

function onPageChange() {
  void nextTick(measureTableHeight)
}

function onPageSizeChange() {
  page.value = 1
  void nextTick(measureTableHeight)
}

function search() {
  page.value = 1
  void nextTick(measureTableHeight)
}

async function loadCategories() {
  const res: any = await http.get('/material-categories')
  categories.value = res.data?.items || res.data || []
}

async function loadSizes() {
  const res: any = await http.get('/sizes')
  sizes.value = res.data?.items || res.data || []
}

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/shared-materials')
    rows.value = (res.data || []).map((row: any) => ({
      ...row,
      pool_row_key: `${row.supplier_product_id}:${row.size_id ?? ''}`,
    }))
    selectedRows.value = []
    ;(tableRef.value as any)?.clearSelection?.()
    for (const k of Object.keys(occupancyCache)) delete occupancyCache[k]
    for (const k of Object.keys(inTransitCache)) delete inTransitCache[k]
  } finally {
    loading.value = false
    const maxPage = Math.max(1, Math.ceil(filteredTotal.value / pageSize.value) || 1)
    if (page.value > maxPage) page.value = maxPage
    void nextTick(measureTableHeight)
  }
}

async function searchProducts(q: string) {
  productLoading.value = true
  try {
    const res: any = await http.get('/supplier-products', {
      params: { page: 1, page_size: 30, keyword: q || undefined, active_only: true },
    })
    productOptions.value = res.data?.items || res.data || []
  } finally {
    productLoading.value = false
  }
}

function openAdjust(row?: any) {
  form.supplier_product_id = row?.supplier_product_id || null
  form.size_id = row?.size_id ?? null
  form.qty_delta = 0
  form.unit_cost = undefined
  form.note = ''
  if (row) {
    productOptions.value = [
      {
        id: row.supplier_product_id,
        product_code: row.supplier_product_code,
        name: row.supplier_product_name,
      },
    ]
  } else {
    searchProducts('')
  }
  adjustVisible.value = true
}

async function openLedger(row: any) {
  const sizePart = row.size_value ? ` · ${row.size_value}` : ''
  ledgerTitle.value = `流水 · ${row.supplier_product_code || ''} ${row.supplier_product_name || ''}${sizePart}`
  ledgerVisible.value = true
  ledgerLoading.value = true
  ledgerPage.value = 1
  ledgers.value = []
  try {
    const res: any = await http.get('/shared-materials/ledgers', {
      params: {
        supplier_product_id: row.supplier_product_id,
        size_id: row.size_id || undefined,
        limit: 500,
      },
    })
    ledgers.value = res.data || []
  } finally {
    ledgerLoading.value = false
  }
}

async function doAdjust() {
  if (!form.supplier_product_id) {
    ElMessage.warning('请选择物料')
    return
  }
  if (!form.qty_delta) {
    ElMessage.warning('请填写增减数量')
    return
  }
  const note = (form.note || '').trim()
  if (!note) {
    ElMessage.warning('请填写备注')
    return
  }
  await http.post('/shared-materials/adjust', {
    supplier_product_id: form.supplier_product_id,
    size_id: form.size_id || null,
    qty_delta: form.qty_delta,
    unit_cost: form.unit_cost,
    note,
  })
  ElMessage.success('已调整')
  adjustVisible.value = false
  load()
}

function resetInboundForm() {
  inboundForm.image_url = ''
  inboundForm.product_code = ''
  inboundForm.name = ''
  inboundForm.category_id = null
  inboundForm.color_id = null
  inboundForm.size_id = null
  inboundForm.unit_price = undefined
  inboundForm.pricing_unit_id = null
  inboundForm.supplier_name = ''
  inboundForm.qty = undefined
}

async function openManualInbound() {
  resetInboundForm()
  inboundVisible.value = true
  try {
    const [colorRes, unitRes, partnerRes]: any[] = await Promise.all([
      http.get('/colors'),
      http.get('/pricing-units'),
      http.get('/partners', { params: { role: 'supplier', active_only: true, page: 1, page_size: 500 } }),
    ])
    colors.value = colorRes.data?.items || []
    units.value = unitRes.data?.items || []
    supplierNames.value = (partnerRes.data?.items || [])
      .map((p: any) => String(p.name || '').trim())
      .filter(Boolean)
  } catch {
    /* 下拉失败仍可手填编号和供应商 */
  }
}

function querySupplierSuggestions(query: string, cb: (items: { value: string }[]) => void) {
  const q = query.trim().toLowerCase()
  const items = supplierNames.value
    .filter((name) => !q || name.toLowerCase().includes(q))
    .slice(0, 20)
    .map((name) => ({ value: name }))
  cb(items)
}

async function onInboundImage(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('请选择图片')
    return
  }
  inboundUploading.value = true
  try {
    const prepared = await prepareImageForUpload(file)
    const fd = new FormData()
    fd.append('file', prepared)
    const res: any = await http.post('/supplier-products/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    inboundForm.image_url = res.data?.url || ''
  } finally {
    inboundUploading.value = false
  }
}

async function submitInbound() {
  const productCode = inboundForm.product_code.trim()
  const name = inboundForm.name.trim()
  const supplierName = inboundForm.supplier_name.trim()
  const qty = Number(inboundForm.qty)
  if (!productCode) {
    ElMessage.warning('请填写物料编号')
    return
  }
  if (!name) {
    ElMessage.warning('请填写名称')
    return
  }
  if (!supplierName) {
    ElMessage.warning('请填写供应商')
    return
  }
  if (!qty || qty <= 0) {
    ElMessage.warning('入库数量须大于 0')
    return
  }
  inboundSaving.value = true
  try {
    await http.post('/shared-materials/manual-receive', {
      product_code: productCode,
      name,
      supplier_name: supplierName,
      qty,
      category_id: inboundForm.category_id,
      color_id: inboundForm.color_id,
      size_id: inboundForm.size_id,
      unit_price: inboundForm.unit_price ?? null,
      pricing_unit_id: inboundForm.pricing_unit_id,
      image_url: inboundForm.image_url || null,
    })
    ElMessage.success('已入库，并同步到物料色卡和供应商')
    inboundVisible.value = false
    await load()
  } finally {
    inboundSaving.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadCategories(), loadSizes()])
  await load()
})
</script>

<style scoped>
.slip-groups {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}
.inv-panel {
  min-width: 0;
}
.category-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}
.col-h {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  line-height: 1.2;
}
.col-h-tip {
  font-size: 14px;
  color: #909399;
  cursor: help;
  vertical-align: middle;
}
.col-h-tip:hover {
  color: var(--el-color-primary);
}
.cat-chip {
  border: 1px solid #dcdfe6;
  background: #fff;
  color: #606266;
  border-radius: 4px;
  padding: 4px 12px;
  font-size: 13px;
  line-height: 1.4;
  cursor: pointer;
}
.cat-chip:hover:not(:disabled) {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}
.cat-chip.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary);
  color: #fff;
}
.cat-chip:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.product-thumb {
  width: 100%;
  aspect-ratio: 1 / 1;
  height: auto;
  display: block;
  margin: 0;
  border-radius: 4px;
}
.product-thumb :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
:deep(td.mat-image-col) {
  padding: 2px !important;
}
:deep(th.mat-image-col) {
  padding: 8px 2px !important;
}
:deep(td.mat-image-col .cell) {
  padding: 2px !important;
  line-height: 0;
  width: 100%;
}
:deep(th.mat-image-col .cell) {
  padding: 0 2px !important;
}
.mat-image-empty {
  line-height: 1.45;
  display: inline-block;
}
.muted {
  color: var(--el-text-color-secondary);
}
.warn {
  color: var(--el-color-warning);
  font-weight: 600;
}
.alert-short {
  color: var(--el-color-danger);
  font-weight: 600;
}
.qty-hover {
  cursor: pointer;
  border-bottom: 1px dashed currentColor;
}
.demand-order-img {
  width: 36px;
  height: 36px;
}
.demand-size-note {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.in {
  color: var(--el-color-success);
  font-weight: 600;
}
.out {
  color: var(--el-color-danger);
  font-weight: 600;
}
.select-hint {
  margin: 0 0 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.pool-table :deep(.el-table-column--selection .cell) {
  justify-content: center;
}
.return-note {
  margin-top: 12px;
}
.inbound-image {
  display: flex;
  align-items: center;
  gap: 12px;
}
.inbound-thumb {
  width: 72px;
  height: 72px;
  border-radius: 4px;
  border: 1px solid #dcdfe6;
  background: #fafafa;
}
.inbound-thumb-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.inbound-image-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.inbound-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  column-gap: 16px;
}
.product-file-input {
  display: none;
}
.ledger-drawer-body {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  gap: 12px;
}
.ledger-drawer-body > .el-table {
  flex: 1;
  min-height: 0;
}
.ledger-pagination {
  flex: none;
  display: flex;
  justify-content: flex-end;
}
</style>

<style>
.ledger-drawer.el-drawer .el-drawer__body {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  padding-bottom: 16px;
  box-sizing: border-box;
}
.pool-detail-popper.el-popover {
  padding: 10px 12px;
  box-sizing: border-box;
}
.pool-detail-panel {
  width: 100%;
  overflow-x: hidden;
}
.pool-detail-panel .pool-detail-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}
.pool-detail-popper .pool-detail-table.el-table,
.pool-detail-popper .pool-detail-table .el-table__inner-wrapper,
.pool-detail-popper .pool-detail-table .el-table__header,
.pool-detail-popper .pool-detail-table .el-table__body {
  width: 100% !important;
}
.pool-detail-popper .el-table__body-wrapper,
.pool-detail-popper .el-table__header-wrapper {
  overflow-x: hidden !important;
}
.pool-detail-popper .occ-thumb {
  width: 40px;
  height: 40px;
  display: block;
  margin: 0 auto;
  border-radius: 4px;
}
.pool-detail-popper .occ-thumb .el-image__inner {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
</style>
