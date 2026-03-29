<template>
  <div class="chat-page">
    <nav class="nav-bar">
      <div class="nav-left">
        <button class="back-btn" @click="router.push('/')">
          <el-icon><ArrowLeft /></el-icon>
        </button>
        <div class="logo-box">A</div>
        <span class="logo-text">aPaaS Builder AI</span>
      </div>
      <div class="nav-right">
        <ThemeToggle />
        <button class="nav-link" @click="router.push('/apps')">
          📁 我的应用
          <span v-if="appCount > 0" class="project-count">{{ appCount }}</span>
        </button>
        <button class="nav-link" @click="router.push('/')">+ 新建应用</button>
      </div>
    </nav>

    <div class="main-area">
      <!-- 顶部 Tab 切换（始终可见） -->
      <div class="agent-tabs">
        <button class="agent-tab" :class="{ active: activeView === 'builder' }" @click="activeView = 'builder'">
          <span>🤖</span>
          <span>搭建智能体</span>
          <span v-if="activeView === 'builder'" class="active-dot"></span>
        </button>
        <button
          v-if="SHOW_PLATFORM_CONFIG && store.currentApp?.apaas_app_id"
          class="agent-tab"
          :class="{ active: activeView === 'platform' }"
          @click="switchToPlatform"
        >
          <span>🛠️</span>
          <span>辅助搭建</span>
          <span v-if="activeView === 'platform'" class="active-dot"></span>
        </button>
        <button
          v-if="SHOW_PLATFORM_CONFIG && activeView === 'platform' && platformIframeUrl"
          class="agent-tab-action"
          @click="openPlatformNewTab"
          title="在新窗口打开"
        >↗</button>
      </div>

      <!-- 平台配置 iframe（v-show 保持不销毁） -->
      <div v-show="SHOW_PLATFORM_CONFIG && activeView === 'platform'" class="platform-iframe-container">
        <div v-if="platformLoading" class="platform-loading">
          <span class="loading-spinner">⟳</span> 加载平台配置...
        </div>
        <div v-else-if="platformError" class="platform-error">
          <p>{{ platformError }}</p>
          <div class="platform-error-actions">
            <button class="platform-retry-btn" @click="loadPlatformUrl">重试</button>
            <button class="platform-open-btn" @click="openPlatformNewTab">在新窗口打开</button>
          </div>
        </div>
        <template v-else-if="platformIframeUrl">
          <div v-if="platformLoginHint" class="platform-login-hint">
            <span>💡 首次使用请在下方登录平台（账号: <b>{{ platformLoginHint }}</b>）</span>
            <button class="hint-nav-btn" @click="navigateIframeToApp" title="登录后点击跳转到应用配置页">🔄 跳转到应用</button>
            <button class="hint-dismiss-btn" @click="platformLoginHint = ''">✕</button>
          </div>
          <iframe
            ref="platformIframeRef"
            :src="platformIframeUrl"
            class="platform-iframe"
            frameborder="0"
            allow="clipboard-read; clipboard-write"
            @error="onIframeError"
          ></iframe>
        </template>
      </div>

      <!-- 搭建智能体内容区（横向布局） -->
      <div v-show="!SHOW_PLATFORM_CONFIG || activeView === 'builder'" class="builder-content">
      <!-- 左侧对话区 -->
      <div class="chat-side">
        <!-- 对话历史栏 -->
        <div class="conversation-history-bar">
          <div class="conv-history-left">
            <span class="conv-history-label">对话历史</span>
            <el-select
              v-model="selectedConversationId"
              placeholder="选择对话..."
              class="conv-history-select"
              :teleported="false"
              @change="onConversationSwitch"
              popper-class="conv-history-popper"
            >
              <el-option
                v-for="conv in conversationList"
                :key="conv.id"
                :value="conv.id"
                :label="getConversationLabel(conv)"
              >
                <div class="conv-option-row">
                  <span class="conv-option-title">{{ getConversationLabel(conv) }}</span>
                  <span class="conv-option-time">{{ formatConvTime(conv.created_at) }}</span>
                </div>
              </el-option>
            </el-select>
          </div>
          <button class="conv-new-btn" @click="startNewConversation">+ 新建对话</button>
        </div>

        <div class="messages" ref="messagesRef">
          <div v-for="(msg, idx) in messages" :key="idx" class="chat-bubble" :class="msg.role">
            <div class="bubble-inner">
              <div v-if="msg.role === 'assistant'" class="agent-label">
                <span>{{ agents[msg.agent || 'builder']?.icon }}</span>
                <span>{{ agents[msg.agent || 'builder']?.name }}</span>
              </div>
              <div class="bubble-content" :class="msg.role" v-html="formatContent(msg.content)"></div>
            </div>
          </div>
          <div v-if="isTyping" class="chat-bubble assistant">
            <div class="bubble-inner">
              <div class="bubble-content assistant">
                <span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>
              </div>
            </div>
          </div>
          <!-- 编码冲突修复输入 -->
          <div v-if="activeConflict" class="chat-bubble assistant">
            <div class="bubble-inner">
              <div class="agent-label"><span>🤖</span><span>搭建智能体</span></div>
              <div class="bubble-content assistant conflict-resolve-box">
                <div class="conflict-label">请输入新编码替换 <code>{{ activeConflict.current_code }}</code>：</div>
                <div class="conflict-input-row">
                  <input
                    v-model="activeConflict.newCode"
                    class="conflict-input"
                    placeholder="输入新编码，如 xxx_v2"
                    @keydown.enter="resolveConflictAndRetry"
                    :disabled="activeConflict.resolving"
                  />
                  <button class="conflict-btn confirm" @click="resolveConflictAndRetry" :disabled="activeConflict.resolving">
                    {{ activeConflict.resolving ? '修复中...' : '确认修复' }}
                  </button>
                  <button class="conflict-btn cancel" @click="cancelConflict" :disabled="activeConflict.resolving">取消</button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="input-bar">
          <div class="input-wrap">
            <label class="upload-btn" title="上传功能设计文档(.md)">
              <input type="file" accept=".md" @change="handleDocUpload" style="display:none" />
              📄
            </label>
            <input v-model="inputText" @keydown.enter="sendMessage" placeholder="输入消息，或上传设计文档..." />
            <button class="send-btn" :class="{ disabled: !inputText.trim() }" @click="sendMessage">
              <el-icon><Promotion /></el-icon>
            </button>
          </div>
        </div>
      </div>

      <!-- 右侧预览面板 -->
      <div class="preview-side">
        <div v-if="store.currentApp" class="preview-tabs">
          <button v-for="tab in tabs" :key="tab.k" class="ptab" :class="{ active: store.previewTab === tab.k }" @click="store.previewTab = tab.k">{{ tab.l }}</button>
        </div>

        <!-- 未开始 -->
        <div v-if="!store.currentApp" class="preview-empty">
          <div class="empty-icon">📋</div>
          <div>开始对话后<br>这里会实时展示配置预览</div>
        </div>

        <div v-else class="preview-body">
          <!-- 文档版本 -->
          <div v-show="store.previewTab === 'docs'" class="tab-content doc-versions-tab">
            <div class="doc-upload-bar">
              <span class="doc-tab-title">文档版本</span>
            </div>
            <div v-if="docVersionsLoading" class="preview-empty small">加载中...</div>
            <div v-else-if="docVersions.length === 0" class="preview-empty small">暂无文档版本</div>
            <div v-else class="doc-version-list">
              <div v-for="ver in docVersions" :key="ver.id" class="doc-version-card">
                <div class="doc-ver-header">
                  <span class="doc-ver-num">V{{ ver.version }}</span>
                  <span class="doc-ver-filename">{{ ver.filename }}</span>
                </div>
                <div class="doc-ver-meta">
                  <span class="doc-ver-time">{{ formatDocTime(ver.created_at) }}</span>
                  <span v-if="ver.summary" class="doc-ver-summary">{{ ver.summary }}</span>
                </div>
                <div class="doc-ver-actions">
                  <button class="doc-action-btn" @click="openDocPreview(ver)">预览</button>
                  <button v-if="ver.version >= 2" class="doc-action-btn diff" @click="openDocDiff(ver)">与上一版本对比</button>
                </div>
              </div>
            </div>
          </div>

          <!-- 文档预览弹窗 -->
          <el-dialog v-model="docPreviewVisible" :title="docPreviewTitle" width="70%" class="doc-preview-dialog" :append-to-body="true">
            <div class="doc-preview-body markdown-body" v-html="renderMarkdown(docPreviewContent)"></div>
          </el-dialog>

          <!-- 文档对比弹窗 -->
          <el-dialog v-model="docDiffVisible" title="版本对比" width="90%" class="doc-diff-dialog" :append-to-body="true">
            <div class="diff-summary-bar">
              <span class="diff-stat added">+ {{ docDiffResult.right.filter(l => l.type === 'added').length }} 行新增</span>
              <span class="diff-stat removed">- {{ docDiffResult.left.filter(l => l.type === 'removed').length }} 行删除</span>
              <span class="diff-stat unchanged">{{ docDiffResult.right.filter(l => l.type === 'same' && l.text).length }} 行未变</span>
            </div>
            <div class="doc-diff-container">
              <div class="doc-diff-pane">
                <div class="doc-diff-pane-title">{{ docDiffLeftTitle }}</div>
                <div class="doc-diff-content">
                  <div v-for="(line, idx) in docDiffResult.left" :key="'l'+idx" class="doc-diff-line" :class="{ removed: line.type === 'removed' }">
                    <span class="doc-diff-lineno">{{ idx + 1 }}</span>
                    <span class="doc-diff-text">{{ line.text }}</span>
                  </div>
                </div>
              </div>
              <div class="doc-diff-pane">
                <div class="doc-diff-pane-title">{{ docDiffRightTitle }}</div>
                <div class="doc-diff-content">
                  <div v-for="(line, idx) in docDiffResult.right" :key="'r'+idx" class="doc-diff-line" :class="{ added: line.type === 'added' }">
                    <span class="doc-diff-lineno">{{ idx + 1 }}</span>
                    <span class="doc-diff-text">{{ line.text }}</span>
                  </div>
                </div>
              </div>
              <!-- 变更摘要面板 -->
              <div class="diff-changes-panel">
                <div class="dcp-title">变更摘要</div>
                <div class="dcp-list">
                  <div v-for="(change, idx) in diffChangeSummary" :key="idx" class="dcp-item" :class="change.type">
                    <span class="dcp-icon">{{ change.type === 'added' ? '+' : change.type === 'removed' ? '-' : '~' }}</span>
                    <span class="dcp-text">{{ change.text }}</span>
                  </div>
                  <div v-if="diffChangeSummary.length === 0" class="dcp-empty">无结构化变更</div>
                </div>
              </div>
            </div>
          </el-dialog>

          <div v-show="store.previewTab === 'overview'" class="tab-content">
            <div class="overview-header">
              <h4>{{ store.preview.appName }}</h4>
              <span class="status-tag" :class="appDisplayStatus">
                {{ appDisplayStatusText }}
              </span>
            </div>
            <div class="stat-grid">
              <div class="stat-card indigo"><div class="stat-num">{{ store.preview.models.length }}</div><div class="stat-label">数据模型</div></div>
              <div class="stat-card teal"><div class="stat-num">{{ store.preview.models.length }}</div><div class="stat-label">表单配置</div></div>
              <div class="stat-card emerald"><div class="stat-num">{{ store.preview.roles.length }}</div><div class="stat-label">角色</div></div>
              <div class="stat-card amber"><div class="stat-num">{{ store.preview.dicts.length }}</div><div class="stat-label">数据字典</div></div>
            </div>
            <div class="sub-section">
              <div class="sub-title">角色 <button class="add-mini" @click="addRole">+</button></div>
              <div class="tag-list">
                <span v-for="(r, ri) in store.preview.roles" :key="r.code" class="tag editable" @click="removeRole(ri)" title="点击删除">{{ r.name }} ×</span>
                <span v-if="store.preview.roles.length === 0" class="tag empty">暂无角色</span>
              </div>
            </div>
            <div class="sub-section">
              <div class="sub-title">数据字典 <button class="add-mini" @click="addDict">+</button></div>
              <div class="dict-list">
                <div v-for="(d, di) in store.preview.dicts" :key="d.code" class="dict-row">
                  <span class="dict-name">{{ d.name }}</span>
                  <span class="dict-opts" :class="{ empty: !d.options || d.options.length === 0 }">
                    {{ d.options && d.options.length > 0 ? d.options.map((o: any) => typeof o === 'string' ? o : o.name).join('、') : '⚠️ 空字典' }}
                  </span>
                  <button class="edit-mini" @click="editDict(di)" title="编辑选项">✏️</button>
                  <button class="del-mini" @click="removeDict(di)" title="删除字典">🗑</button>
                </div>
              </div>
            </div>
            <!-- 分阶段生成配置按钮 -->
            <button v-if="store.currentApp && store.preview.models.length === 0 && !assembling" class="assemble-btn" @click="startAssembleConfig">
              🧩 自动生成配置
            </button>
            <!-- 生成进度 -->
            <div v-if="assembling" class="assemble-progress">
              <div class="assemble-spinner">⟳</div>
              <span>{{ assembleMessage }}</span>
            </div>
            <!-- 开始生成（部署到平台） -->
            <!-- 开始生成 / 已部署状态 -->
            <div v-if="(deployAllDone || store.currentApp?.status === 'completed') && !hasConfigChanged" class="deployed-banner">
              <span>✅ 已部署到平台</span>
              <button class="view-deploy-btn" @click="openDeployPanel">查看部署记录</button>
            </div>
            <button v-else-if="!assembling && store.preview.models.length > 0 && (store.currentApp?.status === 'draft' || store.currentApp?.status === 'generating' || store.currentApp?.status === 'failed' || hasConfigChanged)" class="gen-btn" :disabled="generating" @click="startGenerate">{{ generating ? '创建中...' : hasConfigChanged ? '⚡ 更新配置并部署' : deployAppId ? '⚡ 重新部署' : '⚡ 开始生成' }}</button>
          </div>

          <!-- 模型 -->
          <div v-show="store.previewTab === 'models'" class="tab-content">
            <div class="model-select-bar" v-if="store.preview.models.length > 3">
              <label class="model-select-all">
                <input type="checkbox" :checked="selectedModelIndices.length === 0" @change="toggleSelectAll" />
                <span>全选 ({{ selectedModelIndices.length === 0 ? store.preview.models.length : selectedModelIndices.length }}/{{ store.preview.models.length }})</span>
              </label>
              <span class="model-select-tip">可勾选部分模型分批生成</span>
            </div>
            <div v-for="(m, mi) in store.preview.models" :key="mi" class="model-card" :class="{ 'model-deselected': selectedModelIndices.length > 0 && !selectedModelIndices.includes(mi) }">
              <div class="model-header">
                <label v-if="store.preview.models.length > 3" class="model-checkbox" @click.stop>
                  <input type="checkbox" :checked="selectedModelIndices.length === 0 || selectedModelIndices.includes(mi)" @change="toggleModelSelect(mi)" />
                </label>
                <span>📊</span><span class="model-name">{{ m.name }}</span><span class="model-code">{{ m.code }}</span>
              </div>
              <div class="field-list">
                <div v-for="(f, fi) in m.fields" :key="fi" class="field-row">
                  <div class="field-left"><span class="field-icon" :title="f.type">{{ getFieldIcon(f) }}</span><span class="field-name">{{ f.name }}</span><span v-if="f.required" class="req">*</span></div>
                  <div class="field-right"><span v-if="f.dict" class="ftag dict">{{ f.dict }}</span><span v-if="f.ref" class="ftag ref">→{{ typeof f.ref === 'object' ? f.ref.model : f.ref }}</span><span class="ftype">{{ f.type }}</span></div>
                </div>
              </div>
            </div>
          </div>

          <!-- 表单 -->
          <div v-show="store.previewTab === 'forms'" class="tab-content">
            <div class="form-selector">
              <button v-for="(m, mi) in store.preview.models" :key="mi" class="form-tab" :class="{ active: store.previewFormIdx === mi }" @click="store.previewFormIdx = mi">{{ m.name }}</button>
            </div>
            <div class="form-preview">
              <div class="form-title">{{ store.preview.models[store.previewFormIdx]?.name }} 表单</div>
              <div class="form-fields-grid">
                <div v-for="(f, fi) in store.preview.models[store.previewFormIdx]?.fields" :key="fi" class="form-field" :class="{ 'full-width': ['多行输入','附件上传','子表'].includes(f.type) }">
                  <template v-if="f.type === '子表'">
                    <div class="form-label">{{ f.name }}<span v-if="f.required" class="req">*</span></div>
                    <div class="subtable-wrapper">
                      <table class="subtable">
                        <thead>
                          <tr>
                            <th class="subtable-idx">#</th>
                            <th v-for="sf in (f.sub_fields || [])" :key="sf.name">{{ sf.name }}</th>
                            <th class="subtable-op">操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr>
                            <td class="subtable-idx">1</td>
                            <td v-for="sf in (f.sub_fields || [])" :key="sf.name">
                              <span v-if="sf.type === '数据单选'" class="subtable-data-selector"><span class="mock-link">选择{{ typeof sf.ref === 'object' ? sf.ref.model : (sf.ref || sf.name) }}</span> <span class="mock-arrow">🔗</span></span>
                              <span v-else-if="sf.type === '下拉单选'" class="subtable-placeholder">请选择{{ sf.dict || sf.name }} <span class="mock-arrow">▼</span></span>
                              <span v-else-if="sf.type === '下拉多选'" class="subtable-placeholder">请选择{{ sf.dict || sf.name }} <span class="mock-arrow">☰</span></span>
                              <span v-else-if="sf.type === '日期时间'" class="subtable-placeholder">请选择日期 <span class="mock-arrow">📅</span></span>
                              <span v-else-if="sf.type === '金额'" class="subtable-placeholder">¥ 0.00</span>
                              <span v-else-if="sf.type === '数字'" class="subtable-placeholder">0</span>
                              <span v-else-if="sf.type === '人员选择'" class="subtable-placeholder">请选择人员 <span class="mock-arrow">👤</span></span>
                              <span v-else-if="sf.type === '部门选择'" class="subtable-placeholder">请选择部门 <span class="mock-arrow">🏢</span></span>
                              <span v-else-if="sf.type === '开关'" class="subtable-placeholder"><span class="mock-switch">○───</span></span>
                              <span v-else class="subtable-placeholder">请输入{{ sf.name }}</span>
                            </td>
                            <td class="subtable-op"><span class="subtable-del">删除</span></td>
                          </tr>
                        </tbody>
                      </table>
                      <div class="subtable-add">+ 添加一行</div>
                    </div>
                  </template>
                  <template v-else>
                    <div class="form-label">{{ f.name }}<span v-if="f.required" class="req">*</span></div>
                    <div class="form-mock" :class="f.type === '多行输入' ? 'tall' : ''">
                      <template v-if="f.type === '单据号'"><span class="mock-auto">AUTO-001</span></template>
                      <template v-else-if="f.type === '金额'">¥ 0.00</template>
                      <template v-else-if="f.type === '数字'">0</template>
                      <template v-else-if="f.type === '下拉单选'">请选择{{ f.dict || '' }} <span class="mock-arrow">▼</span></template>
                      <template v-else-if="f.type === '下拉多选'">请选择{{ f.dict || '' }} <span class="mock-arrow">☰</span></template>
                      <template v-else-if="f.type === '数据单选'"><span class="mock-link">选择{{ typeof f.ref === 'object' ? f.ref.model : (f.ref || '') }}</span> <span class="mock-arrow">🔗</span></template>
                      <template v-else-if="f.type === '日期时间'">请选择日期 <span class="mock-arrow">📅</span></template>
                      <template v-else-if="f.type === '附件上传'">📎 点击上传附件</template>
                      <template v-else-if="f.type === '开关'"><span class="mock-switch">○───</span></template>
                      <template v-else-if="f.type === '人员选择'">请选择人员 <span class="mock-arrow">👤</span></template>
                      <template v-else-if="f.type === '部门选择'">请选择部门 <span class="mock-arrow">🏢</span></template>
                      <template v-else-if="f.type === '地理位置'">请选择位置 <span class="mock-arrow">📍</span></template>
                      <template v-else>请输入{{ f.name }}</template>
                    </div>
                  </template>
                </div>
              </div>
            </div>
          </div>

          <!-- 权限 -->
          <div v-show="store.previewTab === 'perms'" class="tab-content">
            <div v-for="(p, pi) in store.preview.permissions" :key="pi" class="perm-card">
              <div class="perm-header">{{ p.form }}</div>
              <table class="perm-table">
                <thead><tr><th>角色</th><th>操作权限</th><th>数据范围</th></tr></thead>
                <tbody>
                  <tr v-for="(rule, ri) in p.rules" :key="ri">
                    <td>{{ rule.role }}</td>
                    <td>{{ rule.op }}</td>
                    <td><span class="data-tag" :class="rule.data === '全部数据' ? 'all' : rule.data.includes('部门') ? 'dept' : 'self'">{{ rule.data }}</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <!-- 变更计划确认 overlay -->
        <div v-if="store.showChangePlan && store.changePlan" class="change-plan-overlay">
          <div class="change-plan-header">
            <h3>变更计划（V{{ store.changePlan.fromVersion }} → V{{ store.changePlan.toVersion }}）</h3>
            <button class="change-plan-close" @click="store.showChangePlan = false">✕</button>
          </div>

          <div class="change-plan-body">
            <ConfigDiff
              v-if="changePlanResourceDiff"
              :has-changes="changePlanResourceDiff.has_changes"
              :summary="changePlanResourceDiff.summary"
              :role-changes="changePlanResourceDiff.role_changes"
              :dict-changes="changePlanResourceDiff.dict_changes"
              :model-changes="changePlanResourceDiff.model_changes"
              :form-changes="changePlanResourceDiff.form_changes"
              :process-changes="[]"
              :warnings="changePlanResourceDiff.warnings"
              :unsupported-changes="changePlanResourceDiff.unsupported_changes"
              :show-actions="false"
              class="change-plan-diff"
            />

            <!-- 新增 -->
            <div class="change-group" v-if="addedActions.length">
              <div class="group-title" @click="toggleChangePlanGroup('added')">
                <span class="group-arrow" :class="{ expanded: expandedGroups.added }">▸</span>
                新增 ({{ addedActions.length }})
              </div>
              <template v-if="expandedGroups.added">
                <div v-for="action in addedActions" :key="action.id" class="change-item">
                  <input type="checkbox" v-model="action.selected" class="change-checkbox" />
                  <span class="change-icon add">+</span>
                  <span class="change-desc">{{ action.description }}</span>
                </div>
              </template>
            </div>

            <!-- 修改 -->
            <div class="change-group" v-if="modifiedActions.length">
              <div class="group-title" @click="toggleChangePlanGroup('modified')">
                <span class="group-arrow" :class="{ expanded: expandedGroups.modified }">▸</span>
                修改 ({{ modifiedActions.length }})
              </div>
              <template v-if="expandedGroups.modified">
                <div v-for="action in modifiedActions" :key="action.id" class="change-item">
                  <input type="checkbox" v-model="action.selected" class="change-checkbox" />
                  <span class="change-icon modify">~</span>
                  <span class="change-desc">{{ action.description }}</span>
                </div>
              </template>
            </div>

            <!-- 删除 -->
            <div class="change-group" v-if="removedActions.length">
              <div class="group-title" @click="toggleChangePlanGroup('removed')">
                <span class="group-arrow" :class="{ expanded: expandedGroups.removed }">▸</span>
                删除 ({{ removedActions.length }})
              </div>
              <template v-if="expandedGroups.removed">
                <div v-for="action in removedActions" :key="action.id" class="change-item">
                  <input type="checkbox" v-model="action.selected" class="change-checkbox" />
                  <span class="change-icon remove">-</span>
                  <span class="change-desc">{{ action.description }}</span>
                </div>
              </template>
            </div>
          </div>

          <div class="change-plan-footer">
            <button class="cp-btn" @click="changePlanSelectAll(true)">全选</button>
            <button class="cp-btn" @click="changePlanSelectAll(false)">取消全选</button>
            <span class="cp-count">已选 {{ changePlanSelectedCount }}/{{ changePlanTotalCount }} 项</span>
            <button class="cp-btn primary" @click="executeChangePlan" :disabled="changePlanSelectedCount === 0 || executingChangePlan">
              {{ executingChangePlan ? '执行中...' : '确认执行' }}
            </button>
            <button class="cp-btn" @click="cancelChangePlan">取消</button>
          </div>
        </div>

        <!-- 未连接提示 -->
        <div v-if="!store.connected && store.currentApp" class="connect-warn">
          <div class="warn-title">⚠ 未连接得帆云平台</div>
          <p>请先连接平台才能生成应用。</p>
          <button @click="store.showConnectModal = true" class="warn-link">连接平台</button>
        </div>
      </div>

      <!-- 第三栏：部署面板 -->
      <div class="deploy-side" :class="{ open: deployOpen && activeView === 'builder' }">
        <div class="deploy-header">
          <div>
            <div class="deploy-title">部署到平台</div>
            <div class="deploy-desc">{{ deploySteps.length }} 个步骤</div>
          </div>
          <button class="deploy-close" @click="deployOpen = false">✕</button>
        </div>
        <div class="deploy-progress">
          <div class="dp-track"><div class="dp-fill" :style="{ width: deployPercent + '%' }"></div></div>
          <span class="dp-meta">{{ deployDoneCount }}/{{ deploySteps.length }}</span>
        </div>
        <div class="deploy-actions">
          <button class="dp-run-all" :disabled="deployRunningAll || deployExecuting !== null || deployAllDone" @click="deployRunAll">
            {{ deployAllDone ? '✓ 全部完成' : deployRunningAll ? '执行中...' : '▶ 一键执行' }}
          </button>
        </div>
        <div class="deploy-groups">
          <template v-for="(group, gi) in deployGroups" :key="gi">
            <div class="dg" :class="{ done: group.allDone, err: group.hasError }">
              <div class="dg-hd">
                <span class="dg-icon">{{ group.icon }}</span>
                <span class="dg-name">{{ group.title }}</span>
                <span class="dg-badge" :class="group.allDone ? 'done' : group.hasError ? 'err' : ''">
                  {{ group.allDone ? '完成' : group.hasError ? '失败' : group.doneCount + '/' + group.steps.length }}
                </span>
              </div>
              <div v-for="s in group.steps" :key="s.key" class="ds" :class="[s.status, { running: deployExecuting === s.key }]">
                <div class="ds-dot" :class="[s.status, { pulse: deployExecuting === s.key }]">
                  <template v-if="s.status === 'completed'">✓</template>
                  <template v-else-if="s.status === 'error'">!</template>
                </div>
                <div class="ds-body">
                  <div class="ds-name">{{ s.label.replace(/^创建(模型|表单): /, '') }}</div>
                  <div v-if="s.error" class="ds-err">{{ s.error }}</div>
                </div>
                <div class="ds-act">
                  <span v-if="deployExecuting === s.key" class="ds-spin"></span>
                  <button v-else-if="s.status === 'completed'" class="ds-btn redo" :disabled="deployRunningAll" @click="deployRedo(s.key)">↻</button>
                  <button v-else-if="s.status === 'error'" class="ds-btn retry" :disabled="deployRunningAll" @click="deployExec(s.key)">重试</button>
                  <button v-else-if="s.deps_met" class="ds-btn run" :disabled="deployRunningAll" @click="deployExec(s.key)">执行</button>
                  <span v-else class="ds-lock">🔒</span>
                </div>
              </div>
            </div>
          </template>
        </div>
        <div v-if="deployAllDone" class="deploy-done">
          🎉 部署完成！<button class="deploy-done-btn" @click="openInPlatform">查看应用 →</button>
          <button class="deploy-log-btn" @click="showApiLogs = true">📋 API日志</button>
        </div>
      </div>
    </div>


    <ConnectModal v-model="store.showConnectModal" />
    <EnvSelectModal v-model="showEnvSelect" @selected="onEnvSelected" />

    <!-- API 调用日志弹窗 -->
    <el-dialog v-model="showApiLogs" title="API 调用日志" width="80%" :append-to-body="true">
      <div class="api-logs-header">
        <el-select v-model="apiLogFilter" placeholder="筛选步骤" clearable size="small" style="width:200px">
          <el-option label="全部" value="" />
          <el-option label="仅失败" value="failed" />
        </el-select>
        <span class="api-logs-count">共 {{ apiLogs.length }} 条记录</span>
      </div>
      <div class="api-logs-table">
        <table>
          <thead>
            <tr><th>时间</th><th>步骤</th><th>API</th><th>状态</th><th>耗时</th><th>结果</th></tr>
          </thead>
          <tbody>
            <tr v-for="log in apiLogs" :key="log.id" :class="{ error: !log.success }">
              <td class="log-time">{{ log.created_at?.slice(11, 19) }}</td>
              <td class="log-step">{{ log.step_key }}</td>
              <td class="log-url" :title="log.url">{{ log.url?.split('/').pop() }}</td>
              <td class="log-status" :class="log.success ? 'ok' : 'fail'">{{ log.response_status }}</td>
              <td class="log-ms">{{ log.elapsed_ms }}ms</td>
              <td class="log-result">{{ log.success ? '✓' : log.error_message?.slice(0, 40) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="apiLogs.length === 0" class="api-logs-empty">暂无日志</div>
      </div>
    </el-dialog>

    <!-- 增量更新弹窗 -->
    <div v-if="showIncrementalUpdate" class="incremental-modal-overlay" @click.self="closeIncrementalUpdate">
      <div class="incremental-modal">
        <div class="incremental-header">
          <h3>增量更新</h3>
          <button class="incremental-close" @click="closeIncrementalUpdate">✕</button>
        </div>

        <!-- 配置差异预览 -->
        <div v-if="incrementalDiff" class="incremental-diff">
          <ConfigDiff
            :has-changes="incrementalDiff.has_changes"
            :summary="incrementalDiff.summary"
            :role-changes="incrementalDiff.role_changes"
            :dict-changes="incrementalDiff.dict_changes"
            :model-changes="incrementalDiff.model_changes"
            :form-changes="incrementalDiff.form_changes"
            :process-changes="[]"
            :warnings="incrementalDiff.warnings"
            :unsupported-changes="incrementalDiff.unsupported_changes"
            :show-actions="false"
          />
        </div>

        <!-- 更新步骤 -->
        <div v-if="incrementalSteps.length > 0" class="incremental-steps">
          <UpdateSteps
            :steps="incrementalSteps"
            :executing="incrementalExecuting"
            :results="incrementalResults?.results"
            :errors="incrementalResults?.errors"
            :warnings="incrementalResults?.warnings"
            @execute="executeIncrementalUpdate"
            @cancel="closeIncrementalUpdate"
            @close="closeIncrementalUpdate"
          />
        </div>
      </div>
      </div><!-- /builder-content -->
    </div>
  </div>
</template>

<script setup lang="ts">
import { API_PREFIX } from '@/utils/request'
import { ref, reactive, computed, nextTick, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ArrowLeft, Promotion } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usePreviewStore } from '@/stores/preview'
import { useUserStore } from '@/stores/user'
import { applicationApi } from '@/api/application'
import { incrementalApi, type DiffResponse, type ExecuteResponse } from '@/api/incremental'
import { conversationApi, type ConversationWithApp } from '@/api/conversation'
import { marked } from 'marked'
import ConnectModal from '@/components/ConnectModal.vue'
import EnvSelectModal from '@/components/EnvSelectModal.vue'
import { platformEnvApi } from '@/api/platformEnv'
import request from '@/utils/request'
import ConfigDiff from '@/components/ConfigDiff.vue'
import UpdateSteps from '@/components/UpdateSteps.vue'
import type { Message } from '@/types'
import ThemeToggle from '@/components/ThemeToggle.vue'

const router = useRouter()
const route = useRoute()
const store = usePreviewStore()
const userStore = useUserStore()

const messagesRef = ref<HTMLElement>()
const inputText = ref('')
const isTyping = ref(false)
const currentAgent = ref('builder')
const SHOW_PLATFORM_CONFIG = true

// ── 应用计数（导航栏徽标） ──
const appCount = ref(0)
const fetchAppCount = async () => {
  try {
    const apps = await applicationApi.list() as any[]
    appCount.value = apps.length
  } catch { /* ignore */ }
}

// ── 平台配置 iframe ──
const activeView = ref<'builder' | 'platform'>('builder')
const platformIframeUrl = ref('')
const platformAppUrl = ref('')  // 应用配置页 URL（登录后跳转用）
const platformLoading = ref(false)
const platformError = ref('')
const platformLoginHint = ref('')
const platformIframeRef = ref<HTMLIFrameElement | null>(null)

const loadPlatformUrl = async () => {
  if (!existingAppId.value) return
  platformLoading.value = true
  platformError.value = ''
  try {
    // 获取平台真实 URL，iframe 直连平台
    const data = await platformEnvApi.getEmbedUrl(existingAppId.value)
    const { url, username } = data as any
    platformIframeUrl.value = url
    platformAppUrl.value = url
    // 首次使用需要在 iframe 中登录平台（登录一次后 cookie 保持）
    if (username) {
      platformLoginHint.value = `首次使用请在下方登录平台（账号: ${username}），登录后自动进入应用配置`
    }
  } catch (e: any) {
    platformError.value = e?.response?.data?.detail || e?.message || '获取平台链接失败'
  } finally {
    platformLoading.value = false
  }
}

const switchToPlatform = () => {
  activeView.value = 'platform'
  if (!platformIframeUrl.value) {
    loadPlatformUrl()
  }
}

const navigateIframeToApp = () => {
  if (platformIframeRef.value && platformAppUrl.value) {
    platformIframeRef.value.src = platformAppUrl.value
    platformLoginHint.value = ''
  }
}

const openPlatformNewTab = () => {
  if (platformAppUrl.value || platformIframeUrl.value) {
    window.open(platformAppUrl.value || platformIframeUrl.value, '_blank')
  }
}

const onIframeError = () => {
  platformError.value = '平台页面加载失败，可能不支持 iframe 嵌入'
}

// 字段类型图标映射（兜底，防止后端返回中文导致竖排）
const FIELD_ICON_MAP: Record<string, string> = {
  '单据号': '#', '单行输入': 'T', '多行输入': '¶',
  '手机号码': 'P', '电子邮箱': '@', '下拉单选': '▼',
  '下拉多选': '☰', '数据单选': '⇢', '数据多选': '⇢', '日期时间': 'D',
  '金额': '¥', '数字': 'N', '附件上传': '⊕',
  '开关': '⊘', '人员选择': '⊙', '部门选择': '⊙',
  '地理位置': '◎', '子表': '▦', '地区地址': '◎',
  '单选框': '○', '多选框': '☐', '富文本': 'R',
  '超链接': '⊕', '证件号': '#', '签名': 'S',
}
const getFieldIcon = (f: any) => {
  // 如果 icon 是单字符或已是合法符号，直接用
  if (f.icon && f.icon.length <= 2) return f.icon
  // 否则从 type 映射
  return FIELD_ICON_MAP[f.type] || FIELD_ICON_MAP[f.icon] || 'T'
}

const agents: Record<string, { name: string; icon: string }> = {
  builder: { name: '搭建智能体', icon: '🤖' },
  assistant: { name: '辅助开发智能体', icon: '🛠️' },
  developer: { name: '复杂开发智能体', icon: '💻' }
}

const tabs = [
  { k: 'overview', l: '概览' }, { k: 'models', l: '模型' },
  { k: 'forms', l: '表单' }, { k: 'perms', l: '权限' },
  { k: 'docs', l: '文档' },
]

if (store.previewTab === 'workflow') {
  store.previewTab = 'overview'
}

const messages = reactive<Message[]>([
  { id: 0, role: 'assistant', agent: 'builder', content: '你好！我是 aPaaS 搭建智能体，可以帮你通过对话的方式在得帆云平台上快速搭建应用。\n\n你可以告诉我想要创建什么系统，我会帮你理清需求并自动生成。\n\n比如：\n• "我想做一个客户管理系统"\n• "帮我搭建一个项目管理应用"\n• "创建一个售后服务工单系统"', created_at: '' }
])

const scrollToBottom = () => { nextTick(() => { if (messagesRef.value) messagesRef.value.scrollTop = messagesRef.value.scrollHeight }) }

// 从AI回复中提取JSON配置（支持 preview 完整配置和 patch 增量修改）
const extractPreviewData = (content: string) => {
  // 提取所有 ```json 块
  const allMatches = [...content.matchAll(/```json\s*([\s\S]*?)```/g)]
  if (allMatches.length === 0) return

  for (const match of allMatches) {
    try {
      const parsed = JSON.parse((match[1] || '').trim())
      console.log('extractPreviewData: parsed type =', parsed.type, parsed)

      // 完整配置模式
      if (parsed.type === 'preview' && parsed.data) {
        if (store.preview.models.length > 0) {
          console.warn('已有配置，忽略 LLM 重复输出的完整 JSON')
          continue
        }
        store.currentApp = { name: parsed.data.appName, status: 'draft' }
        store.preview.appName = parsed.data.appName || ''
        store.preview.roles = parsed.data.roles || []
        store.preview.dicts = parsed.data.dicts || []
        store.preview.models = parsed.data.models || []
        store.preview.workflows = parsed.data.workflows || []
        store.preview.permissions = parsed.data.permissions || []

        // 自动创建 Application（如果还没有）
        if (!existingAppId.value && parsed.data.appName) {
          applicationApi.autoCreate({
            app_name: parsed.data.appName,
            config_preview: parsed.data,
            conversation_id: conversationId.value || undefined,
          }).then(result => {
            existingAppId.value = result.app_id
            router.replace({ query: { ...route.query, app_id: String(result.app_id) } })
            console.log(`Auto-created app: id=${result.app_id}, is_new=${result.is_new}`)
          }).catch(e => {
            console.error('Auto-create application failed:', e)
          })
        }
        continue
      }

      // 增量 patch 模式
      if (parsed.type === 'patch' && parsed.actions) {
        const validActions = validateAndFixActions(parsed.actions)
        console.log(`Applying patch: ${validActions.length}/${parsed.actions.length} valid actions`)
        if (validActions.length > 0) {
          applyPatch(validActions)
        }
        continue
      }

      // 兜底：如果 LLM 直接输出了字典/模型数组，尝试智能合并
      if (Array.isArray(parsed)) {
        // 猜测是字典数组还是模型数组
        if (parsed.length > 0 && parsed[0].options !== undefined) {
          // 看起来是字典数组
          console.log('Auto-detect: dict array, merging', parsed.length, 'dicts')
          for (const d of parsed) {
            const existing = store.preview.dicts.find(x => x.name === d.name || x.code === d.code)
            if (existing) {
              Object.assign(existing, d)
            } else {
              store.preview.dicts.push(d)
            }
          }
          continue
        }
        if (parsed.length > 0 && parsed[0].fields !== undefined) {
          // 看起来是模型数组
          console.log('Auto-detect: model array, merging', parsed.length, 'models')
          for (const m of parsed) {
            const existing = store.preview.models.find(x => x.name === m.name || x.code === m.code)
            if (existing) {
              Object.assign(existing, m)
            } else {
              store.preview.models.push(m)
            }
          }
          continue
        }
      }

      // 兜底：单个字典或模型对象
      if (parsed.options !== undefined && parsed.name) {
        console.log('Auto-detect: single dict, merging')
        const existing = store.preview.dicts.find(x => x.name === parsed.name || x.code === parsed.code)
        if (existing) Object.assign(existing, parsed)
        else store.preview.dicts.push(parsed)
        continue
      }

    } catch (e) {
      console.error('Failed to parse JSON block:', e)
    }
  }
}

// ── Patch 校验 & 自动修复 ──

const VALID_PATCH_OPS = new Set([
  'add_dict', 'update_dict', 'remove_dict',
  'add_field', 'update_field', 'remove_field',
  'add_model', 'remove_model',
  'add_role', 'remove_role',
  'add_workflow', 'update_workflow', 'remove_workflow',
  'add_permission', 'update_permission', 'remove_permission', 'set_permissions',
])

const generateCode = (name: string): string => {
  if (!name) return 'c_' + Math.random().toString(36).slice(2, 9)
  const ascii = name.replace(/[^a-zA-Z0-9_]/g, '').toLowerCase()
  return ascii.length >= 2 ? ascii : 'c_' + Math.random().toString(36).slice(2, 9)
}

const validateAndFixActions = (actions: any[]): any[] => {
  return actions.filter((action, i) => {
    if (!action || typeof action !== 'object') {
      console.warn(`Patch action[${i}]: 不是对象，已跳过`)
      return false
    }
    if (!action.op || !VALID_PATCH_OPS.has(action.op)) {
      console.warn(`Patch action[${i}]: 未知操作 '${action.op}'，已跳过`)
      return false
    }
    // remove 操作需要 target
    if (action.op.startsWith('remove_') && !action.target) {
      console.warn(`Patch action[${i}] (${action.op}): 缺失 target，已跳过`)
      return false
    }
    // add 操作需要 value
    if (action.op.startsWith('add_') && !action.value) {
      console.warn(`Patch action[${i}] (${action.op}): 缺失 value，已跳过`)
      return false
    }
    // field 操作需要 model
    if (['add_field', 'update_field', 'remove_field'].includes(action.op) && !action.model) {
      console.warn(`Patch action[${i}] (${action.op}): 缺失 model，已跳过`)
      return false
    }
    // 自动修复 value 中缺失的 code
    if (action.value && typeof action.value === 'object') {
      if (action.value.name && !action.value.code) {
        action.value.code = generateCode(action.value.name)
        console.log(`Patch action[${i}]: 自动生成 code '${action.value.code}'`)
      }
      // 修复 fields 中的 code
      if (Array.isArray(action.value.fields)) {
        for (const f of action.value.fields) {
          if (f && f.name && !f.code) {
            f.code = generateCode(f.name)
          }
        }
      }
      // 修复 options 中的 code
      if (Array.isArray(action.value.options)) {
        for (const opt of action.value.options) {
          if (opt && opt.name && !opt.code) {
            opt.code = generateCode(opt.name)
          }
        }
      }
    }
    return true
  })
}

// 应用 patch 操作到 store.preview
const applyPatch = (actions: any[]) => {
  for (const action of actions) {
    const { op, value, target, model } = action
    try {
      switch (op) {
        case 'add_dict':
          store.preview.dicts.push(value)
          break
        case 'update_dict': {
          const dict = store.preview.dicts.find(d => d.name === target)
          if (dict && value) Object.assign(dict, value)
          break
        }
        case 'remove_dict':
          store.preview.dicts = store.preview.dicts.filter(d => d.name !== target)
          break
        case 'add_field': {
          const m = store.preview.models.find(m => m.name === model)
          if (m) m.fields.push(value)
          break
        }
        case 'update_field': {
          const m2 = store.preview.models.find(m => m.name === model)
          if (m2) {
            const f = m2.fields.find(f => f.name === target)
            if (f && value) Object.assign(f, value)
          }
          break
        }
        case 'remove_field': {
          const m3 = store.preview.models.find(m => m.name === model)
          if (m3) m3.fields = m3.fields.filter(f => f.name !== target)
          break
        }
        case 'add_model':
          store.preview.models.push(value)
          break
        case 'remove_model':
          store.preview.models = store.preview.models.filter(m => m.name !== target)
          break
        case 'add_role':
          store.preview.roles.push(value)
          break
        case 'remove_role':
          store.preview.roles = store.preview.roles.filter(r => r.name !== target)
          break
        case 'add_workflow':
          store.preview.workflows.push(value)
          break
        case 'update_workflow': {
          const wf = store.preview.workflows.find(w => w.name === target)
          if (wf) Object.assign(wf, value)
          else store.preview.workflows.push({ name: target, ...value })
          break
        }
        case 'remove_workflow':
          store.preview.workflows = store.preview.workflows.filter(w => w.name !== target)
          break
        case 'add_permission':
          store.preview.permissions.push(value)
          break
        case 'update_permission': {
          const perm = store.preview.permissions.find(p => p.form === target)
          if (perm && value) Object.assign(perm, value)
          else store.preview.permissions.push({ form: target, ...value })
          break
        }
        case 'remove_permission':
          store.preview.permissions = store.preview.permissions.filter(p => p.form !== target)
          break
        case 'set_permissions':
          // 批量设置所有权限（替换整个数组）
          store.preview.permissions = value || []
          break
        default:
          console.warn(`Unknown patch op: ${op}`)
      }
    } catch (e) {
      console.error(`Patch action failed: ${op}`, e)
    }
  }
  // 标记配置已更新
  if (!store.currentApp) {
    store.currentApp = { name: store.preview.appName, status: 'draft' }
  }
}

// ── 直接编辑配置（不走 LLM）──

const addRole = () => {
  const name = prompt('角色名称（中文）：')
  if (!name) return
  const code = prompt('角色编码（英文，如 role_admin）：', `role_${name}`)
  if (!code) return
  store.preview.roles.push({ name, code })
}

const removeRole = (idx: number) => {
  const r = store.preview.roles[idx]
  if (!r) return
  if (confirm(`删除角色「${r.name}」？`)) {
    store.preview.roles.splice(idx, 1)
  }
}

const addDict = () => {
  const name = prompt('字典名称（中文）：')
  if (!name) return
  const code = prompt('字典编码（英文，如 dict_status）：', `dict_${name}`)
  if (!code) return
  const optsStr = prompt('选项（逗号分隔，如：选项A,选项B,选项C）：')
  const options = optsStr ? optsStr.split(/[,，]/).map((s, i) => ({ name: s.trim(), code: `opt_${i}` })) : []
  store.preview.dicts.push({ name, code, options })
}

const editDict = (idx: number) => {
  const d = store.preview.dicts[idx]
  if (!d) return
  const currentOpts = d.options?.map((o: any) => typeof o === 'string' ? o : o.name).join('，') || ''
  const newOpts = prompt(`编辑「${d.name}」的选项（逗号分隔）：`, currentOpts)
  if (newOpts === null) return
  d.options = newOpts.split(/[,，]/).filter(s => s.trim()).map((s, i) => ({
    name: s.trim(),
    code: (d.options?.[i] as any)?.code || `opt_${i}`
  }))
}

const removeDict = (idx: number) => {
  const d = store.preview.dicts[idx]
  if (!d) return
  if (confirm(`删除字典「${d.name}」？`)) {
    store.preview.dicts.splice(idx, 1)
  }
}

const conversationId = ref<number | null>(null)
const existingAppId = ref<number | null>(null)  // 从"继续完善"进来时，关联的已有应用ID
const generating = ref(false)
const showEnvSelect = ref(false)
const selectedEnvId = ref<number | null>(null)
const showApiLogs = ref(false)
const apiLogs = ref<any[]>([])
const apiLogFilter = ref('')

watch(showApiLogs, async (val) => {
  if (val && existingAppId.value) {
    try {
      const params = new URLSearchParams({ page: '1', page_size: '200' })
      if (apiLogFilter.value === 'failed') params.set('success', 'false')
      const res = await request.get(`/applications/${existingAppId.value}/api-logs?${params}`)
      apiLogs.value = (res as any).items || []
    } catch { apiLogs.value = [] }
  }
})

const onEnvSelected = (envId: number) => {
  selectedEnvId.value = envId
  showEnvSelect.value = false
  // 继续生成流程
  startGenerateWithEnv(envId)
}

// ── 对话历史 ──
const conversationList = ref<ConversationWithApp[]>([])
const selectedConversationId = ref<number | null>(null)

const getConversationLabel = (conv: ConversationWithApp) => {
  if (conv.app_name) return conv.app_name
  const title = conv.title || '新对话'
  return title.length > 30 ? title.slice(0, 30) + '...' : title
}

const formatConvTime = (dateStr: string) => {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return '今天'
  if (diff < 172800000) return '昨天'
  return `${d.getMonth() + 1}/${d.getDate()}`
}

const fetchConversationList = async () => {
  try {
    conversationList.value = await conversationApi.listWithApps({ agent_type: 'builder' })
    // 同步选中状态
    if (conversationId.value) {
      selectedConversationId.value = conversationId.value
    }
  } catch (e) {
    console.error('获取对话列表失败:', e)
  }
}

const loadConversation = async (cid: number) => {
  resetConversationWorkspace()
  conversationId.value = cid
  selectedConversationId.value = cid

  messages.splice(0, messages.length)

  try {
    const historyMessages = await conversationApi.getMessages(cid)
    if (historyMessages && historyMessages.length > 0) {
      for (const msg of historyMessages) {
        if (msg.role === 'system') {
          extractPreviewData(msg.content)
          continue
        }
        messages.push({
          id: msg.id,
          role: msg.role as any,
          agent: msg.role === 'assistant' ? 'builder' : undefined,
          content: msg.content,
          created_at: msg.created_at
        })
        if (msg.role === 'assistant') {
          extractPreviewData(msg.content)
        }
      }
      scrollToBottom()
    } else {
      // 空对话，显示欢迎消息
      messages.push({ id: 0, role: 'assistant', agent: 'builder', content: '你好！我是 aPaaS 搭建智能体，可以帮你通过对话的方式在得帆云平台上快速搭建应用。\n\n你可以告诉我想要创建什么系统，我会帮你理清需求并自动生成。', created_at: '' })
    }

    // 恢复关联的应用配置
    if (!store.preview.appName && store.preview.models.length === 0) {
      try {
        const apps = await applicationApi.list() as any[]
        const linkedApp = apps.find((a: any) => a.conversation_id === cid && a.config_preview)
        if (linkedApp?.config_preview) {
          const data = linkedApp.config_preview.data || linkedApp.config_preview
          store.preview.appName = data.appName || ''
          store.preview.models = data.models || []
          store.preview.dicts = data.dicts || []
          store.preview.roles = data.roles || []
          store.preview.workflows = data.workflows || []
          store.preview.permissions = data.permissions || []
          store.currentApp = { name: store.preview.appName, status: 'draft' }
          if (linkedApp.id && typeof linkedApp.id === 'number') {
            existingAppId.value = linkedApp.id
          }
        }
      } catch { /* ignore */ }
    }

    // 更新 URL
    router.replace(`/chat/${cid}`)
  } catch (e) {
    console.error('加载对话失败:', e)
    messages.push({ id: 0, role: 'assistant', agent: 'builder', content: '加载对话历史失败，请重试。', created_at: '' })
  }
}

const onConversationSwitch = (newId: number) => {
  if (newId && newId !== conversationId.value) {
    loadConversation(newId)
  }
}

const startNewConversation = () => {
  resetConversationWorkspace()
  conversationId.value = null
  selectedConversationId.value = null
  messages.splice(0, messages.length)
  messages.push({ id: 0, role: 'assistant', agent: 'builder', content: '你好！我是 aPaaS 搭建智能体，可以帮你通过对话的方式在得帆云平台上快速搭建应用。\n\n你可以告诉我想要创建什么系统，我会帮你理清需求并自动生成。\n\n比如：\n• "我想做一个客户管理系统"\n• "帮我搭建一个项目管理应用"\n• "创建一个售后服务工单系统"', created_at: '' })
  router.replace('/chat')
}

// ── 文档版本 ──
interface DocVersion {
  id: number
  version: number
  filename: string
  summary: string
  raw_content: string
  created_at: string
}
const docVersions = ref<DocVersion[]>([])
const docVersionsLoading = ref(false)
const docPreviewVisible = ref(false)
const docPreviewContent = ref('')
const docPreviewTitle = ref('')
const docDiffVisible = ref(false)
const docDiffLeft = ref('')
const docDiffRight = ref('')
const docDiffLeftTitle = ref('')
const docDiffRightTitle = ref('')
// docUploadInputRef removed — upload is via chat input only

const fetchDocVersions = async () => {
  docVersionsLoading.value = true
  try {
    let res: any
    if (existingAppId.value) {
      res = await applicationApi.getDocVersions(existingAppId.value)
    } else if (conversationId.value) {
      res = await applicationApi.getDocVersionsByConversation(conversationId.value)
    } else {
      docVersionsLoading.value = false
      return
    }
    const versions = Array.isArray(res) ? res : (res?.versions || res?.data || [])
    docVersions.value = versions
  } catch (e) {
    console.error('Failed to fetch doc versions', e)
  } finally {
    docVersionsLoading.value = false
  }
}

const formatDocTime = (dateStr: string) => {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const openDocPreview = (ver: DocVersion) => {
  docPreviewTitle.value = `V${ver.version} — ${ver.filename}`
  docPreviewContent.value = ver.raw_content || '（无内容）'
  docPreviewVisible.value = true
}

const openDocDiff = (ver: DocVersion) => {
  const prevVer = docVersions.value.find(v => v.version === ver.version - 1)
  if (!prevVer) return
  docDiffLeftTitle.value = `V${prevVer.version} — ${prevVer.filename}`
  docDiffRightTitle.value = `V${ver.version} — ${ver.filename}`
  docDiffLeft.value = prevVer.raw_content || ''
  docDiffRight.value = ver.raw_content || ''
  docDiffVisible.value = true
}

const computeLineDiff = (oldText: string, newText: string) => {
  const oldLines = oldText.split('\n')
  const newLines = newText.split('\n')
  // Simple LCS-based diff
  const m = oldLines.length, n = newLines.length
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0))
  for (let i = 1; i <= m; i++) {
    const currentRow = dp[i]
    const prevRow = dp[i - 1]
    if (!currentRow || !prevRow) continue
    for (let j = 1; j <= n; j++) {
      const prevDiag = prevRow[j - 1] ?? 0
      const prevUp = prevRow[j] ?? 0
      const prevLeft = currentRow[j - 1] ?? 0
      currentRow[j] = oldLines[i - 1] === newLines[j - 1] ? prevDiag + 1 : Math.max(prevUp, prevLeft)
    }
  }

  const leftResult: { text: string; type: 'same' | 'removed' }[] = []
  const rightResult: { text: string; type: 'same' | 'added' }[] = []
  let i = m, j = n
  const leftTmp: typeof leftResult = []
  const rightTmp: typeof rightResult = []
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      leftTmp.push({ text: oldLines[i - 1] || '', type: 'same' })
      rightTmp.push({ text: newLines[j - 1] || '', type: 'same' })
      i--; j--
    } else if (j > 0 && (i === 0 || (dp[i]?.[j - 1] ?? 0) >= (dp[i - 1]?.[j] ?? 0))) {
      leftTmp.push({ text: '', type: 'same' })
      rightTmp.push({ text: newLines[j - 1] || '', type: 'added' })
      j--
    } else {
      leftTmp.push({ text: oldLines[i - 1] || '', type: 'removed' })
      rightTmp.push({ text: '', type: 'same' })
      i--
    }
  }
  leftTmp.reverse()
  rightTmp.reverse()
  return { left: leftTmp, right: rightTmp }
}

const docDiffResult = computed(() => {
  if (!docDiffLeft.value && !docDiffRight.value) return { left: [], right: [] }
  return computeLineDiff(docDiffLeft.value, docDiffRight.value)
})

// 变更摘要：从 diff 的新增行中提取结构化变更（章节标题、表单、字典、角色等）
const diffChangeSummary = computed(() => {
  const changes: { type: string; text: string }[] = []
  const addedLines = docDiffResult.value.right.filter(l => l.type === 'added').map(l => l.text.trim()).filter(Boolean)
  const removedLines = docDiffResult.value.left.filter(l => l.type === 'removed').map(l => l.text.trim()).filter(Boolean)

  // 提取新增的章节标题
  for (const line of addedLines) {
    if (line.startsWith('##')) {
      changes.push({ type: 'added', text: line.replace(/^#+\s*/, '') })
    } else if (line.startsWith('|') && line.includes('【新增】')) {
      const cells = line.split('|').map(c => c.trim()).filter(Boolean)
      changes.push({ type: 'added', text: cells[0] || line })
    } else if (line.includes('【新增') || line.includes('新增')) {
      const clean = line.replace(/^[\s|*-]+/, '').replace(/\*\*/g, '')
      if (clean.length < 60) changes.push({ type: 'added', text: clean })
    }
  }

  // 提取删除的章节
  for (const line of removedLines) {
    if (line.startsWith('##')) {
      changes.push({ type: 'removed', text: line.replace(/^#+\s*/, '') })
    }
  }

  // 提取修改的行（新增中包含已有章节名称的）
  for (const line of addedLines) {
    if (line.startsWith('|') && !line.includes('【新增】') && !line.startsWith('|--') && !line.startsWith('| 字')) {
      const cells = line.split('|').map(c => c.trim()).filter(Boolean)
      if (cells.length >= 2 && cells.some(c => c.includes('**'))) {
        changes.push({ type: 'modified', text: `${cells[0]}: 选项变更` })
      }
    }
  }

  // 去重
  const seen = new Set<string>()
  return changes.filter(c => {
    const key = c.type + c.text
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }).slice(0, 30)
})

// triggerDocUpload / handleDocVersionUpload removed — doc upload is via chat input only

// ── 部署面板 ──
interface DeployStep { key: string; label: string; status: 'pending' | 'completed' | 'error'; deps_met: boolean; error?: string; result?: any }
const deployOpen = ref(false)
const deployAppId = ref<number | null>(null)
const deploySteps = ref<DeployStep[]>([])
const deployExecuting = ref<string | null>(null)
const deployRunningAll = ref(false)

// ── 编码冲突修复 ──
interface ConflictState {
  step: string
  model_name: string
  current_code: string
  message: string
  newCode: string
  resolving: boolean
}
const activeConflict = ref<ConflictState | null>(null)

const deployDoneCount = computed(() => deploySteps.value.filter(s => s.status === 'completed').length)
const deployPercent = computed(() => deploySteps.value.length ? Math.round(deployDoneCount.value / deploySteps.value.length * 100) : 0)
const deployAllDone = computed(() => deploySteps.value.length > 0 && deployDoneCount.value === deploySteps.value.length)

// 应用状态（综合 deployAllDone 和 app.status）
const appDisplayStatus = computed(() => {
  if (deployAllDone.value) return 'deployed'
  const s = store.currentApp?.status
  if (s === 'completed') return 'deployed'
  return s || 'draft'
})
const appDisplayStatusText = computed(() => {
  const s = appDisplayStatus.value
  if (s === 'deployed' || s === 'completed') return '已部署'
  if (s === 'draft') return '待生成'
  if (s === 'generating') return '生成中'
  if (s === 'failed') return '生成失败'
  return '待生成'
})

// 检测配置是否有变更（对比当前 preview 和已部署的步骤）
const hasConfigChanged = computed(() => {
  if (!deploySteps.value.length) return false
  // 当前部署链路暂时隐藏审批流程步骤：1(app) + 1(roles_dicts) + models + forms + 1(perms)
  const expectedSteps = 1 + 1 + store.preview.models.length + store.preview.models.length + 1
  return expectedSteps !== deploySteps.value.length
})

// ── 增量更新 ──
const showIncrementalUpdate = ref(false)
const incrementalDiff = ref<DiffResponse | null>(null)
const incrementalExecuting = ref(false)
const incrementalSteps = ref<{ key: string; label: string; status: 'pending' | 'running' | 'completed' | 'error'; details?: string; error?: string }[]>([])
const incrementalResults = ref<ExecuteResponse | null>(null)

function resetConversationWorkspace() {
  store.reset()
  store.pendingFile = null
  existingAppId.value = null
  generating.value = false
  showEnvSelect.value = false
  selectedEnvId.value = null
  selectedModelIndices.value = []
  activeConflict.value = null
  isTyping.value = false
  showApiLogs.value = false
  apiLogs.value = []
  apiLogFilter.value = ''

  activeView.value = 'builder'
  platformIframeUrl.value = ''
  platformAppUrl.value = ''
  platformLoading.value = false
  platformError.value = ''
  platformLoginHint.value = ''

  docVersions.value = []
  docVersionsLoading.value = false
  docPreviewVisible.value = false
  docPreviewContent.value = ''
  docPreviewTitle.value = ''
  docDiffVisible.value = false
  docDiffLeft.value = ''
  docDiffRight.value = ''
  docDiffLeftTitle.value = ''
  docDiffRightTitle.value = ''

  deployOpen.value = false
  deployAppId.value = null
  deploySteps.value = []
  deployExecuting.value = null
  deployRunningAll.value = false

  showIncrementalUpdate.value = false
  incrementalDiff.value = null
  incrementalExecuting.value = false
  incrementalSteps.value = []
  incrementalResults.value = null
}

const deployGroups = computed(() => {
  const defs = [
    { title: '初始化', icon: '🚀', test: (s: DeployStep) => s.key === 'create_app' },
    { title: '角色', icon: '👥', test: (s: DeployStep) => s.key.startsWith('create_role:') || s.key === 'create_roles_dicts' },
    { title: '数据字典', icon: '📖', test: (s: DeployStep) => s.key.startsWith('create_dict:') },
    { title: '数据模型', icon: '🗃', test: (s: DeployStep) => s.key.startsWith('create_model:') },
    { title: '表单配置', icon: '📋', test: (s: DeployStep) => s.key.startsWith('create_form:') },
    { title: '权限配置', icon: '🔐', test: (s: DeployStep) => s.key === 'configure_permissions' },
  ]
  return defs.map(d => {
    const ss = deploySteps.value.filter(d.test)
    return { ...d, steps: ss, allDone: ss.length > 0 && ss.every(s => s.status === 'completed'), hasError: ss.some(s => s.status === 'error'), doneCount: ss.filter(s => s.status === 'completed').length }
  }).filter(d => d.steps.length > 0)
})

async function openDeployPanel() {
  if (existingAppId.value) {
    deployAppId.value = existingAppId.value
    deployOpen.value = true
    await loadDeployStatus()
  }
}

async function openInPlatform() {
  if (SHOW_PLATFORM_CONFIG && store.currentApp?.apaas_app_id) {
    switchToPlatform()
    return
  }
  router.push('/apps')
}

async function loadDeployStatus() {
  if (!deployAppId.value) return
  try {
    const resp = await applicationApi.getStepStatus(deployAppId.value)
    deploySteps.value = resp.steps || []
  } catch { /* ignore */ }
}

async function deployExec(key: string) {
  if (!deployAppId.value) return
  deployExecuting.value = key
  try {
    const resp = await applicationApi.executeStep(deployAppId.value, key)
    if (resp.status === 'conflict' && resp.conflict) {
      handleConflict(resp, key)
    } else if (resp.status === 'error') {
      // create_app 失败且涉及编码问题，弹出编码修改框
      if (key === 'create_app' && resp.error && (resp.error.includes('编码') || resp.error.includes('code') || resp.error.includes('Code'))) {
        try {
          const { value: newCode } = await ElMessageBox.prompt(
            `创建失败：${resp.error}\n\n请输入新的应用编码（如 asset-manage）：`,
            '修改应用编码',
            {
              inputValue: 'app-' + Date.now().toString(36),
              inputPattern: /^[a-zA-Z][a-zA-Z0-9\-]*$/,
              inputErrorMessage: '编码只能包含英文字母、数字和连字符(-)，且以字母开头',
              confirmButtonText: '重试',
              cancelButtonText: '取消'
            }
          )
          if (newCode) {
            // 更新后端应用编码
            await request.patch(`/applications/${deployAppId.value}/code`, { app_code: newCode })
            // 重置步骤并重试
            await applicationApi.resetStep(deployAppId.value, key)
            await loadDeployStatus()
            deployExecuting.value = null
            await deployExec(key)
            return
          }
        } catch { /* cancelled */ }
      } else {
        ElMessage.error(resp.error || '失败')
      }
    }
  } catch (e: any) { ElMessage.error(e.message || '失败') }
  finally { deployExecuting.value = null; await loadDeployStatus() }
}

async function deployRedo(key: string) {
  if (!deployAppId.value) return
  await applicationApi.resetStep(deployAppId.value, key)
  await loadDeployStatus()
  await deployExec(key)
}

async function deployRunAll() {
  if (!deployAppId.value || deployRunningAll.value || deployExecuting.value !== null || deployAllDone.value) return

  deployRunningAll.value = true
  try {
    for (const s of deploySteps.value) {
      if (s.status === 'completed') continue
      await loadDeployStatus()
      const fresh = deploySteps.value.find(x => x.key === s.key)
      if (!fresh?.deps_met) continue
      deployExecuting.value = s.key
      const resp = await applicationApi.executeStep(deployAppId.value, s.key)
      await loadDeployStatus()
      if (resp.status === 'conflict' && resp.conflict) {
        handleConflict(resp, s.key)
        deployExecuting.value = null
        return  // 暂停，等用户修复冲突后可再次一键执行
      }
      if (resp.status === 'error') {
        ElMessage.error(resp.error + '，已暂停')
        deployExecuting.value = null
        return
      }
    }
    deployExecuting.value = null
    ElMessage.success('全部完成！')
  } catch (e: any) {
    ElMessage.error(e.message || '失败')
  } finally {
    deployExecuting.value = null
    deployRunningAll.value = false
    await loadDeployStatus()
  }
}
function handleConflict(resp: any, stepKey: string) {
  const c = resp.conflict
  // 在对话区显示冲突信息
  messages.push({
    id: Date.now(),
    role: 'assistant',
    agent: 'builder',
    content: `\u26a0\ufe0f **编码冲突**：${c.model_name}的编码 \`${c.current_code}\` 在平台上已存在。\n\n请在下方输入一个新的编码来替换它：`,
    created_at: new Date().toISOString(),
  })
  scrollToBottom()
  // 设置冲突状态
  activeConflict.value = {
    step: stepKey,
    model_name: c.model_name,
    current_code: c.current_code,
    message: c.message,
    newCode: c.current_code + '_v2',
    resolving: false,
  }
}

async function resolveConflictAndRetry() {
  if (!activeConflict.value || !deployAppId.value) return
  const c = activeConflict.value
  if (!c.newCode.trim()) { ElMessage.warning('请输入新编码'); return }
  if (c.newCode === c.current_code) { ElMessage.warning('新编码不能和旧编码相同'); return }

  c.resolving = true
  try {
    await applicationApi.resolveConflict(deployAppId.value, {
      step: c.step,
      model_name: c.model_name,
      old_code: c.current_code,
      new_code: c.newCode,
    })
    // 在对话区显示修复成功
    messages.push({
      id: Date.now(),
      role: 'assistant',
      agent: 'builder',
      content: `\u2705 编码已更新：\`${c.current_code}\` \u2192 \`${c.newCode}\`\n\n正在重试该步骤...`,
      created_at: new Date().toISOString(),
    })
    scrollToBottom()
    const conflictStep = c.step
    activeConflict.value = null
    // 重新加载配置预览（编码已变）
    try {
      const appData = await applicationApi.get(deployAppId.value) as any
      if (appData.config_preview) {
        const cfg = typeof appData.config_preview === 'string' ? JSON.parse(appData.config_preview) : appData.config_preview
        const d = cfg.data || cfg
        store.preview = { appName: appData.app_name, models: d.models || [], roles: d.roles || [], dicts: d.dicts || [], workflows: d.workflows || [], permissions: d.permissions || [] }
      }
    } catch { /* ignore */ }
    // 自动重试
    await deployExec(conflictStep)
  } catch (e: any) {
    ElMessage.error(e.message || '修复失败')
  } finally {
    if (activeConflict.value) activeConflict.value.resolving = false
  }
}

function cancelConflict() {
  activeConflict.value = null
  messages.push({
    id: Date.now(),
    role: 'assistant',
    agent: 'builder',
    content: '\u274c 已取消编码修复。你可以在部署面板中点击"重试"来重新执行该步骤。',
    created_at: new Date().toISOString(),
  })
  scrollToBottom()
}

const selectedModelIndices = ref<number[]>([])  // 选中的模型索引，空=全选

const toggleSelectAll = () => {
  if (selectedModelIndices.value.length === 0) {
    // 当前全选状态 → 不变（全选就是空数组）
    // 实际上checkbox checked时取消全选没意义，保持全选
  } else {
    selectedModelIndices.value = []
  }
}
const toggleModelSelect = (idx: number) => {
  const total = store.preview.models.length
  if (selectedModelIndices.value.length === 0) {
    // 从全选变为取消一个：生成除了idx之外的所有索引
    selectedModelIndices.value = Array.from({ length: total }, (_, i) => i).filter(i => i !== idx)
  } else if (selectedModelIndices.value.includes(idx)) {
    selectedModelIndices.value = selectedModelIndices.value.filter(i => i !== idx)
    // 如果取消后为空，恢复全选
    if (selectedModelIndices.value.length === 0) {
      // 空 = 全选，但用户意图是全不选？不合理，至少选一个
      selectedModelIndices.value = [0]
    }
  } else {
    selectedModelIndices.value.push(idx)
    // 如果全部选中，回到空数组（全选）
    if (selectedModelIndices.value.length === total) {
      selectedModelIndices.value = []
    }
  }
}

const startGenerate = async () => {
  // 检查是否已部署到平台（有 apaas_app_id）
  if (existingAppId.value) {
    const existingApp = await applicationApi.get(existingAppId.value)
    if ((existingApp as any).apaas_app_id) {
      // 先检查是否有未完成的步骤 — 如果有，直接打开部署面板继续
      try {
        const stepStatus = await applicationApi.getStepStatus(existingAppId.value)
        const steps = stepStatus.steps || []
        const hasIncomplete = steps.some((s: any) => s.status !== 'completed')
        if (hasIncomplete) {
          // 有未完成步骤，直接打开部署面板继续
          deployAppId.value = existingAppId.value
          deployOpen.value = true
          await loadDeployStatus()
          return
        }
      } catch { /* ignore, fall through to incremental */ }
      // 所有步骤都完成了，走增量更新流程
      await startIncrementalUpdate(existingAppId.value)
      return
    }
    // 应用已绑定环境？直接继续
    if ((existingApp as any).platform_env_id) {
      selectedEnvId.value = (existingApp as any).platform_env_id
    }
  }

  // 检查是否有可用环境
  if (!selectedEnvId.value) {
    try {
      const envs = await platformEnvApi.list()
      const defaultEnv = envs.find(e => e.is_default && e.status === 'connected')
      if (defaultEnv) {
        selectedEnvId.value = defaultEnv.id
      } else if (envs.some(e => e.status === 'connected')) {
        // 有已连接环境但没默认，弹出选择
        showEnvSelect.value = true
        return
      } else {
        // 没有任何已连接环境
        ElMessage.warning('请先在环境管理中添加并连接平台环境')
        router.push('/platform-envs')
        return
      }
    } catch {
      ElMessage.warning('请先在环境管理中添加平台环境')
      router.push('/platform-envs')
      return
    }
  }

  await startGenerateWithEnv(selectedEnvId.value!)
}

const startGenerateWithEnv = async (envId: number) => {
  generating.value = true
  try {

    // 未部署，执行全量生成流程 — 让用户确认/修改应用编码
    const defaultCode = 'app-' + Date.now().toString(36)
    let appCode: string
    try {
      const { value } = await ElMessageBox.prompt(
        '应用编码创建后不可修改，请确认或调整（如 asset-manage）：',
        '确认应用编码',
        {
          inputValue: defaultCode,
          inputPattern: /^[a-zA-Z][a-zA-Z0-9\-]*$/,
          inputErrorMessage: '编码只能包含英文字母、数字和连字符(-)，且以字母开头',
          confirmButtonText: '确认生成',
          cancelButtonText: '取消',
        }
      )
      appCode = value
    } catch {
      // 用户取消
      generating.value = false
      return
    }

    const payload = {
      conversation_id: conversationId.value || 0,
      app_name: store.preview.appName,
      app_code: appCode,
      description: store.preview.appName,
      platform_env_id: envId,
      config_preview: {
        type: 'preview',
        data: { ...store.preview },
        ...(selectedModelIndices.value.length > 0 ? { selected_model_indices: selectedModelIndices.value } : {})
      }
    }

    let newAppId: number
    if (existingAppId.value) {
      const app = await applicationApi.update(existingAppId.value, payload)
      newAppId = (app as any).id
    } else {
      const app = await applicationApi.create(payload)
      newAppId = (app as any).id
      existingAppId.value = newAppId
    }
    // 不跳转，在本页打开部署面板
    deployAppId.value = newAppId
    deployOpen.value = true
    await loadDeployStatus()
  } catch (e: any) {
    ElMessage.error('创建应用失败: ' + (e.message || ''))
  } finally {
    generating.value = false
  }
}

// 开始增量更新流程
const startIncrementalUpdate = async (appId: number) => {
  try {
    // 构建新配置
    const newConfig = {
      type: 'preview',
      data: { ...store.preview },
      ...(selectedModelIndices.value.length > 0 ? { selected_model_indices: selectedModelIndices.value } : {})
    }

    // 计算差异
    const diff = await incrementalApi.computeDiff(appId, newConfig)
    incrementalDiff.value = diff

    if (!diff.has_changes) {
      ElMessage.info('配置无变更，无需更新')
      generating.value = false
      return
    }

    // 显示增量更新面板
    deployAppId.value = appId
    showIncrementalUpdate.value = true
    incrementalSteps.value = buildIncrementalSteps(diff)
    incrementalResults.value = null
    generating.value = false
  } catch (e: any) {
    ElMessage.error('计算配置差异失败: ' + (e.message || ''))
    generating.value = false
  }
}

// 构建增量更新步骤列表
const buildIncrementalSteps = (diff: DiffResponse) => {
  const steps: { key: string; label: string; status: 'pending' | 'running' | 'completed' | 'error'; details?: string; error?: string }[] = []

  if (diff.role_changes.length > 0) {
    steps.push({ key: 'roles', label: '更新角色', status: 'pending', details: `${diff.role_changes.length} 个变更` })
  }
  if (diff.dict_changes.length > 0) {
    steps.push({ key: 'dicts', label: '更新字典', status: 'pending', details: `${diff.dict_changes.length} 个变更` })
  }
  if (diff.model_changes.length > 0) {
    steps.push({ key: 'models', label: '更新模型', status: 'pending', details: `${diff.model_changes.length} 个变更` })
  }
  if (diff.form_changes.length > 0) {
    steps.push({ key: 'forms', label: '更新表单', status: 'pending', details: `${diff.form_changes.length} 个变更` })
  }

  return steps
}

// 执行增量更新（流式）
const executeIncrementalUpdate = async () => {
  if (!deployAppId.value || !incrementalDiff.value) return

  incrementalExecuting.value = true

  // 重置所有步骤状态为 pending
  for (const step of incrementalSteps.value) {
    step.status = 'pending'
    step.details = undefined
    step.error = undefined
  }

  // 构建新配置
  const newConfig = {
    type: 'preview',
    data: { ...store.preview },
    ...(selectedModelIndices.value.length > 0 ? { selected_model_indices: selectedModelIndices.value } : {})
  }

  // 获取 token
  const token = userStore.token
  if (!token) {
    ElMessage.error('未登录，请重新登录')
    incrementalExecuting.value = false
    return
  }

  // 使用流式接口执行增量更新
  incrementalApi.executeUpdateStream(
    deployAppId.value,
    newConfig,
    token,
    // onProgress
    (event) => {
      // 更新对应阶段的步骤状态
      if (event.stage && event.stage !== 'init') {
        const stepKey = event.stage
        const step = incrementalSteps.value.find(s => s.key === stepKey)
        if (step) {
          if (event.status === 'running') {
            step.status = 'running'
            step.details = event.step
          } else if (event.status === 'done') {
            step.status = 'completed'
            step.details = event.step
          }
        }
      }
    },
    // onComplete
    (result) => {
      incrementalResults.value = result
      incrementalExecuting.value = false

      // 确保所有步骤都标记为完成
      for (const step of incrementalSteps.value) {
        if (step.status === 'running' || step.status === 'pending') {
          step.status = 'completed'
        }
        // 添加详细结果
        const category = step.key as keyof typeof result.results
        if (result.results[category] && result.results[category].length > 0) {
          step.details = result.results[category].join(', ')
        }
      }

      // 检查是否有错误
      if (result.errors && result.errors.length > 0) {
        for (const step of incrementalSteps.value) {
          const matchedError = result.errors.find(e => e.toLowerCase().includes(step.key))
          if (matchedError) {
            step.status = 'error'
            step.error = matchedError
          }
        }
        ElMessage.warning('部分更新失败，请查看详情')
      } else {
        ElMessage.success('增量更新完成！')
      }
    },
    // onError
    (message) => {
      incrementalExecuting.value = false
      ElMessage.error('增量更新失败: ' + message)
      for (const step of incrementalSteps.value) {
        if (step.status === 'running') {
          step.status = 'error'
          step.error = message
        }
      }
    }
  )
}

// 关闭增量更新面板
const closeIncrementalUpdate = () => {
  showIncrementalUpdate.value = false
  incrementalDiff.value = null
  incrementalSteps.value = []
  incrementalResults.value = null
}

const handleDocUpload = async (e: Event) => {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  target.value = '' // reset for re-upload

  // 增量流程：已有关联应用时，走增量文档上传（不再依赖 preview 状态）
  if (existingAppId.value) {
    await handleIncrementalDocUpload(file)
    return
  }

  const userMsgId = Date.now()
  messages.push({ id: userMsgId, role: 'user', content: `📄 上传设计文档: ${file.name}`, created_at: '' })

  // 结构化进度状态
  const progressMsgId = userMsgId + 1
  const phases = reactive<Record<string, { icon: string, label: string, status: string, detail: string }>>({
    skeleton: { icon: '📋', label: '提取骨架', status: 'pending', detail: '' },
    dicts: { icon: '📖', label: '字典选项', status: 'pending', detail: '' },
    models: { icon: '🗃', label: '模型字段', status: 'pending', detail: '' },
    complete: { icon: '✨', label: '拼装配置', status: 'pending', detail: '' },
  })

  const buildProgressContent = () => {
    const lines = [`**📄 解析文档：${file.name}**\n`]
    for (const [, p] of Object.entries(phases)) {
      const icon = p.status === 'done' ? '✅' : p.status === 'running' ? '🔄' : '○'
      lines.push(`${icon} **${p.label}**　${p.detail}`)
    }
    return lines.join('\n')
  }

  messages.push({ id: progressMsgId, role: 'assistant', agent: 'builder', content: buildProgressContent(), created_at: '' })
  scrollToBottom()

  try {
    const token = localStorage.getItem('token')
    const formData = new FormData()
    formData.append('file', file)

    const response = await fetch(`${API_PREFIX}/applications/upload-doc-with-conversation`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body: formData
    })

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: '请求失败' }))
      throw new Error(err.detail || '文档上传失败')
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let finalResult: any = null

    while (reader) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      let currentEvent = ''
      for (const line of lines) {
        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          const dataStr = line.slice(5).trim()
          if (!dataStr) continue
          try {
            const data = JSON.parse(dataStr)

            if (currentEvent === 'progress') {
              const msg = data.message || ''
              // 解析 [phase] message 格式
              const phaseMatch = msg.match(/^\[(\w+)\]\s*(.*)/)
              if (phaseMatch) {
                const [, phase, detail] = phaseMatch
                if (phases[phase]) {
                  phases[phase].status = 'running'
                  phases[phase].detail = detail

                  // 如果当前 phase 完成了
                  if (detail.includes('完成')) {
                    phases[phase].status = 'done'
                  }
                }
              }

              // 实时更新预览：字典批次
              if (data.batch && Array.isArray(data.batch)) {
                const phaseKey = phaseMatch?.[1] || ''
                if (phaseKey === 'dicts') {
                  for (const d of data.batch) {
                    if (!store.preview.dicts.find((x: any) => x.code === d.code)) {
                      store.preview.dicts.push(d)
                    }
                  }
                } else if (phaseKey === 'models') {
                  for (const m of data.batch) {
                    if (!store.preview.models.find((x: any) => x.code === m.code)) {
                      store.preview.models.push(m)
                    }
                  }
                } else if (phaseKey === 'workflows') {
                  for (const w of data.batch) {
                    store.preview.workflows.push(w)
                  }
                } else if (phaseKey === 'permissions') {
                  if (!store.preview.permissions) store.preview.permissions = []
                  for (const p of data.batch) {
                    const existing = store.preview.permissions.find((x: any) => x.form === p.form)
                    if (existing) Object.assign(existing, p)
                    else store.preview.permissions.push(p)
                  }
                }
              }

              // 骨架完成时设置基础信息
              if (data.data?.appName && !store.preview.appName) {
                store.preview.appName = data.data.appName
                store.preview.roles = data.data.roles || []
                store.currentApp = { name: data.data.appName, status: 'draft' }
              }

              // 更新进度消息
              const pmsg = messages.find(m => m.id === progressMsgId)
              if (pmsg) {
                pmsg.content = buildProgressContent()
              }
              scrollToBottom()

            } else if (currentEvent === 'done') {
              finalResult = data
            } else if (currentEvent === 'error') {
              throw new Error(data.message || '文档解析失败')
            }
          } catch (parseErr: any) {
            if (parseErr.message && !parseErr.message.includes('JSON')) throw parseErr
          }
        }
      }
    }

    // 完成：更新进度消息为最终总结
    const pmsg = messages.find(m => m.id === progressMsgId)

    if (finalResult) {
      conversationId.value = finalResult.conversation_id
      router.replace(`/chat/${finalResult.conversation_id}`)

      // 最终更新 store
      const previewData = finalResult.preview?.data || finalResult.preview
      if (previewData?.appName || previewData?.models) {
        store.currentApp = { name: previewData.appName, status: 'draft' }
        store.preview.appName = previewData.appName || ''
        store.preview.roles = previewData.roles || []
        store.preview.dicts = previewData.dicts || []
        store.preview.models = previewData.models || []
        store.preview.workflows = previewData.workflows || []
        store.preview.permissions = previewData.permissions || []
      }

      // 文档上传完成后自动创建 Application（如果还没有）
      if (!existingAppId.value && store.preview.appName) {
        try {
          const result = await applicationApi.autoCreate({
            app_name: store.preview.appName,
            config_preview: { ...store.preview },
            conversation_id: conversationId.value || undefined,
          })
          existingAppId.value = result.app_id
          router.replace({ query: { ...route.query, app_id: String(result.app_id) } })
          console.log(`Doc upload auto-created app: id=${result.app_id}, is_new=${result.is_new}`)
        } catch (e) {
          console.warn('文档上传后自动创建应用失败:', e)
        }
      }

      // 文档上传完成后自动刷新文档版本列表
      fetchDocVersions()

      // 替换进度消息为完成总结
      const completePhase = phases.complete
      if (pmsg && completePhase) {
        completePhase.status = 'done'
        completePhase.detail = `${store.preview.models.length} 模型, ${store.preview.dicts.length} 字典, ${store.preview.roles.length} 角色`
        if (!store.connected) {
          pmsg.content = buildProgressContent() + '\n\n配置已就绪！请先连接得帆云平台环境，然后点击"开始生成"部署。'
          // 自动弹出连接弹窗
          store.showConnectModal = true
        } else {
          pmsg.content = buildProgressContent() + '\n\n你可以调整配置，或点击"开始生成"部署到平台。'
        }
      }
    } else if (pmsg) {
      pmsg.content += '\n\n⚠️ 解析完成但未获取到配置数据'
    }
  } catch (err: any) {
    const pmsg = messages.find(m => m.id === progressMsgId)
    if (pmsg) {
      pmsg.content += `\n\n❌ 解析失败: ${err?.message || '未知错误'}`
    } else {
      messages.push({ id: Date.now(), role: 'assistant', agent: 'builder', content: `文档解析失败: ${err?.message || '未知错误'}`, created_at: '' })
    }
  }
  scrollToBottom()
}

// ── 增量文档变更 ──
const executingChangePlan = ref(false)
const expandedGroups = reactive<Record<string, boolean>>({ added: true, modified: true, removed: true })

const addedActions = computed(() =>
  store.changePlan?.actions.filter(a => a.op?.startsWith('add')) || []
)
const modifiedActions = computed(() =>
  store.changePlan?.actions.filter(a => a.op?.startsWith('modify') || a.op?.startsWith('update')) || []
)
const removedActions = computed(() =>
  store.changePlan?.actions.filter(a => a.op?.startsWith('remove') || a.op?.startsWith('delete')) || []
)
const changePlanResourceDiff = computed<DiffResponse | null>(() => {
  const diff = store.changePlan?.diffSummary as Partial<DiffResponse> | null | undefined
  if (!diff) return null
  if (!Array.isArray(diff.role_changes)) return null
  if (!Array.isArray(diff.dict_changes)) return null
  if (!Array.isArray(diff.model_changes)) return null
  if (!Array.isArray(diff.form_changes)) return null
  if (!Array.isArray(diff.process_changes)) return null
  if (!Array.isArray(diff.warnings)) return null
  if (!Array.isArray(diff.unsupported_changes)) return null
  return {
    has_changes: Boolean(diff.has_changes),
    summary: diff.summary || '',
    role_changes: diff.role_changes,
    dict_changes: diff.dict_changes,
    model_changes: diff.model_changes,
    form_changes: diff.form_changes,
    process_changes: diff.process_changes,
    warnings: diff.warnings,
    unsupported_changes: diff.unsupported_changes
  }
})
const changePlanSelectedCount = computed(() =>
  store.changePlan?.actions.filter(a => a.selected).length || 0
)
const changePlanTotalCount = computed(() =>
  store.changePlan?.actions.length || 0
)

const toggleChangePlanGroup = (group: string) => {
  expandedGroups[group] = !expandedGroups[group]
}

const changePlanSelectAll = (val: boolean) => {
  if (!store.changePlan) return
  store.changePlan.actions.forEach(a => { a.selected = val })
}

const cancelChangePlan = () => {
  store.showChangePlan = false
  store.changePlan = null
  messages.push({
    id: Date.now(),
    role: 'assistant',
    agent: 'builder',
    content: '已取消变更计划。',
    created_at: ''
  })
  scrollToBottom()
}

const handleIncrementalDocUpload = async (file: File) => {
  const appId = existingAppId.value!
  const userMsgId = Date.now()
  messages.push({ id: userMsgId, role: 'user', content: `📄 上传文档新版本: ${file.name}`, created_at: '' })

  const progressMsgId = userMsgId + 1
  messages.push({
    id: progressMsgId,
    role: 'assistant',
    agent: 'builder',
    content: '正在分析文档变更...',
    created_at: ''
  })
  scrollToBottom()

  try {
    // 如果没有会话ID，自动创建一个关联到当前应用
    if (!conversationId.value) {
      try {
        const newConv = await conversationApi.create({ agent_type: 'builder' })
        conversationId.value = newConv.id
        selectedConversationId.value = newConv.id
      } catch {
        throw new Error('创建会话失败')
      }
    }
    const token = localStorage.getItem('token')
    const formData = new FormData()
    formData.append('file', file)
    formData.append('conversation_id', conversationId.value.toString())

    const url = applicationApi.uploadDocVersionUrl(appId)
    const response = await fetch(url, {
      method: 'POST',
      headers: token ? { 'Authorization': `Bearer ${token}` } : {},
      body: formData
    })

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: '请求失败' }))
      throw new Error(err.detail || '文档上传失败')
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let changePlanData: any = null

    while (reader) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      let currentEvent = ''
      for (const line of lines) {
        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          const dataStr = line.slice(5).trim()
          if (!dataStr) continue
          try {
            const data = JSON.parse(dataStr)

            if (currentEvent === 'progress') {
              const pmsg = messages.find(m => m.id === progressMsgId)
              if (pmsg) {
                const step = data.step || data.phase || ''
                const msg = data.message || ''
                const icon = step === 'indexing' ? '📑' : step === 'parsing' ? '🔍' : step === 'diffing' ? '📊' : '⏳'
                pmsg.content = `${icon} ${msg}`
              }
              scrollToBottom()
            } else if (currentEvent === 'done') {
              changePlanData = data.change_plan || data
              // P0: 用 V2 配置更新 preview store
              if (data.parsed_config) {
                const pc = data.parsed_config.data || data.parsed_config
                store.preview.appName = pc.appName || store.preview.appName
                store.preview.models = pc.models || []
                store.preview.dicts = pc.dicts || []
                store.preview.roles = pc.roles || []
                store.preview.workflows = pc.workflows || []
                store.preview.permissions = pc.permissions || []
                store.currentApp = { name: store.preview.appName, status: 'draft' }
              }
            } else if (currentEvent === 'error') {
              throw new Error(data.message || '文档分析失败')
            }
          } catch (parseErr: any) {
            if (parseErr.message && !parseErr.message.includes('JSON')) throw parseErr
          }
        }
      }
    }

    // 处理变更计划
    if (changePlanData) {
      // 确保 actions 有 selected 属性
      if (changePlanData.actions) {
        changePlanData.actions = changePlanData.actions.map((a: any) => ({
          ...a,
          selected: a.selected !== undefined ? a.selected : true
        }))
      }
      // 映射后端字段名到前端期望的字段名
      const toVersion = changePlanData.version || 1
      store.changePlan = {
        ...changePlanData,
        id: changePlanData.change_plan_id || changePlanData.id,
        fromVersion: changePlanData.is_first_version ? 0 : (toVersion - 1),
        toVersion: toVersion,
        diffSummary: changePlanData.diff || changePlanData.diffSummary,
      }
      store.showChangePlan = true

      const pmsg = messages.find(m => m.id === progressMsgId)
      if (pmsg) {
        // op 格式为 add_model, add_dict, modify_field, remove_role 等
        const addCount = changePlanData.actions?.filter((a: any) => a.op?.startsWith('add')).length || 0
        const modCount = changePlanData.actions?.filter((a: any) => a.op?.startsWith('modify') || a.op?.startsWith('update')).length || 0
        const delCount = changePlanData.actions?.filter((a: any) => a.op?.startsWith('remove') || a.op?.startsWith('delete')).length || 0
        pmsg.content = `📊 文档变更分析完成：新增 ${addCount} 项，修改 ${modCount} 项，删除 ${delCount} 项。\n\n请在右侧面板确认要执行的变更。`
      }
    } else {
      const pmsg = messages.find(m => m.id === progressMsgId)
      if (pmsg) {
        pmsg.content = '文档分析完成，未发现配置变更。'
      }
    }
  } catch (err: any) {
    const pmsg = messages.find(m => m.id === progressMsgId)
    if (pmsg) {
      pmsg.content = `❌ 文档变更分析失败: ${err?.message || '未知错误'}`
    } else {
      messages.push({
        id: Date.now(),
        role: 'assistant',
        agent: 'builder',
        content: `文档变更分析失败: ${err?.message || '未知错误'}`,
        created_at: ''
      })
    }
  }
  scrollToBottom()
}

const executeChangePlan = async () => {
  if (!store.changePlan || !existingAppId.value) return
  const appId = existingAppId.value
  const planId = store.changePlan.id

  executingChangePlan.value = true

  // 构建 selections
  const selections: Record<string, boolean> = {}
  store.changePlan.actions.forEach(a => {
    selections[a.id] = a.selected
  })

  const execMsgId = Date.now()
  messages.push({
    id: execMsgId,
    role: 'assistant',
    agent: 'builder',
    content: '正在执行变更计划...',
    created_at: ''
  })
  scrollToBottom()

  try {
    // 先提交 selections
    await applicationApi.updateSelections(appId, planId, selections)

    // SSE 执行
    const token = localStorage.getItem('token')
    const url = applicationApi.executeChangePlanUrl(appId, planId)
    const response = await fetch(url, {
      method: 'POST',
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    })

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: '请求失败' }))
      throw new Error(err.detail || '执行失败')
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let updatedConfig: any = null

    while (reader) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      let currentEvent = ''
      for (const line of lines) {
        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          const dataStr = line.slice(5).trim()
          if (!dataStr) continue
          try {
            const data = JSON.parse(dataStr)

            if (currentEvent === 'progress') {
              const emsg = messages.find(m => m.id === execMsgId)
              if (emsg) {
                const msg = data.message || ''
                const step = data.step || ''
                const icon = data.status === 'done' ? '✅' : '⏳'
                emsg.content = `${icon} ${msg || step}`
              }
              scrollToBottom()
            } else if (currentEvent === 'done') {
              updatedConfig = data.updated_config || data.config || data
            } else if (currentEvent === 'error') {
              throw new Error(data.message || '执行失败')
            }
          } catch (parseErr: any) {
            if (parseErr.message && !parseErr.message.includes('JSON')) throw parseErr
          }
        }
      }
    }

    // 完成：更新 store
    if (updatedConfig) {
      const previewData = updatedConfig.data || updatedConfig
      if (previewData.appName || previewData.models) {
        store.preview.appName = previewData.appName || store.preview.appName
        store.preview.roles = previewData.roles || store.preview.roles
        store.preview.dicts = previewData.dicts || store.preview.dicts
        store.preview.models = previewData.models || store.preview.models
        store.preview.workflows = previewData.workflows || store.preview.workflows
        store.preview.permissions = previewData.permissions || store.preview.permissions
      }
    }

    const emsg = messages.find(m => m.id === execMsgId)
    if (emsg) {
      emsg.content = `✅ 变更计划执行完成！已选 ${changePlanSelectedCount.value} 项变更已应用。`
    }

    // 关闭面板
    store.showChangePlan = false
    store.changePlan = null
  } catch (err: any) {
    const emsg = messages.find(m => m.id === execMsgId)
    if (emsg) {
      emsg.content = `❌ 变更执行失败: ${err?.message || '未知错误'}`
    }
  } finally {
    executingChangePlan.value = false
  }
  scrollToBottom()
}

// ── 分阶段生成配置 ──
const assembling = ref(false)
const assembleMessage = ref('')

const startAssembleConfig = async () => {
  if (!conversationId.value) {
    await createConversation()
  }
  if (!conversationId.value) return

  assembling.value = true
  assembleMessage.value = '正在分析需求...'

  // 收集最近的用户消息作为需求
  const userMessages = messages.filter(m => m.role === 'user').map(m => m.content)
  const prompt = userMessages.join('\n') || '请根据对话内容生成应用配置'

  try {
    const token = localStorage.getItem('token')
    const response = await fetch(`${API_PREFIX}/chat/generate-config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ conversation_id: conversationId.value, message: prompt })
    })

    if (!response.ok) throw new Error('请求失败')

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    if (!reader) throw new Error('无法读取响应')

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const chunk = decoder.decode(value, { stream: true })
      for (const line of chunk.split('\n')) {
        if (!line.startsWith('data: ')) continue
        try {
          const evt = JSON.parse(line.slice(6))

          if (evt.phase && evt.message) {
            assembleMessage.value = evt.message
          }

          // 骨架完成 → 显示模型名和字典名（占位）
          if (evt.phase === 'skeleton' && evt.status === 'done' && evt.data) {
            const sk = evt.data
            store.preview.appName = sk.appName || ''
            store.preview.roles = sk.roles || []
            // 用骨架的 dict_names 创建空字典占位
            store.preview.dicts = (sk.dict_names || []).map((d: any) => ({
              name: d.name, code: d.code, options: []
            }))
            // 用骨架的 model_names 创建空模型占位
            store.preview.models = (sk.model_names || []).map((m: any) => ({
              name: m.name, code: m.code, fields: []
            }))
            store.currentApp = { name: store.preview.appName, status: 'draft' }
          }

          // 字典批次完成 → 更新对应字典的选项
          if (evt.phase === 'dicts' && evt.batch) {
            for (const newDict of evt.batch) {
              const existing = store.preview.dicts.find(
                (d: any) => d.code === newDict.code || d.name === newDict.name
              )
              if (existing) {
                existing.options = newDict.options || []
                if (newDict.code) existing.code = newDict.code
              } else {
                store.preview.dicts.push(newDict)
              }
            }
          }

          // 模型批次完成 → 更新对应模型的字段
          if (evt.phase === 'models' && evt.batch) {
            for (const newModel of evt.batch) {
              const existing = store.preview.models.find(
                (m: any) => m.code === newModel.code || m.name === newModel.name
              )
              if (existing) {
                existing.fields = newModel.fields || []
                if (newModel.code) existing.code = newModel.code
              } else {
                store.preview.models.push(newModel)
              }
            }
          }

          // 流程批次完成 → 更新 workflows
          if (evt.phase === 'workflows' && evt.batch) {
            for (const wf of evt.batch) {
              const existing = store.preview.workflows.find((w: any) => w.name === wf.name || w.form === wf.form)
              if (existing) Object.assign(existing, wf)
              else store.preview.workflows.push(wf)
            }
          }

          // 权限批次完成 → 更新 permissions
          if (evt.phase === 'permissions' && evt.batch) {
            if (!store.preview.permissions) store.preview.permissions = []
            for (const p of evt.batch) {
              const existing = store.preview.permissions.find((x: any) => x.form === p.form)
              if (existing) Object.assign(existing, p)
              else store.preview.permissions.push(p)
            }
          }

          // 完整配置 → 最终覆盖
          if (evt.phase === 'complete' && evt.data) {
            const d = evt.data
            store.preview.appName = d.appName || store.preview.appName
            store.preview.roles = d.roles || store.preview.roles
            store.preview.dicts = d.dicts || store.preview.dicts
            store.preview.models = d.models || store.preview.models
            store.preview.workflows = d.workflows || []
            store.preview.permissions = d.permissions || []
            store.currentApp = { name: store.preview.appName, status: 'draft' }
          }

          if (evt.type === 'done') break

        } catch (e) { /* ignore parse errors */ }
      }
    }

    // 添加完成消息到对话
    messages.push({
      id: Date.now(), role: 'assistant', agent: 'builder',
      content: `配置生成完成！${store.preview.models.length} 个模型、${store.preview.dicts.length} 个字典、${store.preview.roles.length} 个角色。\n\n可以直接编辑右侧预览，或点击 **开始生成** 部署到平台。`,
      created_at: ''
    })
    scrollToBottom()

  } catch (e: any) {
    ElMessage.error(`配置生成失败: ${e.message}`)
  } finally {
    assembling.value = false
    assembleMessage.value = ''
  }
}

const createConversation = async () => {
  const token = localStorage.getItem('token')
  const res = await fetch(`${API_PREFIX}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    body: JSON.stringify({ agent_type: currentAgent.value })
  })
  if (res.ok) {
    const data = await res.json()
    conversationId.value = data.id
    selectedConversationId.value = data.id
    // 更新 URL，刷新后能恢复对话
    router.replace(`/chat/${data.id}`)
    // 刷新对话列表
    fetchConversationList()
  }
}

const sendMessage = async () => {
  if (!inputText.value.trim()) return
  const text = inputText.value.trim()
  inputText.value = ''
  messages.push({ id: Date.now(), role: 'user', content: text, created_at: '' })
  scrollToBottom()
  isTyping.value = true

  // 如果还没有对话，先创建
  if (!conversationId.value) {
    await createConversation()
  }

  if (!conversationId.value) {
    isTyping.value = false
    messages.push({ id: Date.now(), role: 'assistant', agent: currentAgent.value, content: '创建对话失败，请重试。', created_at: '' })
    scrollToBottom()
    return
  }

  // 调用后端API
  try {
    const token = localStorage.getItem('token')
    const response = await fetch(`${API_PREFIX}/chat/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({
        conversation_id: conversationId.value,
        message: text,
        ...(store.preview.appName ? { current_config: { ...store.preview } } : {})
      })
    })

    if (!response.ok) throw new Error('发送失败')

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    let assistantContent = ''

    if (!reader) throw new Error('无法读取响应')

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      const chunk = decoder.decode(value, { stream: true })
      const lines = chunk.split('\n')

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const parsed = JSON.parse(line.slice(6))
            if (parsed.type === 'thinking') {
              // AI 正在思考，保持 isTyping 状态
            } else if (parsed.type === 'message') {
              isTyping.value = false
              assistantContent += parsed.data
              // 更新最后一条消息或创建新消息
              const lastMsg = messages[messages.length - 1]
              if (lastMsg && lastMsg.role === 'assistant' && lastMsg.agent === currentAgent.value && lastMsg.id === -1) {
                lastMsg.content = assistantContent
              } else {
                messages.push({ id: -1, role: 'assistant', agent: currentAgent.value, content: assistantContent, created_at: '' })
              }
              scrollToBottom()
            } else if (parsed.type === 'done') {
              isTyping.value = false
              // 标记完成，设置正式id
              const lastMsg = messages[messages.length - 1]
              if (lastMsg && lastMsg.id === -1) lastMsg.id = Date.now()
              // 提取配置JSON
              extractPreviewData(assistantContent)
              // 如果提到了应用名但还没设置currentApp
              if (!store.currentApp && assistantContent.length > 50) {
                const appNameMatch = assistantContent.match(/搭建.*?[**](.+?)[**]/)
                if (appNameMatch) {
                  store.currentApp = { name: appNameMatch[1] || '', status: 'talking' }
                }
              }
            }
          } catch (e) { /* ignore parse errors */ }
        }
      }
    }
  } catch (error) {
    console.error('Send error:', error)
    isTyping.value = false
    messages.push({ id: Date.now(), role: 'assistant', agent: currentAgent.value, content: '发送失败，请重试。', created_at: '' })
    scrollToBottom()
  }
}

const renderMarkdown = (t: string) => {
  if (!t) return '<p>（无内容）</p>'
  return marked.parse(t, { breaks: true, gfm: true }) as string
}

const formatContent = (t: string) => {
  // 隐藏JSON代码块，只显示文字部分
  let text = t.replace(/```json[\s\S]*?```/g, '')
  // 清理多余空行
  text = text.replace(/\n{3,}/g, '\n\n').trim()
  return text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>').replace(/• /g, '<span style="color:#818cf8;margin-right:4px">•</span> ')
}

onMounted(async () => {
  // 检查平台连接状态
  try {
    const token = localStorage.getItem('token')
    if (token) {
      const res = await fetch(`${API_PREFIX}/apaas/status`, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      if (res.ok) {
        const data = await res.json()
        store.connected = data.connected
      }
    }
  } catch (e) { /* ignore */ }

  // ── 优先通过 app_id 加载应用（应用为锚点）──
  const appIdParam = route.query.app_id as string
  if (appIdParam) {
    const aid = Number(appIdParam)
    if (aid) {
      existingAppId.value = aid
      try {
        const app = await applicationApi.get(aid) as any
        // 恢复配置
        if (app.config_preview) {
          const data = app.config_preview.data || app.config_preview
          store.preview.appName = data.appName || app.app_name || ''
          store.preview.models = data.models || []
          store.preview.dicts = data.dicts || []
          store.preview.roles = data.roles || []
          store.preview.workflows = data.workflows || []
          store.preview.permissions = data.permissions || []
          store.currentApp = { name: store.preview.appName, status: app.status || 'ready', apaas_app_id: app.apaas_app_id }
        }
        console.log(`Loaded app ${aid}: ${app.app_name}, status=${app.status}, conv=${app.conversation_id}`)
        // 加载关联对话的历史消息
        if (app.conversation_id) {
          conversationId.value = app.conversation_id
          selectedConversationId.value = app.conversation_id
          const historyMessages = await conversationApi.getMessages(app.conversation_id)
          if (historyMessages?.length) {
            messages.splice(0, messages.length)
            for (const msg of historyMessages) {
              if (msg.role === 'system') continue
              messages.push({ id: msg.id, role: msg.role as any, agent: msg.role === 'assistant' ? 'builder' : undefined, content: msg.content, created_at: msg.created_at })
            }
            scrollToBottom()
          }
        }
        console.log(`Loaded app ${aid}: ${app.app_name}`)
      } catch (e) {
        console.error('Failed to load application:', e)
      }
    }
  }
  // ── 兼容旧链接：通过 conversation_id 加载 ──
  else {
    const idParam = route.params.id as string
    if (idParam) {
      const cid = Number(idParam)
      if (!isNaN(cid)) {
        conversationId.value = cid
        try {
          // 加载历史消息
          const historyMessages = await conversationApi.getMessages(cid)
          if (historyMessages && historyMessages.length > 0) {
            messages.splice(0, messages.length)
            for (const msg of historyMessages) {
              if (msg.role === 'system') {
                extractPreviewData(msg.content)
                continue
              }
              messages.push({
                id: msg.id,
                role: msg.role as any,
                agent: msg.role === 'assistant' ? 'builder' : undefined,
                content: msg.content,
                created_at: msg.created_at
              })
              if (msg.role === 'assistant') {
                extractPreviewData(msg.content)
              }
            }
            scrollToBottom()
          }
          // 查找关联的应用
          if (!existingAppId.value) {
            try {
              const apps = await applicationApi.list() as any[]
              const linkedApp = apps.find((a: any) => a.conversation_id === cid && a.config_preview)
              if (linkedApp?.config_preview) {
                const data = linkedApp.config_preview.data || linkedApp.config_preview
                store.preview.appName = data.appName || ''
                store.preview.models = data.models || []
                store.preview.dicts = data.dicts || []
                store.preview.roles = data.roles || []
                store.preview.workflows = data.workflows || []
                store.preview.permissions = data.permissions || []
                store.currentApp = { name: store.preview.appName, status: 'draft' }
                existingAppId.value = linkedApp.id
                // 更新 URL 为 app_id 模式
                router.replace({ path: '/chat', query: { app_id: String(linkedApp.id) } })
                console.log('Migrated to app-centric URL:', linkedApp.id)
              }
            } catch (e2) {
              console.warn('Failed to recover config from app:', e2)
            }
          }
        } catch (e) {
          console.error('Failed to load conversation history:', e)
        }
      }
    }
  }

  // 从 /generate/:id 重定向过来，自动打开部署面板
  const deployParam = route.query.deploy_app_id as string
  if (deployParam) {
    const aid = Number(deployParam)
    if (aid) {
      deployAppId.value = aid
      existingAppId.value = aid
      deployOpen.value = true
      loadDeployStatus()
      // 加载应用信息到预览
      try {
        const app = await applicationApi.get(aid) as any
        if (app.config_preview) {
          const data = app.config_preview.data || app.config_preview
          store.preview.appName = data.appName || app.app_name || ''
          store.preview.models = data.models || []
          store.preview.dicts = data.dicts || []
          store.preview.roles = data.roles || []
          store.currentApp = { name: store.preview.appName, status: app.status || 'ready' }
        }
        // 加载关联的对话
        if (app.conversation_id) {
          conversationId.value = app.conversation_id
          const historyMessages = await conversationApi.getMessages(app.conversation_id)
          if (historyMessages?.length) {
            messages.splice(0, messages.length)
            for (const msg of historyMessages) {
              if (msg.role === 'system') continue
              messages.push({ id: msg.id, role: msg.role as any, agent: msg.role === 'assistant' ? 'builder' : undefined, content: msg.content, created_at: msg.created_at })
            }
          }
        }
      } catch { /* ignore */ }
    }
  }

  const prompt = route.query.prompt as string
  if (prompt) {
    inputText.value = prompt
    nextTick(() => sendMessage())
  }

  // 从 Landing 页带过来的待解析文件
  if (store.pendingFile) {
    const file = store.pendingFile
    store.pendingFile = null
    resetConversationWorkspace()
    messages.splice(0, messages.length)
    nextTick(() => {
      const dt = new DataTransfer()
      dt.items.add(file)
      const fakeInput = document.createElement('input')
      fakeInput.type = 'file'
      fakeInput.files = dt.files
      handleDocUpload({ target: fakeInput } as any)
    })
  }

  // 同步对话历史选中
  if (conversationId.value) {
    selectedConversationId.value = conversationId.value
  }

  // 加载对话历史列表
  fetchConversationList()

  // 加载应用计数
  fetchAppCount()
})

// 切换到文档 tab 时自动加载版本列表
watch(() => store.previewTab, (tab) => {
  if (tab === 'workflow') {
    store.previewTab = 'overview'
    return
  }
  if (tab === 'docs' && (existingAppId.value || conversationId.value) && docVersions.value.length === 0) {
    fetchDocVersions()
  }
})
watch(existingAppId, (id) => {
  if (id && store.previewTab === 'docs') {
    fetchDocVersions()
  }
})
watch(conversationId, (id) => {
  if (id && store.previewTab === 'docs' && !existingAppId.value) {
    fetchDocVersions()
  }
})
</script>

<style scoped>
/* ══════════════════════════════════════════════
   Theme — uses CSS custom properties (var(--t-*))
   for light/dark theme support.
   See theme definition for variable values.
   ══════════════════════════════════════════════ */

.chat-page { height: 100vh; display: flex; flex-direction: column; background: var(--t-bg-base); color: var(--t-text-primary); }

/* ── 导航栏 ── */
.nav-bar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 16px; flex-shrink: 0;
  background: rgba(17,17,17,0.75);
  backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--t-border-subtle);
}
.nav-left, .nav-right { display: flex; align-items: center; gap: 10px; }
.back-btn { background: none; border: none; color: var(--t-text-muted); cursor: pointer; padding: 4px; transition: color 0.2s; }
.back-btn:hover { color: var(--t-text-primary); }
.logo-box {
  width: 28px; height: 28px;
  background: var(--t-brand-gradient);
  border-radius: 8px; display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 700; font-size: 12px;
}
.logo-text { font-size: 14px; font-weight: 600; color: var(--t-text-primary); }
.nav-link {
  font-size: 12px; color: var(--t-text-secondary); background: none; border: none;
  cursor: pointer; padding: 6px 12px; border-radius: 8px; transition: all 0.2s;
}
.nav-link:hover { background: var(--t-bg-subtle); color: var(--t-text-primary); transform: translateY(-1px); }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--t-border-strong); }
.dot.active { background: var(--t-success); }

.main-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; position: relative; }

/* ── 搭建智能体内容区（横向布局） ── */
.builder-content { flex: 1; display: flex; overflow: hidden; min-height: 0; }

/* ── 左侧对话 ── */
.chat-side { flex: 1; display: flex; flex-direction: column; min-width: 0; min-width: 320px; }

/* Agent tabs */
.agent-tabs {
  display: flex; gap: 4px; padding: 8px 16px; flex-shrink: 0;
  background: var(--t-bg-base); border-bottom: 1px solid var(--t-border-subtle);
}
.agent-tab {
  display: flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 8px;
  font-size: 12px; font-weight: 500; background: none; border: none;
  color: var(--t-text-muted); cursor: pointer; transition: all 0.2s;
  position: relative;
}
.agent-tab:hover { background: var(--t-bg-subtle); color: var(--t-text-primary); }
.agent-tab.active {
  background: var(--t-brand-subtle); color: var(--t-brand-light);
}
.agent-tab.active::after {
  content: ''; position: absolute; bottom: -8px; left: 12px; right: 12px; height: 2px;
  background: var(--t-brand-gradient); border-radius: 1px;
}
.active-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--t-success); }
.agent-tab-action {
  margin-left: auto; padding: 4px 8px; border-radius: 6px;
  font-size: 14px; background: none; border: none;
  color: var(--t-text-muted); cursor: pointer; transition: all 0.2s;
}
.agent-tab-action:hover { background: var(--t-border-subtle); color: var(--t-text-primary); }

/* 消息区 */
/* ── 对话历史栏 ── */
.conversation-history-bar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 4px 16px; flex-shrink: 0;
  background: transparent; border-bottom: 1px solid var(--t-border-subtle);
}
.conv-history-left {
  display: flex; align-items: center; gap: 10px;
}
.conv-history-label {
  font-size: 11px; color: var(--t-text-muted); white-space: nowrap; font-weight: 400;
}
.conv-history-select {
  width: 300px;
}
.conv-history-select :deep(.el-select__wrapper),
.conv-history-select :deep(.el-input__wrapper),
.conv-history-select :deep(.el-select__wrapper.is-focused),
.conv-history-select :deep(.el-select__wrapper.is-hovering) {
  background: transparent !important; border: 1px solid var(--t-border-subtle) !important;
  box-shadow: none !important; border-radius: 8px !important; height: 28px;
}
.conv-history-select :deep(.el-select__wrapper.is-hovering) {
  border-color: var(--t-border-strong) !important;
}
.conv-history-select :deep(.el-select__wrapper.is-focused) {
  border-color: var(--t-brand-glow) !important;
}
.conv-history-select :deep(.el-select__selection) {
  color: var(--t-text-primary) !important;
}
.conv-history-select :deep(.el-select__placeholder),
.conv-history-select :deep(.el-select__placeholder.is-transparent) {
  color: var(--t-text-muted) !important;
}
.conv-history-select :deep(.el-select__caret),
.conv-history-select :deep(.el-select__suffix) {
  color: var(--t-text-muted) !important;
}
.conv-history-select :deep(.el-select__selected-item .el-tag) {
  background: transparent !important; border: none !important; color: var(--t-text-primary) !important;
}
.conv-history-select :deep(.el-input__wrapper:hover) {
  border-color: var(--t-border-strong) !important;
}
.conv-history-select :deep(.el-input__wrapper.is-focus),
.conv-history-select :deep(.el-input.is-focus .el-input__wrapper) {
  border-color: var(--t-brand-glow) !important; box-shadow: none !important;
}
.conv-history-select :deep(.el-select__tags),
.conv-history-select :deep(.el-tag) {
  background: transparent !important;
}
.conv-history-select :deep(.el-tag .el-tag__content) {
  color: var(--t-text-primary) !important;
}
.conv-history-select :deep(.el-select__input) {
  background: transparent !important; color: var(--t-text-primary) !important;
}
.conv-history-select :deep(.el-select__placeholder) {
  color: var(--t-text-muted) !important;
}
.conv-history-select :deep(.el-select__selected-item) {
  color: var(--t-text-primary) !important;
}
.conv-history-select :deep(.el-input__inner) {
  color: var(--t-text-primary) !important; font-size: 12px !important;
}
.conv-history-select :deep(.el-input__suffix) {
  color: var(--t-text-muted) !important;
}
.conv-history-select :deep(.el-select-dropdown) {
  background: var(--t-bg-panel) !important; border: 1px solid var(--t-border-subtle) !important;
  border-radius: 10px !important;
}
.conv-history-select :deep(.el-select-dropdown__item) {
  color: var(--t-text-secondary) !important; font-size: 12px !important;
  padding: 6px 12px !important;
}
.conv-history-select :deep(.el-select-dropdown__item.is-selected) {
  color: var(--t-brand-light) !important; font-weight: 600;
}
.conv-history-select :deep(.el-select-dropdown__item:hover),
.conv-history-select :deep(.el-select-dropdown__item.hover) {
  background: var(--t-brand-subtle) !important;
}
.conv-history-select :deep(.el-popper.is-light) {
  background: var(--t-bg-panel) !important; border: 1px solid var(--t-border-subtle) !important;
}
.conv-history-select :deep(.el-popper.is-light .el-popper__arrow::before) {
  background: var(--t-bg-panel) !important; border-color: var(--t-border-subtle) !important;
}
.conv-option-row {
  display: flex; justify-content: space-between; align-items: center; width: 100%; gap: 12px;
}
.conv-option-title {
  flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.conv-option-time {
  flex-shrink: 0; font-size: 11px; color: var(--t-text-muted);
}
.conv-new-btn {
  all: unset; cursor: pointer; font-size: 11px; font-weight: 400;
  color: var(--t-text-muted); padding: 3px 10px; border-radius: 6px;
  border: 1px solid var(--t-border-subtle); transition: all 0.2s;
  white-space: nowrap;
}
.conv-new-btn:hover {
  color: var(--t-brand-light); background: var(--t-brand-subtle); border-color: rgba(167,139,250,0.2);
}

.messages { flex: 1; overflow-y: auto; padding: 16px; background: var(--t-bg-base); }
.chat-bubble { margin-bottom: 16px; animation: fadeUp 0.3s ease-out; }
.chat-bubble.user { display: flex; justify-content: flex-end; }
.chat-bubble.assistant { display: flex; justify-content: flex-start; }
.bubble-inner { max-width: 80%; }
.agent-label { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--t-text-muted); margin-bottom: 4px; }
.bubble-content { padding: 10px 14px; border-radius: 14px; font-size: 13px; line-height: 1.6; }
.bubble-content.user {
  background: var(--t-brand-gradient);
  color: #fff; border-bottom-right-radius: 4px;
}
.bubble-content.assistant {
  background: var(--t-bg-elevated); border: 1px solid var(--t-border-subtle);
  color: var(--t-text-primary); border-bottom-left-radius: 4px;
}
@keyframes fadeUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

.typing-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--t-text-muted); display: inline-block; animation: pulseDot 1.4s infinite ease-in-out both; margin-right: 3px; }
.typing-dot:nth-child(1) { animation-delay: -0.32s; }
.typing-dot:nth-child(2) { animation-delay: -0.16s; }
@keyframes pulseDot { 0%,80%,100% { transform: scale(0); } 40% { transform: scale(1); } }

/* 底部输入框 */
.input-bar { padding: 12px 16px; background: var(--t-bg-base); border-top: 1px solid var(--t-border-subtle); flex-shrink: 0; }
.input-wrap {
  display: flex; align-items: center; gap: 8px;
  background: var(--t-bg-elevated); border-radius: 12px; padding: 8px 8px 8px 12px;
  border: 1px solid var(--t-border-subtle); transition: border-color 0.3s, box-shadow 0.3s;
}
.input-wrap:focus-within {
  border-color: var(--t-brand);
  box-shadow: 0 0 0 3px var(--t-brand-subtle), inset 0 0 0 1px var(--t-brand-glow);
}
.upload-btn { cursor: pointer; font-size: 18px; padding: 2px 4px; border-radius: 6px; opacity: 0.5; transition: opacity 0.2s; }
.upload-btn:hover { opacity: 1; background: var(--t-bg-subtle); }
.input-wrap input { flex: 1; background: transparent; border: none; outline: none; font-size: 13px; color: var(--t-text-primary); }
.input-wrap input::placeholder { color: var(--t-text-muted); }
.send-btn {
  width: 32px; height: 32px; border-radius: 8px;
  background: var(--t-brand-gradient);
  color: #fff; border: none; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: transform 0.2s, box-shadow 0.2s;
}
.send-btn.disabled { opacity: 0.3; cursor: not-allowed; }
.send-btn:hover:not(.disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px var(--t-brand-glow); }

/* ── 右侧预览面板 ── */
.preview-side {
  flex: 1; background: var(--t-bg-base); border-left: 1px solid var(--t-border-subtle);
  display: flex; flex-direction: column; min-width: 0; position: relative;
}
.preview-tabs { display: flex; border-bottom: 1px solid var(--t-border-subtle); padding: 0 8px; flex-shrink: 0; }
.ptab {
  padding: 10px 12px; font-size: 12px; font-weight: 500; border: none; background: none;
  color: var(--t-text-muted); cursor: pointer; border-bottom: 2px solid transparent;
  transition: color 0.2s;
}
.ptab:hover { color: var(--t-text-secondary); }
.ptab.active {
  color: var(--t-brand-light);
  border-image: var(--t-brand-gradient) 1;
  border-bottom-width: 2px; border-bottom-style: solid;
}
.preview-empty { padding: 24px; text-align: center; color: var(--t-text-muted); font-size: 13px; margin-top: 80px; }
.preview-empty .empty-icon { font-size: 40px; opacity: 0.3; margin-bottom: 12px; }
.preview-empty.small { margin-top: 0; padding: 32px; }
.preview-body { flex: 1; overflow-y: auto; }
.tab-content { padding: 16px; }

/* ── 文档版本 ── */
.doc-versions-tab { display: flex; flex-direction: column; gap: 12px; }
.doc-upload-bar { display: flex; align-items: center; justify-content: space-between; }
.doc-tab-title { font-size: 14px; font-weight: 600; color: var(--t-text-primary); }
.doc-upload-btn {
  padding: 6px 14px; font-size: 12px; font-weight: 500; border: none; border-radius: 8px;
  background: var(--t-brand-gradient); color: #fff; cursor: pointer;
  transition: opacity 0.2s;
}
.doc-upload-btn:hover { opacity: 0.85; }
.doc-version-list { display: flex; flex-direction: column; gap: 10px; }
.doc-version-card {
  border: 1px solid var(--t-border-subtle); border-radius: 12px; padding: 12px 14px;
  background: var(--t-bg-elevated); transition: border-color 0.2s;
}
.doc-version-card:hover { border-color: var(--t-brand-glow); }
.doc-ver-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.doc-ver-num {
  font-size: 13px; font-weight: 700;
  background: var(--t-brand-gradient);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.doc-ver-filename { font-size: 13px; color: var(--t-text-primary); font-weight: 500; }
.doc-ver-meta { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.doc-ver-time { font-size: 11px; color: var(--t-text-muted); }
.doc-ver-summary { font-size: 11px; color: var(--t-text-secondary); }
.doc-ver-actions { display: flex; gap: 8px; }
.doc-action-btn {
  padding: 4px 10px; font-size: 11px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--t-border-subtle); background: var(--t-border-subtle);
  color: var(--t-text-secondary); transition: all 0.2s;
}
.doc-action-btn:hover { background: var(--t-border-subtle); color: #fff; }
.doc-action-btn.diff { border-color: var(--t-brand-glow); color: var(--t-brand-light); }
.doc-action-btn.diff:hover { background: var(--t-brand-subtle); }

/* 文档预览弹窗 */
:deep(.doc-preview-dialog) .el-dialog { background: var(--t-bg-panel); color: var(--t-text-primary); }
:deep(.doc-preview-dialog) .el-dialog__header { border-bottom: 1px solid var(--t-border-subtle); }
:deep(.doc-preview-dialog) .el-dialog__title { color: var(--t-text-primary); }
:deep(.doc-preview-dialog) .el-dialog__headerbtn .el-dialog__close { color: var(--t-text-secondary); }
.doc-preview-body {
  max-height: 70vh; overflow-y: auto; padding: 16px;
  font-size: 13px; line-height: 1.7; color: var(--t-text-primary);
  background: var(--t-bg-base); border-radius: 8px;
}
.doc-preview-body :deep(h1) { font-size: 20px; color: #fff; margin: 20px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--t-border-subtle); }
.doc-preview-body :deep(h2) { font-size: 17px; color: var(--t-text-primary); margin: 18px 0 10px; }
.doc-preview-body :deep(h3) { font-size: 15px; color: var(--t-text-primary); margin: 14px 0 8px; }
.doc-preview-body :deep(h4) { font-size: 13px; color: var(--t-text-primary); margin: 10px 0 6px; }
.doc-preview-body :deep(p) { margin: 6px 0; }
.doc-preview-body :deep(ul), .doc-preview-body :deep(ol) { padding-left: 20px; margin: 6px 0; }
.doc-preview-body :deep(li) { margin: 3px 0; }
.doc-preview-body :deep(code) { background: var(--t-border-subtle); padding: 2px 6px; border-radius: 4px; font-size: 12px; }
.doc-preview-body :deep(pre) { background: var(--t-border-subtle); padding: 12px; border-radius: 8px; overflow-x: auto; }
.doc-preview-body :deep(table) { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 12px; }
.doc-preview-body :deep(th) { background: var(--t-brand-subtle); color: var(--t-brand-light); text-align: left; padding: 8px 12px; border: 1px solid var(--t-border-subtle); font-weight: 600; }
.doc-preview-body :deep(td) { padding: 6px 12px; border: 1px solid var(--t-border-subtle); }
.doc-preview-body :deep(tr:hover td) { background: var(--t-bg-subtle); }
.doc-preview-body :deep(strong) { color: var(--t-brand-light); }
.doc-preview-body :deep(hr) { border: none; border-top: 1px solid var(--t-border-subtle); margin: 16px 0; }

/* 文档对比弹窗 */
:deep(.doc-diff-dialog) .el-dialog { background: var(--t-bg-panel); color: var(--t-text-primary); }
:deep(.doc-diff-dialog) .el-dialog__header { border-bottom: 1px solid var(--t-border-subtle); }
:deep(.doc-diff-dialog) .el-dialog__title { color: var(--t-text-primary); }
:deep(.doc-diff-dialog) .el-dialog__headerbtn .el-dialog__close { color: var(--t-text-secondary); }
.diff-summary-bar {
  display: flex; gap: 16px; padding: 10px 14px; margin-bottom: 12px;
  background: var(--t-border-subtle); border-radius: 10px; border: 1px solid var(--t-border-subtle);
}
.diff-stat { font-size: 13px; font-weight: 500; }
.diff-stat.added { color: var(--t-success); }
.diff-stat.removed { color: var(--t-danger); }
.diff-stat.unchanged { color: var(--t-text-muted); }
.doc-diff-container { display: flex; gap: 8px; max-height: 70vh; }

/* 变更摘要面板 */
.diff-changes-panel {
  width: 240px; flex-shrink: 0; display: flex; flex-direction: column;
  background: var(--t-border-subtle); border: 1px solid var(--t-border-subtle);
  border-radius: 10px; overflow: hidden;
}
.dcp-title {
  font-size: 12px; font-weight: 600; color: var(--t-text-secondary);
  padding: 10px 12px; border-bottom: 1px solid var(--t-border-subtle);
  background: var(--t-bg-subtle);
}
.dcp-list { flex: 1; overflow-y: auto; padding: 8px; }
.dcp-item {
  display: flex; align-items: flex-start; gap: 6px; padding: 5px 6px;
  font-size: 11px; line-height: 1.4; border-radius: 6px; margin-bottom: 2px;
}
.dcp-item.added { color: var(--t-success); background: rgba(52,211,153,0.06); }
.dcp-item.removed { color: var(--t-danger); background: rgba(248,113,113,0.06); }
.dcp-item.modified { color: var(--t-warning); background: rgba(251,191,36,0.06); }
.dcp-icon { font-weight: 700; flex-shrink: 0; width: 14px; text-align: center; }
.dcp-text { word-break: break-all; }
.dcp-empty { text-align: center; color: var(--t-text-muted); font-size: 11px; padding: 20px 0; }
.doc-diff-pane { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.doc-diff-pane-title {
  font-size: 12px; font-weight: 600; padding: 8px 12px;
  background: var(--t-border-subtle); border-radius: 8px 8px 0 0;
  color: var(--t-text-secondary); border: 1px solid var(--t-border-subtle);
  border-bottom: none;
}
.doc-diff-content {
  flex: 1; overflow-y: auto; background: var(--t-bg-base); border-radius: 0 0 8px 8px;
  border: 1px solid var(--t-border-subtle); font-size: 12px; font-family: 'Menlo', 'Monaco', monospace;
}
.doc-diff-line { display: flex; min-height: 20px; line-height: 20px; }
.doc-diff-lineno {
  width: 36px; text-align: right; padding-right: 8px; flex-shrink: 0;
  color: var(--t-text-muted); user-select: none;
}
.doc-diff-text { flex: 1; padding: 0 8px; white-space: pre-wrap; word-break: break-all; color: var(--t-text-secondary); }
.doc-diff-line.removed { background: rgba(239,68,68,0.12); }
.doc-diff-line.removed .doc-diff-text { color: #fca5a5; }
.doc-diff-line.added { background: rgba(34,197,94,0.12); }
.doc-diff-line.added .doc-diff-text { color: #86efac; }

/* ── 概览 ── */
.overview-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.overview-header h4 { font-size: 14px; font-weight: 600; color: var(--t-text-primary); margin: 0; }
.status-tag { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.status-tag.ready { background: rgba(16,185,129,0.15); color: var(--t-success); }
.status-tag.deployed { background: rgba(96,165,250,0.15); color: var(--t-info); }
.deployed-banner {
  display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; border-radius: 12px; font-size: 13px; font-weight: 500; margin-top: 8px;
  background: rgba(96,165,250,0.1); color: var(--t-info); border: 1px solid rgba(96,165,250,0.15);
}
.view-deploy-btn {
  background: none; border: 1px solid rgba(96,165,250,0.3); color: var(--t-info); cursor: pointer;
  font-size: 11px; padding: 3px 10px; border-radius: 6px; transition: all 0.2s;
}
.view-deploy-btn:hover { background: rgba(96,165,250,0.15); }
.deployed-link { background: none; border: none; color: var(--t-brand-light); cursor: pointer; font-size: 12px; text-decoration: underline; margin-left: 8px; }
.status-tag.talking { background: var(--t-brand-subtle); color: var(--t-brand-light); }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(80px, 1fr)); gap: 8px; margin-bottom: 16px; }
.stat-card { border-radius: 12px; padding: 12px; text-align: center; border: 1px solid var(--t-border-subtle); }
.stat-card.indigo { background: var(--t-brand-subtle); }
.stat-card.emerald { background: rgba(16,185,129,0.1); }
.stat-card.amber { background: rgba(245,158,11,0.1); }
.stat-card.teal { background: rgba(20,184,166,0.1); }
.stat-card.purple { background: var(--t-brand-subtle); }
.stat-num { font-size: 20px; font-weight: 700; }
.stat-card.indigo .stat-num { color: var(--t-brand-light); }
.stat-card.teal .stat-num { color: #2dd4bf; }
.stat-card.emerald .stat-num { color: var(--t-success); }
.stat-card.amber .stat-num { color: var(--t-warning); }
.stat-card.purple .stat-num { color: var(--t-brand-light); }
.stat-label { font-size: 11px; color: var(--t-text-muted); }
.sub-section { margin-bottom: 16px; }
.sub-title { font-size: 12px; font-weight: 500; color: var(--t-text-secondary); margin-bottom: 8px; }
.tag-list { display: flex; flex-wrap: wrap; gap: 6px; }
.tag { font-size: 12px; background: var(--t-border-subtle); color: var(--t-text-secondary); padding: 4px 10px; border-radius: 6px; }
.dict-list { display: flex; flex-direction: column; gap: 6px; }
.dict-row { display: flex; align-items: center; gap: 6px; font-size: 12px; padding: 4px 8px; background: var(--t-border-subtle); border-radius: 6px; }
.dict-name { color: var(--t-text-primary); white-space: nowrap; }
.dict-opts { flex: 1; color: var(--t-text-muted); }
.dict-opts.empty { color: var(--t-danger); }
.edit-mini, .del-mini { background: none; border: none; cursor: pointer; font-size: 11px; padding: 2px; opacity: 0.3; transition: opacity 0.2s; flex-shrink: 0; color: var(--t-text-secondary); }
.dict-row:hover .edit-mini, .dict-row:hover .del-mini { opacity: 1; }
.add-mini { background: none; border: 1px dashed var(--t-border-strong); color: var(--t-text-muted); font-size: 11px; padding: 0 6px; border-radius: 4px; cursor: pointer; margin-left: 8px; transition: all 0.2s; }
.add-mini:hover { border-color: var(--t-brand); color: var(--t-brand-light); }
.tag.editable { cursor: pointer; transition: all 0.2s; }
.tag.editable:hover { background: rgba(239,68,68,0.15); color: var(--t-danger); }
.tag.empty { background: var(--t-bg-subtle); color: var(--t-text-muted); font-style: italic; }
.assemble-btn {
  width: 100%; padding: 10px; border: none; border-radius: 12px;
  font-size: 13px; font-weight: 500; cursor: pointer; margin-top: 8px;
  background: rgba(245,158,11,0.15); color: var(--t-warning);
  border: 1px solid rgba(245,158,11,0.2); transition: all 0.2s;
}
.assemble-btn:hover { background: rgba(245,158,11,0.25); transform: translateY(-1px); }
.assemble-progress {
  display: flex; align-items: center; gap: 8px; padding: 10px 12px;
  background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.15);
  border-radius: 12px; font-size: 12px; color: var(--t-warning); margin-top: 8px;
}
.assemble-spinner { animation: spin 1s linear infinite; display: inline-block; font-size: 16px; }
.gen-btn {
  width: 100%; padding: 10px;
  background: var(--t-brand-gradient);
  color: #fff; border: none; border-radius: 12px; font-size: 13px; font-weight: 500;
  cursor: pointer; margin-top: 8px; transition: transform 0.2s, box-shadow 0.2s;
}
.gen-btn:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 16px var(--t-brand-glow); }
.gen-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ── 模型 ── */
.model-card { border: 1px solid var(--t-border-subtle); border-radius: 12px; overflow: hidden; margin-bottom: 12px; background: var(--t-bg-panel); }
.model-header { display: flex; align-items: center; gap: 8px; padding: 10px 12px; background: var(--t-bg-subtle); font-size: 12px; }
.model-name { font-weight: 600; color: var(--t-text-primary); }
.model-code { margin-left: auto; font-size: 10px; color: var(--t-text-muted); font-family: monospace; }
.field-list { }
.field-row { display: flex; justify-content: space-between; align-items: center; padding: 0 12px; height: 44px; min-height: 44px; border-top: 1px solid var(--t-border-subtle); transition: background 0.15s; }
.field-row:hover { background: var(--t-bg-subtle); }
.field-left { display: flex; align-items: center; gap: 8px; min-width: 0; flex: 1; }
.field-icon { width: 24px; min-width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; font-size: 12px; background: var(--t-border-subtle); border-radius: 6px; color: var(--t-text-muted); flex-shrink: 0; }
.field-name { font-size: 13px; color: var(--t-text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.req { color: var(--t-danger); font-size: 10px; margin-left: 2px; flex-shrink: 0; }
.field-right { display: flex; align-items: center; gap: 6px; flex-shrink: 0; margin-left: 12px; }
.ftag { font-size: 10px; padding: 2px 8px; border-radius: 4px; white-space: nowrap; line-height: 1.4; }
.ftag.dict { background: rgba(245,158,11,0.12); color: var(--t-warning); }
.ftag.ref { background: rgba(96,165,250,0.12); color: var(--t-info); }
.ftype { font-size: 11px; color: var(--t-text-muted); white-space: nowrap; }

/* 模型选择 */
.model-select-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; padding: 8px 12px; background: var(--t-border-subtle); border-radius: 8px; }
.model-select-all { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--t-text-primary); cursor: pointer; }
.model-select-all input { accent-color: var(--t-brand); }
.model-select-tip { font-size: 11px; color: var(--t-text-muted); }
.model-checkbox { display: flex; align-items: center; cursor: pointer; }
.model-checkbox input { accent-color: var(--t-brand); width: 14px; height: 14px; }
.model-card.model-deselected { opacity: 0.35; }
.model-card.model-deselected:hover { opacity: 0.6; }

/* ── 表单 ── */
.form-selector { display: flex; gap: 4px; margin-bottom: 12px; overflow-x: auto; padding-bottom: 4px; }
.form-tab { font-size: 12px; padding: 4px 10px; border-radius: 8px; border: none; background: none; color: var(--t-text-muted); cursor: pointer; white-space: nowrap; transition: all 0.2s; }
.form-tab.active { background: var(--t-brand-subtle); color: var(--t-brand-light); font-weight: 500; }
.form-preview { border: 1px solid var(--t-border-subtle); border-radius: 12px; overflow: hidden; background: var(--t-bg-elevated); }
.form-title { background: var(--t-brand-subtle); padding: 8px 16px; font-size: 12px; font-weight: 600; color: var(--t-brand-light); border-bottom: 1px solid var(--t-brand-subtle); }
.form-fields-grid { padding: 16px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.form-field { min-width: 0; }
.form-field.full-width { grid-column: 1 / -1; }
.form-label { font-size: 12px; color: var(--t-text-secondary); margin-bottom: 4px; }
.form-mock { border: 1px solid var(--t-border-subtle); border-radius: 8px; padding: 6px 10px; font-size: 12px; color: var(--t-text-muted); background: var(--t-border-subtle); display: flex; justify-content: space-between; }
.form-mock.tall { min-height: 56px; }
.mock-auto { font-style: italic; color: var(--t-text-muted); }
.mock-arrow { color: var(--t-text-muted); }
.mock-link { color: var(--t-info); }
.mock-switch { color: var(--t-text-muted); font-size: 10px; letter-spacing: -1px; }

/* ── 子表 ── */
.subtable-wrapper { border: 1px solid var(--t-border-subtle); border-radius: 8px; overflow: hidden; }
.subtable { width: 100%; border-collapse: collapse; font-size: 12px; }
.subtable thead { background: var(--t-bg-subtle); }
.subtable th { padding: 6px 10px; text-align: left; font-weight: 500; color: var(--t-text-secondary); border-bottom: 1px solid var(--t-border-subtle); white-space: nowrap; }
.subtable td { padding: 6px 10px; border-bottom: 1px solid var(--t-border-subtle); color: var(--t-text-secondary); }
.subtable-idx { width: 32px; text-align: center; color: var(--t-text-muted); }
.subtable-op { width: 48px; text-align: center; }
.subtable-del { color: var(--t-danger); cursor: pointer; font-size: 11px; }
.subtable-placeholder { color: var(--t-text-muted); display: flex; justify-content: space-between; align-items: center; }
.subtable-data-selector { display: flex; justify-content: space-between; align-items: center; }
.subtable-add { padding: 8px; text-align: center; font-size: 12px; color: var(--t-brand-light); cursor: pointer; border-top: 1px dashed var(--t-border-subtle); transition: background 0.2s; }
.subtable-add:hover { background: var(--t-bg-subtle); }

/* ── 流程 ── */
.wf-card { border: 1px solid var(--t-border-subtle); border-radius: 12px; overflow: hidden; margin-bottom: 12px; background: var(--t-bg-elevated); }
.wf-header { display: flex; justify-content: space-between; padding: 8px 12px; background: var(--t-bg-subtle); }
.wf-name { font-size: 12px; font-weight: 600; color: var(--t-text-primary); }
.wf-form { font-size: 10px; color: var(--t-text-muted); }
.wf-nodes { display: flex; flex-direction: column; align-items: center; padding: 16px; gap: 4px; }
.wf-node { padding: 8px 16px; border-radius: 8px; font-size: 12px; font-weight: 500; text-align: center; min-width: 120px; }
.wf-node.start { background: rgba(16,185,129,0.12); color: var(--t-success); border-radius: 20px; }
.wf-node.approve { background: var(--t-brand-subtle); color: var(--t-brand-light); }
.wf-node.end { background: var(--t-border-subtle); color: var(--t-text-muted); border-radius: 20px; }
.wf-role { font-size: 10px; opacity: 0.7; margin-top: 2px; }
.wf-arrow { color: var(--t-text-muted); font-size: 12px; }

/* ── 权限 ── */
.perm-card { border: 1px solid var(--t-border-subtle); border-radius: 12px; overflow: hidden; margin-bottom: 12px; background: var(--t-bg-elevated); }
.perm-header { padding: 8px 12px; background: var(--t-bg-subtle); font-size: 12px; font-weight: 600; color: var(--t-text-primary); }
.perm-table { width: 100%; border-collapse: collapse; }
.perm-table th { font-size: 10px; color: var(--t-text-muted); font-weight: 500; text-align: left; padding: 6px 12px; border-bottom: 1px solid var(--t-border-subtle); }
.perm-table td { font-size: 12px; color: var(--t-text-secondary); padding: 6px 12px; border-bottom: 1px solid var(--t-border-subtle); }
.data-tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; }
.data-tag.all { background: rgba(239,68,68,0.12); color: var(--t-danger); }
.data-tag.dept { background: rgba(245,158,11,0.12); color: var(--t-warning); }
.data-tag.self { background: rgba(96,165,250,0.12); color: var(--t-info); }

.connect-warn { padding: 16px; }
.connect-warn > div { background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.15); border-radius: 12px; padding: 12px; font-size: 12px; }
.warn-title { color: var(--t-warning); font-weight: 500; margin-bottom: 4px; }
.connect-warn p { color: rgba(245,158,11,0.7); margin: 0 0 8px; }
.warn-link { color: var(--t-warning); text-decoration: underline; background: none; border: none; cursor: pointer; font-size: 12px; }

/* ── 部署面板（第三栏） ── */
.deploy-side {
  width: 0; min-width: 0; overflow: hidden;
  background: var(--t-bg-base); border-left: 1px solid var(--t-border-subtle);
  display: flex; flex-direction: column; transition: width 0.3s ease, min-width 0.3s ease;
}
.deploy-side.open { width: 340px; min-width: 340px; }
@media (max-width: 1200px) {
  .deploy-side.open { position: absolute; right: 0; top: 0; bottom: 0; z-index: 20; width: 360px; min-width: 360px; box-shadow: -4px 0 24px rgba(0,0,0,0.4); }
}

.deploy-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 16px 8px; }
.deploy-title { font-size: 14px; font-weight: 700; color: var(--t-text-primary); }
.deploy-desc { font-size: 11px; color: var(--t-text-muted); margin-top: 2px; }
.deploy-close { all: unset; cursor: pointer; color: var(--t-text-muted); font-size: 16px; padding: 4px; transition: color 0.2s; }
.deploy-close:hover { color: var(--t-text-secondary); }

.deploy-progress { padding: 0 16px 8px; display: flex; align-items: center; gap: 8px; }
.dp-track { flex: 1; height: 3px; background: var(--t-border-subtle); border-radius: 2px; overflow: hidden; }
.dp-fill { height: 100%; background: var(--t-brand-gradient); border-radius: 2px; transition: width 0.5s; }
.dp-meta { font-size: 10px; color: var(--t-text-muted); white-space: nowrap; }

.deploy-actions { padding: 0 16px 12px; }
.dp-run-all {
  width: 100%; padding: 8px;
  background: var(--t-brand-gradient);
  color: #fff; border: none; border-radius: 8px; font-size: 12px; cursor: pointer; font-weight: 500;
  transition: transform 0.2s, box-shadow 0.2s;
}
.dp-run-all:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px var(--t-brand-glow); }
.dp-run-all:disabled { opacity: 0.35; cursor: not-allowed; background: var(--t-border-subtle); }

.deploy-groups { flex: 1; overflow-y: auto; padding: 0 12px 12px; }
.dg { background: var(--t-bg-elevated); border: 1px solid var(--t-border-subtle); border-radius: 12px; margin-bottom: 8px; overflow: hidden; }
.dg.done { border-color: rgba(16,185,129,0.25); }
.dg.err { border-color: rgba(239,68,68,0.25); }
.dg-hd { display: flex; align-items: center; gap: 6px; padding: 10px 14px; background: var(--t-bg-subtle); font-size: 12px; }
.dg-icon { font-size: 13px; }
.dg-name { font-weight: 600; color: var(--t-text-primary); flex: 1; }
.dg-badge { font-size: 9px; padding: 1px 6px; border-radius: 99px; font-weight: 600; background: var(--t-border-subtle); color: var(--t-text-muted); }
.dg-badge.done { background: rgba(16,185,129,0.12); color: var(--t-success); }
.dg-badge.err { background: rgba(239,68,68,0.12); color: var(--t-danger); }

.ds { display: flex; align-items: center; padding: 7px 14px; gap: 10px; font-size: 12px; }
.ds + .ds { border-top: 1px solid var(--t-border-subtle); }
.ds:hover { background: var(--t-bg-subtle); }
.ds-dot { width: 18px; height: 18px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 9px; font-weight: 700; color: #fff; flex-shrink: 0; }
.ds-dot.completed { background: var(--t-success); }
.ds-dot.error { background: var(--t-danger); }
.ds-dot.pending { background: var(--t-border-strong); width: 7px; height: 7px; margin: 0 5.5px; }
.ds-dot.pulse { background: var(--t-brand); animation: dpulse 1.5s infinite; }
@keyframes dpulse { 0%,100% { box-shadow: 0 0 0 0 var(--t-brand-glow); } 50% { box-shadow: 0 0 0 5px var(--t-brand-subtle); } }

.ds-body { flex: 1; min-width: 0; }
.ds-name { color: var(--t-text-primary); }
.ds.completed .ds-name { color: var(--t-text-muted); }
.ds.pending .ds-name { color: var(--t-text-muted); }
.ds-err { font-size: 10px; color: var(--t-danger); margin-top: 1px; }

.ds-act { flex-shrink: 0; }
.ds-btn { border: none; cursor: pointer; border-radius: 6px; font-weight: 500; font-size: 11px; transition: transform 0.2s; }
.ds-btn.run { padding: 3px 10px; background: var(--t-brand-gradient); color: #fff; }
.ds-btn.run:hover:not(:disabled) { transform: translateY(-1px); }
.ds-btn.retry { padding: 3px 10px; background: var(--t-danger); color: #fff; }
.ds-btn.redo { padding: 2px 5px; background: none; color: var(--t-text-muted); font-size: 14px; }
.ds-btn.redo:hover:not(:disabled) { color: var(--t-brand-light); }
.ds-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.ds-spin { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--t-border-subtle); border-top-color: var(--t-brand); border-radius: 50%; animation: spin 0.7s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.ds-lock { font-size: 11px; opacity: 0.15; }

.deploy-done { padding: 12px 16px; text-align: center; font-size: 13px; color: var(--t-success); font-weight: 500; }
.deploy-done-btn {
  background: var(--t-brand-gradient); color: #fff; border: none;
  border-radius: 6px; padding: 5px 12px; font-size: 12px; cursor: pointer; margin-left: 8px;
  transition: transform 0.2s;
}
.deploy-done-btn:hover { transform: translateY(-1px); }
.deploy-log-btn {
  background: none; border: 1px solid var(--t-border-subtle); color: var(--t-text-secondary);
  border-radius: 6px; padding: 5px 10px; font-size: 11px; cursor: pointer; margin-left: 6px;
}
.deploy-log-btn:hover { background: var(--t-bg-subtle); color: #fff; }

/* API 日志弹窗 */
.api-logs-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.api-logs-count { font-size: 12px; color: var(--t-text-muted); }
.api-logs-table { max-height: 500px; overflow-y: auto; }
.api-logs-table table { width: 100%; border-collapse: collapse; font-size: 12px; }
.api-logs-table th { text-align: left; padding: 8px 10px; color: var(--t-text-secondary); border-bottom: 1px solid var(--t-border-subtle); font-weight: 500; }
.api-logs-table td { padding: 6px 10px; border-bottom: 1px solid var(--t-border-subtle); color: var(--t-text-primary); }
.api-logs-table tr.error td { color: var(--t-danger); }
.api-logs-table tr:hover td { background: var(--t-bg-subtle); }
.log-time { font-family: monospace; color: var(--t-text-muted); }
.log-step { color: var(--t-brand-light); }
.log-url { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.log-status.ok { color: var(--t-success); }
.log-status.fail { color: var(--t-danger); font-weight: 600; }
.log-ms { font-family: monospace; color: var(--t-text-secondary); }
.log-result { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.api-logs-empty { text-align: center; padding: 40px; color: var(--t-text-muted); }

/* ── nav-right 项目按钮 ── */
.nav-link.active { background: var(--t-brand-subtle); color: var(--t-brand-light); }
.project-count {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 18px; height: 18px; padding: 0 5px;
  background: var(--t-brand-gradient); color: #fff; border-radius: 9px;
  font-size: 10px; font-weight: 600; margin-left: 4px;
}


/* ── 平台配置 iframe ── */
.platform-iframe-container {
  flex: 1; position: relative; overflow: hidden; min-height: 0;
}
.platform-tab-bar {
  display: flex; align-items: center; gap: 4px; padding: 4px 16px;
  border-bottom: 1px solid var(--t-border-subtle);
  flex-shrink: 0; background: rgba(0,0,0,0.3); height: 36px;
}
.platform-fullscreen-btn {
  all: unset; cursor: pointer; margin-left: auto; color: var(--t-text-muted);
  font-size: 16px; padding: 2px 8px; border-radius: 4px;
}
.platform-fullscreen-btn:hover { color: #fff; background: var(--t-border-subtle); }
.platform-login-hint {
  display: flex; align-items: center; gap: 12px; padding: 6px 16px;
  background: var(--t-brand-subtle); border-bottom: 1px solid var(--t-brand-subtle);
  font-size: 12px; color: var(--t-text-secondary); flex-shrink: 0;
}
.platform-login-hint b { color: var(--t-brand-light); }
.hint-nav-btn {
  margin-left: auto; background: var(--t-brand-gradient); color: #fff;
  border: none; border-radius: 6px; padding: 4px 12px; font-size: 12px; cursor: pointer;
  white-space: nowrap;
}
.hint-nav-btn:hover { opacity: 0.9; }
.hint-dismiss-btn {
  all: unset; cursor: pointer; color: var(--t-text-muted); font-size: 14px; padding: 2px;
}
.hint-dismiss-btn:hover { color: var(--t-text-secondary); }
.platform-iframe {
  position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: none; background: #fff;
}
.platform-loading {
  flex: 1; display: flex; align-items: center; justify-content: center;
  color: var(--t-text-secondary); font-size: 14px; gap: 8px;
}
.platform-loading .loading-spinner {
  display: inline-block; animation: spin 1s linear infinite;
}
.platform-error {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  color: var(--t-text-secondary); gap: 16px; padding: 40px;
}
.platform-error p { margin: 0; font-size: 14px; text-align: center; max-width: 400px; }
.platform-error-actions { display: flex; gap: 12px; }
.platform-retry-btn, .platform-open-btn {
  padding: 8px 20px; border-radius: 8px; border: none; cursor: pointer;
  font-size: 13px; transition: transform 0.2s, box-shadow 0.2s;
}
.platform-retry-btn {
  background: var(--t-brand-gradient); color: #fff;
}
.platform-retry-btn:hover { transform: translateY(-1px); box-shadow: 0 4px 12px var(--t-brand-glow); }
.platform-open-btn {
  background: var(--t-border-subtle); color: var(--t-text-secondary); border: 1px solid var(--t-border-subtle);
}
.platform-open-btn:hover { background: var(--t-bg-subtle); }

/* ── 变更计划 overlay ── */
.change-plan-overlay {
  position: absolute;
  inset: 0;
  z-index: 20;
  background: var(--t-bg-base);
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--t-border-subtle);
}
.change-plan-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--t-border-subtle);
}
.change-plan-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--t-text-primary);
}
.change-plan-close {
  background: none;
  border: none;
  color: var(--t-text-muted);
  font-size: 18px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
}
.change-plan-close:hover {
  color: #fff;
  background: var(--t-border-subtle);
}
.change-plan-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 20px;
}
.change-plan-diff {
  margin-bottom: 16px;
}
.change-group {
  margin-bottom: 16px;
}
.group-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--t-text-secondary);
  cursor: pointer;
  padding: 6px 0;
  user-select: none;
}
.group-title:hover { color: var(--t-text-primary); }
.group-arrow {
  display: inline-block;
  transition: transform 0.15s;
  font-size: 11px;
}
.group-arrow.expanded { transform: rotate(90deg); }
.change-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px 6px 18px;
  border-radius: 6px;
  font-size: 13px;
  color: var(--t-text-primary);
}
.change-item:hover { background: var(--t-bg-subtle); }
.change-checkbox {
  accent-color: var(--t-brand);
  width: 14px;
  height: 14px;
  cursor: pointer;
}
.change-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 4px;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}
.change-icon.add {
  background: rgba(16, 185, 129, 0.15);
  color: var(--t-success);
}
.change-icon.modify {
  background: rgba(234, 179, 8, 0.15);
  color: #eab308;
}
.change-icon.remove {
  background: rgba(239, 68, 68, 0.15);
  color: var(--t-danger);
}
.change-desc { flex: 1; line-height: 1.4; }
.change-plan-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--t-border-subtle);
  flex-wrap: wrap;
}
.cp-btn {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid var(--t-border-strong);
  background: var(--t-bg-subtle);
  color: var(--t-text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.cp-btn:hover {
  background: var(--t-border-subtle);
  color: #fff;
}
.cp-btn.primary {
  background: var(--t-brand);
  border-color: var(--t-brand);
  color: #fff;
}
.cp-btn.primary:hover { background: #6d28d9; }
.cp-btn.primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.cp-count {
  font-size: 12px;
  color: var(--t-text-secondary);
  margin-left: auto;
  margin-right: 4px;
}
.change-plan-body::-webkit-scrollbar { width: 4px; }
.change-plan-body::-webkit-scrollbar-track { background: transparent; }
.change-plan-body::-webkit-scrollbar-thumb { background: var(--t-border-subtle); border-radius: 2px; }
.change-plan-body::-webkit-scrollbar-thumb:hover { background: var(--t-border-strong); }

/* 增量更新弹窗 */
.incremental-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.incremental-modal {
  background: var(--t-bg-panel);
  border-radius: 16px;
  width: 90%;
  max-width: 600px;
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4);
}

.incremental-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--t-border-subtle);
}

.incremental-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #fff;
}

.incremental-close {
  background: none;
  border: none;
  color: #888;
  font-size: 20px;
  cursor: pointer;
  padding: 4px;
  line-height: 1;
  transition: color 0.2s;
}

.incremental-close:hover {
  color: #fff;
}

.incremental-diff {
  padding: 16px 20px;
  border-bottom: 1px solid var(--t-border-subtle);
}

.incremental-steps {
  padding: 16px 20px;
}

/* ── 滚动条 ── */
.messages::-webkit-scrollbar,
.preview-body::-webkit-scrollbar,
.deploy-groups::-webkit-scrollbar,
.projects-list::-webkit-scrollbar { width: 4px; }
.messages::-webkit-scrollbar-track,
.preview-body::-webkit-scrollbar-track,
.deploy-groups::-webkit-scrollbar-track,
.projects-list::-webkit-scrollbar-track { background: transparent; }
.messages::-webkit-scrollbar-thumb,
.preview-body::-webkit-scrollbar-thumb,
.deploy-groups::-webkit-scrollbar-thumb,
.projects-list::-webkit-scrollbar-thumb { background: var(--t-border-subtle); border-radius: 2px; }
.messages::-webkit-scrollbar-thumb:hover,
.preview-body::-webkit-scrollbar-thumb:hover,
.deploy-groups::-webkit-scrollbar-thumb:hover,
.projects-list::-webkit-scrollbar-thumb:hover { background: var(--t-border-strong); }

/* 编码冲突修复 */
.conflict-resolve-box { padding: 4px 0; }
.conflict-label { margin-bottom: 8px; font-size: 13px; }
.conflict-label code { background: rgba(139, 92, 246, 0.2); color: var(--t-brand-light); padding: 1px 6px; border-radius: 4px; font-family: monospace; font-size: 12px; }
.conflict-input-row { display: flex; gap: 8px; align-items: center; }
.conflict-input { flex: 1; padding: 6px 10px; border: 1px solid var(--t-border-strong); border-radius: 6px; background: var(--t-border-subtle); color: #e2e8f0; font-size: 13px; font-family: monospace; outline: none; transition: border-color 0.2s; }
.conflict-input:focus { border-color: var(--t-brand); }
.conflict-input:disabled { opacity: 0.5; }
.conflict-btn { border: none; cursor: pointer; border-radius: 6px; font-size: 12px; font-weight: 500; padding: 6px 14px; transition: all 0.2s; }
.conflict-btn.confirm { background: var(--t-brand-gradient); color: #fff; }
.conflict-btn.confirm:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 2px 8px var(--t-brand-glow); }
.conflict-btn.cancel { background: var(--t-border-subtle); color: #94a3b8; }
.conflict-btn.cancel:hover:not(:disabled) { background: var(--t-bg-subtle); }
.conflict-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
