<!-- SpecDesignPanel.vue — design-v4 U3: SPEC 设计层 (跟"功能" tab 平行).

  设计 tab = 改 SPEC 文档 (长链: 改 1 处 → AI 把 SPEC 翻译成 apaas 配置改多处).
  跟"功能" tab (直接 iframe apaas 原生, 短链: 改 1 处 = 1 处) 平行.

  布局: 3 pane —
   - LEFT  nav-pane (240px):   11 章节, 4 分组
   - CENTER doc-pane (1fr):    markdown 风格章节渲染, hover 出"用对话改这段"
   - RIGHT chat-slot (360px):  P2 接 ConfigAssistant — MVP 显 placeholder

  数据来源 (MVP 复用现有 endpoint):
   - GET /applications/{appId}                                 — app 元数据
   - GET /applications/{appId}/section-content/roles           — 角色
   - GET /applications/{appId}/section-content/models?with_fields=true — 数据模型 + 字段
   - GET /applications/{appId}/section-content/dicts           — 字典
   - GET /applications/{appId}/section-content/menus           — 菜单
   - GET /applications/{appId}/section-content/processes       — 流程
   - GET /applications/{appId}/datasources                     — 数据源

  视觉 100% 跟 docs/internal/design-tab-mockup-2026-05-27.html 视图 ① 对齐.
  设计 token 完全用 design-v3-tokens.css (`var(--brand)` / `var(--surface)` 等).

  ⚠️ MVP 不接 chat / 不做版本对比 / "确认并生成" disabled (P2).
-->
<template>
  <section class="sdp" aria-label="SPEC 设计">
    <!-- ── 顶部 toolbar ────────────────────────────────────────────────── -->
    <div class="sdp-toolbar">
      <!-- 版本 pill — 2026-05-27 升级: dropdown 列历史版本 -->
      <div ref="versionDropdownRef" class="version-pill-wrap">
        <button
          class="version-pill"
          :title="draftHint"
          type="button"
          :aria-expanded="versionDropdownOpen"
          aria-haspopup="listbox"
          @click="toggleVersionDropdown"
        >
          <span
            class="dot"
            :class="{ draft: selectedVersionId === null, prod: selectedVersionId !== null }"
            aria-hidden="true"
          ></span>
          <span class="version-pill-label">{{ versionPillLabel }}</span>
          <span class="arrow" aria-hidden="true">▾</span>
        </button>
        <div v-if="versionDropdownOpen" class="version-dropdown" role="listbox">
          <button
            class="version-dropdown-item"
            :class="{ active: selectedVersionId === null }"
            type="button"
            role="option"
            :aria-selected="selectedVersionId === null"
            @click="onSelectVersion(null)"
          >
            <span class="version-dropdown-dot draft" aria-hidden="true"></span>
            <span class="version-dropdown-main">
              <span class="version-dropdown-label">草稿 (当前)</span>
              <span class="version-dropdown-sub">{{ diffTotalCount > 0 ? `${diffTotalCount} 处未应用` : '尚无改动' }}</span>
            </span>
          </button>
          <div v-if="versionsLoading" class="version-dropdown-empty">加载历史中…</div>
          <template v-else-if="versions.length > 0">
            <button
              v-for="v in versions"
              :key="String(v.id)"
              class="version-dropdown-item"
              :class="{ active: String(selectedVersionId) === String(v.id), 'is-active-prod': v.is_active }"
              type="button"
              role="option"
              :aria-selected="String(selectedVersionId) === String(v.id)"
              @click="onSelectVersion(v.id)"
            >
              <span class="version-dropdown-dot" :class="{ prod: v.is_active }" aria-hidden="true"></span>
              <span class="version-dropdown-main">
                <span class="version-dropdown-label">
                  {{ v.version_label }}
                  <span v-if="v.is_active" class="version-dropdown-tag">当前生产</span>
                </span>
                <span class="version-dropdown-sub">{{ versionSubtitle(v) || '—' }}</span>
              </span>
            </button>
          </template>
          <div v-else class="version-dropdown-empty">尚无应用过的历史版本</div>
        </div>
      </div>
      <!-- mode pill (阅读 / 对比) — V1 Part B: 对比模式接通 -->
      <div class="mode-pill" role="tablist" aria-label="视图模式">
        <button
          :class="{ active: viewMode === 'read' }"
          role="tab"
          :aria-selected="viewMode === 'read'"
          type="button"
          @click="onSwitchMode('read')"
        >
          <span aria-hidden="true">📖</span> 阅读
        </button>
        <button
          :class="{ active: viewMode === 'compare' }"
          role="tab"
          :aria-selected="viewMode === 'compare'"
          type="button"
          :disabled="loading"
          :title="viewMode === 'compare' ? '切回阅读模式' : '草稿 vs 生产 对比 (MVP 仅数据模型显精细差异)'"
          @click="onSwitchMode('compare')"
        >
          <span aria-hidden="true">🔍</span> 对比
          <span v-if="diffTotalCount > 0" class="mode-pill-badge">{{ diffTotalCount }}</span>
        </button>
      </div>
      <div class="toolbar-divider" aria-hidden="true"></div>
      <button
        class="toolbar-btn"
        type="button"
        :disabled="exporting"
        :title="exporting ? '导出中…' : '导出 SPEC 为 .md 文件 (调 /spec/export.md)'"
        @click="onExportMd"
      >
        <span aria-hidden="true">⬇</span> {{ exporting ? '导出中…' : '导出 .md' }}
      </button>
      <button class="toolbar-btn" disabled title="P2 接入">
        <span aria-hidden="true">📜</span> 历史
      </button>
      <div class="spacer"></div>
      <button
        class="apply-cta"
        :disabled="viewMode === 'compare'"
        :title="applyCtaTitle"
        @click="onOpenApplyModal"
      >
        <span aria-hidden="true">✨</span> 确认并生成
        <span v-if="diffTotalCount > 0" class="apply-cta-count">[{{ diffTotalCount }}]</span>
      </button>
    </div>

    <!-- ── 3 pane shell ────────────────────────────────────────────────── -->
    <div class="sdp-shell">

      <!-- LEFT: chapter nav -->
      <nav class="sdp-nav-pane" aria-label="章节导航">
        <div
          v-for="group in CHAPTER_GROUPS"
          :key="group.key"
          class="nav-section"
        >
          <div class="nav-section-title">{{ group.title }}</div>
          <button
            v-for="ch in group.items"
            :key="ch.key"
            class="nav-item"
            :class="{ active: activeChapter === ch.key }"
            type="button"
            @click="onChapterClick(ch.key)"
          >
            <span class="num">{{ ch.num }}</span>
            <span class="label">{{ ch.title }}</span>
            <!-- V1 Part B: 对比模式下显 +X / ~Y / 无差异 -->
            <span
              v-if="viewMode === 'compare'"
              class="nav-diff-badge"
              :class="{ 'nav-diff-badge-zero': chapterDiffLabel(ch.key) === '无差异' }"
            >{{ chapterDiffLabel(ch.key) }}</span>
          </button>
        </div>
      </nav>

      <!-- CENTER: SPEC doc — 阅读模式 (read mode) -->
      <main v-if="viewMode === 'read'" class="sdp-doc-pane" ref="docPaneRef">
        <!-- doc header -->
        <div class="doc-title-row">
          <h1 class="doc-title">{{ appName }}</h1>
          <div class="doc-meta">
            <span v-if="appCode" class="mono">{{ appCode }}</span>
            <template v-if="appCode"><span>·</span></template>
            <span>草稿</span>
            <span>·</span>
            <span>{{ lastFetchedLabel }}</span>
          </div>
        </div>

        <!-- 草稿提示 banner -->
        <div class="doc-version-banner" role="status">
          <span aria-hidden="true">⚠️</span>
          <span>
            这里渲染应用的 <strong>SPEC 文档</strong> — 跟"功能" tab 直接改 apaas
            不同, 设计 tab 改的是<strong>语义描述</strong>, 由 AI 把改动翻译成
            apaas 平台配置. 当前为 read-only 预览 (P2 接入编辑).
          </span>
        </div>

        <!-- loading -->
        <div v-if="loading" class="state-block">
          <div class="spinner" aria-hidden="true"></div>
          <span>加载 SPEC 中…</span>
        </div>

        <!-- error -->
        <div v-else-if="error" class="state-block state-err">
          <div class="state-icon" aria-hidden="true">⚠️</div>
          <p>{{ error }}</p>
          <button class="toolbar-btn" type="button" @click="reload">重试</button>
        </div>

        <!-- 章节内容 (load 完成后渲染) -->
        <template v-else>
          <section
            v-for="ch in CHAPTERS"
            :key="ch.key"
            :id="`sec-${ch.key}`"
            class="section"
            :ref="el => bindSectionRef(ch.key, el as HTMLElement | null)"
          >
            <div class="section-head">
              <h2>{{ ch.num }}、{{ ch.title }}</h2>
              <button
                class="section-edit-btn"
                type="button"
                @click="onEditChapter(ch.key)"
                title="P2 接入 — 用对话改这段 SPEC"
              >
                <span aria-hidden="true">✨</span> 用对话改这段
              </button>
            </div>

            <!-- 章节内容 (按 key 分发) -->
            <!-- 一、应用信息 -->
            <template v-if="ch.key === 'app_info'">
              <table class="spec-table">
                <thead>
                  <tr><th style="width: 28%">字段</th><th>值</th></tr>
                </thead>
                <tbody>
                  <tr><td>应用名称</td><td>{{ appName || '—' }}</td></tr>
                  <tr><td>应用编码</td><td><span class="mono">{{ appCode || '—' }}</span></td></tr>
                  <tr v-if="appDescription"><td>应用描述</td><td>{{ appDescription }}</td></tr>
                  <tr v-if="apaasAppIdShown">
                    <td>aPaaS 应用 ID</td>
                    <td><span class="mono">{{ apaasAppIdShown }}</span></td>
                  </tr>
                  <tr v-if="appCreatedAt">
                    <td>创建时间</td>
                    <td>{{ appCreatedAt }}</td>
                  </tr>
                </tbody>
              </table>
            </template>

            <!-- 二、角色与权限 -->
            <template v-else-if="ch.key === 'roles'">
              <div v-if="loadedRoles.length === 0" class="subsection-empty">
                尚未配置角色 — 用对话或去权限 tab 添加.
              </div>
              <table v-else class="spec-table">
                <thead>
                  <tr><th>角色名称</th><th>编码</th><th>说明</th></tr>
                </thead>
                <tbody>
                  <tr v-for="r in loadedRoles" :key="r.id">
                    <td>{{ r.name }}</td>
                    <td><span class="mono">{{ r.code || '—' }}</span></td>
                    <td>{{ describeExtra(r.extra, 'description') || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </template>

            <!-- 三、数据模型 -->
            <template v-else-if="ch.key === 'data_model'">
              <div v-if="loadedModels.length === 0" class="subsection-empty">
                尚未定义数据模型 — 用对话添加模型, 或去"功能"tab 选菜单看真实配置.
              </div>
              <div
                v-for="m in loadedModels"
                :key="m.id"
                class="subsection"
              >
                <h3>
                  {{ m.name }}
                  <span v-if="m.code" class="mono code-after-h3">({{ m.code }})</span>
                </h3>
                <table v-if="modelFields(m).length" class="spec-table">
                  <thead>
                    <tr>
                      <th>字段名</th>
                      <th>code</th>
                      <th>类型</th>
                      <th>必填</th>
                      <th>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="f in modelFields(m)" :key="String(f.code || f.id || f.name)">
                      <td>{{ f.name || '—' }}</td>
                      <td><span class="mono">{{ f.code || '—' }}</span></td>
                      <td><span class="type-chip">{{ f.type || '—' }}</span></td>
                      <td>
                        <span v-if="f.required" class="required-mark">*</span>
                        <span v-else class="muted">—</span>
                      </td>
                      <td>{{ f.description || '—' }}</td>
                    </tr>
                  </tbody>
                </table>
                <div v-else class="subsection-empty">该模型未拉到字段详情.</div>
              </div>
            </template>

            <!-- 四、数据字典 -->
            <template v-else-if="ch.key === 'dict'">
              <div v-if="loadedDicts.length === 0" class="subsection-empty">
                尚未定义数据字典.
              </div>
              <div v-for="d in loadedDicts" :key="d.id" class="subsection">
                <h3>
                  {{ d.name }}
                  <span v-if="d.code" class="mono code-after-h3">({{ d.code }})</span>
                </h3>
                <table v-if="dictItems(d).length" class="spec-table">
                  <thead>
                    <tr><th>code</th><th>名称</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="di in dictItems(d)" :key="String(di.code || di.value || di.name)">
                      <td><span class="mono">{{ di.code || di.value || '—' }}</span></td>
                      <td>{{ di.name || di.label || '—' }}</td>
                    </tr>
                  </tbody>
                </table>
                <div v-else class="subsection-empty subsection-empty-soft">字典项明细未拉到.</div>
              </div>
            </template>

            <!-- 五、菜单结构 -->
            <template v-else-if="ch.key === 'menus'">
              <div v-if="loadedMenus.length === 0" class="subsection-empty">
                尚未定义菜单.
              </div>
              <table v-else class="spec-table">
                <thead>
                  <tr>
                    <th>菜单名称</th>
                    <th>编码</th>
                    <th>类型</th>
                    <th>关联表单/页面</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="m in loadedMenus" :key="m.id">
                    <td>{{ m.name }}</td>
                    <td><span class="mono">{{ m.code || '—' }}</span></td>
                    <td>
                      <span class="type-chip">{{
                        describeExtra(m.extra, 'menu_type') || describeExtra(m.extra, 'type') || '—'
                      }}</span>
                    </td>
                    <td>
                      <span class="mono">{{
                        describeExtra(m.extra, 'form_id') || describeExtra(m.extra, 'page_url') || '—'
                      }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </template>

            <!-- 六、表单设计 — X (2026-05-27): 真渲染每个 MODEL menu 的表单关联 -->
            <template v-else-if="ch.key === 'form'">
              <div v-if="modelMenus.length === 0" class="subsection-empty">
                没有挂表单的菜单. 用对话加 "新建借书申请表单" 之类.
              </div>
              <template v-else>
                <p class="ch-intro">
                  应用共 <strong>{{ modelMenus.length }}</strong> 个表单
                  (跟 MODEL 类型菜单 1:1).
                  字段定义详见<strong>三、数据模型</strong>; 这里列每个表单的菜单挂载点.
                </p>
                <table class="spec-table">
                  <thead>
                    <tr>
                      <th>菜单名</th>
                      <th>菜单编码</th>
                      <th>关联表单 ID</th>
                      <th>表单 code</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="m in modelMenus" :key="m.id">
                      <td>{{ m.name }}</td>
                      <td><span class="mono">{{ m.code || '—' }}</span></td>
                      <td><span class="mono">{{ describeExtra(m.extra, 'form_id') || '—' }}</span></td>
                      <td><span class="mono">{{ describeExtra(m.extra, 'form_code') || '—' }}</span></td>
                    </tr>
                  </tbody>
                </table>
                <p class="hint">
                  布局 / 必填 / 字段权限请去 "功能" tab 选对应菜单 → 表单设计 panel 改.
                  下次 sprint 接 list_apaas_form_components 把字段标记 (必填 / 权限) 显这.
                </p>
              </template>
            </template>

            <!-- 七、列表设计 — X (2026-05-27): 同样真渲染 MODEL menu list -->
            <template v-else-if="ch.key === 'list'">
              <div v-if="modelMenus.length === 0" class="subsection-empty">
                没有挂列表的菜单.
              </div>
              <template v-else>
                <p class="ch-intro">
                  每个 MODEL 菜单含 1 个列表视图 (跟表单 1:1 同 form_id).
                </p>
                <table class="spec-table">
                  <thead>
                    <tr>
                      <th>菜单名</th>
                      <th>表单 ID</th>
                      <th>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="m in modelMenus" :key="m.id">
                      <td>{{ m.name }}</td>
                      <td><span class="mono">{{ describeExtra(m.extra, 'form_id') || '—' }}</span></td>
                      <td class="text-3">查询条件 / 列字段 详见"功能" tab → 列表设计</td>
                    </tr>
                  </tbody>
                </table>
                <p class="hint">
                  下次 sprint 接 listPageView (queryConditions + queryList) 直接显这.
                </p>
              </template>
            </template>

            <!-- 八、业务流程 (2026-05-27: 拆出业务事件到九, 这里只渲流程) -->
            <template v-else-if="ch.key === 'process'">
              <div v-if="loadedProcesses.length === 0" class="subsection-empty">
                尚未定义流程 — 用对话添加流程, 或去"功能"tab 选菜单 → 流程设计.
              </div>
              <table v-else class="spec-table">
                <thead>
                  <tr>
                    <th>流程名称</th>
                    <th>编码</th>
                    <th>关联表单</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="p in loadedProcesses" :key="p.id">
                    <td>{{ p.name }}</td>
                    <td><span class="mono">{{ p.code || '—' }}</span></td>
                    <td>
                      <span class="mono">{{
                        describeExtra(p.extra, 'form_id') || describeExtra(p.extra, 'form_code') || '—'
                      }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </template>

            <!-- 九、业务事件 (2026-05-27: 新加 — 拉 /section-content/business-events) -->
            <template v-else-if="ch.key === 'event'">
              <div v-if="loadedEvents.length === 0" class="subsection-empty">
                尚未定义业务事件 — 用对话添加事件触发器,
                或去 "功能" tab → 流程设计 panel 查看.
              </div>
              <table v-else class="spec-table">
                <thead>
                  <tr>
                    <th>事件名称</th>
                    <th>编码</th>
                    <th>触发类型</th>
                    <th>关联资源</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="e in loadedEvents" :key="e.id">
                    <td>{{ e.name }}</td>
                    <td><span class="mono">{{ e.code || '—' }}</span></td>
                    <td><span class="type-chip">{{ describeExtra(e.extra, 'event_type') || describeExtra(e.extra, 'trigger') || '—' }}</span></td>
                    <td><span class="mono">{{ describeExtra(e.extra, 'target') || describeExtra(e.extra, 'form_id') || '—' }}</span></td>
                  </tr>
                </tbody>
              </table>
            </template>

            <!-- 十、集成 & 自开发 — X (2026-05-27): 真渲染 CUSTOM menu list -->
            <template v-else-if="ch.key === 'integration'">
              <div v-if="customMenus.length === 0" class="subsection-empty">
                无自开发页面 (CUSTOM 菜单).
                <p class="hint">用 Vibe Coding / 在线 IDE 写自定义 Vue 页, 部署后挂菜单.</p>
              </div>
              <template v-else>
                <p class="ch-intro">
                  应用含 <strong>{{ customMenus.length }}</strong> 个自开发 Vue 页 (CUSTOM 类型菜单).
                </p>
                <table class="spec-table">
                  <thead>
                    <tr>
                      <th>菜单名</th>
                      <th>组件 / 页面 code</th>
                      <th>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="m in customMenus" :key="m.id">
                      <td>{{ m.name }}</td>
                      <td><span class="mono">{{ describeExtra(m.extra, 'link_url') || '—' }}</span></td>
                      <td class="text-3">详见"功能" tab 选该菜单, 跳 IDE 改 Vue 源码</td>
                    </tr>
                  </tbody>
                </table>
                <p class="hint">
                  P5: 加 API 集成 / Webhook 配置列表 (现 apaas 无对应 schema).
                </p>
              </template>
            </template>

            <!-- 十一、数据源 -->
            <template v-else-if="ch.key === 'datasource'">
              <div v-if="datasourceNote" class="subsection-empty subsection-empty-soft">
                {{ datasourceNote }}
              </div>
              <table v-else-if="loadedDatasources.length" class="spec-table">
                <thead>
                  <tr>
                    <th>数据源名称</th>
                    <th>类型</th>
                    <th>连接</th>
                    <th>关联模型</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="ds in loadedDatasources" :key="ds.datasource_id || ds.name">
                    <td>{{ ds.name || '—' }}</td>
                    <td><span class="type-chip">{{ ds.type || '—' }}</span></td>
                    <td class="mono">
                      <template v-if="ds.host">{{ ds.host }}<template v-if="ds.port">:{{ ds.port }}</template></template>
                      <template v-else>—</template>
                    </td>
                    <td><span class="muted">{{ ds.model_count ?? 0 }}</span></td>
                  </tr>
                </tbody>
              </table>
              <div v-else class="subsection-empty">尚未关联数据源.</div>
            </template>
          </section>
        </template>
      </main>

      <!-- V1 Part B: 对比模式 (compare mode) — side-by-side 2 col (v1.1 vs 草稿) -->
      <main v-else-if="viewMode === 'compare'" class="sdp-compare-shell" aria-label="SPEC 对比">
        <!-- LEFT col: 生产 (v1.1) -->
        <div class="sdp-compare-col">
          <div class="sdp-compare-col-head left">
            <span class="sdp-compare-col-dot" aria-hidden="true">●</span>
            <span class="sdp-compare-col-ver">v1.1 (生产)</span>
            <span class="sdp-compare-col-meta">apaas 真实状态</span>
          </div>

          <!-- compare loading -->
          <div v-if="compareLoading" class="state-block">
            <div class="spinner" aria-hidden="true"></div>
            <span>加载对比草稿中…</span>
          </div>

          <!-- 章节渲染 — 跟 read mode 一致结构, 但只渲 active section 让对照集中 -->
          <template v-else>
            <section
              v-for="ch in CHAPTERS"
              :key="`prod-${ch.key}`"
              :id="`sec-prod-${ch.key}`"
              class="section section-compare"
            >
              <div class="section-head section-head-compare">
                <h2>{{ ch.num }}、{{ ch.title }}</h2>
              </div>

              <!-- 数据模型: 跟 read mode 同结构, 字段不染色 (这是基线) -->
              <template v-if="ch.key === 'data_model'">
                <div v-if="loadedModels.length === 0" class="subsection-empty">
                  生产无数据模型.
                </div>
                <div v-for="m in loadedModels" :key="`prod-${m.id}`" class="subsection">
                  <h3>
                    {{ m.name }}
                    <span v-if="m.code" class="mono code-after-h3">({{ m.code }})</span>
                  </h3>
                  <table v-if="modelFields(m).length" class="spec-table">
                    <thead>
                      <tr>
                        <th>字段名</th>
                        <th>code</th>
                        <th>类型</th>
                        <th>必填</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="f in modelFields(m)"
                        :key="`prod-${m.id}-${String(f.code || f.name)}`"
                        :class="{ 'sdp-diff-row-del': isFieldDeletedInDraft(m, f) }"
                      >
                        <td><span :class="{ 'sdp-diff-cell-del': isFieldDeletedInDraft(m, f) }">{{ f.name || '—' }}</span></td>
                        <td><span class="mono" :class="{ 'sdp-diff-cell-del': isFieldDeletedInDraft(m, f) }">{{ f.code || '—' }}</span></td>
                        <td><span class="type-chip">{{ f.type || '—' }}</span></td>
                        <td>
                          <span v-if="f.required" class="required-mark">*</span>
                          <span v-else class="muted">—</span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                  <div v-else class="subsection-empty">该模型未拉到字段详情.</div>
                </div>
                <!-- 草稿新增的模型 在生产侧显占位 (跟 mockup 视图 ② 一致) -->
                <div
                  v-for="m in comparedModels.filter(x => x.is_added_in_draft)"
                  :key="`prod-placeholder-${m.code}`"
                  class="subsection sdp-compare-placeholder"
                >
                  <div class="subsection-empty subsection-empty-soft">
                    (无 "{{ m.name }}" 模型 — 草稿新增)
                  </div>
                </div>
              </template>

              <!-- 非 data_model 章节: MVP 只显占位 (SPEC chat 当前只能改 4 类) -->
              <template v-else>
                <div class="subsection-empty subsection-empty-soft">
                  <strong>{{ ch.title }}</strong> — 草稿 vs 生产 无差异 (MVP 仅数据模型支持精细 diff).
                </div>
              </template>
            </section>
          </template>
        </div>

        <!-- RIGHT col: 草稿 -->
        <div class="sdp-compare-col">
          <div class="sdp-compare-col-head right">
            <span class="sdp-compare-col-dot draft" aria-hidden="true">●</span>
            <span class="sdp-compare-col-ver">草稿</span>
            <span class="sdp-compare-col-meta">{{ compareDraftMeta }}</span>
          </div>

          <div v-if="compareLoading" class="state-block">
            <div class="spinner" aria-hidden="true"></div>
            <span>加载对比草稿中…</span>
          </div>

          <template v-else>
            <section
              v-for="ch in CHAPTERS"
              :key="`draft-${ch.key}`"
              :id="`sec-draft-${ch.key}`"
              class="section section-compare"
            >
              <div class="section-head section-head-compare">
                <h2>{{ ch.num }}、{{ ch.title }}</h2>
                <span
                  v-if="viewMode === 'compare' && chapterDiffLabel(ch.key) !== '无差异'"
                  class="sdp-changed-chip"
                >{{ chapterDiffLabel(ch.key) }}</span>
              </div>

              <!-- 数据模型: 草稿渲染 + 新增字段 / 新增模型 染色 -->
              <template v-if="ch.key === 'data_model'">
                <div v-if="!hasAnyDraftModel && loadedModels.length === 0" class="subsection-empty">
                  尚无草稿改动.
                </div>
                <!-- 渲染所有 (生产 ∪ 草稿) 的模型 -->
                <div
                  v-for="m in comparedModels"
                  :key="`draft-${m.code || m.id}`"
                  class="subsection"
                  :class="{ 'sdp-diff-subsection-add': m.is_added_in_draft }"
                >
                  <h3>
                    <span :class="{ 'sdp-diff-cell-add': m.is_added_in_draft }">
                      {{ m.name }}
                      <span v-if="m.code" class="mono code-after-h3">({{ m.code }})</span>
                      <span v-if="m.is_added_in_draft" class="sdp-changed-chip">新模型</span>
                    </span>
                  </h3>
                  <table v-if="m.compared_fields.length" class="spec-table">
                    <thead>
                      <tr>
                        <th>字段名</th>
                        <th>code</th>
                        <th>类型</th>
                        <th>必填</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="f in m.compared_fields"
                        :key="`draft-${m.code}-${String(f.code || f.name)}`"
                        :class="{
                          'sdp-diff-row-add': f.diff_kind === 'add',
                          'sdp-diff-row-del': f.diff_kind === 'del',
                        }"
                      >
                        <td>
                          <span :class="{
                            'sdp-diff-cell-add': f.diff_kind === 'add',
                            'sdp-diff-cell-del': f.diff_kind === 'del',
                          }">{{ f.name || '—' }}</span>
                        </td>
                        <td>
                          <span class="mono" :class="{
                            'sdp-diff-cell-add': f.diff_kind === 'add',
                            'sdp-diff-cell-del': f.diff_kind === 'del',
                          }">{{ f.code || '—' }}</span>
                        </td>
                        <td>
                          <span class="type-chip" :class="{
                            'sdp-diff-cell-add': f.diff_kind === 'add',
                            'sdp-diff-cell-del': f.diff_kind === 'del',
                          }">{{ f.type || '—' }}</span>
                        </td>
                        <td>
                          <span v-if="f.required" class="required-mark">*</span>
                          <span v-else class="muted">—</span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                  <div v-else class="subsection-empty">该模型未拉到字段详情.</div>
                </div>
              </template>

              <template v-else>
                <div class="subsection-empty subsection-empty-soft">
                  <strong>{{ ch.title }}</strong> — 草稿 vs 生产 无差异 (MVP 仅数据模型支持精细 diff).
                </div>
              </template>
            </section>
          </template>
        </div>
      </main>

      <!-- RIGHT: chat slot — U7 接通 SpecChatPanel (内嵌对话改 SPEC 草稿) -->
      <aside class="sdp-chat-slot" aria-label="SPEC 对话助手">
        <SpecChatPanel
          ref="specChatRef"
          :app-id="props.appId"
          :apaas-app-id="props.apaasAppId"
          :active-chapter="activeChapter"
          :chapter-title="currentChapterTitle"
          @spec-updated="onSpecUpdated"
        />
      </aside>
    </div>

    <!-- V3 (2026-05-27): 确认并生成 modal — list plan + 串行 MCP (MVP dry-run) -->
    <SpecApplyModal
      :app-id="props.appId"
      :visible="applyModalOpen"
      @close="applyModalOpen = false"
      @applied="onApplyDone"
    />
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import request, { API_PREFIX } from '@/utils/request'
import SpecChatPanel from './SpecChatPanel.vue'
import SpecApplyModal from './SpecApplyModal.vue'

// ── props ──────────────────────────────────────────────────────────────
const props = defineProps<{
  appId: number
  apaasAppId?: string
}>()

// ── 章节定义 ────────────────────────────────────────────────────────────
type ChapterKey =
  | 'app_info'
  | 'roles'
  | 'data_model'
  | 'dict'
  | 'menus'
  | 'form'
  | 'list'
  | 'process'
  | 'event'
  | 'integration'
  | 'datasource'

interface ChapterDef {
  key: ChapterKey
  title: string
  group: '基础' | '数据' | '功能' | '扩展'
  num: string
}

// 2026-05-27 升级: 拆 "流程 & 事件" → 八、业务流程 + 九、业务事件 (10 → 11 章)
const CHAPTERS: ChapterDef[] = [
  { key: 'app_info',    title: '应用信息',      group: '基础', num: '一' },
  { key: 'roles',       title: '角色与权限',    group: '基础', num: '二' },
  { key: 'data_model',  title: '数据模型',      group: '数据', num: '三' },
  { key: 'dict',        title: '数据字典',      group: '数据', num: '四' },
  { key: 'menus',       title: '菜单结构',      group: '功能', num: '五' },
  { key: 'form',        title: '表单设计',      group: '功能', num: '六' },
  { key: 'list',        title: '列表设计',      group: '功能', num: '七' },
  { key: 'process',     title: '业务流程',      group: '功能', num: '八' },
  { key: 'event',       title: '业务事件',      group: '功能', num: '九' },
  { key: 'integration', title: '集成 & 自开发', group: '扩展', num: '十' },
  { key: 'datasource',  title: '数据源',        group: '扩展', num: '十一' },
]

const CHAPTER_GROUPS = computed(() => {
  const groups: Array<{ key: string; title: string; items: ChapterDef[] }> = []
  for (const ch of CHAPTERS) {
    let g = groups.find(x => x.title === ch.group)
    if (!g) {
      g = { key: ch.group, title: ch.group, items: [] }
      groups.push(g)
    }
    g.items.push(ch)
  }
  return groups
})

// ── 数据接口 (跟 section-content endpoint 对齐) ──────────────────────────
interface SectionItem {
  id: string
  name: string
  code?: string | null
  extra?: Record<string, any>
}

interface SectionResp {
  ok: boolean
  items?: SectionItem[]
  total?: number
  error_code?: string
  message?: string
}

interface DatasourceItem {
  datasource_id?: string
  name?: string
  type?: string
  host?: string | null
  port?: number | null
  model_count?: number
}

// ── 2026-05-27 升级: 版本历史 (拉 /spec/versions, 优雅 404 fallback) ─────
interface SpecVersion {
  id: number | string
  version_label: string
  applied_at?: string | null
  applied_by_user_id?: number | string | null
  applied_by_username?: string | null
  applied_steps?: number | null
  failed_steps?: number | null
  is_active?: boolean
}

const versions = ref<SpecVersion[]>([])
const versionsLoading = ref(false)
const versionDropdownOpen = ref(false)
// 选中"草稿" (null) 或某历史版本 ID — MVP 仅做 UI 切换 + toast, 详细 snapshot 留 P3
const selectedVersionId = ref<number | string | null>(null)
const versionDropdownRef = ref<HTMLElement | null>(null)

// ── reactive state ─────────────────────────────────────────────────────
const loading = ref(true)
const error = ref('')
const lastFetchedAt = ref<Date | null>(null)
// 默认选中第三章 (数据模型) — 跟 mockup 截图一致
const activeChapter = ref<ChapterKey>('data_model')

const docPaneRef = ref<HTMLElement | null>(null)
const sectionRefs = ref<Record<string, HTMLElement | null>>({})
function bindSectionRef(key: string, el: HTMLElement | null) {
  sectionRefs.value[key] = el
}

// V1 Part A: SpecChatPanel ref — 章节锚点 "用对话改这段" 联动 chat input focus.
// 通过 defineExpose 暴露的 focusInput() 让用户点 "用对话改这段" 后:
//   1. 切到该章节 (activeChapter.value = key) → ChatPanel ctx chip / quick chips 自动联动
//   2. textarea autofocus + scroll into view → 用户无需再点 chat 区就能直接打字
const specChatRef = ref<{ focusInput?: () => void } | null>(null)

// app 元数据
const appName = ref('')
const appCode = ref('')
const appDescription = ref('')
const appCreatedAt = ref('')

// section 数据
const loadedRoles = ref<SectionItem[]>([])
const loadedModels = ref<SectionItem[]>([])
const loadedDicts = ref<SectionItem[]>([])
const loadedMenus = ref<SectionItem[]>([])
const loadedProcesses = ref<SectionItem[]>([])
const loadedEvents = ref<SectionItem[]>([])  // 2026-05-27: 业务事件章节 (九)

// X (2026-05-27): 按 menu_type 分组 — 六/七 章用 MODEL 菜单, 九 章用 CUSTOM 菜单.
// MODEL = 数据驱动表单/列表; CUSTOM = 自开发 Vue 页.
const modelMenus = computed(() => loadedMenus.value.filter(m => {
  const t = String(m.extra?.menu_type || '').toUpperCase()
  return t === 'MODEL' || t === 'MENU_TYPE_MODEL'
}))
const customMenus = computed(() => loadedMenus.value.filter(m => {
  const t = String(m.extra?.menu_type || '').toUpperCase()
  return t === 'CUSTOM' || t === 'MENU_TYPE_CUSTOM'
}))
const loadedDatasources = ref<DatasourceItem[]>([])
const datasourceNote = ref('')

// ── V1 Part B: 对比模式 (compare mode) state ────────────────────────────
// viewMode = 'read'    单列 SPEC 渲染 (现有行为)
// viewMode = 'compare' 双列 v1.1 (生产 / apaas 真状态) vs 草稿 (spec_sections)
//
// 数据来源:
//   生产: loadedModels (现有, apaas /section-content/models 真实状态)
//   草稿: draftSections (新加, /applications/{id}/spec-sections/data_model/{code})
//         为 null 表示该模型尚无草稿 → diff=0
//
// MVP 简化:
//   - 只对 data_model 做精细 field-级 diff
//   - 其他章节 (roles/dict/menus/process/event/form/list/integration/datasource) 显占位
//   - update-level diff (字段 attr 改了, e.g., required) MVP 不算
//   - 删除字段也算 — 草稿里没该 code 但生产里有 → 'del'
const viewMode = ref<'read' | 'compare'>('read')
const compareLoading = ref(false)
const compareDraftFetchedAt = ref<Date | null>(null)

// draftSections: key = data_model.section_key (=model_code), value = { spec_json, draft_version, updated_at }
interface DraftSectionEntry {
  spec_json: any
  draft_version: number
  updated_at: string | null
}
const draftSections = ref<Record<string, DraftSectionEntry>>({})

// 跟 read mode 拿到的 modelFields() 一致的 shape, 加 diff_kind
interface ComparedField extends ModelField {
  diff_kind?: 'add' | 'del' | 'unchanged'
}
interface ComparedModel {
  id: string
  code: string
  name: string
  is_added_in_draft: boolean   // 草稿里新增的模型 (生产无此 model_code)
  compared_fields: ComparedField[]
}

// ── computed display ──────────────────────────────────────────────────
const apaasAppIdShown = computed(() => props.apaasAppId || '')

const lastFetchedLabel = computed(() => {
  if (!lastFetchedAt.value) return '加载中…'
  const d = lastFetchedAt.value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
})

const draftHint = computed(() => 'MVP: 当前为 SPEC 只读预览, 编辑接 P2')

// ── 字段 / 字典项 解构 helpers ─────────────────────────────────────────
interface ModelField {
  id?: string
  name?: string
  code?: string
  type?: string
  required?: boolean
  description?: string
}

function modelFields(m: SectionItem): ModelField[] {
  const extra = m.extra || {}
  // backend with_fields=true → extra 含 fields[]
  const raw = (extra.fields || extra.components || extra.columns || []) as any[]
  if (!Array.isArray(raw)) return []
  return raw.map((f: any): ModelField => ({
    id: String(f.id || f.uuid || f.field_id || ''),
    name: String(f.field_name || f.label || f.name || ''),
    code: String(f.field_code || f.code || f.bo_code || ''),
    type: String(
      f.field_type || f.type || f.component_type || f.data_type || '',
    ).toUpperCase(),
    required: Boolean(f.required ?? f.is_required ?? false),
    description: String(f.description || f.comment || f.remark || ''),
  }))
}

interface DictEntry {
  code?: string
  value?: string
  name?: string
  label?: string
}

function dictItems(d: SectionItem): DictEntry[] {
  const extra = d.extra || {}
  const raw = (extra.items || extra.values || extra.options || []) as any[]
  if (!Array.isArray(raw)) return []
  return raw.map((x: any): DictEntry => ({
    code: x.code || x.value,
    value: x.value || x.code,
    name: x.name || x.label,
    label: x.label || x.name,
  }))
}

function describeExtra(extra: Record<string, any> | undefined, key: string): string {
  if (!extra) return ''
  const v = extra[key]
  if (v === null || v === undefined) return ''
  return String(v)
}

// ── V1 Part B: 对比模式 helpers ─────────────────────────────────────────
// 把 spec_json.fields 拍成跟 modelFields() 一致的 shape — 避免 template 两套字段名
function draftFieldsAsModelFields(spec: any): ModelField[] {
  const fields = spec?.fields
  if (!Array.isArray(fields)) return []
  return fields.map((f: any): ModelField => ({
    id: String(f.id || ''),
    name: String(f.label || f.name || f.field_name || ''),
    code: String(f.code || f.field_code || ''),
    type: String(f.field_type || f.type || 'STRING').toUpperCase(),
    required: Boolean(f.required),
    description: String(f.description || ''),
  }))
}

// 判断生产里某字段在草稿里是否被删 — 用于左列染色 (del)
function isFieldDeletedInDraft(m: SectionItem, f: ModelField): boolean {
  const code = m.code || ''
  if (!code) return false
  const draft = draftSections.value[code]
  if (!draft) return false
  const draftFields = draftFieldsAsModelFields(draft.spec_json)
  // 草稿里完全没字段 = 全删?  这是 hint 而非确定: backend init 时已写 fields[].
  // 但 spec_json 异常时也别误判, 这里只在 fields[] 真存在且不含此 code 时才标 del.
  if (draftFields.length === 0) return false
  return !draftFields.some(df => (df.code || '') === (f.code || ''))
}

// 计算所有"已加载草稿的模型"的字段对比表
const comparedModels = computed<ComparedModel[]>(() => {
  // 用 model_code 索引生产
  const prodByCode: Record<string, SectionItem> = {}
  for (const m of loadedModels.value) {
    if (m.code) prodByCode[m.code] = m
  }
  // 草稿里所有 model_code
  const draftCodes = Object.keys(draftSections.value)

  const result: ComparedModel[] = []

  // 1. 先按生产模型顺序输出 (保留 read mode 顺序)
  for (const m of loadedModels.value) {
    const prodFields = modelFields(m)
    const code = m.code || ''
    const draft = code ? draftSections.value[code] : undefined
    let compared: ComparedField[]
    if (draft) {
      const draftFields = draftFieldsAsModelFields(draft.spec_json)
      compared = mergeFieldsForDiff(prodFields, draftFields)
    } else {
      // 无草稿 — 等同于生产 (无差异)
      compared = prodFields.map(f => ({ ...f, diff_kind: 'unchanged' as const }))
    }
    result.push({
      id: String(m.id),
      code,
      name: m.name || code || '(unnamed)',
      is_added_in_draft: false,
      compared_fields: compared,
    })
  }

  // 2. 草稿里多出来的模型 (生产没该 code) — 标 is_added_in_draft
  for (const code of draftCodes) {
    if (code && prodByCode[code]) continue   // 已在生产里
    const draft = draftSections.value[code]
    const draftFields = draftFieldsAsModelFields(draft.spec_json)
    // 整模型新加 — 全字段都标 add
    const compared: ComparedField[] = draftFields.map(f => ({ ...f, diff_kind: 'add' as const }))
    const draftName = (draft.spec_json?.model_name as string | undefined) || code
    result.push({
      id: `draft-only-${code}`,
      code,
      name: draftName || code,
      is_added_in_draft: true,
      compared_fields: compared,
    })
  }

  return result
})

// 把生产 / 草稿两套 fields 按 code 合并 — 同 code 保留草稿版本 (unchanged), 多的来源标 add/del
function mergeFieldsForDiff(prod: ModelField[], draft: ModelField[]): ComparedField[] {
  const draftByCode: Record<string, ModelField> = {}
  for (const f of draft) {
    if (f.code) draftByCode[f.code] = f
  }
  const prodByCode: Record<string, ModelField> = {}
  for (const f of prod) {
    if (f.code) prodByCode[f.code] = f
  }
  const result: ComparedField[] = []
  // 先按生产顺序; 同 code 在草稿里也存在 → unchanged; 生产有草稿没 → del
  for (const f of prod) {
    const code = f.code || ''
    if (code && draftByCode[code]) {
      result.push({ ...f, diff_kind: 'unchanged' })
    } else if (code) {
      // 草稿里删了这字段
      result.push({ ...f, diff_kind: 'del' })
    } else {
      result.push({ ...f, diff_kind: 'unchanged' })
    }
  }
  // 再追加草稿独有的 (新增字段)
  for (const f of draft) {
    const code = f.code || ''
    if (code && !prodByCode[code]) {
      result.push({ ...f, diff_kind: 'add' })
    }
  }
  return result
}

const hasAnyDraftModel = computed(() => Object.keys(draftSections.value).length > 0)

// 各章节差异 label — 左 nav 显示 (+X / ~Y / 无差异)
function chapterDiffLabel(chapterKey: string): string {
  if (chapterKey !== 'data_model') return '无差异'
  let addCount = 0
  let delCount = 0
  for (const m of comparedModels.value) {
    if (m.is_added_in_draft) {
      addCount += 1  // 新模型本身算一个 add
    }
    for (const f of m.compared_fields) {
      if (f.diff_kind === 'add') addCount += 1
      else if (f.diff_kind === 'del') delCount += 1
    }
  }
  if (addCount === 0 && delCount === 0) return '无差异'
  const parts: string[] = []
  if (addCount > 0) parts.push(`+${addCount}`)
  if (delCount > 0) parts.push(`~${delCount}`)
  return parts.join(' / ')
}

// 整页总差异数 (CTA badge + mode pill badge 用)
const diffTotalCount = computed(() => {
  let count = 0
  for (const m of comparedModels.value) {
    if (m.is_added_in_draft) count += 1
    for (const f of m.compared_fields) {
      if (f.diff_kind === 'add' || f.diff_kind === 'del') count += 1
    }
  }
  return count
})

const applyCtaTitle = computed(() => {
  if (viewMode.value === 'compare') return '切回阅读模式才能生成 (P2 接入)'
  if (diffTotalCount.value === 0) return '无草稿改动 — 用对话改 SPEC 后即可生成 (P2)'
  return 'P2 接入 — 需 SPEC 改动后才能生成'
})

const compareDraftMeta = computed(() => {
  if (!compareDraftFetchedAt.value) return '加载中…'
  const d = compareDraftFetchedAt.value
  const pad = (n: number) => String(n).padStart(2, '0')
  const dt = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  return `${dt} 你的改动`
})

// 加载 data_model 草稿 — 为每个生产模型 GET 一次 spec_section.
// 失败 (404 / exists:false) 静默 — 等同于无草稿 (无差异).
async function fetchDraftSections(): Promise<void> {
  if (!props.appId || loadedModels.value.length === 0) {
    draftSections.value = {}
    return
  }
  const tasks = loadedModels.value
    .filter(m => !!m.code)
    .map(async (m): Promise<[string, DraftSectionEntry | null]> => {
      try {
        const resp = await request.get<any, any>(
          `/applications/${props.appId}/spec-sections/data_model/${encodeURIComponent(String(m.code))}`,
        )
        if (resp?.ok && resp.exists && resp.section) {
          return [
            String(m.code),
            {
              spec_json: resp.section.spec_json,
              draft_version: Number(resp.section.draft_version || 0),
              updated_at: resp.section.updated_at || null,
            },
          ]
        }
      } catch {
        // 静默 — 单个 section 失败不阻塞整页
      }
      return [String(m.code), null]
    })
  const results = await Promise.allSettled(tasks)
  const map: Record<string, DraftSectionEntry> = {}
  for (const r of results) {
    if (r.status !== 'fulfilled') continue
    const [code, entry] = r.value
    if (entry) map[code] = entry
  }
  draftSections.value = map
  compareDraftFetchedAt.value = new Date()
}

// 切模式 — 'compare' 时按需加载草稿
async function onSwitchMode(mode: 'read' | 'compare'): Promise<void> {
  if (mode === viewMode.value) return
  if (mode === 'compare') {
    // 加载草稿 — 阻塞 UI 用 compareLoading
    viewMode.value = 'compare'
    compareLoading.value = true
    try {
      await fetchDraftSections()
    } finally {
      compareLoading.value = false
    }
  } else {
    viewMode.value = 'read'
  }
}

// ── 数据加载 ──────────────────────────────────────────────────────────
async function fetchSection(
  endpoint: string,
  fallback: SectionItem[] = [],
): Promise<SectionItem[]> {
  try {
    const resp = await request.get<any, SectionResp>(endpoint)
    if (resp?.ok && Array.isArray(resp.items)) return resp.items
  } catch {
    // 静默 — 一个 section 失败不阻塞整页
  }
  return fallback
}

// X (2026-05-27): apaas-menus 是 hierarchical (children/submenus nested), 不像
// section-content endpoints 是 flat list. 单独 helper dfs flatten + map 到 SectionItem.
async function fetchMenusFromApaas(endpoint: string): Promise<SectionItem[]> {
  try {
    const resp = await request.get<any, any>(endpoint)
    const raw: any[] = resp?.items || resp?.menus || []
    if (!Array.isArray(raw)) return []
    const out: SectionItem[] = []
    const dfs = (arr: any[], depth: number) => {
      for (const m of arr) {
        if (!m || typeof m !== 'object') continue
        out.push({
          id: String(m.menu_id || m.id || ''),
          code: String(m.menu_code || m.form_code || m.link_url || ''),
          name: String(m.menu_name || m.name || ''),
          extra: {
            menu_type: m.menu_type || m.type || '',
            form_id: m.form_id || '',
            form_code: m.form_code || '',
            link_url: m.link_url || '',
            depth,
            parent_menu_id: m.parent_menu_id || '',
            is_group: !!m.is_group,
          },
        })
        const kids = m.children || m.submenus
        if (Array.isArray(kids) && kids.length) dfs(kids, depth + 1)
      }
    }
    dfs(raw, 0)
    return out
  } catch {
    return []
  }
}

async function fetchApp(): Promise<void> {
  try {
    const resp = await request.get<any, any>(`/applications/${props.appId}`)
    if (resp && typeof resp === 'object') {
      appName.value = String(resp.name || resp.app_name || `应用 ${props.appId}`)
      appCode.value = String(resp.app_code || resp.code || '')
      appDescription.value = String(resp.description || '')
      const ca = resp.created_at || resp.createdAt
      if (ca) {
        try {
          const dt = new Date(ca)
          appCreatedAt.value = isNaN(dt.getTime()) ? String(ca) : dt.toLocaleString()
        } catch { appCreatedAt.value = String(ca) }
      }
    }
  } catch {
    appName.value = `应用 ${props.appId}`
  }
}

// 2026-05-27 升级: 拉版本历史 — Y agent backend 404 时优雅静默
async function loadVersions(): Promise<void> {
  if (!props.appId) return
  versionsLoading.value = true
  try {
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/spec/versions`,
    )
    const arr = resp?.versions || resp?.items || []
    if (Array.isArray(arr)) {
      versions.value = arr as SpecVersion[]
    } else {
      versions.value = []
    }
  } catch {
    // 静默 — Y agent 还没接 backend 时这里 404
    versions.value = []
  } finally {
    versionsLoading.value = false
  }
}

// 当前激活的版本 (is_active=true) — 用于版本 pill 副标 + 区分草稿
const activeVersion = computed<SpecVersion | null>(() => {
  return versions.value.find(v => v.is_active) || null
})

// 版本 pill 主标 (e.g. "草稿" / "v1.2 (生产)")
const versionPillLabel = computed(() => {
  if (selectedVersionId.value === null) {
    if (diffTotalCount.value > 0) return `草稿 · ${diffTotalCount.value} 处未应用`
    return '草稿'
  }
  const v = versions.value.find(x => String(x.id) === String(selectedVersionId.value))
  return v ? v.version_label : '草稿'
})

function formatVersionTime(s: string | null | undefined): string {
  if (!s) return ''
  try {
    const d = new Date(s)
    if (isNaN(d.getTime())) return s
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch {
    return s
  }
}

function versionSubtitle(v: SpecVersion): string {
  const parts: string[] = []
  const ts = formatVersionTime(v.applied_at)
  if (ts) parts.push(ts)
  const who = v.applied_by_username || (v.applied_by_user_id ? `user#${v.applied_by_user_id}` : '')
  if (who) parts.push(String(who))
  if (typeof v.applied_steps === 'number') {
    if (v.failed_steps && v.failed_steps > 0) {
      parts.push(`${v.applied_steps} step, ${v.failed_steps} fail`)
    } else if (v.applied_steps > 0) {
      parts.push(`${v.applied_steps} step`)
    }
  }
  return parts.join(' · ')
}

function onSelectVersion(versionId: number | string | null) {
  selectedVersionId.value = versionId
  versionDropdownOpen.value = false
  if (versionId === null) {
    // 切回"草稿" — 无副作用 (read mode 仍渲染 loadedModels)
    return
  }
  // MVP: toast 提示 + 切到对比模式让用户看 diff 视图
  // P3: 真拉 /spec/versions/{id} snapshot 用作 left col baseline 替换 loadedModels
  ElMessage.info(`查看 ${versions.value.find(v => String(v.id) === String(versionId))?.version_label || '历史版本'} — 切到对比模式`)
  if (viewMode.value !== 'compare') {
    onSwitchMode('compare')
  }
}

function toggleVersionDropdown() {
  versionDropdownOpen.value = !versionDropdownOpen.value
}

function closeVersionDropdown() {
  versionDropdownOpen.value = false
}

async function fetchDatasources(): Promise<void> {
  try {
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/datasources`,
    )
    if (resp?.ok && Array.isArray(resp.items)) {
      loadedDatasources.value = resp.items as DatasourceItem[]
      datasourceNote.value = ''
    } else {
      loadedDatasources.value = []
      const code = String(resp?.error_code || '')
      if (code === 'APP_NOT_DEPLOYED') {
        datasourceNote.value = '应用尚未部署到 aPaaS 平台 — 部署后才能拉数据源.'
      } else if (code === 'TOOL_NOT_AVAILABLE') {
        datasourceNote.value = '后端数据源 API 尚未就绪.'
      } else if (resp?.message) {
        datasourceNote.value = String(resp.message)
      }
    }
  } catch (e: any) {
    loadedDatasources.value = []
    if (e?.response?.status === 404) {
      datasourceNote.value = '后端数据源接口未上线.'
    }
  }
}

// 2026-05-28: 把 generator parsed_sections 原始字段映射成 SectionItem 形态
// (id 用 code 兜底, code 用同字段, name 直取). 给前端章节渲染统一形态.
function _toSectionItems(
  arr: any,
  idField: string,
  nameField: string,
  codeField: string,
): SectionItem[] {
  if (!Array.isArray(arr)) return []
  return arr.map((it: any, idx: number) => {
    const id = String(it?.[idField] ?? it?.id ?? it?.code ?? idx)
    const name = String(it?.[nameField] ?? it?.name ?? '')
    const code = String(it?.[codeField] ?? it?.code ?? '')
    return { id, name, code, extra: it }
  })
}

async function reload(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const base = `/applications/${props.appId}`

    // 2026-05-28: 优先走 /spec/parsed (DB cache 命中 1ms, 不命中 backend 跑
    // generator 5-25s 同时落库). 失败 fallback 老 8-fetchSection 并发拉.
    await fetchApp()
    let usedParsedCache = false
    try {
      const parsedResp = await request.get<{
        ok: boolean
        sections?: Record<string, any>
        cache_hit?: boolean
      }>(`${base}/spec/parsed`)
      if (parsedResp?.ok && parsedResp.sections) {
        const s = parsedResp.sections
        loadedRoles.value = _toSectionItems(s.roles, 'id', 'name', 'code')
        loadedModels.value = _toSectionItems(s.models, 'id', 'name', 'code')
        loadedDicts.value = _toSectionItems(s.dicts, 'id', 'name', 'code')
        // generator 的 menus 已 flatten 含 menu_id / menu_name / menu_type, 透传
        loadedMenus.value = _toSectionItems(s.menus, 'menu_id', 'menu_name', 'menu_code')
        loadedProcesses.value = _toSectionItems(s.processes, 'id', 'name', 'code')
        loadedEvents.value = _toSectionItems(s.business_events, 'id', 'name', 'code')
        // datasources 单独拉 (不在 spec 章节注册路径)
        await fetchDatasources()
        usedParsedCache = true
        lastFetchedAt.value = new Date()
      }
    } catch (parsedErr) {
      // /spec/parsed 失败 (404 / 网络 / generator 崩) — 不挡, 走老路
      console.warn('[SpecDesignPanel] /spec/parsed failed, fallback to 8-fetchSection', parsedErr)
    }

    if (!usedParsedCache) {
      // Fallback: 老 8-endpoint 并发拉 (X commit 前的路径)
      const [, roles, models, dicts, menus, processes, events] = await Promise.all([
        Promise.resolve(),
        fetchSection(`${base}/section-content/roles`),
        fetchSection(`${base}/section-content/models?with_fields=true`),
        fetchSection(`${base}/section-content/dicts?with_options=true`),
        fetchMenusFromApaas(`${base}/apaas-menus`),
        fetchSection(`${base}/section-content/processes`),
        fetchSection(`${base}/section-content/business-events`),
        fetchDatasources(),
      ])
      loadedRoles.value = roles
      loadedModels.value = models
      loadedDicts.value = dicts
      loadedMenus.value = menus
      loadedProcesses.value = processes
      loadedEvents.value = events
      lastFetchedAt.value = new Date()
    }

    // V1 Part B: 处在对比模式时同步刷新草稿 (例如换应用 / spec-updated 触发的 reload)
    if (viewMode.value === 'compare') {
      compareLoading.value = true
      try {
        await fetchDraftSections()
      } finally {
        compareLoading.value = false
      }
    }
  } catch (e: any) {
    error.value = e?.message || '加载 SPEC 失败'
  } finally {
    loading.value = false
  }
}

// ── 章节切换 ────────────────────────────────────────────────────────
function onChapterClick(key: ChapterKey) {
  activeChapter.value = key
  // 滚动到对应章节
  nextTick(() => {
    const el = sectionRefs.value[key]
    if (el && docPaneRef.value) {
      try {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      } catch {
        // 老浏览器兜底
        docPaneRef.value.scrollTop = el.offsetTop - 16
      }
    }
  })
}

function onEditChapter(key: ChapterKey) {
  // V1 Part A: 锚点联动 chat —
  //   1. 切 activeChapter → SpecChatPanel 通过 props.activeChapter watch 自动:
  //      - 清空 history (避 cross-chapter 串台)
  //      - header ctx chip 显示新章节标题
  //      - quick chips / placeholder 也跟着切
  //   2. 滚 doc-pane 到对应章节让用户看到"改这段"的上下文
  //   3. 调 specChatRef.focusInput() → textarea autofocus + scroll into view
  activeChapter.value = key
  nextTick(() => {
    const el = sectionRefs.value[key]
    if (el) {
      try { el.scrollIntoView({ behavior: 'smooth', block: 'start' }) } catch { /* ignore */ }
    }
    // chat input focus — 让用户无需再点 chat 区即可打字
    try { specChatRef.value?.focusInput?.() } catch { /* ignore */ }
  })
}

// ── U7 chat panel 回调 ────────────────────────────────────────────────
// SpecChatPanel emit('spec-updated') 时调 — 重新拉对应章节数据 (MVP 简化:
// 整个 reload 一次, 性能不是问题). 同时 toast 提示用户看到了改动.
const SECTION_TYPE_TO_CHAPTER: Record<string, string> = {
  data_model: '数据模型',
  permission: '角色权限',
  page: '菜单/页面',
  form: '表单',
  list: '列表',
  process: '流程',
}

async function onSpecUpdated(sectionType: string, sectionKey: string) {
  const label = SECTION_TYPE_TO_CHAPTER[sectionType] || sectionType
  ElMessage.success(`已更新 SPEC 草稿: ${label} · ${sectionKey}`)
  // 简化: 整页 reload — 让 SpecDesignPanel 的所有章节数据保持新鲜.
  // P2 可以只 reload 对应章节, 避免闪烁.
  await reload()
}

// ── V3 (2026-05-27): 确认并生成 modal ────────────────────────────────
const applyModalOpen = ref(false)
function onOpenApplyModal() {
  applyModalOpen.value = true
}
async function onApplyDone() {
  applyModalOpen.value = false
  ElMessage.success('已应用草稿到 apaas (MVP dry-run)')
  await reload()
}

// ── 2026-05-27 升级: 导出 .md (调 /spec/export.md, fetch + blob 触发下载) ─
const exporting = ref(false)
async function onExportMd() {
  if (exporting.value) return
  exporting.value = true
  try {
    const token = localStorage.getItem('token') || ''
    // 用绝对 API_PREFIX 走 fetch — axios 默认返 JSON, blob 用 fetch 直观
    const url = `${API_PREFIX}/applications/${props.appId}/spec/export.md`
    const resp = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`)
    }
    const blob = await resp.blob()
    const dlUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = dlUrl
    a.download = `${appCode.value || `spec-app-${props.appId}`}.md`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(dlUrl), 1000)
    ElMessage.success('已导出 SPEC.md')
  } catch (e: any) {
    ElMessage.error(`导出失败: ${e?.message || e}`)
  } finally {
    exporting.value = false
  }
}

// ── 章节标题 (给 SpecChatPanel header ctx chip 用) ────────────────────
const currentChapterTitle = computed(() => {
  const ch = CHAPTERS.find(c => c.key === activeChapter.value)
  return ch ? `${ch.num}、${ch.title}` : ''
})

// ── lifecycle ──────────────────────────────────────────────────────
// 全局 click outside — 关闭版本 dropdown
function onDocClick(ev: MouseEvent) {
  if (!versionDropdownOpen.value) return
  const wrap = versionDropdownRef.value
  if (wrap && !wrap.contains(ev.target as Node)) {
    closeVersionDropdown()
  }
}

onMounted(() => {
  reload()
  loadVersions()
  document.addEventListener('click', onDocClick, { capture: true })
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick, { capture: true } as any)
})

watch(
  () => props.appId,
  (v, ov) => {
    if (v && v !== ov) {
      reload()
      loadVersions()
    }
  },
)
</script>

<style scoped>
.sdp {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg);
  font-family: var(--font-sans);
  color: var(--text);
  overflow: hidden;
}

/* ── 顶部 toolbar ─────────────────────────────────────────────────── */
.sdp-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 20px;
  background: var(--surface);
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.version-pill-wrap {
  position: relative;
  display: inline-flex;
}
.version-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 13px;
  color: var(--text);
  cursor: pointer;
  font-weight: 500;
  font-family: inherit;
}
.version-pill:hover { background: var(--surface); border-color: var(--line-strong); }
.version-pill[aria-expanded="true"] {
  background: var(--surface);
  border-color: var(--brand);
  box-shadow: 0 0 0 2px var(--brand-soft);
}
.version-pill .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.version-pill .dot.draft { background: var(--warn); }
.version-pill .dot.prod { background: var(--ok); }
.version-pill .arrow { color: var(--text-4); font-size: 11px; }
.version-pill-label { color: var(--text); }

/* 版本 dropdown — 2026-05-27 升级 */
.version-dropdown {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 100;
  min-width: 280px;
  max-width: 360px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  padding: 6px;
  max-height: 320px;
  overflow-y: auto;
}
.version-dropdown-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  background: transparent;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  color: var(--text);
}
.version-dropdown-item:hover { background: var(--surface-2); }
.version-dropdown-item.active { background: var(--brand-soft); }
.version-dropdown-item.active .version-dropdown-label { color: var(--brand); font-weight: 600; }
.version-dropdown-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-4);
  margin-top: 6px;
  flex-shrink: 0;
}
.version-dropdown-dot.draft { background: var(--warn); }
.version-dropdown-dot.prod { background: var(--ok); }
.version-dropdown-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.version-dropdown-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.version-dropdown-sub {
  font-size: 11px;
  color: var(--text-4);
  font-family: var(--font-mono);
  word-break: break-all;
}
.version-dropdown-tag {
  padding: 1px 6px;
  background: var(--ok-soft);
  color: var(--ok);
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
}
.version-dropdown-empty {
  padding: 14px 10px;
  font-size: 12px;
  color: var(--text-4);
  text-align: center;
}

.mode-pill {
  display: inline-flex;
  background: var(--surface-2);
  border-radius: 8px;
  padding: 2px;
  border: 1px solid var(--line);
}
.mode-pill button {
  padding: 4px 10px;
  background: transparent;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-3);
  cursor: pointer;
  font-family: inherit;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.mode-pill button.active {
  background: var(--surface);
  color: var(--brand);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}
.mode-pill button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.toolbar-divider {
  width: 1px;
  height: 20px;
  background: var(--line);
}
.toolbar-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 13px;
  color: var(--text);
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s;
}
.toolbar-btn:hover:not(:disabled) {
  background: var(--surface-2);
  border-color: var(--line-strong);
}
.toolbar-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.spacer { flex: 1; }

.apply-cta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: var(--brand);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s;
}
.apply-cta:hover:not(:disabled) { background: var(--brand-hover); }
.apply-cta:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* ── 3 pane shell ─────────────────────────────────────────────────── */
.sdp-shell {
  display: grid;
  grid-template-columns: 240px 1fr 360px;
  flex: 1;
  min-height: 0;
  background: var(--bg);
  overflow: hidden;
}

/* ── LEFT: chapter nav ────────────────────────────────────────────── */
.sdp-nav-pane {
  background: var(--surface);
  border-right: 1px solid var(--line);
  overflow-y: auto;
  padding: 12px 0;
}
.nav-section { margin-bottom: 12px; }
.nav-section-title {
  padding: 4px 16px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-4);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.nav-item {
  display: flex;
  align-items: center;
  width: 100%;
  padding: 8px 16px;
  color: var(--text);
  cursor: pointer;
  font-size: 13px;
  border-left: 3px solid transparent;
  background: transparent;
  border-top: none;
  border-right: none;
  border-bottom: none;
  text-align: left;
  font-family: inherit;
  transition: all 0.1s;
  gap: 6px;
}
.nav-item:hover { background: var(--surface-2); }
.nav-item.active {
  background: var(--brand-soft);
  color: var(--brand);
  border-left-color: var(--brand);
  font-weight: 500;
}
.nav-item .num {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-4);
  min-width: 24px;
}
.nav-item.active .num { color: var(--brand); }
.nav-item .label { flex: 1; }

/* ── CENTER: doc pane ─────────────────────────────────────────────── */
.sdp-doc-pane {
  overflow-y: auto;
  padding: 32px 56px;
  background: var(--surface);
  min-width: 0;
}
.doc-title-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.doc-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--text);
  margin: 0;
}
.doc-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-3);
  font-size: 12px;
}
.doc-meta .mono { color: var(--text-4); }

.doc-version-banner {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 16px;
  background: var(--warn-soft);
  border: 1px solid rgba(180, 83, 9, 0.30);
  border-radius: 8px;
  color: var(--warn);
  font-size: 13px;
  margin-bottom: 28px;
  line-height: 1.55;
}
.doc-version-banner strong { color: var(--warn); font-weight: 600; }

/* states */
.state-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 64px 16px;
  color: var(--text-3);
  font-size: 13px;
}
.state-block.state-err { color: var(--err); }
.state-icon { font-size: 40px; opacity: 0.75; }
.spinner {
  width: 18px; height: 18px;
  border: 2px solid var(--line-strong);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: sdp-spin 0.9s linear infinite;
}
@keyframes sdp-spin { to { transform: rotate(360deg); } }

/* ── section ─────────────────────────────────────────────────────── */
.section {
  margin-bottom: 36px;
  scroll-margin-top: 16px;
}
.section-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 16px;
  position: relative;
}
.section-head h2 {
  font-size: 17px;
  font-weight: 600;
  color: var(--text);
  margin: 0;
}
.section-edit-btn {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: transparent;
  border: 1px dashed var(--brand);
  color: var(--brand);
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s, background 0.15s;
  font-family: inherit;
}
.section:hover .section-edit-btn { opacity: 1; }
.section-edit-btn:hover { background: var(--brand-soft); }
.section-edit-btn:focus-visible { opacity: 1; outline: 2px solid var(--brand); outline-offset: 1px; }

/* subsection */
.subsection { margin-bottom: 20px; }
.subsection h3 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin: 0 0 8px;
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.code-after-h3 {
  color: var(--text-4);
  font-weight: 400;
  font-size: 12px;
}
.subsection-empty {
  padding: 14px 16px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 12.5px;
  border-radius: 8px;
  border: 1px dashed var(--line-strong);
}
.subsection-empty-soft {
  background: var(--brand-soft);
  border-color: rgba(29, 78, 216, 0.20);
  color: var(--text-2);
}
.subsection-empty-soft strong {
  color: var(--brand);
  font-weight: 600;
}

/* table */
.spec-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  border: 1px solid var(--line);
  border-radius: 6px;
  overflow: hidden;
  background: var(--surface);
}
.spec-table thead th {
  background: var(--surface-2);
  padding: 8px 12px;
  text-align: left;
  font-weight: 600;
  color: var(--text-2);
  border-bottom: 1px solid var(--line);
  font-size: 12.5px;
}
.spec-table td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--surface-3);
  color: var(--text);
  vertical-align: top;
}
.spec-table tr:last-child td { border-bottom: none; }

.mono {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-3);
}
.required-mark { color: var(--err); font-weight: 600; }
.muted { color: var(--text-4); }

.type-chip {
  display: inline-block;
  padding: 1px 6px;
  background: var(--surface-3);
  border-radius: 4px;
  font-size: 11px;
  color: var(--text-2);
  font-family: var(--font-mono);
}

/* ── RIGHT: chat slot ────────────────────────────────────────────── */
/* U7: chat slot 现在装 SpecChatPanel — 让子组件自填充, 不再 center 显空态. */
.sdp-chat-slot {
  background: var(--surface);
  border-left: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.sdp-chat-slot > :deep(.spc-shell) {
  flex: 1;
  min-height: 0;
}

/* ════════════════════════════════════════════════════════════════════ */
/* V1 Part B: 对比模式 (compare mode)                                    */
/* 视觉跟 mockup 视图 ② 100% 对齐                                          */
/* ════════════════════════════════════════════════════════════════════ */

/* doc 区改成 1fr 1fr 双列, 共享纵向滚动 — 左右各一道 sticky header */
.sdp-compare-shell {
  display: grid;
  grid-template-columns: 1fr 1fr;
  background: var(--surface);
  min-width: 0;
  overflow: hidden;
}
.sdp-compare-col {
  overflow-y: auto;
  padding: 24px 32px;
  background: var(--surface);
  min-width: 0;
}
.sdp-compare-col + .sdp-compare-col {
  border-left: 1px solid var(--line);
}
.sdp-compare-col-head {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--surface);
  padding: 12px 0;
  margin: -24px 0 20px;       /* 反向抵 padding-top */
  padding-top: 16px;
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: center;
  gap: 8px;
}
.sdp-compare-col-dot {
  font-size: 12px;
  color: var(--text-4);
  line-height: 1;
}
.sdp-compare-col-dot.draft { color: var(--warn); }
.sdp-compare-col-ver {
  font-weight: 600;
  font-size: 14px;
}
.sdp-compare-col-head.left .sdp-compare-col-ver { color: var(--text-2); }
.sdp-compare-col-head.right .sdp-compare-col-ver { color: var(--brand); }
.sdp-compare-col-meta {
  font-size: 11px;
  color: var(--text-4);
  margin-left: auto;
}

/* compare 模式 section 头 — 不要 hover 出"用对话改"按钮 (在阅读模式才有) */
.section-head-compare {
  /* 跟 .section-head 一致, 但不要 hover btn (compare 模式无 edit) */
}

/* 字段 / 行 diff 染色 — 用 design-v3 token (--ok-soft / --err-soft) */
.sdp-diff-cell-add {
  display: inline-block;
  background: var(--ok-soft);
  border-left: 3px solid var(--ok);
  padding: 1px 6px 1px 8px;
  border-radius: 2px;
  color: var(--text);
}
.sdp-diff-cell-del {
  display: inline-block;
  background: var(--err-soft);
  border-left: 3px solid var(--err);
  padding: 1px 6px 1px 8px;
  border-radius: 2px;
  color: var(--text);
  text-decoration: line-through;
  opacity: 0.7;
}

/* 整行级 — 给 td 加底色 (覆盖默认 td) */
.spec-table tr.sdp-diff-row-add td {
  background: var(--ok-soft);
}
.spec-table tr.sdp-diff-row-add td:first-child {
  border-left: 3px solid var(--ok);
}
.spec-table tr.sdp-diff-row-del td {
  background: var(--err-soft);
  opacity: 0.75;
}
.spec-table tr.sdp-diff-row-del td:first-child {
  border-left: 3px solid var(--err);
}

/* 整模型新增 — h3 + table 都标 */
.sdp-diff-subsection-add {
  border-left: 3px solid var(--ok);
  padding-left: 12px;
  background: linear-gradient(to right, var(--ok-soft), transparent 50%);
  border-radius: 4px;
}
.sdp-diff-subsection-add > h3 {
  margin-top: 6px;
}

/* 变更标签 chip — 跟 mockup .changed-chip 对齐 */
.sdp-changed-chip {
  padding: 1px 6px;
  background: var(--warn-soft);
  color: var(--warn);
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  margin-left: 6px;
  vertical-align: middle;
}

/* 左 nav 章节差异 badge (+X / ~Y / 无差异) */
.nav-diff-badge {
  margin-left: auto;
  font-size: 10px;
  color: var(--brand);
  font-weight: 500;
}
.nav-diff-badge-zero {
  color: var(--text-4);
  font-weight: 400;
}

/* mode-pill / CTA badge */
.mode-pill-badge {
  display: inline-block;
  margin-left: 4px;
  min-width: 16px;
  padding: 0 4px;
  background: var(--brand);
  color: #fff;
  border-radius: 8px;
  font-size: 10px;
  line-height: 14px;
  font-weight: 600;
  text-align: center;
}
.mode-pill button.active .mode-pill-badge {
  background: var(--brand);
}
.apply-cta-count {
  margin-left: 4px;
  font-weight: 600;
  opacity: 0.9;
}
</style>
