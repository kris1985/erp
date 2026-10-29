<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">员工与部门</h1>
      </div>
    </header>

    <div class="admin-card emp-shell" :class="{ 'is-tree-collapsed': treeCollapsed }">
      <!-- 左：部门树；生产单位挂在当前选中部门下 -->
      <aside class="emp-tree-panel">
        <div v-if="!treeCollapsed" class="emp-tree-toolbar">
          <button
            type="button"
            class="emp-tree-collapse-btn"
            title="收起部门树"
            @click="toggleTreeCollapsed"
          >«</button>
        </div>
        <template v-if="!treeCollapsed">
          <div class="emp-tab-fill">
            <div class="emp-tree-body">
              <el-tree
                :key="deptTreeKey"
                ref="deptTreeRef"
                :indent="8"
                :data="treeData"
                node-key="id"
                :props="{ label: 'name', children: 'children' }"
                highlight-current
                :expand-on-click-node="false"
                default-expand-all
                :current-node-key="selectedKey"
                @node-click="onDeptClick"
              >
                <template #default="{ data, node }">
                  <div class="emp-tree-node">
                    <el-icon class="emp-tree-node__icon" :class="{ 'is-open': node.expanded }">
                      <component :is="node.expanded ? FolderOpened : Folder" />
                    </el-icon>
                    <span class="emp-tree-node__text" :title="deptTreeLabel(data)">
                      <span class="emp-tree-node__name">{{ data.name }}</span>
                      <span v-if="data.leader_name" class="emp-tree-node__leader">{{ data.leader_name }}</span>
                    </span>
                    <span v-if="data.employee_count" class="emp-tree-node__badge">{{ data.employee_count }}</span>
                    <span class="emp-tree-node__ops" @click.stop>
                      <el-dropdown
                        v-permission="'btn.workers.write'"
                        trigger="click"
                        @command="(cmd: string) => onDeptCommand(data, cmd)"
                      >
                        <button type="button" class="emp-more-button" aria-label="部门操作" @click.stop>···</button>
                        <template #dropdown>
                          <el-dropdown-menu>
                            <el-dropdown-item command="child">
                              {{ data.kind === 'root' ? '新增部门' : '新增子部门' }}
                            </el-dropdown-item>
                            <template v-if="data.kind === 'dept'">
                              <el-dropdown-item command="edit">编辑</el-dropdown-item>
                              <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                            </template>
                          </el-dropdown-menu>
                        </template>
                      </el-dropdown>
                    </span>
                  </div>
                </template>
              </el-tree>
            </div>
          </div>
        </template>
        <button
          v-else
          type="button"
          class="emp-tree-collapsed-rail"
          title="展开部门树"
          @click="toggleTreeCollapsed"
        >
          <span class="emp-tree-collapsed-rail__chev">»</span>
          <span class="emp-tree-collapsed-rail__text">部门</span>
        </button>
      </aside>

      <!-- 右：当前部门的生产单位（横条，不占左侧树高）+ 员工 / 详情 -->
      <section class="emp-list-panel">
        <div v-if="orgEnableTeams && typeof selectedDeptId === 'number'" class="emp-team-strip">
          <button
            type="button"
            class="emp-team-chip"
            :class="{ 'is-current': !selectedTeamId }"
            @click="clearTeamSelection"
          >员工</button>
          <template v-if="selectedDeptHasSegment">
            <button
              v-for="t in scopedTeams"
              :key="t.id"
              type="button"
              class="emp-team-chip"
              :class="{ 'is-current': selectedTeamId === t.id }"
              @click="onTeamClick(t)"
            >
              {{ t.name }}
              <span v-if="t.is_default" class="emp-team-chip__mark">默</span>
            </button>
            <el-tooltip :disabled="canCreateTeam" :content="teamCreateHint" placement="top">
              <span>
                <el-button
                  link
                  type="primary"
                  size="small"
                  :disabled="!canCreateTeam"
                  @click="openTeam()"
                >＋ {{ teamLabelText }}</el-button>
              </span>
            </el-tooltip>
          </template>
          <span v-else class="muted emp-team-strip__hint">未挂工序段，不能建{{ teamLabelText }}</span>
        </div>

        <!-- 班组详情 -->
        <div v-if="showTeamDetail" class="team-detail">
          <div class="team-detail-head">
            <h3>{{ selectedTeam.name }}</h3>
            <el-tag v-if="selectedTeam.is_default" type="warning">默认{{ teamLabelText }}</el-tag>
            <el-tag v-if="selectedTeam.segment_name" type="info">{{ selectedTeam.segment_name }}</el-tag>
          </div>
          <div class="team-detail-grid">
            <div class="team-detail-item"><span class="muted">{{ leaderLabelText }}</span><b>{{ selectedTeam.leader_name || '—' }}</b></div>
            <div class="team-detail-item"><span class="muted">所属部门</span><b>{{ selectedTeam.department_name || '—' }}</b></div>
            <div class="team-detail-item"><span class="muted">人数</span><b>{{ (selectedTeam.members || []).length }}</b></div>
            <div class="team-detail-item"><span class="muted">默认{{ teamLabelText }}</span><b>{{ selectedTeam.is_default ? '是' : '否' }}</b></div>
          </div>
          <div class="team-member-list">
            <div class="section-label">成员</div>
            <el-tag v-for="m in selectedTeam.members" :key="m.id" size="small" style="margin: 2px 4px 2px 0">
              {{ m.name }}
            </el-tag>
            <div v-if="!selectedTeam.members?.length" class="muted" style="font-size: 12px">暂无成员</div>
          </div>
          <div style="margin-top: 16px">
            <el-button v-permission="'btn.teams.write'" type="primary" size="small" @click="manageMembers(selectedTeam)">成员管理</el-button>
            <el-button v-permission="'btn.teams.write'" size="small" @click="editTeam(selectedTeam)">编辑{{ teamLabelText }}</el-button>
          </div>
        </div>
        <!-- 员工列表 -->
        <template v-else>
          <div class="admin-toolbar">
            <el-input
              v-model="filters.keyword"
              clearable
              placeholder="姓名 / 手机"
              style="width: 150px"
              @clear="search"
              @keyup.enter="search"
            />
            <el-select v-model="filters.process_id" clearable filterable placeholder="全部工序" style="width: 140px" @change="search">
              <el-option v-for="p in processOptions" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
            <el-checkbox v-model="showLeftEmployees" @change="search">显示离职人员</el-checkbox>
            <div class="spacer" />
            <el-button @click="search">查询</el-button>
            <el-button @click="resetFilters">重置</el-button>
            <el-button v-permission="'btn.workers.write'" type="primary" @click="openCreate">新增员工</el-button>
          </div>

          <div ref="tableHostRef">
            <el-table
              ref="tableRef"
              :data="rows"
              stripe
              border
              allow-drag-last-column
              :max-height="tableMaxHeight"
              @header-dragend="onHeaderDragend"
            >
              <el-table-column column-key="photo" label="照片" :width="colWidth('photo', 76)" align="center" resizable>
                <template #default="{ row }">
                  <div
                    class="emp-photo-cell"
                    :class="{ 'is-dragging': photoDragKey === photoCellKey(row.id, 'photo_url'), 'is-uploading': photoUploadingKey === photoCellKey(row.id, 'photo_url') }"
                    :title="row.photo_url ? '拖拽图片可更换' : '拖拽图片到这里，或点击上传，可不填'"
                    @dragenter.prevent="onPhotoCellDragEnter(row, 'photo_url')"
                    @dragover.prevent
                    @dragleave.prevent="onPhotoCellDragLeave(row, 'photo_url')"
                    @drop.prevent="onPhotoCellDrop($event, row, 'photo_url')"
                    @click="pickPhotoForRow(row, 'photo_url')"
                  >
                    <el-image
                      v-if="row.photo_url"
                      :src="row.photo_url"
                      :preview-src-list="[row.photo_url]"
                      fit="cover"
                      preview-teleported
                      class="emp-photo-thumb"
                      @click.stop
                    />
                    <span v-else>{{ photoUploadingKey === photoCellKey(row.id, 'photo_url') ? '…' : '拖入' }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="name" label="姓名" :width="colWidth('name', 90)" resizable />
              <el-table-column prop="mobile" label="手机" :width="colWidth('mobile', 120)" resizable />
              <el-table-column prop="identity_card_no" label="身份证号" :width="colWidth('identity_card_no', 180)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ row.identity_card_no || '—' }}</template>
              </el-table-column>
              <el-table-column column-key="id_card_photo" label="身份证照" :width="colWidth('id_card_photo', 168)" align="center" resizable>
                <template #default="{ row }">
                  <div class="emp-id-photo-pair">
                    <div
                      class="emp-photo-cell emp-photo-cell--id"
                      :class="{ 'is-dragging': photoDragKey === photoCellKey(row.id, 'id_card_front_url'), 'is-uploading': photoUploadingKey === photoCellKey(row.id, 'id_card_front_url') }"
                      :title="row.id_card_front_url ? '拖拽可更换人像面' : '拖入或点击上传人像面，可不填'"
                      @dragenter.prevent="onPhotoCellDragEnter(row, 'id_card_front_url')"
                      @dragover.prevent
                      @dragleave.prevent="onPhotoCellDragLeave(row, 'id_card_front_url')"
                      @drop.prevent="onPhotoCellDrop($event, row, 'id_card_front_url')"
                      @click="pickPhotoForRow(row, 'id_card_front_url')"
                    >
                      <el-image
                        v-if="row.id_card_front_url"
                        :src="row.id_card_front_url"
                        :preview-src-list="idCardPreviewList(row)"
                        :initial-index="0"
                        fit="cover"
                        preview-teleported
                        class="emp-id-photo-thumb"
                        @click.stop
                      />
                      <span v-else>{{ photoUploadingKey === photoCellKey(row.id, 'id_card_front_url') ? '…' : '正面' }}</span>
                    </div>
                    <div
                      class="emp-photo-cell emp-photo-cell--id"
                      :class="{ 'is-dragging': photoDragKey === photoCellKey(row.id, 'id_card_back_url'), 'is-uploading': photoUploadingKey === photoCellKey(row.id, 'id_card_back_url') }"
                      :title="row.id_card_back_url ? '拖拽可更换国徽面' : '拖入或点击上传国徽面，可不填'"
                      @dragenter.prevent="onPhotoCellDragEnter(row, 'id_card_back_url')"
                      @dragover.prevent
                      @dragleave.prevent="onPhotoCellDragLeave(row, 'id_card_back_url')"
                      @drop.prevent="onPhotoCellDrop($event, row, 'id_card_back_url')"
                      @click="pickPhotoForRow(row, 'id_card_back_url')"
                    >
                      <el-image
                        v-if="row.id_card_back_url"
                        :src="row.id_card_back_url"
                        :preview-src-list="idCardPreviewList(row)"
                        :initial-index="row.id_card_front_url ? 1 : 0"
                        fit="cover"
                        preview-teleported
                        class="emp-id-photo-thumb"
                        @click.stop
                      />
                      <span v-else>{{ photoUploadingKey === photoCellKey(row.id, 'id_card_back_url') ? '…' : '反面' }}</span>
                    </div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="hire_date" label="入职日期" :width="colWidth('hire_date', 110)" resizable>
                <template #default="{ row }">{{ row.hire_date || '—' }}</template>
              </el-table-column>
              <el-table-column prop="leave_date" label="离职日期" :width="colWidth('leave_date', 110)" resizable>
                <template #default="{ row }">{{ row.leave_date || '—' }}</template>
              </el-table-column>
              <el-table-column column-key="dept" label="部门" :width="colWidth('dept', 110)" resizable>
                <template #default="{ row }">{{ row.department_name || '—' }}</template>
              </el-table-column>
              <el-table-column column-key="job_title" label="职务" :width="colWidth('job_title', 110)" resizable>
                <template #default="{ row }">{{ row.job_title_name || '—' }}</template>
              </el-table-column>
              <el-table-column column-key="processes" label="工序" :width="colWidth('processes', 120)" resizable>
                <template #default="{ row }">
                  <template v-if="row.process_names?.length">
                    <el-tag v-for="name in row.process_names" :key="name" size="small" style="margin-right: 4px">{{ name }}</el-tag>
                  </template>
                  <span v-else class="muted">—</span>
                </template>
              </el-table-column>
              <el-table-column column-key="roles" label="角色" :width="colWidth('roles', 140)" resizable>
                <template #default="{ row }">
                  <template v-if="row.roles?.length">
                    <el-tag v-for="r in row.role_names" :key="r" size="small" style="margin-right: 4px">{{ r }}</el-tag>
                  </template>
                  <span v-else class="muted">—</span>
                </template>
              </el-table-column>
              <el-table-column column-key="base_salary" label="底薪" :width="colWidth('base_salary', 110)" align="right" resizable>
                <template #default="{ row }">
                  {{ row.salary_model === 'fixed' || row.salary_model === 'base_plus_piece' || row.salary_model === 'hourly' ? formatSalaryAmount(row.base_salary) : '—' }}
                </template>
              </el-table-column>
              <el-table-column column-key="guaranteed_salary" label="保底" :width="colWidth('guaranteed_salary', 110)" align="right" resizable>
                <template #default="{ row }">
                  {{ row.salary_model === 'guaranteed_piece' ? formatSalaryAmount(row.base_salary) : '—' }}
                </template>
              </el-table-column>
              <el-table-column column-key="overtime_rate" label="加班费/小时" :width="colWidth('overtime_rate', 120)" align="right" resizable>
                <template #default="{ row }">
                  {{ row.salary_model === 'fixed' ? formatSalaryAmount(row.overtime_hourly_rate) : '—' }}
                </template>
              </el-table-column>
              <el-table-column column-key="meal_allowance_daily" label="餐补/天" :width="colWidth('meal_allowance_daily', 100)" align="right" resizable>
                <template #default="{ row }">
                  {{ Number(row.meal_allowance_daily || 0) > 0 ? formatSalaryAmount(row.meal_allowance_daily) : '—' }}
                </template>
              </el-table-column>
              <el-table-column column-key="housing_allowance_daily" label="住宿补/天" :width="colWidth('housing_allowance_daily', 110)" align="right" resizable>
                <template #default="{ row }">
                  {{ Number(row.housing_allowance_daily || 0) > 0 ? formatSalaryAmount(row.housing_allowance_daily) : '—' }}
                </template>
              </el-table-column>
              <el-table-column column-key="other_allowance_daily" label="其它补/天" :width="colWidth('other_allowance_daily', 110)" align="right" resizable>
                <template #default="{ row }">
                  {{ Number(row.other_allowance_daily || 0) > 0 ? formatSalaryAmount(row.other_allowance_daily) : '—' }}
                </template>
              </el-table-column>
              <el-table-column label="员工考核参考" align="center">
                <el-table-column column-key="cumulative_wage" label="累计工资" :width="colWidth('cumulative_wage', 110)" align="right" resizable>
                  <template #default="{ row }">{{ formatSalaryAmount(row.cumulative_wage) }}</template>
                </el-table-column>
                <el-table-column column-key="cumulative_loss" label="累计损失" :width="colWidth('cumulative_loss', 110)" align="right" resizable>
                  <template #default="{ row }">{{ formatSalaryAmount(row.cumulative_loss) }}</template>
                </el-table-column>
                <el-table-column column-key="loss_wage_ratio" label="损失/工资" :width="colWidth('loss_wage_ratio', 100)" align="right" resizable>
                  <template #default="{ row }">{{ formatLossRatio(row.loss_wage_ratio) }}</template>
                </el-table-column>
              </el-table-column>
              <el-table-column column-key="status" label="状态" :width="colWidth('status', 80)" resizable>
                <template #default="{ row }">
                  <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                    {{ row.is_active ? '在职' : '离职' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column column-key="actions" label="操作" width="56" align="center" :resizable="false">
                <template #default="{ row }">
                  <el-dropdown
                    v-if="$can(['btn.workers.write', 'btn.users.write'])"
                    trigger="click"
                    @command="(cmd: string) => onEmployeeCommand(row, cmd)"
                  >
                    <el-button link class="emp-more-button" aria-label="更多操作">···</el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item v-if="$can(['btn.workers.write', 'btn.users.write'])" command="edit">编辑</el-dropdown-item>
                        <el-dropdown-item v-if="$can('btn.workers.write')" command="salary">薪资档案</el-dropdown-item>
                        <el-dropdown-item v-if="row.has_account && $can('btn.users.write')" command="reset">重置密码</el-dropdown-item>
                        <el-dropdown-item v-if="$can('btn.users.write')" command="active">{{ row.is_active ? '离职' : '复职' }}</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </section>
    </div>

    <!-- 员工新增/编辑 -->
    <el-dialog v-model="visible" :title="form.id ? '编辑员工' : '新增员工'" width="min(640px, calc(100vw - 32px))">
      <el-form label-width="110px">
        <el-form-item label="姓名" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="照片">
          <div
            class="emp-photo-drop"
            :class="{ 'is-dragging': formPhotoDraggingSlot === 'photo_url', 'is-uploading': formPhotoUploadingSlot === 'photo_url' }"
            @dragenter.prevent="onFormPhotoDragEnter('photo_url')"
            @dragover.prevent
            @dragleave.prevent="onFormPhotoDragLeave('photo_url')"
            @drop.prevent="onFormPhotoDrop($event, 'photo_url')"
            @click="pickFormPhoto('photo_url')"
          >
            <template v-if="form.photo_url">
              <el-image
                :src="form.photo_url"
                :preview-src-list="[form.photo_url]"
                fit="cover"
                preview-teleported
                class="emp-photo-preview"
                @click.stop
              />
              <button type="button" class="emp-photo-remove" title="移除照片" @click.stop="form.photo_url = ''">×</button>
            </template>
            <span v-else>{{ formPhotoUploadingSlot === 'photo_url' ? '上传中…' : formPhotoDraggingSlot === 'photo_url' ? '松开以上传' : '拖拽或点击上传，可不填' }}</span>
          </div>
        </el-form-item>
        <el-form-item label="手机" required>
          <el-input v-model="form.mobile" placeholder="登录账号，必填" />
        </el-form-item>
        <el-form-item label="入职日期" required>
          <el-date-picker
            v-model="form.hire_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择入职日期"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item v-if="form.id && form.is_active === false" label="离职日期" required>
          <el-date-picker
            v-model="form.leave_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择离职日期"
            :disabled-date="disableFormLeaveDate"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="身份证号">
          <el-input v-model="form.identity_card_no" maxlength="32" placeholder="可选" />
        </el-form-item>
        <el-form-item label="身份证照片">
          <div class="emp-id-photo-pair">
            <div>
              <div class="emp-id-caption">人像面</div>
              <div
                class="emp-photo-drop emp-id-photo-drop"
                :class="{ 'is-dragging': formPhotoDraggingSlot === 'id_card_front_url', 'is-uploading': formPhotoUploadingSlot === 'id_card_front_url' }"
                @dragenter.prevent="onFormPhotoDragEnter('id_card_front_url')"
                @dragover.prevent
                @dragleave.prevent="onFormPhotoDragLeave('id_card_front_url')"
                @drop.prevent="onFormPhotoDrop($event, 'id_card_front_url')"
                @click="pickFormPhoto('id_card_front_url')"
              >
                <template v-if="form.id_card_front_url">
                  <el-image
                    :src="form.id_card_front_url"
                    :preview-src-list="[form.id_card_front_url, form.id_card_back_url].filter(Boolean)"
                    fit="cover"
                    preview-teleported
                    class="emp-id-photo-preview"
                    @click.stop
                  />
                  <button type="button" class="emp-photo-remove" title="移除人像面" @click.stop="form.id_card_front_url = ''">×</button>
                </template>
                <span v-else>{{ formPhotoUploadingSlot === 'id_card_front_url' ? '上传中…' : formPhotoDraggingSlot === 'id_card_front_url' ? '松开以上传' : '拖拽或点击，可不填' }}</span>
              </div>
            </div>
            <div>
              <div class="emp-id-caption">国徽面</div>
              <div
                class="emp-photo-drop emp-id-photo-drop"
                :class="{ 'is-dragging': formPhotoDraggingSlot === 'id_card_back_url', 'is-uploading': formPhotoUploadingSlot === 'id_card_back_url' }"
                @dragenter.prevent="onFormPhotoDragEnter('id_card_back_url')"
                @dragover.prevent
                @dragleave.prevent="onFormPhotoDragLeave('id_card_back_url')"
                @drop.prevent="onFormPhotoDrop($event, 'id_card_back_url')"
                @click="pickFormPhoto('id_card_back_url')"
              >
                <template v-if="form.id_card_back_url">
                  <el-image
                    :src="form.id_card_back_url"
                    :preview-src-list="[form.id_card_front_url, form.id_card_back_url].filter(Boolean)"
                    :initial-index="form.id_card_front_url ? 1 : 0"
                    fit="cover"
                    preview-teleported
                    class="emp-id-photo-preview"
                    @click.stop
                  />
                  <button type="button" class="emp-photo-remove" title="移除国徽面" @click.stop="form.id_card_back_url = ''">×</button>
                </template>
                <span v-else>{{ formPhotoUploadingSlot === 'id_card_back_url' ? '上传中…' : formPhotoDraggingSlot === 'id_card_back_url' ? '松开以上传' : '拖拽或点击，可不填' }}</span>
              </div>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="紧急联系人">
          <el-input v-model="form.emergency_contact" maxlength="50" placeholder="可选" />
        </el-form-item>
        <el-form-item label="紧急联系电话">
          <el-input v-model="form.emergency_phone" maxlength="20" placeholder="可选" />
        </el-form-item>
        <el-form-item label="部门" for="">
          <el-select
            v-model="form.department_id"
            clearable
            filterable
            placeholder="请选择"
            style="width: 100%"
            @change="onDeptSelectChange"
          >
            <el-option v-for="d in deptOptions" :key="d.id" :label="d.name" :value="d.id" />
            <el-option :value="__NEW_DEPT__" label="＋ 新建部门…" />
          </el-select>
        </el-form-item>
        <el-form-item label="职务" for="">
          <el-select
            v-model="form.job_title_id"
            clearable
            filterable
            placeholder="请选择"
            style="width: 100%"
            @change="onJobTitleSelectChange"
          >
            <el-option v-for="t in jobTitles" :key="t.id" :label="t.name" :value="t.id" />
            <el-option :value="__NEW_JOB__" label="＋ 新建职务…" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="formDeptSegmentId != null" label="工序" for="">
          <el-select
            v-model="form.process_ids"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="只能选本部门工序段下的工序"
            style="width: 100%"
          >
            <el-option v-for="p in processFormOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>

        <template v-if="form.id">
          <el-divider content-position="left">权限</el-divider>
          <p class="muted" style="margin: 0 0 10px; font-size: 12px; line-height: 1.6">
            后台权限与手机功能统一由角色控制；生产员工的手机功能请到“角色”中配置。
          </p>
          <el-form-item label="角色" for="">
            <el-select
              v-model="form.roles"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              :disabled="!isAdmin"
              placeholder="可多选，权限取并集；不选 = 纯生产员工"
              style="width: 100%"
            >
              <el-option v-for="r in roleOptions" :key="r.code" :label="r.name" :value="r.code" />
            </el-select>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button v-permission="['btn.workers.write', 'btn.users.write']" type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
    <input ref="photoFileRef" type="file" accept="image/*" hidden @change="onPhotoFile" />

    <el-dialog v-model="leaveVisible" title="办理离职" width="min(420px, calc(100vw - 32px))">
      <p class="muted" style="margin: 0 0 12px; line-height: 1.6">
        为「{{ leaveForm.name }}」办理离职。离职后不计入部门人数，且不能登录。
      </p>
      <el-form label-width="90px">
        <el-form-item label="离职日期" required>
          <el-date-picker
            v-model="leaveForm.leave_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择离职日期"
            :disabled-date="disableLeaveDialogDate"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="leaveVisible = false">取消</el-button>
        <el-button type="danger" @click="confirmLeave">确认离职</el-button>
      </template>
    </el-dialog>

    <!-- 薪资档案（计薪方式 / 银行卡，与员工基础信息分开） -->
    <el-dialog
      v-model="salaryVisible"
      :title="salaryForm.name ? `薪资档案 · ${salaryForm.name}` : '薪资档案'"
      width="min(520px, calc(100vw - 32px))"
    >
      <el-form label-width="110px">
        <el-form-item label="计薪方式">
          <el-select v-model="salaryForm.salary_model" style="width: 100%">
            <el-option label="纯计件" value="pure_piece" />
            <el-option v-if="salaryForm.salary_model === 'base_plus_piece'" label="底薪+计件" value="base_plus_piece" />
            <el-option label="保底+计件" value="guaranteed_piece" />
            <el-option label="底薪" value="fixed" />
          </el-select>
        </el-form-item>
        <el-form-item
          v-if="salaryForm.salary_model !== 'pure_piece'"
          :label="salaryForm.salary_model === 'guaranteed_piece' ? '保底金额' : '底薪'"
        >
          <el-input-number v-model="salaryForm.base_salary" :min="0" :precision="2" />
        </el-form-item>
        <el-form-item v-if="salaryForm.salary_model === 'fixed'" label="每小时加班费">
          <el-input-number v-model="salaryForm.overtime_hourly_rate" :min="0" :precision="2" />
          <span class="muted" style="margin-left: 8px">已设加班时间段时按打卡时长计算，未设时按每天超过 8 小时</span>
        </el-form-item>
        <el-form-item label="餐费补贴">
          <el-input-number v-model="salaryForm.meal_allowance_daily" :min="0" :precision="2" />
          <span class="muted" style="margin-left: 8px">元/天 · 按出勤天数</span>
        </el-form-item>
        <el-form-item label="住宿补贴">
          <el-input-number v-model="salaryForm.housing_allowance_daily" :min="0" :precision="2" />
          <span class="muted" style="margin-left: 8px">元/天 · 按出勤天数</span>
        </el-form-item>
        <el-form-item label="其它补贴">
          <el-input-number v-model="salaryForm.other_allowance_daily" :min="0" :precision="2" />
          <span class="muted" style="margin-left: 8px">元/天 · 按出勤天数</span>
        </el-form-item>
        <el-form-item label="收款户名"><el-input v-model="salaryForm.bank_account_name" placeholder="默认与姓名相同" /></el-form-item>
        <el-form-item label="银行卡号"><el-input v-model="salaryForm.bank_account" placeholder="银行代发用" /></el-form-item>
        <el-form-item label="开户行"><el-input v-model="salaryForm.bank_name" placeholder="如 工行XX支行" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="salaryVisible = false">取消</el-button>
        <el-button v-permission="'btn.workers.write'" type="primary" @click="saveSalaryProfile">保存</el-button>
      </template>
    </el-dialog>

    <!-- 快捷新建部门（员工表单里顺手建，建完自动选中） -->
    <el-dialog v-model="quickDeptVisible" title="＋ 新建部门" width="380px">
      <el-form label-width="80px">
        <el-form-item label="名称" required><el-input v-model="quickDeptForm.name" placeholder="如：针车二部" /></el-form-item>
        <el-form-item label="工序段">
          <el-select v-model="quickDeptForm.process_segment_id" clearable filterable placeholder="未挂段" style="width: 100%">
            <el-option v-for="seg in quickDeptSegments" :key="seg.id" :label="seg.name" :value="seg.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="quickDeptVisible = false">取消</el-button>
        <el-button v-permission="'btn.workers.write'" type="primary" @click="saveQuickDept">保存并选中</el-button>
      </template>
    </el-dialog>

    <!-- 部门新增/编辑 -->
    <el-dialog v-model="deptVisible" :title="deptForm.id ? '编辑部门' : '新增部门'" width="480px">
      <el-form label-width="90px">
        <el-form-item label="部门名称" required><el-input v-model="deptForm.name" /></el-form-item>
        <el-form-item v-if="deptForm.id" label="上级部门">
          <el-select v-model="deptForm.parent_id" clearable filterable placeholder="留空=顶级部门" style="width: 100%">
            <el-option
              v-for="d in deptParentOptions"
              :key="d.id"
              :label="d.name"
              :value="d.id"
              :disabled="d.id === deptForm.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="工序段">
          <el-select v-model="deptForm.process_segment_id" clearable filterable placeholder="未挂段" style="width: 100%">
            <el-option v-for="seg in segments" :key="seg.id" :label="seg.name" :value="seg.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人">
          <el-select
            v-model="deptForm.leader_id"
            clearable
            filterable
            placeholder="选一名员工（可跨部门）；无班组时即组长，派工「派给负责人」用此"
            style="width: 100%"
          >
            <el-option v-for="e in employeeOptions" :key="e.id" :label="e.mobile ? `${e.name}（${e.mobile}）` : e.name" :value="e.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="排序"><el-input-number v-model="deptForm.sort_order" :min="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="deptVisible = false">取消</el-button>
        <el-button v-permission="'btn.workers.write'" type="primary" @click="saveDept">保存</el-button>
      </template>
    </el-dialog>

    <!-- 新建/编辑班组 -->
    <el-dialog v-model="teamVisible" :title="teamForm.id ? '编辑' + teamLabelText : '新建' + teamLabelText" width="420px">
      <el-form label-width="90px">
        <el-form-item :label="teamLabelText + '名称'" required><el-input v-model="teamForm.name" /></el-form-item>
        <el-form-item :label="leaderLabelText">
          <el-select v-model="teamForm.leader_worker_id" clearable filterable placeholder="可空" style="width: 100%">
            <el-option v-for="e in employeeOptions" :key="e.id" :label="e.mobile ? `${e.name}（${e.mobile}）` : e.name" :value="e.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属部门" required>
          <el-select v-model="teamForm.department_id" clearable filterable placeholder="仅挂工序段的部门可建" style="width: 100%">
            <el-option v-for="d in segmentDeptOptions" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="teamVisible = false">取消</el-button>
        <el-button v-permission="'btn.teams.write'" type="primary" @click="saveTeam">保存</el-button>
      </template>
    </el-dialog>

    <!-- 成员管理 -->
    <el-dialog v-model="membersVisible" :title="`成员管理：${editingTeamName}`" width="460px">
      <el-transfer
        v-model="memberIds"
        :data="workerOptions"
        :titles="['全部工人', '成员']"
        filterable
      />
      <template #footer>
        <el-button @click="membersVisible = false">取消</el-button>
        <el-button v-permission="'btn.teams.write'" type="primary" @click="saveMembers">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Folder, FolderOpened } from '@element-plus/icons-vue'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import { fetchOrgSettings } from '@/composables/useOrgSettings'
import { prepareImageForUpload } from '@/utils/imageUpload'

const auth = useAuthStore()
const isAdmin = computed(() => auth.isAdmin())
const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths('employees-list', tableRef, {
  flexKey: 'roles',
  flexDefaultMin: 140,
  fitToContainer: true,
  groupEdgeResize: true,
})
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()

const TREE_COLLAPSE_KEY = 'erp_employees_tree_collapsed'
const treeCollapsed = ref(false)

function toggleTreeCollapsed() {
  treeCollapsed.value = !treeCollapsed.value
  try {
    localStorage.setItem(TREE_COLLAPSE_KEY, treeCollapsed.value ? '1' : '0')
  } catch {
    // ignore
  }
  void nextTick(() => {
    measureTableHeight()
    relayoutTable()
  })
}

// ── 左右分栏：部门树 + 当前部门下的生产单位 ──
const orgEnableTeams = ref(false)
const teamLabelText = ref('班组')
const leaderLabelText = computed(() => {
  if (teamLabelText.value === '产线') return '线长'
  if (teamLabelText.value === '班') return '班长'
  return '组长'
})

const showTeamDetail = computed(() => !!selectedTeam.value)

// ── 部门树（纯部门，不混班组） ──
interface OrgNode {
  id: string
  kind: 'root' | 'dept'
  name: string
  dept_id?: number
  parent_id: number | null
  manager_name?: string
  leader_name?: string
  segment_id?: number | null
  employee_count: number
  is_active: boolean
  raw?: any
  children?: OrgNode[]
}

const depts = ref<any[]>([])
const segments = ref<any[]>([])
const deptTreeRef = ref()
const treeData = ref<OrgNode[]>([])
const deptTreeKey = ref(0)
const selectedKey = ref<string | null>(null)
const selectedDeptId = ref<number | null | 'all'>(null)

function deptTreeLabel(data: OrgNode) {
  return data.leader_name ? `${data.name} ${data.leader_name}` : data.name
}

function buildDeptTree(list: any[]): OrgNode[] {
  const root: OrgNode = {
    id: 'all',
    kind: 'root',
    name: auth.tenantName || '全部员工',
    parent_id: null,
    employee_count: list.reduce((n, d) => n + (d.employee_count || 0), 0),
    is_active: true,
    children: [],
  }
  const byId = new Map<number, OrgNode>()
  for (const d of list) {
    byId.set(d.id, {
      id: `dept-${d.id}`,
      kind: 'dept',
      name: d.name,
      dept_id: d.id,
      parent_id: d.parent_id,
      manager_name: d.manager_name,
      leader_name: d.leader_name,
      segment_id: d.process_segment_id,
      employee_count: d.employee_count || 0,
      is_active: d.is_active,
      raw: d,
      children: [],
    })
  }
  const roots: OrgNode[] = []
  for (const node of byId.values()) {
    if (node.parent_id != null && byId.has(node.parent_id)) {
      byId.get(node.parent_id)!.children!.push(node)
    } else {
      roots.push(node)
    }
  }
  root.children = roots
  return [root]
}

function findNode(nodes: OrgNode[], id: string): OrgNode | null {
  for (const n of nodes) {
    if (n.id === id) return n
    if (n.children?.length) {
      const hit = findNode(n.children, id)
      if (hit) return hit
    }
  }
  return null
}

function rebuildTree() {
  treeData.value = buildDeptTree(depts.value)
  deptTreeKey.value += 1
  // 树重建后同步选中态：节点消失则回落根
  if (selectedKey.value) {
    const node = findNode(treeData.value, selectedKey.value)
    if (!node) {
      selectedKey.value = null
      selectedDeptId.value = null
    }
  }
}

async function loadDepts() {
  const res: any = await http.get('/departments')
  depts.value = res.data?.items || []
  rebuildTree()
}

async function loadSegments() {
  const segRes: any = await http.get('/process-segments')
  segments.value = segRes.data?.items || []
}

function onDeptClick(data: OrgNode) {
  selectedKey.value = data.id
  selectedDeptId.value = data.kind === 'root' ? 'all' : (data.dept_id ?? null)
  selectedTeam.value = null
  selectedTeamId.value = null
  void load()
}

// 部门下拉选项（含子部门平铺，缩进提示；不含根节点）
const deptOptions = computed(() => {
  const flat: any[] = []
  const walk = (nodes: OrgNode[], depth: number) => {
    for (const n of nodes) {
      if (n.kind === 'dept') flat.push({ id: n.dept_id, name: `${'　'.repeat(depth)}${n.name}` })
      if (n.children?.length) walk(n.children, depth + 1)
    }
  }
  walk(treeData.value, 0)
  return flat
})

// 员工下拉（部门负责人 / 组长选择）
const employeeOptions = ref<any[]>([])
async function loadEmployeeOptions() {
  try {
    const res: any = await http.get('/employees', { params: { page_size: 500, is_active: true } })
    employeeOptions.value = res.data?.items || []
  } catch {
    employeeOptions.value = []
  }
}

// ── 部门 CRUD ──
const deptVisible = ref(false)
const deptForm = reactive<any>({
  id: null,
  name: '',
  parent_id: null,
  process_segment_id: null,
  leader_id: null,
  sort_order: 0,
})

function openDeptCreate(parentId?: number | null) {
  // 显式传 null = 顶级；未传才用当前选中部门作默认上级（须仍存在）
  const fallback =
    selectedDeptId.value !== 'all' && depts.value.some((d) => d.id === selectedDeptId.value)
      ? selectedDeptId.value
      : null
  Object.assign(deptForm, {
    id: null,
    name: '',
    parent_id: parentId !== undefined ? parentId : fallback,
    process_segment_id: null,
    leader_id: null,
    sort_order: 0,
  })
  deptVisible.value = true
}

function openDeptEdit(data: OrgNode) {
  const raw = depts.value.find((d) => d.id === data.dept_id)
  Object.assign(deptForm, {
    id: data.dept_id,
    name: data.name,
    parent_id: data.parent_id ?? null,
    process_segment_id: data.segment_id ?? null,
    leader_id: raw?.leader_id ?? null,
    sort_order: raw?.sort_order ?? 0,
  })
  deptVisible.value = true
}

const deptParentOptions = computed(() => deptOptions.value.filter((d) => d.id !== deptForm.id))

async function saveDept() {
  if (!String(deptForm.name || '').trim()) {
    ElMessage.warning('请填写部门名称')
    return
  }
  const payload = {
    name: deptForm.name.trim(),
    parent_id: deptForm.parent_id ?? null,
    process_segment_id: deptForm.process_segment_id ?? null,
    leader_id: deptForm.leader_id ?? null,
    sort_order: deptForm.sort_order || 0,
  }
  if (deptForm.id) {
    await http.patch(`/departments/${deptForm.id}`, payload)
  } else {
    await http.post('/departments', payload)
  }
  ElMessage.success('已保存')
  deptVisible.value = false
  await refreshOrg()
  await loadEmployeeOptions()
  await load()
}

function onDeptCommand(data: OrgNode, cmd: string) {
  if (cmd === 'child') openDeptCreate(data.kind === 'root' ? null : data.dept_id)
  else if (cmd === 'edit' && data.kind === 'dept') openDeptEdit(data)
  else if (cmd === 'delete' && data.kind === 'dept') void deleteDept(data)
}

async function deleteDept(data: OrgNode) {
  try {
    await ElMessageBox.confirm(
      `确定删除部门「${data.name}」？删除后不可恢复。`,
      '删除部门',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    // silent：守卫提示（有子部门/员工）由后端 detail 自己弹，避免拦截器双提示
    await http.delete(`/departments/${data.dept_id}`, { silent: true } as any)
    ElMessage.success('部门已删除')
    if (selectedDeptId.value === data.dept_id) {
      selectedKey.value = null
      selectedDeptId.value = null
    }
    await refreshOrg()
    await load()
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    ElMessage.warning(typeof detail === 'string' ? detail : '无法删除该部门')
  }
}

function onEmployeeCommand(row: any, cmd: string) {
  if (cmd === 'edit') openEdit(row)
  else if (cmd === 'salary') openSalaryProfile(row)
  else if (cmd === 'reset') void resetPwd(row)
  else if (cmd === 'active') void toggleActive(row)
}

// ── 班组（独立列表管理，不混入部门树） ──
const teams = ref<any[]>([])
const selectedTeam = ref<any | null>(null)
const selectedTeamId = ref<number | null>(null)

const selectedDeptHasSegment = computed(() => {
  if (typeof selectedDeptId.value !== 'number') return false
  return depts.value.some((d) => d.id === selectedDeptId.value && d.process_segment_id)
})

const canCreateTeam = computed(() => selectedDeptHasSegment.value)

const teamCreateHint = computed(() => {
  if (typeof selectedDeptId.value !== 'number') return `请先选中已挂工序段的部门，再新建${teamLabelText.value}`
  if (!selectedDeptHasSegment.value) return `需先给该部门挂工序段，才能建${teamLabelText.value}`
  return ''
})

const scopedTeams = computed(() => {
  if (typeof selectedDeptId.value !== 'number') return []
  return teams.value.filter((t) => t.department_id === selectedDeptId.value)
})

/** 班组只能建在挂了工序段的部门下（D8），新建弹窗的部门下拉只列这些。 */
const segmentDeptOptions = computed(() => {
  const withSegment = new Set(depts.value.filter((d) => d.process_segment_id).map((d) => d.id))
  return deptOptions.value.filter((d) => withSegment.has(d.id))
})

async function loadTeams() {
  try {
    const res: any = await http.get('/teams', { params: { include_inactive: true } })
    teams.value = res.data?.items || []
  } catch {
    teams.value = []
  }
}

function onTeamClick(t: any) {
  selectedTeamId.value = t.id
  selectedTeam.value = t
}

function clearTeamSelection() {
  selectedTeamId.value = null
  selectedTeam.value = null
}

const teamVisible = ref(false)
const teamForm = reactive<any>({ id: null, name: '', leader_worker_id: null, department_id: null })

function openTeam() {
  Object.assign(teamForm, {
    id: null,
    name: '',
    leader_worker_id: null,
    department_id: typeof selectedDeptId.value === 'number' && selectedDeptHasSegment.value
      ? selectedDeptId.value
      : (segmentDeptOptions.value[0]?.id ?? null),
  })
  teamVisible.value = true
}

function editTeam(t: any) {
  Object.assign(teamForm, {
    id: t.id,
    name: t.name,
    leader_worker_id: t.leader_worker_id ?? null,
    department_id: t.department_id ?? null,
  })
  teamVisible.value = true
}

async function saveTeam() {
  if (!String(teamForm.name || '').trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  if (teamForm.department_id == null) {
    ElMessage.warning('请选择所属部门（需已挂工序段）')
    return
  }
  const payload = {
    name: teamForm.name.trim(),
    leader_worker_id: teamForm.leader_worker_id,
    department_id: teamForm.department_id,
  }
  if (teamForm.id) await http.patch(`/teams/${teamForm.id}`, payload)
  else await http.post('/teams', payload)
  ElMessage.success('已保存')
  teamVisible.value = false
  await refreshTeams()
}

// ── 组员管理 ──
const membersVisible = ref(false)
const memberIds = ref<number[]>([])
const editingTeamId = ref<number | null>(null)
const editingTeamName = ref('')
const workerOptions = ref<{ key: number; label: string }[]>([])

async function ensureWorkerMap() {
  if (workerOptions.value.length) return
  try {
    const res: any = await http.get('/teams/worker-map')
    workerOptions.value = Object.entries(res.data?.map || {}).map(([id, name]: any) => ({
      key: Number(id),
      label: name,
    }))
  } catch {
    workerOptions.value = []
  }
}

async function manageMembers(t: any) {
  editingTeamId.value = t.id
  editingTeamName.value = t.name
  memberIds.value = (t.members || []).map((m: any) => Number(m.id))
  await ensureWorkerMap()
  membersVisible.value = true
}

async function saveMembers() {
  if (editingTeamId.value == null) return
  await http.put(`/teams/${editingTeamId.value}/members`, { worker_ids: memberIds.value })
  ElMessage.success('已保存')
  membersVisible.value = false
  await refreshTeams()
}

async function refreshTeams() {
  await loadTeams()
  // 组员/班组数据变化后，同步右侧选中详情
  if (selectedTeamId.value != null) {
    const hit = teams.value.find((t) => t.id === selectedTeamId.value)
    selectedTeam.value = hit ?? null
    if (!hit) selectedTeamId.value = null
  }
}

async function refreshOrg() {
  await Promise.all([loadDepts(), loadTeams()])
}

// ── 员工表单：部门下拉快捷新建（D11/25.2） ──
const __NEW_DEPT__ = Symbol('new-dept')
const __NEW_JOB__ = Symbol('new-job')
const jobTitles = ref<any[]>([])
async function loadJobTitles() {
  try {
    const res: any = await http.get('/job-titles', { params: { active_only: true } })
    jobTitles.value = res.data?.items || []
  } catch {
    jobTitles.value = []
  }
}
async function onJobTitleSelectChange(val: any) {
  if (val !== __NEW_JOB__) return
  form.job_title_id = null
  try {
    const { value } = await ElMessageBox.prompt('职务名称', '新建职务', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputPlaceholder: '如：厂长',
    })
    const name = String(value || '').trim()
    if (!name) return
    const res: any = await http.post('/job-titles', { name, is_active: true })
    await loadJobTitles()
    form.job_title_id = res.data?.id ?? null
  } catch {
    form.job_title_id = null
  }
}
const quickDeptVisible = ref(false)
const quickDeptForm = reactive<any>({ name: '', process_segment_id: null })
const quickDeptSegments = ref<any[]>([])
async function onDeptSelectChange(val: any) {
  if (val === __NEW_DEPT__) {
    form.department_id = null
    void quickAddDept()
    return
  }
  pruneProcessIds()
}
async function quickAddDept() {
  quickDeptForm.name = ''
  quickDeptForm.process_segment_id = null
  try {
    const segRes: any = await http.get('/process-segments')
    quickDeptSegments.value = segRes.data?.items || []
  } catch {
    quickDeptSegments.value = []
  }
  quickDeptVisible.value = true
}
async function saveQuickDept() {
  if (!String(quickDeptForm.name || '').trim()) {
    ElMessage.warning('请填写部门名称')
    return
  }
  const res: any = await http.post('/departments', {
    name: quickDeptForm.name.trim(),
    process_segment_id: quickDeptForm.process_segment_id,
  })
  quickDeptVisible.value = false
  ElMessage.success('已新建部门')
  await refreshOrg()
  await loadEmployeeOptions()
  form.department_id = res.data?.id ?? null
  pruneProcessIds()
}

// ── 员工列表 ──
const rows = ref<any[]>([])
const processes = ref<any[]>([])
const visible = ref(false)
const filters = reactive({
  keyword: '',
  process_id: null as number | null,
})
/** 默认不列出离职人员；勾选后在职与离职一起显示。部门人数始终不含离职。 */
const showLeftEmployees = ref(false)
function todayIso() {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** 离职日期不能早于入职日期。 */
function isBeforeHire(day: Date, hire: string) {
  if (!hire) return false
  const [y, m, d] = hire.split('-').map(Number)
  const min = new Date(y, (m || 1) - 1, d || 1)
  const cur = new Date(day.getFullYear(), day.getMonth(), day.getDate())
  return cur.getTime() < min.getTime()
}

const form = reactive<any>({
  id: null,
  name: '',
  mobile: '',
  identity_card_no: '',
  emergency_contact: '',
  emergency_phone: '',
  photo_url: '',
  id_card_front_url: '',
  id_card_back_url: '',
  hire_date: '',
  leave_date: '',
  is_active: true,
  department_id: null,
  job_title_id: null,
  process_ids: [] as number[],
  roles: [] as string[],
})

type PhotoSlot = 'photo_url' | 'id_card_front_url' | 'id_card_back_url'

const photoFileRef = ref<HTMLInputElement | null>(null)
const photoPickTarget = ref<'form' | number | null>(null)
const photoPickSlot = ref<PhotoSlot>('photo_url')
const photoUploadingKey = ref<string | null>(null)
const photoDragKey = ref<string | null>(null)
const formPhotoUploadingSlot = ref<PhotoSlot | null>(null)
const formPhotoDraggingSlot = ref<PhotoSlot | null>(null)
let photoDragDepth = 0
let formPhotoDragDepth = 0

function photoCellKey(id: number, slot: PhotoSlot) {
  return `${id}:${slot}`
}

function resetPhotoCellDrag() {
  photoDragDepth = 0
  photoDragKey.value = null
}

function onPhotoCellDragEnter(row: { id: number }, slot: PhotoSlot) {
  const key = photoCellKey(row.id, slot)
  if (photoDragKey.value !== key) {
    photoDragDepth = 0
    photoDragKey.value = key
  }
  photoDragDepth += 1
}

function onPhotoCellDragLeave(row: { id: number }, slot: PhotoSlot) {
  if (photoDragKey.value !== photoCellKey(row.id, slot)) return
  photoDragDepth = Math.max(0, photoDragDepth - 1)
  if (photoDragDepth === 0) photoDragKey.value = null
}

function idCardPreviewList(row: { id_card_front_url?: string; id_card_back_url?: string }) {
  return [row.id_card_front_url, row.id_card_back_url].filter((url): url is string => !!url)
}

function pickPhotoForRow(row: { id: number; photo_url?: string; id_card_front_url?: string; id_card_back_url?: string }, slot: PhotoSlot) {
  if (row[slot] || photoUploadingKey.value != null) return
  photoPickTarget.value = row.id
  photoPickSlot.value = slot
  photoFileRef.value?.click()
}

function pickFormPhoto(slot: PhotoSlot) {
  if (formPhotoUploadingSlot.value) return
  photoPickTarget.value = 'form'
  photoPickSlot.value = slot
  photoFileRef.value?.click()
}

function onFormPhotoDragEnter(slot: PhotoSlot) {
  if (formPhotoUploadingSlot.value) return
  if (formPhotoDraggingSlot.value !== slot) {
    formPhotoDragDepth = 0
    formPhotoDraggingSlot.value = slot
  }
  formPhotoDragDepth += 1
}

function onFormPhotoDragLeave(slot: PhotoSlot) {
  if (formPhotoDraggingSlot.value !== slot) return
  formPhotoDragDepth = Math.max(0, formPhotoDragDepth - 1)
  if (formPhotoDragDepth === 0) formPhotoDraggingSlot.value = null
}

function resetFormPhotoDrag() {
  formPhotoDragDepth = 0
  formPhotoDraggingSlot.value = null
}

function photoFailText(slot: PhotoSlot) {
  return slot === 'photo_url' ? '照片上传失败' : '身份证照片上传失败'
}

async function uploadPhotoFile(file: File) {
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('请上传图片')
    return ''
  }
  const prepared = await prepareImageForUpload(file)
  const body = new FormData()
  body.append('file', prepared)
  const res: any = await http.post('/employees/upload-photo', body, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return String(res.data?.url || '')
}

async function onPhotoCellDrop(event: DragEvent, row: { id: number }, slot: PhotoSlot) {
  resetPhotoCellDrag()
  const file = Array.from(event.dataTransfer?.files || []).find((item) => item.type.startsWith('image/'))
  if (!file) {
    if (event.dataTransfer?.files?.length) ElMessage.warning('请上传图片')
    return
  }
  photoUploadingKey.value = photoCellKey(row.id, slot)
  try {
    const url = await uploadPhotoFile(file)
    if (!url) return
    await http.patch(`/employees/${row.id}`, { [slot]: url })
    ;(row as Record<string, unknown>)[slot] = url
  } catch (err: any) {
    if (!err?.response) ElMessage.error(err?.message || photoFailText(slot))
  } finally {
    photoUploadingKey.value = null
  }
}

async function onFormPhotoDrop(event: DragEvent, slot: PhotoSlot) {
  resetFormPhotoDrag()
  const file = Array.from(event.dataTransfer?.files || []).find((item) => item.type.startsWith('image/'))
  if (!file) {
    if (event.dataTransfer?.files?.length) ElMessage.warning('请上传图片')
    return
  }
  formPhotoUploadingSlot.value = slot
  try {
    const url = await uploadPhotoFile(file)
    if (url) form[slot] = url
  } catch (err: any) {
    if (!err?.response) ElMessage.error(err?.message || photoFailText(slot))
  } finally {
    formPhotoUploadingSlot.value = null
  }
}

async function onPhotoFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  const target = photoPickTarget.value
  const slot = photoPickSlot.value
  input.value = ''
  photoPickTarget.value = null
  if (!file || target == null) return
  if (target === 'form') {
    formPhotoUploadingSlot.value = slot
    try {
      const url = await uploadPhotoFile(file)
      if (url) form[slot] = url
    } catch (err: any) {
      if (!err?.response) ElMessage.error(err?.message || photoFailText(slot))
    } finally {
      formPhotoUploadingSlot.value = null
    }
    return
  }
  photoUploadingKey.value = photoCellKey(target, slot)
  try {
    const url = await uploadPhotoFile(file)
    if (!url) return
    await http.patch(`/employees/${target}`, { [slot]: url })
    const row = rows.value.find((item) => item.id === target)
    if (row) row[slot] = url
  } catch (err: any) {
    if (!err?.response) ElMessage.error(err?.message || photoFailText(slot))
  } finally {
    photoUploadingKey.value = null
  }
}

const leaveVisible = ref(false)
const leaveForm = reactive({
  id: null as number | null,
  name: '',
  hire_date: '' as string,
  leave_date: '',
})

function disableFormLeaveDate(day: Date) {
  return isBeforeHire(day, form.hire_date)
}

function disableLeaveDialogDate(day: Date) {
  return isBeforeHire(day, leaveForm.hire_date)
}

const salaryVisible = ref(false)
const salaryForm = reactive<any>({
  id: null,
  name: '',
  salary_model: 'pure_piece',
  base_salary: 0,
  overtime_hourly_rate: 0,
  meal_allowance_daily: 0,
  housing_allowance_daily: 0,
  other_allowance_daily: 0,
  bank_account: '',
  bank_name: '',
  bank_account_name: '',
})

const processOptions = computed(() => processes.value.filter((p) => p.is_active))

function departmentSegmentId(departmentId: number | null | undefined) {
  if (departmentId == null) return null
  const hit = depts.value.find((d) => d.id === departmentId)
  const segId = hit?.process_segment_id
  return segId == null ? null : Number(segId)
}

const formDeptSegmentId = computed(() => departmentSegmentId(form.department_id))

const processFormOptions = computed(() => {
  const segId = formDeptSegmentId.value
  if (segId == null) return []
  const selected = new Set(form.process_ids || [])
  return processes.value.filter((p) => {
    if (Number(p.segment_id) !== segId) return false
    return p.is_active || selected.has(p.id)
  })
})

function pruneProcessIds() {
  const segId = departmentSegmentId(form.department_id)
  if (segId == null) {
    form.process_ids = []
    return
  }
  const allowed = new Set(
    processes.value.filter((p) => Number(p.segment_id) === segId).map((p) => p.id),
  )
  form.process_ids = (form.process_ids || []).filter((id: number) => allowed.has(id))
}

const roleOptions = ref<{ code: string; name: string }[]>([])
const formatSalaryAmount = (value: unknown) => `¥${Number(value || 0).toFixed(2)}`
const formatLossRatio = (value: unknown) => {
  if (value === null || value === undefined || value === '') return '—'
  return `${Number(value).toFixed(2)}%`
}

async function loadRoles() {
  try {
    const res: any = await http.get('/roles')
    const items = res.data?.items || []
    if (items.length) roleOptions.value = items
      .filter((r: any) => r.code !== 'worker')
      .map((r: any) => ({ code: r.code, name: r.name }))
  } catch {
    roleOptions.value = []
  }
}

async function loadProcesses() {
  try {
    const res: any = await http.get('/processes', { params: { page_size: 500 } })
    processes.value = res.data?.items || []
  } catch {
    processes.value = []
  }
}

async function load() {
  const params: any = {
    page_size: 500,
    keyword: filters.keyword.trim() || undefined,
    process_id: filters.process_id || undefined,
    role: filters.role || undefined,
    is_active: showLeftEmployees.value ? undefined : true,
  }
  if (selectedDeptId.value != null && selectedDeptId.value !== 'all') {
    params.department_id = selectedDeptId.value
  }
  const items: any[] = []
  let pageNo = 1
  let totalCount = 0
  while (pageNo < 50) {
    const res: any = await http.get('/employees', { params: { ...params, page: pageNo } })
    const batch = res.data?.items || []
    totalCount = res.data?.total || 0
    items.push(...batch)
    if (!batch.length || items.length >= totalCount) break
    pageNo += 1
  }
  rows.value = items
  void nextTick(() => {
    measureTableHeight()
    relayoutTable()
  })
}

function search() {
  void load()
}

function resetFilters() {
  filters.keyword = ''
  filters.process_id = null
  filters.role = ''
  showLeftEmployees.value = false
  search()
}

function openCreate() {
  Object.assign(form, {
    id: null,
    name: '',
    mobile: '',
    identity_card_no: '',
    emergency_contact: '',
    emergency_phone: '',
    photo_url: '',
    id_card_front_url: '',
    id_card_back_url: '',
    hire_date: todayIso(),
    leave_date: '',
    is_active: true,
    department_id: selectedDeptId.value !== 'all' ? selectedDeptId.value : null,
    job_title_id: null,
    process_ids: [],
    roles: [],
  })
  visible.value = true
}

function openEdit(row: any) {
  Object.assign(form, {
    id: row.id,
    name: row.name,
    mobile: row.mobile || '',
    identity_card_no: row.identity_card_no || '',
    emergency_contact: row.emergency_contact || '',
    emergency_phone: row.emergency_phone || '',
    photo_url: row.photo_url || '',
    id_card_front_url: row.id_card_front_url || '',
    id_card_back_url: row.id_card_back_url || '',
    hire_date: row.hire_date || '',
    leave_date: row.leave_date || '',
    is_active: row.is_active !== false,
    department_id: row.department_id ?? null,
    job_title_id: row.job_title_id ?? null,
    process_ids: Array.isArray(row.process_ids) ? [...row.process_ids] : [],
    roles: Array.isArray(row.roles) ? [...row.roles] : [],
  })
  pruneProcessIds()
  visible.value = true
}

function openSalaryProfile(row: any) {
  Object.assign(salaryForm, {
    id: row.id,
    name: row.name || '',
    salary_model: row.salary_model === 'hourly' ? 'fixed' : (row.salary_model || 'pure_piece'),
    base_salary: Number(row.base_salary || 0),
    overtime_hourly_rate: Number(row.overtime_hourly_rate || 0),
    meal_allowance_daily: Number(row.meal_allowance_daily || 0),
    housing_allowance_daily: Number(row.housing_allowance_daily || 0),
    other_allowance_daily: Number(row.other_allowance_daily || 0),
    bank_account: row.bank_account || '',
    bank_name: row.bank_name || '',
    bank_account_name: row.bank_account_name || '',
  })
  salaryVisible.value = true
}

async function saveSalaryProfile() {
  if (!salaryForm.id) return
  await http.patch(`/employees/${salaryForm.id}`, {
    salary_model: salaryForm.salary_model,
    base_salary: salaryForm.salary_model === 'pure_piece' ? 0 : salaryForm.base_salary,
    overtime_hourly_rate: salaryForm.salary_model === 'fixed' ? salaryForm.overtime_hourly_rate : 0,
    meal_allowance_daily: salaryForm.meal_allowance_daily || 0,
    housing_allowance_daily: salaryForm.housing_allowance_daily || 0,
    other_allowance_daily: salaryForm.other_allowance_daily || 0,
    bank_account: salaryForm.bank_account || null,
    bank_name: salaryForm.bank_name || null,
    bank_account_name: salaryForm.bank_account_name || null,
  })
  ElMessage.success('薪资档案已保存')
  salaryVisible.value = false
  await load()
}

async function save() {
  if (!form.name?.trim()) {
    ElMessage.warning('请填写姓名')
    return
  }
  if (!form.mobile?.trim()) {
    ElMessage.warning('请填写手机号')
    return
  }
  if (!form.hire_date) {
    ElMessage.warning('请选择入职日期')
    return
  }
  if (form.id && form.is_active === false) {
    if (!form.leave_date) {
      ElMessage.warning('请选择离职日期')
      return
    }
    if (form.leave_date < form.hire_date) {
      ElMessage.warning('离职日期不能早于入职日期')
      return
    }
  }
  pruneProcessIds()
  const payload: any = {
    name: form.name.trim(),
    mobile: form.mobile.trim(),
    identity_card_no: form.identity_card_no || null,
    emergency_contact: form.emergency_contact || null,
    emergency_phone: form.emergency_phone || null,
    photo_url: form.photo_url || null,
    id_card_front_url: form.id_card_front_url || null,
    id_card_back_url: form.id_card_back_url || null,
    hire_date: form.hire_date,
    department_id: form.department_id ?? null,
    job_title_id: form.job_title_id ?? null,
    process_ids: form.process_ids || [],
    role: form.role,
  }
  if (form.id && form.is_active === false) {
    payload.leave_date = form.leave_date
  }
  if (form.id && isAdmin.value) {
    payload.roles = form.roles || []
  }
  if (form.id) {
    await http.patch(`/employees/${form.id}`, payload)
  } else {
    await http.post('/employees', payload)
  }
  ElMessage.success('已保存')
  visible.value = false
  await load()
  await refreshOrg()
  await loadEmployeeOptions()
}

function toggleActive(row: any) {
  if (row.is_active) {
    leaveForm.id = row.id
    leaveForm.name = row.name || ''
    leaveForm.hire_date = row.hire_date || ''
    leaveForm.leave_date = todayIso()
    leaveVisible.value = true
    return
  }
  void restoreActive(row)
}

async function confirmLeave() {
  if (!leaveForm.id) return
  if (!leaveForm.leave_date) {
    ElMessage.warning('请选择离职日期')
    return
  }
  if (leaveForm.hire_date && leaveForm.leave_date < leaveForm.hire_date) {
    ElMessage.warning('离职日期不能早于入职日期')
    return
  }
  await http.patch(`/employees/${leaveForm.id}`, {
    is_active: false,
    leave_date: leaveForm.leave_date,
  })
  ElMessage.success('已办理离职')
  leaveVisible.value = false
  await load()
  await refreshOrg()
  await loadEmployeeOptions()
}

async function restoreActive(row: any) {
  try {
    await ElMessageBox.confirm(
      `确定恢复「${row.name}」为在职？恢复后清空离职日期。`,
      '恢复在职',
      { type: 'warning', confirmButtonText: '复职', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await http.patch(`/employees/${row.id}`, { is_active: true })
  ElMessage.success('已恢复在职')
  await load()
  await refreshOrg()
  await loadEmployeeOptions()
}

async function resetPwd(row: any) {
  await http.patch(`/employees/${row.id}`, { reset_password: true })
  ElMessage.success('已重置为默认密码 123456，下次登录须改密')
  await load()
}

onMounted(async () => {
  try {
    treeCollapsed.value = localStorage.getItem(TREE_COLLAPSE_KEY) === '1'
  } catch {
    treeCollapsed.value = false
  }
  try {
    const orgSettings = await fetchOrgSettings()
    orgEnableTeams.value = orgSettings.enable_teams
    teamLabelText.value = orgSettings.team_label
  } catch {
    // 组织设置接口失败时按无班组模式处理
  }
  await Promise.all([loadDepts(), loadTeams(), loadSegments(), loadProcesses(), loadRoles(), loadEmployeeOptions(), loadJobTitles()])
  await load()
})
</script>

<style scoped>
.emp-shell {
  display: flex;
  /* admin.css 对「含分页的 admin-card」强制 column 布局，这里必须行向排列（左树右表） */
  flex-direction: row !important;
  gap: 12px;
  padding: 0;
  overflow: hidden;
}

.emp-tree-panel {
  position: relative;
  width: 240px;
  min-width: 220px;
  min-height: 0;
  border-right: 1px solid var(--el-border-color-lighter, #e4e7ed);
  display: flex;
  flex-direction: column;
  padding: 4px 6px 12px 4px;
  /* 与全局背景（.admin-app #f3f5f8）保持一致，随主题透明继承 */
  background: transparent;
  transition: width 0.18s ease, min-width 0.18s ease, padding 0.18s ease;
}

.emp-shell.is-tree-collapsed .emp-tree-panel {
  width: 36px;
  min-width: 36px;
  padding: 4px 2px 12px;
}

.emp-tab-fill {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}

.emp-tree-toolbar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  flex-shrink: 0;
  height: 16px;
  padding: 0 2px;
  margin-bottom: 2px;
}

.emp-tree-collapse-btn {
  border: none;
  background: transparent;
  color: var(--el-text-color-secondary, #909399);
  width: 22px;
  height: 16px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 16px;
  font-weight: 600;
  line-height: 1;
  padding: 0;
}

.emp-tree-collapse-btn:hover {
  background: var(--el-fill-color-light, #f5f7fa);
  color: var(--el-color-primary);
}

.emp-tree-collapsed-rail {
  flex: 1;
  width: 100%;
  border: none;
  background: transparent;
  cursor: pointer;
  padding: 6px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  color: var(--el-text-color-secondary, #909399);
  border-radius: 6px;
}

.emp-tree-collapsed-rail:hover {
  background: var(--el-fill-color-light, #f5f7fa);
  color: var(--el-color-primary);
}

.emp-tree-collapsed-rail__chev {
  font-size: 12px;
  line-height: 1;
}

.emp-tree-collapsed-rail__text {
  writing-mode: vertical-rl;
  letter-spacing: 0.2em;
  font-size: 12px;
  font-weight: 600;
}

.emp-tree-body {
  flex: 1;
  overflow: auto;
  padding-bottom: 8px;
}

/* ── el-tree 基础：行高 / 悬停 / 选中态 ── */
.emp-tree-body :deep(.el-tree) {
  --el-tree-node-hover-bg-color: #f5f7fa;
  background: transparent;
}

.emp-tree-body :deep(.el-tree-node__content) {
  height: 36px;
  border-radius: 6px;
  margin: 1px 0;
  padding-right: 2px;
}

.emp-tree-body :deep(.el-tree-node__content:hover) {
  background: #f5f7fa;
}

/* 选中：浅蓝背景 + 主色文字 + 左侧蓝色指示条 */
.emp-tree-body :deep(.el-tree-node.is-current > .el-tree-node__content) {
  background: var(--el-color-primary-light-9, #e8f3ff);
  color: var(--el-color-primary);
  box-shadow: inset 3px 0 0 var(--el-color-primary);
}

.emp-tree-body :deep(.el-tree-node.is-current > .el-tree-node__content .emp-tree-node__name) {
  color: var(--el-color-primary);
  font-weight: 600;
}

.emp-tree-body :deep(.el-tree-node__expand-icon) {
  padding: 0 2px;
  font-size: 12px;
  color: #909399;
}

/* ── 树节点内容 ── */
.emp-tree-node {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  flex: 1;
  height: 36px;
}

.emp-tree-node__icon {
  font-size: 16px;
  color: #a0a6b0;
  flex-shrink: 0;
}

.emp-tree-node__icon.is-open {
  color: var(--el-color-primary);
}

.emp-tree-node__text {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.emp-tree-node__name {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--el-text-color-primary, #303133);
}

.emp-tree-node__leader {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 400;
  color: #909399;
}

.emp-tree-body :deep(.el-tree-node.is-current > .el-tree-node__content .emp-tree-node__leader) {
  color: #909399;
  font-weight: 400;
}

/* 人数徽章：圆角、右对齐 */
.emp-tree-node__badge {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 12px;
  line-height: 18px;
  color: #6b7280;
  padding: 0 2px;
  text-align: center;
}

.emp-tree-body :deep(.el-tree-node.is-current) .emp-tree-node__badge {
  color: var(--el-color-primary);
}

.emp-tree-node__ops {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
}

.emp-more-button {
  min-width: 22px;
  height: 22px;
  padding: 0 2px;
  border: none;
  background: transparent;
  color: var(--el-text-color-regular, #606266);
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 1px;
  line-height: 1;
  cursor: pointer;
  border-radius: 4px;
}

.emp-more-button:hover {
  color: var(--el-color-primary);
  background: var(--el-fill-color-light, #f5f7fa);
}

.emp-photo-cell {
  display: grid;
  width: 44px;
  height: 44px;
  margin: 0 auto;
  place-items: center;
  border: 1px dashed var(--el-border-color);
  border-radius: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  cursor: pointer;
  overflow: hidden;
  background: var(--el-fill-color-blank);
}

.emp-photo-cell.is-dragging {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}

.emp-photo-cell.is-uploading {
  opacity: 0.6;
}

.emp-id-photo-pair {
  display: flex;
  gap: 6px;
  align-items: flex-start;
  justify-content: center;
}

.emp-id-caption {
  margin-bottom: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1;
}

.emp-photo-cell--id {
  width: 72px;
  height: 46px;
  margin: 0;
}

.emp-photo-thumb {
  width: 44px;
  height: 44px;
}

.emp-id-photo-thumb {
  width: 72px;
  height: 46px;
}

.emp-photo-thumb :deep(img),
.emp-id-photo-thumb :deep(img),
.emp-photo-preview :deep(img),
.emp-id-photo-preview :deep(img) {
  -webkit-user-drag: none;
}

.emp-photo-drop {
  position: relative;
  display: grid;
  width: 148px;
  min-height: 96px;
  place-items: center;
  padding: 8px;
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.4;
  text-align: center;
  cursor: pointer;
  background: var(--el-fill-color-blank);
}

.emp-photo-drop.is-dragging {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}

.emp-photo-drop.is-uploading {
  opacity: 0.7;
}

.emp-photo-preview {
  width: 120px;
  height: 80px;
  border-radius: 6px;
}

.emp-id-photo-drop {
  width: 200px;
  min-height: 120px;
}

.emp-id-photo-preview {
  width: 180px;
  height: 112px;
  border-radius: 6px;
}

.emp-photo-remove {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 20px;
  height: 20px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: #d33;
  color: #fff;
  line-height: 20px;
  cursor: pointer;
}

.emp-list-panel {
  flex: 1;
  min-width: 0;
  min-height: 0;
  padding: 12px;
  display: flex;
  flex-direction: column;
}

.emp-list-panel :deep(.el-table th.el-table__cell) {
  padding: 6px 0;
}

.emp-list-panel :deep(.el-table th.el-table__cell .cell) {
  line-height: 1.25;
}

.emp-team-strip {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin: -4px 0 10px;
  flex-shrink: 0;
}

.emp-team-strip__hint {
  font-size: 12px;
}

.emp-team-chip {
  border: 1px solid var(--el-border-color-lighter, #e4e7ed);
  border-radius: 16px;
  background: #fff;
  padding: 4px 12px;
  font-size: 13px;
  line-height: 20px;
  color: var(--el-text-color-primary, #303133);
  cursor: pointer;
}

.emp-team-chip:hover {
  border-color: var(--el-color-primary-light-5, #a0cfff);
}

.emp-team-chip.is-current {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9, #e8f3ff);
  color: var(--el-color-primary);
  font-weight: 600;
}

.emp-team-chip__mark {
  margin-left: 4px;
  font-size: 11px;
  font-weight: 500;
  opacity: 0.75;
}

/* ── 班组详情（右侧选中班组时） ── */
.team-detail {
  padding: 8px 4px;
}

.team-detail-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.team-detail-head h3 {
  margin: 0;
}

.team-detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}

.team-detail-item span {
  display: block;
  font-size: 12px;
}

.team-detail-item b {
  font-size: 14px;
}

.team-member-list {
  margin-top: 16px;
}

.section-label {
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}
</style>
