<!-- FormDesignerPanel.vue — Form Builder 3 列布局 (design-v4 Phase A).

  2026-05-26 大下 session: 从 446 行 table 视图重写成 builder 视图, 跟 Claude
  design 截图对齐. 命名保留 FormDesignerPanel 防 ChatPage import 扩散, 内部
  实现已升级为 builder 范式 (3 col: 组件库 / 预览 canvas / 字段属性).

  布局:
    +--------+-------------------------+---------+
    | 组件库 |   表单 preview canvas    | 属性面板 |
    | 200px  |   flex: 1                | 280px   |
    +--------+-------------------------+---------+

  数据源: list_apaas_app_models with_fields=true (复用现有 endpoint).
  写回 backend: P2 — 当前拖排/编辑/新增字段仅 local state, 提示走配置助手.

  Props 跟旧版兼容 (appId/menuId/menuName/formId).
-->
<template>
  <section class="fbp" aria-label="表单设计器">
    <!-- 空态 1: 未选菜单 -->
    <div v-if="!menuId" class="fbp-empty">
      <div class="fbp-empty-icon">📝</div>
      <h3>选择一个表单</h3>
      <p>从左侧菜单列表点击某个表单, 这里显该表单的字段设计.</p>
    </div>

    <!-- 空态 2: 加载中 -->
    <div v-else-if="loading" class="fbp-state">
      <div class="fbp-spinner" />
      加载字段…
    </div>

    <!-- 空态 3: 错误 -->
    <div v-else-if="error" class="fbp-state fbp-state-err">
      <div class="fbp-state-icon">⚠️</div>
      <p>{{ error }}</p>
      <button class="fbp-btn fbp-btn-ghost" @click="reload">重试</button>
    </div>

    <!-- 3 列 builder (preview mode 只显中央 canvas, edit mode 显 3 列) -->
    <div v-else class="fbp-3col" :class="{ 'preview-mode': viewMode === 'preview' }">
      <!-- ─── 左: 组件库 (2 tab: 数据模型 / 业务组件) ─────── -->
      <aside v-show="viewMode === 'edit'" class="fbp-lib" aria-label="组件库">
        <div class="fbp-lib-tabs" role="tablist">
          <button
            class="fbp-lib-tab"
            :class="{ active: libTab === 'model' }"
            role="tab"
            :aria-selected="libTab === 'model'"
            @click="libTab = 'model'"
          >
            数据模型
          </button>
          <button
            class="fbp-lib-tab"
            :class="{ active: libTab === 'component' }"
            role="tab"
            :aria-selected="libTab === 'component'"
            @click="libTab = 'component'"
          >
            业务组件
          </button>
        </div>

        <!-- 业务组件 tab -->
        <template v-if="libTab === 'component'">
          <div class="fbp-lib-head">
            <div class="fbp-lib-search">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>
              </svg>
              <input v-model="libSearchKw" placeholder="搜索组件" />
            </div>
          </div>
          <div class="fbp-lib-body">
            <div
              v-for="cat in filteredCategories"
              :key="cat.code"
              class="fbp-lib-cat"
            >
              <button
                class="fbp-lib-cat-head"
                :aria-expanded="!collapsedCats[cat.code]"
                @click="toggleCat(cat.code)"
              >
                <svg
                  class="fbp-lib-cat-caret"
                  :class="{ collapsed: collapsedCats[cat.code] }"
                  width="10" height="10" viewBox="0 0 24 24"
                  fill="none" stroke="currentColor" stroke-width="2.5"
                >
                  <polyline points="6 9 12 15 18 9"/>
                </svg>
                <span class="fbp-lib-cat-bar" />
                <span>{{ cat.label }}</span>
                <span class="fbp-lib-cat-count">{{ cat.widgets.length }}</span>
              </button>
              <draggable
                v-show="!collapsedCats[cat.code]"
                :model-value="cat.widgets"
                :group="{ name: 'form-fields', pull: 'clone', put: false }"
                :sort="false"
                :clone="cloneWidgetToField"
                item-key="type"
                class="fbp-lib-chips"
                tag="div"
              >
                <template #item="{ element: w }">
                  <button
                    class="fbp-lib-chip fbp-lib-chip-draggable"
                    :title="`点击或拖入 canvas — ${w.label}`"
                    @click="onAddWidget(w)"
                  >
                    <span class="fbp-lib-chip-icon">{{ w.icon }}</span>
                    <span class="fbp-lib-chip-label">{{ w.label }}</span>
                  </button>
                </template>
              </draggable>
            </div>
          </div>
        </template>

        <!-- 数据模型 tab -->
        <template v-else>
          <div class="fbp-lib-head">
            <div class="fbp-lib-search">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>
              </svg>
              <input v-model="libSearchKw" placeholder="输入模型名称" />
            </div>
          </div>
          <div class="fbp-lib-body fbp-lib-model-body">
            <button class="fbp-lib-model-add" disabled title="P2 接入: 走配置助手对话">
              <span>+ </span><span>添加数据模型</span>
              <span class="fbp-lib-help">?</span>
            </button>
            <div class="fbp-lib-model-list">
              <button
                v-for="m in filteredModels"
                :key="m.id || m.extra?.model_id"
                class="fbp-lib-model-item"
                :class="{ active: String(m.id || m.extra?.model_id) === selectedLibModelId }"
                @click="selectedLibModelId = String(m.id || m.extra?.model_id || '')"
              >
                <span class="fbp-lib-model-icon">主</span>
                <span class="fbp-lib-model-name">{{ m.name }}</span>
              </button>
              <div v-if="filteredModels.length === 0" class="fbp-lib-empty">
                <span v-if="libSearchKw">无匹配模型</span>
                <span v-else>该应用暂无数据模型</span>
              </div>
            </div>

            <!-- 选中 model 的已使用字段 -->
            <div v-if="selectedLibModel" class="fbp-lib-model-detail">
              <div class="fbp-lib-model-detail-head">
                <span class="fbp-lib-model-detail-bar" />
                <div class="fbp-lib-model-detail-info">
                  <span class="fbp-lib-model-detail-name">{{ selectedLibModel.name }}</span>
                  <span class="fbp-lib-model-detail-code mono">{{ selectedLibModel.code }}</span>
                </div>
              </div>
              <div class="fbp-lib-model-detail-section">
                <button class="fbp-lib-model-detail-toggle" @click="modelFieldsCollapsed = !modelFieldsCollapsed">
                  <span>已使用组件</span>
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
                       :style="{ transform: modelFieldsCollapsed ? 'rotate(-90deg)' : 'rotate(0)' }">
                    <polyline points="6 9 12 15 18 9"/>
                  </svg>
                </button>
                <draggable
                  v-show="!modelFieldsCollapsed"
                  :model-value="selectedLibModelFields"
                  :group="{ name: 'form-fields', pull: 'clone', put: false }"
                  :sort="false"
                  :clone="cloneModelFieldToField"
                  item-key="field_code"
                  class="fbp-lib-chips fbp-lib-chips-model"
                  tag="div"
                >
                  <template #item="{ element: f }">
                    <button
                      class="fbp-lib-chip fbp-lib-chip-draggable"
                      :title="`点击或拖入 canvas — ${f.field_name} - ${f.field_code}`"
                      @click="onAddExistingField(f)"
                    >
                      <span class="fbp-lib-chip-icon">T</span>
                      <span class="fbp-lib-chip-label">{{ f.field_name || f.field_code }}</span>
                    </button>
                  </template>
                </draggable>
                <div
                  v-if="!modelFieldsCollapsed && selectedLibModelFields.length === 0"
                  class="fbp-lib-empty fbp-lib-empty-sm"
                >
                  该模型暂无字段
                </div>
              </div>
            </div>
          </div>
        </template>
      </aside>

      <!-- ─── 中: 预览 canvas ─────────────────────────────── -->
      <main class="fbp-canvas" :class="{ 'viewport-mobile': canvasViewport === 'mobile' }" aria-label="表单预览">
        <header class="fbp-canvas-head">
          <div class="fbp-canvas-meta">
            <h1 class="fbp-canvas-title">{{ menuName || '表单设计' }}</h1>
            <p class="fbp-canvas-sub">
              <span v-if="modelCode" class="fbp-code mono">{{ modelCode }}</span>
              <span class="fbp-canvas-stat">{{ fields.length }} 字段</span>
              <span v-if="fields.filter(f => f.required).length" class="fbp-canvas-stat">
                {{ fields.filter(f => f.required).length }} 必填
              </span>
            </p>
          </div>
          <div class="fbp-canvas-actions">
            <!-- O2-Form: view/edit mode segmented toggle (default preview, 跟产品"业务视角"对齐) -->
            <div class="fbp-mode-toggle" role="group" aria-label="切换视图模式">
              <button
                class="fbp-mode-btn"
                :class="{ active: viewMode === 'preview' }"
                title="业务视角 — 看真表单"
                @click="viewMode = 'preview'"
              >
                <span aria-hidden="true">👁</span> 预览
              </button>
              <button
                class="fbp-mode-btn"
                :class="{ active: viewMode === 'edit' }"
                title="配置视角 — 字段卡片 + 拖排"
                @click="viewMode = 'edit'"
              >
                <span aria-hidden="true">✏️</span> 编辑
              </button>
            </div>
            <!-- preview mode 显"用对话改"CTA, edit mode 显原 AI 助手 -->
            <button
              v-if="viewMode === 'preview'"
              class="fbp-btn fbp-btn-ghost"
              title="改字段请用配置助手对话, 比如 '把 ISBN 改成必填'"
              @click="onOpenConfigAssistant"
            >
              <span class="fbp-btn-icon">✨</span> 用对话改
            </button>
            <button v-else class="fbp-btn fbp-btn-ghost" @click="showAiHelper = !showAiHelper">
              <span class="fbp-btn-icon">✨</span> AI 助手
            </button>
            <button
              class="fbp-btn fbp-btn-primary fbp-btn-save"
              :class="{ 'has-dirty': saveCounts.total > 0, saving }"
              :disabled="saving"
              @click="onSaveForm"
            >
              <span v-if="saving" class="fbp-btn-spinner" />
              <span v-if="saving">保存中…</span>
              <span v-else-if="saveCounts.total > 0">保存 ({{ saveCounts.total }})</span>
              <span v-else>保存</span>
            </button>
          </div>
        </header>

        <!-- O2-Form: preview mode banner — 提示业务视角 -->
        <div v-if="viewMode === 'preview'" class="fbp-preview-banner">
          <span class="fbp-preview-banner-icon" aria-hidden="true">✨</span>
          <span>业务视角预览 — 看到的就是最终用户填表样子, 改字段请用配置助手对话</span>
        </div>

        <!-- 保存进度提示 (saving 时显) -->
        <div v-if="saving && saveProgress" class="fbp-save-progress">
          <div class="fbp-spinner fbp-save-progress-spin" />
          <span class="fbp-save-progress-text">
            保存中 {{ saveProgress.done + 1 }} / {{ saveProgress.total }} —
            <span class="fbp-save-progress-current">{{ saveProgress.current }}</span>
          </span>
          <div class="fbp-save-progress-bar">
            <div
              class="fbp-save-progress-fill"
              :style="{ width: `${Math.min(100, (saveProgress.done / Math.max(1, saveProgress.total)) * 100)}%` }"
            />
          </div>
        </div>

        <!-- canvas toolbar (跟 apaas 原生一致: 查看业务对象 / PC-Mobile / 表单设置) — 仅 edit mode -->
        <div v-if="viewMode === 'edit'" class="fbp-canvas-toolbar">
          <button
            class="fbp-toolbar-btn fbp-toolbar-btn-outline"
            disabled
            title="P2 接入"
          >
            查看业务对象
          </button>
          <div class="fbp-toolbar-viewport">
            <button
              class="fbp-toolbar-vp"
              :class="{ active: canvasViewport === 'pc' }"
              title="桌面视图"
              @click="canvasViewport = 'pc'; canvasLayout = '2col'"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="2" y="3" width="20" height="14" rx="2"/>
                <path d="M8 21h8M12 17v4"/>
              </svg>
            </button>
            <button
              class="fbp-toolbar-vp"
              :class="{ active: canvasViewport === 'mobile' }"
              title="移动视图"
              @click="canvasViewport = 'mobile'; canvasLayout = '1col'"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="6" y="2" width="12" height="20" rx="2"/>
                <line x1="12" y1="18" x2="12" y2="18"/>
              </svg>
            </button>
          </div>
          <button
            class="fbp-toolbar-btn"
            disabled
            title="P2 接入"
          >
            表单设置
          </button>
        </div>

        <div class="fbp-canvas-body" :class="{ 'fbp-canvas-body-preview': viewMode === 'preview' }">
          <!-- ─── O2-Form: preview mode 真业务表单 ───────────────────── -->
          <div v-if="viewMode === 'preview'" class="fbp-form-preview">
            <div class="fbp-form-preview-head">
              <h2 class="fbp-form-preview-title">{{ menuName || '表单' }}</h2>
              <p class="fbp-form-preview-sub">
                <span v-if="modelCode" class="fbp-code mono">{{ modelCode }}</span>
                <span>{{ fields.length }} 字段</span>
              </p>
            </div>
            <div v-if="fields.length === 0" class="fbp-form-preview-empty">
              <div class="fbp-canvas-empty-icon">🧩</div>
              <p>该表单暂无字段</p>
              <p class="hint">切到"编辑"模式从组件库添加, 或用配置助手对话生成</p>
            </div>
            <form v-else class="fbp-form-preview-grid" @submit.prevent="onPreviewSubmit">
              <div
                v-for="f in fields"
                :key="f.id"
                class="fbp-form-row"
                :class="{ 'fbp-form-row-full': isFullWidthWidget(f.type) }"
                @mouseenter="hoveredFieldId = f.id"
                @mouseleave="hoveredFieldId = ''"
              >
                <label class="fbp-form-label">
                  {{ f.name || '未命名字段' }}
                  <span v-if="f.required" class="fbp-form-req">*</span>
                  <button
                    v-if="hoveredFieldId === f.id"
                    type="button"
                    class="fbp-form-edit-hint"
                    title="改字段请用配置助手对话"
                    @click="onInlineEditHint(f)"
                  >改这个字段 →</button>
                </label>
                <FormPreviewInput :field="f" :model-value="formValues[f.code]" @update:model-value="(v: any) => formValues[f.code] = v" />
                <p v-if="f.description" class="fbp-form-desc">{{ f.description }}</p>
              </div>
              <div class="fbp-form-actions">
                <button type="button" class="fbp-btn fbp-btn-ghost" @click="onPreviewCancel">取消</button>
                <button type="submit" class="fbp-btn fbp-btn-primary">
                  <span aria-hidden="true">✓</span> 提交申请
                </button>
              </div>
            </form>
          </div>

          <!-- ─── edit mode: 原 builder 卡片 list (G1/F3 真存追踪) ────── -->
          <draggable
            v-else
            v-model="fields"
            item-key="id"
            :group="{ name: 'form-fields', pull: false, put: true }"
            handle=".fbp-card-handle"
            ghost-class="fbp-card-ghost"
            chosen-class="fbp-card-chosen"
            drag-class="fbp-card-drag"
            animation="180"
            class="fbp-card-list"
            :class="{
              'fbp-card-list-1col': canvasLayout === '1col',
              'fbp-card-list-empty': fields.length === 0,
            }"
            @change="onFieldsChange"
          >
            <template v-if="fields.length === 0" #header>
              <div class="fbp-canvas-empty">
                <div class="fbp-canvas-empty-icon">🧩</div>
                <p>该表单暂无字段</p>
                <p class="hint">从左侧组件库点击或拖入字段</p>
              </div>
            </template>
            <template #item="{ element: f, index: i }">
              <div
                class="fbp-card"
                :class="{
                  active: selectedFieldId === f.id,
                  'fbp-card-fullwidth': isFullWidthWidget(f.type),
                  'fbp-card-pending': f._pending,
                  'fbp-card-dirty': !f._pending && isFieldDirtyVsOriginal(f),
                  'fbp-card-saving': f._saving,
                }"
                @click="onSelectField(f.id)"
              >
                <div class="fbp-card-handle" title="拖动排序">
                  <svg width="10" height="14" viewBox="0 0 6 10" fill="currentColor">
                    <circle cx="1.5" cy="1.5" r="0.9"/>
                    <circle cx="4.5" cy="1.5" r="0.9"/>
                    <circle cx="1.5" cy="5" r="0.9"/>
                    <circle cx="4.5" cy="5" r="0.9"/>
                    <circle cx="1.5" cy="8.5" r="0.9"/>
                    <circle cx="4.5" cy="8.5" r="0.9"/>
                  </svg>
                </div>
                <div class="fbp-card-body">
                  <div class="fbp-card-label">
                    <span class="fbp-card-name">{{ f.name || '未命名字段' }}</span>
                    <span v-if="f.required" class="fbp-card-req">*</span>
                    <span class="fbp-card-type-chip">{{ widgetLabel(f.type) }}</span>
                    <span class="fbp-card-key mono">{{ f.code }}</span>
                    <span v-if="f._pending" class="fbp-card-badge fbp-card-badge-pending">● 未保存</span>
                    <span v-else-if="!f._pending && isFieldDirtyVsOriginal(f)" class="fbp-card-badge fbp-card-badge-dirty" title="已改, 未保存"></span>
                  </div>
                  <div class="fbp-card-preview">
                    <FieldPreview :field="f" />
                  </div>
                </div>
                <div class="fbp-card-ops" @click.stop>
                  <button
                    class="fbp-icon-btn"
                    :title="f._pending ? '删除字段 (本地)' : '删除字段 (apaas 软删)'"
                    :disabled="saving"
                    @click="onRemoveField(f.id)"
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="3 6 5 6 21 6"/>
                      <path d="M19 6l-2 14a2 2 0 01-2 2H9a2 2 0 01-2-2L5 6"/>
                      <path d="M10 11v6M14 11v6"/>
                    </svg>
                  </button>
                </div>
                <div v-if="f._saving" class="fbp-card-saving-overlay">
                  <div class="fbp-spinner" />
                </div>
              </div>
            </template>
          </draggable>

          <div v-if="viewMode === 'edit'" class="fbp-canvas-drop">
            <span class="fbp-canvas-drop-icon">+</span>
            <span>从左侧组件库点击或拖入字段 · 或</span>
            <button class="fbp-link-btn" @click="showAiHelper = true">让 AI 添加</button>
          </div>
        </div>

        <!-- AI 助手 inline (右下角浮起) -->
        <transition name="fbp-fade">
          <div v-if="showAiHelper" class="fbp-ai">
            <div class="fbp-ai-head">
              <span class="fbp-ai-title">✨ AI 助手</span>
              <button class="fbp-ai-close" @click="showAiHelper = false">×</button>
            </div>
            <div class="fbp-ai-chips">
              <button class="fbp-ai-chip" @click="onAiPrompt('分析当前表单')">分析当前表单</button>
              <button class="fbp-ai-chip" @click="onAiPrompt('帮我添加常用字段')">添加字段</button>
              <button class="fbp-ai-chip" @click="onAiPrompt('生成 5 条测试数据')">生成测试数据</button>
            </div>
            <div class="fbp-ai-tips">
              <p>试试问:</p>
              <ul>
                <li>"加一个金额字段, 必填, 最大 50000"</li>
                <li>"把字段按使用频率排序"</li>
                <li>"给请假类型加 5 个选项"</li>
              </ul>
            </div>
            <div class="fbp-ai-input">
              <input v-model="aiPrompt" placeholder="问 AI 帮你改表单…" @keyup.enter="onAiSubmit" />
              <button class="fbp-btn fbp-btn-primary fbp-btn-sm" @click="onAiSubmit">发送</button>
            </div>
          </div>
        </transition>
      </main>

      <!-- ─── 右: 字段属性面板 (preview mode 隐藏) ────────────── -->
      <aside v-show="viewMode === 'edit'" class="fbp-props" aria-label="字段属性">
        <div v-if="!selectedField" class="fbp-props-empty">
          <div class="fbp-props-empty-icon">👈</div>
          <p>选中一个字段查看属性</p>
          <p class="hint">点击中央 canvas 任意字段卡</p>
        </div>
        <template v-else>
          <div class="fbp-props-head">
            <span class="fbp-card-type-chip">{{ widgetLabel(selectedField.type) }}</span>
            <span class="fbp-props-title">字段属性</span>
          </div>
          <div class="fbp-props-body">
            <div class="fbp-row">
              <label>标题名称</label>
              <input v-model="selectedField.name" placeholder="如 请假类型" />
            </div>
            <div class="fbp-row">
              <label>字段 Key</label>
              <input v-model="selectedField.code" class="mono" placeholder="如 leave_type" />
            </div>
            <div class="fbp-row">
              <label>组件类型</label>
              <select v-model="selectedField.type">
                <optgroup v-for="cat in FIELD_CATEGORIES" :key="cat.code" :label="cat.label">
                  <option v-for="w in cat.widgets" :key="w.type" :value="w.type">{{ w.label }}</option>
                </optgroup>
              </select>
            </div>
            <div v-if="modelCode" class="fbp-row">
              <label>数据模型</label>
              <input :value="modelCode" class="mono" readonly disabled />
            </div>
            <div v-if="selectedField._src?._model_field" class="fbp-row">
              <label>模型字段</label>
              <input
                :value="`${selectedField._src._model_field.field_name}-${selectedField._src._model_field.field_code}`"
                readonly
                disabled
              />
            </div>
            <div class="fbp-row">
              <label>标题说明</label>
              <textarea v-model="selectedField.description" placeholder="请输入" rows="2" class="fbp-row-textarea" />
            </div>
            <div class="fbp-row">
              <label>提示文字</label>
              <input v-model="selectedField.placeholder" placeholder="请输入" />
            </div>
            <div v-if="hasMaxLength(selectedField.type)" class="fbp-row">
              <label>长度限制</label>
              <input v-model.number="selectedField.max_length" type="number" placeholder="200" min="0" />
            </div>
            <div class="fbp-switch-grid">
              <div class="fbp-switch-row">
                <span>必填</span>
                <button
                  class="fbp-switch"
                  :class="{ on: selectedField.required }"
                  @click="selectedField.required = !selectedField.required"
                >
                  <span class="fbp-switch-knob" />
                </button>
              </div>
              <div class="fbp-switch-row">
                <span>可编辑</span>
                <button
                  class="fbp-switch"
                  :class="{ on: selectedField.editable }"
                  @click="selectedField.editable = !selectedField.editable"
                >
                  <span class="fbp-switch-knob" />
                </button>
              </div>
              <div class="fbp-switch-row">
                <span>AI 校验</span>
                <button
                  class="fbp-switch"
                  :class="{ on: selectedField.ai_validate }"
                  @click="selectedField.ai_validate = !selectedField.ai_validate"
                >
                  <span class="fbp-switch-knob" />
                </button>
              </div>
            </div>

            <!-- select/radio 类型显选项 list -->
            <div v-if="needsOptions(selectedField.type)" class="fbp-options">
              <div class="fbp-options-head">
                <label>选项 ({{ (selectedField.options || []).length }})</label>
                <button class="fbp-link-btn fbp-link-btn-sm" @click="onAddOption">+ 新增</button>
              </div>
              <div class="fbp-options-list">
                <div
                  v-for="(opt, i) in (selectedField.options || [])"
                  :key="i"
                  class="fbp-option-row"
                >
                  <input
                    v-model="opt.name"
                    placeholder="显示名"
                    class="fbp-option-input"
                  />
                  <input
                    v-model="opt.code"
                    placeholder="value"
                    class="fbp-option-input mono"
                  />
                  <button class="fbp-icon-btn" @click="onRemoveOption(i)" title="删除选项">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <line x1="18" y1="6" x2="6" y2="18"/>
                      <line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                  </button>
                </div>
              </div>
              <div v-if="!(selectedField.options || []).length" class="fbp-options-empty">
                无选项. 点击"+ 新增"添加.
              </div>
            </div>

            <!-- AI prompt -->
            <div class="fbp-row fbp-row-ai">
              <label>问 AI</label>
              <input
                v-model="propsAiPrompt"
                placeholder="如: 把字段按使用频率排序"
                @keyup.enter="onPropsAiSubmit"
              />
            </div>
          </div>
        </template>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch, h, type PropType } from 'vue'
import draggable from 'vuedraggable'
import request from '@/utils/request'

/* ────────────────────────────────────────────────────────────────
   类型定义 + 注册表
   ──────────────────────────────────────────────────────────────── */

// 2026-05-26 设计 v4 对齐 apaas 38 组件 (3 分类) — 用宽松 string 避免 38 个 union
// 维护负担, 关键类型在 FIELD_CATEGORIES + COMPONENT_TYPE_MAP 里登记.
type FieldType = string

interface FieldOption {
  code: string
  name: string
}

interface FormField {
  id: string
  code: string
  name: string
  type: FieldType
  placeholder?: string
  required: boolean
  editable: boolean
  ai_validate: boolean
  options?: FieldOption[]
  // apaas 额外属性 (跟低代码原生表单设计 一致)
  description?: string   // 标题说明
  hint?: string          // 提示文字 (placeholder 别名 — apaas 用 "提示文字")
  max_length?: number    // 长度限制 (text/textarea/phone/idcard/email)
  _src?: any
  // 2026-05-26 G1 真存追踪
  _pending?: boolean     // 新加未保存 (走 add endpoint)
  _dirty?: boolean       // 已存但属性改过 (走 update endpoint)
  _saving?: boolean      // 保存中 (loading overlay)
  _model_id?: string     // apaas model_id (update/disable endpoint 必填)
  _model_code?: string   // apaas model_code (add endpoint 必填)
  _field_id?: string     // apaas field_id (update/disable endpoint 必填; pending 为空)
  _original?: {          // initial snapshot (dirty diff 用)
    code: string
    name: string
    type: FieldType
    required: boolean
    max_length?: number
    description?: string
    placeholder?: string
  }
}

interface WidgetMeta {
  type: FieldType
  label: string
  icon: string
}

interface WidgetCategory {
  code: string
  label: string
  widgets: WidgetMeta[]
}

// 2026-05-26 设计 v4: 完全对齐 得帆云 aPaaS 业务组件 list (38 组件 3 类).
// 不再用我们自己的 5 分类 — apaas 表单设计器超出此范围的 widget 没法存. 业务组件
// type code 直接跟 apaas component_type 对应 (FORM_TEXT_INPUT → text 等).
const FIELD_CATEGORIES: WidgetCategory[] = [
  {
    code: 'common',
    label: '常用组件',
    widgets: [
      { type: 'text', label: '单行输入', icon: 'T' },
      { type: 'textarea', label: '多行输入', icon: '¶' },
      { type: 'number', label: '数字输入', icon: '#' },
      { type: 'datetime', label: '日期时间', icon: '📅' },
      { type: 'user', label: '人员选择', icon: '👤' },
      { type: 'dept', label: '部门选择', icon: '🏢' },
      { type: 'phone', label: '手机号码', icon: '📞' },
      { type: 'email', label: '电子邮箱', icon: '✉' },
      { type: 'idcard', label: '证件号', icon: '🆔' },
      { type: 'radio', label: '单选框', icon: '◉' },
      { type: 'multi_select', label: '多选框', icon: '☑' },
      { type: 'select', label: '下拉框', icon: '▾' },
      { type: 'select_single', label: '下拉单选', icon: '✓' },
      { type: 'money', label: '金额', icon: '¥' },
      { type: 'file', label: '附件上传', icon: '📎' },
      { type: 'richtext', label: '富文本', icon: '§' },
      { type: 'region', label: '地区地址', icon: '🚏' },
      { type: 'location', label: '定位', icon: '📍' },
      { type: 'hyperlink', label: '超链接', icon: '🔗' },
      { type: 'switch', label: '开关', icon: '⊙' },
    ],
  },
  {
    code: 'advanced',
    label: '高级组件',
    widgets: [
      { type: 'serial_no', label: '单据号', icon: 'N°' },
      { type: 'data_select', label: '数据选择', icon: '⊟' },
      { type: 'data_single', label: '数据单选', icon: '⊡' },
      { type: 'ref_form', label: '关联表单', icon: '↗' },
      { type: 'data_stat', label: '数据统计', icon: 'N' },
      { type: 'cross_field', label: '他表字段', icon: 'T?' },
      { type: 'form_button', label: '表单按钮', icon: '⊏' },
      { type: 'subtable', label: '子表', icon: '⊞' },
      { type: 'virtual_field', label: '虚拟字段', icon: 'V' },
      { type: 'custom_dev', label: '自开发字段', icon: '</>' },
    ],
  },
  {
    code: 'layout',
    label: '页面布局组件',
    widgets: [
      { type: 'static_text', label: '静态文本', icon: 'Aa' },
      { type: 'static_image', label: '静态图片', icon: '🖼' },
      { type: 'divider', label: '分隔符', icon: '━' },
      { type: 'placeholder', label: '占位符', icon: '□' },
      { type: 'collapse_layout', label: '折叠布局', icon: '⊟' },
      { type: 'tab_layout', label: '分页布局', icon: '▤' },
      { type: 'frame_layout', label: '框架布局', icon: '⊑' },
      { type: 'template_file', label: '模板文件', icon: '📋' },
    ],
  },
]

const WIDGET_LABEL_MAP: Record<string, string> = Object.fromEntries(
  FIELD_CATEGORIES.flatMap(c => c.widgets.map(w => [w.type, w.label]))
)

function widgetLabel(t: FieldType | string): string {
  return WIDGET_LABEL_MAP[t] || t
}

function needsOptions(t: FieldType): boolean {
  return ['select', 'select_multi', 'radio', 'multi_select', 'tag', 'select_single'].includes(t)
}

const HAS_MAX_LENGTH = new Set<string>([
  'text', 'textarea', 'richtext', 'phone', 'email', 'idcard', 'hyperlink', 'serial_no', 'region',
])
function hasMaxLength(t: string): boolean {
  return HAS_MAX_LENGTH.has(t)
}

/* ────────────────────────────────────────────────────────────────
   Backend ↔ Builder field mapping
   ──────────────────────────────────────────────────────────────── */

// apaas form_components.component_type → 我们 widget type 映射 (form_id 路径).
// 真实 component_type 取值 (从 /xdap-app/formComponent/query 抓的实际返回 + 推测):
const COMPONENT_TYPE_MAP: Record<string, FieldType> = {
  // 输入
  FORM_TEXT_INPUT: 'text',
  FORM_INPUT: 'text',
  FORM_TEXTAREA_INPUT: 'textarea',
  FORM_TEXTAREA: 'textarea',
  FORM_NUMBER_INPUT: 'number',
  FORM_NUMBER: 'number',
  FORM_AMOUNT_INPUT: 'money',
  FORM_AMOUNT: 'money',
  FORM_RICH_TEXT_INPUT: 'richtext',
  FORM_RICH_TEXT: 'richtext',
  FORM_PHONE_INPUT: 'phone',
  FORM_PHONE: 'phone',
  FORM_MOBILE: 'phone',
  FORM_EMAIL_INPUT: 'email',
  FORM_EMAIL: 'email',
  FORM_IDCARD_INPUT: 'idcard',
  FORM_IDCARD: 'idcard',
  // 日期
  FORM_DATEPICK_INPUT: 'datetime',
  FORM_DATEPICK: 'datetime',
  FORM_DATE_INPUT: 'datetime',
  FORM_DATETIME: 'datetime',
  FORM_DATE: 'datetime',
  FORM_TIME_INPUT: 'datetime',
  // 选择
  FORM_PEOPLE_SELECT: 'user',
  FORM_PEOPLE: 'user',
  FORM_USER_SELECT: 'user',
  FORM_DEPT_SELECT: 'dept',
  FORM_DEPT: 'dept',
  FORM_DEPARTMENT_SELECT: 'dept',
  FORM_RADIO_GROUP: 'radio',
  FORM_RADIO: 'radio',
  FORM_CHECKBOX_GROUP: 'multi_select',
  FORM_CHECKBOX: 'multi_select',
  FORM_SELECT_BOX: 'select',
  FORM_SELECT: 'select',
  FORM_DROPDOWN: 'select',
  FORM_DROPDOWN_SINGLE: 'select_single',
  FORM_SELECT_SINGLE: 'select_single',
  FORM_DICTIONARY: 'select',
  // 文件
  FORM_FILE_UPLOAD: 'file',
  FORM_FILE: 'file',
  FORM_ATTACHMENT: 'file',
  FORM_IMAGE_UPLOAD: 'static_image',
  FORM_IMAGE: 'static_image',
  // 其他常用
  FORM_REGION_ADDRESS: 'region',
  FORM_REGION: 'region',
  FORM_ADDRESS: 'region',
  FORM_LOCATION: 'location',
  FORM_HYPERLINK: 'hyperlink',
  FORM_LINK: 'hyperlink',
  FORM_SWITCH: 'switch',
  FORM_BOOLEAN: 'switch',
  // 高级
  FORM_DOCUMENT_NUMBER: 'serial_no',
  FORM_SERIAL_NO: 'serial_no',
  FORM_DATA_SELECT: 'data_select',
  FORM_DATA_SINGLE: 'data_single',
  FORM_DATA_SELECT_SINGLE: 'data_single',
  FORM_REF_FORM: 'ref_form',
  FORM_REFERENCE_FORM: 'ref_form',
  FORM_DATA_STAT: 'data_stat',
  FORM_DATA_STATISTICS: 'data_stat',
  FORM_CROSS_FIELD: 'cross_field',
  FORM_REFERENCE_FIELD: 'cross_field',
  FORM_BUTTON: 'form_button',
  FORM_SUBTABLE: 'subtable',
  FORM_SUB_TABLE: 'subtable',
  FORM_VIRTUAL_FIELD: 'virtual_field',
  FORM_CUSTOM_DEV: 'custom_dev',
  FORM_CUSTOM_DEVELOP: 'custom_dev',
  // 页面布局
  FORM_STATIC_TEXT: 'static_text',
  FORM_TEXT: 'static_text',
  FORM_STATIC_IMAGE: 'static_image',
  FORM_DIVIDER: 'divider',
  FORM_PLACEHOLDER: 'placeholder',
  FORM_COLLAPSE_LAYOUT: 'collapse_layout',
  FORM_TAB_LAYOUT: 'tab_layout',
  FORM_TABS: 'tab_layout',
  FORM_FRAME_LAYOUT: 'frame_layout',
  FORM_TEMPLATE_FILE: 'template_file',
}

function componentTypeToWidget(t: string | undefined): FieldType {
  if (!t) return 'text'
  const norm = String(t).toUpperCase().trim()
  return COMPONENT_TYPE_MAP[norm] || 'text'
}

// apaas 平台 dataType 可能 uppercase (STRING/BIG_TEXT/DATE/DICT_SINGLE) 或
// lowercase. 全 normalize 成 lowercase 后查 map. (Model 字段 fallback 路径用)
const BACKEND_TYPE_MAP: Record<string, FieldType> = {
  // 文本
  string: 'text', text: 'text', varchar: 'text', char: 'text',
  big_text: 'textarea', long_text: 'textarea', textarea: 'textarea', text_area: 'textarea',
  rich_text: 'richtext', richtext: 'richtext', html: 'richtext',
  // 数字
  integer: 'number', int: 'number', bigint: 'number', long: 'number',
  number: 'number', decimal: 'number', float: 'number', double: 'number',
  money: 'money', currency: 'money', amount: 'money',
  // 日期/时间
  date: 'date',
  datetime: 'datetime', date_time: 'datetime', timestamp: 'datetime',
  time: 'time',
  daterange: 'daterange', date_range: 'daterange',
  month: 'month',
  // 布尔
  boolean: 'switch', bool: 'switch', tinyint: 'switch',
  // 选择
  dict: 'dict', dict_single: 'select', dict_multi: 'select_multi',
  dictionary: 'dict', dictionary_single: 'select', dictionary_multi: 'select_multi',
  select: 'select', radio: 'radio', checkbox: 'multi_select',
  // 引用
  ref: 'ref', reference: 'ref', refer: 'ref',
  // 人员/组织
  user: 'user', employee: 'user', staff: 'user',
  dept: 'dept', department: 'dept', org: 'dept',
  role: 'role',
  // 文件
  file: 'file', attachment: 'file', upload: 'file',
  image: 'image', picture: 'image', img: 'image',
  // 其他
  json: 'textarea', object: 'textarea',
  color: 'color',
}

function backendTypeToWidget(t: string | undefined): FieldType {
  if (!t) return 'text'
  const norm = String(t).toLowerCase().replace(/_$/, '')
  return BACKEND_TYPE_MAP[norm] || 'text'
}

// 2026-05-26 G1: 反向 — widget type → apaas data_type (add/update model-field endpoint 用).
// backend `_AddFieldReq.field_type` 默 STRING, 取 STRING/NUM/DATE/DATETIME/BOOLEAN/TEXT/BIG_TEXT.
const WIDGET_TO_BACKEND_TYPE: Record<string, string> = {
  text: 'STRING',
  textarea: 'BIG_TEXT',
  richtext: 'BIG_TEXT',
  number: 'NUM',
  money: 'NUM',
  phone: 'STRING',
  email: 'STRING',
  idcard: 'STRING',
  date: 'DATE',
  datetime: 'DATETIME',
  time: 'DATETIME',
  switch: 'BOOLEAN',
  user: 'STRING',
  dept: 'STRING',
  radio: 'STRING',
  select: 'STRING',
  select_single: 'STRING',
  multi_select: 'STRING',
  select_multi: 'STRING',
  dict: 'STRING',
  hyperlink: 'STRING',
  region: 'STRING',
  location: 'STRING',
  serial_no: 'STRING',
  file: 'TEXT',
  // 高级/布局组件大多 form-only, 落到 model 时 fallback STRING
}
function widgetToBackendType(t: string): string {
  return WIDGET_TO_BACKEND_TYPE[t] || 'STRING'
}

// 2026-05-26 G1: 字段 snapshot (用于 dirty diff)
function snapshotField(f: FormField): NonNullable<FormField['_original']> {
  return {
    code: f.code,
    name: f.name,
    type: f.type,
    required: f.required,
    max_length: f.max_length,
    description: f.description,
    placeholder: f.placeholder,
  }
}

// 2026-05-26 G1: 字段是否真改了 (跟 _original snapshot 比)
function isFieldDirtyVsOriginal(f: FormField): boolean {
  if (f._pending) return false  // 新加未保存的不算 dirty (走 add 不走 update)
  const o = f._original
  if (!o) return false
  return (
    o.code !== f.code
    || o.name !== f.name
    || o.type !== f.type
    || o.required !== f.required
    || (o.max_length || 0) !== (f.max_length || 0)
    || (o.description || '') !== (f.description || '')
    || (o.placeholder || '') !== (f.placeholder || '')
  )
}

let _uidCounter = 0
function nextId(): string {
  _uidCounter += 1
  return `fb_${Date.now().toString(36)}_${_uidCounter}`
}

/* ────────────────────────────────────────────────────────────────
   Inline FieldPreview component — 字段卡片真实预览 widget
   ──────────────────────────────────────────────────────────────── */

const FieldPreview = {
  props: {
    field: { type: Object as PropType<FormField>, required: true },
  },
  setup(props: { field: FormField }) {
    return () => {
      const f = props.field
      const ph = f.placeholder || `请输入${f.name || '内容'}`
      const cls = 'fbp-pv-input'
      switch (f.type) {
        case 'textarea':
        case 'richtext':
          return h('textarea', { class: cls, placeholder: ph, rows: 2, readonly: true })
        case 'number':
        case 'money':
        case 'rating':
        case 'slider':
          return h('input', { class: cls, type: 'number', placeholder: ph, readonly: true })
        case 'switch':
          return h('div', { class: 'fbp-pv-switch' }, [
            h('span', { class: 'fbp-pv-switch-knob' }),
          ])
        case 'select':
        case 'dict':
        case 'cascade':
          return h('div', { class: 'fbp-pv-select' }, [
            h('span', { class: 'fbp-pv-select-text' }, ph),
            h('span', { class: 'fbp-pv-select-caret' }, '▾'),
          ])
        case 'select_multi':
        case 'multi_select':
        case 'tag': {
          const opts = (f.options || []).slice(0, 3)
          if (opts.length === 0) {
            return h('div', { class: 'fbp-pv-select' }, [
              h('span', { class: 'fbp-pv-select-text' }, '请选择…'),
              h('span', { class: 'fbp-pv-select-caret' }, '▾'),
            ])
          }
          return h('div', { class: 'fbp-pv-chips' }, opts.map(o =>
            h('span', { class: 'fbp-pv-chip' }, o.name || o.code)
          ))
        }
        case 'radio': {
          const opts = (f.options || []).slice(0, 3)
          if (opts.length === 0) {
            return h('div', { class: 'fbp-pv-radio' }, [
              h('span', { class: 'fbp-pv-radio-item' }, [h('span', { class: 'fbp-pv-radio-dot' }), '请选择']),
            ])
          }
          return h('div', { class: 'fbp-pv-radio' }, opts.map(o =>
            h('span', { class: 'fbp-pv-radio-item' }, [
              h('span', { class: 'fbp-pv-radio-dot' }),
              o.name || o.code,
            ])
          ))
        }
        case 'color':
          return h('div', { class: 'fbp-pv-color' }, [
            h('span', { class: 'fbp-pv-color-swatch', style: 'background:#3b82f6' }),
            h('span', { class: 'fbp-pv-select-text' }, '#3b82f6'),
          ])
        case 'date':
          return h('input', { class: cls, type: 'date', readonly: true })
        case 'time':
          return h('input', { class: cls, type: 'time', readonly: true })
        case 'datetime':
          return h('input', { class: cls, type: 'datetime-local', readonly: true })
        case 'daterange':
          return h('div', { class: 'fbp-pv-range' }, [
            h('input', { class: cls, type: 'date', readonly: true }),
            h('span', { class: 'fbp-pv-range-sep' }, '→'),
            h('input', { class: cls, type: 'date', readonly: true }),
          ])
        case 'month':
          return h('input', { class: cls, type: 'month', readonly: true })
        case 'user':
        case 'dept':
        case 'role':
          return h('div', { class: 'fbp-pv-pick' }, [
            h('span', { class: 'fbp-pv-avatar' }, f.type === 'user' ? '👤' : f.type === 'dept' ? '🏢' : '🛡'),
            h('span', { class: 'fbp-pv-select-text' }, ph),
          ])
        case 'image':
        case 'file':
          return h('div', { class: 'fbp-pv-upload' }, [
            h('span', { class: 'fbp-pv-upload-icon' }, f.type === 'image' ? '🖼' : '📎'),
            h('span', { class: 'fbp-pv-upload-text' }, f.type === 'image' ? '上传图片' : '上传文件'),
          ])
        case 'signature':
          return h('div', { class: 'fbp-pv-sig' }, [
            h('span', { class: 'fbp-pv-sig-line' }),
            h('span', { class: 'fbp-pv-sig-text' }, '请在此签名'),
          ])
        case 'ref':
        case 'ref_form':
        case 'subtable':
        case 'data_select':
        case 'data_single':
        case 'data_stat':
        case 'cross_field':
        case 'aggregate':
          return h('div', { class: 'fbp-pv-select' }, [
            h('span', { class: 'fbp-pv-select-text' }, ph || (
              f.type === 'subtable' ? '子表数据' :
              f.type === 'data_select' ? '请选择数据' :
              f.type === 'data_single' ? '请选择一条数据' :
              f.type === 'data_stat' ? '统计值' :
              f.type === 'cross_field' ? '关联他表字段' :
              f.type === 'ref_form' ? '关联表单数据' : '引用值'
            )),
            h('span', { class: 'fbp-pv-select-caret' }, '→'),
          ])
        // 新 apaas widget 类型 (v4)
        case 'phone':
          return h('input', { class: cls, type: 'tel', placeholder: ph || '请输入手机号', readonly: true })
        case 'email':
          return h('input', { class: cls, type: 'email', placeholder: ph || '请输入邮箱地址', readonly: true })
        case 'idcard':
          return h('input', { class: cls, type: 'text', placeholder: ph || '请输入证件号', readonly: true })
        case 'region':
          return h('div', { class: 'fbp-pv-select' }, [
            h('span', { class: 'fbp-pv-select-text' }, ph || '请选择省/市/区'),
            h('span', { class: 'fbp-pv-select-caret' }, '▾'),
          ])
        case 'location':
          return h('div', { class: 'fbp-pv-select' }, [
            h('span', { class: 'fbp-pv-select-text' }, '📍 ' + (ph || '点击定位')),
            h('span', { class: 'fbp-pv-select-caret' }, '→'),
          ])
        case 'hyperlink':
          return h('input', { class: cls, type: 'url', placeholder: ph || 'https://', readonly: true })
        case 'serial_no':
          return h('input', { class: cls, type: 'text', placeholder: 'SQDH-20260526-0001', readonly: true })
        case 'select_single':
          return h('div', { class: 'fbp-pv-select' }, [
            h('span', { class: 'fbp-pv-select-text' }, ph || '请选择…'),
            h('span', { class: 'fbp-pv-select-caret' }, '▾'),
          ])
        // 页面布局组件
        case 'static_text':
          return h('div', { class: 'fbp-pv-static' }, f.placeholder || f.name || '静态文本内容')
        case 'static_image':
          return h('div', { class: 'fbp-pv-upload' }, [
            h('span', { class: 'fbp-pv-upload-icon' }, '🖼'),
            h('span', { class: 'fbp-pv-upload-text' }, '静态图片'),
          ])
        case 'divider':
          return h('div', { class: 'fbp-pv-divider' })
        case 'placeholder':
          return h('div', { class: 'fbp-pv-placeholder' })
        case 'collapse_layout':
        case 'tab_layout':
        case 'frame_layout':
          return h('div', { class: 'fbp-pv-layout' }, f.type === 'collapse_layout' ? '【折叠布局】' : f.type === 'tab_layout' ? '【分页布局】' : '【框架布局】')
        case 'template_file':
          return h('div', { class: 'fbp-pv-select' }, [
            h('span', { class: 'fbp-pv-select-text' }, '📋 模板文件'),
            h('span', { class: 'fbp-pv-select-caret' }, '→'),
          ])
        // 高级
        case 'form_button':
          return h('button', { class: 'fbp-pv-formbtn', type: 'button' }, f.name || '按钮')
        case 'virtual_field':
        case 'custom_dev':
          return h('div', { class: 'fbp-pv-select' }, [
            h('span', { class: 'fbp-pv-select-text' }, f.type === 'virtual_field' ? '虚拟字段 (公式计算)' : '自开发字段'),
            h('span', { class: 'fbp-pv-select-caret' }, '→'),
          ])
        default:
          return h('input', { class: cls, type: 'text', placeholder: ph, readonly: true })
      }
    }
  },
}

/* ────────────────────────────────────────────────────────────────
   O2-Form: FormPreviewInput — preview mode 真业务表单 widget
   字段以真表单形式渲染 (input/select/date 等), 用户可填. 不存数据.
   ──────────────────────────────────────────────────────────────── */

const FormPreviewInput = {
  props: {
    field: { type: Object as PropType<FormField>, required: true },
    modelValue: { type: null as any, default: undefined },
  },
  emits: ['update:modelValue'],
  setup(props: { field: FormField; modelValue: any }, { emit }: { emit: (e: 'update:modelValue', v: any) => void }) {
    return () => {
      const f = props.field
      const v = props.modelValue
      const ph = f.placeholder || `请输入${f.name || ''}`
      const cls = 'fbp-fp-input'
      const onInput = (e: Event) => emit('update:modelValue', (e.target as HTMLInputElement).value)
      const opts = f.options || []
      switch (f.type) {
        case 'textarea':
        case 'richtext':
          return h('textarea', { class: cls, placeholder: ph, rows: 3, value: v ?? '', onInput })
        case 'number':
        case 'money':
        case 'rating':
        case 'slider':
          return h('input', { class: cls, type: 'number', placeholder: ph, value: v ?? '', onInput })
        case 'switch':
          return h('label', { class: 'fbp-fp-switch', 'data-on': v ? 'true' : 'false' }, [
            h('input', {
              type: 'checkbox',
              checked: !!v,
              onChange: (e: Event) => emit('update:modelValue', (e.target as HTMLInputElement).checked),
            }),
            h('span', { class: 'fbp-fp-switch-track' }, [h('span', { class: 'fbp-fp-switch-knob' })]),
          ])
        case 'select':
        case 'dict':
        case 'select_single':
          return h('select', { class: cls, value: v ?? '', onChange: (e: Event) => emit('update:modelValue', (e.target as HTMLSelectElement).value) }, [
            h('option', { value: '' }, ph || '请选择…'),
            ...opts.map(o => h('option', { value: o.code }, o.name || o.code)),
          ])
        case 'select_multi':
        case 'multi_select':
        case 'tag':
          return h('select', {
            class: cls,
            multiple: true,
            size: Math.min(4, Math.max(2, opts.length || 2)),
            onChange: (e: Event) => emit('update:modelValue', Array.from((e.target as HTMLSelectElement).selectedOptions).map(o => o.value)),
          }, opts.length === 0
            ? [h('option', { disabled: true }, '无选项 — 请用配置助手配置')]
            : opts.map(o => h('option', { value: o.code }, o.name || o.code)))
        case 'radio':
          return h('div', { class: 'fbp-fp-radio-group' }, opts.length === 0
            ? [h('span', { class: 'fbp-fp-empty-hint' }, '无选项 — 请用配置助手配置')]
            : opts.map(o => h('label', { class: 'fbp-fp-radio-item' }, [
                h('input', { type: 'radio', name: f.code, value: o.code, checked: v === o.code, onChange: () => emit('update:modelValue', o.code) }),
                h('span', null, o.name || o.code),
              ])))
        case 'date':
          return h('input', { class: cls, type: 'date', value: v ?? '', onInput })
        case 'time':
          return h('input', { class: cls, type: 'time', value: v ?? '', onInput })
        case 'datetime':
          return h('input', { class: cls, type: 'datetime-local', value: v ?? '', onInput })
        case 'daterange':
          return h('div', { class: 'fbp-fp-range' }, [
            h('input', { class: cls, type: 'date' }),
            h('span', { class: 'fbp-fp-range-sep' }, '→'),
            h('input', { class: cls, type: 'date' }),
          ])
        case 'month':
          return h('input', { class: cls, type: 'month', value: v ?? '', onInput })
        case 'user':
        case 'dept':
        case 'role':
          return h('div', { class: 'fbp-fp-pick' }, [
            h('span', { class: 'fbp-fp-pick-icon' }, f.type === 'user' ? '👤' : f.type === 'dept' ? '🏢' : '🛡'),
            h('input', { class: cls, type: 'text', placeholder: ph, value: v ?? '', onInput, style: 'border:none;background:transparent;padding:0;flex:1;' }),
          ])
        case 'image':
        case 'file':
          return h('label', { class: 'fbp-fp-upload' }, [
            h('span', { class: 'fbp-fp-upload-icon' }, f.type === 'image' ? '🖼' : '📎'),
            h('span', { class: 'fbp-fp-upload-text' }, f.type === 'image' ? '点击上传图片' : '点击上传文件'),
            h('input', { type: 'file', style: 'display:none' }),
          ])
        case 'phone':
          return h('input', { class: cls, type: 'tel', placeholder: ph || '请输入手机号', value: v ?? '', onInput })
        case 'email':
          return h('input', { class: cls, type: 'email', placeholder: ph || '请输入邮箱地址', value: v ?? '', onInput })
        case 'idcard':
          return h('input', { class: cls, type: 'text', placeholder: ph || '请输入证件号', value: v ?? '', onInput })
        case 'region':
          return h('input', { class: cls, type: 'text', placeholder: ph || '请选择省/市/区', value: v ?? '', onInput })
        case 'location':
          return h('input', { class: cls, type: 'text', placeholder: ph || '📍 点击定位', value: v ?? '', onInput })
        case 'hyperlink':
          return h('input', { class: cls, type: 'url', placeholder: ph || 'https://', value: v ?? '', onInput })
        case 'serial_no':
          return h('input', { class: cls, type: 'text', placeholder: 'SQDH-XXXX (自动生成)', value: v ?? '', readonly: true })
        case 'static_text':
          return h('div', { class: 'fbp-fp-static' }, f.placeholder || f.name || '')
        case 'static_image':
          return h('div', { class: 'fbp-fp-static-img' }, [h('span', null, '🖼 静态图片')])
        case 'divider':
          return h('hr', { class: 'fbp-fp-divider' })
        case 'placeholder':
          return h('div', { class: 'fbp-fp-placeholder' })
        case 'collapse_layout':
        case 'tab_layout':
        case 'frame_layout':
          return h('div', { class: 'fbp-fp-layout-hint' }, f.type === 'collapse_layout' ? '【折叠布局】' : f.type === 'tab_layout' ? '【分页布局】' : '【框架布局】')
        case 'form_button':
          return h('button', { class: 'fbp-btn fbp-btn-ghost fbp-btn-sm', type: 'button' }, f.name || '按钮')
        case 'ref':
        case 'ref_form':
        case 'subtable':
        case 'data_select':
        case 'data_single':
        case 'data_stat':
        case 'cross_field':
        case 'virtual_field':
        case 'custom_dev':
        case 'template_file':
          return h('input', { class: cls, type: 'text', placeholder: ph || '关联数据 (点击选择)', value: v ?? '', onInput })
        default:
          return h('input', { class: cls, type: 'text', placeholder: ph, value: v ?? '', onInput })
      }
    }
  },
}

/* ────────────────────────────────────────────────────────────────
   Props / state
   ──────────────────────────────────────────────────────────────── */

const props = defineProps<{
  appId: number
  menuId?: string
  menuName?: string
  formId?: string
}>()

const fields = ref<FormField[]>([])
const modelCode = ref('')
const loading = ref(false)
const error = ref('')
const dirty = ref(false)

// 2026-05-26 G1 真存追踪
// 删除的 field — 已 splice 出 fields 数组, 保留这里给保存按钮调 disable endpoint
const deletedFields = ref<FormField[]>([])
const saving = ref(false)
const saveProgress = ref<{ done: number; total: number; current: string } | null>(null)

const libSearchKw = ref('')
const collapsedCats = ref<Record<string, boolean>>({})

// sidebar 2 tab: 业务组件 (默认) / 数据模型
const libTab = ref<'component' | 'model'>('component')
// 数据模型 tab 的 source — 跟低代码原生 data-model-fn-config 一致, 来自 form/{form_id}/detail.
// 不再用 list_apaas_app_models (那个会漏 borrow_apply 等 form-scoped model).
const formDetailModels = ref<any[]>([])
const formMainModelCode = ref<string>('')
// 老 fallback: list_apaas_app_models 拿到的应用所有 model (form_id 为空或 form detail 失败兜底)
const allModels = ref<any[]>([])
const selectedLibModelId = ref<string>('')
// sidebar 数据模型 list — 优先用 formDetailModels (form 关联真模型), 兜底 allModels (应用全部主表)
const sidebarModelList = computed<any[]>(() => {
  if (formDetailModels.value.length > 0) {
    return formDetailModels.value.map((m: any) => ({
      id: m.model_id,
      name: m.model_name,
      code: m.model_code,
      is_main: m.is_main,
      extra: { fields: m.fields, model_id: m.model_id, model_code: m.model_code, model_name: m.model_name },
    }))
  }
  return allModels.value
})
const selectedLibModel = computed(() =>
  sidebarModelList.value.find(m => String(m.id || m.extra?.model_id) === selectedLibModelId.value)
)
const selectedLibModelFields = computed<any[]>(() => {
  const raw = (selectedLibModel.value?.extra?.fields || []) as any[]
  return raw
})

function onAddExistingField(rawField: any) {
  // 从数据模型 tab 拖/点一个已使用字段 → 加到 canvas (作 reuse, 同 code 跳过)
  // 注: 这种字段在 apaas model 里已存在 — 加到 form 只是 layout 改动. 不走 add endpoint,
  // 也不 mark _pending. form layout 真存是 P3 (set_apaas_form_config). 当前只是 local form layout.
  const code = String(rawField.field_code || '')
  if (!code) return
  if (fields.value.some(f => f.code === code)) {
    alert(`字段 "${code}" 已在 form 上, 不重复加`)
    return
  }
  const widgetType = backendTypeToWidget(rawField.data_type || rawField.field_type)
  const mc = (selectedLibModel.value?.code as string) || (selectedLibModel.value?.extra?.model_code as string) || ''
  const mid = String(selectedLibModel.value?.id || selectedLibModel.value?.extra?.model_id || '')
  const newField: FormField = {
    id: nextId(),
    code,
    name: String(rawField.field_name || code),
    type: widgetType,
    placeholder: '',
    required: !!rawField.required,
    editable: true,
    ai_validate: false,
    options: needsOptions(widgetType) ? [] : undefined,
    _src: rawField,
    _model_id: mid,
    _model_code: mc,
    _field_id: String(rawField.field_id || ''),
  }
  fields.value.push(newField)
  selectedFieldId.value = newField.id
  dirty.value = true
}

const selectedFieldId = ref<string>('')
const selectedField = computed<FormField | undefined>(() =>
  fields.value.find(f => f.id === selectedFieldId.value)
)

const showAiHelper = ref(false)
const aiPrompt = ref('')
const propsAiPrompt = ref('')

/* ────────────────────────────────────────────────────────────────
   O2-Form: view-mode 切换 (preview 默认 / edit)
   preview mode 隐藏左库 + 右属性, 中央显真业务表单 (像最终用户填表).
   edit mode 显原 3 列 builder.
   ──────────────────────────────────────────────────────────────── */
const viewMode = ref<'preview' | 'edit'>('preview')
const hoveredFieldId = ref<string>('')
// preview mode 用户填表的值 (仅 local, 切表单/切 mode reset, 不存)
const formValues = ref<Record<string, any>>({})

watch(
  () => props.formId,
  () => { formValues.value = {} }
)
watch(viewMode, () => { hoveredFieldId.value = '' })

function onPreviewSubmit() {
  alert('预览模式 — 提交不会真存. 改字段请用配置助手对话, 或切到"编辑"模式手动调.')
}
function onPreviewCancel() {
  formValues.value = {}
}
function onInlineEditHint(f: FormField) {
  alert(`请用右下角"配置助手"浮窗对话, 如:\n\n"把字段 ${f.name || f.code} 改成 XXX"\n"把 ${f.code} 改成必填"`)
}
function onOpenConfigAssistant() {
  alert('改字段请用右下角"配置助手"浮窗对话, 比如:\n\n"把 ISBN 改成必填"\n"加一个备注字段, 多行输入, 不必填"\n"删掉申请说明字段"')
}

/* ────────────────────────────────────────────────────────────────
   Computed
   ──────────────────────────────────────────────────────────────── */

const modelFieldsCollapsed = ref(false)

// canvas 布局: 2 列 (default, 跟 apaas 一致) / 1 列 (mobile or 用户偏好)
const canvasLayout = ref<'1col' | '2col'>('2col')
const canvasViewport = ref<'pc' | 'mobile'>('pc')

// 哪些 widget 必须占满 2 列 (跟 apaas 原生一致)
const FULL_WIDTH_WIDGETS = new Set<string>([
  'textarea', 'richtext',
  'static_text', 'static_image', 'divider', 'placeholder',
  'collapse_layout', 'tab_layout', 'frame_layout', 'template_file',
  'subtable', 'data_select', 'data_stat',
])
function isFullWidthWidget(t: string): boolean {
  return canvasLayout.value === '1col' || FULL_WIDTH_WIDGETS.has(t)
}

const filteredModels = computed(() => {
  const kw = libSearchKw.value.trim().toLowerCase()
  if (!kw) return sidebarModelList.value
  return sidebarModelList.value.filter((m: any) =>
    (m.name || '').toLowerCase().includes(kw)
    || (m.code || '').toLowerCase().includes(kw)
  )
})

const filteredCategories = computed(() => {
  const kw = libSearchKw.value.trim().toLowerCase()
  if (!kw) return FIELD_CATEGORIES
  return FIELD_CATEGORIES
    .map(c => ({
      ...c,
      widgets: c.widgets.filter(w => w.label.toLowerCase().includes(kw) || w.type.includes(kw)),
    }))
    .filter(c => c.widgets.length > 0)
})

/* ────────────────────────────────────────────────────────────────
   Methods
   ──────────────────────────────────────────────────────────────── */

function toggleCat(code: string) {
  collapsedCats.value[code] = !collapsedCats.value[code]
}

function onSelectField(id: string) {
  selectedFieldId.value = id
}

// 构造 FormField 共用函数 — click 路径 & drag clone 路径都走这里
function buildFieldFromWidget(w: WidgetMeta): FormField {
  // 2026-05-26 G1: 新加字段 mark _pending=true, 主表 model_code / model_id 用当前选中的 sidebar model
  const mc = (selectedLibModel.value?.code as string) || (selectedLibModel.value?.extra?.model_code as string) || formMainModelCode.value || modelCode.value || ''
  const mid = String(selectedLibModel.value?.id || selectedLibModel.value?.extra?.model_id || '')
  return {
    id: nextId(),
    code: `${w.type}_${fields.value.length + 1}`,
    name: w.label,
    type: w.type,
    placeholder: '',
    required: false,
    editable: true,
    ai_validate: false,
    options: needsOptions(w.type) ? [] : undefined,
    _pending: true,
    _model_id: mid,
    _model_code: mc,
  }
}

function onAddWidget(w: WidgetMeta) {
  const newField = buildFieldFromWidget(w)
  fields.value.push(newField)
  selectedFieldId.value = newField.id
  dirty.value = true
}

// vuedraggable 4 clone fn — 库 chip 拖入 canvas 时被调, 必须返新 object
// (否则同一对象进多次会引用绑定爆炸).
function cloneWidgetToField(w: WidgetMeta): FormField {
  return buildFieldFromWidget(w)
}

// 数据模型 tab "已使用字段" chip 拖入 canvas 时被调
// 注: 已存在 apaas model 的字段, 复用到 form layout — 不 mark _pending (跟 onAddExistingField 一致).
function cloneModelFieldToField(rawField: any): FormField {
  const code = String(rawField.field_code || `field_${Math.random().toString(36).slice(2, 6)}`)
  const widgetType = backendTypeToWidget(rawField.data_type || rawField.field_type)
  const mc = (selectedLibModel.value?.code as string) || (selectedLibModel.value?.extra?.model_code as string) || ''
  const mid = String(selectedLibModel.value?.id || selectedLibModel.value?.extra?.model_id || '')
  return {
    id: nextId(),
    code,
    name: String(rawField.field_name || code),
    type: widgetType,
    placeholder: '',
    required: !!rawField.required,
    editable: true,
    ai_validate: false,
    options: needsOptions(widgetType) ? [] : undefined,
    _src: rawField,
    _model_id: mid,
    _model_code: mc,
    _field_id: String(rawField.field_id || ''),
  }
}

// drop 后 callback — cross-group add 或同组重排都走 @change
function onFieldsChange(evt: any) {
  if (evt?.added) {
    // 跨容器 drop — 库 chip 推过来新字段, 选中并 dirty
    const newField: FormField | undefined = evt.added.element
    if (newField?.id) {
      selectedFieldId.value = newField.id
    }
    dirty.value = true
  } else if (evt?.moved) {
    // 内部重排
    dirty.value = true
  } else if (evt?.removed) {
    // 我们不允许内部往外拖 — 但 cross-group pull:false 已经禁了, 容错保留
    dirty.value = true
  }
}

function onRemoveField(id: string) {
  const idx = fields.value.findIndex(f => f.id === id)
  if (idx < 0) return
  const f = fields.value[idx]
  // 2026-05-26 G1: 删字段真存. confirm dialog 提示真存到 apaas (apaas 软删, 数据保留).
  const isPending = !!f._pending
  const hasFieldId = !!(f._field_id && f._model_id)
  const msg = isPending
    ? `删除字段 "${f.name}" — 未保存, 仅本地移除?`
    : hasFieldId
      ? `删除字段 "${f.name}" — 保存时真存到 apaas (apaas 软删, 数据保留)?`
      : `删除字段 "${f.name}" — 该字段无 field_id (仅本地), 仅本地移除?`
  if (!window.confirm(msg)) return
  fields.value.splice(idx, 1)
  // 已存在 apaas 平台的字段 → 加入 deletedFields, 保存时调 disable endpoint
  if (!isPending && hasFieldId) {
    deletedFields.value.push(f)
  }
  if (selectedFieldId.value === id) selectedFieldId.value = ''
  dirty.value = true
}

function onFieldsReorder() {
  // 仅 fallback: vuedraggable 4 v-model 重排时不主动触 @change moved 的极端情况
  dirty.value = true
}

function onAddOption() {
  if (!selectedField.value) return
  if (!selectedField.value.options) selectedField.value.options = []
  const n = selectedField.value.options.length + 1
  selectedField.value.options.push({ code: `opt_${n}`, name: `选项${n}` })
}

function onRemoveOption(i: number) {
  if (!selectedField.value?.options) return
  selectedField.value.options.splice(i, 1)
}

// 2026-05-26 G1 真存 — 计算待保存 batch
const pendingFields = computed(() => fields.value.filter(f => f._pending))
const updatedFields = computed(() => fields.value.filter(f => !f._pending && isFieldDirtyVsOriginal(f)))
const saveCounts = computed(() => ({
  add: pendingFields.value.length,
  update: updatedFields.value.length,
  del: deletedFields.value.length,
  total: pendingFields.value.length + updatedFields.value.length + deletedFields.value.length,
}))

async function onSaveForm() {
  if (saving.value) return
  const { add, update, del, total } = saveCounts.value
  if (total === 0) {
    alert('当前无修改')
    return
  }
  // 检 add 的字段都有 model_code + model_id (空了 backend 会拒)
  const orphans = pendingFields.value.filter(f => !(f._model_code && f._model_id))
  if (orphans.length > 0) {
    alert(
      `有 ${orphans.length} 个新字段未关联数据模型 (model_id/model_code 为空):\n`
      + orphans.map(f => `· ${f.name} (${f.code})`).join('\n')
      + '\n\n请先在左侧"数据模型" tab 选中目标 model, 再加字段.'
    )
    return
  }
  // 检字段 code/name 必填
  const blanks = [...pendingFields.value, ...updatedFields.value].filter(f => !f.code.trim() || !f.name.trim())
  if (blanks.length > 0) {
    alert(`有 ${blanks.length} 个字段缺 code 或 name:\n` + blanks.map(f => `· ${f.name || '(空)'} - ${f.code || '(空)'}`).join('\n'))
    return
  }

  const parts: string[] = []
  if (add) parts.push(`${add} 个新字段`)
  if (update) parts.push(`${update} 个字段改动`)
  if (del) parts.push(`${del} 个字段删除`)
  const msg = `保存 ${parts.join(' + ')} — 真存到 apaas?\n\n注: 删除走 apaas 软删 (status=DISABLE, 数据保留).`
  if (!window.confirm(msg)) return

  saving.value = true
  saveProgress.value = { done: 0, total, current: '' }
  const errors: string[] = []
  let successCount = 0

  // 串行调 endpoint — 简单, 避免一次性打爆 apaas
  try {
    // 1. 新增字段
    for (const f of pendingFields.value) {
      f._saving = true
      saveProgress.value = { done: successCount, total, current: `新增 ${f.name}` }
      try {
        const resp: any = await request.post(
          `/applications/${props.appId}/crud/model-field/add`,
          {
            model_id: f._model_id || '',
            model_code: f._model_code || '',
            field_code: f.code,
            field_name: f.name,
            field_type: widgetToBackendType(f.type),
            max_length: f.max_length || 255,
            comment: f.description || '',
          },
        )
        if (resp?.ok) {
          successCount += 1
        } else {
          errors.push(`新增 "${f.name}" 失败: ${resp?.message || resp?.error_code || '未知错误'}`)
        }
      } catch (e: any) {
        errors.push(`新增 "${f.name}" 失败: ${e?.response?.data?.message || e?.message || '网络错误'}`)
      } finally {
        f._saving = false
      }
    }
    // 2. 改动字段
    for (const f of updatedFields.value) {
      if (!f._field_id || !f._model_id) {
        errors.push(`改 "${f.name}" 失败: 缺 field_id / model_id (可能是 sidebar 加进来还没刷新)`)
        continue
      }
      f._saving = true
      saveProgress.value = { done: successCount, total, current: `改 ${f.name}` }
      try {
        const resp: any = await request.post(
          `/applications/${props.appId}/crud/model-field/update`,
          {
            model_id: f._model_id,
            field_id: f._field_id,
            field_code: f.code,
            field_name: f.name,
            field_type: widgetToBackendType(f.type),
            max_length: f.max_length || 0,
            comment: f.description || '',
          },
        )
        if (resp?.ok) {
          successCount += 1
        } else {
          errors.push(`改 "${f.name}" 失败: ${resp?.message || resp?.error_code || '未知错误'}`)
        }
      } catch (e: any) {
        errors.push(`改 "${f.name}" 失败: ${e?.response?.data?.message || e?.message || '网络错误'}`)
      } finally {
        f._saving = false
      }
    }
    // 3. 删除字段
    for (const f of deletedFields.value) {
      if (!f._field_id || !f._model_id) {
        errors.push(`删 "${f.name}" 失败: 缺 field_id / model_id`)
        continue
      }
      saveProgress.value = { done: successCount, total, current: `删除 ${f.name}` }
      try {
        const resp: any = await request.post(
          `/applications/${props.appId}/crud/model-field/disable`,
          {
            model_id: f._model_id,
            field_id: f._field_id,
            field_code: f.code,
            field_name: f.name,
          },
        )
        if (resp?.ok) {
          successCount += 1
        } else {
          errors.push(`删 "${f.name}" 失败: ${resp?.message || resp?.error_code || '未知错误'}`)
        }
      } catch (e: any) {
        errors.push(`删 "${f.name}" 失败: ${e?.response?.data?.message || e?.message || '网络错误'}`)
      }
    }
  } finally {
    saving.value = false
    saveProgress.value = null
  }

  if (errors.length === 0) {
    alert(`保存成功 — ${successCount} 项已写入 apaas. 即将刷新最新数据.`)
    await reload()
  } else if (successCount > 0) {
    alert(
      `部分成功: ${successCount} / ${total} 已写入.\n\n失败:\n${errors.join('\n')}\n\n`
      + `成功部分已 commit 到 apaas, 失败部分保留 dirty 状态. 重试保存只重发失败项.`
    )
    // 重新拉真数据, 但保留失败的本地 dirty 状态 (失败的 field 还在 pending/updated/deleted 队列里)
    // 简化: 整体 reload, 让用户重新发现 dirty (避免半合并状态)
    await reload()
  } else {
    alert(`保存失败 (0 / ${total}):\n\n${errors.join('\n')}`)
    // 失败时不刷新, 保留 dirty 状态让用户重试
  }
}

function onAiPrompt(prompt: string) {
  aiPrompt.value = prompt
  onAiSubmit()
}

function onAiSubmit() {
  if (!aiPrompt.value.trim()) return
  alert(
    `AI 助手 — Phase A 占位.\n\n您的输入:\n"${aiPrompt.value}"\n\n` +
    '请到右侧配置助手浮窗对话, 它会真正调 MCP 工具改表单.'
  )
  aiPrompt.value = ''
}

function onPropsAiSubmit() {
  if (!propsAiPrompt.value.trim()) return
  alert(
    `AI 改字段 — Phase A 占位.\n\n您的输入:\n"${propsAiPrompt.value}"\n\n` +
    '请到右侧配置助手对话.'
  )
  propsAiPrompt.value = ''
}

/* ────────────────────────────────────────────────────────────────
   Data load
   ──────────────────────────────────────────────────────────────── */

async function reload() {
  if (!props.appId || !props.menuId) {
    fields.value = []
    modelCode.value = ''
    return
  }
  loading.value = true
  error.value = ''
  modelCode.value = ''  // 切 menu 前先 reset 防残留
  try {
    // ── 优先路径: form_id → /forms/{form_id}/detail (跟得帆云原生 data-model-fn-config 100% 对齐).
    // 一次拿 components + models, sidebar 数据模型 tab 也用这个数据 (不再走漏 model 的 list_apaas_app_models).
    if (props.formId) {
      const respFD = await request.get<any, any>(
        `/applications/${props.appId}/forms/${props.formId}/detail`
      )
      if (respFD?.ok) {
        // 设 sidebar models (跟低代码原生页面一致 — form 关联的真模型, 不是应用全部 model)
        formDetailModels.value = respFD.models || []
        formMainModelCode.value = String(respFD.main_model_code || '')
        // 默认选中 main model
        if (formMainModelCode.value && formDetailModels.value.length > 0) {
          const mm = formDetailModels.value.find((m: any) => m.model_code === formMainModelCode.value)
          if (mm) selectedLibModelId.value = String(mm.model_id || mm.model_code)
        }
        // canvas 字段从 components
        const comps = respFD.components || []
        fields.value = comps.map((c: any): FormField => {
          const compType = String(c.component_type || '')
          const widgetType = componentTypeToWidget(compType)
          const boCode = String(c.bo_code || '')
          const [_modelCode, fieldCode] = boCode.includes('~') ? boCode.split('~') : ['', boCode]
          if (_modelCode) modelCode.value = _modelCode
          // 关联 model 字段 (查 model_code → fields → 拿 max_length / description)
          const mm = (respFD.models || []).find((m: any) => m.model_code === _modelCode)
          const mf = mm?.fields?.find((x: any) => x.field_code === fieldCode)
          const f: FormField = {
            id: nextId(),
            code: fieldCode || `field_${Math.random().toString(36).slice(2, 6)}`,
            name: String(c.label || fieldCode || '未命名'),
            type: widgetType,
            placeholder: '',
            required: !!c.required,
            editable: true,
            ai_validate: false,
            options: needsOptions(widgetType) ? [] : undefined,
            description: String(mf?.description || ''),
            hint: '',
            max_length: mf?.max_length ? Number(mf.max_length) : undefined,
            _src: { ...c, _component_type: compType, _uuid: c.uuid, _model_field: mf },
            // 2026-05-26 G1: 真存追踪 — _model_id / _model_code / _field_id 从 model.fields 反查
            _model_id: String(mm?.model_id || ''),
            _model_code: _modelCode || String(mm?.model_code || ''),
            _field_id: String(mf?.field_id || ''),
          }
          f._original = snapshotField(f)
          return f
        })
        if (!modelCode.value) modelCode.value = formMainModelCode.value
        if (fields.value.length > 0 && !selectedFieldId.value) {
          selectedFieldId.value = fields.value[0].id
        }
        deletedFields.value = []
        dirty.value = false
        return
      }
      // form/detail 没拿到 → 兜底走 model 路径
    }

    // ── 兜底路径: model name/id match (老逻辑, FormBuilder Phase A initial)
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/section-content/models?with_fields=true`
    )
    if (resp?.ok) {
      const items: any[] = resp.items || []
      const target = items.find(it => {
        const raw = it.extra || {}
        return String(raw.model_id) === String(props.menuId)
          || String(raw.form_id) === String(props.formId)
          || (props.menuName && raw.model_name === props.menuName)
      })
      if (target) {
        const raw = target.extra || {}
        modelCode.value = raw.model_code || target.code || ''
        const _model_id = String(raw.model_id || target.id || '')
        const _model_code = String(modelCode.value)
        const rawFields = Array.isArray(raw.fields) ? raw.fields : []
        fields.value = rawFields.map((rf: any): FormField => {
          const wt = backendTypeToWidget(rf.data_type || rf.field_type)
          const f: FormField = {
            id: nextId(),
            code: rf.field_code || `field_${Math.random().toString(36).slice(2, 6)}`,
            name: rf.field_name || rf.field_code || '未命名',
            type: wt,
            placeholder: rf.placeholder || '',
            required: !!rf.required,
            editable: rf.editable !== false,
            ai_validate: !!rf.ai_validate,
            options: Array.isArray(rf.options) ? rf.options.map((o: any) => ({
              code: String(o.code || o.value || ''),
              name: String(o.name || o.label || o.code || ''),
            })) : (needsOptions(wt) ? [] : undefined),
            description: String(rf.description || ''),
            max_length: rf.max_length ? Number(rf.max_length) : undefined,
            _src: rf,
            _model_id,
            _model_code,
            _field_id: String(rf.field_id || ''),
          }
          f._original = snapshotField(f)
          return f
        })
        if (fields.value.length > 0 && !selectedFieldId.value) {
          selectedFieldId.value = fields.value[0].id
        }
      } else {
        fields.value = []
        modelCode.value = ''
      }
      deletedFields.value = []
      dirty.value = false
    } else {
      error.value = resp?.message || resp?.error_code || '加载失败'
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '网络错误'
  } finally {
    loading.value = false
  }
}

// ── sidebar 数据模型 tab — list 应用 models + 已使用字段拖入 canvas ──
async function loadAllModels() {
  if (!props.appId) return
  try {
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/section-content/models?with_fields=true`
    )
    if (resp?.ok) {
      allModels.value = resp.items || []
      if (allModels.value.length > 0 && !selectedLibModelId.value) {
        // 默认选首个 model (跟得帆云一致)
        selectedLibModelId.value = String(allModels.value[0].id || allModels.value[0].extra?.model_id || '')
      }
    }
  } catch {
    /* sidebar model list 拉失败不影响 canvas */
  }
}

watch(() => [props.appId, props.menuId, props.formId], () => reload(), { immediate: true })
watch(() => props.appId, () => loadAllModels(), { immediate: true })
</script>

<style scoped>
.fbp {
  font-family: var(--font-sans);
  color: var(--text);
  background: var(--bg);
  height: 100%;
  display: flex;
  flex-direction: column;
  font-feature-settings: 'cv11', 'ss01';
  overflow: hidden;
}

/* ─── Empty / state ─────────────────────────────────────────── */
.fbp-empty,
.fbp-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  height: 100%;
  color: var(--text-3);
  gap: 12px;
  padding: 48px 16px;
}
.fbp-empty-icon,
.fbp-state-icon { font-size: 40px; line-height: 1; }
.fbp-empty h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
}
.fbp-empty p,
.fbp-state p { margin: 0; font-size: 13.5px; }
.fbp-state-err { color: var(--err); }
.fbp-state-err .fbp-btn { margin-top: 8px; }

.fbp-spinner {
  width: 18px; height: 18px;
  border: 2px solid var(--line-strong);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: fbp-spin 0.9s linear infinite;
}
@keyframes fbp-spin { to { transform: rotate(360deg); } }

/* ─── 3 列 shell ────────────────────────────────────────────── */
.fbp-3col {
  display: grid;
  grid-template-columns: 220px 1fr 300px;
  height: 100%;
  min-height: 0;
}
/* O2-Form: preview mode — 只占中央 canvas, 左库 + 右属性 v-show 隐藏 */
.fbp-3col.preview-mode {
  grid-template-columns: 1fr;
}

/* ─── O2-Form: view-mode segmented toggle (跟"开发/生产"同款) ─ */
.fbp-mode-toggle {
  display: inline-flex;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 2px;
  flex-shrink: 0;
}
.fbp-mode-btn {
  height: 26px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 500;
  font-family: inherit;
  background: transparent;
  border: 0;
  border-radius: 6px;
  color: var(--text-3);
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.fbp-mode-btn:hover { color: var(--text); }
.fbp-mode-btn.active {
  background: var(--surface);
  color: var(--brand);
  box-shadow: 0 1px 2px rgba(11, 27, 63, 0.06);
}

/* ─── O2-Form: preview mode banner ──────────────────────────── */
.fbp-preview-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 28px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 12.5px;
  border-bottom: 1px solid var(--line);
}
.fbp-preview-banner-icon {
  font-size: 14px;
}

/* ─── O2-Form: 真业务表单 (preview mode) ────────────────────── */
.fbp-canvas-body-preview {
  padding: 24px;
  align-items: center;
  background: var(--bg);
}
.fbp-form-preview {
  width: 100%;
  max-width: 800px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 28px 32px 24px;
  box-shadow: var(--sh-1);
}
.fbp-form-preview-head {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--line);
}
.fbp-form-preview-title {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: -0.2px;
}
.fbp-form-preview-sub {
  margin: 0;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
  color: var(--text-3);
}
.fbp-form-preview-empty {
  padding: 56px 16px 40px;
  text-align: center;
  color: var(--text-3);
}
.fbp-form-preview-empty .hint {
  font-size: 12.5px;
  color: var(--text-4);
  margin-top: 4px;
}
.fbp-form-preview-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px 24px;
}
.fbp-form-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  position: relative;
}
.fbp-form-row-full {
  grid-column: 1 / -1;
}
.fbp-form-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
  line-height: 1.2;
}
.fbp-form-req {
  color: var(--err);
  font-weight: 700;
  margin-left: 2px;
}
.fbp-form-edit-hint {
  margin-left: auto;
  background: transparent;
  border: none;
  color: var(--brand);
  font-size: 11.5px;
  font-family: inherit;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: background 0.12s;
}
.fbp-form-edit-hint:hover {
  background: var(--brand-soft);
  text-decoration: underline;
}
.fbp-form-desc {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--text-4);
}
.fbp-form-actions {
  grid-column: 1 / -1;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 10px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
}

/* responsive — narrow viewport preview 单列 */
@media (max-width: 720px) {
  .fbp-form-preview-grid {
    grid-template-columns: 1fr;
  }
}

/* ─── FormPreviewInput :deep styles (真 input 可填) ─────────── */
:deep(.fbp-fp-input) {
  width: 100%;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font-size: 13.5px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.12s, box-shadow 0.12s;
  box-sizing: border-box;
}
:deep(.fbp-fp-input::placeholder) { color: var(--text-4); }
:deep(.fbp-fp-input:focus) {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
:deep(textarea.fbp-fp-input) {
  height: auto;
  min-height: 76px;
  padding: 8px 12px;
  line-height: 1.55;
  resize: vertical;
}
:deep(select.fbp-fp-input) {
  appearance: none;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 24 24' fill='none' stroke='%23748094' stroke-width='2'><polyline points='6 9 12 15 18 9'/></svg>");
  background-repeat: no-repeat;
  background-position: right 10px center;
  padding-right: 30px;
}
:deep(select.fbp-fp-input[multiple]) {
  height: auto;
  padding: 6px 8px;
  background-image: none;
}
:deep(.fbp-fp-switch) {
  display: inline-flex;
  align-items: center;
  cursor: pointer;
  height: 36px;
}
:deep(.fbp-fp-switch input) {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
:deep(.fbp-fp-switch-track) {
  display: inline-flex;
  align-items: center;
  width: 40px;
  height: 22px;
  padding: 2px;
  border-radius: 999px;
  background: var(--line-strong);
  transition: background 0.15s;
}
:deep(.fbp-fp-switch[data-on="true"] .fbp-fp-switch-track) {
  background: var(--brand);
  justify-content: flex-end;
}
:deep(.fbp-fp-switch-knob) {
  width: 18px;
  height: 18px;
  background: #fff;
  border-radius: 50%;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.18);
  transition: transform 0.15s;
}
:deep(.fbp-fp-radio-group) {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  padding: 7px 0;
  font-size: 13.5px;
  color: var(--text);
}
:deep(.fbp-fp-radio-item) {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
}
:deep(.fbp-fp-empty-hint) {
  color: var(--text-4);
  font-size: 12.5px;
  font-style: italic;
}
:deep(.fbp-fp-range) {
  display: flex;
  align-items: center;
  gap: 8px;
}
:deep(.fbp-fp-range-sep) { color: var(--text-4); font-size: 13px; }
:deep(.fbp-fp-pick) {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
}
:deep(.fbp-fp-pick-icon) {
  font-size: 14px;
  color: var(--text-3);
}
:deep(.fbp-fp-upload) {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  padding: 0 14px;
  border: 1px dashed var(--line-strong);
  border-radius: 6px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 13px;
  cursor: pointer;
  transition: border-color 0.12s, color 0.12s;
}
:deep(.fbp-fp-upload:hover) {
  border-color: var(--brand);
  color: var(--brand);
}
:deep(.fbp-fp-static) {
  padding: 8px 12px;
  font-size: 13.5px;
  color: var(--text);
  background: var(--surface-2);
  border-radius: 6px;
}
:deep(.fbp-fp-static-img) {
  padding: 16px;
  text-align: center;
  font-size: 13px;
  color: var(--text-3);
  background: var(--surface-2);
  border: 1px dashed var(--line-strong);
  border-radius: 6px;
}
:deep(.fbp-fp-divider) {
  border: none;
  height: 1px;
  background: var(--line-strong);
  margin: 8px 0;
}
:deep(.fbp-fp-placeholder) {
  height: 24px;
  background: repeating-linear-gradient(45deg, var(--surface-2), var(--surface-2) 4px, var(--surface-3) 4px, var(--surface-3) 8px);
  border-radius: 4px;
  border: 1px dashed var(--line-strong);
}
:deep(.fbp-fp-layout-hint) {
  padding: 14px 12px;
  text-align: center;
  font-size: 12.5px;
  color: var(--text-3);
  background: var(--surface-2);
  border: 1px dashed var(--line-strong);
  border-radius: 6px;
}

/* ─── 左: 组件库 ────────────────────────────────────────────── */
.fbp-lib {
  background: var(--surface);
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  min-height: 0;
}
/* sidebar 2 tab header */
.fbp-lib-tabs {
  display: flex;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.fbp-lib-tab {
  flex: 1;
  padding: 12px 8px 11px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-3);
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: color 0.12s, border-color 0.12s;
}
.fbp-lib-tab:hover { color: var(--text-2); }
.fbp-lib-tab.active {
  color: var(--brand);
  border-bottom-color: var(--brand);
  font-weight: 600;
}

.fbp-lib-head {
  padding: 12px;
  border-bottom: 1px solid var(--line);
}
.fbp-lib-search {
  position: relative;
  display: flex;
  align-items: center;
}
.fbp-lib-search input {
  width: 100%;
  height: 30px;
  padding: 0 10px 0 28px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface-2);
  color: var(--text);
  font-size: 12.5px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.12s;
}
.fbp-lib-search input:focus { border-color: var(--brand); background: var(--surface); }
.fbp-lib-search input::placeholder { color: var(--text-4); }
.fbp-lib-search svg {
  position: absolute;
  left: 9px;
  color: var(--text-4);
  pointer-events: none;
}

.fbp-lib-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px 16px;
}
.fbp-lib-cat { margin-top: 4px; }
.fbp-lib-cat-head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 6px;
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.4px;
  text-align: left;
  font-family: inherit;
}
.fbp-lib-cat-head:hover { color: var(--text-2); }
.fbp-lib-cat-caret {
  transition: transform 0.15s;
  color: var(--text-4);
}
.fbp-lib-cat-caret.collapsed { transform: rotate(-90deg); }
.fbp-lib-cat-bar {
  display: inline-block;
  width: 3px;
  height: 12px;
  background: var(--brand);
  border-radius: 2px;
}
.fbp-lib-cat-count {
  margin-left: auto;
  font-size: 10.5px;
  color: var(--text-4);
  background: var(--surface-2);
  padding: 1px 6px;
  border-radius: 999px;
  font-weight: 500;
}

.fbp-lib-chips {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  padding: 0 2px 4px;
}
.fbp-lib-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 8px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 6px;
  font-size: 12px;
  font-family: inherit;
  color: var(--text-2);
  cursor: pointer;
  text-align: left;
  transition: all 0.12s;
  min-width: 0;
}
.fbp-lib-chip:hover {
  background: var(--brand-soft);
  border-color: var(--brand-soft-2);
  color: var(--brand);
}
.fbp-lib-chip-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  font-size: 13px;
  flex-shrink: 0;
  color: var(--text-3);
}
.fbp-lib-chip:hover .fbp-lib-chip-icon { color: var(--brand); }
.fbp-lib-chip-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}

/* chip drag affordance — 鼠标手 grab; 拖动时 grabbing */
.fbp-lib-chip-draggable {
  cursor: grab;
  user-select: none;
}
.fbp-lib-chip-draggable:active {
  cursor: grabbing;
}
/* SortableJS 给 dragged 节点加 sortable-chosen / sortable-drag class */
.fbp-lib-chips .sortable-chosen,
.fbp-lib-chips .sortable-drag {
  cursor: grabbing;
  opacity: 0.85;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
}
/* 库容器本身 cursor copy — 暗示这是 clone 操作 */
.fbp-lib-chips.sortable-drag-over {
  /* lib 不允许 put — 但保险 */
  cursor: not-allowed;
}

/* ── 数据模型 tab ─────────────────────────────────────────── */
.fbp-lib-model-body {
  padding: 0;
  display: flex;
  flex-direction: column;
}
.fbp-lib-model-add {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 12px 16px;
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--line);
  color: var(--brand);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  text-align: left;
  font-weight: 500;
}
.fbp-lib-model-add:disabled { opacity: 0.6; cursor: not-allowed; }
.fbp-lib-help {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border: 1px solid var(--line-strong);
  border-radius: 50%;
  font-size: 10px;
  color: var(--text-4);
  font-weight: normal;
}
.fbp-lib-model-list {
  padding: 4px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 280px;
  overflow-y: auto;
}
.fbp-lib-model-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: transparent;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
  color: var(--text-2);
  cursor: pointer;
  text-align: left;
  transition: background 0.12s;
}
.fbp-lib-model-item:hover { background: var(--surface-2); }
.fbp-lib-model-item.active {
  background: var(--brand-soft);
  color: var(--brand);
  font-weight: 500;
}
.fbp-lib-model-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  background: var(--surface-3);
  border-radius: 3px;
  font-size: 10px;
  color: var(--text-3);
  flex-shrink: 0;
}
.fbp-lib-model-item.active .fbp-lib-model-icon {
  background: var(--brand);
  color: #fff;
}
.fbp-lib-model-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fbp-lib-empty {
  padding: 24px 12px;
  text-align: center;
  font-size: 12px;
  color: var(--text-4);
}
.fbp-lib-empty-sm { padding: 8px 12px; font-size: 11.5px; }

.fbp-lib-model-detail {
  border-top: 1px solid var(--line);
  padding: 12px 12px 16px;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.fbp-lib-model-detail-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.fbp-lib-model-detail-bar {
  width: 3px;
  height: 28px;
  background: var(--brand);
  border-radius: 2px;
  flex-shrink: 0;
}
.fbp-lib-model-detail-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.fbp-lib-model-detail-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.fbp-lib-model-detail-code {
  font-size: 11.5px;
  color: var(--text-3);
}

.fbp-lib-model-detail-section { display: flex; flex-direction: column; }
.fbp-lib-model-detail-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  font-family: inherit;
  color: var(--text-2);
  margin-bottom: 8px;
}
.fbp-lib-model-detail-toggle:hover { background: var(--surface-3); }
.fbp-lib-model-detail-toggle svg { transition: transform 0.15s; color: var(--text-4); }

.fbp-lib-chips-model {
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}

/* ─── 中: canvas ────────────────────────────────────────────── */
.fbp-canvas {
  background: var(--bg);
  display: flex;
  flex-direction: column;
  min-height: 0;
  position: relative;
}
.fbp-canvas-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 28px 16px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.fbp-canvas-title {
  margin: 0 0 4px;
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: -0.2px;
}
.fbp-canvas-sub {
  margin: 0;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12.5px;
  color: var(--text-3);
}
.fbp-code {
  display: inline-block;
  padding: 1px 7px;
  font-size: 11.5px;
  background: var(--surface-2);
  border-radius: 4px;
  color: var(--text-3);
  border: 1px solid var(--line);
}
.fbp-canvas-sub > * + * {
  position: relative;
  padding-left: 14px;
}
.fbp-canvas-sub > * + *::before {
  content: '·';
  position: absolute;
  left: 4px;
  color: var(--text-4);
}
.fbp-canvas-stat { /* legacy class, layout inherited from > * + * */ }

.fbp-canvas-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.fbp-canvas-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 28px 24px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* canvas toolbar: 查看业务对象 / PC-Mobile / 表单设置 */
.fbp-canvas-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 28px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.fbp-toolbar-btn {
  height: 28px;
  padding: 0 12px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 5px;
  font-size: 12.5px;
  font-family: inherit;
  color: var(--text-2);
  cursor: pointer;
}
.fbp-toolbar-btn:not(:disabled):hover {
  border-color: var(--brand);
  color: var(--brand);
}
.fbp-toolbar-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.fbp-toolbar-btn-outline {
  border-color: var(--brand);
  color: var(--brand);
}
.fbp-toolbar-viewport {
  margin-left: auto;
  margin-right: auto;
  display: inline-flex;
  align-items: center;
  gap: 0;
  border: 1px solid var(--line);
  border-radius: 6px;
  overflow: hidden;
  background: var(--surface-2);
}
.fbp-toolbar-vp {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 28px;
  padding: 0;
  background: transparent;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.fbp-toolbar-vp:hover { color: var(--text); }
.fbp-toolbar-vp.active {
  background: var(--surface);
  color: var(--brand);
  box-shadow: 0 0 0 1px var(--brand-soft-2) inset;
}

.fbp-canvas-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 56px 16px 40px;
  color: var(--text-3);
  background: var(--surface);
  border: 1px dashed var(--line-strong);
  border-radius: 10px;
  gap: 6px;
}
.fbp-canvas-empty-icon { font-size: 36px; line-height: 1; margin-bottom: 6px; }
.fbp-canvas-empty p { margin: 0; font-size: 14px; }
.fbp-canvas-empty .hint { font-size: 12.5px; color: var(--text-4); }

/* ─── 字段卡片 ──────────────────────────────────────────────── */
.fbp-card-list {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 14px;
}
.fbp-card-list-1col {
  grid-template-columns: 1fr;
}
.fbp-card-fullwidth {
  grid-column: 1 / -1;
}
/* viewport mobile 时 canvas body 收窄模拟手机宽度 */
.fbp-canvas.viewport-mobile .fbp-canvas-body {
  max-width: 420px;
  margin: 0 auto;
}
.fbp-card {
  display: flex;
  align-items: stretch;
  gap: 0;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.12s, box-shadow 0.12s;
  overflow: hidden;
}
.fbp-card:hover {
  border-color: var(--line-strong);
  box-shadow: var(--sh-2);
}
.fbp-card.active {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.fbp-card-ghost {
  opacity: 0.4;
  background: var(--brand-soft);
}
.fbp-card-chosen {
  cursor: grabbing;
}
.fbp-card-drag {
  /* SortableJS 给被拖 element 加 — 透明半浮 */
  opacity: 0.85;
  cursor: grabbing;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.15);
}

/* ─── 2026-05-26 G1 真存追踪视觉 ────────────────────────────── */
/* 未保存新字段 (走 add endpoint): 虚线左边 + 橙色 */
.fbp-card-pending {
  border-style: dashed;
  border-color: var(--warn, #f59e0b);
  border-left-width: 3px;
  background: color-mix(in srgb, var(--warn, #f59e0b) 6%, var(--surface));
}
.fbp-card-pending:hover { border-color: var(--warn, #f59e0b); }
.fbp-card-pending.active {
  /* active 状态盖住 brand outline, 仍突出 pending */
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--warn, #f59e0b) 25%, transparent);
  border-color: var(--warn, #f59e0b);
}

/* 已存字段 (apaas 上有) 但改过: 右上小橙点提示 (绝对定位, 不挤 chip 行布局) */
.fbp-card-dirty .fbp-card-name::after {
  content: '';
  /* 不在 ::after, 用 badge */
}
.fbp-card-badge {
  font-size: 10.5px;
  line-height: 1.1;
  padding: 2px 7px;
  border-radius: 999px;
  font-weight: 600;
  letter-spacing: 0.2px;
}
.fbp-card-badge-pending {
  background: var(--warn, #f59e0b);
  color: #fff;
}
.fbp-card-badge-dirty {
  /* 仅小橙点 — 8x8 */
  display: inline-block;
  width: 8px; height: 8px;
  padding: 0;
  border-radius: 50%;
  background: var(--warn, #f59e0b);
}

/* 保存中的字段卡 overlay */
.fbp-card-saving {
  position: relative;
  pointer-events: none;
}
.fbp-card-saving-overlay {
  position: absolute;
  inset: 0;
  background: color-mix(in srgb, var(--surface) 70%, transparent);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2;
  border-radius: inherit;
}

/* ─── 保存按钮 — 数字 + spinner + has-dirty 橙脉冲 ────────── */
.fbp-btn-save.has-dirty {
  position: relative;
}
.fbp-btn-save.has-dirty::after {
  content: '';
  position: absolute;
  top: -2px;
  right: -2px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--warn, #f59e0b);
  box-shadow: 0 0 0 2px var(--surface);
  animation: fbp-pulse 1.6s ease-in-out infinite;
}
@keyframes fbp-pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.3); opacity: 0.7; }
}
.fbp-btn-save.saving {
  opacity: 0.85;
  cursor: progress;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.fbp-btn-spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 1.5px solid rgba(255, 255, 255, 0.45);
  border-top-color: #fff;
  border-radius: 50%;
  animation: fbp-spin 0.85s linear infinite;
  vertical-align: middle;
}

/* ─── 保存进度条 ───────────────────────────────────────────── */
.fbp-save-progress {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  background: color-mix(in srgb, var(--brand-soft) 60%, var(--surface));
  border-bottom: 1px solid var(--line);
  font-size: 12.5px;
  color: var(--text);
}
.fbp-save-progress-spin {
  width: 14px;
  height: 14px;
}
.fbp-save-progress-text {
  flex-shrink: 0;
}
.fbp-save-progress-current {
  color: var(--brand);
  font-weight: 500;
}
.fbp-save-progress-bar {
  flex: 1;
  height: 4px;
  background: var(--line);
  border-radius: 999px;
  overflow: hidden;
}
.fbp-save-progress-fill {
  height: 100%;
  background: var(--brand);
  border-radius: 999px;
  transition: width 0.2s ease;
}

/* 跨容器 drop hover — canvas list 接受 lib chip 推过来时显蓝边 */
.fbp-card-list {
  /* 最小可放区高度, 即使空也能 drop */
  min-height: 80px;
  position: relative;
  transition: background 0.15s, box-shadow 0.15s;
}
/* SortableJS 给 接收容器加 sortable-ghost (我们 ghost-class) 但 cross-group
   时 sortable 也会给 container 加 'sortable-drag-over' class 仅在 .vue-draggable 上
   不一定可靠. 用 .fbp-card-list-empty 加视觉提示已足够. */
.fbp-card-list-empty {
  min-height: 200px;
  border: 1px dashed var(--line-strong);
  border-radius: 10px;
  display: flex;
  align-items: stretch;
  justify-content: center;
  transition: border-color 0.15s, background 0.15s;
}
.fbp-card-list-empty:hover {
  /* 空表单 list hover (drag-over 时) 显蓝边 */
  border-color: var(--brand);
  background: var(--brand-soft);
}

.fbp-card-handle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  background: var(--surface-2);
  color: var(--text-4);
  cursor: grab;
  flex-shrink: 0;
}
.fbp-card-handle:hover { color: var(--text-3); background: var(--surface-3); }
.fbp-card-handle:active { cursor: grabbing; }

.fbp-card-body {
  flex: 1;
  padding: 10px 14px 12px;
  min-width: 0;
}
.fbp-card-label {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.fbp-card-name {
  font-size: 13.5px;
  font-weight: 500;
  color: var(--text);
}
.fbp-card-req {
  color: var(--err);
  font-weight: 700;
  margin-left: -4px;
}
.fbp-card-type-chip {
  display: inline-block;
  padding: 1.5px 8px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.1px;
}
.fbp-card-key {
  font-size: 11.5px;
  color: var(--text-4);
  margin-left: auto;
}
.fbp-card-preview {
  /* preview row */
  display: block;
  font-size: 12.5px;
}

.fbp-card-ops {
  display: flex;
  align-items: center;
  padding: 0 10px;
  opacity: 0;
  transition: opacity 0.12s;
}
.fbp-card:hover .fbp-card-ops { opacity: 1; }

/* ─── Preview widgets (inline FieldPreview renders these) ──── */
:deep(.fbp-pv-input) {
  width: 100%;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 12.5px;
  font-family: inherit;
  outline: none;
  resize: none;
}
:deep(textarea.fbp-pv-input) {
  height: auto;
  padding: 6px 10px;
  line-height: 1.5;
}
:deep(.fbp-pv-select),
:deep(.fbp-pv-pick),
:deep(.fbp-pv-upload),
:deep(.fbp-pv-color) {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--surface-2);
  font-size: 12.5px;
  color: var(--text-3);
}
:deep(.fbp-pv-select-text),
:deep(.fbp-pv-upload-text) { flex: 1; }
:deep(.fbp-pv-select-caret) { color: var(--text-4); font-size: 11px; }
:deep(.fbp-pv-switch) {
  display: inline-flex;
  align-items: center;
  width: 32px;
  height: 18px;
  padding: 2px;
  border-radius: 999px;
  background: var(--line-strong);
}
:deep(.fbp-pv-switch-knob) {
  width: 14px; height: 14px;
  background: var(--surface);
  border-radius: 50%;
  box-shadow: var(--sh-1);
}
:deep(.fbp-pv-chips) {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
:deep(.fbp-pv-chip) {
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 11.5px;
  border: 1px solid var(--line);
}
:deep(.fbp-pv-radio) {
  display: flex;
  gap: 12px;
  font-size: 12.5px;
  color: var(--text-2);
}
:deep(.fbp-pv-radio-item) {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
:deep(.fbp-pv-radio-dot) {
  width: 11px; height: 11px;
  border: 1.5px solid var(--text-4);
  border-radius: 50%;
}
:deep(.fbp-pv-color-swatch) {
  width: 14px; height: 14px; border-radius: 3px;
  border: 1px solid var(--line);
}
:deep(.fbp-pv-range) {
  display: flex;
  align-items: center;
  gap: 6px;
}
:deep(.fbp-pv-range-sep) { color: var(--text-4); font-size: 12px; }
:deep(.fbp-pv-avatar),
:deep(.fbp-pv-upload-icon) {
  font-size: 13px;
}
:deep(.fbp-pv-sig) {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  height: 40px;
  padding: 0 10px 8px;
  border: 1px dashed var(--line-strong);
  border-radius: 5px;
  background: var(--surface-2);
}
:deep(.fbp-pv-sig-line) {
  flex: 1;
  height: 1px;
  background: var(--text-4);
}
:deep(.fbp-pv-sig-text) {
  font-size: 11.5px;
  color: var(--text-4);
}
:deep(.fbp-pv-static) {
  padding: 6px 10px;
  font-size: 13px;
  color: var(--text);
  background: var(--surface-2);
  border-radius: 5px;
}
:deep(.fbp-pv-divider) {
  height: 1px;
  background: var(--line-strong);
  margin: 8px 0;
}
:deep(.fbp-pv-placeholder) {
  height: 24px;
  background: repeating-linear-gradient(
    45deg,
    var(--surface-2),
    var(--surface-2) 4px,
    var(--surface-3) 4px,
    var(--surface-3) 8px
  );
  border-radius: 4px;
  border: 1px dashed var(--line-strong);
}
:deep(.fbp-pv-layout) {
  padding: 12px 10px;
  text-align: center;
  font-size: 12px;
  color: var(--text-3);
  background: var(--surface-2);
  border: 1px dashed var(--line-strong);
  border-radius: 5px;
}
:deep(.fbp-pv-formbtn) {
  padding: 6px 14px;
  background: var(--brand);
  color: #fff;
  border: none;
  border-radius: 5px;
  font-size: 12.5px;
  font-family: inherit;
  cursor: default;
}

/* ─── canvas footer drop ───────────────────────────────────── */
.fbp-canvas-drop {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 14px 12px;
  margin-top: 4px;
  border: 1px dashed var(--line-strong);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text-3);
  font-size: 12.5px;
}
.fbp-canvas-drop-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--brand-soft);
  color: var(--brand);
  font-weight: 600;
}

/* ─── AI 浮起 ──────────────────────────────────────────────── */
.fbp-ai {
  position: absolute;
  right: 28px;
  bottom: 24px;
  width: 300px;
  background: var(--surface);
  border: 1px solid var(--line-strong);
  border-radius: 10px;
  box-shadow: var(--sh-4);
  z-index: 5;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.fbp-ai-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
}
.fbp-ai-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.fbp-ai-close {
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: var(--text-3);
  font-size: 18px;
  cursor: pointer;
  border-radius: 4px;
  font-family: inherit;
}
.fbp-ai-close:hover { background: var(--surface-2); color: var(--text); }

.fbp-ai-chips {
  display: flex;
  gap: 6px;
  padding: 10px 14px;
  flex-wrap: wrap;
}
.fbp-ai-chip {
  padding: 5px 10px;
  background: var(--brand-soft);
  border: 1px solid var(--brand-soft-2);
  color: var(--brand);
  border-radius: 999px;
  font-size: 11.5px;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.12s;
}
.fbp-ai-chip:hover { background: var(--brand-soft-2); }

.fbp-ai-tips {
  padding: 0 14px 8px;
  font-size: 11.5px;
  color: var(--text-3);
}
.fbp-ai-tips p { margin: 0 0 4px; }
.fbp-ai-tips ul {
  margin: 0;
  padding-left: 16px;
}
.fbp-ai-tips li { margin: 2px 0; color: var(--text-3); }

.fbp-ai-input {
  display: flex;
  gap: 6px;
  padding: 8px 12px 12px;
  border-top: 1px solid var(--line);
  background: var(--surface-2);
}
.fbp-ai-input input {
  flex: 1;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--surface);
  color: var(--text);
  font-size: 12px;
  font-family: inherit;
  outline: none;
}
.fbp-ai-input input:focus { border-color: var(--brand); }

/* ─── 右: 属性面板 ──────────────────────────────────────────── */
.fbp-props {
  background: var(--surface);
  border-left: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.fbp-props-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  height: 100%;
  color: var(--text-3);
  padding: 32px 16px;
  gap: 6px;
}
.fbp-props-empty-icon { font-size: 28px; }
.fbp-props-empty p { margin: 0; font-size: 13px; }
.fbp-props-empty .hint { font-size: 11.5px; color: var(--text-4); }

.fbp-props-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
}
.fbp-props-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text);
}

.fbp-props-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px 20px;
}

.fbp-row {
  margin-bottom: 12px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.fbp-row label {
  font-size: 11.5px;
  color: var(--text-3);
  font-weight: 500;
}
.fbp-row input,
.fbp-row select {
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--surface);
  color: var(--text);
  font-size: 12.5px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.12s;
}
.fbp-row input:focus,
.fbp-row select:focus { border-color: var(--brand); }
.fbp-row input.mono,
.fbp-row select { font-family: var(--font-mono); font-size: 12px; }
.fbp-row input[readonly],
.fbp-row input:disabled {
  background: var(--surface-2);
  color: var(--text-3);
  cursor: not-allowed;
}
.fbp-row-textarea {
  min-height: 56px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--surface);
  color: var(--text);
  font-family: inherit;
  font-size: 12.5px;
  resize: vertical;
  outline: none;
  transition: border-color 0.12s;
}
.fbp-row-textarea:focus { border-color: var(--brand); }

.fbp-switch-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 14px 0 16px;
  padding: 12px 12px;
  background: var(--surface-2);
  border-radius: 8px;
}
.fbp-switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
  color: var(--text-2);
}
.fbp-switch {
  width: 32px;
  height: 18px;
  padding: 2px;
  border-radius: 999px;
  background: var(--line-strong);
  border: none;
  cursor: pointer;
  transition: background 0.18s;
  position: relative;
  display: inline-flex;
  align-items: center;
}
.fbp-switch.on { background: var(--brand); }
.fbp-switch-knob {
  width: 14px;
  height: 14px;
  background: var(--surface);
  border-radius: 50%;
  box-shadow: var(--sh-2);
  transition: transform 0.18s var(--ease);
}
.fbp-switch.on .fbp-switch-knob { transform: translateX(14px); }

.fbp-options {
  margin: 16px 0;
  padding: 12px;
  background: var(--surface-2);
  border-radius: 8px;
}
.fbp-options-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.fbp-options-head label {
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-3);
}
.fbp-options-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.fbp-option-row {
  display: flex;
  align-items: center;
  gap: 4px;
}
.fbp-option-input {
  flex: 1;
  height: 26px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--surface);
  color: var(--text);
  font-size: 11.5px;
  font-family: inherit;
  outline: none;
  min-width: 0;
}
.fbp-option-input.mono { font-family: var(--font-mono); font-size: 11px; }
.fbp-option-input:focus { border-color: var(--brand); }
.fbp-options-empty {
  font-size: 11px;
  color: var(--text-4);
  text-align: center;
  padding: 6px 0;
}

.fbp-row-ai {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}

/* ─── Buttons ───────────────────────────────────────────────── */
.fbp-btn {
  height: 30px;
  padding: 0 14px;
  border-radius: 6px;
  font-size: 12.5px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  border: 1px solid transparent;
  white-space: nowrap;
  transition: background 0.12s, border-color 0.12s, color 0.12s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.fbp-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.fbp-btn-ghost {
  background: var(--surface);
  border-color: var(--line-strong);
  color: var(--text);
}
.fbp-btn-ghost:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand);
}
.fbp-btn-primary {
  background: var(--brand);
  color: #fff;
}
.fbp-btn-primary:hover:not(:disabled) {
  background: var(--brand-hover);
}
.fbp-btn-sm {
  height: 26px;
  padding: 0 10px;
  font-size: 11.5px;
}
.fbp-btn-icon { font-size: 13px; line-height: 1; }

.fbp-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 4px;
  color: var(--text-3);
  cursor: pointer;
  transition: all 0.12s;
}
.fbp-icon-btn:hover:not(:disabled) {
  background: var(--err-soft);
  color: var(--err);
  border-color: var(--err);
}

.fbp-link-btn {
  background: transparent;
  border: none;
  color: var(--brand);
  cursor: pointer;
  font-family: inherit;
  font-size: 12.5px;
  font-weight: 500;
  padding: 0;
}
.fbp-link-btn:hover { color: var(--brand-hover); text-decoration: underline; }
.fbp-link-btn-sm { font-size: 11.5px; }

.mono { font-family: var(--font-mono); }

/* ─── Transitions ───────────────────────────────────────────── */
.fbp-fade-enter-active,
.fbp-fade-leave-active {
  transition: opacity 0.15s, transform 0.15s var(--ease);
}
.fbp-fade-enter-from,
.fbp-fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

/* ─── Responsive — narrow viewport (< 1200px) 收起属性面板 ─── */
@media (max-width: 1200px) {
  .fbp-3col {
    grid-template-columns: 200px 1fr 260px;
  }
}
@media (max-width: 1000px) {
  .fbp-3col {
    grid-template-columns: 180px 1fr;
  }
  .fbp-props { display: none; }
}
</style>
