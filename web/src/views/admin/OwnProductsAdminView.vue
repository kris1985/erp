<template>
  <div class="own-page">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">产品开发</h1>
        <p class="page-desc">一色一款 · 工序报价 · 物料成本 · 客户报价</p>
      </div>
    </header>

    <div class="admin-toolbar own-toolbar">
      <div class="own-toolbar-left">
        <el-input
          v-model="keyword"
          clearable
          placeholder="搜索产品编号"
          class="search-input"
          @clear="reloadList"
          @keyup.enter="reloadList"
        >
          <template #prefix>
            <el-icon class="search-icon"><Search /></el-icon>
          </template>
        </el-input>
        <div class="own-sort-group">
          <el-select v-model="sortKey" class="sort-select" style="width: 120px" @change="reloadList">
            <el-option label="按日期" value="date" />
            <el-option label="按订单量" value="order_qty" />
          </el-select>
          <el-radio-group v-model="sortOrder" size="default" @change="reloadList">
            <el-radio-button label="desc">降序</el-radio-button>
            <el-radio-button label="asc">升序</el-radio-button>
          </el-radio-group>
        </div>
      </div>
      <div class="own-toolbar-right">
        <template v-if="batchSelectMode">
          <el-checkbox
            v-if="rows.length"
            :model-value="pageAllSelected"
            :indeterminate="pageSomeSelected"
            @change="togglePageSelect"
          >
            本页全选
          </el-checkbox>
          <el-button
            type="primary"
            :disabled="!selectedCount"
            @click="confirmBatchSelection"
          >
            确认报价{{ selectedCount ? `（${selectedCount}）` : '' }}
          </el-button>
          <el-button @click="exitBatchSelectMode">取消</el-button>
        </template>
        <el-button
          v-else
          type="primary"
          plain
          :disabled="!rows.length && !total"
          @click="enterBatchSelectMode"
        >
          批量报价
        </el-button>
        <el-button type="primary" class="add-btn" @click="openForm()">新增产品</el-button>
      </div>
    </div>

    <div class="gallery-scroll-host">
      <div v-if="rows.length" class="product-gallery" :class="{ 'is-selecting': batchSelectMode }">
        <article
          v-for="(row, index) in rows"
          :key="row.id"
          class="gallery-card"
          :class="{ 'is-selected': batchSelectMode && isSelected(row.id) }"
          :style="{ '--delay': `${Math.min(index, 15) * 28}ms` }"
        >
          <label v-if="batchSelectMode" class="gallery-check" @click.stop>
            <el-checkbox
              :model-value="isSelected(row.id)"
              @change="(v: boolean | string | number) => toggleSelect(row, !!v)"
            />
          </label>
          <button type="button" class="gallery-image-btn" @click="openDetail(row)">
            <el-image
              v-if="row.image_url"
              :src="row.image_url"
              fit="contain"
              class="gallery-image"
            />
            <div v-else class="gallery-image-empty">
              <span>暂无图片</span>
            </div>
            <div class="gallery-image-veil">查看详情</div>
          </button>
          <div class="gallery-text">
            <div class="gallery-row">
              <span class="gallery-code" :title="row.product_code">{{ row.product_code }}</span>
              <span class="gallery-cost">¥{{ formatPrice(totalCost(row)) }}</span>
            </div>
            <div v-if="row.colors?.length" class="gallery-colors">
              <span
                v-for="c in row.colors.slice(0, 3)"
                :key="c.id"
                class="gallery-color-chip"
              >{{ c.name }}</span>
              <span v-if="row.colors.length > 3" class="gallery-color-more">+{{ row.colors.length - 3 }}</span>
            </div>
            <div v-else class="gallery-colors">
              <span class="gallery-color-chip is-missing">未绑色</span>
            </div>
            <div class="gallery-foot">
              <span class="gallery-qty">
                订单量
                <strong>{{ Number(row.order_qty || 0).toLocaleString('zh-CN') }}</strong>
              </span>
              <span class="gallery-date">{{ formatDate(row.created_at) }}</span>
            </div>
          </div>
        </article>
      </div>

      <div v-else class="empty-wrap">
        <el-empty description="暂无产品，点击右上角新增" />
      </div>
    </div>

    <div v-if="total > 0" class="admin-pagination">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        background
        layout="total, sizes, prev, pager, next"
        :total="total"
        :page-sizes="[10, 20, 40, 60]"
        @current-change="loadProducts"
        @size-change="onPageSizeChange"
      />
    </div>

    <el-dialog
      v-model="visible"
      width="96vw"
      top="3vh"
      class="dev-dialog product-edit-dialog"
      destroy-on-close
      @opened="onEditDialogOpened"
    >
      <template #header>
        <div class="detail-dialog-header">
          <div class="detail-dialog-heading">
            <span class="detail-dialog-title">
              {{ form.id ? '编辑产品' : isCopying ? '复制产品' : '新增产品' }}
            </span>
            <span v-if="form.product_code" class="detail-dialog-code">{{ form.product_code }}</span>
          </div>
          <div class="detail-dialog-actions">
            <el-button
              v-if="form.id"
              :loading="exportingId === form.id"
              @click="startExport({ id: form.id, product_code: form.product_code })"
            >
              导出 Excel
            </el-button>
            <el-button v-if="form.id" @click="copyFromEdit">复制为新</el-button>
            <el-button @click="visible = false">取消</el-button>
            <el-button type="primary" :loading="saving" @click="save">保存</el-button>
          </div>
        </div>
      </template>
      <div class="dev-layout">
        <section class="dev-panel shoe-panel">
          <div class="panel-kicker">产品信息</div>
          <el-alert
            v-if="isCopying"
            class="copy-hint"
            type="info"
            :closable="false"
            show-icon
            title="已复制物料、工序、成本与报价。请修改编号与颜色后保存（同款不同色常用）。"
          />
          <div
            class="shoe-image-box"
            :class="{ 'is-dragging': imageDragging, 'is-uploading': uploading }"
            tabindex="0"
            @dragenter.prevent="onImageDragEnter"
            @dragover.prevent="onImageDragOver"
            @dragleave.prevent="onImageDragLeave"
            @drop.prevent="onImageDrop"
            @paste="onImagePaste"
            @click="onImageZoneClick"
          >
            <el-image
              v-if="form.image_url"
              :src="form.image_url"
              fit="contain"
              class="shoe-preview"
            />
            <div v-else class="shoe-preview empty">
              <span>{{ uploading ? '上传中…' : '拖拽 / 粘贴 / 点击上传' }}</span>
            </div>
            <div v-if="imageDragging" class="shoe-drop-mask">松开以上传</div>
            <div v-else-if="form.image_url && !uploading" class="shoe-hover-hint">点击更换图片</div>
            <button
              v-if="form.image_url && !uploading"
              type="button"
              class="shoe-clear-btn"
              @click.stop="form.image_url = ''"
            >
              清除
            </button>
            <input
              ref="imageFileInputRef"
              type="file"
              class="shoe-file-input"
              accept="image/jpeg,image/png,image/gif,image/webp"
              @change="onImageFileChange"
            />
          </div>

          <el-form label-position="top" class="shoe-form">
            <el-form-item label="产品编号" required>
              <el-input v-model="form.product_code" placeholder="如 OP-001" />
            </el-form-item>
            <el-form-item label="颜色" required>
              <div class="color-select-row">
                <el-select
                  v-model="formColorId"
                  filterable
                  style="flex: 1; min-width: 0"
                  placeholder="本货号的成品颜色"
                >
                  <el-option
                    v-for="c in colors"
                    :key="c.id"
                    :label="c.name"
                    :value="c.id"
                  />
                </el-select>
                <el-popover
                  v-model:visible="colorQuickVisible"
                  placement="bottom-end"
                  :width="280"
                  trigger="click"
                  @show="onColorQuickShow"
                >
                  <template #reference>
                    <el-button>新增</el-button>
                  </template>
                  <div class="color-quick">
                    <div class="color-quick-title">新增颜色</div>
                    <el-input
                      ref="colorQuickInputRef"
                      v-model="newColorName"
                      placeholder="如：黑、白、卡其"
                      maxlength="20"
                      @keyup.enter="createColorQuick"
                    />
                    <div class="color-quick-actions">
                      <el-button size="small" @click="colorQuickVisible = false">取消</el-button>
                      <el-button
                        type="primary"
                        size="small"
                        :loading="creatingColor"
                        @click="createColorQuick"
                      >
                        添加
                      </el-button>
                    </div>
                  </div>
                </el-popover>
              </div>
              <p class="muted color-bind-hint">
                一色一款：每个货号只绑一个颜色。同楦不同色请复制产品，改编号和颜色后保存。
              </p>
              <p v-if="extraBoundColorNames.length" class="color-bind-warn">
                该货号还绑了{{ extraBoundColorNames.join('、') }}。保存后只保留当前所选色。
              </p>
            </el-form-item>
            <el-form-item label="面料">
              <el-input v-model="form.fabric" placeholder="选填" maxlength="100" />
            </el-form-item>
            <el-form-item label="内里">
              <el-input v-model="form.lining" placeholder="选填" maxlength="100" />
            </el-form-item>
            <el-form-item label="订单量">
              <el-input-number
                v-model="form.order_qty"
                :min="0"
                :precision="0"
                :step="1"
                controls-position="right"
                style="width: 100%"
                placeholder="订单量"
              />
            </el-form-item>
            <el-form-item label="追溯">
              <el-switch
                v-model="form.trace_enabled"
                active-text="开启"
                inactive-text="关闭"
              />
              <div class="muted" style="margin-top: 4px; line-height: 1.4">
                开追溯：开裁必须打扎捆码，合帮前必须扫扎捆。关追溯：合帮前可扫流转卡或扎捆（看是否打印）。
              </div>
            </el-form-item>
            <el-form-item label="总成本">
              <div class="edit-total-cost">
                <span class="edit-total-label">合计</span>
                <strong>¥{{ formatPrice(previewTotalCost) }}</strong>
              </div>
              <div class="edit-cost-breakdown">
                <span>物料 ¥{{ formatPrice(previewMaterialCost) }}</span>
                <span>人工 ¥{{ formatPrice(previewLaborCost) }}</span>
                <span>其它 ¥{{ formatPrice(previewOtherCost) }}</span>
              </div>
            </el-form-item>
            <el-form-item label="统一报价">
              <el-input-number
                v-model="form.quote_price"
                :min="0"
                :precision="2"
                :step="1"
                controls-position="right"
                style="width: 100%"
                placeholder="手输统一报价"
              />
              <div v-if="form.id && peerActuals" class="peer-edit-hint muted">
                <template v-if="peerActuals.available">
                  实际 ¥{{ formatPrice(peerActuals.actual_unit_cost?.median) }}/双 ·
                  {{ peerVsArchiveShort(peerActuals) }}
                </template>
                <template v-else>
                  暂无出货记录 · 档案 ¥{{ formatPrice(peerActuals.card_unit_cost) }}/双
                </template>
              </div>
            </el-form-item>
            <el-form-item label="客户报价" class="quote-form-item">
              <div class="quote-editor">
                <div class="panel-title-row quote-toolbar">
                  <span class="quote-hint">按客户分别报价（可选）</span>
                  <el-button type="primary" size="small" @click="addQuote">添加客户</el-button>
                </div>
                <el-table
                  ref="quotesTableRef"
                  border
                  :data="form.quotes"
                  size="small"
                  class="soft-table"
                  empty-text="暂无客户报价"
                  @header-dragend="onHeaderDragend"
                >
                  <el-table-column
                    column-key="customer"
                    label="客户"
                    :min-width="flexColMinWidth('customer', 120)"
                    resizable
                  >
                    <template #default="{ row }">
                      <el-select
                        v-model="row.partner_id"
                        filterable
                        style="width: 100%"
                        placeholder="选择客户"
                      >
                        <el-option
                          v-for="c in customers"
                          :key="c.id"
                          :label="c.short_name ? `${c.short_name}（${c.name}）` : c.name"
                          :value="c.id"
                          :disabled="isCustomerUsed(c.id, row)"
                        />
                      </el-select>
                    </template>
                  </el-table-column>
                  <el-table-column column-key="quote_price" label="报价" :width="colWidth('quote_price', 118)" resizable>
                    <template #default="{ row }">
                      <el-input-number
                        v-model="row.quote_price"
                        :min="0"
                        :precision="2"
                        :step="1"
                        controls-position="right"
                        style="width: 100%"
                      />
                    </template>
                  </el-table-column>
                  <el-table-column column-key="col" label="" :width="colWidth('col', 44)" resizable>
                    <template #default="{ $index }">
                      <el-button link type="danger" :icon="Delete" title="删除" @click="form.quotes.splice($index, 1)" />
                    </template>
                  </el-table-column>
                </el-table>
              </div>
            </el-form-item>
          </el-form>
        </section>

        <section class="dev-panel materials-panel">
          <div class="panel-title-row">
            <div class="panel-title">物料明细</div>
            <el-button type="primary" size="small" @click="addMaterial">添加物料</el-button>
          </div>
          <el-table
            ref="materialsTableRef"
            border
            :data="form.materials"
            size="small"
            class="soft-table"
            empty-text="请添加物料"
            @header-dragend="onHeaderDragend1"
          >
            <el-table-column
              column-key="material_image"
              label="图片"
              :width="colWidth1('material_image', 72)"
              align="center"
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
              column-key="name"
              label="名称"
              :min-width="flexColMinWidth1('name', 100)"
              show-overflow-tooltip
              resizable
            >
              <template #default="{ row }">{{ row.supplier_product_name || '—' }}</template>
            </el-table-column>
            <el-table-column column-key="color" label="颜色" :width="colWidth1('color', 72)" resizable>
              <template #default="{ row }">{{ row.color_name || '—' }}</template>
            </el-table-column>
            <el-table-column column-key="material_code" label="编号" :width="colWidth1('material_code', 150)" resizable>
              <template #default="{ row }">
                <el-select
                  v-model="row.supplier_product_id"
                  filterable
                  size="small"
                  style="width: 100%"
                  placeholder="选择"
                  @change="onMaterialProductChange(row)"
                >
                  <el-option
                    v-for="sp in supplierProducts"
                    :key="sp.id"
                    :label="supplierProductLabel(sp)"
                    :value="sp.id"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column column-key="supplier" label="供应商" :width="colWidth1('supplier', 100)" show-overflow-tooltip resizable>
              <template #default="{ row }">{{ row.partner_name || '—' }}</template>
            </el-table-column>
            <el-table-column column-key="unit_price" label="单价" :width="colWidth1('unit_price', 80)" align="right" resizable>
              <template #default="{ row }">{{ formatPrice(row.unit_price, 1) }}</template>
            </el-table-column>
            <el-table-column column-key="qty" label="用量" :width="colWidth1('qty', 120)" resizable>
              <template #default="{ row }">
                <el-input-number
                  v-model="row.qty"
                  :min="0"
                  :precision="1"
                  :step="1"
                  controls-position="right"
                  size="small"
                  style="width: 100%"
                />
              </template>
            </el-table-column>
            <el-table-column column-key="price_unit" label="单位" :width="colWidth1('price_unit', 80)" resizable>
              <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
            </el-table-column>
            <el-table-column column-key="consume_process" label="消耗工序" :width="colWidth1('consume_process', 130)" resizable>
              <template #default="{ row }">
                <el-select
                  v-model="row.consume_process_id"
                  clearable
                  filterable
                  size="small"
                  placeholder="跟分类/首道"
                  style="width: 100%"
                >
                  <el-option v-for="p in processes" :key="p.id" :label="p.name" :value="p.id" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column column-key="usage_by_size" label="按码" :width="colWidth1('usage_by_size', 70)" align="center" resizable>
              <template #default="{ row }">
                <el-switch v-model="row.usage_by_size" size="small" />
              </template>
            </el-table-column>
            <el-table-column column-key="size_table" label="用量码表" :width="colWidth1('size_table', 140)" resizable>
              <template #default="{ row }">
                <el-select
                  v-model="row.size_usage_table_id"
                  clearable
                  filterable
                  size="small"
                  :disabled="!row.usage_by_size"
                  placeholder="选码表"
                  style="width: 100%"
                >
                  <el-option v-for="t in sizeUsageTables" :key="t.id" :label="t.name" :value="t.id" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column column-key="loss_rate" label="损耗%" :width="colWidth1('loss_rate', 100)" resizable>
              <template #default="{ row }">
                <el-input-number
                  v-model="row.loss_rate_pct"
                  :min="0"
                  :max="100"
                  :precision="1"
                  :step="0.5"
                  controls-position="right"
                  size="small"
                  style="width: 100%"
                />
              </template>
            </el-table-column>
            <el-table-column column-key="loss_fixed" label="固定损耗" :width="colWidth1('loss_fixed', 110)" resizable>
              <template #default="{ row }">
                <el-input-number
                  v-model="row.loss_fixed_qty"
                  :min="0"
                  :precision="1"
                  :step="0.1"
                  controls-position="right"
                  size="small"
                  style="width: 100%"
                />
              </template>
            </el-table-column>
            <el-table-column column-key="material_total" label="总价" :width="colWidth1('material_total', 96)" align="right" resizable>
              <template #default="{ row }">
                <span class="money">{{ formatPrice(lineTotal(row)) }}</span>
              </template>
            </el-table-column>
            <el-table-column column-key="col" label="" :width="colWidth1('col', 56)" fixed="right" resizable>
              <template #default="{ $index }">
                <el-button link type="danger" :icon="Delete" title="删除" @click="form.materials.splice($index, 1)" />
              </template>
            </el-table-column>
          </el-table>
          <div class="cost-summary-line">
            <span>材料成本</span>
            <strong>¥{{ formatPrice(previewMaterialCost) }}</strong>
          </div>

          <div class="panel-title-row labor-title">
            <div class="panel-title">部件清单（工艺两段）</div>
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap">
              <el-button type="primary" size="small" @click="addPart">添加部件</el-button>
              <el-popover
                v-model:visible="partQuickVisible"
                placement="bottom-end"
                :width="280"
                trigger="click"
                @show="onPartQuickShow"
              >
                <template #reference>
                  <el-button size="small">新建部件</el-button>
                </template>
                <div class="color-quick">
                  <div class="color-quick-title">新建部件（写入部件字典）</div>
                  <el-input
                    ref="partQuickNameRef"
                    v-model="newPartName"
                    placeholder="如：前帮、后帮、鞋舌"
                    maxlength="50"
                    @keyup.enter="createPartQuick"
                  />
                  <div class="color-quick-actions">
                    <el-button size="small" @click="partQuickVisible = false">取消</el-button>
                    <el-button
                      type="primary"
                      size="small"
                      :loading="creatingPart"
                      @click="createPartQuick"
                    >
                      添加
                    </el-button>
                  </div>
                </div>
              </el-popover>
              <el-button size="small" @click="loadPartDefinitions">刷新</el-button>
            </div>
          </div>
          <el-table
            ref="partsTableRef"
            border
            :data="form.parts"
            size="small"
            class="soft-table"
            empty-text="无部件时沿用整鞋单线工序；配置部件后开裁可生成「1筐N捆」"
            @header-dragend="onHeaderDragendParts"
          >
            <el-table-column
              column-key="part_id"
              label="部件"
              :min-width="flexColMinWidthParts('part_id', 160)"
              resizable
            >
              <template #default="{ row }">
                <el-select
                  v-model="row.part_id"
                  filterable
                  style="width: 100%"
                  placeholder="选择部件"
                >
                  <el-option
                    v-for="p in partDefinitions"
                    :key="p.id"
                    :label="p.name"
                    :value="p.id"
                    :disabled="isPartUsed(p.id, row)"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column column-key="pieces" label="每双件数" :width="colWidthParts('pieces', 110)" resizable>
              <template #default="{ row }">
                <el-input-number
                  v-model="row.pieces_per_pair"
                  :min="1"
                  :precision="0"
                  controls-position="right"
                  style="width: 100%"
                />
              </template>
            </el-table-column>
            <el-table-column column-key="col" label="" :width="colWidthParts('col', 56)" fixed="right" resizable>
              <template #default="{ $index }">
                <el-button
                  link
                  type="danger"
                  :icon="Delete"
                  title="删除"
                  @click="removePartAt($index)"
                />
              </template>
            </el-table-column>
          </el-table>

          <div class="panel-title-row labor-title">
            <div class="panel-title">人工成本</div>
            <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap">
              <el-checkbox v-if="form.id" v-model="syncLaborsToOpenOrders">
                同步到在制执行单
              </el-checkbox>
              <el-button type="primary" size="small" @click="addLabor">添加行</el-button>
              <el-popover
                v-model:visible="processQuickVisible"
                placement="bottom-end"
                :width="280"
                trigger="click"
                @show="onProcessQuickShow"
              >
                <template #reference>
                  <el-button size="small">新建工序</el-button>
                </template>
                <div class="color-quick">
                  <div class="color-quick-title">新建工序（写入基础资料）</div>
                  <el-input
                    ref="processQuickInputRef"
                    v-model="newProcessName"
                    placeholder="如：裁断、针车"
                    maxlength="50"
                    @keyup.enter="createProcessQuick"
                  />
                  <el-select v-model="newProcessType" style="width: 100%; margin-top: 8px">
                    <el-option label="个人" value="personal" />
                    <el-option label="集体" value="group" />
                  </el-select>
                  <div class="color-quick-actions">
                    <el-button size="small" @click="processQuickVisible = false">取消</el-button>
                    <el-button
                      type="primary"
                      size="small"
                      :loading="creatingProcess"
                      @click="createProcessQuick"
                    >
                      添加
                    </el-button>
                  </div>
                </div>
              </el-popover>
            </div>
          </div>
          <el-table
            ref="laborsTableRef"
            border
            :data="form.labors"
            size="small"
            class="soft-table"
            empty-text="点击「添加行」选择工序，或「新建工序」写入基础资料"
            @header-dragend="onHeaderDragend2"
          >
            <el-table-column
              column-key="process_name"
              label="工序"
              :min-width="flexColMinWidth2('process_name', 160)"
              resizable
            >
              <template #default="{ row }">
                <el-select
                  v-model="row.process_name"
                  filterable
                  style="width: 100%"
                  placeholder="选择工序"
                  @change="(name: string) => onLaborProcessChange(row, name)"
                >
                  <el-option
                    v-for="p in laborProcessOptions"
                    :key="p.id"
                    :label="p.name"
                    :value="p.name"
                    :disabled="isProcessNameUsed(p.name, row)"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column column-key="part_id" label="所属段" :width="colWidth2('part_id', 140)" resizable>
              <template #default="{ row }">
                <el-select
                  v-model="row.part_id"
                  clearable
                  placeholder="整鞋段"
                  style="width: 100%"
                  @change="() => onLaborPartChange(row)"
                >
                  <el-option label="整鞋段" :value="null" />
                  <el-option
                    v-for="p in form.parts.filter((x: any) => x.part_id)"
                    :key="p.part_id"
                    :label="partLabel(p.part_id)"
                    :value="p.part_id"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column column-key="type" label="类型" :width="colWidth2('type', 110)" resizable>
              <template #default="{ row }">
                <el-select v-model="row.process_type" style="width: 100%">
                  <el-option label="个人" value="personal" />
                  <el-option label="集体" value="group" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column column-key="kit" label="齐套点" :width="colWidth2('kit', 88)" align="center" resizable>
              <template #default="{ row }">
                <el-checkbox
                  v-model="row.is_kit_checkpoint"
                  :disabled="row.part_id != null"
                  @change="() => onKitCheckpointChange(row)"
                />
              </template>
            </el-table-column>
            <el-table-column column-key="price" label="价格" :width="colWidth2('price', 140)" resizable>
              <template #default="{ row }">
                <el-input-number
                  v-model="row.unit_price"
                  :min="0"
                  :precision="2"
                  :step="0.1"
                  controls-position="right"
                  style="width: 100%"
                />
              </template>
            </el-table-column>
            <el-table-column column-key="col" label="" :width="colWidth2('col', 56)" fixed="right" resizable>
              <template #default="{ $index }">
                <el-button link type="danger" :icon="Delete" title="删除" @click="form.labors.splice($index, 1)" />
              </template>
            </el-table-column>
          </el-table>
          <div class="cost-summary-line">
            <span>人工成本</span>
            <strong>¥{{ formatPrice(previewLaborCost) }}</strong>
          </div>

          <div class="panel-title-row labor-title">
            <div class="panel-title">其它成本</div>
            <div style="display: flex; align-items: center; gap: 8px">
              <el-button type="primary" size="small" @click="addOtherCost">添加行</el-button>
              <el-popover
                v-model:visible="otherCostQuickVisible"
                placement="bottom-end"
                :width="280"
                trigger="click"
                @show="onOtherCostQuickShow"
              >
                <template #reference>
                  <el-button size="small">新建其它成本</el-button>
                </template>
                <div class="color-quick">
                  <div class="color-quick-title">新建其它成本（写入基础资料）</div>
                  <el-input
                    ref="otherCostQuickInputRef"
                    v-model="newOtherCostName"
                    placeholder="如：包装辅料"
                    maxlength="50"
                    @keyup.enter="createOtherCostQuick"
                  />
                  <div class="color-quick-actions">
                    <el-button size="small" @click="otherCostQuickVisible = false">取消</el-button>
                    <el-button
                      type="primary"
                      size="small"
                      :loading="creatingOtherCost"
                      @click="createOtherCostQuick"
                    >
                      添加
                    </el-button>
                  </div>
                </div>
              </el-popover>
            </div>
          </div>
          <el-table
            ref="overheadTableRef"
            border
            :data="form.other_costs"
            size="small"
            class="soft-table"
            empty-text="点击「添加行」选择其它成本，或「新建其它成本」写入基础资料"
            @header-dragend="onHeaderDragend3"
          >
            <el-table-column
              column-key="item"
              label="项目"
              :min-width="flexColMinWidth3('item', 180)"
              resizable
            >
              <template #default="{ row }">
                <el-select
                  v-model="row.name"
                  filterable
                  style="width: 100%"
                  placeholder="选择其它成本"
                >
                  <el-option
                    v-for="item in activeOtherCostItems"
                    :key="item.id"
                    :label="item.name"
                    :value="item.name"
                    :disabled="isOtherCostNameUsed(item.name, row)"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column column-key="amount" label="金额" :width="colWidth3('amount', 140)" resizable>
              <template #default="{ row }">
                <el-input-number
                  v-model="row.amount"
                  :min="0"
                  :precision="2"
                  :step="0.1"
                  controls-position="right"
                  style="width: 100%"
                />
              </template>
            </el-table-column>
            <el-table-column column-key="col" label="" :width="colWidth3('col', 56)" fixed="right" resizable>
              <template #default="{ $index }">
                <el-button link type="danger" :icon="Delete" title="删除" @click="form.other_costs.splice($index, 1)" />
              </template>
            </el-table-column>
          </el-table>
          <div class="cost-summary-line">
            <span>其它成本</span>
            <strong>¥{{ formatPrice(previewOtherCost) }}</strong>
          </div>
        </section>
      </div>
    </el-dialog>

    <el-dialog
      v-model="detailVisible"
      width="96vw"
      top="3vh"
      class="dev-dialog detail-dialog"
      destroy-on-close
      @opened="onDetailDialogOpened"
    >
      <template #header>
        <div class="detail-dialog-header">
          <div class="detail-dialog-heading">
            <span class="detail-dialog-title">产品详情</span>
            <span v-if="detailRow" class="detail-dialog-code">{{ detailRow.product_code }}</span>
          </div>
          <div v-if="detailRow" class="detail-dialog-actions">
            <el-button
              size="default"
              :loading="exportingId === detailRow.id"
              @click="startExport(detailRow)"
            >
              导出 Excel
            </el-button>
            <el-button @click="copyFromDetail">复制</el-button>
            <el-button type="danger" plain @click="remove(detailRow)">删除</el-button>
            <el-button type="primary" @click="editFromDetail">编辑</el-button>
          </div>
        </div>
      </template>
      <div v-if="detailRow" class="dev-layout">
        <section class="dev-panel shoe-panel">
          <div class="panel-kicker">产品信息</div>
          <div class="shoe-image-box">
            <el-image
              v-if="detailRow.image_url"
              :src="detailRow.image_url"
              fit="contain"
              class="shoe-preview"
              :preview-src-list="[detailRow.image_url]"
              preview-teleported
            />
            <div v-else class="shoe-preview empty">暂无产品图</div>
          </div>
          <div class="detail-meta">
            <div class="detail-meta-row">
              <span>产品编号</span>
              <b>{{ detailRow.product_code }}</b>
            </div>
            <div class="detail-meta-row">
              <span>颜色</span>
              <b>
                {{
                  detailRow.colors?.length
                    ? detailRow.colors.map((c) => c.name).join('、')
                    : '未绑颜色'
                }}
              </b>
            </div>
            <div class="detail-meta-row">
              <span>面料</span>
              <b>{{ detailRow.fabric || '—' }}</b>
            </div>
            <div class="detail-meta-row">
              <span>内里</span>
              <b>{{ detailRow.lining || '—' }}</b>
            </div>
            <div class="detail-meta-row">
              <span>订单量</span>
              <b>{{ detailRow.order_qty ?? 0 }}</b>
            </div>
            <div class="detail-meta-row">
              <span>录入日期</span>
              <b>{{ formatDate(detailRow.created_at) }}</b>
            </div>
            <div class="detail-meta-row">
              <span>总成本</span>
              <b class="detail-total-cost">¥{{ formatPrice(totalCost(detailRow)) }}</b>
            </div>
            <div class="detail-meta-row">
              <span>统一报价</span>
              <b>
                {{
                  detailRow.quote_price != null && detailRow.quote_price !== ''
                    ? `¥${formatPrice(detailRow.quote_price)}`
                    : '—'
                }}
              </b>
            </div>
            <div class="detail-meta-row detail-meta-quotes">
              <span class="detail-quotes-heading">客户报价</span>
              <div v-if="detailRow.quotes?.length" class="quote-list">
                <div v-for="q in detailRow.quotes" :key="q.id" class="quote-item">
                  <span class="quote-customer">{{ q.partner_short_name || q.partner_name }}</span>
                  <strong class="quote-value">¥{{ formatPrice(q.quote_price) }}</strong>
                </div>
              </div>
              <b v-else class="detail-quotes-empty">—</b>
            </div>
          </div>

          <section class="peer-actuals-panel" aria-label="批价参照">
            <div class="panel-title-row">
              <div class="panel-title">批价参照</div>
              <span class="section-count">估算</span>
            </div>
            <div v-if="peerActualsLoading" class="muted peer-actuals-empty">加载中…</div>
            <template v-else-if="peerActuals">
              <div v-if="!peerActuals.available" class="peer-actuals-empty muted">
                暂无出货记录 · 档案成本 ¥{{ formatPrice(peerActuals.card_unit_cost) }}/双
              </div>
              <div v-else class="peer-actuals-body">
                <div class="peer-rows">
                  <div class="peer-row">
                    <span class="peer-row-label">实际花费</span>
                    <span class="peer-row-value">
                      ¥{{ formatPrice(peerActuals.actual_unit_cost?.median) }}
                      <em>/双</em>
                    </span>
                  </div>
                  <div class="peer-row">
                    <span class="peer-row-label">档案成本</span>
                    <span class="peer-row-value peer-row-value-sub">
                      ¥{{ formatPrice(peerActuals.card_unit_cost) }}
                      <em>/双</em>
                    </span>
                  </div>
                  <div class="peer-row peer-row-verdict">
                    <span class="peer-row-label">对照</span>
                    <span
                      class="peer-row-value"
                      :class="{
                        'is-hot': Number(peerActuals.delta_vs_card?.median_pct) >= 12,
                        'is-pos': Number(peerActuals.delta_vs_card?.median_pct) > 0,
                        'is-neg': Number(peerActuals.delta_vs_card?.median_pct) < 0,
                      }"
                    >
                      {{ peerVsArchiveText(peerActuals) }}
                    </span>
                  </div>
                  <div v-if="peerShowCostBand(peerActuals)" class="peer-row peer-row-meta">
                    <span class="peer-row-label">多数区间</span>
                    <span class="peer-row-value">
                      ¥{{ formatPrice(peerActuals.actual_unit_cost?.p25) }}–¥{{
                        formatPrice(peerActuals.actual_unit_cost?.p75)
                      }}
                    </span>
                  </div>
                  <div class="peer-row peer-row-meta">
                    <span class="peer-row-label">参考</span>
                    <span class="peer-row-value">
                      <template v-if="peerActuals.actual_gross_margin?.median != null">
                        毛利 {{ formatPeerMargin(peerActuals.actual_gross_margin?.median) }} ·
                      </template>
                      {{
                        (peerActuals.sample_orders || [])
                          .slice(0, 3)
                          .map((s: any) => s.order_no)
                          .filter(Boolean)
                          .join('、') || `${peerActuals.sample_size} 单`
                      }}
                    </span>
                  </div>
                </div>
              </div>
            </template>
          </section>
        </section>

        <section class="dev-panel materials-panel">
          <div class="panel-title-row">
            <div class="panel-title">物料明细</div>
            <span class="section-count">{{ (detailRow.materials || []).length }} 项</span>
          </div>
          <el-table
            ref="detailMaterialsTableRef"
            border
            :data="detailRow.materials || []"
            size="small"
            class="soft-table"
            empty-text="暂无物料"
            @header-dragend="onHeaderDragend4"
          >
            <el-table-column
              column-key="material_image"
              label="图片"
              :width="colWidth4('material_image', 72)"
              align="center"
              class-name="mat-image-col"
              header-class-name="mat-image-col"
              resizable
            >
              <template #default="{ row: m }">
                <el-image
                  v-if="m.image_url"
                  :src="m.image_url"
                  :preview-src-list="[m.image_url]"
                  preview-teleported
                  fit="contain"
                  class="product-thumb"
                />
                <span v-else class="muted mat-image-empty"></span>
              </template>
            </el-table-column>
            <el-table-column column-key="name" label="名称" :min-width="flexColMinWidth4('name', 110)" show-overflow-tooltip resizable>
              <template #default="{ row: m }">{{ m.supplier_product_name || '—' }}</template>
            </el-table-column>
            <el-table-column column-key="color" label="颜色" :width="colWidth4('color', 72)" resizable>
              <template #default="{ row: m }">{{ m.color_name || '—' }}</template>
            </el-table-column>
            <el-table-column column-key="material_code" label="编号" :width="colWidth4('material_code', 100)" show-overflow-tooltip resizable>
              <template #default="{ row: m }">{{ m.supplier_product_code || '—' }}</template>
            </el-table-column>
            <el-table-column column-key="supplier" label="供应商" :width="colWidth4('supplier', 110)" show-overflow-tooltip resizable>
              <template #default="{ row: m }">{{ m.partner_name || '—' }}</template>
            </el-table-column>
            <el-table-column column-key="consume_process" label="消耗工序" :width="colWidth4('consume_process', 110)" resizable>
              <template #default="{ row: m }">
                <span v-if="m.consume_process_name">{{ m.consume_process_name }}</span>
                <span v-else class="muted">未标注</span>
                <el-tag v-if="m.consume_source === 'category'" size="small" type="info" style="margin-left: 4px">分类</el-tag>
                <el-tag v-else-if="m.consume_source === 'bom'" size="small" style="margin-left: 4px">覆盖</el-tag>
              </template>
            </el-table-column>
            <el-table-column column-key="unit_price" label="单价" :width="colWidth4('unit_price', 80)" align="right" resizable>
              <template #default="{ row: m }">{{ formatPrice(m.unit_price, 1) }}</template>
            </el-table-column>
            <el-table-column column-key="qty" label="用量" :width="colWidth4('qty', 70)" align="right" resizable>
              <template #default="{ row: m }">{{ formatPrice(m.qty, 1) }}</template>
            </el-table-column>
            <el-table-column column-key="unit" label="单位" :width="colWidth4('unit', 72)" resizable>
              <template #default="{ row: m }">{{ m.pricing_unit_name || '—' }}</template>
            </el-table-column>
            <el-table-column column-key="loss_rate" label="损耗%" :width="colWidth4('loss_rate', 80)" align="right" resizable>
              <template #default="{ row: m }">{{ formatPrice(Number(m.loss_rate || 0) * 100, 1) }}</template>
            </el-table-column>
            <el-table-column column-key="loss_fixed" label="固定损耗" :width="colWidth4('loss_fixed', 90)" align="right" resizable>
              <template #default="{ row: m }">{{ formatPrice(m.loss_fixed_qty, 1) }}</template>
            </el-table-column>
            <el-table-column column-key="material_total" label="总价" :width="colWidth4('material_total', 90)" align="right" resizable>
              <template #default="{ row: m }">
                <span class="money">{{ formatPrice(m.line_total) }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div class="cost-summary-line">
            <span>材料成本</span>
            <strong>¥{{ formatPrice(detailRow.material_cost) }}</strong>
          </div>

          <div class="panel-title-row labor-title">
            <div class="panel-title">人工成本</div>
            <span class="section-count">{{ (detailRow.labors || []).length }} 道工序</span>
          </div>
          <el-table
            ref="detailLaborsTableRef"
            border
            :data="detailRow.labors || []"
            size="small"
            class="soft-table"
            empty-text="暂无工序"
            @header-dragend="onHeaderDragend5"
          >
            <el-table-column column-key="process_name" label="工序" :min-width="flexColMinWidth5('process_name', 120)" show-overflow-tooltip resizable>
              <template #default="{ row: l }">{{ l.process_name || '—' }}</template>
            </el-table-column>
            <el-table-column column-key="type" label="类型" :width="colWidth5('type', 72)" resizable>
              <template #default="{ row: l }">
                <el-tag v-if="l.process_type === 'group'" size="small" type="warning">集体</el-tag>
                <span v-else class="muted">个人</span>
              </template>
            </el-table-column>
            <el-table-column column-key="price" label="价格" :width="colWidth5('price', 100)" align="right" resizable>
              <template #default="{ row: l }">
                <span class="money">¥{{ formatPrice(l.unit_price) }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div class="cost-summary-line">
            <span>人工成本</span>
            <strong>¥{{ formatPrice(detailRow.labor_cost) }}</strong>
          </div>

          <div class="panel-title-row labor-title">
            <div class="panel-title">其它成本</div>
            <span class="section-count">{{ (detailRow.other_costs || []).length }} 项</span>
          </div>
          <el-table
            ref="detailOverheadTableRef"
            border
            :data="detailRow.other_costs || []"
            size="small"
            class="soft-table"
            empty-text="暂无其它成本"
            @header-dragend="onHeaderDragend6"
          >
            <el-table-column column-key="item" label="项目" :min-width="flexColMinWidth6('item', 140)" show-overflow-tooltip resizable>
              <template #default="{ row: o }">{{ o.name || '—' }}</template>
            </el-table-column>
            <el-table-column column-key="amount" label="金额" :width="colWidth6('amount', 100)" align="right" resizable>
              <template #default="{ row: o }">
                <span class="money">¥{{ formatPrice(o.amount) }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div class="cost-summary-line">
            <span>其它成本</span>
            <strong>¥{{ formatPrice(detailRow.other_cost) }}</strong>
          </div>
        </section>
      </div>
    </el-dialog>

    <el-dialog
      v-model="batchCustomerVisible"
      title="选择报价客户"
      width="440px"
      append-to-body
      destroy-on-close
    >
      <p class="export-hint">
        已选 {{ selectedCount }} 款产品。有该客户报价的用客户价，没有的用统一报价。
      </p>
      <el-radio-group v-model="batchPartnerId" class="export-customer-list">
        <el-radio :label="0" class="export-customer-item">
          <span class="export-customer-name">统一报价（不指定客户）</span>
        </el-radio>
        <el-radio
          v-for="c in customers"
          :key="c.id"
          :label="c.id"
          class="export-customer-item"
        >
          <span class="export-customer-name">{{ c.short_name || c.name }}</span>
        </el-radio>
      </el-radio-group>
      <template #footer>
        <el-button @click="batchCustomerVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmBatchCustomer">查看报价单</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="batchQuoteVisible"
      width="720px"
      top="6vh"
      append-to-body
      destroy-on-close
      class="batch-quote-dialog"
    >
      <template #header>
        <div class="batch-quote-header">
          <div>
            <div class="batch-quote-title">产品报价单</div>
            <div class="batch-quote-sub">
              <template v-if="batchCustomerLabel">客户：{{ batchCustomerLabel }}</template>
              <template v-if="batchPartnerId">（无客户报价用统一报价）</template>
            </div>
          </div>
          <div class="batch-quote-actions">
            <el-button @click="printBatchQuote">打印</el-button>
            <el-button type="primary" :loading="batchExporting" @click="exportBatchQuote">
              导出 Excel
            </el-button>
          </div>
        </div>
      </template>
      <div class="batch-quote-sheet">
        <el-table
          :data="batchQuoteRows"
          size="small"
          stripe
          border
          class="soft-table batch-quote-table"
          empty-text="暂无产品" @header-dragend="onHeaderDragend7">
          <el-table-column column-key="index" type="index" label="#" :width="colWidth7('index', 52)" align="center" />
          <el-table-column column-key="image" label="图片" :width="colWidth7('image', 80)" align="center" resizable>
            <template #default="{ row }">
              <el-image
                v-if="row.image_url"
                :src="row.image_url"
                :preview-src-list="[row.image_url]"
                fit="contain"
                class="batch-quote-thumb"
                preview-teleported
              />
              <span v-else class="batch-quote-thumb empty">无图</span>
            </template>
          </el-table-column>
          <el-table-column prop="product_code" label="编号" :width="colWidth7('product_code', 120)" show-overflow-tooltip resizable />
          <el-table-column prop="color_text" label="颜色" :width="colWidth7('color_text', 120)" show-overflow-tooltip resizable />
          <el-table-column prop="fabric" label="面料" :width="colWidth7('fabric', 100)" show-overflow-tooltip resizable>
            <template #default="{ row }">{{ row.fabric || '—' }}</template>
          </el-table-column>
          <el-table-column prop="lining" label="内里" :width="colWidth7('lining', 100)" show-overflow-tooltip resizable>
            <template #default="{ row }">{{ row.lining || '—' }}</template>
          </el-table-column>
          <el-table-column column-key="price" label="价格" :width="colWidth7('price', 110)" align="right" resizable>
            <template #default="{ row }">
              <strong v-if="row.price != null" class="money">¥{{ formatPrice(row.price) }}</strong>
              <span v-else class="muted">未报价</span>
              <div v-if="row.price_source === 'customer'" class="price-tag">客户价</div>
              <div v-else-if="row.price_source === 'unified'" class="price-tag muted-tag">统一价</div>
            </template>
          </el-table-column>
        </el-table>
        <div class="batch-quote-footer">
          共 {{ batchQuoteRows.length }} 款 · {{ formatDate(new Date().toISOString()) }}
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Search } from '@element-plus/icons-vue'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableColWidths } from '@/composables/useTableColWidths'

const quotesTableRef = ref()
const materialsTableRef = ref()
const partsTableRef = ref()
const laborsTableRef = ref()
const overheadTableRef = ref()
const {
  colWidth,
  flexColMinWidth,
  onHeaderDragend,
  relayoutTable: relayoutQuotes,
} = useTableColWidths('own-products-quotes', quotesTableRef, {
  flexKey: 'customer',
  flexDefaultMin: 120,
  fitToContainer: true,
})
const {
  colWidth: colWidth1,
  flexColMinWidth: flexColMinWidth1,
  onHeaderDragend: onHeaderDragend1,
  relayoutTable: relayoutMaterials,
} = useTableColWidths('own-products-materials', materialsTableRef, {
  flexKey: 'name',
  flexDefaultMin: 100,
  fitToContainer: true,
})
const {
  colWidth: colWidthParts,
  flexColMinWidth: flexColMinWidthParts,
  onHeaderDragend: onHeaderDragendParts,
} = useTableColWidths('own-products-parts', partsTableRef, {
  flexKey: 'part_id',
  flexDefaultMin: 160,
  fitToContainer: true,
})
const {
  colWidth: colWidth2,
  flexColMinWidth: flexColMinWidth2,
  onHeaderDragend: onHeaderDragend2,
  relayoutTable: relayoutLabors,
} = useTableColWidths('own-products-labors', laborsTableRef, {
  flexKey: 'process_name',
  flexDefaultMin: 160,
  fitToContainer: true,
})
const {
  colWidth: colWidth3,
  flexColMinWidth: flexColMinWidth3,
  onHeaderDragend: onHeaderDragend3,
  relayoutTable: relayoutOverhead,
} = useTableColWidths('own-products-overhead', overheadTableRef, {
  flexKey: 'item',
  flexDefaultMin: 180,
  fitToContainer: true,
})
const detailMaterialsTableRef = ref()
const detailLaborsTableRef = ref()
const detailOverheadTableRef = ref()
const {
  colWidth: colWidth4,
  flexColMinWidth: flexColMinWidth4,
  onHeaderDragend: onHeaderDragend4,
  relayoutTable: relayoutDetailMaterials,
} = useTableColWidths('own-products-detail-materials', detailMaterialsTableRef, {
  flexKey: 'name',
  flexDefaultMin: 110,
  fitToContainer: true,
})
const {
  colWidth: colWidth5,
  flexColMinWidth: flexColMinWidth5,
  onHeaderDragend: onHeaderDragend5,
  relayoutTable: relayoutDetailLabors,
} = useTableColWidths('own-products-detail-labors', detailLaborsTableRef, {
  flexKey: 'process_name',
  flexDefaultMin: 120,
  fitToContainer: true,
})
const {
  colWidth: colWidth6,
  flexColMinWidth: flexColMinWidth6,
  onHeaderDragend: onHeaderDragend6,
  relayoutTable: relayoutDetailOverhead,
} = useTableColWidths('own-products-detail-overhead', detailOverheadTableRef, {
  flexKey: 'item',
  flexDefaultMin: 140,
  fitToContainer: true,
})
const { colWidth: colWidth7, onHeaderDragend: onHeaderDragend7 } = useTableColWidths('own-products-list')
const rows = ref<any[]>([])
const colors = ref<any[]>([])
const extraBoundColors = ref<{ id: number; name: string }[]>([])
const supplierProducts = ref<any[]>([])
const processes = ref<any[]>([])
const sizeUsageTables = ref<any[]>([])
const materialCategories = ref<any[]>([])
const customers = ref<any[]>([])
const keyword = ref('')
const sortKey = ref<'date' | 'order_qty'>('date')
const sortOrder = ref<'asc' | 'desc'>('desc')
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const visible = ref(false)
const detailVisible = ref(false)
const detailRow = ref<any>(null)
const isCopying = ref(false)
const peerActuals = ref<any>(null)
const peerActualsLoading = ref(false)
const saving = ref(false)
const syncLaborsToOpenOrders = ref(false)
const uploading = ref(false)
const imageDragging = ref(false)
const imageDragDepth = ref(0)
const imageFileInputRef = ref<HTMLInputElement | null>(null)
const exportingId = ref<number | null>(null)
const selectedMap = ref<Map<number, any>>(new Map())
const batchSelectMode = ref(false)
const batchCustomerVisible = ref(false)
const batchQuoteVisible = ref(false)
const batchPartnerId = ref<number>(0)
const batchQuoteRows = ref<any[]>([])
const batchExporting = ref(false)
const companyName = ref('')
const colorQuickVisible = ref(false)
const creatingColor = ref(false)
const newColorName = ref('')
const colorQuickInputRef = ref<any>(null)
const processQuickVisible = ref(false)
const creatingProcess = ref(false)
const newProcessName = ref('')
const newProcessType = ref<'personal' | 'group'>('personal')
const processQuickInputRef = ref<any>(null)
const partQuickVisible = ref(false)
const creatingPart = ref(false)
const newPartName = ref('')
const partQuickNameRef = ref<any>(null)
const otherCostQuickVisible = ref(false)
const creatingOtherCost = ref(false)
const newOtherCostName = ref('')
const otherCostQuickInputRef = ref<any>(null)
const otherCostItems = ref<any[]>([])
const partDefinitions = ref<any[]>([])
const auth = useAuthStore()

const form = reactive<any>({
  id: null,
  product_code: '',
  image_url: '',
  fabric: '',
  lining: '',
  color_ids: [] as number[],
  parts: [] as any[],
  materials: [] as any[],
  labors: [] as any[],
  other_costs: [] as any[],
  quotes: [] as any[],
  quote_price: null as number | null,
  order_qty: 0,
  trace_enabled: false,
})

const formColorId = computed({
  get: () => form.color_ids[0] ?? null,
  set: (v: number | null) => {
    form.color_ids = v ? [v] : []
    extraBoundColors.value = extraBoundColors.value.filter((c) => c.id !== v)
  },
})
const extraBoundColorNames = computed(() => extraBoundColors.value.map((c) => c.name).filter(Boolean))

function reloadList() {
  page.value = 1
  void loadProducts()
}

function onPageSizeChange() {
  page.value = 1
  void loadProducts()
}

async function loadProducts() {
  const products: any = await http.get('/own-products', {
    params: {
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim() || undefined,
      sort_by: sortKey.value,
      sort_order: sortOrder.value,
    },
  })
  rows.value = products.data.items
  total.value = products.data.total || 0
  syncSelectionFromRows()
  if (!rows.value.length && page.value > 1 && total.value > 0) {
    page.value = Math.max(1, Math.ceil(total.value / pageSize.value))
    await loadProducts()
  }
}

const selectedCount = computed(() => selectedMap.value.size)

const pageAllSelected = computed(
  () => rows.value.length > 0 && rows.value.every((r) => selectedMap.value.has(r.id)),
)

const pageSomeSelected = computed(
  () =>
    rows.value.some((r) => selectedMap.value.has(r.id)) && !pageAllSelected.value,
)

const batchCustomerLabel = computed(() => {
  if (!batchPartnerId.value) return ''
  const c = customers.value.find((x) => x.id === batchPartnerId.value)
  return c ? c.short_name || c.name || '' : ''
})

function effectiveBatchPartnerId(): number | null {
  return batchPartnerId.value || null
}

function snapshotProduct(row: any) {
  return {
    id: row.id,
    product_code: row.product_code,
    image_url: row.image_url || '',
    colors: Array.isArray(row.colors) ? row.colors.map((c: any) => ({ ...c })) : [],
    quote_price: row.quote_price,
    quotes: Array.isArray(row.quotes) ? row.quotes.map((q: any) => ({ ...q })) : [],
  }
}

function syncSelectionFromRows() {
  if (!selectedMap.value.size) return
  const m = new Map(selectedMap.value)
  for (const row of rows.value) {
    if (m.has(row.id)) m.set(row.id, snapshotProduct(row))
  }
  selectedMap.value = m
}

function isSelected(id: number) {
  return selectedMap.value.has(id)
}

function toggleSelect(row: any, checked: boolean) {
  const m = new Map(selectedMap.value)
  if (checked) m.set(row.id, snapshotProduct(row))
  else m.delete(row.id)
  selectedMap.value = m
}

function togglePageSelect(checked: boolean | string | number) {
  const on = !!checked
  const m = new Map(selectedMap.value)
  for (const row of rows.value) {
    if (on) m.set(row.id, snapshotProduct(row))
    else m.delete(row.id)
  }
  selectedMap.value = m
}

function clearSelection() {
  selectedMap.value = new Map()
}

function enterBatchSelectMode() {
  batchSelectMode.value = true
}

function exitBatchSelectMode() {
  batchSelectMode.value = false
  clearSelection()
}

function colorText(row: any) {
  const names = (row.colors || [])
    .map((c: any) => String(c.name || '').trim())
    .filter(Boolean)
  return names.length ? names.join('、') : '—'
}

function resolveBatchPrice(product: any, partnerId: number | null) {
  if (partnerId != null) {
    const q = (product.quotes || []).find((x: any) => Number(x.partner_id) === Number(partnerId))
    if (q && q.quote_price != null && q.quote_price !== '') {
      return { price: Number(q.quote_price), source: 'customer' as const }
    }
  }
  if (product.quote_price != null && product.quote_price !== '') {
    return { price: Number(product.quote_price), source: 'unified' as const }
  }
  return { price: null, source: 'none' as const }
}

function confirmBatchSelection() {
  if (!selectedCount.value) {
    ElMessage.warning('请先勾选产品')
    return
  }
  if (customers.value.length) {
    batchPartnerId.value = customers.value[0]?.id ?? 0
    batchCustomerVisible.value = true
    return
  }
  batchPartnerId.value = 0
  openBatchQuoteSheet()
}

function confirmBatchCustomer() {
  batchCustomerVisible.value = false
  openBatchQuoteSheet()
}

function openBatchQuoteSheet() {
  const partnerId = effectiveBatchPartnerId()
  const items = Array.from(selectedMap.value.values()).map((p) => {
    const resolved = resolveBatchPrice(p, partnerId)
    return {
      id: p.id,
      product_code: p.product_code,
      image_url: p.image_url,
      color_text: colorText(p),
      fabric: p.fabric || '',
      lining: p.lining || '',
      price: resolved.price,
      price_source: resolved.source,
    }
  })
  batchQuoteRows.value = items
  batchQuoteVisible.value = true
  void ensureCompanyName()
}

async function ensureCompanyName() {
  if (companyName.value) return
  try {
    const res: any = await http.get('/auth/me')
    companyName.value = String(res.data?.tenant_name || '').trim()
  } catch {
    companyName.value = ''
  }
}

async function printBatchQuote() {
  if (!batchQuoteRows.value.length) {
    ElMessage.warning('暂无报价数据')
    return
  }
  await ensureCompanyName()
  const rowsHtml = batchQuoteRows.value
    .map((item, idx) => {
      const img = item.image_url
        ? `<img src="${escapeHtml(item.image_url)}" alt="" />`
        : '<span class="no-img">无图</span>'
      const price =
        item.price != null ? `¥${formatPrice(item.price)}` : '<span class="muted">未报价</span>'
      return `<tr>
        <td class="idx">${idx + 1}</td>
        <td class="img">${img}</td>
        <td class="code">${escapeHtml(item.product_code || '')}</td>
        <td class="color">${escapeHtml(item.color_text || '—')}</td>
        <td class="fabric">${escapeHtml(item.fabric || '—')}</td>
        <td class="lining">${escapeHtml(item.lining || '—')}</td>
        <td class="price">${price}</td>
      </tr>`
    })
    .join('')
  const customerText = batchCustomerLabel.value
    ? `客户：${escapeHtml(batchCustomerLabel.value)}`
    : '统一报价'
  const signCompany = escapeHtml(companyName.value || '—')
  const signDate = formatDate(new Date().toISOString())
  const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title></title>
<style>
  * { box-sizing: border-box; }
  @page { margin: 0; size: auto; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
    color: #111827;
    padding: 16mm;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  h1 { font-size: 20px; margin: 0 0 14px; text-align: center; }
  .customer {
    text-align: left;
    font-size: 16px;
    font-weight: 650;
    color: #111827;
    margin: 0 0 14px;
    line-height: 1.4;
  }
  table { width: 100%; border-collapse: collapse; }
  th, td { border: 1px solid #cbd5e1; padding: 8px 10px; vertical-align: middle; }
  th { background: #0076ff; color: #fff; font-size: 13px; }
  th.idx, td.idx { text-align: center; width: 40px; }
  th.img, td.img { width: 72px; text-align: center; }
  td.img img { width: 56px; height: 56px; object-fit: contain; }
  th.code, td.code { text-align: left; font-weight: 700; }
  th.color, td.color { text-align: left; }
  th.fabric, td.fabric, th.lining, td.lining { text-align: left; }
  th.price, td.price { text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .no-img, .muted { color: #94a3b8; font-size: 12px; }
  .footer { margin-top: 20px; text-align: center; color: #64748b; font-size: 12px; }
  .sign {
    margin-top: 40px;
    text-align: right;
    page-break-inside: avoid;
  }
  .sign .company {
    font-size: 14px;
    font-weight: 650;
    color: #111827;
    line-height: 1.4;
  }
  .sign .date {
    margin-top: 8px;
    font-size: 13px;
    color: #64748b;
    line-height: 1.4;
  }
</style></head><body>
  <h1>产品报价单</h1>
  <div class="customer">${customerText}</div>
  <table>
    <thead><tr>
      <th class="idx">#</th>
      <th class="img">图片</th>
      <th class="code">编号</th>
      <th class="color">颜色</th>
      <th class="fabric">面料</th>
      <th class="lining">内里</th>
      <th class="price">价格</th>
    </tr></thead>
    <tbody>${rowsHtml}</tbody>
  </table>
  <div class="footer">共 ${batchQuoteRows.value.length} 款</div>
  <div class="sign">
    <div class="company">${signCompany}</div>
    <div class="date">${signDate}</div>
  </div>
</body></html>`

  const old = document.getElementById('batch-quote-print-frame')
  if (old) old.remove()

  const iframe = document.createElement('iframe')
  iframe.id = 'batch-quote-print-frame'
  iframe.setAttribute('aria-hidden', 'true')
  iframe.style.cssText =
    'position:fixed;right:0;bottom:0;width:0;height:0;border:0;opacity:0;pointer-events:none;'
  document.body.appendChild(iframe)

  const frameWin = iframe.contentWindow
  const frameDoc = frameWin?.document
  if (!frameWin || !frameDoc) {
    iframe.remove()
    ElMessage.error('无法创建打印预览')
    return
  }

  frameDoc.open()
  frameDoc.write(html)
  frameDoc.close()

  let printed = false
  const doPrint = () => {
    if (printed) return
    printed = true
    try {
      frameWin.focus()
      frameWin.print()
    } finally {
      setTimeout(() => iframe.remove(), 1000)
    }
  }

  const imgs = Array.from(frameDoc.images || [])
  if (!imgs.length) {
    setTimeout(doPrint, 50)
    return
  }
  let left = imgs.length
  const done = () => {
    left -= 1
    if (left <= 0) doPrint()
  }
  imgs.forEach((img) => {
    if (img.complete) done()
    else {
      img.addEventListener('load', done, { once: true })
      img.addEventListener('error', done, { once: true })
    }
  })
  setTimeout(doPrint, 2500)
}

function escapeHtml(s: string) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

async function exportBatchQuote() {
  if (!batchQuoteRows.value.length) return
  batchExporting.value = true
  try {
    const res = await fetch('/api/v1/own-products/batch-quote/export', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${auth.token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        product_ids: batchQuoteRows.value.map((r) => r.id),
        partner_id: effectiveBatchPartnerId(),
      }),
    })
    if (!res.ok) {
      const text = await res.text()
      let msg = '导出失败'
      try {
        const body = JSON.parse(text)
        msg = body.detail || body.error?.message || msg
      } catch {
        /* ignore */
      }
      ElMessage.error(msg)
      return
    }
    const blob = await res.blob()
    const cd = res.headers.get('Content-Disposition') || ''
    let filename = `产品报价单_${batchCustomerLabel.value || '统一报价'}.xlsx`
    const mStar = cd.match(/filename\*=UTF-8''([^;]+)/i)
    const m = cd.match(/filename="?([^";]+)"?/i)
    if (mStar?.[1]) filename = decodeURIComponent(mStar[1])
    else if (m?.[1]) filename = m[1]
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('报价单已导出')
  } finally {
    batchExporting.value = false
  }
}

const previewMaterialCost = computed(() =>
  form.materials.reduce((sum: number, row: any) => sum + lineTotal(row), 0),
)

const previewLaborCost = computed(() =>
  form.labors.reduce((sum: number, row: any) => sum + Number(row.unit_price || 0), 0),
)

const previewOtherCost = computed(() =>
  form.other_costs.reduce((sum: number, row: any) => sum + Number(row.amount || 0), 0),
)

const previewTotalCost = computed(
  () => previewMaterialCost.value + previewLaborCost.value + previewOtherCost.value,
)

const activeProcesses = computed(() =>
  (processes.value || []).filter((p: any) => p.is_active !== false),
)

const activeOtherCostItems = computed(() => {
  const items = (otherCostItems.value || []).filter((x: any) => x.is_active !== false)
  const names = new Set(items.map((x: any) => String(x.name || '').trim()).filter(Boolean))
  // 编辑存量产品时，已用但已停用的项目仍要能显示在当前行
  for (const o of form.other_costs) {
    const n = String(o.name || '').trim()
    if (n && !names.has(n)) {
      items.push({ id: `legacy-${n}`, name: n, is_active: false })
      names.add(n)
    }
  }
  return items
})

const laborProcessOptions = computed(() => {
  const items = [...activeProcesses.value]
  const names = new Set(items.map((p: any) => String(p.name || '').trim()).filter(Boolean))
  for (const l of form.labors) {
    const n = String(l.process_name || '').trim()
    if (n && !names.has(n)) {
      items.push({ id: `legacy-${n}`, name: n, type: l.process_type || 'personal', is_active: false })
      names.add(n)
    }
  }
  return items
})

function formatTime(v?: string) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 19)
}

function formatDate(v?: string) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 10)
}

function formatPrice(v: any, digits = 2) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(digits)
}

function lineTotal(row: any) {
  const qty = Number(row.qty || 0)
  const price = Number(row.unit_price || 0)
  return qty * price
}

function totalCost(row: any) {
  return Number(row.material_cost || 0) + Number(row.labor_cost || 0) + Number(row.other_cost || 0)
}

function supplierProductLabel(sp: any) {
  const parts = [sp.product_code]
  if (sp.name) parts.push(sp.name)
  if (sp.partner_name) parts.push(sp.partner_name)
  if (sp.unit_price != null) parts.push(`¥${formatPrice(sp.unit_price, 1)}`)
  return parts.join(' · ')
}

function spById(id: number) {
  return supplierProducts.value.find((x) => x.id === id)
}

function onMaterialProductChange(row: any) {
  const sp = spById(row.supplier_product_id)
  row.unit_price = sp?.unit_price != null ? Number(sp.unit_price) : 0
  row.image_url = sp?.image_url || ''
  row.color_name = sp?.color_name || ''
  row.pricing_unit_name = sp?.pricing_unit_name || ''
  row.partner_name = sp?.partner_name || ''
  row.supplier_product_code = sp?.product_code || ''
  row.supplier_product_name = sp?.name || ''
  // 分类建议按码：预填 BOM（仍可手改）
  const cat = sp?.category_id
    ? materialCategories.value.find((c: any) => c.id === sp.category_id)
    : null
  if (cat?.suggest_usage_by_size) {
    row.usage_by_size = true
    row.size_usage_table_id =
      cat.default_size_usage_table_id ||
      sizeUsageTables.value.find((t: any) => t.name === '大底通用')?.id ||
      null
  } else {
    row.usage_by_size = false
    row.size_usage_table_id = null
  }
}

function isProcessNameUsed(name: string, current: any) {
  const key = String(name || '').trim().toLowerCase()
  if (!key) return false
  const partKey = current?.part_id ?? null
  return form.labors.some(
    (l: any) =>
      l !== current &&
      (l.part_id ?? null) === partKey &&
      String(l.process_name || '').trim().toLowerCase() === key,
  )
}

function partLabel(partId: number | null | undefined) {
  if (partId == null) return '整鞋段'
  const hit = partDefinitions.value.find((p) => p.id === partId)
  if (hit) return `${hit.code} · ${hit.name}`
  const fromForm = form.parts.find((p: any) => p.part_id === partId)
  return fromForm?.part_name || `部件#${partId}`
}

function isPartUsed(partId: number, current: any) {
  return form.parts.some((p: any) => p !== current && p.part_id === partId)
}

async function loadPartDefinitions() {
  try {
    const res: any = await http.get('/part-definitions', { params: { active_only: true } })
    partDefinitions.value = res.data?.items || []
  } catch {
    partDefinitions.value = []
  }
}

async function onPartQuickShow() {
  newPartName.value = ''
  await nextTick()
  partQuickNameRef.value?.focus?.()
}

function suggestPartCode(name: string) {
  const map: Record<string, string> = {
    前帮: 'QB',
    后帮: 'HB',
    鞋舌: 'SX',
    侧帮: 'CB',
    包头: 'BT',
    护踵: 'HZ',
  }
  if (map[name]) return map[name]
  // 名称首字拼音不够稳时用时间短码，保证必填 code
  return `P${Date.now().toString(36).toUpperCase().slice(-5)}`
}

async function createPartQuick() {
  const name = newPartName.value.trim()
  if (!name) {
    ElMessage.warning('请填写部件名称')
    return
  }
  const code = suggestPartCode(name)
  creatingPart.value = true
  try {
    const res: any = await http.post('/part-definitions', {
      code,
      name,
      source: '裁断',
      is_active: true,
    })
    const p = res.data
    if (!partDefinitions.value.some((x: any) => x.id === p.id)) {
      partDefinitions.value.push(p)
    }
    const empty = form.parts.find((x: any) => !x.part_id)
    if (empty) {
      empty.part_id = p.id
      if (!empty.pieces_per_pair) empty.pieces_per_pair = 1
    } else {
      form.parts.push({ part_id: p.id, pieces_per_pair: 1 })
    }
    partQuickVisible.value = false
    ElMessage.success(`已添加部件「${p.name}」`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '添加失败')
  } finally {
    creatingPart.value = false
  }
}

function addPart() {
  form.parts.push({
    part_id: null,
    pieces_per_pair: 1,
  })
}

function removePartAt(index: number) {
  const removed = form.parts[index]
  form.parts.splice(index, 1)
  const pid = removed?.part_id
  if (pid == null) return
  for (const l of form.labors) {
    if (l.part_id === pid) {
      l.part_id = null
    }
  }
}

function onLaborPartChange(row: any) {
  if (row.part_id != null) {
    row.is_kit_checkpoint = false
  }
}

function onKitCheckpointChange(row: any) {
  if (!row.is_kit_checkpoint) return
  row.part_id = null
  for (const l of form.labors) {
    if (l !== row) l.is_kit_checkpoint = false
  }
}

function isOtherCostNameUsed(name: string, current: any) {
  const key = String(name || '').trim().toLowerCase()
  if (!key) return false
  return form.other_costs.some(
    (o: any) => o !== current && String(o.name || '').trim().toLowerCase() === key,
  )
}

function isCustomerUsed(partnerId: number, current: any) {
  return form.quotes.some((q: any) => q !== current && q.partner_id === partnerId)
}

function addMaterial() {
  form.materials.push({
    supplier_product_id: null,
    qty: 1,
    unit_price: 0,
    image_url: '',
    color_name: '',
    pricing_unit_name: '',
    partner_name: '',
    supplier_product_code: '',
    supplier_product_name: '',
    consume_process_id: null,
    usage_by_size: false,
    size_usage_table_id: null,
    loss_rate_pct: 0,
    loss_fixed_qty: 0,
  })
}

function addLabor() {
  form.labors.push({
    process_name: '',
    process_type: 'personal',
    unit_price: 0,
    part_id: null,
    is_kit_checkpoint: false,
  })
}

function processTypeOfName(name: string) {
  const n = String(name || '').trim()
  const hit = processes.value.find((p) => String(p.name || '').trim() === n)
  return hit?.type === 'group' ? 'group' : 'personal'
}

function onLaborProcessChange(row: any, name: string) {
  row.process_type = processTypeOfName(name)
}

function addOtherCost() {
  form.other_costs.push({
    name: '',
    amount: 0,
  })
}

function addQuote() {
  form.quotes.push({
    partner_id: null,
    quote_price: 0,
  })
}

async function onColorQuickShow() {
  newColorName.value = ''
  await nextTick()
  colorQuickInputRef.value?.focus?.()
}

async function createColorQuick() {
  const name = newColorName.value.trim()
  if (!name) {
    ElMessage.warning('请输入颜色名称')
    return
  }
  creatingColor.value = true
  try {
    const res: any = await http.post('/colors', { name })
    const c = res.data
    const existing = colors.value.find((x) => x.id === c.id)
    if (!existing) colors.value.push(c)
    form.color_ids = [c.id]
    extraBoundColors.value = []
    newColorName.value = ''
    colorQuickVisible.value = false
    ElMessage.success(`已添加颜色「${c.name}」`)
  } finally {
    creatingColor.value = false
  }
}

function genProcessCode() {
  return `P${Date.now().toString(36).toUpperCase()}`
}

async function onProcessQuickShow() {
  newProcessName.value = ''
  newProcessType.value = 'personal'
  await nextTick()
  processQuickInputRef.value?.focus?.()
}

async function createProcessQuick() {
  const name = newProcessName.value.trim()
  if (!name) {
    ElMessage.warning('请输入工序名称')
    return
  }
  creatingProcess.value = true
  try {
    const res: any = await http.post('/processes', {
      name,
      code: genProcessCode(),
      default_price: 0,
      default_days: 1,
      sort_order: processes.value.length,
      type: newProcessType.value,
    })
    const p = res.data
    if (!processes.value.some((x: any) => x.id === p.id)) processes.value.push(p)
    if (!form.labors.some((l: any) => String(l.process_name || '').trim() === p.name)) {
      form.labors.push({
        process_name: p.name,
        process_type: p.type === 'group' ? 'group' : 'personal',
        unit_price: 0,
      })
    }
    processQuickVisible.value = false
    ElMessage.success(`已添加工序「${p.name}」`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '添加失败')
  } finally {
    creatingProcess.value = false
  }
}

async function onOtherCostQuickShow() {
  newOtherCostName.value = ''
  await nextTick()
  otherCostQuickInputRef.value?.focus?.()
}

async function createOtherCostQuick() {
  const name = newOtherCostName.value.trim()
  if (!name) {
    ElMessage.warning('请输入项目名称')
    return
  }
  creatingOtherCost.value = true
  try {
    const res: any = await http.post('/other-cost-items', {
      name,
      sort_order: otherCostItems.value.length,
      is_active: true,
    })
    const item = res.data
    if (!otherCostItems.value.some((x: any) => x.id === item.id)) otherCostItems.value.push(item)
    if (!form.other_costs.some((o: any) => String(o.name || '').trim() === item.name)) {
      form.other_costs.push({ name: item.name, amount: 0 })
    }
    otherCostQuickVisible.value = false
    ElMessage.success(`已添加其它成本「${item.name}」`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '添加失败')
  } finally {
    creatingOtherCost.value = false
  }
}

async function load() {
  const [colorRes, spRes, processRes, partnerRes, otherCostRes, sizeTableRes, catRes]: any[] =
    await Promise.all([
      http.get('/colors'),
      http.get('/supplier-products', { params: { active_only: true, page_size: 200 } }),
      http.get('/processes'),
      http.get('/partners', { params: { role: 'customer_brand', active_only: true, page_size: 200 } }),
      http.get('/other-cost-items'),
      http.get('/material-size-usage-tables'),
      http.get('/material-categories', { params: { active_only: true } }),
    ])
  colors.value = colorRes.data.items
  supplierProducts.value = spRes.data.items
  processes.value = processRes.data.items || []
  customers.value = partnerRes.data.items || []
  otherCostItems.value = otherCostRes.data?.items || []
  sizeUsageTables.value = sizeTableRes.data?.items || []
  materialCategories.value = catRes.data?.items || []
  await loadProducts()
}

function startExport(row: { id: number; product_code?: string }) {
  if (!row?.id) {
    ElMessage.warning('请先保存产品后再导出')
    return
  }
  const full = rows.value.find((r) => r.id === row.id) || row
  void exportExcel({ id: row.id, product_code: full.product_code || row.product_code })
}

async function exportExcel(row: { id: number; product_code?: string }) {
  if (!row?.id) {
    ElMessage.warning('请先保存产品后再导出')
    return
  }
  exportingId.value = row.id
  try {
    const res = await fetch(`/api/v1/own-products/${row.id}/export`, {
      headers: { Authorization: `Bearer ${auth.token}` },
    })
    if (!res.ok) {
      const text = await res.text()
      let msg = '导出失败'
      try {
        const body = JSON.parse(text)
        msg = body.detail || body.error?.message || msg
      } catch {
        /* ignore */
      }
      ElMessage.error(msg)
      return
    }
    const blob = await res.blob()
    const cd = res.headers.get('Content-Disposition') || ''
    const code = row.product_code || String(row.id)
    let filename = `产品成本明细_${code}.xlsx`
    const mStar = cd.match(/filename\*=UTF-8''([^;]+)/i)
    const m = cd.match(/filename="?([^";]+)"?/i)
    if (mStar?.[1]) filename = decodeURIComponent(mStar[1])
    else if (m?.[1]) filename = m[1]
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success(`已导出「${code}」`)
  } finally {
    exportingId.value = null
  }
}

async function loadPeerActuals(productId: number) {
  peerActualsLoading.value = true
  peerActuals.value = null
  try {
    const res: any = await http.get(`/own-products/${productId}/peer-actuals`)
    peerActuals.value = res.data || null
  } catch {
    peerActuals.value = {
      available: false,
      empty_reason: '同类实绩暂时无法加载',
      peer_scope_label: '同款出货',
      note: '仅供批价参照，不阻断报价。',
    }
  } finally {
    peerActualsLoading.value = false
  }
}

function formatPeerDeltaPct(v: unknown) {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}%`
}

function formatPeerMargin(v: unknown) {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

function peerShowCostBand(panel: any) {
  if (Number(panel?.sample_size || 0) < 3) return false
  const a = Number(panel?.actual_unit_cost?.p25)
  const b = Number(panel?.actual_unit_cost?.p75)
  if (Number.isNaN(a) || Number.isNaN(b)) return false
  return Math.abs(a - b) >= 0.01
}

function peerShowMarginBand(panel: any) {
  if (Number(panel?.sample_size || 0) < 3) return false
  const a = Number(panel?.actual_gross_margin?.p25)
  const b = Number(panel?.actual_gross_margin?.p75)
  if (Number.isNaN(a) || Number.isNaN(b)) return false
  return Math.abs(a - b) >= 0.0001
}

function peerVsArchiveText(panel: any) {
  const pct = panel?.delta_vs_card?.median_pct
  if (pct == null || pct === '') return '暂无法和档案成本对比'
  const n = Number(pct)
  if (Number.isNaN(n)) return '暂无法和档案成本对比'
  const thin = Number(panel?.sample_size || 0) <= 1
  const tip = thin ? '（样本较少）' : ''
  if (Math.abs(n) < 3) return `和档案差不多${tip}`
  if (n >= 100) {
    const times = (n / 100 + 1).toFixed(1)
    return `约 ${times} 倍档案，建议按实际留价${tip}`
  }
  if (n >= 12) return `比档案贵约 ${n.toFixed(0)}%，建议留余量${tip}`
  if (n > 0) return `比档案贵约 ${n.toFixed(0)}%${tip}`
  if (n <= -50) return `明显低于档案${tip}`
  return `比档案便宜约 ${Math.abs(n).toFixed(0)}%${tip}`
}

function peerVsArchiveShort(panel: any) {
  const pct = panel?.delta_vs_card?.median_pct
  if (pct == null || pct === '') return '暂无法对比'
  const n = Number(pct)
  if (Number.isNaN(n)) return '暂无法对比'
  if (Math.abs(n) < 3) return '与档案接近'
  if (n >= 100) return `约档案 ${(n / 100 + 1).toFixed(1)} 倍`
  if (n > 0) return `比档案贵约 ${n.toFixed(0)}%`
  return `比档案便宜约 ${Math.abs(n).toFixed(0)}%`
}

function openDetail(row: any) {
  detailRow.value = row
  detailVisible.value = true
  void loadPeerActuals(row.id)
}

function onEditDialogOpened() {
  relayoutQuotes()
  relayoutMaterials()
  relayoutLabors()
  relayoutOverhead()
}

function onDetailDialogOpened() {
  relayoutDetailMaterials()
  relayoutDetailLabors()
  relayoutDetailOverhead()
}

function editFromDetail() {
  const row = detailRow.value
  if (!row) return
  detailVisible.value = false
  openForm(row)
}

function suggestCopyCode(code: string): string {
  const base = String(code || '').trim()
  if (!base) return ''
  const m = base.match(/^(.*)-副本(\d+)?$/)
  if (!m) return `${base}-副本`
  const stem = m[1]
  const n = m[2] ? Number(m[2]) : 1
  return `${stem}-副本${n + 1}`
}

function fillFormFromRow(row: any, opts?: { asCopy?: boolean }) {
  const asCopy = !!opts?.asCopy
  const boundIds = [...(row.color_ids || [])]
  const firstColorId = boundIds[0] ?? null
  extraBoundColors.value = asCopy
    ? []
    : (row.colors || []).filter((c: any) => c.id && c.id !== firstColorId)
  Object.assign(form, {
    id: asCopy ? null : row.id,
    product_code: asCopy ? suggestCopyCode(row.product_code) : row.product_code,
    image_url: row.image_url || '',
    fabric: row.fabric || '',
    lining: row.lining || '',
    color_ids: firstColorId ? [firstColorId] : [],
    parts: (row.parts || []).map((p: any) => ({
      part_id: p.part_id,
      part_name: p.part_name || '',
      pieces_per_pair: Number(p.pieces_per_pair || 1),
    })),
    materials: (row.materials || []).map((m: any) => ({
      supplier_product_id: m.supplier_product_id,
      qty: Number(m.qty || 0),
      unit_price: Number(m.unit_price || 0),
      image_url: m.image_url || '',
      color_name: m.color_name || '',
      pricing_unit_name: m.pricing_unit_name || '',
      partner_name: m.partner_name || '',
      supplier_product_code: m.supplier_product_code || '',
      supplier_product_name: m.supplier_product_name || '',
      consume_process_id: m.consume_process_id ?? null,
      usage_by_size: !!m.usage_by_size,
      size_usage_table_id: m.size_usage_table_id ?? null,
      loss_rate_pct:
        m.loss_rate_pct != null
          ? Number(m.loss_rate_pct || 0)
          : Number(m.loss_rate || 0) * 100,
      loss_fixed_qty: Number(m.loss_fixed_qty || 0),
    })),
    labors: (row.labors || []).map((l: any) => ({
      process_name: l.process_name || '',
      process_type: l.process_type === 'group' ? 'group' : 'personal',
      unit_price: Number(l.unit_price || 0),
      part_id: l.part_id ?? null,
      is_kit_checkpoint: !!l.is_kit_checkpoint,
    })),
    other_costs: (row.other_costs || []).map((o: any) => ({
      name: o.name || '',
      amount: Number(o.amount || 0),
    })),
    quotes: (row.quotes || []).map((q: any) => ({
      partner_id: q.partner_id,
      quote_price: Number(q.quote_price || 0),
    })),
    quote_price: row.quote_price != null && row.quote_price !== '' ? Number(row.quote_price) : null,
    order_qty: asCopy ? 0 : Number(row.order_qty || 0),
    trace_enabled: !!row.trace_enabled,
  })
  syncLaborsToOpenOrders.value = false
  isCopying.value = asCopy
  if (asCopy) {
    peerActuals.value = null
  } else {
    void loadPeerActuals(row.id)
  }
}

function openFormAsCopy(row: any) {
  fillFormFromRow(row, { asCopy: true })
  visible.value = true
  ElMessage.success('已复制，请修改编号与颜色后保存')
}

function copyFromDetail() {
  const row = detailRow.value
  if (!row) return
  detailVisible.value = false
  openFormAsCopy(row)
}

function copyFromEdit() {
  if (!form.id) return
  openFormAsCopy({
    id: form.id,
    product_code: form.product_code,
    image_url: form.image_url,
    fabric: form.fabric,
    lining: form.lining,
    color_ids: [...(form.color_ids || [])],
    parts: (form.parts || []).map((p: any) => ({ ...p })),
    materials: (form.materials || []).map((m: any) => ({ ...m })),
    labors: (form.labors || []).map((l: any) => ({ ...l })),
    other_costs: (form.other_costs || []).map((o: any) => ({ ...o })),
    quotes: (form.quotes || []).map((q: any) => ({ ...q })),
    quote_price: form.quote_price,
    order_qty: form.order_qty,
    trace_enabled: form.trace_enabled,
  })
}

function openForm(row?: any) {
  void loadPartDefinitions()
  if (row) {
    fillFormFromRow(row)
  } else {
    Object.assign(form, {
      id: null,
      product_code: '',
      image_url: '',
      fabric: '',
      lining: '',
      color_ids: [],
      parts: [],
      materials: [],
      labors: [],
      other_costs: [],
      quotes: [],
      quote_price: null,
      order_qty: 0,
      trace_enabled: false,
    })
    extraBoundColors.value = []
    syncLaborsToOpenOrders.value = false
    isCopying.value = false
    peerActuals.value = null
  }
  visible.value = true
}

async function uploadImageFile(file: File) {
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('请选择图片文件')
    return
  }
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res: any = await http.post('/supplier-products/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    form.image_url = res.data.url
    ElMessage.success('图片已上传')
  } catch {
    ElMessage.error('图片上传失败')
  } finally {
    uploading.value = false
  }
}

function pickImageFromDataTransfer(dt: DataTransfer | null): File | null {
  if (!dt) return null
  const files = Array.from(dt.files || [])
  const img = files.find((f) => f.type.startsWith('image/'))
  if (img) return img
  const items = Array.from(dt.items || [])
  for (const item of items) {
    if (item.kind === 'file' && item.type.startsWith('image/')) {
      const f = item.getAsFile()
      if (f) return f
    }
  }
  return null
}

function onImageDragEnter() {
  imageDragDepth.value += 1
  imageDragging.value = true
}

function onImageDragOver() {
  imageDragging.value = true
}

function onImageDragLeave() {
  imageDragDepth.value = Math.max(0, imageDragDepth.value - 1)
  if (imageDragDepth.value === 0) imageDragging.value = false
}

function onImageDrop(e: DragEvent) {
  imageDragDepth.value = 0
  imageDragging.value = false
  const file = pickImageFromDataTransfer(e.dataTransfer)
  if (file) void uploadImageFile(file)
  else ElMessage.warning('请拖入图片文件')
}

function onImagePaste(e: ClipboardEvent) {
  const file = pickImageFromDataTransfer(e.clipboardData as unknown as DataTransfer)
  if (file) {
    e.preventDefault()
    void uploadImageFile(file)
  }
}

function onImageZoneClick() {
  if (uploading.value) return
  imageFileInputRef.value?.click()
}

function onImageFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) void uploadImageFile(file)
}

function onGlobalPaste(e: ClipboardEvent) {
  if (!visible.value || uploading.value) return
  const target = e.target as HTMLElement | null
  if (target) {
    const tag = target.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable) return
  }
  const file = pickImageFromDataTransfer(e.clipboardData as unknown as DataTransfer)
  if (file) {
    e.preventDefault()
    void uploadImageFile(file)
  }
}

watch(visible, (open) => {
  if (open) {
    imageDragging.value = false
    imageDragDepth.value = 0
    window.addEventListener('paste', onGlobalPaste)
  } else {
    window.removeEventListener('paste', onGlobalPaste)
  }
})

onUnmounted(() => {
  window.removeEventListener('paste', onGlobalPaste)
})

async function save() {
  if (!form.product_code.trim()) {
    ElMessage.warning('请填写产品编号')
    return
  }
  if (!form.color_ids.length) {
    ElMessage.warning('请选择成品颜色')
    return
  }
  const materials = form.materials.filter((m: any) => m.supplier_product_id)
  if (materials.some((m: any) => !(Number(m.qty) >= 0))) {
    ElMessage.warning('请检查物料用量')
    return
  }
  const labors = form.labors
    .map((l: any) => ({
      ...l,
      process_name: String(l.process_name || '').trim(),
    }))
    .filter((l: any) => l.process_name)
  if (labors.some((l: any) => !(Number(l.unit_price) >= 0))) {
    ElMessage.warning('请检查工序价格')
    return
  }
  const processKeys = labors.map(
    (l: any) => `${l.part_id ?? 0}:${String(l.process_name || '').toLowerCase()}`,
  )
  if (new Set(processKeys).size !== processKeys.length) {
    ElMessage.warning('同一部件（或整鞋段）下工序不能重复')
    return
  }
  const kitCount = labors.filter((l: any) => l.is_kit_checkpoint).length
  if (kitCount > 1) {
    ElMessage.warning('齐套检查点最多只能勾选一个')
    return
  }
  if (labors.some((l: any) => l.is_kit_checkpoint && l.part_id != null)) {
    ElMessage.warning('齐套检查点须落在整鞋段')
    return
  }
  if ((form.parts || []).some((p: any) => !p.part_id)) {
    ElMessage.warning('请选择部件或删除空行')
    return
  }
  const otherCosts = form.other_costs
    .map((o: any) => ({
      ...o,
      name: String(o.name || '').trim(),
    }))
    .filter((o: any) => o.name)
  if (otherCosts.some((o: any) => !(Number(o.amount) >= 0))) {
    ElMessage.warning('请检查其它成本金额')
    return
  }
  const otherNames = otherCosts.map((o: any) => o.name.toLowerCase())
  if (new Set(otherNames).size !== otherNames.length) {
    ElMessage.warning('同一其它成本项目不能重复添加')
    return
  }
  const quotes = form.quotes.filter((q: any) => q.partner_id)
  if (quotes.some((q: any) => !(Number(q.quote_price) >= 0))) {
    ElMessage.warning('请检查客户报价')
    return
  }
  const partnerIds = quotes.map((q: any) => q.partner_id)
  if (new Set(partnerIds).size !== partnerIds.length) {
    ElMessage.warning('同一客户不能重复报价')
    return
  }
  if (form.id) {
    const origin = rows.value.find((r) => r.id === form.id)
    const priceChanges: string[] = []
    for (const l of labors) {
      const old = (origin?.labors || []).find(
        (x: any) => String(x.process_name || '').trim() === l.process_name,
      )
      if (!old) continue
      const before = Number(old.unit_price || 0)
      const after = Number(l.unit_price || 0)
      if (Math.abs(before - after) > 1e-9) {
        priceChanges.push(`${l.process_name}：¥${before.toFixed(2)} → ¥${after.toFixed(2)}`)
      }
    }
    if (priceChanges.length) {
      try {
        await ElMessageBox.confirm(
          `工序改价只影响之后的新报工；已报工按当时锁价计薪，不会跟着变。\n\n${priceChanges.join('\n')}`,
          '确认改价',
          { type: 'warning', confirmButtonText: '确认保存', cancelButtonText: '取消' },
        )
      } catch {
        return
      }
    }
  }
  saving.value = true
  try {
    const payload = {
      product_code: form.product_code.trim(),
      image_url: form.image_url || null,
      fabric: form.fabric?.trim() || null,
      lining: form.lining?.trim() || null,
      color_ids: form.color_ids || [],
      parts: (form.parts || [])
        .filter((p: any) => p.part_id)
        .map((p: any, i: number) => ({
          part_id: p.part_id,
          pieces_per_pair: Math.max(1, Number(p.pieces_per_pair || 1)),
          sort_order: i,
        })),
      materials: materials.map((m: any, i: number) => ({
        supplier_product_id: m.supplier_product_id,
        qty: m.qty ?? 0,
        sort_order: i,
        consume_process_id: m.consume_process_id || null,
        usage_by_size: !!m.usage_by_size,
        size_usage_table_id: m.usage_by_size ? m.size_usage_table_id || null : null,
        loss_rate: Math.max(0, Number(m.loss_rate_pct || 0) / 100),
        loss_fixed_qty: Math.max(0, Number(m.loss_fixed_qty || 0)),
      })),
      labors: labors.map((l: any, i: number) => ({
        process_name: l.process_name,
        process_type: l.process_type === 'group' ? 'group' : 'personal',
        unit_price: l.unit_price ?? 0,
        sort_order: i,
        part_id: l.part_id ?? null,
        is_kit_checkpoint: !!l.is_kit_checkpoint,
      })),
      other_costs: otherCosts.map((o: any, i: number) => ({
        name: o.name,
        amount: o.amount ?? 0,
        sort_order: i,
      })),
      quotes: quotes.map((q: any, i: number) => ({
        partner_id: q.partner_id,
        quote_price: q.quote_price ?? 0,
        sort_order: i,
      })),
      quote_price: form.quote_price != null && form.quote_price !== '' ? form.quote_price : null,
      order_qty: form.order_qty ?? 0,
      trace_enabled: !!form.trace_enabled,
      sync_labors_to_open_orders: form.id ? !!syncLaborsToOpenOrders.value : false,
    }
    if (form.id) {
      await http.patch(`/own-products/${form.id}`, payload)
    } else {
      await http.post('/own-products', payload)
    }
    ElMessage.success('已保存')
    visible.value = false
    isCopying.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function remove(row: any) {
  if (!row?.id) return
  try {
    await ElMessageBox.confirm(
      `删除产品「${row.product_code}」？若仍被订单/报工引用将无法删除，可改用停用。`,
      '确认删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await http.delete(`/own-products/${row.id}`, { silent: true })
    ElMessage.success('已删除')
    detailVisible.value = false
    detailRow.value = null
    if (selectedMap.value.has(row.id)) {
      const m = new Map(selectedMap.value)
      m.delete(row.id)
      selectedMap.value = m
    }
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '删除失败')
  }
}

onMounted(() => {
  void load()
  void loadPartDefinitions()
})
</script>

<style scoped>
.own-page {
  --ink: #111827;
  --muted: #6b7280;
  --line: #e5e7eb;
  --panel: #f8fafc;
  --accent: #0076ff;
  --accent-soft: rgba(0, 118, 255, 0.1);
  --card-shadow: 0 8px 28px rgba(15, 23, 42, 0.06);
}

.own-toolbar {
  flex-shrink: 0;
  margin-bottom: 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.own-toolbar-left,
.own-toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.own-sort-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 有分页时内容区 overflow:hidden，画廊需内部滚动，分页贴底 */
.gallery-scroll-host {
  flex: 1 1 auto;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

.search-input {
  width: 260px;
}

.search-input :deep(.el-input__wrapper) {
  border-radius: 10px;
  box-shadow: 0 0 0 1px var(--line) inset;
}

.search-icon {
  color: #94a3b8;
}

.add-btn {
  border-radius: 10px;
  padding: 10px 18px;
}

.copy-hint {
  margin-bottom: 12px;
}

.product-gallery {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  column-gap: 16px;
  row-gap: 22px;
}

.gallery-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0;
  min-width: 0;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
  animation: card-in 0.35s ease both;
  animation-delay: var(--delay, 0ms);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.gallery-card:hover {
  border-color: #80baff;
  box-shadow: 0 10px 28px rgba(0, 118, 255, 0.1);
  transform: translateY(-2px);
}

.gallery-card.is-selected {
  border-color: #0076ff;
  box-shadow: 0 0 0 2px rgba(0, 118, 255, 0.18);
}

.gallery-card.is-selected .gallery-image-btn {
  border-color: transparent;
  box-shadow: none;
}

.gallery-check {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.12);
  cursor: pointer;
}

.gallery-check :deep(.el-checkbox) {
  height: auto;
}

.gallery-image-btn {
  position: relative;
  display: block;
  width: 100%;
  aspect-ratio: 1;
  padding: 0;
  border: 0;
  border-bottom: 1px solid var(--line);
  border-radius: 0;
  background:
    linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
  overflow: hidden;
  cursor: pointer;
}

.gallery-image-veil {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(17, 24, 39, 0.42);
  color: #fff;
  font-size: 13px;
  font-weight: 650;
  opacity: 0;
  transition: opacity 0.2s ease;
  pointer-events: none;
}

.gallery-card:hover .gallery-image-veil {
  opacity: 1;
}

.gallery-image {
  width: 100%;
  height: 100%;
}

.gallery-image-empty {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  font-size: 13px;
  background:
    linear-gradient(135deg, rgba(0, 118, 255, 0.04), transparent 55%),
    var(--panel);
}

.gallery-text {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 12px 14px;
  min-width: 0;
}

.gallery-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.gallery-code {
  min-width: 0;
  font-size: 14px;
  font-weight: 750;
  color: var(--ink);
  letter-spacing: 0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.25;
}

.gallery-cost {
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 750;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}

.gallery-colors {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-height: 20px;
}

.gallery-color-chip {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 7px;
  border-radius: 999px;
  font-size: 11px;
  color: #0369a1;
  background: #e8f3ff;
  border: 1px solid #cce4ff;
}

.gallery-color-chip.is-missing {
  color: #b45309;
  background: #fff7ed;
  border-color: #fed7aa;
}

.gallery-color-more {
  font-size: 11px;
  color: var(--muted);
  line-height: 20px;
}

.gallery-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.gallery-date {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  line-height: 1.25;
  text-align: right;
}

.gallery-qty {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.25;
}

.gallery-qty strong {
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

.gallery-text .muted {
  color: var(--muted);
}

@media (max-width: 1200px) {
  .product-gallery {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .product-gallery {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .product-gallery {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.product-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.product-card {
  display: grid;
  grid-template-columns: minmax(250px, 290px) 1fr;
  gap: 0;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 14px;
  overflow: hidden;
  cursor: pointer;
  opacity: 0;
  transform: translateY(8px);
  animation: card-in 0.45s ease forwards;
  animation-delay: var(--delay, 0ms);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.product-card:hover {
  border-color: #80baff;
  box-shadow: var(--card-shadow);
  transform: translateY(-2px);
}

@keyframes card-in {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.product-card-left {
  padding: 16px;
  border-right: 1px solid var(--line);
  background:
    linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.product-card-image {
  width: 100%;
}

.product-thumb,
.product-thumb-empty {
  width: 100%;
  aspect-ratio: 1;
  border-radius: 12px;
  background: #fff;
  border: 1px solid var(--line);
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
}

.product-thumb-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  font-size: 13px;
  background:
    repeating-linear-gradient(
      -45deg,
      #fff,
      #fff 8px,
      #f1f5f9 8px,
      #f1f5f9 16px
    );
}

.product-thumb :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.product-card-meta {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.meta-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.meta-label {
  flex: 0 0 64px;
  font-size: 12px;
  color: var(--muted);
  line-height: 22px;
}

.product-code {
  flex: 1;
  min-width: 0;
  font-size: 17px;
  font-weight: 750;
  color: var(--ink);
  line-height: 22px;
  letter-spacing: 0.01em;
}

.product-colors {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.color-chip {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 12px;
  color: var(--accent);
  background: var(--accent-soft);
  border: 1px solid rgba(0, 118, 255, 0.16);
}

.meta-row-quotes {
  flex-direction: column;
  gap: 8px;
}

.meta-row-quotes .meta-label {
  flex: none;
  line-height: 1.2;
}

.quote-list {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.quote-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid var(--line);
}

.quote-customer {
  font-size: 13px;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.quote-value {
  color: var(--accent);
  font-size: 14px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.meta-time .product-time {
  flex: 1;
  font-size: 12px;
  color: var(--muted);
  line-height: 22px;
}

.product-card-right {
  padding: 16px 18px 14px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: #fff;
}

.right-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.section-title {
  position: relative;
  padding-left: 10px;
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
}

.section-title::before {
  content: '';
  position: absolute;
  left: 0;
  top: 2px;
  bottom: 2px;
  width: 3px;
  border-radius: 2px;
  background: var(--accent);
}

.section-count {
  font-size: 12px;
  color: var(--muted);
  background: var(--panel);
  border-radius: 999px;
  padding: 2px 9px;
}

.soft-table {
  width: 100%;
  --el-table-border-color: #d0d7e2;
  --el-table-header-bg-color: #f7f9fc;
  --el-table-header-text-color: #64748b;
  --el-table-row-hover-bg-color: #f0f7ff;
  border-radius: 12px;
  overflow: hidden;
  border: none;
  box-shadow:
    0 0 0 1px rgba(15, 23, 42, 0.06),
    0 1px 2px rgba(15, 23, 42, 0.03),
    0 8px 24px rgba(15, 23, 42, 0.04);
}

.soft-table :deep(.el-table__inner-wrapper) {
  width: 100%;
}

.soft-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}

.soft-table :deep(.el-table__header-wrapper) {
  border-bottom: none;
  box-shadow: none !important;
}

.soft-table :deep(th.el-table__cell) {
  background: #f7f9fc !important;
  font-weight: 600;
  color: #64748b;
  font-size: 12px;
  letter-spacing: 0.04em;
  border-bottom: 1px solid #d0d7e2 !important;
  box-shadow: none !important;
}

.soft-table :deep(td.el-table__cell) {
  border-bottom: 1px solid #dce3ed !important;
  box-shadow: none !important;
}

.money {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: var(--ink);
}

.cost-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  padding: 12px;
  border-radius: 12px;
  background:
    linear-gradient(135deg, #f8fafc 0%, #e8f3ff 100%);
  border: 1px solid var(--line);
}

.cost-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 4px 6px;
}

.cost-cell span {
  font-size: 12px;
  color: var(--muted);
}

.cost-cell b {
  font-size: 15px;
  font-weight: 650;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

.cost-total {
  border-radius: 10px;
  background: transparent;
  border: none;
  padding: 8px 10px;
}

.cost-total strong {
  font-size: 17px;
  font-weight: 750;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}

.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 2px;
}

.export-hint {
  margin: 0 0 14px;
  font-size: 13px;
  color: var(--muted);
  line-height: 1.5;
}

.export-customer-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}

.export-customer-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  margin: 0 !important;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  height: auto !important;
}

.export-customer-item :deep(.el-radio__label) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding-left: 8px;
}

.export-customer-name {
  color: var(--ink);
  font-weight: 600;
}

.export-customer-price {
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}

.batch-quote-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-right: 28px;
  width: 100%;
}

.batch-quote-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--ink);
  line-height: 1.3;
}

.batch-quote-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--muted);
}

.batch-quote-actions {
  display: flex;
  flex-shrink: 0;
  gap: 8px;
}

.batch-quote-sheet {
  max-height: min(68vh, 640px);
  overflow: auto;
}

/* 弹窗 teleport 到 body，补齐与 admin.css 边框表一致的左右分隔线 */
.batch-quote-table.el-table--border :deep(.el-table__cell) {
  border-right: 1px solid #dce3ed !important;
}

.batch-quote-thumb {
  width: 52px;
  height: 52px;
  border-radius: 6px;
  border: 1px solid var(--line);
  background: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: zoom-in;
}

.batch-quote-footer {
  margin-top: 18px;
  padding: 8px 0 4px;
  text-align: center;
  font-size: 12px;
  color: var(--muted);
  letter-spacing: 0.02em;
}

.batch-quote-thumb.empty {
  color: var(--muted);
  font-size: 11px;
  cursor: default;
}

.batch-quote-thumb :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.price-tag {
  margin-top: 2px;
  font-size: 11px;
  color: var(--accent);
  font-weight: 500;
}

.price-tag.muted-tag {
  color: var(--muted);
}

.empty-wrap {
  padding: 48px 0 32px;
  border-radius: 12px;
  background: var(--panel);
  border: 1px dashed var(--line);
}

.muted {
  color: var(--muted);
}

.dev-layout {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 16px;
  min-height: 520px;
}

.detail-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-right: 28px;
  width: 100%;
}

.detail-dialog-heading {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.detail-dialog-title {
  font-size: 17px;
  font-weight: 750;
  color: var(--ink);
  line-height: 1.3;
}

.detail-dialog-code {
  font-size: 13px;
  font-weight: 600;
  color: var(--accent);
  background: var(--accent-soft);
  border: 1px solid rgba(0, 118, 255, 0.16);
  border-radius: 999px;
  padding: 2px 10px;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-dialog-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.panel-kicker {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--accent);
  margin-bottom: 12px;
}

.dev-panel {
  border: 1px solid var(--line);
  border-radius: 14px;
  background: #fff;
  padding: 12px;
  min-width: 0;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
}

.shoe-panel {
  background:
    linear-gradient(180deg, #f8fbff 0%, #ffffff 120px);
}

.panel-title {
  font-size: 14px;
  font-weight: 750;
  margin-bottom: 12px;
  color: var(--ink);
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-title::before {
  content: '';
  width: 3px;
  height: 14px;
  border-radius: 2px;
  background: var(--accent);
}

.panel-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
}

.panel-title-row .panel-title {
  margin-bottom: 0;
}

.labor-title {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px dashed var(--line);
}

.cost-summary-line,
.other-cost-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 10px;
  font-size: 13px;
  color: #606266;
}

.cost-summary-line strong {
  font-size: 16px;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

.dialog-total {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 10px;
  background: linear-gradient(135deg, #e8f3ff, #f8fafc);
  border: 1px solid rgba(0, 118, 255, 0.18);
  font-size: 13px;
  color: var(--muted);
}

.dialog-total strong {
  font-size: 20px;
  font-weight: 750;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}

.quote-editor {
  width: 100%;
}

.quote-toolbar {
  margin-bottom: 8px;
}

.quote-hint {
  font-size: 12px;
  color: var(--muted);
}

.quote-form-item :deep(.el-form-item__content) {
  display: block;
  line-height: normal;
}

.shoe-form {
  margin-top: 14px;
}

.edit-total-cost {
  width: 100%;
  min-height: 40px;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 10px;
  background: linear-gradient(135deg, #e8f3ff 0%, #f5faff 100%);
  border: 1px solid #cce4ff;
  line-height: 1.3;
}

.edit-total-label {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}

.edit-total-cost strong {
  font-size: 20px;
  font-weight: 750;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}

.edit-cost-breakdown {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--muted);
}

.color-select-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
}

.color-bind-hint {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.45;
}

.color-bind-warn {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.45;
  color: #b45309;
}

.color-quick-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
  margin-bottom: 8px;
}

.color-quick-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}

.detail-meta {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.detail-meta-row {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 10px;
  align-items: start;
  font-size: 13px;
}

.detail-meta-row > span {
  color: var(--muted);
  font-weight: 600;
  line-height: 1.5;
}

.detail-meta-row > b {
  color: var(--ink);
  font-weight: 650;
  line-height: 1.5;
  word-break: break-all;
}

.detail-meta-row > b.detail-total-cost {
  color: var(--accent);
  font-weight: 750;
  font-variant-numeric: tabular-nums;
}

.detail-meta-quotes {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 4px;
  padding-top: 12px;
  border-top: 1px dashed var(--line);
}

.detail-quotes-heading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  width: 100%;
  color: var(--ink);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.12em;
  line-height: 1.2;
  text-align: center;
}

.detail-quotes-heading::before,
.detail-quotes-heading::after {
  content: '';
  flex: 1;
  max-width: 56px;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--line), transparent);
}

.detail-quotes-heading::before {
  background: linear-gradient(90deg, transparent, rgba(100, 116, 139, 0.45));
}

.detail-quotes-heading::after {
  background: linear-gradient(90deg, rgba(100, 116, 139, 0.45), transparent);
}

.detail-quotes-empty {
  display: block;
  text-align: center;
  color: var(--muted);
  font-weight: 500;
}

.detail-meta-quotes .quote-list {
  gap: 6px;
}

.peer-actuals-panel {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-lighter, #ebeef5);
}

.peer-actuals-empty {
  font-size: 13px;
  line-height: 1.45;
  margin-top: 8px;
}

.peer-rows {
  margin-top: 8px;
  display: grid;
  gap: 8px;
}

.peer-row {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 10px;
  align-items: baseline;
}

.peer-row-label {
  font-size: 12px;
  color: var(--el-text-color-secondary, #909399);
  line-height: 1.4;
}

.peer-row-value {
  font-size: 15px;
  font-weight: 650;
  color: #1f2937;
  line-height: 1.35;
  text-align: right;
  word-break: break-word;
}

.peer-row-value em {
  margin-left: 2px;
  font-style: normal;
  font-size: 12px;
  font-weight: 500;
  color: #94a3b8;
}

.peer-row-value-sub {
  font-size: 15px;
  font-weight: 600;
}

.peer-row-verdict .peer-row-value {
  font-size: 13px;
  font-weight: 600;
}

.peer-row-verdict .peer-row-value.is-pos,
.peer-row-verdict .peer-row-value.is-hot {
  color: #c45656;
}

.peer-row-verdict .peer-row-value.is-neg {
  color: #2f7d4a;
}

.peer-row-meta .peer-row-value {
  font-size: 12px;
  font-weight: 500;
  color: #64748b;
}

.peer-edit-hint {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.45;
}

.shoe-form :deep(.el-form-item) {
  margin-bottom: 14px;
}

.shoe-form :deep(.el-form-item__label) {
  color: #64748b;
  font-weight: 600;
  padding-bottom: 4px !important;
  line-height: 1.3;
}

.shoe-form :deep(.quote-form-item) {
  margin-bottom: 0;
}

.shoe-image-box {
  position: relative;
  width: 100%;
  cursor: pointer;
  outline: none;
  border-radius: 12px;
  transition: transform 0.2s ease;
}

.shoe-image-box:hover .shoe-preview {
  border-color: #80baff;
  box-shadow: 0 8px 22px rgba(0, 118, 255, 0.14);
}

.shoe-image-box:hover .shoe-preview.empty {
  color: #0076ff;
  background:
    repeating-linear-gradient(
      -45deg,
      #f8fbff,
      #f8fbff 8px,
      #eef6ff 8px,
      #eef6ff 16px
    );
}

.shoe-image-box:hover .shoe-hover-hint {
  opacity: 1;
}

.shoe-image-box.is-dragging .shoe-preview {
  border-color: #0076ff;
  box-shadow: 0 0 0 2px rgba(0, 118, 255, 0.25);
}

.shoe-image-box.is-uploading {
  pointer-events: none;
  opacity: 0.75;
}

.shoe-preview {
  width: 100%;
  aspect-ratio: 1;
  border-radius: 12px;
  border: 1px dashed var(--line);
  background: #fff;
  display: block;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease, color 0.2s ease;
}

.shoe-preview.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  font-size: 13px;
  background:
    repeating-linear-gradient(
      -45deg,
      #fff,
      #fff 8px,
      #f1f5f9 8px,
      #f1f5f9 16px
    );
}

.shoe-preview :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.shoe-drop-mask {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: rgba(0, 118, 255, 0.12);
  color: #0076ff;
  font-size: 14px;
  font-weight: 650;
  pointer-events: none;
}

.shoe-hover-hint {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: rgba(17, 24, 39, 0.42);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  opacity: 0;
  transition: opacity 0.2s ease;
  pointer-events: none;
}

.shoe-clear-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 2;
  border: none;
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 12px;
  color: #fff;
  background: rgba(17, 24, 39, 0.65);
  cursor: pointer;
}

.shoe-clear-btn:hover {
  background: rgba(220, 38, 38, 0.85);
}

.shoe-file-input {
  display: none;
}

.materials-panel {
  background: #fff;
}

/* 表内编辑：与订单管理行内编辑一致，收紧控件内边距 */
.materials-panel .soft-table :deep(.el-input__wrapper),
.materials-panel .soft-table :deep(.el-select__wrapper) {
  padding-left: 4px !important;
  padding-right: 4px !important;
}

.materials-panel .soft-table :deep(.el-input__inner) {
  padding-left: 0;
  padding-right: 0;
}

.materials-panel .soft-table :deep(.el-select__wrapper) {
  gap: 2px;
  min-height: 24px;
}

.materials-panel .soft-table :deep(.el-select__suffix) {
  width: 14px;
}

.materials-panel .soft-table :deep(.el-select__caret) {
  font-size: 12px;
}

.materials-panel .soft-table :deep(.el-input-number .el-input__wrapper),
.materials-panel .soft-table :deep(.el-input-number.is-controls-right .el-input__wrapper) {
  padding-left: 4px !important;
  padding-right: 4px !important;
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

:deep(td.mat-image-col .product-thumb) {
  width: 100%;
  aspect-ratio: 1 / 1;
  height: auto;
  display: block;
  margin: 0;
  border-radius: 4px;
  border: none;
  box-shadow: none;
  background: transparent;
}

:deep(td.mat-image-col .product-thumb .el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.mat-image-empty {
  line-height: 1.45;
  display: inline-block;
}

@media (max-width: 1100px) {
  .cost-strip {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 960px) {
  .product-card,
  .dev-layout {
    grid-template-columns: 1fr;
  }

  .product-card-left {
    border-right: none;
    border-bottom: 1px solid var(--line);
  }
}
</style>

<style>
.dev-dialog.el-dialog {
  border-radius: 16px;
  overflow: hidden;
}
.dev-dialog .el-dialog__header {
  margin-right: 0;
  padding: 12px 14px 10px;
  border-bottom: 1px solid #eef2f7;
}
.dev-dialog .el-dialog__body {
  padding: 10px 12px 12px;
  background: #f3f5f8;
}
.dev-dialog .el-dialog__footer {
  padding: 10px 14px 14px;
  border-top: 1px solid #eef2f7;
}
</style>
