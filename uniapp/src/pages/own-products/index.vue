<template>
  <view class="page h5-dev" :class="{ 'h5-dev--bar': showBar }">
    <view v-if="!canSee" class="h5-home-empty">没有产品开发权限</view>

    <template v-else-if="mode === 'list'">
      <view class="card h5-dev-search">
        <input :value="keyword" confirm-type="search" placeholder="搜索工厂型号" @input="onKeyword" @confirm="search" />
        <text v-if="keyword" @click="clearKeyword">清除</text>
      </view>
      <view class="h5-dev-chips">
        <text v-for="item in statusItems" :key="item.value" :class="{ on: status === item.value }" @click="setStatus(item.value)">{{ item.label }}</text>
      </view>

      <view v-if="loading && !rows.length" class="h5-home-empty">正在读取产品…</view>
      <view v-else-if="!rows.length" class="h5-home-empty">{{ keyword ? '没有匹配的工厂型号' : '还没有产品' }}</view>
      <view v-else>
        <view v-for="row in rows" :key="row.id" class="card h5-dev-card" @click="openDetail(row.id)">
          <image v-if="row.image_url" :src="displayImageUrl(row.image_url)" mode="aspectFill" />
          <view v-else class="h5-dev-swatch">{{ swatch(row) }}</view>
          <view class="h5-dev-card__body">
            <view class="h5-dev-card__top">
              <strong>{{ row.product_code }}</strong>
              <text class="h5-dev-status" :class="row.approval_status === 'pending' ? 'pending' : 'approved'">{{ statusLabel(row.approval_status) }}</text>
            </view>
            <text>{{ colorText(row) }}</text>
            <text>{{ metaText(row) }}</text>
          </view>
        </view>
        <view class="h5-dev-more">{{ rows.length >= total ? `共 ${total} 款` : '上拉加载更多' }}</view>
      </view>
    </template>

    <template v-else-if="mode === 'detail' && current">
      <view class="card h5-dev-hero">
        <image v-if="current.image_url" :src="displayImageUrl(current.image_url)" mode="aspectFill" @click="previewImage(current.image_url)" />
        <view v-else class="h5-dev-swatch h5-dev-swatch--lg">{{ swatch(current) }}</view>
        <view>
          <strong>{{ current.product_code }}</strong>
          <text class="h5-dev-status" :class="current.approval_status === 'pending' ? 'pending' : 'approved'">{{ statusLabel(current.approval_status) }}</text>
          <text class="h5-dev-hero__meta">{{ metaText(current) || '未填年份季节' }}</text>
        </view>
      </view>

      <scroll-view v-if="detailBom.groups.length > 1" class="h5-dev-colors" scroll-x :show-scrollbar="false">
        <text v-for="group in detailBom.groups" :key="group.colorId" :class="{ on: group.colorId === activeColorId }" @click="detailColorId = group.colorId">{{ group.name }}</text>
      </scroll-view>

      <view class="card h5-dev-cost">
        <view class="h5-dev-cost__grid">
          <view><text>物料</text><strong>{{ money(activeColorGroup ? activeColorGroup.pair : detailBom.sharedCost) }}</strong></view>
          <view><text>人工</text><strong>{{ money(current.labor_cost) }}</strong></view>
          <view><text>提成</text><strong>{{ money(current.commission_cost) }}</strong></view>
          <view><text>其它</text><strong>{{ money(current.other_cost) }}</strong></view>
        </view>
        <view class="h5-dev-cost__total">
          <text>{{ activeColorGroup ? `${activeColorGroup.name} 单双成本` : '单双成本' }}</text>
          <strong>{{ money(detailTotal) }}</strong>
        </view>
      </view>

      <view class="card h5-dev-block">
        <view class="h5-dev-block__head"><text>基础信息</text></view>
        <view class="h5-dev-facts">
          <view v-for="fact in detailFacts" :key="fact.label">
            <text>{{ fact.label }}</text>
            <strong>{{ fact.value }}</strong>
          </view>
        </view>
      </view>

      <view class="card h5-dev-block">
        <view class="h5-dev-block__head"><text>客户报价</text><view class="h5-dev-block__side"><text>{{ quoteCount(current.quotes) }}</text><text v-if="canWrite" class="h5-dev-edit" @click="openSection('quotes')">编辑</text></view></view>
        <view v-if="!(current.quotes || []).length" class="h5-dev-empty">暂无特殊客户报价</view>
        <view v-for="quote in current.quotes" :key="quote.id" class="h5-dev-pair">
          <text>{{ quote.partner_short_name || quote.partner_name || '客户' }}</text>
          <strong>{{ money(quote.quote_price) }}</strong>
        </view>
      </view>

      <view class="card h5-dev-block">
        <view class="h5-dev-block__head"><text>品牌报价</text><view class="h5-dev-block__side"><text>{{ quoteCount(current.brand_quotes) }}</text><text v-if="canWrite" class="h5-dev-edit" @click="openSection('brands')">编辑</text></view></view>
        <view v-if="!(current.brand_quotes || []).length" class="h5-dev-empty">暂无特殊品牌报价</view>
        <view v-for="quote in current.brand_quotes" :key="quote.id" class="h5-dev-pair">
          <text>{{ quote.brand_name || '品牌' }}</text>
          <strong>{{ money(quote.quote_price) }}</strong>
        </view>
      </view>

      <view class="card h5-dev-block">
        <view class="h5-dev-block__head">
          <text>物料{{ activeColorGroup ? ` · ${activeColorGroup.name}` : '' }}</text>
          <view class="h5-dev-block__side"><text>{{ materialCount }} 项</text><text v-if="canWrite" class="h5-dev-edit" @click="openSection('materials')">编辑</text></view>
        </view>
        <view v-if="detailBom.shared.length" class="h5-dev-subhead">共用 · {{ money(detailBom.sharedCost) }}</view>
        <view v-for="item in detailBom.shared" :key="`shared-${item.id}`" class="h5-dev-mat">
          <image v-if="item.image_url" :src="displayImageUrl(item.image_url)" mode="aspectFill" @click="previewMaterials(item, detailBom.shared)" />
          <view v-else class="h5-dev-swatch h5-dev-swatch--sm">{{ materialMark(item) }}</view>
          <view>
            <view class="h5-dev-mat__top"><strong>{{ item.supplier_product_code || item.supplier_product_name || '物料' }}</strong><text>{{ money(item.line_total) }}</text></view>
            <text>{{ materialLine(item) }}</text>
            <text>{{ materialQty(item) }}</text>
          </view>
        </view>
        <view v-if="activeColorGroup" class="h5-dev-subhead">{{ activeColorGroup.name }} · {{ money(activeColorGroup.fabric) }}</view>
        <view v-if="activeColorGroup && !activeColorGroup.rows.length" class="h5-dev-empty">这个颜色没有单独物料</view>
        <view v-for="item in activeColorGroup?.rows || []" :key="item.id" class="h5-dev-mat">
          <image v-if="item.image_url" :src="displayImageUrl(item.image_url)" mode="aspectFill" @click="previewMaterials(item, activeColorGroup.rows)" />
          <view v-else class="h5-dev-swatch h5-dev-swatch--sm">{{ materialMark(item) }}</view>
          <view>
            <view class="h5-dev-mat__top"><strong>{{ item.supplier_product_code || item.supplier_product_name || '物料' }}</strong><text>{{ money(item.line_total) }}</text></view>
            <text>{{ materialLine(item) }}</text>
            <text>{{ materialQty(item) }}</text>
          </view>
        </view>
        <view v-if="!detailBom.shared.length && !activeColorGroup" class="h5-dev-empty">暂无物料</view>
      </view>

      <view class="card h5-dev-block">
        <view class="h5-dev-block__head"><text>工艺路线</text><view class="h5-dev-block__side"><text>{{ (current.labors || []).length }} 道</text><text v-if="canWrite && (current.labors || []).length" class="h5-dev-edit" @click="openSection('labors')">编辑</text></view></view>
        <view v-if="!detailLaborGroups.length" class="h5-dev-empty">暂无工序</view>
        <view v-for="group in detailLaborGroups" :key="group.key" class="h5-dev-route">
          <view class="h5-dev-route__head">
            <text>{{ group.name }}</text>
            <strong>{{ money(laborSection(group).subtotal) }}</strong>
          </view>
          <view v-if="group.split" class="h5-dev-mini">
            <text v-for="section in group.sections" :key="section.key" :class="{ on: laborSection(group).key === section.key }" @click="pickDept(group.key, section.key)">{{ section.name }}</text>
          </view>
          <view v-if="!laborSection(group).items.length" class="h5-dev-empty">暂无工序</view>
          <view v-for="labor in laborSection(group).items" :key="labor.id" class="h5-dev-labor">
            <view><strong>{{ labor.process_name || '工序' }}</strong><text>{{ money(labor.unit_price) }}</text></view>
            <text v-if="labor.requirement_note">{{ labor.requirement_note }}</text>
          </view>
          <text v-if="group.refPrice" class="h5-dev-ref">参考价 {{ money(group.refPrice) }}</text>
        </view>
      </view>

      <view class="card h5-dev-block">
        <view class="h5-dev-block__head"><text>设计师提成</text><view class="h5-dev-block__side"><text>{{ quoteCount(current.commissions) }}</text><text v-if="canWrite" class="h5-dev-edit" @click="openSection('commissions')">编辑</text></view></view>
        <view v-if="!(current.commissions || []).length" class="h5-dev-empty">暂无设计师提成</view>
        <view v-for="row in current.commissions" :key="row.id" class="h5-dev-pair">
          <text>{{ row.employee_name || '未选人' }}</text>
          <strong>{{ money(row.amount) }}</strong>
        </view>
      </view>

      <view class="card h5-dev-block">
        <view class="h5-dev-block__head"><text>管理提成</text><view class="h5-dev-block__side"><text>{{ quoteCount(current.mgmt_commissions) }}</text><text v-if="canWrite" class="h5-dev-edit" @click="openSection('mgmt')">编辑</text></view></view>
        <view v-if="!(current.mgmt_commissions || []).length" class="h5-dev-empty">暂无管理提成</view>
        <view v-for="row in current.mgmt_commissions" :key="row.id" class="h5-dev-pair">
          <text>{{ row.job_title_name || '职务' }}</text>
          <strong>{{ money(row.amount) }}</strong>
        </view>
      </view>

      <view class="card h5-dev-block">
        <view class="h5-dev-block__head"><text>其它成本</text><view class="h5-dev-block__side"><text>{{ quoteCount(current.other_costs) }}</text><text v-if="canWrite" class="h5-dev-edit" @click="openSection('costs')">编辑</text></view></view>
        <view v-if="!(current.other_costs || []).length" class="h5-dev-empty">暂无其它成本</view>
        <view v-for="row in current.other_costs" :key="row.id" class="h5-dev-pair">
          <text>{{ row.name }}</text>
          <strong>{{ money(row.amount) }}</strong>
        </view>
      </view>

      <view v-if="(current.parts || []).length" class="card h5-dev-block">
        <view class="h5-dev-block__head"><text>部件</text><text>{{ current.parts.length }}</text></view>
        <view v-for="part in current.parts" :key="part.id" class="h5-dev-pair">
          <text>{{ part.part_name || part.part_code || '部件' }}{{ part.part_source ? ` · ${part.part_source}` : '' }}</text>
          <strong>{{ part.pieces_per_pair || 0 }} 片/双</strong>
        </view>
      </view>
    </template>

    <template v-else-if="mode === 'form'">
      <view class="card h5-dev-photo" @click="choosePhoto">
        <image v-if="form.image_url" :src="displayImageUrl(form.image_url)" mode="aspectFill" />
        <view v-else class="h5-dev-photo__empty">
          <text>{{ uploading ? '正在上传…' : '添加产品图' }}</text>
          <text>拍照或从相册选择</text>
        </view>
      </view>

      <view class="card h5-dev-form">
        <view class="h5-dev-field">
          <text>工厂型号</text>
          <input v-model="form.product_code" maxlength="64" placeholder="必填" />
        </view>
        <view class="h5-dev-field" @click="openColorPicker">
          <text>颜色</text>
          <strong :class="{ mute: !form.color_ids.length }">{{ selectedColorText }}</strong>
        </view>
        <view class="h5-dev-field">
          <text>面料</text>
          <input v-model="form.fabric" maxlength="80" placeholder="选填" />
        </view>
        <view class="h5-dev-field">
          <text>里料</text>
          <input v-model="form.lining" maxlength="80" placeholder="选填" />
        </view>
        <view class="h5-dev-field" @click="openMaterialPicker('last')">
          <text>楦型</text>
          <strong :class="{ mute: !form.shoe_last_product_id }">{{ form.shoe_last_label || '从楦头色卡选择' }}</strong>
          <text v-if="form.shoe_last_product_id" class="h5-dev-clear" @click.stop="clearMaterial('last')">清除</text>
        </view>
        <view class="h5-dev-field">
          <text>楦头占用</text>
          <input v-model="form.shoe_last_hours" type="digit" placeholder="小时，选填" />
        </view>
        <view class="h5-dev-field" @click="openMaterialPicker('sole')">
          <text>鞋底型号</text>
          <strong :class="{ mute: !form.sole_mold_product_id }">{{ form.sole_mold_label || '从大底色卡选择' }}</strong>
          <text v-if="form.sole_mold_product_id" class="h5-dev-clear" @click.stop="clearMaterial('sole')">清除</text>
        </view>
        <view class="h5-dev-field" @click="openMaterialPicker('heel')">
          <text>鞋跟型号</text>
          <strong :class="{ mute: !form.heel_model_id }">{{ form.heel_model_label || '从鞋跟色卡选择' }}</strong>
          <text v-if="form.heel_model_id" class="h5-dev-clear" @click.stop="clearMaterial('heel')">清除</text>
        </view>
        <view class="h5-dev-field">
          <text>年份</text>
          <input v-model="form.product_year" type="number" maxlength="4" placeholder="如 2026" />
        </view>
        <view class="h5-dev-field h5-dev-field--season">
          <text>季节</text>
          <view class="h5-dev-seasons">
            <text v-for="item in seasons" :key="item.value" :class="{ on: form.season === item.value }" @click="form.season = item.value">{{ item.label }}</text>
          </view>
        </view>
        <view class="h5-dev-field">
          <text>统一报价</text>
          <input v-model="form.quote_price" type="digit" placeholder="元/双，选填" />
        </view>
      </view>
    </template>

    <template v-else-if="mode === 'section'">
      <view v-if="section === 'materials'" class="card h5-dev-block">
        <view class="h5-dev-block__head"><text>物料</text><text>点一行改用量</text></view>
        <scroll-view class="h5-dev-colors" scroll-x :show-scrollbar="false">
          <text :class="{ on: materialColorId == null }" @click="materialColorId = null">共用</text>
          <text v-for="color in current?.colors || []" :key="color.id" :class="{ on: materialColorId === color.id }" @click="materialColorId = color.id">{{ color.name }}</text>
        </scroll-view>
        <view v-if="!editingMaterialRows.length" class="h5-dev-empty">这个颜色还没有物料</view>
        <view v-for="item in editingMaterialRows" :key="item.key" class="h5-dev-mat" @click="openMaterialLine(item)">
          <image v-if="item.image_url" :src="displayImageUrl(item.image_url)" mode="aspectFill" />
          <view v-else class="h5-dev-swatch h5-dev-swatch--sm">{{ materialMark(item) }}</view>
          <view>
            <view class="h5-dev-mat__top"><strong>{{ item.supplier_product_code || item.supplier_product_name || '物料' }}</strong><text>{{ item.consume_segment_name || '未选消耗部门' }}</text></view>
            <text>{{ materialLine(item) }}</text>
            <text>用量 {{ item.qtyText || '0' }}{{ item.pricing_unit_name ? ` ${item.pricing_unit_name}` : '' }}</text>
          </view>
        </view>
        <text class="h5-dev-inline" @click="openSheet('catalog')">添加物料</text>
      </view>

      <view v-else-if="section === 'labors'" class="card h5-dev-block">
        <view class="h5-dev-block__head"><text>工艺路线</text><text>只改单价和要求</text></view>
        <view v-if="!editLaborGroups.length" class="h5-dev-empty">还没有工序，请在电脑端添加</view>
        <view v-for="group in editLaborGroups" :key="group.key" class="h5-dev-route">
          <view class="h5-dev-route__head">
            <text>{{ group.name }}</text>
            <strong>{{ money(laborSection(group).subtotal) }}</strong>
          </view>
          <view v-if="group.split" class="h5-dev-mini">
            <text v-for="part in group.sections" :key="part.key" :class="{ on: laborSection(group).key === part.key }" @click="pickDept(group.key, part.key)">{{ part.name }}</text>
          </view>
          <view v-for="labor in laborSection(group).items" :key="labor.key" class="h5-dev-labor">
            <view><strong>{{ labor.process_name || '工序' }}</strong><input v-model="labor.priceText" class="h5-dev-price" type="digit" placeholder="单价" /></view>
            <textarea v-model="labor.noteText" class="h5-dev-note" maxlength="500" auto-height placeholder="工艺要求，选填" />
          </view>
          <text v-if="group.refPrice" class="h5-dev-ref">参考价 {{ money(group.refPrice) }}，手机上不改</text>
        </view>
      </view>

      <view v-else class="card h5-dev-block">
        <view class="h5-dev-block__head"><text>{{ sectionTitle }}</text></view>
        <view v-if="!draftRows.length" class="h5-dev-empty">还没有内容</view>
        <view v-for="row in draftRows" :key="row.key" class="h5-dev-editrow">
          <input v-if="section === 'costs'" v-model="row.label" maxlength="40" placeholder="项目名称" />
          <text v-else class="h5-dev-editrow__name">{{ row.label }}</text>
          <input v-model="row.priceText" class="h5-dev-price" type="digit" placeholder="金额" />
          <text class="h5-dev-del" @click="removeDraft(row.key)">删除</text>
        </view>
        <text v-if="section === 'costs'" class="h5-dev-inline" @click="addCostRow">添加项目</text>
        <text v-else class="h5-dev-inline" @click="openSheet(sectionSheet)">{{ sectionAddLabel }}</text>
      </view>
    </template>

    <view v-if="showBar" class="cut-sticky-bar h5-dev-bar">
      <text v-if="mode === 'form' || mode === 'section'" class="h5-dev-hint">{{ canApprove ? '保存后直接生效' : '保存后进入待审批' }}</text>
      <view class="h5-dev-bar__row">
        <button v-if="mode === 'list'" class="cut-sticky-button" @click="startCreate">新建产品</button>
        <button v-if="mode === 'detail' && canWrite" class="h5-dev-ghost" @click="startEdit">基础信息</button>
        <button v-if="mode === 'section'" class="cut-sticky-button" :disabled="saving" @click="saveSection">{{ saving ? '保存中…' : '保存' }}</button>
        <button v-if="mode === 'detail' && canApprove && current?.approval_status === 'pending'" class="cut-sticky-button" :disabled="saving" @click="approve">通过审批</button>
        <button v-if="mode === 'form'" class="cut-sticky-button" :disabled="saving || uploading" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
      </view>
    </view>

    <view v-if="picker" class="h5-dev-mask" @click="closePicker">
      <view class="h5-dev-sheet" @click.stop>
        <view class="h5-dev-sheet__head">
          <strong>{{ pickerTitle }}</strong>
          <text @click="closePicker">完成</text>
        </view>
        <view v-if="picker !== 'color'" class="h5-dev-sheet__search">
          <input :value="materialKeyword" confirm-type="search" placeholder="搜索编号或名称" @input="onMaterialKeyword" />
        </view>
        <view v-else class="h5-dev-sheet__search">
          <input :value="colorKeyword" placeholder="搜索颜色" @input="onColorKeyword" />
        </view>
        <scroll-view scroll-y class="h5-dev-sheet__list">
          <view v-if="picker === 'color'">
            <view v-if="!filteredColors.length" class="h5-dev-sheet__empty">没有可选颜色</view>
            <view v-for="color in filteredColors" :key="color.id" class="h5-dev-option" @click="toggleColor(color.id)">
              <text>{{ color.name }}</text>
              <text class="h5-dev-check" :class="{ on: form.color_ids.includes(color.id) }">{{ form.color_ids.includes(color.id) ? '已选' : '' }}</text>
            </view>
          </view>
          <view v-else-if="materialLoading" class="h5-dev-sheet__empty">正在查找…</view>
          <view v-else-if="!materials.length" class="h5-dev-sheet__empty">没有匹配的色卡</view>
          <template v-else>
            <view v-for="item in materials" :key="item.id" class="h5-dev-option" @click="pickMaterial(item)">
              <text>{{ item.product_code }}</text>
              <text class="h5-dev-option__sub">{{ materialSub(item) }}</text>
            </view>
          </template>
        </scroll-view>
      </view>
    </view>

    <view v-if="sheet" class="h5-dev-mask" @click="closeSheet">
      <view class="h5-dev-sheet" @click.stop>
        <view class="h5-dev-sheet__head">
          <strong>{{ sheetTitle }}</strong>
          <text @click="closeSheet">{{ sheet === 'line' ? '完成' : '关闭' }}</text>
        </view>
        <template v-if="sheet === 'line' && lineEdit">
          <view class="h5-dev-field"><text>用量</text><input v-model="lineEdit.qtyText" type="digit" placeholder="必填" /></view>
          <view class="h5-dev-field"><text>损耗%</text><input v-model="lineEdit.lossRateText" type="digit" placeholder="选填" /></view>
          <view class="h5-dev-field"><text>固定损耗</text><input v-model="lineEdit.lossFixedText" type="digit" placeholder="选填" /></view>
          <view class="h5-dev-field h5-dev-field--season">
            <text>消耗部门</text>
            <view class="h5-dev-seasons">
              <text v-for="seg in segments" :key="seg.id" :class="{ on: lineEdit.consume_segment_id === seg.id }" @click="chooseSegment(seg)">{{ seg.name }}</text>
            </view>
          </view>
          <text v-if="!segments.length" class="h5-dev-empty">还没有工序段，请先在电脑端维护</text>
          <text class="h5-dev-del h5-dev-inline" @click="removeMaterialLine">删除这行</text>
        </template>
        <template v-else>
          <view class="h5-dev-sheet__search">
            <input :value="sheetKeyword" confirm-type="search" :placeholder="sheet === 'employee' || sheet === 'catalog' ? '搜索' : '筛选'" @input="onSheetKeyword" />
          </view>
          <scroll-view scroll-y class="h5-dev-sheet__list">
            <view v-if="sheetLoading" class="h5-dev-sheet__empty">正在查找…</view>
            <view v-else-if="!sheetVisible.length" class="h5-dev-sheet__empty">没有可选项</view>
            <template v-else>
              <view v-for="item in sheetVisible" :key="item.id" class="h5-dev-option" @click="pickSheet(item)">
                <text>{{ item.label }}</text>
                <text v-if="item.sub" class="h5-dev-option__sub">{{ item.sub }}</text>
              </view>
            </template>
          </scroll-view>
        </template>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { onBackPress, onPullDownRefresh, onReachBottom, onShow } from '@dcloudio/uni-app'
import { get, patch, post, uploadFile } from '../../services/http'
import { getProfile } from '../../services/storage'

type Mode = 'list' | 'detail' | 'form' | 'section'
type Section = 'quotes' | 'brands' | 'materials' | 'labors' | 'commissions' | 'mgmt' | 'costs'
type StatusFilter = 'all' | 'pending' | 'approved'
type Picker = '' | 'color' | 'last' | 'sole' | 'heel'
type Sheet = '' | 'customer' | 'brand' | 'employee' | 'title' | 'catalog' | 'line'
type CardKind = 'last' | 'sole' | 'heel'

const seasons = [
  { value: 'SP', label: '春' },
  { value: 'SU', label: '夏' },
  { value: 'AU', label: '秋' },
  { value: 'WI', label: '冬' },
]
const statusItems: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: '待审批' },
  { value: 'approved', label: '已通过' },
]
const categoryName: Record<CardKind, string> = { last: '楦头', sole: '大底', heel: '鞋跟' }

const profile = ref(getProfile())
const mode = ref<Mode>('list')
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const saving = ref(false)
const uploading = ref(false)
const keyword = ref('')
const status = ref<StatusFilter>('all')
const current = ref<any>(null)
const editingId = ref<number | null>(null)
const picker = ref<Picker>('')
const colors = ref<any[]>([])
const colorKeyword = ref('')
const materials = ref<any[]>([])
const materialKeyword = ref('')
const materialLoading = ref(false)
const detailColorId = ref<number | null>(null)
const detailDept = ref<Record<string, string>>({})
const section = ref<Section | ''>('')
const sheet = ref<Sheet>('')
const sheetKeyword = ref('')
const sheetItems = ref<any[]>([])
const sheetLoading = ref(false)
const draftRows = ref<any[]>([])
const draftMaterials = ref<any[]>([])
const draftLabors = ref<any[]>([])
const materialColorId = ref<number | null>(null)
const lineEdit = ref<any>(null)
const segments = ref<any[]>([])
let sectionSnapshot = ''
let rowSeq = 1
let sheetTimer: ReturnType<typeof setTimeout> | undefined
const categoryIds = ref<Partial<Record<string, number>>>({})
let colorsLoaded = false
let categoriesLoaded = false
let loadTicket = 0
let keywordTimer: ReturnType<typeof setTimeout> | undefined
let materialTimer: ReturnType<typeof setTimeout> | undefined
let statusReady = false

const form = reactive({
  product_code: '',
  image_url: '',
  fabric: '',
  lining: '',
  color_ids: [] as number[],
  shoe_last_product_id: null as number | null,
  shoe_last_label: '',
  shoe_last_hours: '',
  sole_mold_product_id: null as number | null,
  sole_mold_label: '',
  heel_model_id: null as number | null,
  heel_model_label: '',
  product_year: '',
  season: '',
  quote_price: '',
})

const features = computed(() => profile.value?.featurePermissions || [])
const canSee = computed(() => features.value.includes('own_products') || features.value.includes('own_products_write') || features.value.includes('own_products_approve'))
const canWrite = computed(() => features.value.includes('own_products_write'))
const canApprove = computed(() => features.value.includes('own_products_approve'))
const showBar = computed(() => {
  if (!canSee.value || picker.value || sheet.value) return false
  if (mode.value === 'list') return canWrite.value
  if (mode.value === 'form' || mode.value === 'section') return true
  return Boolean(current.value && (canWrite.value || (canApprove.value && current.value.approval_status === 'pending')))
})
const sectionTitle = computed(() => ({ quotes: '客户报价', brands: '品牌报价', materials: '物料', labors: '工艺路线', commissions: '设计师提成', mgmt: '管理提成', costs: '其它成本' }[section.value] || '编辑'))
const sectionSheet = computed<Sheet>(() => ({ quotes: 'customer', brands: 'brand', commissions: 'employee', mgmt: 'title' }[section.value as string] || ''))
const sectionAddLabel = computed(() => ({ quotes: '添加客户', brands: '添加品牌', commissions: '添加人员', mgmt: '添加职务' }[section.value] || '添加'))
const sheetTitle = computed(() => ({ customer: '选择客户', brand: '选择品牌', employee: '选择人员', title: '选择职务', catalog: '添加物料', line: '编辑物料' }[sheet.value] || ''))
const editingMaterialRows = computed(() => draftMaterials.value.filter(row => materialColorId.value == null ? !row.bom_color_id : Number(row.bom_color_id) === Number(materialColorId.value)))
const sheetVisible = computed(() => {
  const text = sheetKeyword.value.trim()
  if (sheet.value === 'employee' || sheet.value === 'catalog') return sheetItems.value
  if (!text) return sheetItems.value
  return sheetItems.value.filter(item => String(item.label || '').includes(text) || String(item.sub || '').includes(text))
})
const filteredColors = computed(() => {
  const text = colorKeyword.value.trim()
  if (!text) return colors.value
  return colors.value.filter(item => String(item.name || '').includes(text) || String(item.code || '').includes(text))
})
const selectedColorText = computed(() => {
  if (!form.color_ids.length) return '请选择'
  const names = colors.value.filter(item => form.color_ids.includes(item.id)).map(item => item.name)
  return names.length ? names.join('、') : `已选 ${form.color_ids.length} 个`
})
const pickerTitle = computed(() => {
  if (picker.value === 'color') return '选择颜色'
  if (picker.value === 'last') return '选择楦型'
  if (picker.value === 'sole') return '选择鞋底'
  if (picker.value === 'heel') return '选择鞋跟'
  return ''
})
const detailFacts = computed(() => {
  const row = current.value
  if (!row) return []
  return [
    { label: '颜色', value: colorText(row) },
    { label: '面料', value: textOrDash(row.fabric) },
    { label: '里料', value: textOrDash(row.lining) },
    { label: '楦型', value: cardLabel(row.shoe_last_code, row.shoe_last_name) },
    { label: '楦头占用', value: row.shoe_last_hours == null || row.shoe_last_hours === '' ? '—' : `${trimNumber(row.shoe_last_hours)} 小时` },
    { label: '鞋底型号', value: cardLabel(row.sole_mold_code, row.sole_mold_name) },
    { label: '鞋跟型号', value: cardLabel(row.heel_model_code, row.heel_model_name) },
    { label: '鞋跟型号2', value: cardLabel(row.heel_model_2_code, row.heel_model_2_name) },
    { label: '年份季节', value: metaText(row) || '—' },
    { label: '统一报价', value: row.quote_price == null || row.quote_price === '' ? '—' : money(row.quote_price) },
  ].filter(fact => fact.label !== '鞋跟型号2' || fact.value !== '—')
})
const detailBom = computed(() => {
  const row = current.value
  const materials = row?.materials || []
  const shared = materials.filter((item: any) => !item.bom_color_id)
  const sharedCost = shared.reduce((sum: number, item: any) => sum + Number(item.line_total || 0), 0)
  const groups = (row?.colors || []).map((color: any) => {
    const rows = materials.filter((item: any) => Number(item.bom_color_id) === Number(color.id))
    const fabric = rows.reduce((sum: number, item: any) => sum + Number(item.line_total || 0), 0)
    return { colorId: color.id, name: color.name || '颜色', rows, fabric, pair: sharedCost + fabric }
  })
  const known = new Set(groups.map((group: any) => Number(group.colorId)))
  const extraIds = [...new Set(materials.filter((item: any) => item.bom_color_id && !known.has(Number(item.bom_color_id))).map((item: any) => Number(item.bom_color_id)))]
  for (const colorId of extraIds) {
    const rows = materials.filter((item: any) => Number(item.bom_color_id) === colorId)
    const fabric = rows.reduce((sum: number, item: any) => sum + Number(item.line_total || 0), 0)
    groups.push({ colorId, name: rows[0]?.bom_color_name || '其它颜色', rows, fabric, pair: sharedCost + fabric })
  }
  return { shared, sharedCost, groups }
})
const activeColorGroup = computed(() => {
  const groups = detailBom.value.groups
  if (!groups.length) return null
  return groups.find((group: any) => group.colorId === detailColorId.value) || groups[0]
})
const activeColorId = computed(() => activeColorGroup.value?.colorId ?? null)
const detailTotal = computed(() => {
  const row = current.value
  const rest = Number(row?.labor_cost || 0) + Number(row?.commission_cost || 0) + Number(row?.other_cost || 0)
  const material = activeColorGroup.value ? activeColorGroup.value.pair : detailBom.value.sharedCost
  return material + rest
})
const materialCount = computed(() => detailBom.value.shared.length + (activeColorGroup.value?.rows.length || 0))
function groupLabors(labors: any[], refs: Record<string, any> | null | undefined) {
  const order: string[] = []
  const groups = new Map<string, any>()
  const sorted = [...(labors || [])].sort((a: any, b: any) => Number(a.sort_order || 0) - Number(b.sort_order || 0))
  for (const labor of sorted) {
    const key = String(labor.segment_id ?? labor.segment_name ?? 'none')
    if (!groups.has(key)) {
      order.push(key)
      groups.set(key, { key, name: labor.segment_name || '未分段', segmentId: labor.segment_id, items: [] })
    }
    groups.get(key).items.push(labor)
  }
  const prices = refs || {}
  return order.map(key => {
    const group = groups.get(key)
    const deptOrder: string[] = []
    const depts = new Map<string, any[]>()
    for (const item of group.items) {
      const deptKey = String(item.department_id ?? 'all')
      if (!depts.has(deptKey)) {
        deptOrder.push(deptKey)
        depts.set(deptKey, [])
      }
      depts.get(deptKey)!.push(item)
    }
    const sections = deptOrder.map(deptKey => {
      const items = depts.get(deptKey) || []
      return {
        key: deptKey,
        name: items[0]?.department_name || '未分部门',
        items,
        subtotal: items.reduce((sum: number, item: any) => sum + Number(item.priceText ?? item.unit_price ?? 0), 0),
      }
    })
    const refPrice = Number(prices[String(group.segmentId)] || 0)
    const processSum = sections.reduce((sum: number, part: any) => sum + part.subtotal, 0)
    return { ...group, sections, split: sections.length > 1, refPrice, subtotal: processSum > 0 ? processSum : refPrice }
  })
}
const detailLaborGroups = computed(() => groupLabors(current.value?.labors || [], current.value?.segment_ref_prices))
const editLaborGroups = computed(() => groupLabors(draftLabors.value, current.value?.segment_ref_prices))

watch([mode, picker, sheet, section, editingId, () => current.value?.product_code], () => {
  let title = '产品开发'
  if (sheet.value) title = sheetTitle.value
  else if (picker.value === 'color') title = '选择颜色'
  else if (picker.value === 'last') title = '选择楦型'
  else if (picker.value === 'sole') title = '选择鞋底'
  else if (picker.value === 'heel') title = '选择鞋跟'
  else if (mode.value === 'form') title = editingId.value ? '编辑产品' : '新建产品'
  else if (mode.value === 'section') title = sectionTitle.value
  else if (mode.value === 'detail') title = current.value?.product_code || '产品详情'
  uni.setNavigationBarTitle({ title })
})

function toast(title: string) {
  uni.showToast({ title, icon: 'none' })
}
function statusLabel(value: string) {
  return value === 'pending' ? '待审批' : '已通过'
}
function seasonLabel(value: string) {
  return seasons.find(item => item.value === value)?.label || ''
}
function textOrDash(value: unknown) {
  const text = String(value || '').trim()
  return text || '—'
}
function cardLabel(code: unknown, name: unknown) {
  const text = [code, name].map(item => String(item || '').trim()).filter(Boolean).join(' · ')
  return text || '—'
}
function colorText(row: any) {
  const names = (row?.colors || []).map((item: any) => item?.name).filter(Boolean)
  return names.length ? names.join('、') : '未选颜色'
}
function metaText(row: any) {
  return [row?.product_year, seasonLabel(row?.season)].filter(Boolean).join(' · ')
}
function swatch(row: any) {
  return String(row?.product_code || '品').trim().slice(0, 1)
}
function trimNumber(value: unknown) {
  const text = String(value)
  return text.replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1')
}
function money(value: unknown) {
  if (value == null || value === '') return '—'
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '—'
  return `¥${amount.toFixed(2)}`
}
function quoteCount(rows: unknown) {
  const count = Array.isArray(rows) ? rows.length : 0
  return count ? `${count} 项` : ''
}
function materialMark(item: any) {
  return String(item?.supplier_product_name || item?.supplier_product_code || '料').trim().slice(0, 1)
}
function materialLine(item: any) {
  return [item?.supplier_product_name, item?.color_name, item?.partner_name, item?.consume_segment_name].filter(Boolean).join(' · ') || '—'
}
function materialQty(item: any) {
  const parts = [`用量 ${trimNumber(item?.qty ?? '')}`]
  if (item?.pricing_unit_name) parts.push(item.pricing_unit_name)
  parts.push(`单价 ${money(item?.unit_price)}`)
  if (Number(item?.loss_rate)) parts.push(`损耗 ${trimNumber(Math.round(Number(item.loss_rate) * 10000) / 100)}%`)
  if (Number(item?.loss_fixed_qty)) parts.push(`固定损耗 ${trimNumber(item.loss_fixed_qty)}`)
  if (item?.usage_by_size) parts.push(item.size_usage_table_name ? `按码 ${item.size_usage_table_name}` : '按码')
  return parts.join(' · ')
}
function previewMaterials(item: any, list: any[]) {
  const urls = (list || []).map(row => displayImageUrl(row?.image_url)).filter(Boolean)
  const currentUrl = displayImageUrl(item?.image_url)
  if (currentUrl) uni.previewImage({ urls: urls.length ? urls : [currentUrl], current: currentUrl })
}
function laborSection(group: any) {
  const sections = group?.sections || []
  if (!group?.split) {
    return { key: 'all', items: sections.flatMap((section: any) => section.items), subtotal: group?.subtotal || 0 }
  }
  const currentKey = detailDept.value[group.key]
  return sections.find((section: any) => section.key === currentKey) || sections[0] || { key: '', items: [], subtotal: 0 }
}
function pickDept(groupKey: string, deptKey: string) {
  detailDept.value = { ...detailDept.value, [groupKey]: deptKey }
}
function displayImageUrl(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw || /^(https?:|data:|blob:)/i.test(raw)) return raw
  const path = raw.startsWith('/') ? raw : `/${raw}`
  const apiOrigin = String(import.meta.env.VITE_API_BASE_URL || '').match(/^https?:\/\/[^/]+/i)?.[0]
  return apiOrigin ? `${apiOrigin}${path}` : path
}
function previewImage(url: string) {
  const resolved = displayImageUrl(url)
  if (resolved) uni.previewImage({ urls: [resolved], current: resolved })
}
function materialSub(item: any) {
  return [item?.name, item?.color_name].map(part => String(part || '').trim()).filter(Boolean).join(' · ')
}
function blankForm() {
  form.product_code = ''
  form.image_url = ''
  form.fabric = ''
  form.lining = ''
  form.color_ids = []
  form.shoe_last_product_id = null
  form.shoe_last_label = ''
  form.shoe_last_hours = ''
  form.sole_mold_product_id = null
  form.sole_mold_label = ''
  form.heel_model_id = null
  form.heel_model_label = ''
  form.product_year = String(new Date().getFullYear())
  form.season = ''
  form.quote_price = ''
}
function fillForm(row: any) {
  form.product_code = row.product_code || ''
  form.image_url = row.image_url || ''
  form.fabric = row.fabric || ''
  form.lining = row.lining || ''
  form.color_ids = [...(row.color_ids || [])]
  form.shoe_last_product_id = row.shoe_last_product_id || null
  form.shoe_last_label = cardLabel(row.shoe_last_code, row.shoe_last_name) === '—' ? '' : cardLabel(row.shoe_last_code, row.shoe_last_name)
  form.shoe_last_hours = row.shoe_last_hours == null || row.shoe_last_hours === '' ? '' : trimNumber(row.shoe_last_hours)
  form.sole_mold_product_id = row.sole_mold_product_id || null
  form.sole_mold_label = cardLabel(row.sole_mold_code, row.sole_mold_name) === '—' ? '' : cardLabel(row.sole_mold_code, row.sole_mold_name)
  form.heel_model_id = row.heel_model_id || null
  form.heel_model_label = cardLabel(row.heel_model_code, row.heel_model_name) === '—' ? '' : cardLabel(row.heel_model_code, row.heel_model_name)
  form.product_year = row.product_year ? String(row.product_year) : ''
  form.season = row.season || ''
  form.quote_price = row.quote_price == null || row.quote_price === '' ? '' : String(row.quote_price)
}

async function load(reset = false) {
  if (!canSee.value) return
  if (reset) {
    page.value = 1
    rows.value = []
  }
  const ticket = ++loadTicket
  loading.value = true
  try {
    const query: Record<string, unknown> = { page: page.value, page_size: 20 }
    const text = keyword.value.trim()
    if (text) query.keyword = text
    if (status.value !== 'all') query.approval_status = status.value
    const data: any = await get('/own-products', query)
    if (ticket !== loadTicket) return
    const items = data?.items || []
    rows.value = reset ? items : rows.value.concat(items)
    total.value = Number(data?.total || 0)
  } catch (error: any) {
    if (ticket === loadTicket) toast(error?.message || '产品加载失败')
  } finally {
    if (ticket === loadTicket) loading.value = false
  }
}
function search() {
  void load(true)
}
function onKeyword(event: any) {
  keyword.value = event?.detail?.value || ''
  clearTimeout(keywordTimer)
  keywordTimer = setTimeout(() => void load(true), 300)
}
function clearKeyword() {
  keyword.value = ''
  void load(true)
}
function setStatus(value: StatusFilter) {
  if (status.value === value) return
  status.value = value
  void load(true)
}
async function openDetail(id: number) {
  try {
    current.value = await get(`/own-products/${id}`)
    detailColorId.value = current.value?.colors?.[0]?.id ?? null
    detailDept.value = {}
    mode.value = 'detail'
  } catch (error: any) {
    toast(error?.message || '产品读取失败')
  }
}
async function ensureColors() {
  if (colorsLoaded) return
  const data: any = await get('/colors')
  colors.value = data?.items || []
  colorsLoaded = true
}
async function ensureCategories() {
  if (categoriesLoaded) return
  const data: any = await get('/material-categories', { active_only: true })
  const next: Partial<Record<string, number>> = {}
  for (const item of data?.items || []) {
    if (item?.name === '楦头' || item?.name === '大底' || item?.name === '鞋跟') next[item.name] = item.id
  }
  categoryIds.value = next
  categoriesLoaded = true
}
async function startCreate() {
  editingId.value = null
  blankForm()
  mode.value = 'form'
  try { await ensureColors() } catch { /* 打开颜色时再提示 */ }
}
async function startEdit() {
  if (!current.value) return
  editingId.value = current.value.id
  try { await ensureColors() } catch { /* 颜色名暂时用已选数量 */ }
  fillForm(current.value)
  mode.value = 'form'
}
function choosePhoto() {
  if (uploading.value) return
  const items = form.image_url ? ['拍照', '从相册选择', '移除图片'] : ['拍照', '从相册选择']
  uni.showActionSheet({
    itemList: items,
    success: result => {
      if (items[result.tapIndex] === '移除图片') {
        form.image_url = ''
        return
      }
      const source = result.tapIndex === 0 ? 'camera' : 'album'
      uni.chooseImage({
        count: 1,
        sizeType: ['compressed'],
        sourceType: [source],
        success: async chosen => {
          const filePath = chosen.tempFilePaths?.[0]
          if (!filePath) return
          uploading.value = true
          try {
            const uploaded: any = await uploadFile('/supplier-products/upload', filePath)
            form.image_url = uploaded?.url || ''
          } catch (error: any) {
            toast(error?.message || '图片上传失败')
          } finally {
            uploading.value = false
          }
        },
      })
    },
  })
}
function optionalDecimal(raw: string, label: string) {
  const text = raw.trim()
  if (!text) return null
  if (!/^\d+(\.\d+)?$/.test(text)) throw new Error(`${label}请填数字`)
  if (Number(text) < 0) throw new Error(`${label}不能为负`)
  return text
}
function buildBody() {
  const productCode = form.product_code.trim()
  if (!productCode) throw new Error('请填写工厂型号')
  const year = Number(form.product_year)
  if (!Number.isInteger(year) || year < 2000 || year > 2100) throw new Error('年份请填 2000 到 2100')
  if (!form.season) throw new Error('请选择季节')
  if (!form.color_ids.length) throw new Error('请至少选择一个颜色')
  return {
    product_code: productCode,
    product_year: year,
    season: form.season,
    image_url: form.image_url.trim() || null,
    fabric: form.fabric.trim() || null,
    lining: form.lining.trim() || null,
    color_ids: [...form.color_ids],
    shoe_last_product_id: form.shoe_last_product_id,
    shoe_last_hours: optionalDecimal(form.shoe_last_hours, '楦头占用时间'),
    sole_mold_product_id: form.sole_mold_product_id,
    heel_model_id: form.heel_model_id,
    quote_price: optionalDecimal(form.quote_price, '统一报价'),
  }
}
async function save() {
  if (saving.value) return
  let body: ReturnType<typeof buildBody>
  try {
    body = buildBody()
  } catch (error: any) {
    toast(error?.message || '请检查填写内容')
    return
  }
  saving.value = true
  try {
    // 只提交基础资料。物料、人工和报价明细留在电脑端，避免手机保存把它们清空。
    const saved: any = editingId.value
      ? await patch(`/own-products/${editingId.value}`, body)
      : await post('/own-products', body)
    current.value = saved
    detailColorId.value = saved?.colors?.[0]?.id ?? null
    detailDept.value = {}
    editingId.value = saved?.id || editingId.value
    mode.value = 'detail'
    toast(saved?.approval_status === 'pending' ? '已保存，等待审批' : '已保存')
    void load(true)
  } catch (error: any) {
    toast(error?.message || '保存失败')
  } finally {
    saving.value = false
  }
}
function approve() {
  if (!current.value || saving.value) return
  uni.showModal({
    title: '通过审批',
    content: `确认通过 ${current.value.product_code} ？`,
    success: async result => {
      if (!result.confirm) return
      saving.value = true
      try {
        current.value = await post(`/own-products/${current.value.id}/approve`, {})
        toast('已通过')
        void load(true)
      } catch (error: any) {
        toast(error?.message || '审批失败')
      } finally {
        saving.value = false
      }
    },
  })
}
async function openColorPicker() {
  colorKeyword.value = ''
  picker.value = 'color'
  try {
    await ensureColors()
  } catch (error: any) {
    toast(error?.message || '颜色加载失败')
  }
}
function onColorKeyword(event: any) {
  colorKeyword.value = event?.detail?.value || ''
}
function toggleColor(id: number) {
  if (form.color_ids.includes(id)) form.color_ids = form.color_ids.filter(item => item !== id)
  else form.color_ids = [...form.color_ids, id]
}
async function openMaterialPicker(kind: CardKind) {
  try {
    await ensureCategories()
  } catch (error: any) {
    toast(error?.message || '分类加载失败')
    return
  }
  const name = categoryName[kind]
  if (!categoryIds.value[name]) {
    toast(`还没有「${name}」分类`)
    return
  }
  picker.value = kind
  materialKeyword.value = ''
  materials.value = []
  void searchMaterials()
}
function onMaterialKeyword(event: any) {
  materialKeyword.value = event?.detail?.value || ''
  clearTimeout(materialTimer)
  materialTimer = setTimeout(() => void searchMaterials(), 300)
}
async function searchMaterials() {
  const kind = picker.value
  if (kind !== 'last' && kind !== 'sole' && kind !== 'heel') return
  const categoryId = categoryIds.value[categoryName[kind]]
  if (!categoryId) return
  materialLoading.value = true
  try {
    const query: Record<string, unknown> = { category_id: categoryId, active_only: true, page: 1, page_size: 30 }
    const text = materialKeyword.value.trim()
    if (text) query.keyword = text
    const data: any = await get('/supplier-products', query)
    if (picker.value === kind) materials.value = data?.items || []
  } catch (error: any) {
    if (picker.value === kind) toast(error?.message || '色卡加载失败')
  } finally {
    if (picker.value === kind) materialLoading.value = false
  }
}
function pickMaterial(item: any) {
  const label = cardLabel(item.product_code, item.name)
  if (picker.value === 'last') {
    form.shoe_last_product_id = item.id
    form.shoe_last_label = label
  } else if (picker.value === 'sole') {
    form.sole_mold_product_id = item.id
    form.sole_mold_label = label
  } else if (picker.value === 'heel') {
    form.heel_model_id = item.id
    form.heel_model_label = label
  }
  closePicker()
}
function clearMaterial(kind: CardKind) {
  if (kind === 'last') {
    form.shoe_last_product_id = null
    form.shoe_last_label = ''
  } else if (kind === 'sole') {
    form.sole_mold_product_id = null
    form.sole_mold_label = ''
  } else {
    form.heel_model_id = null
    form.heel_model_label = ''
  }
}
function closePicker() {
  picker.value = ''
}
function nextKey() {
  rowSeq += 1
  return `row-${rowSeq}`
}
function looseDecimal(value: unknown) {
  const text = String(value ?? '').trim()
  return text || '0'
}
function fractionFromPercent(value: unknown) {
  const percent = Number(looseDecimal(value))
  return String(Math.round(percent * 10000) / 1000000)
}
function strictDecimal(value: unknown, label: string) {
  const text = String(value ?? '').trim()
  if (!text) return '0'
  if (!/^\d+(\.\d+)?$/.test(text)) throw new Error(`${label}请填数字`)
  return text
}
function openSection(name: Section) {
  if (!current.value) return
  section.value = name
  sheet.value = ''
  lineEdit.value = null
  if (name === 'quotes') {
    draftRows.value = (current.value.quotes || []).map((row: any) => ({ key: `q-${row.id}`, partner_id: row.partner_id, label: row.partner_short_name || row.partner_name || '客户', priceText: trimNumber(row.quote_price) }))
  } else if (name === 'brands') {
    draftRows.value = (current.value.brand_quotes || []).map((row: any) => ({ key: `b-${row.id}`, master_brand_id: row.master_brand_id, label: row.brand_name || '品牌', priceText: trimNumber(row.quote_price) }))
  } else if (name === 'commissions') {
    draftRows.value = (current.value.commissions || []).map((row: any) => ({ key: `c-${row.id}`, employee_id: row.employee_id, label: row.employee_name || '未选人', priceText: trimNumber(row.amount) }))
  } else if (name === 'mgmt') {
    draftRows.value = (current.value.mgmt_commissions || []).map((row: any) => ({ key: `m-${row.id}`, job_title_id: row.job_title_id, label: row.job_title_name || '职务', priceText: trimNumber(row.amount) }))
  } else if (name === 'costs') {
    draftRows.value = (current.value.other_costs || []).map((row: any) => ({ key: `o-${row.id}`, label: row.name || '', priceText: trimNumber(row.amount) }))
  } else if (name === 'materials') {
    draftMaterials.value = (current.value.materials || []).map((row: any) => ({
      key: `mat-${row.id}`,
      supplier_product_id: row.supplier_product_id,
      supplier_product_code: row.supplier_product_code,
      supplier_product_name: row.supplier_product_name,
      image_url: row.image_url,
      color_name: row.color_name,
      partner_name: row.partner_name,
      pricing_unit_name: row.pricing_unit_name,
      consume_process_id: row.consume_process_id,
      consume_segment_id: row.consume_segment_id,
      consume_segment_name: row.consume_segment_name || '',
      bom_color_id: row.bom_color_id ?? null,
      qtyText: trimNumber(row.qty),
      lossRateText: Number(row.loss_rate) ? trimNumber(Math.round(Number(row.loss_rate) * 10000) / 100) : '',
      lossFixedText: Number(row.loss_fixed_qty) ? trimNumber(row.loss_fixed_qty) : '',
      sort_order: row.sort_order,
    }))
    materialColorId.value = detailColorId.value ?? current.value.colors?.[0]?.id ?? null
    void ensureSegments()
  } else if (name === 'labors') {
    draftLabors.value = (current.value.labors || []).map((row: any) => ({ ...row, key: `labor-${row.id}`, priceText: trimNumber(row.unit_price), noteText: row.requirement_note || '' }))
  }
  mode.value = 'section'
  sectionSnapshot = JSON.stringify(sectionBody())
}
function sectionBody() {
  if (section.value === 'quotes') {
    return { quotes: draftRows.value.map((row, index) => ({ partner_id: row.partner_id, quote_price: looseDecimal(row.priceText), sort_order: index })) }
  }
  if (section.value === 'brands') {
    return { brand_quotes: draftRows.value.map((row, index) => ({ master_brand_id: row.master_brand_id, brand_name: row.label, quote_price: looseDecimal(row.priceText), sort_order: index })) }
  }
  if (section.value === 'commissions') {
    return { commissions: draftRows.value.map((row, index) => ({ employee_id: row.employee_id, amount: looseDecimal(row.priceText), sort_order: index })) }
  }
  if (section.value === 'mgmt') {
    return { mgmt_commissions: draftRows.value.map((row, index) => ({ job_title_id: row.job_title_id, amount: looseDecimal(row.priceText), sort_order: index })) }
  }
  if (section.value === 'costs') {
    return { other_costs: draftRows.value.map((row, index) => ({ name: String(row.label || '').trim(), amount: looseDecimal(row.priceText), sort_order: index })) }
  }
  if (section.value === 'materials') {
    return {
      materials: draftMaterials.value.map((row, index) => ({
        supplier_product_id: row.supplier_product_id,
        qty: looseDecimal(row.qtyText),
        sort_order: index,
        consume_process_id: row.consume_process_id ?? null,
        consume_segment_id: row.consume_segment_id ?? null,
        loss_rate: fractionFromPercent(row.lossRateText),
        loss_fixed_qty: looseDecimal(row.lossFixedText),
        color_id: row.bom_color_id ?? null,
      })),
    }
  }
  return {
    labors: draftLabors.value.map((row, index) => ({
      process_name: row.process_name,
      requirement_note: String(row.noteText || '').trim() || null,
      unit_price: looseDecimal(row.priceText),
      department_id: row.department_id ?? null,
      department_prices: row.department_id ? null : (row.department_prices || null),
      sort_order: row.sort_order ?? index,
      part_id: row.part_id ?? null,
      is_kit_checkpoint: Boolean(row.is_kit_checkpoint),
      segment_id: row.segment_id ?? null,
    })),
  }
}
function removeDraft(key: string) {
  draftRows.value = draftRows.value.filter(row => row.key !== key)
}
function addCostRow() {
  draftRows.value = [...draftRows.value, { key: nextKey(), label: '', priceText: '' }]
}
async function ensureSegments() {
  if (segments.value.length) return
  const data: any = await get('/process-segments', { active_only: true })
  segments.value = data?.items || []
}
function openMaterialLine(item: any) {
  lineEdit.value = item
  sheet.value = 'line'
  ensureSegments().catch((error: any) => toast(error?.message || '消耗部门加载失败'))
}
function chooseSegment(seg: any) {
  if (!lineEdit.value) return
  lineEdit.value.consume_segment_id = seg.id
  lineEdit.value.consume_segment_name = seg.name
}
function removeMaterialLine() {
  if (!lineEdit.value) return
  draftMaterials.value = draftMaterials.value.filter(row => row.key !== lineEdit.value.key)
  closeSheet()
}
function closeSheet() {
  sheet.value = ''
  lineEdit.value = null
}
async function openSheet(kind: Sheet) {
  if (!kind) return
  sheetKeyword.value = ''
  sheetItems.value = []
  sheet.value = kind
  if (kind === 'customer') await loadCustomers()
  else if (kind === 'brand') await loadBrands()
  else if (kind === 'title') await loadTitles()
  else if (kind === 'employee') await searchEmployees()
  else if (kind === 'catalog') await searchCatalog()
}
function onSheetKeyword(event: any) {
  sheetKeyword.value = event?.detail?.value || ''
  if (sheet.value !== 'employee' && sheet.value !== 'catalog') return
  clearTimeout(sheetTimer)
  sheetTimer = setTimeout(() => {
    if (sheet.value === 'employee') void searchEmployees()
    if (sheet.value === 'catalog') void searchCatalog()
  }, 300)
}
async function loadCustomers() {
  sheetLoading.value = true
  try {
    const data: any = await get('/partners', { role: 'customer_brand', active_only: true, page: 1, page_size: 200 })
    sheetItems.value = (data?.items || []).map((item: any) => ({ id: item.id, label: item.short_name || item.name, sub: item.short_name ? item.name : '' }))
  } catch (error: any) {
    toast(error?.message || '客户加载失败')
  } finally { sheetLoading.value = false }
}
async function loadBrands() {
  sheetLoading.value = true
  try {
    const data: any = await get('/brands')
    sheetItems.value = (data?.items || []).map((item: any) => ({ id: item.id, label: item.name }))
  } catch (error: any) {
    toast(error?.message || '品牌加载失败')
  } finally { sheetLoading.value = false }
}
async function loadTitles() {
  sheetLoading.value = true
  try {
    const data: any = await get('/job-titles', { active_only: true })
    sheetItems.value = (data?.items || []).map((item: any) => ({ id: item.id, label: item.name }))
  } catch (error: any) {
    toast(error?.message || '职务加载失败')
  } finally { sheetLoading.value = false }
}
async function searchEmployees() {
  sheetLoading.value = true
  try {
    const query: Record<string, unknown> = { is_active: true, page: 1, page_size: 30 }
    const text = sheetKeyword.value.trim()
    if (text) query.keyword = text
    const data: any = await get('/employees', query)
    if (sheet.value === 'employee') sheetItems.value = (data?.items || []).map((item: any) => ({ id: item.id, label: item.name }))
  } catch (error: any) {
    toast(error?.message || '人员加载失败')
  } finally { sheetLoading.value = false }
}
async function searchCatalog() {
  sheetLoading.value = true
  try {
    const query: Record<string, unknown> = { active_only: true, page: 1, page_size: 30 }
    const text = sheetKeyword.value.trim()
    if (text) query.keyword = text
    const data: any = await get('/supplier-products', query)
    if (sheet.value === 'catalog') {
      sheetItems.value = (data?.items || []).map((item: any) => ({
        ...item,
        label: item.product_code,
        sub: [item.name, item.color_name].filter(Boolean).join(' · '),
      }))
    }
  } catch (error: any) {
    toast(error?.message || '色卡加载失败')
  } finally { sheetLoading.value = false }
}
function pickSheet(item: any) {
  if (sheet.value === 'customer') {
    if (draftRows.value.some(row => row.partner_id === item.id)) return toast('这个客户已经有报价')
    draftRows.value = [...draftRows.value, { key: nextKey(), partner_id: item.id, label: item.label, priceText: '' }]
  } else if (sheet.value === 'brand') {
    if (draftRows.value.some(row => row.master_brand_id === item.id)) return toast('这个品牌已经有报价')
    draftRows.value = [...draftRows.value, { key: nextKey(), master_brand_id: item.id, label: item.label, priceText: '' }]
  } else if (sheet.value === 'employee') {
    if (draftRows.value.some(row => row.employee_id === item.id)) return toast('这个人已经有提成')
    draftRows.value = [...draftRows.value, { key: nextKey(), employee_id: item.id, label: item.label, priceText: '' }]
  } else if (sheet.value === 'title') {
    if (draftRows.value.some(row => row.job_title_id === item.id)) return toast('这个职务已经有提成')
    draftRows.value = [...draftRows.value, { key: nextKey(), job_title_id: item.id, label: item.label, priceText: '' }]
  } else if (sheet.value === 'catalog') {
    const colorId = materialColorId.value
    if (draftMaterials.value.some(row => row.supplier_product_id === item.id && (colorId == null ? !row.bom_color_id : Number(row.bom_color_id) === Number(colorId)))) {
      return toast('这个颜色里已经有该物料')
    }
    const created = {
      key: nextKey(),
      supplier_product_id: item.id,
      supplier_product_code: item.product_code,
      supplier_product_name: item.name,
      image_url: item.image_url,
      color_name: item.color_name,
      partner_name: item.partner_name,
      pricing_unit_name: item.pricing_unit_name,
      consume_process_id: null,
      consume_segment_id: null,
      consume_segment_name: '',
      bom_color_id: colorId,
      qtyText: '1',
      lossRateText: '',
      lossFixedText: '',
    }
    draftMaterials.value = [...draftMaterials.value, created]
    openMaterialLine(created)
    return
  }
  closeSheet()
}
async function saveSection() {
  if (saving.value || !current.value) return
  try {
    if (section.value === 'quotes') draftRows.value.forEach(row => strictDecimal(row.priceText, '报价'))
    if (section.value === 'brands') draftRows.value.forEach(row => strictDecimal(row.priceText, '报价'))
    if (section.value === 'commissions') draftRows.value.forEach(row => strictDecimal(row.priceText, '提成'))
    if (section.value === 'mgmt') {
      draftRows.value.forEach(row => {
        if (Number(strictDecimal(row.priceText, '提成')) <= 0) throw new Error('管理提成要大于 0')
      })
    }
    if (section.value === 'costs') {
      draftRows.value.forEach(row => {
        if (!String(row.label || '').trim()) throw new Error('请填写项目名称')
        strictDecimal(row.priceText, '金额')
      })
    }
    if (section.value === 'materials') {
      draftMaterials.value.forEach(row => {
        strictDecimal(row.qtyText, '用量')
        strictDecimal(row.lossRateText, '损耗')
        strictDecimal(row.lossFixedText, '固定损耗')
        if (!row.consume_segment_id) throw new Error(`请为「${row.supplier_product_code || row.supplier_product_name || '物料'}」选择消耗部门`)
      })
    }
    if (section.value === 'labors') {
      draftLabors.value.forEach(row => strictDecimal(row.priceText, `${row.process_name || '工序'}单价`))
    }
  } catch (error: any) {
    toast(error?.message || '请检查填写内容')
    return
  }
  saving.value = true
  try {
    // 只提交当前这一块，避免把没改的物料、工艺或报价整包覆盖掉。
    const saved: any = await patch(`/own-products/${current.value.id}`, sectionBody())
    current.value = saved
    detailColorId.value = materialColorId.value ?? saved?.colors?.[0]?.id ?? detailColorId.value
    leaveSection()
    toast(saved?.approval_status === 'pending' ? '已保存，等待审批' : '已保存')
    void load(true)
  } catch (error: any) {
    toast(error?.message || '保存失败')
  } finally {
    saving.value = false
  }
}
function leaveSection() {
  section.value = ''
  closeSheet()
  mode.value = 'detail'
}
function goBack() {
  if (picker.value) {
    closePicker()
    return
  }
  if (sheet.value) {
    closeSheet()
    return
  }
  if (mode.value === 'section') {
    if (JSON.stringify(sectionBody()) !== sectionSnapshot) {
      uni.showModal({
        title: '放弃修改？',
        content: '这次改动还没保存',
        success: result => { if (result.confirm) leaveSection() },
      })
      return
    }
    leaveSection()
    return
  }
  if (mode.value === 'form' && editingId.value) {
    mode.value = 'detail'
    return
  }
  if (mode.value !== 'list') {
    mode.value = 'list'
    void load(true)
  }
}
onBackPress(() => {
  if (picker.value || mode.value !== 'list') {
    goBack()
    return true
  }
  return false
})
onReachBottom(() => {
  if (mode.value !== 'list' || loading.value || rows.value.length >= total.value) return
  page.value += 1
  void load(false)
})
onPullDownRefresh(async () => {
  try {
    if (mode.value === 'list') await load(true)
    else if (mode.value === 'detail' && current.value) await openDetail(current.value.id)
  } finally {
    uni.stopPullDownRefresh()
  }
})
onShow(() => {
  profile.value = getProfile()
  if (!statusReady) {
    status.value = canApprove.value ? 'pending' : 'all'
    statusReady = true
  }
  if (mode.value === 'list') void load(true)
})
</script>

<style scoped lang="scss">
.h5-dev--bar { padding-bottom: calc(220rpx + env(safe-area-inset-bottom)); }
.h5-dev-search, .h5-dev-field, .h5-dev-card, .h5-dev-hero, .h5-dev-sheet__head, .h5-dev-option, .h5-dev-bar__row {
  display: flex;
  align-items: center;
}
.h5-dev-search {
  gap: 16rpx;
  margin-bottom: 16rpx;
  padding: 8rpx 8rpx 8rpx 24rpx;
}
.h5-dev-search input, .h5-dev-sheet__search input {
  flex: 1;
  height: 76rpx;
  font-size: 28rpx;
}
.h5-dev-search > text, .h5-dev-clear, .h5-dev-sheet__head > text {
  padding: 12rpx 18rpx;
  color: #0057c2;
  font-size: 26rpx;
}
.h5-dev-chips { display: flex; gap: 12rpx; margin-bottom: 18rpx; }
.h5-dev-chips text, .h5-dev-seasons text {
  padding: 12rpx 22rpx;
  border-radius: 999rpx;
  background: #fff;
  color: #667386;
  font-size: 26rpx;
}
.h5-dev-chips text.on, .h5-dev-seasons text.on { background: #0057c2; color: #fff; font-weight: 650; }
.h5-dev-card, .h5-dev-hero { gap: 20rpx; margin-bottom: 16rpx; padding: 22rpx; }
.h5-dev-card image, .h5-dev-swatch, .h5-dev-hero image, .h5-dev-photo image {
  width: 112rpx;
  height: 112rpx;
  flex: none;
  border-radius: 18rpx;
  background: #eef2f7;
}
.h5-dev-swatch {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #1847ae;
  font-size: 36rpx;
  font-weight: 700;
}
.h5-dev-swatch--lg, .h5-dev-hero image, .h5-dev-photo image { width: 168rpx; height: 168rpx; }
.h5-dev-card__body, .h5-dev-hero > view { min-width: 0; flex: 1; }
.h5-dev-card__top { justify-content: space-between; gap: 12rpx; }
.h5-dev-card strong, .h5-dev-hero strong { color: #132033; font-size: 32rpx; }
.h5-dev-card__body > text, .h5-dev-option__sub { display: block; margin-top: 6rpx; color: #667386; font-size: 24rpx; }
.h5-dev-status { flex: none; padding: 4rpx 12rpx; border-radius: 999rpx; font-size: 22rpx; }
.h5-dev-status.pending { background: #fff4d6; color: #9a6700; }
.h5-dev-status.approved { background: #e7f6ee; color: #0b7a43; }
.h5-dev-hero { align-items: flex-start; }
.h5-dev-hero .h5-dev-status { display: inline-block; margin-top: 14rpx; }
.h5-dev-hero__meta { display: block; margin-top: 10rpx; color: #667386; font-size: 24rpx; }
.h5-dev-colors { width: 100%; height: 72rpx; margin-bottom: 16rpx; white-space: nowrap; }
.h5-dev-colors text { display: inline-block; margin-right: 12rpx; padding: 12rpx 22rpx; border-radius: 999rpx; background: #fff; color: #667386; font-size: 26rpx; }
.h5-dev-colors text.on { background: #0057c2; color: #fff; font-weight: 650; }
.h5-dev-cost { margin-bottom: 16rpx; padding: 8rpx 8rpx 22rpx; }
.h5-dev-cost__grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); }
.h5-dev-cost__grid view { padding: 18rpx 8rpx; text-align: center; }
.h5-dev-cost__grid text, .h5-dev-cost__total text { display: block; color: #667386; font-size: 22rpx; }
.h5-dev-cost__grid strong { display: block; margin-top: 8rpx; color: #132033; font-size: 26rpx; }
.h5-dev-cost__total { display: flex; align-items: baseline; justify-content: space-between; margin: 8rpx 16rpx 0; padding-top: 16rpx; border-top: 1rpx solid rgba(60, 60, 67, .08); }
.h5-dev-cost__total strong { color: #0057c2; font-size: 40rpx; }
.h5-dev-block { margin-bottom: 16rpx; padding: 8rpx 24rpx 12rpx; }
.h5-dev-block__head, .h5-dev-pair, .h5-dev-mat__top, .h5-dev-labor > view, .h5-dev-route__head { display: flex; align-items: center; justify-content: space-between; gap: 16rpx; }
.h5-dev-block__head { min-height: 80rpx; }
.h5-dev-block__head > text:first-child, .h5-dev-route__head > text { color: #132033; font-size: 30rpx; font-weight: 700; }
.h5-dev-block__head > text + text, .h5-dev-block__side > text:first-child { color: #667386; font-size: 24rpx; font-weight: 500; }
.h5-dev-block__side { display: flex; align-items: center; gap: 18rpx; }
.h5-dev-edit { color: #0057c2; font-size: 26rpx; font-weight: 700; }
.h5-dev-inline { display: block; padding: 22rpx 0; color: #0057c2; font-size: 28rpx; font-weight: 700; text-align: center; }
.h5-dev-del { color: #c53636; font-size: 26rpx; }
.h5-dev-editrow { display: flex; align-items: center; gap: 12rpx; min-height: 96rpx; border-top: 1rpx solid rgba(60, 60, 67, .08); }
.h5-dev-editrow__name, .h5-dev-editrow > input:first-child { flex: 1; min-width: 0; color: #132033; font-size: 28rpx; }
.h5-dev-price { width: 168rpx; flex: none; color: #132033; font-size: 28rpx; text-align: right; }
.h5-dev-note { width: 100%; min-height: 88rpx; margin-top: 8rpx; padding: 12rpx 16rpx; border-radius: 12rpx; background: #f4f7fb; box-sizing: border-box; font-size: 26rpx; }
.h5-dev-sheet .h5-dev-field { padding-right: 8rpx; padding-left: 8rpx; }
.h5-dev-pair { min-height: 84rpx; border-top: 1rpx solid rgba(60, 60, 67, .08); }
.h5-dev-pair text { color: #132033; font-size: 28rpx; }
.h5-dev-pair strong, .h5-dev-mat__top text, .h5-dev-labor text, .h5-dev-route__head strong { color: #173f9a; font-size: 28rpx; }
.h5-dev-empty, .h5-dev-subhead, .h5-dev-ref { display: block; padding: 8rpx 0 16rpx; color: #667386; font-size: 24rpx; }
.h5-dev-subhead { padding-top: 16rpx; color: #132033; font-weight: 650; }
.h5-dev-mat { display: flex; gap: 16rpx; padding: 16rpx 0; border-top: 1rpx solid rgba(60, 60, 67, .08); }
.h5-dev-mat image, .h5-dev-swatch--sm { width: 96rpx; height: 96rpx; flex: none; border-radius: 16rpx; }
.h5-dev-swatch--sm { font-size: 30rpx; }
.h5-dev-mat > view { min-width: 0; flex: 1; }
.h5-dev-mat strong, .h5-dev-labor strong { color: #132033; font-size: 28rpx; }
.h5-dev-mat text { display: block; margin-top: 6rpx; color: #667386; font-size: 22rpx; }
.h5-dev-mat__top text { margin-top: 0; }
.h5-dev-route { padding: 8rpx 0 12rpx; border-top: 1rpx solid rgba(60, 60, 67, .08); }
.h5-dev-route__head { min-height: 72rpx; }
.h5-dev-mini { display: flex; flex-wrap: wrap; gap: 10rpx; margin-bottom: 8rpx; }
.h5-dev-mini text { padding: 8rpx 16rpx; border-radius: 999rpx; background: #f2f5f9; color: #667386; font-size: 22rpx; }
.h5-dev-mini text.on { background: #e8f1ff; color: #0057c2; font-weight: 700; }
.h5-dev-labor { padding: 12rpx 0; }
.h5-dev-labor > text { display: block; margin-top: 6rpx; color: #667386; font-size: 24rpx; line-height: 1.45; }
.h5-dev-facts view { display: flex; justify-content: space-between; gap: 24rpx; padding: 22rpx 0; border-bottom: 1rpx solid rgba(60, 60, 67, .08); }
.h5-dev-facts view:last-child { border-bottom: 0; }
.h5-dev-facts text { flex: none; color: #667386; font-size: 26rpx; }
.h5-dev-facts strong { color: #132033; font-size: 28rpx; font-weight: 650; text-align: right; word-break: break-all; }
.h5-dev-photo { display: flex; align-items: center; justify-content: center; min-height: 220rpx; margin-bottom: 16rpx; overflow: hidden; }
.h5-dev-photo__empty text { display: block; color: #667386; font-size: 24rpx; text-align: center; }
.h5-dev-photo__empty text:first-child { margin-bottom: 8rpx; color: #0057c2; font-size: 30rpx; font-weight: 700; }
.h5-dev-form { padding: 8rpx 24rpx; }
.h5-dev-field { min-height: 96rpx; gap: 16rpx; border-bottom: 1rpx solid rgba(60, 60, 67, .08); }
.h5-dev-field:last-child { border-bottom: 0; }
.h5-dev-field > text:first-child { width: 148rpx; flex: none; color: #667386; font-size: 26rpx; }
.h5-dev-field input, .h5-dev-field > strong { flex: 1; min-width: 0; overflow: hidden; color: #132033; font-size: 28rpx; font-weight: 650; text-align: right; text-overflow: ellipsis; white-space: nowrap; }
.h5-dev-field > strong.mute { color: #98a2b3; font-weight: 500; }
.h5-dev-field--season { align-items: flex-start; padding: 22rpx 0; }
.h5-dev-seasons { display: flex; flex: 1; flex-wrap: wrap; justify-content: flex-end; gap: 10rpx; }
.h5-dev-more, .h5-dev-hint { display: block; color: #667386; font-size: 24rpx; text-align: center; }
.h5-dev-more { padding: 12rpx 0 28rpx; }
.h5-dev-hint { margin-bottom: 12rpx; }
.h5-dev-bar__row { gap: 16rpx; }
.h5-dev-bar__row button { flex: 1; }
.h5-dev-ghost {
  height: 96rpx;
  margin: 0;
  border-radius: 16rpx;
  background: #e8f1ff;
  color: #0057c2;
  font-size: 32rpx;
  font-weight: 700;
  line-height: 96rpx;
}
.h5-dev-ghost::after, .cut-sticky-button::after { border: 0; }
.h5-dev-mask {
  position: fixed;
  z-index: 80;
  right: 0;
  bottom: 0;
  left: 0;
  top: 0;
  background: rgba(16, 24, 40, .45);
}
.h5-dev-sheet {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  padding: 12rpx 28rpx calc(24rpx + env(safe-area-inset-bottom));
  border-radius: 28rpx 28rpx 0 0;
  background: #fff;
}
.h5-dev-sheet__head { justify-content: space-between; min-height: 88rpx; }
.h5-dev-sheet__head strong { color: #132033; font-size: 32rpx; }
.h5-dev-sheet__list { height: 52vh; }
.h5-dev-option { justify-content: space-between; min-height: 96rpx; border-bottom: 1rpx solid rgba(60, 60, 67, .08); }
.h5-dev-option > text, .h5-dev-option > view > text:first-child { color: #132033; font-size: 28rpx; }
.h5-dev-check { color: #98a2b3; font-size: 24rpx; }
.h5-dev-check.on { color: #0057c2; font-weight: 700; }
.h5-dev-sheet__empty { padding: 80rpx 0; color: #667386; font-size: 26rpx; text-align: center; }
</style>
