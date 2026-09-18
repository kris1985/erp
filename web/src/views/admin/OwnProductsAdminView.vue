<template>
  <div class="own-page">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">产品开发</h1>
        <p class="page-desc">一色一款 · 工序报价 · 物料成本 · 特殊客户/品牌报价</p>
      </div>
    </header>

    <div class="admin-toolbar own-toolbar">
      <div class="own-toolbar-left">
        <el-input
          v-model="keyword"
          clearable
          placeholder="搜索工厂型号"
          class="search-input"
          @clear="reloadList"
          @keyup.enter="reloadList"
        >
          <template #prefix>
            <el-icon class="search-icon"><Search /></el-icon>
          </template>
        </el-input>
        <el-date-picker
          v-model="yearFilter"
          type="year"
          clearable
          value-format="YYYY"
          format="YYYY年"
          placeholder="全部年份"
          class="year-picker"
          @change="reloadList"
        />
        <el-select
          v-model="seasonFilter"
          clearable
          placeholder="全部季节"
          class="season-select"
          @change="reloadList"
        >
          <el-option v-for="item in seasonOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-select
          v-model="shoeLastFilter"
          clearable
          filterable
          placeholder="全部楦型"
          class="shoe-last-select"
          @change="reloadList"
        >
          <el-option
            v-for="sp in shoeLastOptions"
            :key="sp.id"
            :label="shoeLastOptionLabel(sp)"
            :value="sp.id"
          />
        </el-select>
        <el-button v-if="hasFilters" plain @click="resetFilters">重置</el-button>
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
        <el-button v-permission="'btn.own_products.write'" type="primary" class="add-btn" @click="openForm()">新增产品</el-button>
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
              <div class="gallery-title">
                <span class="gallery-code" :title="row.product_code">{{ row.product_code }}</span>
              </div>
              <span class="gallery-cost">
                <template v-if="row.quote_price != null && row.quote_price !== ''">
                  ¥{{ formatPrice(row.quote_price, 1) }}
                </template>
                <template v-else>—</template>
              </span>
            </div>
            <div class="gallery-meta-line">
              <span
                v-if="row.colors?.length"
                class="gallery-color-inline"
                :title="row.colors.map((c) => c.name).join('、')"
              >颜色：{{ row.colors.map((c) => c.name).join('、') }}</span>
              <span v-else class="gallery-color-inline is-missing">颜色：未绑色</span>
              <span>面料：{{ row.fabric || '—' }}</span>
              <span>内里：{{ row.lining || '—' }}</span>
            </div>
            <div class="gallery-meta-line gallery-meta-line--split">
              <span class="gallery-last">楦型：{{ row.shoe_last_name || row.shoe_last_code || '—' }}</span>
              <span class="gallery-year-season">{{ row.product_year ? `${row.product_year}年` : '年份未设置' }}{{ seasonLabel(row.season) }}</span>
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
        <el-empty :description="hasFilters ? '没有符合条件的产品' : '暂无产品，点击右上角新增'" />
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
          </div>
          <div class="detail-dialog-actions">
            <el-button
              v-if="form.id"
              :loading="exportingId === form.id"
              @click="startExport({ id: form.id, product_code: form.product_code })"
            >
              导出 Excel
            </el-button>
            <el-button v-if="form.id" v-permission="'btn.own_products.write'" @click="copyFromEdit">复制为新</el-button>
            <el-button @click="visible = false">取消</el-button>
            <el-button v-permission="'btn.own_products.write'" type="primary" :loading="saving" @click="save">保存</el-button>
          </div>
        </div>
      </template>
      <div class="dev-layout">
        <section class="dev-panel shoe-panel">
          <el-alert
            v-if="isCopying"
            class="copy-hint"
            type="info"
            :closable="false"
            show-icon
            title="已复制物料、工序、成本与报价。请修改编号与颜色后保存（同款不同色常用）。"
          />
          <el-table
            ref="productInfoTableRef"
            border
            :data="productInfoEditRows"
            size="small"
            class="soft-table product-info-table"
            @header-dragend="onHeaderDragendInfo"
          >
            <el-table-column
              column-key="image"
              label="图片"
              :width="colWidthInfo('image', 72)"
              align="center"
              class-name="mat-image-col"
              header-class-name="mat-image-col"
              resizable
            >
              <template #default>
                <div
                  class="shoe-image-box shoe-image-box--table"
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
                    class="product-thumb"
                    :preview-src-list="[form.image_url]"
                    preview-teleported
                    @click.stop
                  />
                  <div v-else class="product-thumb product-thumb--empty">
                    <span>{{ uploading ? '上传中…' : '上传' }}</span>
                  </div>
                  <div v-if="imageDragging" class="shoe-drop-mask">松开</div>
                  <button
                    v-if="form.image_url && !uploading"
                    type="button"
                    class="shoe-clear-btn"
                    @click.stop="form.image_url = ''"
                  >
                    删除
                  </button>
                  <input
                    ref="imageFileInputRef"
                    type="file"
                    class="shoe-file-input"
                    accept="image/jpeg,image/png,image/gif,image/webp"
                    @change="onImageFileChange"
                  />
                </div>
              </template>
            </el-table-column>
            <el-table-column column-key="product_code" label="工厂型号" :width="colWidthInfo('product_code', 120)" resizable>
              <template #default>
                <el-input v-model="form.product_code" size="small" placeholder="如 OP-001" />
              </template>
            </el-table-column>
            <el-table-column column-key="color" label="颜色" :width="colWidthInfo('color', 160)" resizable>
              <template #default>
                <div class="color-select-row">
                  <el-select
                    v-model="formColorId"
                    filterable
                    size="small"
                    style="flex: 1; min-width: 0"
                    placeholder="颜色"
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
                      <el-button link type="primary" size="small" class="color-add-btn" title="新增颜色">
                        +
                      </el-button>
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
              </template>
            </el-table-column>
            <el-table-column column-key="fabric" label="面料" :width="colWidthInfo('fabric', 110)" resizable>
              <template #default>
                <el-input v-model="form.fabric" size="small" placeholder="选填" maxlength="100" />
              </template>
            </el-table-column>
            <el-table-column column-key="lining" label="内里" :width="colWidthInfo('lining', 110)" resizable>
              <template #default>
                <el-input v-model="form.lining" size="small" placeholder="选填" maxlength="100" />
              </template>
            </el-table-column>
            <el-table-column label="楦" align="center">
              <el-table-column column-key="shoe_last" label="型号" :width="colWidthInfo('shoe_last', 140)" resizable>
                <template #default>
                  <el-select
                    v-model="form.shoe_last_id"
                    filterable
                    clearable
                    size="small"
                    style="width: 100%"
                    placeholder="模具楦头"
                  >
                    <el-option
                      v-for="sp in shoeLastOptions"
                      :key="sp.id"
                      :label="shoeLastOptionLabel(sp)"
                      :value="sp.id"
                    />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column
                column-key="shoe_last_hours"
                label="楦头占用时间(小时/双)"
                :width="colWidthInfo('shoe_last_hours', 160)"
                resizable
              >
                <template #default>
                  <el-input-number
                    v-model="form.shoe_last_hours"
                    :min="0"
                    :precision="1"
                    :step="0.5"
                    :controls="false"
                    size="small"
                    style="width: 100%"
                    placeholder="小时"
                  />
                </template>
              </el-table-column>
            </el-table-column>
            <el-table-column column-key="product_year" label="年份" :width="colWidthInfo('product_year', 110)" resizable>
              <template #default>
                <el-date-picker
                  v-model="form.product_year"
                  type="year"
                  value-format="YYYY"
                  format="YYYY年"
                  size="small"
                  style="width: 100%"
                  placeholder="年份"
                />
              </template>
            </el-table-column>
            <el-table-column column-key="season" label="季节" :width="colWidthInfo('season', 100)" resizable>
              <template #default>
                <el-select v-model="form.season" size="small" style="width: 100%" placeholder="季节">
                  <el-option v-for="item in seasonOptions" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column column-key="total_cost" label="总成本" :width="colWidthInfo('total_cost', 120)" align="right" resizable>
              <template #default>
                <strong class="detail-total-cost">¥{{ formatPrice(previewTotalCost) }}</strong>
              </template>
            </el-table-column>
            <el-table-column
              column-key="quote_price"
              label="统一报价"
              :width="colWidthInfo('quote_price', 120)"
              resizable
            >
              <template #default>
                <el-input-number
                  v-model="form.quote_price"
                  :min="0"
                  :precision="2"
                  :step="1"
                  :controls="false"
                  size="small"
                  style="width: 100%"
                  placeholder="报价"
                />
              </template>
            </el-table-column>
          </el-table>
          <p v-if="extraBoundColorNames.length" class="color-bind-warn">
            该工厂型号还绑了{{ extraBoundColorNames.join('、') }}。保存后只保留当前所选色。
          </p>
          <div v-if="form.id && peerActuals" class="peer-edit-hint muted">
            <template v-if="peerActuals.available">
              批价参照：实际 ¥{{ formatPrice(peerActuals.actual_unit_cost?.median) }}/双 ·
              {{ peerVsArchiveShort(peerActuals) }}
            </template>
            <template v-else>
              批价参照：暂无出货记录 · 档案 ¥{{ formatPrice(peerActuals.card_unit_cost) }}/双
            </template>
          </div>

          <div class="quotes-side-by-side">
            <div class="quote-editor product-quotes-block">
              <div class="panel-title-row quote-toolbar">
                <span class="panel-title" style="margin-bottom: 0">特殊客户报价</span>
                <el-button type="primary" size="small" @click="addQuote">添加客户报价</el-button>
              </div>
              <el-table
                ref="quotesTableRef"
                border
                :data="form.quotes"
                size="small"
                class="soft-table"
                empty-text="暂无特殊客户报价"
                @header-dragend="onHeaderDragend"
              >
                <el-table-column
                  column-key="customer"
                  label="客户"
                  :width="colWidth('customer', 120)"
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
                <el-table-column column-key="quote_price" label="报价" :width="colWidth('quote_price', 120)" resizable>
                  <template #default="{ row, $index }">
                    <div class="quote-price-cell">
                      <el-input-number
                        v-model="row.quote_price"
                        :min="0"
                        :precision="2"
                        :step="1"
                        :controls="false"
                        style="width: 100%"
                      />
                      <el-button
                        link
                        type="danger"
                        :icon="Delete"
                        title="删除"
                        @click="form.quotes.splice($index, 1)"
                      />
                    </div>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <div class="quote-editor product-quotes-block">
              <div class="panel-title-row quote-toolbar">
                <span class="panel-title" style="margin-bottom: 0">特殊品牌报价</span>
                <el-button type="primary" size="small" @click="addBrandQuote">添加品牌报价</el-button>
              </div>
              <el-table
                ref="brandQuotesTableRef"
                border
                :data="form.brand_quotes"
                size="small"
                class="soft-table"
                empty-text="暂无特殊品牌报价"
                @header-dragend="onHeaderDragendBrand"
              >
                <el-table-column
                  column-key="brand_name"
                  label="品牌"
                  :width="colWidthBrand('brand_name', 100)"
                  resizable
                >
                  <template #default="{ row }">
                    <el-input
                      v-model="row.brand_name"
                      size="small"
                      maxlength="100"
                      placeholder="品牌名称"
                    />
                  </template>
                </el-table-column>
                <el-table-column column-key="quote_price" label="报价" :width="colWidthBrand('quote_price', 120)" resizable>
                  <template #default="{ row, $index }">
                    <div class="quote-price-cell">
                      <el-input-number
                        v-model="row.quote_price"
                        :min="0"
                        :precision="2"
                        :step="1"
                        :controls="false"
                        style="width: 100%"
                      />
                      <el-button
                        link
                        type="danger"
                        :icon="Delete"
                        title="删除"
                        @click="form.brand_quotes.splice($index, 1)"
                      />
                    </div>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
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
                  :step="0.0001"
                  controls-position="right"
                  size="small"
                  style="width: 100%"
                  @change="(v) => onMaterialQtyChange(row, v)"
                />
              </template>
            </el-table-column>
            <el-table-column column-key="price_unit" label="单位" :width="colWidth1('price_unit', 80)" resizable>
              <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
            </el-table-column>
            <el-table-column column-key="consume_segment" label="消耗部门" :width="colWidth1('consume_segment', 130)" resizable>
              <template #default="{ row }">
                <el-select
                  v-model="row.consume_segment_id"
                  clearable
                  filterable
                  size="small"
                  placeholder="跟分类/首段"
                  style="width: 100%"
                >
                  <el-option v-for="seg in segments" :key="seg.id" :label="seg.name" :value="seg.id" />
                </el-select>
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
        </section>

        <section class="dev-panel labors-panel">
          <div class="panel-title-row">
            <div class="panel-title">工艺路线</div>
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap">
              <el-checkbox v-if="form.id" v-model="syncLaborsToOpenOrders">
                同步到在制生产单
              </el-checkbox>
              <el-button type="primary" size="small" @click="openRouteTemplatePicker">选用模版</el-button>
              <el-button
                type="primary"
                size="small"
                :loading="savingRouteTemplate"
                @click="saveRouteTemplate"
              >
                存为模版
              </el-button>
            </div>
          </div>
          <!-- 工序段重构：工艺路线按段横向排列；参考价选填，未填工序价时按参考价计成本 -->
          <div class="labor-segments">
            <div v-for="seg in laborSegments" :key="seg.key" class="labor-seg-block">
              <div class="labor-seg-head">
                <div class="labor-seg-head-main">
                  <span class="labor-seg-name">{{ segmentDepartmentName(seg.name) }}</span>
                  <template v-if="seg.segmentId != null">
                    <span class="labor-seg-ref-label muted">参考价</span>
                    <el-input-number
                      :model-value="segmentRefPrice(seg.segmentId)"
                      :min="0"
                      :precision="2"
                      :step="0.1"
                      :controls="false"
                      size="small"
                      class="labor-seg-ref-price"
                      placeholder="选填"
                      @update:model-value="(v) => setSegmentRefPrice(seg.segmentId, v)"
                    />
                    <span class="labor-seg-unit muted">元/双</span>
                    <span class="muted labor-seg-sub">
                      小计 ¥{{ formatPrice(segmentEffectiveCost(seg.segmentId)) }}
                    </span>
                  </template>
                </div>
                <el-button link type="primary" size="small" @click="addLaborTo(seg.segmentId)">
                  ＋ 添加工序
                </el-button>
              </div>
              <div v-if="segmentHasProcesses(seg.segmentId)" class="labor-seg-rows">
                <div
                  v-for="row in segmentLabors(seg.segmentId)"
                  :key="row._key"
                  class="labor-seg-row"
                >
                  <div class="labor-seg-row-top">
                    <el-select
                      v-model="row.process_name"
                      filterable
                      size="small"
                      class="labor-seg-process"
                      placeholder="选择工序"
                      @change="(name: string) => onLaborProcessChange(row, name)"
                      @visible-change="(open: boolean) => onLaborProcessSelectVisible(row, open)"
                    >
                      <el-option
                        v-for="p in laborProcessOptionsFor(row)"
                        :key="p.id"
                        :label="p.name"
                        :value="p.name"
                        :disabled="isProcessNameUsed(p.name, row)"
                      />
                      <template #footer>
                        <div class="process-select-footer" @mousedown.stop @click.stop>
                          <template v-if="processQuickRow === row">
                            <el-input
                              ref="processQuickInputRef"
                              v-model="newProcessName"
                              size="small"
                              maxlength="50"
                              placeholder="新工序名称"
                              @keyup.enter="createProcessQuick"
                            />
                            <div class="process-select-footer-row">
                              <el-select v-model="newProcessType" size="small" style="width: 88px">
                                <el-option label="个人" value="personal" />
                                <el-option label="集体" value="group" />
                              </el-select>
                              <el-button size="small" @click="cancelProcessQuick">取消</el-button>
                              <el-button
                                type="primary"
                                size="small"
                                :loading="creatingProcess"
                                @click="createProcessQuick"
                              >
                                添加
                              </el-button>
                            </div>
                          </template>
                          <el-button
                            v-else
                            link
                            type="primary"
                            size="small"
                            @click="startProcessQuickInSelect(row)"
                          >
                            + 新建工序
                          </el-button>
                        </div>
                      </template>
                    </el-select>
                    <div class="labor-seg-price-wrap">
                      <el-input-number
                        v-if="!isHourlyProcess(row)"
                        v-model="row.unit_price"
                        :min="0"
                        :precision="2"
                        :step="0.1"
                        :controls="false"
                        size="small"
                        class="labor-seg-price"
                        placeholder="选填"
                      />
                      <span v-else class="labor-seg-price labor-seg-hourly">计时</span>
                      <el-popover
                        placement="bottom-end"
                        :width="row._pricePopoverWidth || 280"
                        :offset="20"
                        trigger="click"
                        @show="() => loadProcessPriceHistory(row)"
                      >
                        <template #reference>
                          <el-button
                            link
                            type="primary"
                            size="small"
                            class="labor-price-history-btn"
                            :disabled="!String(row.process_name || '').trim()"
                            @mousedown="measurePricePopoverWidth(row)"
                          >
                            历史
                          </el-button>
                        </template>
                        <div v-loading="row._priceHistoryLoading" class="labor-price-history">
                          <div v-if="!(row._priceHistory || []).length" class="muted" style="padding: 8px 0">
                            暂无该工序的改价记录
                          </div>
                          <component
                            :is="isHourlyProcess(row) ? 'div' : 'button'"
                            v-for="item in row._priceHistory || []"
                            :key="item.id"
                            v-bind="isHourlyProcess(row) ? {} : { type: 'button' }"
                            class="labor-price-history-item"
                            :class="{ 'is-readonly': isHourlyProcess(row) }"
                            @click="!isHourlyProcess(row) && applyProcessPrice(row, item.new_price)"
                          >
                            <span class="labor-price-history-price">
                              {{ formatProcessHistoryPrice(item, isHourlyProcess(row)) }}
                            </span>
                            <span class="muted labor-price-history-meta">
                              <template v-if="!isHourlyHistoryZero(item) && item.old_price != null && item.old_price !== ''">
                                原 ¥{{ formatPrice(item.old_price) }} ·
                              </template>
                              {{ item.changed_by_name || '—' }}
                              <template v-if="item.changed_at">
                                · {{ formatHistoryTime(item.changed_at) }}
                              </template>
                            </span>
                          </component>
                        </div>
                      </el-popover>
                    </div>
                    <span class="labor-seg-unit muted">{{ isHourlyProcess(row) ? '计时' : '元/每双' }}</span>
                    <el-button link type="danger" :icon="Delete" title="删除" @click="removeLabor(row)" />
                  </div>
                  <div class="labor-seg-note-wrap" :data-labor-key="row._key">
                    <el-input
                      v-model="row.requirement_note"
                      type="textarea"
                      :rows="2"
                      :autosize="{ minRows: 2, maxRows: 4 }"
                      size="small"
                      placeholder="工艺要求备注"
                      class="labor-seg-note"
                      @input="(val: string) => onRequirementNoteInput(row, val)"
                    />
                    <el-popover
                      placement="bottom-end"
                      :width="row._notePopoverWidth || 280"
                      :offset="20"
                      trigger="click"
                      @show="() => loadRequirementNoteHistory(row)"
                    >
                      <template #reference>
                        <el-button
                          link
                          type="primary"
                          size="small"
                          class="labor-note-history-btn"
                          :disabled="!String(row.process_name || '').trim()"
                          @mousedown="measureNotePopoverWidth(row)"
                        >
                          历史
                        </el-button>
                      </template>
                      <div v-loading="row._noteHistoryLoading" class="labor-note-history">
                        <div v-if="!(row._noteHistory || []).length" class="muted" style="padding: 8px 0">
                          暂无该工序的历史工艺要求
                        </div>
                        <button
                          v-for="(item, idx) in row._noteHistory || []"
                          :key="`${idx}-${item.note}`"
                          type="button"
                          class="labor-note-history-item"
                          @click="applyRequirementNote(row, item.note)"
                        >
                          <span class="labor-note-history-text">{{ item.note }}</span>
                        </button>
                      </div>
                    </el-popover>
                  </div>
                </div>
              </div>
              <div v-else class="labor-seg-empty muted">初期可只填参考价，准备生产时再添加工序</div>
            </div>
          </div>
          <div class="cost-summary-line">
            <span>人工成本</span>
            <strong>¥{{ formatPrice(previewLaborCost) }}</strong>
          </div>
        </section>

        <section class="dev-panel commissions-panel">
          <div class="panel-title-row">
            <div class="panel-title">提成</div>
            <div style="display: flex; align-items: center; gap: 8px">
              <el-popover
                v-model:visible="commissionQuickVisible"
                placement="bottom-end"
                :width="300"
                trigger="click"
                @show="onCommissionQuickShow"
              >
                <template #reference>
                  <el-button type="primary" size="small">新建提成</el-button>
                </template>
                <div class="color-quick">
                  <div class="color-quick-title">添加提成人员（可不选人）</div>
                  <el-select
                    ref="commissionQuickSelectRef"
                    v-model="newCommissionEmployeeId"
                    filterable
                    clearable
                    :teleported="false"
                    style="width: 100%"
                    placeholder="选择人员，可不选"
                  >
                    <el-option
                      v-for="e in commissionQuickEmployeeOptions"
                      :key="e.id"
                      :label="e.mobile ? `${e.name}（${e.mobile}）` : e.name"
                      :value="e.id"
                    />
                  </el-select>
                  <div class="color-quick-actions">
                    <el-button size="small" @click="commissionQuickVisible = false">取消</el-button>
                    <el-button type="primary" size="small" @click="addCommissionQuick">
                      添加
                    </el-button>
                  </div>
                </div>
              </el-popover>
            </div>
          </div>
          <el-table
            border
            :data="commissionOneRow"
            size="small"
            class="soft-table other-cost-one-row-table"
            :key="`cm-edit-${commissionColumns.map((x) => x.key).join('|')}`"
          >
            <el-table-column
              v-for="item in commissionColumns"
              :key="item.key"
              :column-key="`cm-${item.key}`"
              :label="item.label"
              min-width="120"
              align="center"
              show-overflow-tooltip
            >
              <template #default>
                <el-input-number
                  :model-value="commissionAmount(item.key)"
                  :min="0"
                  :precision="2"
                  :step="0.1"
                  :controls="false"
                  size="small"
                  class="other-cost-amount-input"
                  placeholder="选填"
                  @update:model-value="(v) => setCommissionAmount(item.key, v)"
                />
              </template>
            </el-table-column>
            <el-table-column
              v-if="!commissionColumns.length"
              column-key="cm-empty"
              label="暂无提成项目"
              min-width="200"
            >
              <template #default>
                <span class="muted">请先「新建提成」选择人员</span>
              </template>
            </el-table-column>
          </el-table>
          <div class="cost-summary-line">
            <span>提成</span>
            <strong>¥{{ formatPrice(previewCommissionCost) }}</strong>
          </div>
        </section>

        <section class="dev-panel other-costs-panel">
          <div class="panel-title-row">
            <div class="panel-title">其它成本</div>
            <div style="display: flex; align-items: center; gap: 8px">
              <el-popover
                v-model:visible="otherCostQuickVisible"
                placement="bottom-end"
                :width="280"
                trigger="click"
                @show="onOtherCostQuickShow"
              >
                <template #reference>
                  <el-button type="primary" size="small">新建其它成本</el-button>
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
            border
            :data="otherCostOneRow"
            size="small"
            class="soft-table other-cost-one-row-table"
            :key="`oc-edit-${otherCostColumns.map((x) => x.name).join('|')}`"
          >
            <el-table-column
              v-for="item in otherCostColumns"
              :key="item.name"
              :column-key="`oc-${item.name}`"
              :label="item.name"
              min-width="120"
              align="center"
              show-overflow-tooltip
            >
              <template #default>
                <el-input-number
                  :model-value="otherCostAmount(item.name)"
                  :min="0"
                  :precision="2"
                  :step="0.1"
                  :controls="false"
                  size="small"
                  class="other-cost-amount-input"
                  placeholder="选填"
                  @update:model-value="(v) => setOtherCostAmount(item.name, v)"
                />
              </template>
            </el-table-column>
            <el-table-column
              v-if="!otherCostColumns.length"
              column-key="oc-empty"
              label="暂无其它成本项目"
              min-width="200"
            >
              <template #default>
                <span class="muted">请先「新建其它成本」写入基础资料</span>
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
          </div>
          <div v-if="detailRow" class="detail-dialog-actions">
            <el-button :loading="versionsLoading" @click="openProductVersionList">修改记录</el-button>
            <el-button
              size="default"
              :loading="exportingId === detailRow.id"
              @click="startExport(detailRow)"
            >
              导出 Excel
            </el-button>
            <el-button v-permission="'btn.own_products.write'" @click="copyFromDetail">复制</el-button>
            <el-button v-permission="'btn.own_products.write'" type="danger" plain @click="remove(detailRow)">删除</el-button>
            <el-button v-permission="'btn.own_products.write'" type="primary" @click="editFromDetail">编辑</el-button>
          </div>
        </div>
      </template>
      <div v-if="detailRow" class="dev-layout">
        <section class="dev-panel shoe-panel">
          <el-table
            ref="detailProductInfoTableRef"
            border
            :data="productInfoDetailRows"
            size="small"
            class="soft-table product-info-table"
            @header-dragend="onHeaderDragendInfoDetail"
          >
            <el-table-column
              column-key="image"
              label="图片"
              :width="colWidthInfoDetail('image', 72)"
              align="center"
              class-name="mat-image-col"
              header-class-name="mat-image-col"
              resizable
            >
              <template #default>
                <el-image
                  v-if="detailRow.image_url"
                  :src="detailRow.image_url"
                  fit="contain"
                  class="product-thumb"
                  :preview-src-list="[detailRow.image_url]"
                  preview-teleported
                />
                <span v-else class="muted mat-image-empty"></span>
              </template>
            </el-table-column>
            <el-table-column column-key="product_code" label="工厂型号" :width="colWidthInfoDetail('product_code', 120)" show-overflow-tooltip resizable>
              <template #default>{{ detailRow.product_code }}</template>
            </el-table-column>
            <el-table-column column-key="color" label="颜色" :width="colWidthInfoDetail('color', 100)" show-overflow-tooltip resizable>
              <template #default>
                {{
                  detailRow.colors?.length
                    ? detailRow.colors.map((c) => c.name).join('、')
                    : '未绑颜色'
                }}
              </template>
            </el-table-column>
            <el-table-column column-key="fabric" label="面料" :width="colWidthInfoDetail('fabric', 100)" show-overflow-tooltip resizable>
              <template #default>{{ detailRow.fabric || '—' }}</template>
            </el-table-column>
            <el-table-column column-key="lining" label="内里" :width="colWidthInfoDetail('lining', 100)" show-overflow-tooltip resizable>
              <template #default>{{ detailRow.lining || '—' }}</template>
            </el-table-column>
            <el-table-column label="楦" align="center">
              <el-table-column column-key="shoe_last" label="型号" :width="colWidthInfoDetail('shoe_last', 120)" show-overflow-tooltip resizable>
                <template #default>
                  {{
                    detailRow.shoe_last_name
                      || detailRow.shoe_last_code
                      || '—'
                  }}
                </template>
              </el-table-column>
              <el-table-column
                column-key="shoe_last_hours"
                label="楦头占用时间(小时/双)"
                :width="colWidthInfoDetail('shoe_last_hours', 160)"
                align="right"
                resizable
              >
                <template #default>
                  {{
                    detailRow.shoe_last_hours != null && detailRow.shoe_last_hours !== ''
                      ? Number(detailRow.shoe_last_hours).toFixed(1)
                      : '—'
                  }}
                </template>
              </el-table-column>
            </el-table-column>
            <el-table-column column-key="product_year" label="年份" :width="colWidthInfoDetail('product_year', 88)" resizable>
              <template #default>{{ detailRow.product_year ? `${detailRow.product_year}年` : '—' }}</template>
            </el-table-column>
            <el-table-column column-key="season" label="季节" :width="colWidthInfoDetail('season', 80)" resizable>
              <template #default>{{ seasonLabel(detailRow.season) }}</template>
            </el-table-column>
            <el-table-column column-key="total_cost" label="总成本" :width="colWidthInfoDetail('total_cost', 100)" align="right" resizable>
              <template #default>
                <b class="detail-total-cost">¥{{ formatPrice(totalCost(detailRow)) }}</b>
              </template>
            </el-table-column>
            <el-table-column column-key="quote_price" label="统一报价" :width="colWidthInfoDetail('quote_price', 100)" align="right" resizable>
              <template #default>
                {{
                  detailRow.quote_price != null && detailRow.quote_price !== ''
                    ? `¥${formatPrice(detailRow.quote_price)}`
                    : '—'
                }}
              </template>
            </el-table-column>
          </el-table>

          <div class="quotes-side-by-side">
            <div class="product-quotes-block">
              <div class="panel-title-row quote-toolbar">
                <span class="panel-title" style="margin-bottom: 0">特殊客户报价</span>
              </div>
              <div v-if="detailRow.quotes?.length" class="quote-list">
                <div v-for="q in detailRow.quotes" :key="q.id" class="quote-item">
                  <span class="quote-customer">{{ q.partner_short_name || q.partner_name }}</span>
                  <strong class="quote-value">¥{{ formatPrice(q.quote_price) }}</strong>
                </div>
              </div>
              <div v-else class="muted">暂无特殊客户报价</div>
            </div>
            <div class="product-quotes-block">
              <div class="panel-title-row quote-toolbar">
                <span class="panel-title" style="margin-bottom: 0">特殊品牌报价</span>
              </div>
              <div v-if="detailRow.brand_quotes?.length" class="quote-list">
                <div v-for="q in detailRow.brand_quotes" :key="q.id" class="quote-item">
                  <span class="quote-customer">{{ q.brand_name }}</span>
                  <strong class="quote-value">¥{{ formatPrice(q.quote_price) }}</strong>
                </div>
              </div>
              <div v-else class="muted">暂无特殊品牌报价</div>
            </div>
          </div>

          <section
            v-if="peerActuals?.available"
            class="peer-actuals-panel"
            aria-label="批价参照"
          >
            <div class="panel-title-row">
              <div class="panel-title">批价参照</div>
              <span class="section-count">估算</span>
            </div>
            <div class="peer-actuals-body">
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
            <el-table-column column-key="consume_segment" label="消耗部门" :width="colWidth4('consume_segment', 110)" resizable>
              <template #default="{ row: m }">
                <span v-if="m.consume_segment_name">{{ m.consume_segment_name }}</span>
                <span v-else class="muted">未标注</span>
              </template>
            </el-table-column>
            <el-table-column column-key="unit_price" label="单价" :width="colWidth4('unit_price', 80)" align="right" resizable>
              <template #default="{ row: m }">{{ formatPrice(m.unit_price, 1) }}</template>
            </el-table-column>
            <el-table-column column-key="qty" label="用量" :width="colWidth4('qty', 70)" align="right" resizable>
              <template #default="{ row: m }">{{ formatQty(m.qty) }}</template>
            </el-table-column>
            <el-table-column column-key="unit" label="单位" :width="colWidth4('unit', 72)" resizable>
              <template #default="{ row: m }">{{ m.pricing_unit_name || '—' }}</template>
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
        </section>

        <section class="dev-panel labors-panel">
          <div class="panel-title-row">
            <div class="panel-title">工艺路线</div>
            <span class="section-count">{{ (detailRow.labors || []).length }} 道工序</span>
          </div>
          <!-- 工序段重构（19.9）：工艺路线按段分组展示 -->
          <div class="detail-labor-groups">
            <div v-for="g in detailLaborGroups" :key="g.key" class="detail-labor-group">
              <div class="detail-labor-group-head">
                <span class="detail-labor-group-name">{{ segmentDepartmentName(g.name) }}</span>
                <div class="detail-labor-group-meta muted">
                  <span>参考价 ¥{{ formatPrice(g.refPrice) }}</span>
                  <span>小计 ¥{{ formatPrice(g.effectiveCost) }}</span>
                </div>
              </div>
              <div
                v-for="l in g.items"
                :key="l.id ?? l.process_name"
                class="detail-labor-row"
              >
                <div class="detail-labor-line">
                  <span class="detail-labor-name">{{ l.process_name || '—' }}</span>
                  <span v-if="isHourlyLabor(l)" class="money">计时</span>
                  <span v-else class="money">¥{{ formatPrice(l.unit_price) }}</span>
                  <el-tooltip
                    v-if="laborHasPriceHistory(l)"
                    placement="top"
                    :show-after="120"
                    effect="light"
                    popper-class="detail-price-history-popper"
                  >
                    <template #content>
                      <div class="detail-price-history-tip">
                        <div class="detail-price-history-tip-title">改价记录</div>
                        <div
                          v-for="item in laborPriceHistory(l)"
                          :key="item.id"
                          class="detail-price-history-tip-row"
                        >
                          <span class="detail-price-history-tip-price">
                            {{ formatProcessHistoryPrice(item, isHourlyLabor(l)) }}
                          </span>
                          <span class="detail-price-history-tip-meta">
                            <template v-if="!isHourlyHistoryZero(item) && item.old_price != null && item.old_price !== ''">
                              原 ¥{{ formatPrice(item.old_price) }} ·
                            </template>
                            {{ item.changed_by_name || '—' }}
                            <template v-if="item.changed_at">
                              · {{ formatHistoryTime(item.changed_at) }}
                            </template>
                          </span>
                        </div>
                      </div>
                    </template>
                    <el-icon class="detail-price-history-icon" :size="14"><Clock /></el-icon>
                  </el-tooltip>
                  <span v-if="!isHourlyLabor(l)" class="muted detail-labor-unit">元/双</span>
                </div>
                <div v-if="l.requirement_note" class="detail-labor-note muted">
                  <div class="detail-labor-note-label">工艺要求：</div>
                  <div class="detail-labor-note-body">{{ l.requirement_note }}</div>
                </div>
              </div>
              <div v-if="!g.items.length" class="muted" style="padding: 8px 10px; font-size: 12px">
                暂无工序
              </div>
            </div>
          </div>
          <div v-if="!detailLaborGroups.length" class="muted" style="padding: 12px">暂无工序段</div>
          <div class="cost-summary-line">
            <span>人工成本</span>
            <strong>¥{{ formatPrice(detailRow.labor_cost) }}</strong>
          </div>
        </section>

        <section class="dev-panel commissions-panel">
          <div class="panel-title-row">
            <div class="panel-title">提成</div>
            <span class="section-count">{{ (detailRow.commissions || []).length }} 项</span>
          </div>
          <el-table
            v-if="(detailRow.commissions || []).length"
            border
            :data="commissionOneRow"
            size="small"
            class="soft-table other-cost-one-row-table"
          >
            <el-table-column
              v-for="(c, idx) in detailRow.commissions"
              :key="c.id ?? `cm-d-${idx}`"
              :column-key="`dcm-${c.id ?? idx}`"
              :label="c.employee_name || '（未选人）'"
              min-width="120"
              align="right"
              show-overflow-tooltip
            >
              <template #default>
                <span class="money">¥{{ formatPrice(c.amount) }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div v-else class="muted" style="padding: 12px">暂无提成</div>
          <div class="cost-summary-line">
            <span>提成</span>
            <strong>¥{{ formatPrice(detailRow.commission_cost) }}</strong>
          </div>
        </section>

        <section class="dev-panel other-costs-panel">
          <div class="panel-title-row">
            <div class="panel-title">其它成本</div>
            <span class="section-count">{{ (detailRow.other_costs || []).length }} 项</span>
          </div>
          <el-table
            v-if="(detailRow.other_costs || []).length"
            border
            :data="otherCostOneRow"
            size="small"
            class="soft-table other-cost-one-row-table"
          >
            <el-table-column
              v-for="(o, idx) in detailRow.other_costs"
              :key="o.id ?? `${o.name}-${idx}`"
              :column-key="`doc-${o.id ?? idx}`"
              :label="o.name || '—'"
              min-width="120"
              align="right"
              show-overflow-tooltip
            >
              <template #default>
                <span class="money">¥{{ formatPrice(o.amount) }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div v-else class="muted" style="padding: 12px">暂无其它成本</div>
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
        已选 {{ selectedCount }} 款产品。有该特殊客户报价的用客户价，没有的用统一报价。
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
              <template v-if="batchPartnerId">（无特殊客户报价用统一报价）</template>
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

    <el-dialog
      v-model="routeTemplateVisible"
      title="选用工艺路线模版"
      width="520px"
      destroy-on-close
      @opened="loadRouteTemplates"
    >
      <div v-loading="routeTemplatesLoading">
        <div v-if="!routeTemplates.length" class="muted" style="padding: 16px 0">暂无模版，可先在编辑页「存为模版」</div>
        <div v-else class="route-template-list">
          <button
            v-for="tpl in routeTemplates"
            :key="tpl.id"
            type="button"
            class="route-template-item"
            :class="{ 'is-active': selectedRouteTemplateId === tpl.id }"
            @click="selectedRouteTemplateId = tpl.id"
          >
            <div class="route-template-name">{{ tpl.name }}</div>
            <div class="muted route-template-meta">
              {{ (tpl.items || []).length }} 道工序
              <template v-if="tpl.segment_ref_prices && Object.keys(tpl.segment_ref_prices).length">
                · 含段参考价
              </template>
            </div>
          </button>
        </div>
      </div>
      <template #footer>
        <el-button @click="routeTemplateVisible = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="!selectedRouteTemplateId"
          @click="applySelectedRouteTemplate"
        >
          填充到当前路线
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="productVersionsVisible"
      title="产品历史版本"
      width="560px"
      destroy-on-close
      append-to-body
    >
      <div v-loading="versionsLoading">
        <el-empty v-if="!productVersions.length && !versionsLoading" description="暂无历史版本" />
        <div v-else class="product-version-list">
          <button
            v-for="v in productVersions"
            :key="v.id"
            type="button"
            class="product-version-item"
            :disabled="versionOpeningId === v.id"
            @click="openProductVersion(v)"
          >
            <div class="product-version-main">
              <span class="product-version-no">v{{ v.version_no }}</span>
              <span class="product-version-meta">
                {{ v.changed_by_name || '—' }}
                · {{ formatDateTime(v.changed_at) }}
                · {{ v.source === 'product_create' ? '创建' : '保存' }}
              </span>
            </div>
            <div class="product-version-changes">
              <template v-if="(v.changed_section_labels || []).length">
                <span
                  v-for="label in v.changed_section_labels"
                  :key="label"
                  class="product-version-tag"
                >{{ label }}</span>
              </template>
              <span v-else class="product-version-tag is-muted">无变更</span>
            </div>
          </button>
        </div>
      </div>
    </el-dialog>

    <OwnProductDetailDialog
      v-if="historyVersionVisible && historyVersionSnapshot"
      v-model="historyVersionVisible"
      :snapshot="historyVersionSnapshot"
      :version-meta="historyVersionMeta"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Clock, Delete, Search } from '@element-plus/icons-vue'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableColWidths } from '@/composables/useTableColWidths'
import OwnProductDetailDialog from '@/components/OwnProductDetailDialog.vue'

const quotesTableRef = ref()
const brandQuotesTableRef = ref()
const productInfoTableRef = ref()
const detailProductInfoTableRef = ref()
const materialsTableRef = ref()
const laborsTableRef = ref()
const {
  colWidth,
  onHeaderDragend,
  relayoutTable: relayoutQuotes,
} = useTableColWidths('own-products-quotes', quotesTableRef, {
  flexKey: 'customer',
  flexDefaultMin: 120,
  fitToContainer: true,
})
const {
  colWidth: colWidthBrand,
  onHeaderDragend: onHeaderDragendBrand,
  relayoutTable: relayoutBrandQuotes,
} = useTableColWidths('own-products-brand-quotes', brandQuotesTableRef, {
  flexKey: 'brand_name',
  flexDefaultMin: 100,
  fitToContainer: true,
})
const {
  colWidth: colWidthInfo,
  onHeaderDragend: onHeaderDragendInfo,
  relayoutTable: relayoutProductInfo,
} = useTableColWidths('own-products-info-edit', productInfoTableRef, {
  flexKey: 'fabric',
  flexDefaultMin: 100,
  fitToContainer: true,
})
const {
  colWidth: colWidthInfoDetail,
  onHeaderDragend: onHeaderDragendInfoDetail,
  relayoutTable: relayoutDetailProductInfo,
} = useTableColWidths('own-products-info-detail', detailProductInfoTableRef, {
  flexKey: 'fabric',
  flexDefaultMin: 100,
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
  colWidth: colWidth2,
  flexColMinWidth: flexColMinWidth2,
  onHeaderDragend: onHeaderDragend2,
  relayoutTable: relayoutLabors,
} = useTableColWidths('own-products-labors', laborsTableRef, {
  flexKey: 'process_name',
  flexDefaultMin: 160,
  fitToContainer: true,
})
const detailMaterialsTableRef = ref()
const detailLaborsTableRef = ref()
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
const { colWidth: colWidth7, onHeaderDragend: onHeaderDragend7 } = useTableColWidths('own-products-list')
const rows = ref<any[]>([])
const colors = ref<any[]>([])
const extraBoundColors = ref<{ id: number; name: string }[]>([])
const supplierProducts = ref<any[]>([])
const processes = ref<any[]>([])
const segments = ref<any[]>([])
const orgSettingsSkiving = ref(false)
const materialCategories = ref<any[]>([])
const customers = ref<any[]>([])
const keyword = ref('')
const yearFilter = ref<string | null>(null)
const seasonFilter = ref('')
const shoeLastFilter = ref<number | null>(null)
const currentYear = String(new Date().getFullYear())
const seasonOptions = [
  { value: 'SS', label: '春夏' },
  { value: 'FW', label: '秋冬' },
  { value: 'ALL', label: '全年' },
]
const hasFilters = computed(
  () =>
    !!keyword.value.trim() ||
    yearFilter.value !== null ||
    !!seasonFilter.value ||
    shoeLastFilter.value != null,
)
const sortKey = ref<'date' | 'order_qty'>('date')
const sortOrder = ref<'asc' | 'desc'>('desc')
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const visible = ref(false)
const detailVisible = ref(false)
const detailRow = ref<any>(null)
const detailPriceHistoryMap = ref<Record<string, any[]>>({})
const productVersionsVisible = ref(false)
const versionsLoading = ref(false)
const productVersions = ref<any[]>([])
const versionOpeningId = ref<number | null>(null)
const historyVersionVisible = ref(false)
const historyVersionSnapshot = ref<Record<string, any> | null>(null)
const historyVersionMeta = ref<{
  version_no?: number
  changed_by_name?: string | null
  changed_at?: string | null
  source?: string
  changed_sections?: string[]
  changed_section_labels?: string[]
} | null>(null)
const isCopying = ref(false)
const peerActuals = ref<any>(null)
const peerActualsLoading = ref(false)
const saving = ref(false)
const syncLaborsToOpenOrders = ref(false)
const savingRouteTemplate = ref(false)
const routeTemplateVisible = ref(false)
const routeTemplatesLoading = ref(false)
const routeTemplates = ref<any[]>([])
const selectedRouteTemplateId = ref<number | null>(null)
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
const processQuickRow = ref<any>(null)
const creatingProcess = ref(false)
const newProcessName = ref('')
const newProcessType = ref<'personal' | 'group'>('personal')
const processQuickInputRef = ref<any>(null)
const otherCostQuickVisible = ref(false)
const creatingOtherCost = ref(false)
const newOtherCostName = ref('')
const otherCostQuickInputRef = ref<any>(null)
const otherCostItems = ref<any[]>([])
/** 其它成本一行表金额：key=项目名 */
const otherCostAmounts = reactive<Record<string, number>>({})

const commissionQuickVisible = ref(false)
const newCommissionEmployeeId = ref<number | null>(null)
const commissionQuickSelectRef = ref<any>(null)
/** 提成列：本产品已添加的人员（或未选人） */
const commissionColumns = ref<
  { key: string; employee_id: number | null; label: string }[]
>([])
/** 提成一行表金额：key=列 key */
const commissionAmounts = reactive<Record<string, number>>({})
let commissionAnonSeq = 0

const auth = useAuthStore()

const form = reactive<any>({
  id: null,
  product_code: '',
  product_year: currentYear,
  season: '',
  image_url: '',
  fabric: '',
  lining: '',
  shoe_last_id: null as number | null,
  shoe_last_hours: null as number | null,
  color_ids: [] as number[],
  materials: [] as any[],
  labors: [] as any[],
  other_costs: [] as any[],
  quotes: [] as any[],
  brand_quotes: [] as any[],
  quote_price: null as number | null,
  order_qty: 0,
  is_active: true,
})

const employeeOptions = ref<any[]>([])

const productInfoEditRows = computed(() => [form])
const productInfoDetailRows = computed(() => (detailRow.value ? [detailRow.value] : []))
/** 其它成本 / 提成一行表：表头是项目，唯一数据行填金额 */
const otherCostOneRow = computed(() => [{}])
const commissionOneRow = computed(() => [{}])

const commissionQuickEmployeeOptions = computed(() => {
  const used = new Set(
    commissionColumns.value
      .map((c) => c.employee_id)
      .filter((id): id is number => id != null),
  )
  return (employeeOptions.value || []).filter((e: any) => !used.has(e.id))
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

function resetFilters() {
  keyword.value = ''
  yearFilter.value = null
  seasonFilter.value = ''
  shoeLastFilter.value = null
  reloadList()
}

function seasonLabel(value: string | null | undefined) {
  return seasonOptions.find((item) => item.value === value)?.label || '未设置'
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
      product_year: yearFilter.value ?? undefined,
      season: seasonFilter.value || undefined,
      shoe_last_id: shoeLastFilter.value ?? undefined,
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

const previewLaborCost = computed(() => {
  let sum = 0
  const seen = new Set<string>()
  for (const seg of laborSegments.value) {
    const key = seg.segmentId == null ? 'null' : String(seg.segmentId)
    seen.add(key)
    const processSum = segmentSubtotal(seg.segmentId)
    if (processSum > 0) sum += processSum
    else if (seg.segmentId != null) sum += segmentRefPrice(seg.segmentId)
  }
  // 兜底：未出现在 laborSegments 里的工序价（极少）
  for (const row of form.labors) {
    const key = row.segment_id == null ? 'null' : String(row.segment_id)
    if (seen.has(key)) continue
    sum += Number(row.unit_price || 0)
  }
  return sum
})

const previewOtherCost = computed(() =>
  Object.values(otherCostAmounts).reduce((sum, v) => sum + Number(v || 0), 0),
)

const previewCommissionCost = computed(() =>
  Object.values(commissionAmounts).reduce((sum, v) => sum + Number(v || 0), 0),
)

const previewTotalCost = computed(
  () =>
    previewMaterialCost.value +
    previewLaborCost.value +
    previewCommissionCost.value +
    previewOtherCost.value,
)

const activeProcesses = computed(() =>
  (processes.value || []).filter((p: any) => p.is_active !== false),
)

const SHOE_LAST_CATEGORY_NAMES = new Set(['模具楦头', '模型楦头'])
const shoeLastOptions = computed(() => {
  const catIds = new Set(
    (materialCategories.value || [])
      .filter((c: any) => SHOE_LAST_CATEGORY_NAMES.has(String(c.name || '').trim()))
      .map((c: any) => c.id),
  )
  return (supplierProducts.value || []).filter(
    (sp: any) => catIds.has(sp.category_id) && sp.is_active !== false,
  )
})

function shoeLastOptionLabel(sp: any) {
  const name = String(sp.name || '').trim()
  const code = String(sp.product_code || '').trim()
  if (name && code && name !== code) return `${name}（${code}）`
  return name || code || String(sp.id)
}

/** 一行表列：启用的基础项目 + 本产品已有但已停用的项目 */
const otherCostColumns = computed(() => {
  const items = (otherCostItems.value || [])
    .filter((x: any) => x.is_active !== false)
    .slice()
    .sort((a: any, b: any) => Number(a.sort_order || 0) - Number(b.sort_order || 0) || Number(a.id) - Number(b.id))
  const names = new Set(items.map((x: any) => String(x.name || '').trim()).filter(Boolean))
  for (const name of Object.keys(otherCostAmounts)) {
    const n = String(name || '').trim()
    if (n && !names.has(n) && Number(otherCostAmounts[n] || 0) > 0) {
      items.push({ id: `legacy-${n}`, name: n, is_active: false })
      names.add(n)
    }
  }
  return items
})

function clearOtherCostAmounts() {
  for (const k of Object.keys(otherCostAmounts)) delete otherCostAmounts[k]
}

function loadOtherCostAmounts(rows: any[] | null | undefined) {
  clearOtherCostAmounts()
  for (const o of rows || []) {
    const name = String(o.name || '').trim()
    if (!name) continue
    otherCostAmounts[name] = Number(o.amount || 0)
  }
}

function otherCostAmount(name: string) {
  return Number(otherCostAmounts[name] || 0)
}

function setOtherCostAmount(name: string, val: number | null | undefined) {
  const n = String(name || '').trim()
  if (!n) return
  otherCostAmounts[n] = Number(val || 0)
}

function otherCostsPayload() {
  return otherCostColumns.value
    .map((item: any) => {
      const name = String(item.name || '').trim()
      return { name, amount: Number(otherCostAmounts[name] || 0) }
    })
    .filter((o) => o.name && Number(o.amount) > 0)
}

function clearCommissionAmounts() {
  for (const k of Object.keys(commissionAmounts)) delete commissionAmounts[k]
  commissionColumns.value = []
  commissionAnonSeq = 0
}

function commissionColumnKey(employeeId: number | null) {
  if (employeeId != null) return `emp-${employeeId}`
  commissionAnonSeq += 1
  return `anon-${commissionAnonSeq}`
}

function commissionLabel(employeeId: number | null, fallbackName?: string | null) {
  if (employeeId == null) return '（未选人）'
  const hit = (employeeOptions.value || []).find((e: any) => e.id === employeeId)
  if (hit) return hit.mobile ? `${hit.name}（${hit.mobile}）` : hit.name
  return String(fallbackName || '').trim() || `人员#${employeeId}`
}

function loadCommissionAmounts(rows: any[] | null | undefined) {
  clearCommissionAmounts()
  for (const c of rows || []) {
    const employeeId = c.employee_id ?? null
    if (employeeId != null) {
      const key = `emp-${employeeId}`
      if (!commissionColumns.value.some((x) => x.key === key)) {
        commissionColumns.value.push({
          key,
          employee_id: employeeId,
          label: commissionLabel(employeeId, c.employee_name),
        })
      }
      commissionAmounts[key] = Number(c.amount || 0)
      continue
    }
    const key = commissionColumnKey(null)
    commissionColumns.value.push({
      key,
      employee_id: null,
      label: '（未选人）',
    })
    commissionAmounts[key] = Number(c.amount || 0)
  }
}

function commissionAmount(key: string) {
  return Number(commissionAmounts[key] || 0)
}

function setCommissionAmount(key: string, val: number | null | undefined) {
  if (!key) return
  commissionAmounts[key] = Number(val || 0)
}

function commissionsPayload() {
  return commissionColumns.value
    .map((item) => ({
      employee_id: item.employee_id,
      amount: Number(commissionAmounts[item.key] || 0),
    }))
    .filter((c) => Number(c.amount) > 0)
}

async function onCommissionQuickShow() {
  newCommissionEmployeeId.value = null
  await nextTick()
  commissionQuickSelectRef.value?.focus?.()
}

function addCommissionQuick() {
  const employeeId = newCommissionEmployeeId.value
  if (employeeId != null) {
    if (commissionColumns.value.some((c) => c.employee_id === employeeId)) {
      ElMessage.warning('该人员已添加')
      return
    }
    const key = `emp-${employeeId}`
    commissionColumns.value.push({
      key,
      employee_id: employeeId,
      label: commissionLabel(employeeId),
    })
    if (commissionAmounts[key] == null) commissionAmounts[key] = 0
  } else {
    const key = commissionColumnKey(null)
    commissionColumns.value.push({
      key,
      employee_id: null,
      label: '（未选人）',
    })
    commissionAmounts[key] = 0
  }
  commissionQuickVisible.value = false
  newCommissionEmployeeId.value = null
}

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

// 工序段重构（19.3）：选段后工序下拉只显示该段下工序
function laborProcessOptionsFor(row: any) {
  const segId = row?.segment_id
  if (segId == null) return laborProcessOptions.value
  const scoped = laborProcessOptions.value.filter((p: any) => Number(p.segment_id) === Number(segId))
  // 段下无工序时回退全部，避免下拉空白（数据未配段时仍可选）
  return scoped.length ? scoped : laborProcessOptions.value
}

function formatTime(v?: string) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 19)
}

function formatDate(v?: string) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 10)
}

function formatDateTime(v?: string | null) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 19)
}

/** 工序改价历史：精确到分钟 */
function formatHistoryTime(v?: string | null) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 16)
}

function formatPrice(v: any, digits = 2) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(digits)
}

/** 用量：整数不补小数；有小数最多保留 4 位并去掉尾随 0 */
function formatQty(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  if (Number.isInteger(n)) return String(n)
  return String(Number(n.toFixed(4)))
}

function onMaterialQtyChange(row: any, v: number | undefined | null) {
  const n = Number(v)
  if (!Number.isFinite(n) || n < 0) {
    row.qty = 0
    return
  }
  row.qty = Number(n.toFixed(4))
}

function lineTotal(row: any) {
  const qty = Number(row.qty || 0)
  const price = Number(row.unit_price || 0)
  return qty * price
}

function totalCost(row: any) {
  return (
    Number(row.material_cost || 0) +
    Number(row.labor_cost || 0) +
    Number(row.commission_cost || 0) +
    Number(row.other_cost || 0)
  )
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
  // 按码跟物料分类，不再在 BOM 上手改
  applyUsageBySizeFromCategory(row, sp)
}

function applyUsageBySizeFromCategory(row: any, sp?: any) {
  const product = sp ?? spById(row.supplier_product_id)
  const cat = product?.category_id
    ? materialCategories.value.find((c: any) => c.id === product.category_id)
    : null
  row.usage_by_size = !!cat?.suggest_usage_by_size
  row.size_usage_table_id = row.usage_by_size
    ? (cat?.default_size_usage_table_id ?? null)
    : null
}

function isProcessNameUsed(name: string, current: any) {
  const key = String(name || '').trim().toLowerCase()
  if (!key) return false
  return form.labors.some(
    (l: any) =>
      l !== current &&
      String(l.process_name || '').trim().toLowerCase() === key,
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
    consume_segment_id: null,
    usage_by_size: false,
    size_usage_table_id: null,
  })
}

let laborKeySeq = 0
function nextLaborKey() {
  laborKeySeq += 1
  return `labor-${laborKeySeq}-${Date.now()}`
}

// 工序段重构：默认段顺序（铲皮按 skiving_enabled 开关显示）；历史无段行走「未分段」兜底（D18）
const DEFAULT_SEGMENT_CODES = ['cut', 'stitch', 'forming', 'packing']
function segmentDepartmentName(name: string) {
  return name === '未分段' || name.endsWith('部') ? name : `${name}部`
}

const laborSegments = computed(() => {
  const wanted = [...DEFAULT_SEGMENT_CODES]
  if (orgSettingsSkiving.value) wanted.push('skiving')
  const list = segments.value
    .filter((seg) => wanted.includes(seg.code) && seg.is_active !== false)
    .slice()
    .sort(
      (a, b) =>
        Number(a.sort_order || 0) - Number(b.sort_order || 0) || Number(a.id) - Number(b.id),
    )
    .map((seg) => ({ key: `seg-${seg.id}`, name: seg.name, segmentId: seg.id }))
  const hasUnlabeled = (form.labors || []).some((l: any) => l.segment_id == null)
  if (hasUnlabeled) {
    list.push({ key: 'unlabeled', name: '未分段', segmentId: null })
  }
  return list
})

function segmentLabors(segmentId: number | null) {
  return (form.labors || []).filter((l: any) =>
    segmentId == null ? l.segment_id == null : Number(l.segment_id) === Number(segmentId),
  )
}

function segmentHasProcesses(segmentId: number | null) {
  return segmentLabors(segmentId).length > 0
}

function segmentSubtotal(segmentId: number | null) {
  return segmentLabors(segmentId).reduce((sum: number, l: any) => sum + Number(l.unit_price || 0), 0)
}

/** 段有效成本：有工序价用工序合计，否则用参考价 */
function segmentEffectiveCost(segmentId: number | null) {
  const processSum = segmentSubtotal(segmentId)
  if (processSum > 0) return processSum
  return segmentRefPrice(segmentId)
}

/** 段参考价（选填）：未填工序价时计入人工成本 */
const segmentRefPrices = reactive<Record<string, number>>({})

function clearSegmentRefPrices() {
  for (const k of Object.keys(segmentRefPrices)) delete segmentRefPrices[k]
}

function segmentRefPrice(segmentId: number | null) {
  if (segmentId == null) return 0
  return Number(segmentRefPrices[String(segmentId)] || 0)
}

function setSegmentRefPrice(segmentId: number | null, val: number | null | undefined) {
  if (segmentId == null) return
  const n = Number(val || 0)
  if (n > 0) segmentRefPrices[String(segmentId)] = n
  else delete segmentRefPrices[String(segmentId)]
}

function loadSegmentRefPrices(raw: Record<string, any> | null | undefined) {
  clearSegmentRefPrices()
  if (!raw || typeof raw !== 'object') return
  for (const [k, v] of Object.entries(raw)) {
    const n = Number(v || 0)
    if (n > 0) segmentRefPrices[String(k)] = n
  }
}

function segmentRefPricesPayload() {
  const out: Record<string, number> = {}
  for (const [k, v] of Object.entries(segmentRefPrices)) {
    const n = Number(v || 0)
    if (n > 0) out[k] = n
  }
  return Object.keys(out).length ? out : null
}

function addLaborTo(segmentId: number | null) {
  const seg = segmentId != null ? segments.value.find((x) => x.id === segmentId) : null
  form.labors.push({
    process_name: '',
    unit_price: 0,
    requirement_note: '',
    segment_id: segmentId,
    segment_name: seg?.name ?? null,
    sort_order: segmentLabors(segmentId).length * 10,
    _key: nextLaborKey(),
  })
}

function removeLabor(row: any) {
  const idx = form.labors.indexOf(row)
  if (idx >= 0) form.labors.splice(idx, 1)
}

const REQUIREMENT_NOTE_MAX = 500
function onRequirementNoteInput(row: any, val: string) {
  const text = String(val ?? '')
  if (text.length <= REQUIREMENT_NOTE_MAX) {
    row._noteLimitTipShown = false
    return
  }
  row.requirement_note = text.slice(0, REQUIREMENT_NOTE_MAX)
  if (!row._noteLimitTipShown) {
    row._noteLimitTipShown = true
    ElMessage.warning(`工艺要求备注最多 ${REQUIREMENT_NOTE_MAX} 字`)
  }
}

function measureNotePopoverWidth(row: any) {
  const wrap = document.querySelector(`[data-labor-key="${row._key}"]`) as HTMLElement | null
  const block = wrap?.closest('.labor-seg-block') as HTMLElement | null
  const w = Math.round(block?.getBoundingClientRect().width || 0)
  if (w > 0) row._notePopoverWidth = w
}

function measurePricePopoverWidth(row: any) {
  measureNotePopoverWidth(row)
  if (row._notePopoverWidth) row._pricePopoverWidth = row._notePopoverWidth
}

async function loadProcessPriceHistory(row: any) {
  const name = String(row.process_name || '').trim()
  if (!name) {
    row._priceHistory = []
    return
  }
  row._priceHistoryLoading = true
  try {
    const hit = processes.value.find((p: any) => String(p.name || '').trim() === name)
    const res: any = await http.get('/own-products/process-price-history', {
      params: hit?.id ? { process_id: hit.id, limit: 30 } : { process_name: name, limit: 30 },
    })
    row._priceHistory = res.data?.items || []
  } catch {
    row._priceHistory = []
  } finally {
    row._priceHistoryLoading = false
  }
}

function applyProcessPrice(row: any, price: number | string) {
  row.unit_price = Number(price || 0)
  ElMessage.success('已填入历史工序价')
}

async function loadRequirementNoteHistory(row: any) {
  const name = String(row.process_name || '').trim()
  if (!name) {
    row._noteHistory = []
    return
  }
  row._noteHistoryLoading = true
  try {
    const hit = processes.value.find((p: any) => String(p.name || '').trim() === name)
    const res: any = await http.get('/own-products/requirement-notes', {
      params: hit?.id ? { process_id: hit.id, limit: 20 } : { process_name: name, limit: 20 },
    })
    row._noteHistory = res.data?.items || []
  } catch {
    row._noteHistory = []
  } finally {
    row._noteHistoryLoading = false
  }
}

function applyRequirementNote(row: any, note: string) {
  row.requirement_note = String(note || '').slice(0, REQUIREMENT_NOTE_MAX)
  ElMessage.success('已填入历史工艺要求')
}

async function saveRouteTemplate() {
  const items = (form.labors || [])
    .filter((l: any) => String(l.process_name || '').trim())
    .map((l: any, i: number) => ({
      process_name: String(l.process_name || '').trim(),
      requirement_note: String(l.requirement_note || '').trim() || null,
      unit_price: Number(l.unit_price || 0),
      segment_id: l.segment_id ?? null,
      sort_order: i,
    }))
  const refs = segmentRefPricesPayload()
  if (!items.length && !refs) {
    ElMessage.warning('请先添加工序或填写段参考价')
    return
  }
  let name = ''
  try {
    const { value } = await ElMessageBox.prompt('给当前工艺路线起个模版名', '存为模版', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputPlaceholder: '如：常规运动鞋针车成型',
      inputPattern: /\S+/,
      inputErrorMessage: '请填写模版名称',
    })
    name = String(value || '').trim()
  } catch {
    return
  }
  if (!name) return
  savingRouteTemplate.value = true
  try {
    await http.post('/own-products/route-templates', {
      name,
      items,
      segment_ref_prices: refs,
    })
    ElMessage.success(`已保存模版「${name}」`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '保存模版失败')
  } finally {
    savingRouteTemplate.value = false
  }
}

function openRouteTemplatePicker() {
  selectedRouteTemplateId.value = null
  routeTemplateVisible.value = true
}

async function loadRouteTemplates() {
  routeTemplatesLoading.value = true
  try {
    const res: any = await http.get('/own-products/route-templates')
    routeTemplates.value = res.data?.items || []
  } catch {
    routeTemplates.value = []
  } finally {
    routeTemplatesLoading.value = false
  }
}

async function applySelectedRouteTemplate() {
  const id = selectedRouteTemplateId.value
  if (!id) return
  const tpl = routeTemplates.value.find((t) => t.id === id)
  if (!tpl) {
    ElMessage.warning('请选择模版')
    return
  }
  if ((form.labors || []).some((l: any) => String(l.process_name || '').trim() || Number(l.unit_price || 0) > 0 || String(l.requirement_note || '').trim())) {
    try {
      await ElMessageBox.confirm('将用模版覆盖当前工艺路线（含工序价与工艺要求），是否继续？', '选用模版', {
        type: 'warning',
        confirmButtonText: '覆盖填充',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
  }
  const items = Array.isArray(tpl.items) ? tpl.items : []
  form.labors = items.map((row: any, i: number) => {
    const name = String(row.process_name || '').trim()
    const hit = processes.value.find((p: any) => String(p.name || '').trim() === name)
    const segId = row.segment_id ?? hit?.segment_id ?? null
    const seg = segId != null ? segments.value.find((x: any) => x.id === segId) : null
    return {
      process_name: name,
      unit_price: Number(row.unit_price || 0),
      requirement_note: String(row.requirement_note || ''),
      segment_id: segId,
      segment_name: seg?.name ?? row.segment_name ?? null,
      sort_order: row.sort_order ?? i,
      _key: nextLaborKey(),
    }
  })
  loadSegmentRefPrices(tpl.segment_ref_prices || null)
  routeTemplateVisible.value = false
  ElMessage.success(`已填充模版「${tpl.name}」`)
}

// 详情展示：按段分组；段顺序跟工序段基础数据 sort_order，不随工序出现顺序变化
function segmentGroupsOf(labors: any[], refPrices?: Record<string, any> | null) {
  const wanted = [...DEFAULT_SEGMENT_CODES]
  if (orgSettingsSkiving.value) wanted.push('skiving')
  const order = segments.value
    .filter((seg) => wanted.includes(seg.code) && seg.is_active !== false)
    .slice()
    .sort(
      (a, b) =>
        Number(a.sort_order || 0) - Number(b.sort_order || 0) || Number(a.id) - Number(b.id),
    )
    .map((seg) => ({ key: seg.id, name: seg.name }))
  const refOf = (segKey: number) => {
    if (!refPrices || typeof refPrices !== 'object') return null
    const raw = refPrices[String(segKey)] ?? refPrices[segKey as any]
    const n = Number(raw)
    return !Number.isNaN(n) && n > 0 ? n : null
  }
  const groups = order.map((seg) => ({
    key: seg.key,
    name: seg.name,
    items: [] as any[],
    subtotal: 0,
    refPrice: null as number | null,
    effectiveCost: null as number | null,
  }))
  const byKey = new Map(groups.map((g) => [Number(g.key), g]))
  const unlabeled: any[] = []
  for (const l of labors || []) {
    const g = l.segment_id != null ? byKey.get(Number(l.segment_id)) : undefined
    if (g) {
      g.items.push(l)
      g.subtotal += Number(l.unit_price || 0)
    } else {
      unlabeled.push(l)
    }
  }
  for (const g of groups) {
    const ref = refOf(Number(g.key))
    g.refPrice = ref
    g.effectiveCost = g.subtotal > 0 ? g.subtotal : ref
  }
  if (unlabeled.length) {
    const sub = unlabeled.reduce((sum: number, l: any) => sum + Number(l.unit_price || 0), 0)
    groups.push({
      key: 'unlabeled',
      name: '未分段',
      items: unlabeled,
      subtotal: sub,
      refPrice: null,
      effectiveCost: sub > 0 ? sub : null,
    })
  }
  return groups
}

const detailLaborGroups = computed(() => {
  const row = detailRow.value
  if (!row) return []
  return segmentGroupsOf(row.labors || [], row.segment_ref_prices || null)
})

function processTypeOfName(name: string) {
  const n = String(name || '').trim()
  const hit = processes.value.find((p) => String(p.name || '').trim() === n)
  return hit?.type === 'group' ? 'group' : 'personal'
}

function isHourlyProcess(row: any) {
  const name = String(row?.process_name || '').trim()
  return processes.value.some((p: any) => String(p.name || '').trim() === name && p.pay_mode === 'hourly')
}

function isHourlyLabor(l: any) {
  if (l?.pay_mode === 'hourly') return true
  return isHourlyProcess(l)
}

function isHourlyHistoryZero(item: any) {
  const price = Number(item?.new_price)
  return !Number.isFinite(price) || price <= 0
}

function formatProcessHistoryPrice(item: any, hourly = false) {
  if (hourly && isHourlyHistoryZero(item)) return '计时'
  // 切到计时：原价 → 0，展示为「计时」；切回计件：0 → 恢复价，走下方金额
  if (
    item?.source === 'process_pay_mode_change' &&
    isHourlyHistoryZero(item) &&
    Number(item?.old_price) > 0
  ) {
    return '计时'
  }
  return `¥${formatPrice(item?.new_price)}`
}

function onLaborProcessChange(row: any, name: string) {
  // 工序段重构（19.6/D13）：不再处理 process_type。
  // 行段固定（段内新增）→ 保持段不动，避免行跳组；未分段行（历史/兜底）→ 按工序归段
  const n = String(name || '').trim()
  const hit = processes.value.find((p) => String(p.name || '').trim() === n)
  if (hit?.pay_mode === 'hourly') row.unit_price = 0
  if (row.segment_id == null && hit) {
    row.segment_id = hit.segment_id ?? null
    const seg = segments.value.find((x) => x.id === row.segment_id)
    row.segment_name = seg?.name ?? null
  }
}

function addQuote() {
  form.quotes.push({
    partner_id: null,
    quote_price: 0,
  })
}

function addBrandQuote() {
  form.brand_quotes.push({
    brand_name: '',
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

function onLaborProcessSelectVisible(row: any, open: boolean) {
  if (!open && processQuickRow.value === row) cancelProcessQuick()
}

async function startProcessQuickInSelect(row: any) {
  processQuickRow.value = row
  newProcessName.value = ''
  newProcessType.value = 'personal'
  await nextTick()
  processQuickInputRef.value?.focus?.()
}

function cancelProcessQuick() {
  processQuickRow.value = null
  newProcessName.value = ''
  newProcessType.value = 'personal'
}

async function createProcessQuick() {
  const name = newProcessName.value.trim()
  if (!name) {
    ElMessage.warning('请输入工序名称')
    return
  }
  const target = processQuickRow.value
  const segmentId = target?.segment_id ?? null
  creatingProcess.value = true
  try {
    const res: any = await http.post('/processes', {
      name,
      code: genProcessCode(),
      default_price: 0,
      sort_order: processes.value.length,
      type: newProcessType.value,
      segment_id: segmentId,
      per_worker_capacity: null,
      standard_workers: 1,
    })
    const p = res.data
    if (!processes.value.some((x: any) => x.id === p.id)) processes.value.push(p)
    if (target) {
      target.process_name = p.name
      onLaborProcessChange(target, p.name)
    }
    cancelProcessQuick()
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
    setOtherCostAmount(item.name, otherCostAmount(item.name))
    otherCostQuickVisible.value = false
    ElMessage.success(`已添加其它成本「${item.name}」`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '添加失败')
  } finally {
    creatingOtherCost.value = false
  }
}

async function load() {
  const [colorRes, spRes, processRes, segRes, partnerRes, otherCostRes, catRes, empRes]: any[] =
    await Promise.all([
      http.get('/colors'),
      http.get('/supplier-products', { params: { active_only: true, page_size: 200 } }),
      http.get('/processes'),
      http.get('/process-segments'),
      http.get('/partners', { params: { role: 'customer_brand', active_only: true, page_size: 200 } }),
      http.get('/other-cost-items'),
      http.get('/material-categories', { params: { active_only: true } }),
      http.get('/employees', { params: { page_size: 500, is_active: true } }),
    ])
  colors.value = colorRes.data.items
  supplierProducts.value = spRes.data.items
  processes.value = processRes.data.items || []
  segments.value = segRes.data?.items || []
  try {
    const ors: any = await http.get('/org/settings')
    orgSettingsSkiving.value = !!ors.data?.skiving_enabled
  } catch { /* keep false */ }
  customers.value = partnerRes.data.items || []
  otherCostItems.value = otherCostRes.data?.items || []
  materialCategories.value = catRes.data?.items || []
  employeeOptions.value = empRes.data?.items || []
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
  detailPriceHistoryMap.value = {}
  void loadPeerActuals(row.id)
  // 详情单独拉全量，确保参考价等字段齐全
  void (async () => {
    try {
      const res: any = await http.get(`/own-products/${row.id}`)
      if (detailVisible.value && detailRow.value?.id === row.id) {
        detailRow.value = res.data
        await loadDetailPriceHistories(res.data?.labors || [])
      }
    } catch {
      /* 保留列表快照 */
      await loadDetailPriceHistories(row.labors || [])
    }
  })()
}

function laborPriceHistoryKey(l: any) {
  if (l?.process_id != null) return `id:${l.process_id}`
  const name = String(l?.process_name || '').trim()
  return name ? `name:${name}` : ''
}

function laborPriceHistory(l: any) {
  const key = laborPriceHistoryKey(l)
  return key ? detailPriceHistoryMap.value[key] || [] : []
}

function laborHasPriceHistory(l: any) {
  return laborPriceHistory(l).some((i) => i.old_price != null && i.old_price !== '')
}

async function loadDetailPriceHistories(labors: any[]) {
  const tasks = new Map<string, { process_id?: number; process_name?: string }>()
  for (const l of labors || []) {
    const key = laborPriceHistoryKey(l)
    if (!key || tasks.has(key)) continue
    if (l.process_id != null) tasks.set(key, { process_id: Number(l.process_id) })
    else tasks.set(key, { process_name: String(l.process_name || '').trim() })
  }
  const next: Record<string, any[]> = {}
  await Promise.all(
    [...tasks.entries()].map(async ([key, params]) => {
      try {
        const res: any = await http.get('/own-products/process-price-history', {
          params: { ...params, limit: 15 },
        })
        next[key] = res.data?.items || []
      } catch {
        next[key] = []
      }
    }),
  )
  detailPriceHistoryMap.value = next
}

async function openProductVersionList() {
  const id = detailRow.value?.id
  if (!id) return
  productVersionsVisible.value = true
  versionsLoading.value = true
  productVersions.value = []
  try {
    const res: any = await http.get(`/own-products/${id}/versions`)
    productVersions.value = res.data?.items || []
  } catch {
    productVersions.value = []
  } finally {
    versionsLoading.value = false
  }
}

async function openProductVersion(v: any) {
  const id = detailRow.value?.id
  if (!id || !v?.id) return
  versionOpeningId.value = v.id
  try {
    const res: any = await http.get(`/own-products/${id}/versions/${v.id}`)
    historyVersionSnapshot.value = res.data?.snapshot || null
    historyVersionMeta.value = {
      version_no: res.data?.version_no ?? v.version_no,
      changed_by_name: res.data?.changed_by_name ?? v.changed_by_name,
      changed_at: res.data?.changed_at ?? v.changed_at,
      source: res.data?.source ?? v.source,
      changed_sections: res.data?.changed_sections ?? v.changed_sections ?? [],
      changed_section_labels:
        res.data?.changed_section_labels ?? v.changed_section_labels ?? [],
    }
    historyVersionVisible.value = true
  } catch {
    ElMessage.error('打开历史版本失败')
  } finally {
    versionOpeningId.value = null
  }
}

function onEditDialogOpened() {
  relayoutProductInfo()
  relayoutQuotes()
  relayoutBrandQuotes()
  relayoutMaterials()
  relayoutLabors()
}

function onDetailDialogOpened() {
  relayoutDetailProductInfo()
  relayoutDetailMaterials()
  relayoutDetailLabors()
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
    product_year: row.product_year ?? currentYear,
    season: row.season || '',
    image_url: row.image_url || '',
    fabric: row.fabric || '',
    lining: row.lining || '',
    shoe_last_id: row.shoe_last_id ?? null,
    shoe_last_hours:
      row.shoe_last_hours != null && row.shoe_last_hours !== ''
        ? Number(row.shoe_last_hours)
        : null,
    color_ids: firstColorId ? [firstColorId] : [],
    materials: (row.materials || []).map((m: any) => ({
      supplier_product_id: m.supplier_product_id,
      qty: Number(Number(m.qty || 0).toFixed(4)),
      unit_price: Number(m.unit_price || 0),
      image_url: m.image_url || '',
      color_name: m.color_name || '',
      pricing_unit_name: m.pricing_unit_name || '',
      partner_name: m.partner_name || '',
      supplier_product_code: m.supplier_product_code || '',
      supplier_product_name: m.supplier_product_name || '',
      consume_segment_id: m.consume_segment_id ?? null,
      usage_by_size: !!m.usage_by_size,
      size_usage_table_id: m.size_usage_table_id ?? null,
    })),
    labors: (row.labors || []).map((l: any) => {
      // 工序段重构：历史数据无段时按工序主数据兜底归段（迁移 34.11 之外的补充）
      let segId = l.segment_id ?? null
      if (segId == null) {
        const hit = processes.value.find((p: any) => String(p.name || '').trim() === String(l.process_name || '').trim())
        segId = hit?.segment_id ?? null
      }
      const seg = segId != null ? segments.value.find((x) => x.id === segId) : null
      return {
        process_name: l.process_name || '',
        requirement_note: l.requirement_note || '',
        unit_price: Number(l.unit_price || 0),
        segment_id: segId,
        segment_name: seg?.name ?? l.segment_name ?? null,
        sort_order: l.sort_order ?? 0,
        _key: nextLaborKey(),
      }
    }),
    other_costs: (row.other_costs || []).map((o: any) => ({
      name: o.name || '',
      amount: Number(o.amount || 0),
    })),
    quotes: (row.quotes || []).map((q: any) => ({
      partner_id: q.partner_id,
      quote_price: Number(q.quote_price || 0),
    })),
    brand_quotes: (row.brand_quotes || []).map((q: any) => ({
      brand_name: q.brand_name || '',
      quote_price: Number(q.quote_price || 0),
    })),
    quote_price: row.quote_price != null && row.quote_price !== '' ? Number(row.quote_price) : null,
    order_qty: asCopy ? 0 : Number(row.order_qty || 0),
  })
  syncLaborsToOpenOrders.value = false
  isCopying.value = asCopy
  loadSegmentRefPrices(row.segment_ref_prices)
  loadOtherCostAmounts(row.other_costs)
  loadCommissionAmounts(row.commissions)
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
    product_year: form.product_year,
    season: form.season,
    image_url: form.image_url,
    fabric: form.fabric,
    lining: form.lining,
    shoe_last_id: form.shoe_last_id,
    shoe_last_hours: form.shoe_last_hours,
    color_ids: [...(form.color_ids || [])],
    materials: (form.materials || []).map((m: any) => ({ ...m })),
    labors: (form.labors || []).map((l: any) => ({ ...l })),
    commissions: commissionsPayload(),
    other_costs: otherCostsPayload(),
    quotes: (form.quotes || []).map((q: any) => ({ ...q })),
    brand_quotes: (form.brand_quotes || []).map((q: any) => ({ ...q })),
    quote_price: form.quote_price,
    segment_ref_prices: segmentRefPricesPayload(),
    order_qty: form.order_qty,
  })
}

async function openForm(row?: any) {
  if (row) {
    fillFormFromRow(row)
  } else {
    // 工序段重构：预填依赖 processes/segments，未加载时先补齐，避免默认工序为空
    if (!processes.value.length || !segments.value.length) {
      await load()
    }
    Object.assign(form, {
      id: null,
      product_code: '',
      product_year: currentYear,
      season: '',
      image_url: '',
      fabric: '',
      lining: '',
      shoe_last_id: null,
      shoe_last_hours: null,
      color_ids: [],
      materials: [],
      labors: [],
      other_costs: [],
      quotes: [],
      brand_quotes: [],
      quote_price: null,
      order_qty: 0,
    })
    extraBoundColors.value = []
    syncLaborsToOpenOrders.value = false
    isCopying.value = false
    peerActuals.value = null
    // 新增产品不预填工序：初期可填参考价，投产前再写工序
    prefillLaborSegments()
    clearOtherCostAmounts()
    clearCommissionAmounts()
  }
  visible.value = true
}

function prefillLaborSegments() {
  form.labors = []
  clearSegmentRefPrices()
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
  if (uploading.value || form.image_url) return
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
    ElMessage.warning('请填写工厂型号')
    return
  }
  if (!form.color_ids.length) {
    ElMessage.warning('请选择成品颜色')
    return
  }
  if (!form.product_year) {
    ElMessage.warning('请选择年份')
    return
  }
  if (!form.season) {
    ElMessage.warning('请选择季节')
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
  const processKeys = labors.map((l: any) => String(l.process_name || '').toLowerCase())
  if (new Set(processKeys).size !== processKeys.length) {
    ElMessage.warning('工序不能重复')
    return
  }
  const otherCosts = otherCostsPayload()
  if (otherCosts.some((o: any) => !(Number(o.amount) >= 0))) {
    ElMessage.warning('请检查其它成本金额')
    return
  }
  const commissions = commissionsPayload()
  if (commissions.some((c: any) => !(Number(c.amount) >= 0))) {
    ElMessage.warning('请检查提成金额')
    return
  }
  const commissionEmpIds = commissions
    .map((c: any) => c.employee_id)
    .filter((id: any) => id != null)
  if (new Set(commissionEmpIds).size !== commissionEmpIds.length) {
    ElMessage.warning('同一人员不能重复提成')
    return
  }
  const quotes = form.quotes.filter((q: any) => q.partner_id)
  if (quotes.some((q: any) => !(Number(q.quote_price) >= 0))) {
    ElMessage.warning('请检查特殊客户报价')
    return
  }
  const partnerIds = quotes.map((q: any) => q.partner_id)
  if (new Set(partnerIds).size !== partnerIds.length) {
    ElMessage.warning('同一客户不能重复报价')
    return
  }
  const brandQuotes = form.brand_quotes
    .map((q: any) => ({
      ...q,
      brand_name: String(q.brand_name || '').trim(),
    }))
    .filter((q: any) => q.brand_name)
  if (brandQuotes.some((q: any) => !(Number(q.quote_price) >= 0))) {
    ElMessage.warning('请检查特殊品牌报价')
    return
  }
  const brandNames = brandQuotes.map((q: any) => q.brand_name.toLowerCase())
  if (new Set(brandNames).size !== brandNames.length) {
    ElMessage.warning('同一品牌不能重复报价')
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
      product_year: form.product_year,
      season: form.season,
      image_url: form.image_url || null,
      fabric: form.fabric?.trim() || null,
      lining: form.lining?.trim() || null,
      shoe_last_id: form.shoe_last_id || null,
      shoe_last_hours:
        form.shoe_last_hours != null && form.shoe_last_hours !== ''
          ? Number(form.shoe_last_hours)
          : null,
      color_ids: form.color_ids || [],
      materials: materials.map((m: any, i: number) => {
        const sp = spById(m.supplier_product_id)
        const cat = sp?.category_id
          ? materialCategories.value.find((c: any) => c.id === sp.category_id)
          : null
        const usageBySize = !!cat?.suggest_usage_by_size
        return {
          supplier_product_id: m.supplier_product_id,
          qty: m.qty ?? 0,
          sort_order: i,
          consume_segment_id: m.consume_segment_id || null,
          usage_by_size: usageBySize,
          size_usage_table_id: usageBySize
            ? (cat?.default_size_usage_table_id ?? null)
            : null,
          loss_rate: 0,
          loss_fixed_qty: 0,
        }
      }),
      labors: labors.map((l: any, i: number) => ({
        process_name: l.process_name,
        requirement_note: String(l.requirement_note || '').trim() || null,
        unit_price: l.unit_price ?? 0,
        sort_order: i,
        segment_id: l.segment_id ?? null,
      })),
      other_costs: otherCosts.map((o: any, i: number) => ({
        name: o.name,
        amount: o.amount ?? 0,
        sort_order: i,
      })),
      commissions: commissions.map((c: any, i: number) => ({
        employee_id: c.employee_id || null,
        amount: c.amount ?? 0,
        sort_order: i,
      })),
      quotes: quotes.map((q: any, i: number) => ({
        partner_id: q.partner_id,
        quote_price: q.quote_price ?? 0,
        sort_order: i,
      })),
      brand_quotes: brandQuotes.map((q: any, i: number) => ({
        brand_name: q.brand_name,
        quote_price: q.quote_price ?? 0,
        sort_order: i,
      })),
      quote_price: form.quote_price != null && form.quote_price !== '' ? form.quote_price : null,
      segment_ref_prices: segmentRefPricesPayload(),
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

.year-picker {
  width: 140px !important;
}

.season-select {
  width: 164px;
}

.shoe-last-select {
  width: 180px;
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

.gallery-title {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 6px;
  overflow: hidden;
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
  flex: 1 1 auto;
  max-width: 100%;
}

.gallery-color-inline {
  min-width: 0;
  max-width: 40%;
  flex: 0 1 auto;
  font-size: 12px;
  font-weight: 600;
  color: #0369a1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.25;
}

.gallery-color-inline.is-missing {
  color: #b45309;
  font-weight: 500;
}

.gallery-cost {
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 750;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}

.gallery-meta-line {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.35;
  min-width: 0;
}

.gallery-meta-line span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.gallery-meta-line--split {
  justify-content: space-between;
  align-items: baseline;
  flex-wrap: nowrap;
  gap: 8px;
}

.gallery-meta-line--split .gallery-last {
  flex: 1 1 auto;
  min-width: 0;
  text-align: left;
}

.gallery-meta-line--split .gallery-year-season {
  flex: 0 0 auto;
  text-align: right;
  white-space: nowrap;
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
  grid-template-columns: 1fr;
  gap: 20px;
  min-height: 0;
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
  margin-bottom: 8px;
}

.dev-panel {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: #fff;
  padding: 10px 12px;
  min-width: 0;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
}

.shoe-panel {
  background:
    linear-gradient(180deg, #f8fbff 0%, #ffffff 80px);
}

.product-info-table :deep(.el-table__cell) {
  vertical-align: middle;
  padding: 6px 8px;
}

.product-info-table :deep(.el-table__header th.el-table__cell) {
  padding: 2px 6px !important;
  height: auto;
  line-height: 1.15;
}

.product-info-table :deep(.el-table__header th.is-group) {
  padding: 0 6px !important;
  font-size: 11px;
  letter-spacing: 0.08em;
}

.product-info-table :deep(.el-table__header .cell) {
  line-height: 1.15;
  padding-top: 0;
  padding-bottom: 0;
  white-space: nowrap;
}

.product-info-table :deep(.el-table__header th.is-group > .cell) {
  line-height: 1.1;
  padding: 1px 0;
}

.product-quotes-block {
  margin-top: 10px;
}

.quotes-side-by-side {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 48px;
  margin-top: 10px;
  align-items: start;
}

.quotes-side-by-side .product-quotes-block {
  margin-top: 0;
  min-width: 0;
}

@media (max-width: 900px) {
  .quotes-side-by-side {
    grid-template-columns: 1fr;
  }
}

.shoe-image-box--table {
  width: 100%;
  margin: 0;
}

.order-qty-cell {
  font-variant-numeric: tabular-nums;
}

.panel-title {
  font-size: 14px;
  font-weight: 750;
  margin-bottom: 8px;
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
  justify-content: flex-start;
  gap: 10px;
  margin-bottom: 8px;
}

.panel-title-row .panel-title {
  margin-bottom: 0;
}

.labor-title {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed var(--line);
}

.cost-summary-line,
.other-cost-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 8px;
  font-size: 13px;
  color: #606266;
}

.other-cost-one-row-table :deep(.el-table__header .cell) {
  padding: 6px 8px;
}
.other-cost-amount-input {
  width: 100%;
}
.other-cost-amount-input :deep(.el-input__wrapper) {
  padding-left: 8px;
  padding-right: 8px;
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

.quote-price-cell {
  display: flex;
  align-items: center;
  gap: 2px;
  min-width: 0;
}

.quote-price-cell .el-input-number {
  flex: 1;
  min-width: 0;
}

.quote-price-cell .el-button {
  flex-shrink: 0;
  margin: 0;
  padding: 0 2px;
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
  margin-top: 0;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0 10px;
  align-content: start;
}

.edit-total-cost {
  width: 100%;
  min-height: 34px;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 8px;
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
  font-size: 18px;
  font-weight: 750;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}

.color-select-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
}

.color-add-btn {
  padding: 5px 8px;
  min-width: 28px;
  flex-shrink: 0;
  border: none;
  background: transparent;
}
.color-add-btn:hover,
.color-add-btn:focus {
  border: none;
  background: transparent;
  color: var(--el-color-primary);
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
  margin-top: 0;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px 12px;
  align-content: start;
}

.detail-meta-row {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px;
  align-items: start;
  font-size: 13px;
  min-width: 0;
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

.detail-meta-row > b.detail-total-cost,
.detail-total-cost {
  color: var(--accent);
  font-weight: 750;
  font-variant-numeric: tabular-nums;
}

.detail-meta-quotes {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 2px;
  padding-top: 8px;
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
  margin-top: 10px;
  padding-top: 8px;
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
  margin-bottom: 8px;
}

.shoe-form :deep(.el-form-item__label) {
  color: #64748b;
  font-weight: 600;
  padding-bottom: 2px !important;
  line-height: 1.2;
}

.shoe-form :deep(.quote-form-item) {
  margin-bottom: 0;
  grid-column: 1 / -1;
}

.shoe-image-box {
  position: relative;
  width: 120px;
  flex-shrink: 0;
  cursor: pointer;
  outline: none;
  border-radius: 10px;
  transition: transform 0.2s ease;
}

.shoe-image-box--table {
  width: 100%;
}

.shoe-image-box:hover .shoe-preview,
.shoe-image-box:hover .product-thumb--empty {
  border-color: #80baff;
  box-shadow: 0 8px 22px rgba(0, 118, 255, 0.14);
}

.shoe-image-box:hover .shoe-preview.empty,
.shoe-image-box:hover .product-thumb--empty {
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

.shoe-image-box.is-dragging .shoe-preview,
.shoe-image-box.is-dragging .product-thumb--empty {
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
  top: 0;
  right: 0;
  z-index: 2;
  border: none;
  border-radius: 0 8px 0 6px;
  padding: 2px 6px;
  font-size: 11px;
  line-height: 1.2;
  color: #fff;
  background: rgba(17, 24, 39, 0.72);
  cursor: pointer;
}

.shoe-clear-btn:hover {
  background: rgba(220, 38, 38, 0.9);
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

:deep(td.mat-image-col .product-thumb--empty) {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  font-size: 11px;
  border: 1px dashed var(--line);
  background:
    repeating-linear-gradient(
      -45deg,
      #fff,
      #fff 6px,
      #f1f5f9 6px,
      #f1f5f9 12px
    );
}

:deep(td.mat-image-col .product-thumb .el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

:deep(td.mat-image-col .shoe-image-box) {
  width: 100%;
  border-radius: 4px;
}

:deep(td.mat-image-col .shoe-drop-mask) {
  border-radius: 4px;
}

:deep(td.mat-image-col .shoe-clear-btn) {
  border-radius: 0 4px 0 4px;
  padding: 1px 4px;
  font-size: 10px;
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
  .product-card {
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
  background: #b8c2ce;
}
.dev-dialog .el-dialog__header {
  margin-right: 0;
  padding: 12px 14px 10px;
  border-bottom: none;
  background: #b8c2ce;
}
.dev-dialog .el-dialog__body {
  padding: 8px 10px 10px;
  background: #b8c2ce;
}
.dev-dialog .el-dialog__footer {
  padding: 10px 14px 14px;
  border-top: 1px solid #eef2f7;
  background: #b8c2ce;
}
.detail-price-history-popper {
  max-width: 320px;
  padding: 8px 10px !important;
}
.detail-price-history-tip-title {
  font-size: 12px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 6px;
}
.detail-price-history-tip-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 0;
  border-top: 1px solid #eef2f7;
  font-size: 12px;
  line-height: 1.4;
}
.detail-price-history-tip-row:first-of-type {
  border-top: none;
  padding-top: 0;
}
.detail-price-history-tip-price {
  font-weight: 600;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}
.detail-price-history-tip-meta {
  color: #64748b;
}
.product-version-list {
  display: grid;
  gap: 6px;
  max-height: 60vh;
  overflow: auto;
}
.product-version-item {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  text-align: left;
  cursor: pointer;
}
.product-version-item:hover:not(:disabled) {
  border-color: var(--el-color-primary-light-5);
  background: #f8fafc;
}
.product-version-item:disabled {
  opacity: 0.6;
  cursor: wait;
}
.product-version-main {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}
.product-version-no {
  flex-shrink: 0;
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}
.product-version-meta {
  min-width: 0;
  color: #64748b;
  font-size: 13px;
}
.product-version-changes {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.product-version-tag {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: 999px;
  background: #fff7ed;
  color: #c2410c;
  border: 1px solid #fed7aa;
  font-size: 12px;
  line-height: 1.5;
}
.product-version-tag.is-muted {
  background: #f1f5f9;
  color: #64748b;
  border-color: #e2e8f0;
}
</style>

<style scoped>
.labor-segments {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  align-items: start;
}
.labor-seg-block {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
  min-width: 0;
}
.labor-seg-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 6px;
  padding: 8px 10px;
  background: #f8fafc;
}
.labor-seg-head-main {
  display: flex;
  flex-direction: row;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
  flex: 1;
}
.labor-seg-name {
  font-weight: 600;
  font-size: 13px;
}
.labor-seg-sub {
  font-size: 12px;
}
.labor-seg-rows {
  padding: 8px 10px;
  display: grid;
  gap: 10px;
}
.labor-seg-row {
  display: grid;
  gap: 6px;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}
.labor-seg-row:last-child {
  padding-bottom: 0;
  border-bottom: none;
}
.labor-seg-row-top {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}
.labor-seg-process {
  flex: 1 1 auto;
  min-width: 0;
  width: 0;
}
.process-select-footer {
  padding: 6px 8px 4px;
  border-top: 1px solid #eef2f7;
}
.process-select-footer-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
}
.labor-seg-price-wrap {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}
.labor-seg-price {
  width: 52px;
  flex: 0 0 52px;
}
.labor-seg-price :deep(.el-input__wrapper) {
  padding-left: 4px;
  padding-right: 4px;
}
.labor-price-history-btn {
  padding: 0 2px;
  flex-shrink: 0;
}
.labor-price-history {
  max-height: 280px;
  overflow: auto;
}
.labor-price-history-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  width: 100%;
  padding: 8px 6px;
  border: none;
  border-bottom: 1px solid #eef2f7;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.labor-price-history-item:last-child {
  border-bottom: none;
}
.labor-price-history-item:hover {
  background: #f5f9ff;
}
.labor-price-history-item.is-readonly {
  cursor: default;
}
.labor-price-history-item.is-readonly:hover {
  background: transparent;
}
.labor-price-history-price {
  font-size: 14px;
  font-weight: 700;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}
.labor-price-history-meta {
  font-size: 12px;
  line-height: 1.35;
}
.labor-seg-unit {
  flex-shrink: 0;
  font-size: 12px;
  white-space: nowrap;
}
.labor-seg-ref-label {
  flex-shrink: 0;
  font-size: 12px;
  white-space: nowrap;
}
.labor-seg-ref-price {
  width: 64px;
  flex-shrink: 0;
}
.labor-seg-ref-price :deep(.el-input__wrapper) {
  padding-left: 4px;
  padding-right: 4px;
}
.labor-seg-note-wrap {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  width: 100%;
}
.labor-seg-note {
  flex: 1;
  min-width: 0;
}
.labor-seg-note :deep(.el-textarea__inner) {
  resize: vertical;
  line-height: 1.45;
}
.labor-note-history-btn {
  flex-shrink: 0;
  margin-top: 4px;
  padding: 0 2px;
}
.labor-note-history {
  max-height: 240px;
  overflow: auto;
}
.labor-note-history-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  width: 100%;
  padding: 8px 6px;
  border: none;
  border-bottom: 1px solid #eef2f7;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.labor-note-history-item:last-child {
  border-bottom: none;
}
.labor-note-history-item:hover {
  background: #f5f9ff;
}
.labor-note-history-text {
  font-size: 13px;
  color: var(--ink);
  line-height: 1.4;
  white-space: pre-wrap;
  word-break: break-word;
}
.route-template-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 360px;
  overflow: auto;
}
.route-template-item {
  display: block;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  text-align: left;
  cursor: pointer;
}
.route-template-item:hover {
  border-color: #80baff;
}
.route-template-item.is-active {
  border-color: #0076ff;
  background: #f0f7ff;
}
.route-template-name {
  font-size: 14px;
  font-weight: 650;
  color: var(--ink);
}
.route-template-meta {
  margin-top: 4px;
  font-size: 12px;
}
.labor-seg-empty {
  padding: 10px;
  font-size: 12px;
}
.detail-labor-groups {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  align-items: start;
}
.detail-labor-group {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  overflow: hidden;
  min-width: 0;
  margin-bottom: 0;
}
.detail-labor-group-head {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 6px 10px;
  background: #f8fafc;
  font-size: 12px;
  font-weight: 600;
}
.detail-labor-group-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  font-weight: 500;
  width: 100%;
}
.detail-labor-row {
  display: grid;
  gap: 2px;
  padding: 6px 10px;
  border-top: 1px solid var(--el-border-color-lighter);
  font-size: 13px;
}
.detail-labor-line {
  display: flex;
  align-items: baseline;
  gap: 4px;
  min-width: 0;
  width: 100%;
}
.detail-labor-name {
  flex: 1;
  min-width: 0;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.detail-labor-line .money {
  flex-shrink: 0;
  margin-left: auto;
  text-align: right;
}
.detail-price-history-icon {
  flex-shrink: 0;
  color: #64748b;
  cursor: help;
  margin-left: 2px;
  outline: none;
  vertical-align: middle;
}
.detail-price-history-icon:hover {
  color: var(--el-color-primary);
}
.detail-labor-unit {
  flex-shrink: 0;
  font-size: 12px;
  white-space: nowrap;
}
.detail-labor-note {
  margin-top: 6px;
  font-size: 12px;
}
.detail-labor-note-label {
  line-height: 1.4;
}
.detail-labor-note-body {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.45;
}
</style>
