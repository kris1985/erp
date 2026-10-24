<template>
  <view class="page h5-wh" :class="{ 'h5-wh--sub': mode !== 'list' }">
    <view v-if="!canSee" class="h5-home-empty">没有物料仓权限</view>

    <template v-else-if="mode === 'list'">
      <view class="card h5-wh-search">
        <input :value="keyword" confirm-type="search" placeholder="编号、名称、颜色、尺码、供应商" @input="onKeyword" />
        <text v-if="keyword" @click="keyword = ''">清除</text>
      </view>
      <scroll-view class="h5-wh-cats" scroll-x :show-scrollbar="false">
        <text :class="{ on: categoryId == null }" @click="setCategory(null)">全部</text>
        <text v-for="item in visibleCategories" :key="item.id" :class="{ on: categoryId === item.id }" @click="setCategory(item.id)">{{ item.name }}</text>
      </scroll-view>
      <view class="h5-wh-filters">
        <text :class="{ on: !onlyShort }" @click="onlyShort = false">全部库存</text>
        <text :class="{ on: onlyShort }" @click="onlyShort = true">只看预警</text>
      </view>
      <text v-if="selectMode" class="h5-wh-hint">{{ selectHint }}</text>

      <view v-if="loading && !rows.length" class="h5-home-empty">加载中…</view>
      <view v-else-if="!shownRows.length" class="h5-home-empty">{{ emptyText }}</view>
      <view v-else class="h5-wh-list">
        <view
          v-for="row in shownRows"
          :key="row.pool_row_key"
          class="card h5-wh-card"
          :class="{ 'is-picked': !!picked[row.pool_row_key], 'is-locked': !!selectMode && !canSelect(row) }"
          @click="onCard(row)"
        >
          <view class="h5-wh-card__main">
            <view v-if="selectMode" class="h5-wh-check" :class="{ on: !!picked[row.pool_row_key] }" />
            <image v-if="row.image_url" class="h5-wh-thumb" :src="displayImageUrl(row.image_url)" mode="aspectFill" @click.stop="previewImage(row.image_url)" />
            <view v-else class="h5-wh-thumb">{{ swatch(row) }}</view>
            <view class="h5-wh-card__body">
              <view class="h5-wh-card__top">
                <view class="h5-wh-card__title">
                  <strong>{{ row.supplier_product_name || row.supplier_product_code }}</strong>
                  <text v-if="cardMeta(row)">{{ cardMeta(row) }}</text>
                </view>
                <text v-if="row.alert_short" class="h5-wh-short">缺</text>
              </view>
              <view class="h5-wh-metrics">
                <view><text>现存</text><strong>{{ formatNum(row.on_hand_qty) }}</strong></view>
                <view><text>在途</text><strong :class="{ warn: Number(row.in_transit_qty) > 0 }">{{ formatNum(row.in_transit_qty) }}</strong></view>
                <view><text>需求</text><strong :class="{ warn: Number(row.actual_demand_qty) > 0 }">{{ formatNum(row.actual_demand_qty) }}</strong></view>
                <view><text>预警</text><strong :class="alertClass(row)">{{ formatNum(row.alert_qty) }}</strong></view>
              </view>
              <text v-if="!selectMode && row.has_sizes && isShort(row)" class="h5-wh-peek">点开查看各码</text>
            </view>
          </view>
        </view>
        <view class="h5-wh-more">{{ shownRows.length >= filteredRows.length ? `共 ${filteredRows.length} 种` : '上拉加载更多' }}</view>
      </view>

      <view v-if="selectMode" class="cut-sticky-bar h5-wh-bar">
        <button class="h5-wh-ghost" @click="cancelSelect">取消</button>
        <button class="primary-button h5-wh-primary" :loading="saving" :disabled="!pickedCount || saving" @click="confirmSelect">{{ confirmLabel }}</button>
      </view>
      <view v-else class="cut-sticky-bar h5-wh-bar">
        <button class="h5-wh-ghost" @click="openActions">{{ canWrite ? '领退' : '领退记录' }}</button>
        <button v-if="canWrite" class="primary-button h5-wh-primary" @click="openInbound">手工入库</button>
      </view>
    </template>

    <template v-else-if="mode === 'detail' && current">
      <view class="card h5-wh-hero">
        <image v-if="current.image_url" :src="displayImageUrl(current.image_url)" mode="aspectFill" @click="previewImage(current.image_url)" />
        <view v-else class="h5-wh-hero__empty">{{ swatch(current) }}</view>
        <view class="h5-wh-hero__copy">
          <strong>{{ current.supplier_product_name || '未命名' }}</strong>
          <text>{{ current.supplier_product_code }}</text>
          <text v-if="current.alert_short" class="h5-wh-short">库存预警</text>
        </view>
      </view>
      <view class="card h5-wh-facts">
        <view class="h5-wh-fact"><text>分类</text><strong>{{ current.category_name || '—' }}</strong></view>
        <view class="h5-wh-fact"><text>颜色</text><strong>{{ current.color_name || '—' }}</strong></view>
        <view class="h5-wh-fact"><text>单价</text><strong>{{ current.unit_price == null ? '—' : `¥${formatNum(current.unit_price)}` }}<text v-if="current.pricing_unit_name"> / {{ current.pricing_unit_name }}</text></strong></view>
        <view class="h5-wh-fact"><text>供应商</text><strong>{{ current.partner_name || '—' }}</strong></view>
        <view class="h5-wh-fact"><text>现存</text><strong>{{ formatNum(current.on_hand_qty) }}</strong></view>
        <view class="h5-wh-fact"><text>在途</text><strong :class="{ warn: Number(current.in_transit_qty) > 0 }">{{ formatNum(current.in_transit_qty) }}</strong></view>
        <view class="h5-wh-fact"><text>生产需求</text><strong :class="{ warn: Number(current.actual_demand_qty) > 0 }">{{ formatNum(current.actual_demand_qty) }}</strong></view>
        <view class="h5-wh-fact"><text>预警</text><strong :class="alertClass(current)">{{ formatNum(current.alert_qty) }}</strong></view>
      </view>

      <view v-if="current.has_sizes" class="card h5-wh-block">
        <text class="h5-wh-block__title">各码</text>
        <text class="h5-wh-note">左右滑动查看每个码的现存。红色是预警为负的码。</text>
        <view v-if="!detailSizes.length" class="h5-wh-empty">各码现存、在途、需求、预警都是 0</view>
        <view v-else class="h5-wh-board">
          <view class="h5-wh-board__labs">
            <text>码</text>
            <text>现存</text>
            <text>在途</text>
            <text>需求</text>
            <text>预警</text>
          </view>
          <scroll-view class="h5-wh-board__scroll" scroll-x :show-scrollbar="false">
            <view class="h5-wh-board__cols">
              <view v-for="cell in detailSizes" :key="cell.key" class="h5-wh-board__col" :class="{ short: cell.short }">
                <text>{{ cell.label }}</text>
                <strong>{{ formatNum(cell.onHand) }}</strong>
                <text :class="{ warn: cell.transit > 0 }">{{ numText(cell.transit) }}</text>
                <text :class="{ warn: cell.demand > 0 }">{{ numText(cell.demand) }}</text>
                <strong :class="{ short: cell.short }">{{ numText(cell.alert) }}</strong>
              </view>
            </view>
          </scroll-view>
        </view>
      </view>

      <view class="cut-sticky-bar h5-wh-bar">
        <button class="h5-wh-ghost" @click="openLedger">流水</button>
        <button v-if="canAdjust" class="h5-wh-ghost" @click="openCount">盘点</button>
        <button v-if="canDeleteCurrent" class="h5-wh-ghost h5-wh-ghost--danger" @click="removeCurrent">删除</button>
      </view>
    </template>

    <template v-else-if="mode === 'ledger'">
      <text class="h5-wh-back" @click="goBack">‹ 返回物料</text>
      <view v-if="ledgerLoading" class="h5-home-empty">加载中…</view>
      <view v-else-if="!ledgers.length" class="h5-home-empty">暂无出入记录</view>
      <view v-for="row in shownLedgers" :key="row.id" class="card h5-wh-ledger">
        <view class="h5-wh-ledger__top">
          <text>{{ ledgerTime(row.created_at) }}</text>
          <strong :class="Number(row.qty_delta) >= 0 ? 'in' : 'out'">{{ Number(row.qty_delta) >= 0 ? '+' : '' }}{{ formatNum(row.qty_delta) }}</strong>
        </view>
        <text class="h5-wh-ledger__type">{{ row.ledger_type_label || row.ledger_type }}{{ row.size_value ? ` · ${row.size_value}` : '' }}</text>
        <text class="h5-wh-meta">余 {{ formatNum(row.balance_after) }}{{ row.header_no || row.order_no ? ` · ${row.header_no || row.order_no}` : '' }}{{ row.po_no ? ` · ${row.po_no}` : '' }}{{ row.picker_name ? ` · ${row.picker_name}` : '' }}</text>
      </view>
      <view v-if="ledgers.length > shownLedgers.length" class="h5-wh-more">上拉加载更多</view>
    </template>

    <template v-else-if="mode === 'count' && current">
      <text class="h5-wh-back" @click="goBack">‹ 返回物料</text>
      <view class="card h5-wh-hero">
        <image v-if="current.image_url" :src="displayImageUrl(current.image_url)" mode="aspectFill" />
        <view v-else class="h5-wh-hero__empty">{{ swatch(current) }}</view>
        <view class="h5-wh-hero__copy">
          <strong>{{ current.supplier_product_code }}</strong>
          <text>{{ current.supplier_product_name || '—' }}</text>
        </view>
      </view>
      <text class="h5-wh-hint">按码填写实盘数量。空着的码不改。</text>
      <view class="card h5-wh-count">
        <view v-for="part in countParts" :key="part.key" class="h5-wh-count__cell">
          <text>{{ part.size_value || '数量' }}</text>
          <text class="h5-wh-count__sub">现存 {{ formatNum(part.on_hand_qty) }}</text>
          <input :value="part.actual_qty" type="digit" placeholder="实盘" @input="onCountQty(part, $event)" />
        </view>
      </view>
      <view class="cut-sticky-bar h5-wh-bar">
        <button class="h5-wh-ghost" @click="goBack">取消</button>
        <button class="primary-button h5-wh-primary" :loading="saving" @click="submitCount">确定盘点</button>
      </view>
    </template>

    <template v-else-if="mode === 'inbound'">
      <text class="h5-wh-hint">保存后计入物料仓，并同步到物料色卡和供应商。编号已存在时更新色卡并累加数量。</text>
      <view class="card h5-wh-form">
        <view v-if="inbound.image_url" class="h5-wh-photo">
          <image :src="displayImageUrl(inbound.image_url)" mode="aspectFill" @click="previewImage(inbound.image_url)" />
          <text v-if="!uploading" class="h5-wh-photo__clear" @click.stop="inbound.image_url = ''">清除</text>
        </view>
        <view class="h5-wh-photo-actions">
          <button :disabled="uploading" @click="choosePhoto('camera')">{{ uploading ? '上传中…' : '拍照' }}</button>
          <button :disabled="uploading" @click="choosePhoto('album')">从相册选择</button>
        </view>
        <view class="h5-wh-field"><text>物料编号</text><input :value="inbound.product_code" maxlength="50" placeholder="手填编号" @input="onInbound('product_code', $event)" /></view>
        <view class="h5-wh-field"><text>名称</text><input :value="inbound.name" maxlength="100" placeholder="物料名称" @input="onInbound('name', $event)" /></view>
        <view class="h5-wh-field" @click="openSheet('category')"><text>分类</text><strong :class="{ need: !inbound.category_id }">{{ optionName(categories, inbound.category_id) || '选填' }}</strong><text class="h5-wh-chev">›</text></view>
        <view class="h5-wh-field" @click="openSheet('color')"><text>颜色</text><strong :class="{ need: !inbound.color_id }">{{ optionName(colors, inbound.color_id) || '选填' }}</strong><text class="h5-wh-chev">›</text></view>
        <view class="h5-wh-field" @click="openSheet('size')"><text>尺码</text><strong :class="{ need: !inbound.size_id }">{{ sizeName(inbound.size_id) || '未按码' }}</strong><text class="h5-wh-chev">›</text></view>
        <view class="h5-wh-field"><text>单价</text><input :value="inbound.unit_price" type="digit" placeholder="选填" @input="onInbound('unit_price', $event)" /></view>
        <view class="h5-wh-field" @click="openSheet('unit')"><text>计价单位</text><strong :class="{ need: !inbound.pricing_unit_id }">{{ optionName(units, inbound.pricing_unit_id) || '选填' }}</strong><text class="h5-wh-chev">›</text></view>
        <view class="h5-wh-field h5-wh-field--input"><text>供应商</text><input :value="inbound.supplier_name" maxlength="100" placeholder="手填，已有名称会直接使用" @input="onInbound('supplier_name', $event)" @focus="suggestOpen = true" @blur="hideSuggestions" /></view>
        <view v-if="suggestOpen && supplierSuggestions.length" class="h5-wh-suggest">
          <text v-for="name in supplierSuggestions" :key="name" @click="pickSupplier(name)">{{ name }}</text>
        </view>
        <view class="h5-wh-field"><text>数量</text><input :value="inbound.qty" type="digit" placeholder="大于 0" @input="onInbound('qty', $event)" /></view>
      </view>
      <view class="cut-sticky-bar h5-wh-bar">
        <button class="h5-wh-ghost" @click="goBack">取消</button>
        <button class="primary-button h5-wh-primary" :loading="saving" @click="submitInbound">确定入库</button>
      </view>
    </template>

    <template v-else-if="mode === 'qty'">
      <text class="h5-wh-back" @click="goBack">‹ 返回勾选</text>
      <text class="h5-wh-hint">{{ qtyKind === 'purchase' ? `${returnTitle}。每个码单独填数量，不能超过可退。` : '每个码单独填数量，0 或空着的码会跳过。' }}</text>
      <view v-for="group in qtyGroups" :key="group.key" class="card h5-wh-qty">
        <view class="h5-wh-qty__head">
          <view>
            <strong>{{ group.name }}</strong>
            <text>{{ group.code }}</text>
          </view>
        </view>
        <view class="h5-wh-count" :class="{ 'h5-wh-count--price': qtyKind === 'purchase' }">
          <view v-for="line in group.lines" :key="line.key" class="h5-wh-count__cell">
            <view class="h5-wh-count__top">
              <text>{{ line.size_value || '数量' }}</text>
              <text v-if="group.lines.length > 1" class="danger" @click="removeQtyLine(line.key)">移除</text>
            </view>
            <text class="h5-wh-count__sub">{{ line.capLabel }} {{ formatNum(line.cap) }}{{ line.unit_name ? ` ${line.unit_name}` : '' }}</text>
            <input :value="line.qty" type="digit" placeholder="数量" @input="onLineQty(line, 'qty', $event)" />
            <input v-if="qtyKind === 'purchase'" :value="line.unit_price" type="digit" placeholder="单价" @input="onLineQty(line, 'unit_price', $event)" />
            <text v-if="qtyKind === 'purchase'" class="h5-wh-count__sub">金额 {{ returnAmount(line) }}</text>
          </view>
        </view>
      </view>
      <view v-if="qtyKind === 'purchase'" class="card h5-wh-form">
        <view class="h5-wh-field"><text>备注</text><input :value="returnNote" maxlength="255" placeholder="选填" @input="returnNote = inputValue($event)" /></view>
      </view>
      <view class="cut-sticky-bar h5-wh-bar">
        <button class="h5-wh-ghost" @click="goBack">取消</button>
        <button class="primary-button h5-wh-primary" :loading="saving" :disabled="!qtyLines.length" @click="submitQty">{{ qtyKind === 'purchase' ? '确定退货' : '生成确认码' }}</button>
      </view>
    </template>

    <template v-else-if="mode === 'production'">
      <text class="h5-wh-back" @click="goBack">‹ 返回</text>
      <view class="card h5-wh-search">
        <input :value="headerQuery" confirm-type="search" placeholder="生产单号或款号" @input="onHeaderQuery" />
      </view>
      <view v-if="!productionHeader" class="h5-wh-orders">
        <view v-if="searching" class="h5-home-empty">查找中…</view>
        <view v-else-if="!headerOptions.length" class="h5-home-empty">没有匹配的生产单</view>
        <view v-for="row in headerOptions" :key="row.header_id" class="card h5-wh-order" @click="chooseHeader(row)">
          <strong>{{ row.header_no }}</strong>
          <text>{{ headerMeta(row) }}</text>
        </view>
      </view>
      <template v-else>
        <view class="card h5-wh-order h5-wh-order--on">
          <view>
            <strong>{{ productionHeader.header_no }}</strong>
            <text>{{ productionHeader.total_qty }} 双</text>
          </view>
          <text class="h5-wh-back" @click="clearHeader">换一张</text>
        </view>
        <text class="h5-wh-hint">{{ slipKind.endsWith('_return') ? '填写要退回仓库的数量，不能超过可退。' : '填写本次领用。上方是需求，数量不能超过现存。' }}</text>
        <view v-if="previewing" class="h5-home-empty">正在读取物料…</view>
        <view v-else-if="!productionLines.length" class="h5-home-empty">{{ slipKind.endsWith('_return') ? '这张生产单没有可退物料' : '这张生产单没有可领物料' }}</view>
        <view v-for="line in productionLines" :key="line.requirement_id || line.supplier_product_id" class="card h5-wh-qty">
          <view class="h5-wh-qty__head">
            <view class="h5-wh-prod">
              <image v-if="line.image_url" :src="displayImageUrl(line.image_url)" mode="aspectFill" />
              <view>
                <strong>{{ line.material_name || line.material_code }}</strong>
                <text>{{ [line.material_code, line.color_name, line.partner_name].filter(Boolean).join(' · ') }}</text>
              </view>
            </view>
          </view>
          <view v-if="sizeParts(line).length > 1" class="h5-wh-count">
            <view v-for="part in sizeParts(line)" :key="part.requirement_id || part.size_value" class="h5-wh-count__cell" :class="{ short: !!partWarn(part) }">
              <text>{{ part.size_value || '数量' }}</text>
              <text v-for="hint in partHints(part)" :key="hint" class="h5-wh-count__sub">{{ hint }}</text>
              <input :value="part.qty" type="digit" placeholder="本次" @input="onPartQty(part, $event)" />
              <text v-if="partWarn(part)" class="h5-wh-over">{{ partWarn(part) }}</text>
            </view>
          </view>
          <view v-else v-for="part in sizeParts(line)" :key="part.requirement_id || 'all'" class="h5-wh-size-edit">
            <view class="h5-wh-size-edit__meta">
              <strong>{{ part.size_value || line.unit_name || '数量' }}</strong>
              <text>{{ partCaption(part) }}</text>
            </view>
            <input :value="part.qty" type="digit" placeholder="0" @input="onPartQty(part, $event)" />
            <text v-if="partWarn(part)" class="h5-wh-over">{{ partWarn(part) }}</text>
          </view>
        </view>
        <view class="cut-sticky-bar h5-wh-bar">
          <button class="h5-wh-ghost" @click="goBack">取消</button>
          <button class="primary-button h5-wh-primary" :loading="saving" :disabled="!productionReady" @click="submitProduction">生成确认码</button>
        </view>
      </template>
    </template>

    <template v-else-if="mode === 'sign' && slip">
      <view class="card h5-wh-sign">
        <text class="h5-wh-sign__kind">{{ slip.kind_label || '领退单' }}</text>
        <strong>{{ slip.doc_no }}</strong>
        <template v-if="slip.status === 'signed'">
          <text class="h5-wh-sign__ok">{{ signerName }} 已确认，库存已更新</text>
        </template>
        <template v-else>
          <text class="h5-wh-hint">请对方用手机扫描这张码。确认后这里会自动更新。</text>
          <image v-if="slip.qr_png" class="h5-wh-qr" :src="slip.qr_png" mode="aspectFit" />
          <text v-else class="h5-wh-hint">确认码生成失败</text>
          <text class="h5-wh-meta">等待扫码确认…</text>
        </template>
      </view>
      <view class="cut-sticky-bar h5-wh-bar">
        <button v-if="slip.status === 'signed'" class="primary-button h5-wh-primary" @click="finishSign">返回物料仓</button>
        <button v-else class="h5-wh-ghost h5-wh-ghost--danger" @click="goBack">取消这张单</button>
      </view>
    </template>

    <template v-else-if="mode === 'history'">
      <text class="h5-wh-back" @click="goBack">‹ 返回</text>
      <view v-if="historyLoading" class="h5-home-empty">加载中…</view>
      <view v-else-if="!history.length" class="h5-home-empty">暂无已确认的领退记录</view>
      <view v-for="row in history" :key="row.id" class="card h5-wh-history" @click="openHistory(row)">
        <view class="h5-wh-ledger__top">
          <strong>{{ row.kind_label }}</strong>
          <text>{{ ledgerTime(row.signed_at || row.created_at) }}</text>
        </view>
        <text class="h5-wh-meta">{{ row.header_no || '无生产单' }} · {{ row.picker_name || '—' }} · {{ row.line_count }} 种物料</text>
      </view>
    </template>

    <template v-else-if="mode === 'historyDetail' && historyDetail">
      <text class="h5-wh-back" @click="goBack">‹ 返回记录</text>
      <view class="card h5-wh-block">
        <text class="h5-wh-block__title">{{ historyDetail.doc_no }}</text>
        <text class="h5-wh-meta">{{ historyDetail.kind_label }} · {{ historyPerson }} {{ historyDetail.picker_name || '—' }}{{ historyDetail.header_no ? ` · ${historyDetail.header_no}` : '' }}</text>
        <view v-for="line in historyDetail.lines || []" :key="line.id" class="h5-wh-line">
          <view>
            <strong>{{ line.material_name }}</strong>
            <text>{{ line.material_code }}{{ line.size_value ? ` · ${line.size_value}` : '' }}</text>
          </view>
          <strong>{{ line.qty }}{{ line.unit_name || '' }}</strong>
        </view>
        <image v-if="historyDetail.signature_data" class="h5-wh-sign-img" :src="historyDetail.signature_data" mode="widthFix" />
      </view>
    </template>

    <view v-if="sheet" class="h5-wh-mask" @click="closeSheet">
      <view class="h5-wh-sheet" @click.stop>
        <view class="h5-wh-sheet__head">
          <text>{{ sheetTitle }}</text>
          <text @click="closeSheet">关闭</text>
        </view>
        <template v-if="sheet === 'actions'">
          <view class="h5-wh-action" @click="startProduction('production')"><strong>生产领主料</strong><text>按生产单填写数量</text></view>
          <view class="h5-wh-action" @click="startProduction('production_return')"><strong>生产退主料</strong><text>退回这张生产单领过的料</text></view>
          <view class="h5-wh-action" @click="startSelect('aux')"><strong>生产领辅料耗材</strong><text>只显示辅料分类</text></view>
          <view class="h5-wh-action" @click="startSelect('aux_return')"><strong>生产退辅料</strong><text>辅料退回仓库</text></view>
          <view class="h5-wh-action" @click="startSelect('dev')"><strong>开发部领料</strong><text>从现存量勾选</text></view>
          <view class="h5-wh-action" @click="startSelect('dev_return')"><strong>开发部退料</strong><text>开发领用退回仓库</text></view>
          <view class="h5-wh-action" @click="startSelect('return')"><strong>采购退货</strong><text>一次只能退同一个供应商</text></view>
          <view class="h5-wh-action" @click="openHistoryList"><strong>领退记录</strong><text>已确认的领料和退料</text></view>
        </template>
        <template v-else>
          <input class="h5-wh-sheet__search" :value="sheetQuery" placeholder="搜索" @input="sheetQuery = inputValue($event)" />
          <scroll-view scroll-y class="h5-wh-sheet__list">
            <view class="h5-wh-option" @click="pickSheet(null)"><text>不选</text></view>
            <view v-for="item in sheetOptions" :key="item.id" class="h5-wh-option" @click="pickSheet(item.id)">
              <text>{{ item.name }}</text>
            </view>
            <view v-if="!sheetOptions.length" class="h5-wh-empty">没有匹配项</view>
          </scroll-view>
        </template>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { onBackPress, onPullDownRefresh, onReachBottom, onShow, onUnload } from '@dcloudio/uni-app'
import { get, post, del, uploadFile } from '../../services/http'
import { getProfile } from '../../services/storage'

type Mode = 'list' | 'detail' | 'ledger' | 'count' | 'inbound' | 'qty' | 'production' | 'sign' | 'history' | 'historyDetail'
type SelectKind = 'return' | 'dev' | 'aux' | 'dev_return' | 'aux_return'
type SlipKind = 'dev' | 'aux' | 'production' | 'dev_return' | 'aux_return' | 'production_return'
type SheetKind = '' | 'actions' | 'category' | 'color' | 'size' | 'unit'

const SLIP_TITLES: Record<SlipKind, string> = {
  dev: '开发部领料',
  aux: '生产领辅料耗材',
  production: '生产领主料',
  dev_return: '开发部退料',
  aux_return: '生产退辅料',
  production_return: '生产退主料',
}

const profile = ref(getProfile())
const mode = ref<Mode>('list')
const rows = ref<any[]>([])
const categories = ref<any[]>([])
const sizes = ref<any[]>([])
const colors = ref<any[]>([])
const units = ref<any[]>([])
const supplierNames = ref<string[]>([])
const loading = ref(false)
const keyword = ref('')
const categoryId = ref<number | null>(null)
const onlyShort = ref(false)
const visibleCount = ref(20)
const selectMode = ref<SelectKind | null>(null)
const picked = reactive<Record<string, boolean>>({})
const current = ref<any>(null)
const ledgers = ref<any[]>([])
const ledgerLoading = ref(false)
const ledgerCount = ref(30)
const countParts = ref<any[]>([])
const qtyLines = ref<any[]>([])
const qtyKind = ref<'pickup' | 'purchase'>('pickup')
const returnTitle = ref('退货')
const returnNote = ref('')
const slipKind = ref<SlipKind>('dev')
const headerQuery = ref('')
const headerOptions = ref<any[]>([])
const searching = ref(false)
const previewing = ref(false)
const productionHeader = ref<any>(null)
const productionLines = ref<any[]>([])
const slip = ref<any>(null)
const history = ref<any[]>([])
const historyLoading = ref(false)
const historyDetail = ref<any>(null)
const sheet = ref<SheetKind>('')
const sheetQuery = ref('')
const suggestOpen = ref(false)
const saving = ref(false)
const uploading = ref(false)
const inbound = reactive({
  image_url: '',
  product_code: '',
  name: '',
  category_id: null as number | null,
  color_id: null as number | null,
  size_id: null as number | null,
  unit_price: '',
  pricing_unit_id: null as number | null,
  supplier_name: '',
  qty: '',
})

let pollTimer = 0
let headerTimer = 0
let loaded = false

const features = computed(() => profile.value?.featurePermissions || [])
const canSee = computed(() => features.value.includes('shared_materials') || features.value.includes('shared_materials_write'))
const canWrite = computed(() => features.value.includes('shared_materials_write'))
const canAdjust = computed(() => canWrite.value)
const auxPicking = computed(() => selectMode.value === 'aux' || selectMode.value === 'aux_return')
const auxiliaryIds = computed(() => new Set(categories.value.filter(item => item.is_auxiliary).map(item => Number(item.id))))
const activeCategories = computed(() => categories.value.filter(item => item.is_active !== false))
const visibleCategories = computed(() => (auxPicking.value ? activeCategories.value.filter(item => item.is_auxiliary) : activeCategories.value))
const activeSizes = computed(() => [...sizes.value.filter(item => item.is_active !== false)].sort((a, b) => Number(a.sort_order || 0) - Number(b.sort_order || 0) || String(a.size_value).localeCompare(String(b.size_value), 'zh-CN', { numeric: true })))

const filteredRaw = computed(() => {
  let list = rows.value
  if (auxPicking.value) list = list.filter(row => auxiliaryIds.value.has(Number(row.category_id)))
  if (categoryId.value != null) list = list.filter(row => Number(row.category_id) === Number(categoryId.value))
  const text = keyword.value.trim().toLowerCase()
  if (!text) return list
  return list.filter(row => [row.supplier_product_code, row.supplier_product_name, row.category_name, row.color_name, row.size_value, row.pricing_unit_name, row.partner_name].map(item => String(item || '')).join(' ').toLowerCase().includes(text))
})
const groupedRows = computed(() => groupMaterialRows(filteredRaw.value))
const filteredRows = computed(() => (onlyShort.value ? groupedRows.value.filter(row => row.alert_short || Number(row.alert_qty) < 0) : groupedRows.value))
const shownRows = computed(() => filteredRows.value.slice(0, visibleCount.value))
const selectedRows = computed(() => filteredRows.value.filter(row => picked[row.pool_row_key]))
const pickedCount = computed(() => selectedRows.value.length)
const shownLedgers = computed(() => ledgers.value.slice(0, ledgerCount.value))
const supplierSuggestions = computed(() => {
  const text = inbound.supplier_name.trim().toLowerCase()
  return supplierNames.value.filter(name => !text || name.toLowerCase().includes(text)).slice(0, 6)
})
const confirmLabel = computed(() => `${selectMode.value === 'return' ? '确认退货' : '填写数量'}${pickedCount.value ? ` · ${pickedCount.value}` : ''}`)
const selectHint = computed(() => {
  if (selectMode.value === 'return') return '勾选要退给供应商的物料，一次只能退同一家。'
  if (auxPicking.value && !auxiliaryIds.value.size) return '还没有辅料分类。请先在物料分类里打开「是否辅料」。'
  if (auxPicking.value) return '只显示辅料。勾选后填写数量。'
  if (selectMode.value === 'dev_return' || selectMode.value === 'aux_return') return '勾选要退回仓库的物料，确认后填写数量。'
  return '勾选要领的物料，确认后填写数量。'
})
const emptyText = computed(() => (auxPicking.value && !auxiliaryIds.value.size ? '还没有辅料分类' : '没有匹配的物料'))
const canDeleteCurrent = computed(() => canAdjust.value && deletableParts(current.value).length > 0)
const detailSizes = computed(() => sizeCells(current.value))
const qtyGroups = computed(() => {
  const groups = new Map<string, { key: string; name: string; code: string; lines: any[] }>()
  for (const line of qtyLines.value) {
    const key = String(line.supplier_product_id)
    const group = groups.get(key) || { key, name: line.name || line.code || '物料', code: line.code || '', lines: [] as any[] }
    group.lines.push(line)
    groups.set(key, group)
  }
  return [...groups.values()]
})
const productionReady = computed(() => productionLines.value.some(line => sizeParts(line).some(part => Number(part.qty) > 0)) && !productionLines.value.some(line => sizeParts(line).some(part => partWarn(part))))
const signerName = computed(() => slip.value?.picker_name || (String(slip.value?.kind || '').includes('return') ? '退料人' : '领料人'))
const historyPerson = computed(() => String(historyDetail.value?.kind || '').includes('return') ? '退料人' : '领料人')
const sheetTitles: Record<string, string> = { actions: '领退', category: '分类', color: '颜色', size: '尺码', unit: '计价单位' }
const sheetTitle = computed(() => sheetTitles[sheet.value] || '')
const sheetOptions = computed(() => {
  const text = sheetQuery.value.trim().toLowerCase()
  const source = sheet.value === 'category' ? visibleCategories.value : sheet.value === 'color' ? colors.value : sheet.value === 'unit' ? units.value : sheet.value === 'size' ? activeSizes.value : []
  return source
    .filter(item => !text || String(item.name || item.size_value || '').toLowerCase().includes(text))
    .map(item => ({ id: item.id, name: item.name || item.size_value }))
})

watch([mode, selectMode, slipKind, slip], () => {
  const titles: Record<Mode, string> = {
    list: selectMode.value ? selectHintTitle() : '物料仓',
    detail: '物料详情',
    ledger: '出入流水',
    count: '盘点',
    inbound: '手工入库',
    qty: qtyKind.value === 'purchase' ? returnTitle.value : SLIP_TITLES[slipKind.value],
    production: SLIP_TITLES[slipKind.value],
    sign: slip.value?.status === 'signed' ? '已确认' : '等待确认',
    history: '领退记录',
    historyDetail: historyDetail.value?.doc_no || '单据详情',
  }
  uni.setNavigationBarTitle({ title: titles[mode.value] || '物料仓' })
})
watch([keyword, categoryId, onlyShort, selectMode], () => {
  visibleCount.value = 20
})

function selectHintTitle() {
  if (selectMode.value === 'return') return '采购退货'
  if (selectMode.value === 'aux') return '领辅料'
  if (selectMode.value === 'aux_return') return '退辅料'
  if (selectMode.value === 'dev_return') return '开发部退料'
  return '开发部领料'
}
function inputValue(event: any) {
  return String(event?.detail?.value ?? '')
}
function toast(title: string) {
  uni.showToast({ title, icon: 'none' })
}
function asItems(result: any): any[] {
  if (Array.isArray(result)) return result
  return Array.isArray(result?.items) ? result.items : []
}
function formatNum(value: any) {
  const number = Number(value)
  if (Number.isNaN(number)) return '—'
  return Number.isInteger(number) ? String(number) : number.toFixed(4).replace(/\.?0+$/, '')
}
function onHandQty(row: any) {
  if (row?.on_hand_qty != null && row.on_hand_qty !== '') return row.on_hand_qty
  return Number(row?.pool_qty ?? row?.qty ?? 0) + Number(row?.occupied_qty || 0)
}
function isShort(row: any) {
  return !!(row?.alert_short || Number(row?.alert_qty) < 0)
}
function alertClass(row: any) {
  return isShort(row) ? 'short' : ''
}
function sumField(parts: any[], pick: (row: any) => any) {
  const total = parts.reduce((sum, row) => sum + Number(pick(row) || 0), 0)
  return Math.round(total * 10000) / 10000
}
function partRows(row: any): any[] {
  return Array.isArray(row?.parts) && row.parts.length ? row.parts : row ? [row] : []
}
function groupMaterialRows(list: any[]) {
  const groups = new Map<number, any[]>()
  const order: number[] = []
  for (const row of list) {
    const id = Number(row.supplier_product_id)
    if (!groups.has(id)) {
      groups.set(id, [])
      order.push(id)
    }
    groups.get(id)!.push(row)
  }
  return order.map(id => {
    const parts = groups.get(id) || []
    const first = parts[0] || {}
    const sized = parts.filter(row => row.size_value)
    const hasSizes = sized.length > 0
    const sizeMap: Record<string, any> = {}
    for (const row of sized) sizeMap[String(row.size_value)] = row
    return {
      ...first,
      pool_row_key: `mat-${id}`,
      has_sizes: hasSizes,
      parts,
      size_map: sizeMap,
      on_hand_qty: sumField(parts, row => onHandQty(row)),
      pool_qty: sumField(parts, row => row.pool_qty ?? row.qty ?? 0),
      qty: sumField(parts, row => row.qty ?? 0),
      occupied_qty: sumField(parts, row => row.occupied_qty || 0),
      actual_demand_qty: sumField(parts, row => row.actual_demand_qty || 0),
      in_transit_qty: sumField(parts, row => row.in_transit_qty || 0),
      alert_qty: sumField(parts, row => row.alert_qty || 0),
      returnable_qty: sumField(parts, row => row.returnable_qty || 0),
      alert_short: parts.some(row => Number(row.alert_qty) < 0),
      in_transit_orders: parts.flatMap(row => (Array.isArray(row.in_transit_orders) ? row.in_transit_orders : []).map((item: any) => ({ ...item, size_value: row.size_value || '' }))),
      alert_orders: parts.flatMap(row => (Array.isArray(row.alert_orders) ? row.alert_orders : []).map((item: any) => ({ ...item, size_value: row.size_value || item.size_value || '' }))),
    }
  })
}
function sizeRank(value: string) {
  const index = activeSizes.value.findIndex(size => String(size.size_value) === value)
  return index >= 0 ? index : 1000
}
function sortedSizeParts(row: any) {
  return partRows(row)
    .filter(part => part?.size_value)
    .sort((a, b) => sizeRank(String(a.size_value)) - sizeRank(String(b.size_value)) || String(a.size_value).localeCompare(String(b.size_value), 'zh-CN', { numeric: true }))
}
function numText(value: number) {
  return value ? formatNum(value) : ''
}
function sizeCells(row: any) {
  if (!row?.has_sizes) return []
  return sortedSizeParts(row).map(part => {
    const onHand = Number(onHandQty(part)) || 0
    const transit = Number(part.in_transit_qty) || 0
    const demand = Number(part.actual_demand_qty) || 0
    const alert = Number(part.alert_qty) || 0
    return {
      key: String(part.size_id ?? part.size_value),
      label: String(part.size_value),
      onHand,
      transit,
      demand,
      alert,
      short: alert < 0,
      visible: onHand !== 0 || transit !== 0 || demand !== 0 || alert !== 0,
    }
  }).filter(cell => cell.visible)
}
function cardMeta(row: any) {
  const code = row.supplier_product_name ? row.supplier_product_code : ''
  return [code, row.color_name, row.category_name, row.partner_name].filter(Boolean).join(' · ')
}
function swatch(row: any) {
  return String(row?.supplier_product_name || row?.supplier_product_code || row?.color_name || '料').trim().slice(0, 1)
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
function pageOrigin() {
  // 确认码指向站点上的领料确认页，另一台手机扫码后按路径打开。
  // #ifdef H5
  if (typeof location !== 'undefined' && location.origin) return location.origin
  // #endif
  return String(import.meta.env.VITE_H5_BASE_URL || '').replace(/\/$/, '')
}
function optionName(list: any[], id: number | null) {
  return list.find(item => item.id === id)?.name || ''
}
function sizeName(id: number | null) {
  return activeSizes.value.find(item => item.id === id)?.size_value || ''
}
function ledgerTime(value?: string) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '—'
}
function clearPicked() {
  for (const key of Object.keys(picked)) delete picked[key]
}
function linesForAction(row: any) {
  const parts = partRows(row)
  if (selectMode.value === 'dev_return' || selectMode.value === 'aux_return') return parts
  if (selectMode.value === 'dev' || selectMode.value === 'aux') return parts.filter(part => Number(part.pool_qty ?? part.qty) > 0)
  return parts.filter(part => Number(part.returnable_qty) > 0)
}
function canSelect(row: any) {
  if (selectMode.value === 'dev_return' || selectMode.value === 'aux_return') return true
  return linesForAction(row).length > 0
}
function isZero(value: any) {
  const number = Number(value)
  return !Number.isNaN(number) && number === 0
}
function deletableParts(row: any) {
  return partRows(row).filter(part => part?.id && isZero(onHandQty(part)) && isZero(part.in_transit_qty) && isZero(part.actual_demand_qty))
}
function onKeyword(event: any) {
  keyword.value = inputValue(event)
}
function setCategory(id: number | null) {
  categoryId.value = id
}
function onCard(row: any) {
  if (selectMode.value) {
    if (!canSelect(row)) {
      toast(selectMode.value === 'return' ? '这件物料没有可退数量' : '这件物料没有可领数量')
      return
    }
    if (selectMode.value === 'return' && !picked[row.pool_row_key]) {
      const other = selectedRows.value.find(item => item.partner_id !== row.partner_id)
      if (other) {
        toast('一次只能退同一个供应商')
        return
      }
    }
    if (picked[row.pool_row_key]) delete picked[row.pool_row_key]
    else picked[row.pool_row_key] = true
    return
  }
  current.value = row
  mode.value = 'detail'
}
function startSelect(next: SelectKind) {
  closeSheet()
  selectMode.value = next
  clearPicked()
  if ((next === 'aux' || next === 'aux_return') && categoryId.value != null && !auxiliaryIds.value.has(Number(categoryId.value))) categoryId.value = null
  mode.value = 'list'
}
function cancelSelect() {
  selectMode.value = null
  clearPicked()
}
function openActions() {
  if (!canWrite.value) {
    void openHistoryList()
    return
  }
  sheet.value = 'actions'
  sheetQuery.value = ''
}
function closeSheet() {
  sheet.value = ''
  sheetQuery.value = ''
}
function openSheet(next: SheetKind) {
  sheet.value = next
  sheetQuery.value = ''
  suggestOpen.value = false
}
function pickSheet(id: number | null) {
  if (sheet.value === 'category') inbound.category_id = id
  else if (sheet.value === 'color') inbound.color_id = id
  else if (sheet.value === 'size') inbound.size_id = id
  else if (sheet.value === 'unit') inbound.pricing_unit_id = id
  closeSheet()
}
function pickSupplier(name: string) {
  inbound.supplier_name = name
  suggestOpen.value = false
}
function hideSuggestions() {
  setTimeout(() => { suggestOpen.value = false }, 200)
}
function onInbound(key: 'product_code' | 'name' | 'unit_price' | 'supplier_name' | 'qty', event: any) {
  inbound[key] = inputValue(event)
  if (key === 'supplier_name') suggestOpen.value = true
}

async function loadMasters() {
  const [categoryRes, sizeRes] = await Promise.all([
    get<any>('/material-categories'),
    get<any>('/sizes'),
  ])
  categories.value = asItems(categoryRes)
  sizes.value = asItems(sizeRes)
}
async function load(silent = false) {
  if (!canSee.value) return
  if (!silent) loading.value = true
  try {
    const result = await get<any[]>('/shared-materials')
    rows.value = (result || []).map(row => ({ ...row, pool_row_key: `${row.supplier_product_id}:${row.size_id ?? ''}` }))
    clearPicked()
    if (current.value) {
      const next = groupMaterialRows(rows.value).find(row => row.supplier_product_id === current.value.supplier_product_id)
      if (next) current.value = next
    }
    loaded = true
  } catch (error: any) {
    toast(error?.message || '物料仓加载失败')
  } finally {
    loading.value = false
    uni.stopPullDownRefresh()
  }
}

async function openLedger() {
  if (!current.value) return
  mode.value = 'ledger'
  ledgerLoading.value = true
  ledgerCount.value = 30
  ledgers.value = []
  try {
    ledgers.value = await get<any[]>('/shared-materials/ledgers', { supplier_product_id: current.value.supplier_product_id, limit: 500 })
  } catch (error: any) {
    toast(error?.message || '流水加载失败')
  } finally {
    ledgerLoading.value = false
  }
}
function openCount() {
  countParts.value = partRows(current.value).map(part => ({
    key: part.pool_row_key || `${part.supplier_product_id}:${part.size_id ?? ''}`,
    supplier_product_id: part.supplier_product_id,
    size_id: part.size_id ?? null,
    size_value: part.size_value || '',
    on_hand_qty: onHandQty(part),
    actual_qty: '',
  }))
  mode.value = 'count'
}
function onCountQty(part: any, event: any) {
  part.actual_qty = inputValue(event)
}
async function submitCount() {
  const filled = countParts.value.filter(part => part.actual_qty !== '' && !Number.isNaN(Number(part.actual_qty)))
  if (!filled.length) {
    toast('请填写实际现存量')
    return
  }
  saving.value = true
  try {
    for (const part of filled) {
      await post('/shared-materials/adjust', {
        supplier_product_id: part.supplier_product_id,
        size_id: part.size_id || null,
        on_hand_qty: Number(part.actual_qty),
      })
    }
    toast('已盘点')
    mode.value = 'detail'
    await load(true)
  } catch (error: any) {
    toast(error?.message || '盘点失败')
  } finally {
    saving.value = false
  }
}
function removeCurrent() {
  const parts = deletableParts(current.value)
  const name = [current.value?.supplier_product_code, current.value?.supplier_product_name].filter(Boolean).join(' ')
  uni.showModal({
    title: '删除物料仓记录',
    content: parts.length < partRows(current.value).length ? `只删除 ${name} 里现存、在途、生产需求都为 0 的码。` : `确定删除 ${name || '这条物料'}？现存、在途、生产需求都是 0。`,
    success: async result => {
      if (!result.confirm) return
      try {
        for (const part of parts) await del(`/shared-materials/${part.id}`)
        toast('已删除')
        current.value = null
        mode.value = 'list'
        await load(true)
      } catch (error: any) {
        toast(error?.message || '删除失败')
      }
    },
  })
}

async function ensureInboundMasters() {
  if (colors.value.length || units.value.length || supplierNames.value.length) return
  const [colorRes, unitRes, partnerRes] = await Promise.all([
    get<any>('/colors'),
    get<any>('/pricing-units'),
    get<any>('/partners', { role: 'supplier', active_only: true, page: 1, page_size: 500 }),
  ])
  colors.value = asItems(colorRes).filter(item => item.is_active !== false)
  units.value = asItems(unitRes).filter(item => item.is_active !== false)
  supplierNames.value = asItems(partnerRes).map(item => String(item.name || '').trim()).filter(Boolean)
}
async function openInbound() {
  inbound.image_url = ''
  inbound.product_code = ''
  inbound.name = ''
  inbound.category_id = null
  inbound.color_id = null
  inbound.size_id = null
  inbound.unit_price = ''
  inbound.pricing_unit_id = null
  inbound.supplier_name = ''
  inbound.qty = ''
  suggestOpen.value = false
  mode.value = 'inbound'
  try { await ensureInboundMasters() } catch { /* 下拉失败仍可手填编号和供应商 */ }
}
function choosePhoto(source: 'camera' | 'album') {
  if (uploading.value) return
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: [source],
    success: async result => {
      const filePath = result.tempFilePaths?.[0]
      if (!filePath) return
      uploading.value = true
      try {
        const uploaded: any = await uploadFile('/supplier-products/upload', filePath)
        inbound.image_url = uploaded?.url || ''
      } catch (error: any) {
        toast(error?.message || '图片上传失败')
      } finally {
        uploading.value = false
      }
    },
  })
}
async function submitInbound() {
  const qty = Number(inbound.qty)
  if (!inbound.product_code.trim()) return toast('请填写物料编号')
  if (!inbound.name.trim()) return toast('请填写名称')
  if (!inbound.supplier_name.trim()) return toast('请填写供应商')
  if (!qty || qty <= 0) return toast('入库数量须大于 0')
  saving.value = true
  try {
    await post('/shared-materials/manual-receive', {
      product_code: inbound.product_code.trim(),
      name: inbound.name.trim(),
      supplier_name: inbound.supplier_name.trim(),
      qty,
      category_id: inbound.category_id,
      color_id: inbound.color_id,
      size_id: inbound.size_id,
      unit_price: inbound.unit_price === '' ? null : Number(inbound.unit_price),
      pricing_unit_id: inbound.pricing_unit_id,
      image_url: inbound.image_url || null,
    })
    toast('已入库，并同步到物料色卡')
    mode.value = 'list'
    await load(true)
  } catch (error: any) {
    toast(error?.message || '入库失败')
  } finally {
    saving.value = false
  }
}

function poolLine(part: any, cap: number, capLabel: string) {
  return {
    key: `${part.supplier_product_id}:${part.size_id ?? ''}`,
    supplier_product_id: part.supplier_product_id,
    size_id: part.size_id ?? null,
    name: part.supplier_product_name || part.item_name || part.supplier_product_code,
    code: part.supplier_product_code || part.item_code || '',
    size_value: part.size_value || '',
    unit_name: part.pricing_unit_name || part.unit_name || '',
    cap,
    capLabel,
    qty: cap > 0 ? String(Math.floor(cap * 100 + 1e-6) / 100) : '',
    unit_price: '',
  }
}
async function confirmSelect() {
  const parts = selectedRows.value.flatMap(row => linesForAction(row))
  if (!parts.length) return toast('请先勾选物料')
  saving.value = true
  try {
    if (selectMode.value === 'return') {
      const quoted: any = await post('/shared-materials/purchase-return-quote', {
        lines: parts.map(part => ({ supplier_product_id: part.supplier_product_id, size_id: part.size_id ?? null })),
      })
      returnTitle.value = quoted?.supplier_name ? `退货 · ${quoted.supplier_name}` : '退货'
      returnNote.value = ''
      qtyKind.value = 'purchase'
      qtyLines.value = (quoted?.lines || []).map((line: any) => ({
        ...poolLine(line, Number(line.returnable_qty || 0), '可退'),
        name: line.item_name || line.item_code,
        code: line.item_code || '',
        unit_price: String(Math.round(Number(line.unit_price || 0) * 100) / 100),
      }))
    } else if (selectMode.value === 'dev_return' || selectMode.value === 'aux_return') {
      const quoted: any = await post('/warehouse-pickups/returnable', {
        kind: selectMode.value,
        lines: parts.map(part => ({ supplier_product_id: part.supplier_product_id, size_id: part.size_id ?? null })),
      })
      const caps = new Map<string, number>()
      for (const line of quoted?.lines || []) caps.set(`${line.supplier_product_id}:${line.size_id ?? ''}`, Number(line.returnable_qty || 0))
      if (parts.length && [...caps.values()].every(qty => qty <= 0)) toast('这些物料没有可退数量')
      slipKind.value = selectMode.value
      qtyKind.value = 'pickup'
      qtyLines.value = parts.map(part => poolLine(part, caps.get(`${part.supplier_product_id}:${part.size_id ?? ''}`) ?? 0, '可退'))
    } else {
      slipKind.value = selectMode.value === 'aux' ? 'aux' : 'dev'
      qtyKind.value = 'pickup'
      qtyLines.value = parts.map(part => poolLine(part, Number(part.pool_qty ?? part.qty ?? 0), '可用'))
    }
    mode.value = 'qty'
  } catch (error: any) {
    toast(error?.message || '无法继续')
  } finally {
    saving.value = false
  }
}
function onLineQty(line: any, key: 'qty' | 'unit_price', event: any) {
  line[key] = inputValue(event)
}
function removeQtyLine(key: string) {
  qtyLines.value = qtyLines.value.filter(line => line.key !== key)
}
function returnAmount(line: any) {
  const amount = -(Number(line.qty) || 0) * Number(line.unit_price || 0)
  return amount.toFixed(2)
}
async function submitQty() {
  if (qtyKind.value === 'purchase') {
    if (qtyLines.value.some(line => !Number(line.qty) || Number(line.qty) <= 0 || Number(line.qty) > Number(line.cap))) return toast('退货数量须大于 0，且不能超过可退数量')
    if (qtyLines.value.some(line => line.unit_price === '' || Number(line.unit_price) < 0)) return toast('单价不能为负')
    saving.value = true
    try {
      await post('/shared-materials/purchase-returns', {
        note: returnNote.value.trim() || null,
        lines: qtyLines.value.map(line => ({
          supplier_product_id: line.supplier_product_id,
          size_id: line.size_id || null,
          qty: Number(line.qty),
          unit_price: Number(line.unit_price),
        })),
      })
      toast('已退货')
      cancelSelect()
      mode.value = 'list'
      await load(true)
    } catch (error: any) {
      toast(error?.message || '退货失败')
    } finally {
      saving.value = false
    }
    return
  }
  const lines = qtyLines.value.filter(line => Number(line.qty) > 0)
  if (!lines.length) return toast('请至少填写一种物料的数量')
  if (lines.some(line => Number(line.qty) > Number(line.cap))) return toast(slipKind.value.endsWith('_return') ? '数量不能超过可退' : '数量不能超过可用库存')
  await issueSlip(lines.map(line => ({ supplier_product_id: line.supplier_product_id, size_id: line.size_id || undefined, qty: Number(line.qty) })))
}

function startProduction(next: 'production' | 'production_return') {
  closeSheet()
  slipKind.value = next
  headerQuery.value = ''
  headerOptions.value = []
  productionHeader.value = null
  productionLines.value = []
  mode.value = 'production'
  void searchHeaders('')
}
function onHeaderQuery(event: any) {
  headerQuery.value = inputValue(event)
  clearTimeout(headerTimer)
  headerTimer = setTimeout(() => void searchHeaders(headerQuery.value), 250) as unknown as number
}
function headerMeta(row: any) {
  return [row.product_code, row.color_name, `${row.total_qty ?? 0} 双`].filter(Boolean).join(' · ')
}
async function searchHeaders(text: string) {
  searching.value = true
  try {
    const result: any = await get('/warehouse-pickups/production-options', { q: text.trim() })
    headerOptions.value = result?.items || []
  } catch {
    headerOptions.value = []
  } finally {
    searching.value = false
  }
}
function clearHeader() {
  productionHeader.value = null
  productionLines.value = []
}
async function chooseHeader(row: any) {
  productionHeader.value = { header_no: row.header_no, total_qty: row.total_qty }
  await loadProduction(row.header_no)
}
async function loadProduction(headerNo: string) {
  previewing.value = true
  productionLines.value = []
  try {
    const data: any = await get('/warehouse-pickups/production', { header_no: headerNo })
    if (data?.ambiguous) {
      productionHeader.value = null
      headerOptions.value = data.matches || []
      toast('有多张生产单，请点选一张')
      return
    }
    productionHeader.value = data
    productionLines.value = (data?.lines || []).map((line: any) => ({
      ...line,
      qty: '',
      parts: Array.isArray(line.parts) ? line.parts.map((part: any) => ({ ...part, qty: '' })) : line.parts,
    }))
  } catch (error: any) {
    productionHeader.value = null
    toast(error?.message || '生产单读取失败')
  } finally {
    previewing.value = false
  }
}
function sizeParts(line: any): any[] {
  return Array.isArray(line?.parts) && line.parts.length > 1 ? line.parts : [line]
}
function onPartQty(part: any, event: any) {
  part.qty = inputValue(event)
}
function partHints(part: any) {
  if (slipKind.value.endsWith('_return')) return [`可退 ${formatNum(part.returnable_qty)}`]
  return [`需求 ${formatNum(part.required_qty)}`, `现存 ${formatNum(part.max_issue_qty)}`]
}
function partCaption(part: any) {
  if (slipKind.value.endsWith('_return')) return `可退 ${formatNum(part.returnable_qty)}`
  return `需求 ${formatNum(part.required_qty)} · 现存 ${formatNum(part.max_issue_qty)}`
}
function partWarn(part: any) {
  const qty = Number(part?.qty)
  if (!qty || qty <= 0) return ''
  if (slipKind.value.endsWith('_return')) return qty > Number(part.returnable_qty || 0) ? `超过可退 ${formatNum(part.returnable_qty)}` : ''
  return qty > Number(part.max_issue_qty || 0) ? `超过现存 ${formatNum(part.max_issue_qty)}` : ''
}
async function submitProduction() {
  if (productionLines.value.some(line => sizeParts(line).some((part: any) => partWarn(part)))) return toast('数量超过可领或可退')
  const lines: { requirement_id: number; qty: number }[] = []
  for (const line of productionLines.value) {
    for (const part of sizeParts(line)) {
      if (Number(part.qty) > 0) lines.push({ requirement_id: part.requirement_id, qty: Number(part.qty) })
    }
  }
  if (!lines.length) return toast('请至少填写一种物料的数量')
  await issueSlip(lines, productionHeader.value?.header_no)
}
async function issueSlip(lines: any[], headerNo?: string) {
  const origin = pageOrigin()
  if (!origin) return toast('无法生成确认二维码，请配置站点地址')
  saving.value = true
  try {
    slip.value = await post('/warehouse-pickups', {
      kind: slipKind.value,
      header_no: headerNo,
      origin,
      lines,
    })
    cancelSelect()
    mode.value = 'sign'
    startPoll(Number(slip.value?.id))
  } catch (error: any) {
    toast(error?.message || '开单失败')
  } finally {
    saving.value = false
  }
}
function stopPoll() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = 0
}
function startPoll(id: number) {
  stopPoll()
  if (!id) return
  pollTimer = setInterval(() => void pollSigned(id), 2000) as unknown as number
}
async function pollSigned(id: number) {
  try {
    const data: any = await get(`/warehouse-pickups/${id}`)
    if (data?.status === 'signed') {
      stopPoll()
      slip.value = { ...slip.value, ...data }
      await load(true)
    } else if (data?.status === 'cancelled') {
      stopPoll()
      slip.value = null
      mode.value = 'list'
    }
  } catch { /* 下一轮再试 */ }
}
async function abandon(id: number) {
  if (!id) return
  try { await post(`/warehouse-pickups/${id}/cancel`, {}) } catch { /* 已确认或已作废 */ }
}
async function finishSign() {
  stopPoll()
  slip.value = null
  mode.value = 'list'
  await load(true)
}
async function openHistoryList() {
  closeSheet()
  mode.value = 'history'
  historyLoading.value = true
  try {
    const result: any = await get('/warehouse-pickups', { page: 1, page_size: 50, status: 'signed' })
    history.value = result?.items || []
  } catch (error: any) {
    toast(error?.message || '记录加载失败')
  } finally {
    historyLoading.value = false
  }
}
async function openHistory(row: any) {
  try {
    historyDetail.value = await get(`/warehouse-pickups/${row.id}`)
    mode.value = 'historyDetail'
  } catch (error: any) {
    toast(error?.message || '单据加载失败')
  }
}

async function goBack() {
  if (sheet.value) {
    closeSheet()
    return
  }
  if (mode.value === 'sign') {
    stopPoll()
    const pendingId = slip.value?.status === 'pending' ? Number(slip.value.id) : 0
    slip.value = null
    mode.value = 'list'
    if (pendingId) await abandon(pendingId)
    return
  }
  if (mode.value === 'list' && selectMode.value) {
    cancelSelect()
    return
  }
  if (mode.value === 'qty') {
    mode.value = 'list'
    return
  }
  if (mode.value === 'ledger' || mode.value === 'count') {
    mode.value = 'detail'
    return
  }
  if (mode.value === 'historyDetail') {
    mode.value = 'history'
    return
  }
  if (mode.value !== 'list') mode.value = 'list'
}

onBackPress(() => {
  if (sheet.value || selectMode.value || mode.value !== 'list') {
    void goBack()
    return true
  }
  return false
})
onReachBottom(() => {
  if (mode.value === 'list') visibleCount.value += 20
  else if (mode.value === 'ledger') ledgerCount.value += 30
})
onPullDownRefresh(() => {
  if (mode.value === 'list') void load()
  else uni.stopPullDownRefresh()
})
onShow(async () => {
  profile.value = getProfile()
  if (!canSee.value || loaded) return
  try { await loadMasters() } catch (error: any) { toast(error?.message || '分类加载失败') }
  await load()
})
onUnload(() => {
  stopPoll()
  clearTimeout(headerTimer)
  const pendingId = mode.value === 'sign' && slip.value?.status === 'pending' ? Number(slip.value.id) : 0
  if (pendingId) void abandon(pendingId)
})
</script>

<style scoped lang="scss">
.h5-wh-search,
.h5-wh-card,
.h5-wh-hero,
.h5-wh-facts,
.h5-wh-block,
.h5-wh-ledger,
.h5-wh-qty,
.h5-wh-form,
.h5-wh-order,
.h5-wh-sign,
.h5-wh-history { margin-bottom: 16rpx; }
.h5-wh-search { display: flex; align-items: center; gap: 16rpx; padding: 8rpx 8rpx 8rpx 24rpx; }
.h5-wh-search input,
.h5-wh-field input,
.h5-wh-qty__row input,
.h5-wh-size-edit input,
.h5-wh-sheet__search { min-width: 0; height: 72rpx; color: #181b23; font-size: 28rpx; }
.h5-wh-search input { flex: 1; }
.h5-wh-search > text,
.h5-wh-back,
.h5-wh-sheet__head text:last-child { color: #0057c2; font-size: 26rpx; font-weight: 700; }
.h5-wh-back { display: block; margin: 4rpx 0 16rpx; font-size: 28rpx; }
.h5-wh-cats { width: 100%; margin: 8rpx 0 12rpx; white-space: nowrap; }
.h5-wh-cats text,
.h5-wh-filters text { display: inline-flex; align-items: center; height: 56rpx; margin: 0 12rpx 8rpx 0; padding: 0 20rpx; border-radius: 999rpx; background: #fff; color: #414755; font-size: 24rpx; }
.h5-wh-cats text.on,
.h5-wh-filters text.on { background: rgba(0, 87, 194, 0.12); color: #0057c2; font-weight: 700; }
.h5-wh-filters { display: flex; margin-bottom: 8rpx; }
.h5-wh-hint,
.h5-wh-note,
.h5-wh-empty,
.h5-wh-more { display: block; color: #414755; font-size: 24rpx; }
.h5-wh-hint,
.h5-wh-note { margin: 0 4rpx 16rpx; line-height: 1.5; }
.h5-wh-more,
.h5-wh-empty { padding: 12rpx 0 20rpx; text-align: center; }
.h5-wh-card { display: flex; flex-direction: column; gap: 12rpx; padding: 18rpx; }
.h5-wh-card__main { display: flex; gap: 16rpx; align-items: flex-start; min-width: 0; }
.h5-wh-card.is-picked { box-shadow: inset 0 0 0 2rpx #0057c2; }
.h5-wh-card.is-locked { opacity: 0.45; }
.h5-wh-check { width: 32rpx; height: 32rpx; margin-top: 40rpx; border: 2rpx solid #c1c6d7; border-radius: 50%; }
.h5-wh-check.on { border-color: #0057c2; background: #0057c2; box-shadow: inset 0 0 0 6rpx #fff; }
.h5-wh-thumb { display: flex; flex: 0 0 112rpx; align-items: center; justify-content: center; width: 112rpx; height: 112rpx; border-radius: 20rpx; background: #f5f7fa; color: #414755; font-size: 36rpx; font-weight: 750; }
.h5-wh-card__body { flex: 1; min-width: 0; }
.h5-wh-card__title { display: flex; flex: 1; align-items: baseline; gap: 10rpx; min-width: 0; }
.h5-wh-card__title strong { flex: 0 1 auto; max-width: 68%; min-width: 0; }
.h5-wh-card__title text { flex: 1; min-width: 0; overflow: hidden; color: #727786; font-size: 22rpx; text-overflow: ellipsis; white-space: nowrap; }
.h5-wh-card__top,
.h5-wh-fact,
.h5-wh-field,
.h5-wh-line,
.h5-wh-ledger__top,
.h5-wh-qty__head,
.h5-wh-qty__row,
.h5-wh-size-line { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; }
.h5-wh-card__top strong,
.h5-wh-hero__copy strong,
.h5-wh-qty__head strong,
.h5-wh-order strong { overflow: hidden; color: #181b23; font-size: 30rpx; text-overflow: ellipsis; white-space: nowrap; }
.h5-wh-meta,
.h5-wh-qty__head text,
.h5-wh-order text,
.h5-wh-line text,
.h5-wh-ledger__type { color: #414755; font-size: 22rpx; }
.h5-wh-meta { display: block; margin-top: 6rpx; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.h5-wh-peek { display: block; margin-top: 8rpx; color: #0057c2; font-size: 22rpx; font-weight: 700; }
.h5-wh-metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8rpx; margin-top: 12rpx; }
.h5-wh-metrics text { display: block; color: #727786; font-size: 20rpx; }
.h5-wh-metrics strong { display: block; margin-top: 2rpx; color: #181b23; font-size: 26rpx; font-variant-numeric: tabular-nums; }
.h5-wh-metrics strong.warn,
.h5-wh-amount { color: #7d5400; }
.h5-wh-metrics strong.short,
.h5-wh-fact strong.short,
.short,
.h5-wh-over,
.danger { color: #ba1a1a; }
.h5-wh-short { flex-shrink: 0; padding: 4rpx 12rpx; border-radius: 999rpx; background: rgba(186, 26, 26, 0.1); color: #ba1a1a; font-size: 20rpx; font-weight: 700; }
.h5-wh-run { width: 100%; height: 132rpx; white-space: nowrap; }
.h5-wh-run__track { display: inline-flex; gap: 8rpx; height: 132rpx; }
.h5-wh-run__track--wrap { display: flex; flex-wrap: wrap; width: 100%; height: auto; margin-top: 12rpx; white-space: normal; }
.h5-wh-run__cell { display: inline-flex; flex: 0 0 104rpx; flex-direction: column; align-items: center; justify-content: center; box-sizing: border-box; width: 104rpx; min-height: 120rpx; padding: 8rpx 6rpx; border-radius: 16rpx; background: #f5f7fa; }
.h5-wh-run__track--wrap .h5-wh-run__cell { flex-basis: auto; width: auto; min-width: 104rpx; }
.h5-wh-run__cell text,
.h5-wh-board__col text,
.h5-wh-board__labs text { display: flex; align-items: center; justify-content: center; margin: 0; color: #727786; font-size: 20rpx; line-height: 1.2; white-space: nowrap; }
.h5-wh-run__cell strong { display: block; margin: 4rpx 0; color: #181b23; font-size: 26rpx; font-weight: 750; font-variant-numeric: tabular-nums; line-height: 1.2; }
.h5-wh-run__plus { min-height: 24rpx; color: #7d5400; font-size: 18rpx; font-weight: 650; }
.h5-wh-run__track--wrap .h5-wh-run__plus { white-space: normal; text-align: center; }
.h5-wh-run__cell.short,
.h5-wh-board__col.short,
.h5-wh-count__cell.short { background: rgba(186, 26, 26, 0.1); }
.h5-wh-run__cell.short strong { color: #ba1a1a; }
.h5-wh-line { flex-direction: column; align-items: stretch; }
.h5-wh-line__head { display: flex; align-items: center; justify-content: space-between; width: 100%; }
.h5-wh-board { display: flex; align-items: stretch; margin-top: 8rpx; }
.h5-wh-board__labs { display: flex; flex: 0 0 72rpx; flex-direction: column; }
.h5-wh-board__labs text { justify-content: flex-start; height: 52rpx; }
.h5-wh-board__scroll { flex: 1; width: 0; height: 260rpx; white-space: nowrap; }
.h5-wh-board__cols { display: inline-flex; height: 260rpx; }
.h5-wh-board__col { display: inline-flex; flex-direction: column; align-items: center; width: 96rpx; border-radius: 16rpx; }
.h5-wh-board__col text,
.h5-wh-board__col strong { height: 52rpx; color: #181b23; font-size: 24rpx; font-variant-numeric: tabular-nums; }
.h5-wh-board__col strong { font-size: 26rpx; font-weight: 750; }
.h5-wh-board__col text.warn { color: #7d5400; }
.h5-wh-board__col text.short,
.h5-wh-board__col strong.short { color: #ba1a1a; font-weight: 750; }
.h5-wh-count { display: flex; flex-wrap: wrap; gap: 12rpx; padding: 16rpx 0 8rpx; }
.h5-wh-count__cell { display: flex; flex-direction: column; box-sizing: border-box; width: calc((100% - 24rpx) / 3); min-width: 0; padding: 12rpx; border-radius: 16rpx; background: #f5f7fa; }
.h5-wh-count--price .h5-wh-count__cell { width: calc((100% - 12rpx) / 2); }
.h5-wh-count__cell > text,
.h5-wh-count__top > text:first-child { color: #181b23; font-size: 26rpx; font-weight: 750; }
.h5-wh-count__sub,
.h5-wh-count__top .danger { margin-top: 4rpx; color: #727786; font-size: 20rpx; font-weight: 500; line-height: 1.3; }
.h5-wh-count__top { display: flex; align-items: center; justify-content: space-between; gap: 8rpx; }
.h5-wh-count__top .danger { margin-top: 0; color: #ba1a1a; font-size: 22rpx; font-weight: 700; }
.h5-wh-count input { width: 100%; height: 64rpx; margin-top: 8rpx; border-radius: 12rpx; background: #fff; color: #181b23; font-size: 28rpx; text-align: center; }
.h5-wh-hero { display: flex; gap: 20rpx; padding: 20rpx; }
.h5-wh-hero image,
.h5-wh-hero__empty { width: 160rpx; height: 160rpx; border-radius: 24rpx; background: #f5f7fa; }
.h5-wh-hero__empty { display: flex; align-items: center; justify-content: center; color: #414755; font-size: 48rpx; font-weight: 750; }
.h5-wh-hero__copy { display: flex; flex: 1; flex-direction: column; align-items: flex-start; gap: 10rpx; min-width: 0; }
.h5-wh-facts,
.h5-wh-block,
.h5-wh-form,
.h5-wh-qty,
.h5-wh-ledger,
.h5-wh-history,
.h5-wh-sign { padding: 8rpx 24rpx 16rpx; }
.h5-wh-fact,
.h5-wh-field { min-height: 84rpx; border-bottom: 1rpx solid #e0e2ed; }
.h5-wh-fact:last-child,
.h5-wh-field:last-of-type { border-bottom: 0; }
.h5-wh-fact text,
.h5-wh-field > text:first-child,
.h5-wh-qty__row > text:first-child { flex: 0 0 140rpx; color: #414755; font-size: 26rpx; }
.h5-wh-fact strong,
.h5-wh-field strong,
.h5-wh-field input { flex: 1; color: #181b23; font-size: 28rpx; font-weight: 650; text-align: right; }
.h5-wh-fact strong.warn { color: #7d5400; }
.h5-wh-fact strong.short { color: #ba1a1a; }
.h5-wh-field strong.need,
.h5-wh-chev { color: #727786; font-weight: 500; }
.h5-wh-block__title { display: block; padding-top: 16rpx; color: #181b23; font-size: 28rpx; font-weight: 750; }
.h5-wh-line,
.h5-wh-size-line { padding: 14rpx 0; border-top: 1rpx solid #e0e2ed; }
.h5-wh-line strong,
.h5-wh-size-line strong { color: #181b23; font-size: 28rpx; }
.h5-wh-line .h5-wh-run__cell text { display: flex; margin-top: 0; line-height: 1.2; }
.h5-wh-line .h5-wh-run__cell strong { font-size: 26rpx; }
.h5-wh-count__cell .h5-wh-over { display: block; margin-top: 6rpx; color: #ba1a1a; font-size: 20rpx; line-height: 1.3; }
.h5-wh-ledger { padding-top: 18rpx; }
.h5-wh-ledger__top strong.in { color: #266d00; }
.h5-wh-ledger__top strong.out { color: #ba1a1a; }
.h5-wh-ledger__type { display: block; margin-top: 8rpx; }
.h5-wh-photo { position: relative; height: 220rpx; margin: 16rpx 0 0; overflow: hidden; border-radius: 24rpx; background: #f5f7fa; }
.h5-wh-photo image { width: 100%; height: 220rpx; }
.h5-wh-photo__clear { position: absolute; top: 12rpx; right: 12rpx; padding: 8rpx 16rpx; border-radius: 999rpx; background: rgba(255, 255, 255, 0.92); color: #ba1a1a; font-size: 24rpx; }
.h5-wh-photo-actions { display: flex; gap: 12rpx; margin: 16rpx 0 8rpx; }
.h5-wh-photo-actions button { flex: 1; height: 80rpx; margin: 0; border: 0; border-radius: 16rpx; background: #f5f7fa; color: #181b23; font-size: 28rpx; font-weight: 700; line-height: 80rpx; }
.h5-wh-photo-actions button::after,
.h5-wh-ghost::after,
.h5-wh-primary::after { border: 0; }
.h5-wh-suggest text { display: block; padding: 16rpx 0; border-bottom: 1rpx solid #e0e2ed; color: #181b23; font-size: 28rpx; }
.h5-wh-qty__head { align-items: flex-start; padding-top: 12rpx; }
.h5-wh-qty__head view { min-width: 0; }
.h5-wh-qty__head text,
.h5-wh-prod text { display: block; margin-top: 4rpx; }
.h5-wh-qty__row { min-height: 76rpx; }
.h5-wh-qty__row input,
.h5-wh-size-edit input { flex: 1; padding: 0 16rpx; border-radius: 14rpx; background: #f5f7fa; text-align: right; }
.h5-wh-amount { flex: 0 0 auto; font-weight: 700; }
.h5-wh-prod { display: flex; gap: 12rpx; min-width: 0; }
.h5-wh-prod image { width: 72rpx; height: 72rpx; border-radius: 16rpx; background: #f5f7fa; }
.h5-wh-size-edit { padding: 12rpx 0; border-top: 1rpx solid #e0e2ed; }
.h5-wh-size-edit__meta { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 8rpx; }
.h5-wh-size-edit__meta text,
.h5-wh-over { color: #414755; font-size: 22rpx; }
.h5-wh-order { padding: 22rpx 24rpx; }
.h5-wh-order text { display: block; margin-top: 6rpx; }
.h5-wh-order--on { display: flex; align-items: center; justify-content: space-between; }
.h5-wh-sign { padding-top: 28rpx; text-align: center; }
.h5-wh-sign__kind,
.h5-wh-sign__ok { display: block; color: #414755; font-size: 24rpx; }
.h5-wh-sign strong { display: block; margin: 8rpx 0 16rpx; color: #181b23; font-size: 40rpx; }
.h5-wh-sign__ok { color: #266d00; font-size: 28rpx; font-weight: 700; }
.h5-wh-qr { width: 420rpx; height: 420rpx; margin: 12rpx auto; }
.h5-wh-sign-img { width: 100%; margin-top: 12rpx; }
.h5-wh-bar { display: flex; gap: 12rpx; }
.h5-wh-bar .h5-wh-ghost,
.h5-wh-bar .h5-wh-primary { flex: 1; width: auto; height: 84rpx; margin: 0; border: 0; border-radius: 16rpx; font-size: 28rpx; font-weight: 750; line-height: 84rpx; }
.h5-wh-ghost { background: #f5f7fa; color: #181b23; }
.h5-wh-ghost--danger { color: #ba1a1a; }
.h5-wh-primary { margin-top: 0; }
.h5-wh-primary[disabled] { background: #8eb6e8; color: rgba(255, 255, 255, 0.92); }
.h5-wh-mask { position: fixed; z-index: 80; inset: 0; background: rgba(24, 27, 35, 0.38); }
.h5-wh-sheet { position: absolute; right: 0; bottom: 0; left: 0; max-height: 78vh; padding: 8rpx 28rpx calc(24rpx + env(safe-area-inset-bottom)); border-radius: 28rpx 28rpx 0 0; background: #fff; }
.h5-wh-sheet__head { display: flex; align-items: center; justify-content: space-between; height: 80rpx; color: #181b23; font-size: 30rpx; font-weight: 750; }
.h5-wh-sheet__search { box-sizing: border-box; width: 100%; padding: 0 20rpx; border-radius: 16rpx; background: #f5f7fa; }
.h5-wh-sheet__list { max-height: 52vh; margin-top: 8rpx; }
.h5-wh-option,
.h5-wh-action { display: flex; align-items: center; justify-content: space-between; min-height: 88rpx; border-bottom: 1rpx solid #e0e2ed; }
.h5-wh-action { flex-direction: column; align-items: flex-start; justify-content: center; gap: 4rpx; }
.h5-wh-action strong,
.h5-wh-option text { color: #181b23; font-size: 30rpx; }
.h5-wh-action text { color: #727786; font-size: 22rpx; }
.h5-wh--sub { padding-bottom: calc(180rpx + env(safe-area-inset-bottom)); }
</style>
