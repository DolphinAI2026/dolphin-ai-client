<template>
  <div class="req-page">
    <!-- 顶部导航 -->
    <nav class="nav-bar">
      <div class="nav-left">
        <button class="back-btn" @click="router.push('/')">
          <el-icon><ArrowLeft /></el-icon>
        </button>
        <div class="logo-box">A</div>
        <span class="logo-text">需求分析</span>
      </div>
      <div class="nav-right">
        <ThemeToggle />
        <div class="user-menu">
          <el-dropdown @command="handleUserCommand">
            <button class="user-btn">
              <span class="user-avatar">{{ userInitial }}</span>
              <span class="user-name">{{ userStore.user?.username }}</span>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </nav>

    <div class="main-layout">
      <!-- 左侧：会话列表 -->
      <aside class="sidebar">
        <button class="new-session-btn" @click="createSession">
          <el-icon><Plus /></el-icon>
          新建需求分析
        </button>
        <div class="session-list">
          <div
            v-for="s in sessions"
            :key="s.id"
            class="session-item"
            :class="{ active: currentSessionId === s.id }"
            @click="loadSession(s.id)"
          >
            <div class="session-info">
              <span class="session-title">{{ s.title }}</span>
              <span class="session-meta">{{ formatDate(s.updated_at) }}</span>
            </div>
            <div class="session-badges">
              <el-tag
                v-if="s.has_doc"
                size="small"
                type="success"
                @click.stop="loadSession(s.id, true)"
              >
                已生成
              </el-tag>
            </div>
            <button class="delete-btn" @click.stop="deleteSession(s.id)" title="删除">
              <el-icon><Delete /></el-icon>
            </button>
          </div>
          <div v-if="sessions.length === 0" class="empty-sessions">
            暂无历史记录
          </div>
        </div>
      </aside>

      <!-- 中间：对话区域 -->
      <div class="chat-area">
        <!-- 无会话时的引导 -->
        <div v-if="!currentSessionId" class="welcome-state">
          <div class="welcome-icon">💬</div>
          <h2>开始需求分析</h2>
          <p>与 AI 对话，逐步梳理您的业务需求，<br>生成结构化的功能设计文档</p>
          <button class="start-btn" @click="createSession">开始新会话</button>
        </div>

        <!-- 对话内容 -->
        <template v-else>
          <div class="messages-container" ref="messagesContainer">
            <div
              v-for="(msg, idx) in displayMessages"
              :key="idx"
              class="message"
              :class="msg.role"
            >
              <div class="message-avatar">
                <span v-if="msg.role === 'assistant'">AI</span>
                <span v-else>我</span>
              </div>
              <div class="message-bubble">
                <div v-if="msg.role === 'user' && isFileMessage(msg.content)" class="file-msg-badge">
                  <el-icon><Document /></el-icon>
                  <span>{{ extractFileName(msg.content) }}</span>
                  <span v-if="extractUserText(msg.content)" class="file-msg-text">{{ extractUserText(msg.content) }}</span>
                </div>
                <div v-else class="message-content" v-html="renderMarkdown(msg.content || '')"></div>
              </div>
            </div>
            <!-- 流式打字中 -->
            <div v-if="chatStreaming && displayStreamingText" class="message assistant">
              <div class="message-avatar"><span>AI</span></div>
              <div class="message-bubble">
                <div class="message-content" v-html="renderMarkdown(displayStreamingText)"></div>
                <span class="typing-cursor">▋</span>
              </div>
            </div>
            <div v-if="chatStreaming && !displayStreamingText" class="message assistant">
              <div class="message-avatar"><span>AI</span></div>
              <div class="message-bubble thinking">
                <span class="dot"></span><span class="dot"></span><span class="dot"></span>
              </div>
            </div>
          </div>

          <!-- 输入区域 -->
          <div class="input-area">
            <div class="model-picker-row">
              <div class="model-picker-meta">
                <span class="model-picker-label">当前模型</span>
                <span class="model-picker-hint">{{ builderModelHint }}</span>
              </div>
              <el-select
                v-model="selectedBuilderModelId"
                class="model-picker-select"
                popper-class="model-select-dropdown"
                size="small"
                placeholder="选择模型"
                :loading="builderModelLoading"
                :disabled="builderModelLoading || updatingBuilderModel || builderModelOptions.length === 0"
                @change="handleBuilderModelChange"
              >
                <el-option
                  v-for="option in builderModelOptions"
                  :key="option.id"
                  :label="formatBuilderModelOption(option)"
                  :value="option.id"
                >
                  <div class="model-option-row">
                    <span class="model-option-name">{{ option.config_name }}</span>
                    <span class="model-option-meta">{{ option.provider }} / {{ option.model }}</span>
                  </div>
                </el-option>
              </el-select>
            </div>

            <!-- 已上传文件/图片提示 -->
            <div v-if="uploadedFile" class="file-badge">
              <template v-if="uploadedFilePreview">
                <img :src="uploadedFilePreview" class="file-badge-img" />
                <span>{{ uploadedFile.name }}</span>
              </template>
              <template v-else>
                <el-icon><Document /></el-icon>
                <span>{{ uploadedFile.name }}</span>
              </template>
              <button @click="clearUploadedFile"><el-icon><Close /></el-icon></button>
            </div>

            <div class="input-row">
              <label class="upload-label" title="上传需求文档">
                <input
                  type="file"
                  accept=".md,.pdf,.docx,.doc,.txt,.markdown,.png,.jpg,.jpeg,.gif,.webp"
                  @change="handleFileSelect"
                  ref="fileInputRef"
                  hidden
                />
                <el-icon><Paperclip /></el-icon>
              </label>
              <textarea
                v-model="inputText"
                placeholder="描述您的业务需求...（可粘贴截图）"
                @keydown.enter.exact.prevent="sendMessage"
                @keydown.enter.shift.exact="inputText += '\n'"
                rows="1"
                ref="inputRef"
                @input="autoResizeInput"
                @paste="handlePaste"
              ></textarea>
              <button
                class="send-btn"
                @click="sendMessage"
                :disabled="chatStreaming || (!inputText.trim() && !uploadedFile)"
              >
                <el-icon><Promotion /></el-icon>
              </button>
            </div>

            <!-- 操作按钮 -->
            <div class="action-bar">
              <button
                class="gen-doc-btn"
                @click="handleGenerateDoc"
                :disabled="generating || messages.length < 2"
              >
                <el-icon><MagicStick /></el-icon>
                {{ generating ? '生成中...' : (docResult ? '根据对话更新文档' : '生成设计文档') }}
              </button>
              <span class="hint">{{ messages.length < 2 ? '先开始对话，再生成设计文档' : (docResult ? '对话后可随时更新文档' : '根据对话内容生成结构化设计文档') }}</span>
            </div>
          </div>
        </template>
      </div>

      <!-- 右侧：设计文档预览 -->
      <div class="doc-panel" :class="{ visible: docPanelVisible }">
        <div class="doc-header">
          <h3>功能设计文档</h3>
          <div class="doc-actions">
            <el-button v-if="docResult" size="small" @click="editMode = !editMode" :type="editMode ? 'warning' : ''">
              {{ editMode ? '完成编辑' : '编辑' }}
            </el-button>
            <el-button v-if="docResult" size="small" @click="docFullscreen = true">
              <el-icon><FullScreen /></el-icon>
            </el-button>
            <el-button size="small" @click="handleConfirm" type="primary" :loading="confirming" :disabled="!docResult">
              确认生成 →
            </el-button>
          </div>
        </div>

        <!-- 生成进度条 -->
        <div v-if="generating" class="doc-progress">
          <div class="gen-step-text">{{ genStep }}</div>
          <el-progress :percentage="Math.round(genProgress)" :striped="true" :striped-flow="true" :duration="5" status="" />
        </div>

        <!-- 错误提示 -->
        <div v-if="genError && !generating" class="gen-error">
          <el-icon><Warning /></el-icon>
          <span>{{ genError }}</span>
          <el-button size="small" text type="primary" @click="handleGenerateDoc">重试</el-button>
        </div>

        <!-- 文档内容 -->
        <div v-else-if="docResult" class="doc-content">
          <!-- 应用信息 -->
          <div class="doc-section">
            <div class="section-title">
              <span class="section-icon">📱</span>应用信息
            </div>
            <div class="info-grid">
              <div class="info-item">
                <span class="label">应用编码</span>
                <input v-if="editMode" v-model="docResult.app_info.code" class="edit-input" />
                <span v-else class="value">{{ docResult.app_info.code }}</span>
              </div>
              <div class="info-item">
                <span class="label">应用名称</span>
                <input v-if="editMode" v-model="docResult.app_info.name" class="edit-input" />
                <span v-else class="value">{{ docResult.app_info.name }}</span>
              </div>
              <div class="info-item full">
                <span class="label">描述</span>
                <textarea v-if="editMode" v-model="docResult.app_info.description" class="edit-textarea" rows="2"></textarea>
                <span v-else class="value">{{ docResult.app_info.description }}</span>
              </div>
            </div>
          </div>

          <!-- 角色清单 -->
          <div class="doc-section">
            <div class="section-title">
              <span class="section-icon">👥</span>角色清单
              <span class="count-badge">{{ docResult.roles.length }}</span>
            </div>
            <div class="tag-list" v-if="!editMode">
              <el-tag v-for="role in docResult.roles" :key="role.role_code" size="small" :title="role.description">{{ role.role_name }}</el-tag>
            </div>
            <div class="role-table">
              <div v-for="(role, idx) in docResult.roles" :key="role.role_code" class="role-row">
                <input v-if="editMode" v-model="role.role_code" class="edit-input-sm" placeholder="编码" style="width:110px" />
                <span v-else class="role-code">{{ role.role_code }}</span>
                <input v-if="editMode" v-model="role.role_name" class="edit-input-sm" placeholder="角色名" style="width:90px" />
                <span v-else class="role-name">{{ role.role_name }}</span>
                <input v-if="editMode" v-model="role.description" class="edit-input" placeholder="职责描述" style="flex:1" />
                <span v-else class="role-desc">{{ role.description }}</span>
                <button v-if="editMode" class="del-item-btn" @click="docResult.roles.splice(idx, 1)">×</button>
              </div>
            </div>
            <button v-if="editMode" class="add-item-btn" @click="docResult.roles.push({ role_code: 'role_' + docResult.roles.length, role_name: '', description: '' })">+ 新增角色</button>
          </div>

          <!-- 数据字典 -->
          <div class="doc-section">
            <div class="section-title">
              <span class="section-icon">📚</span>数据字典
              <span class="count-badge">{{ docResult.data_dictionary.length }}</span>
            </div>
            <div class="dict-list">
              <div v-for="(d, di) in docResult.data_dictionary" :key="d.dict_code" class="dict-item">
                <div class="dict-header">
                  <input v-if="editMode" v-model="d.dict_name" class="edit-input" style="width:120px" />
                  <span v-else class="dict-name">{{ d.dict_name }}</span>
                  <input v-if="editMode" v-model="d.dict_code" class="edit-input-sm" style="width:130px" />
                  <span v-else class="dict-code">{{ d.dict_code }}</span>
                  <button v-if="editMode" class="del-item-btn" @click="docResult.data_dictionary.splice(di, 1)" style="margin-left:auto">×</button>
                </div>
                <div v-if="editMode" class="dict-items-edit">
                  <div v-for="(item, idx) in d.items" :key="idx" class="dict-item-row">
                    <input v-model="item.item_name" class="edit-input-sm" placeholder="选项名" />
                    <button class="del-item-btn" @click="d.items.splice(idx, 1)">×</button>
                  </div>
                  <button class="add-item-btn" @click="d.items.push({ item_code: 'opt_' + d.items.length, item_name: '' })">+ 添加选项</button>
                </div>
                <div v-else class="dict-items">
                  <el-tag v-for="item in d.items" :key="item.item_code" size="small" type="info">{{ item.item_name }}</el-tag>
                </div>
              </div>
            </div>
            <button v-if="editMode" class="add-item-btn" @click="docResult.data_dictionary.push({ dict_code: 'dict_' + docResult.data_dictionary.length, dict_name: '新字典', items: [] })">+ 新增字典</button>
          </div>

          <!-- 表结构 -->
          <div class="doc-section">
            <div class="section-title">
              <span class="section-icon">🗃️</span>数据表
              <span class="count-badge">{{ docResult.tables.length }}</span>
            </div>
            <div class="table-list">
              <div v-for="(t, ti) in docResult.tables" :key="t.table_code" class="table-item">
                <div class="table-header">
                  <input v-if="editMode" v-model="t.table_name" class="edit-input" style="width:130px" />
                  <span v-else class="table-name">{{ t.table_name }}</span>
                  <el-tag size="small" :type="t.table_type === '子表' ? 'warning' : 'primary'">{{ t.table_type }}</el-tag>
                  <input v-if="editMode" v-model="t.table_code" class="edit-input-sm" style="width:140px" />
                  <span v-else class="table-code">{{ t.table_code }}</span>
                  <button v-if="editMode" class="del-item-btn" @click="docResult.tables.splice(ti, 1)" style="margin-left:auto">×</button>
                </div>
                <div v-if="editMode" class="fields-edit">
                  <div v-for="(f, idx) in t.fields" :key="idx" class="field-edit-row">
                    <input v-model="f.field_name" class="edit-input-sm" placeholder="字段名" />
                    <input v-model="f.data_type" class="edit-input-sm" placeholder="类型" style="width:80px" />
                    <button class="del-item-btn" @click="t.fields.splice(idx, 1)">×</button>
                  </div>
                  <button class="add-item-btn" @click="t.fields.push({ field_code: 'f_' + t.fields.length, field_name: '', data_type: '单行输入' })">+ 添加字段</button>
                </div>
                <div v-else>
                  <div v-if="t.description" class="table-desc">{{ t.description }}</div>
                  <div class="field-list">
                    <span v-for="f in t.fields" :key="f.field_code" class="field-chip" :title="`${f.field_name} (${f.data_type})`">{{ f.field_name }}</span>
                  </div>
                </div>
              </div>
            </div>
            <button v-if="editMode" class="add-item-btn" @click="docResult.tables.push({ table_code: 't_new_' + docResult.tables.length, table_name: '新数据表', table_type: '主表', parent_table: '', description: '', fields: [] })">+ 新增数据表</button>
          </div>

          <!-- 业务流程 -->
          <div class="doc-section" v-if="docResult.flows?.length">
            <div class="section-title">
              <span class="section-icon">🔄</span>业务流程
              <span class="count-badge">{{ docResult.flows.length }}</span>
            </div>
            <div class="flow-list">
              <div v-for="flow in docResult.flows" :key="flow.flow_code" class="flow-item">
                <div class="flow-header">
                  <span class="flow-name">{{ flow.flow_name }}</span>
                </div>
                <div v-if="flow.description" class="flow-desc">{{ flow.description }}</div>
                <div class="flow-steps">
                  <div v-for="step in flow.steps" :key="step.step" class="flow-step">
                    <span class="step-num">{{ step.step }}</span>
                    <span class="step-action">{{ step.action }}</span>
                    <span class="step-role">{{ step.role }}</span>
                    <span v-if="step.status" class="step-status">→ {{ step.status }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 权限矩阵 -->
          <div class="doc-section">
            <div class="section-title">
              <span class="section-icon">🔐</span>权限矩阵
              <button class="sync-matrix-btn" @click="syncMatrix" title="根据当前角色和主表重建矩阵">↻ 同步</button>
            </div>
            <div class="matrix-wrap">
              <table class="matrix-table">
                <thead>
                  <tr>
                    <th>主表</th>
                    <th class="col-all-employee">全部员工</th>
                    <th v-for="role in docResult.roles" :key="role.role_code">{{ role.role_name }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="mapping in mainTableMappings" :key="mapping.table_code">
                    <td>
                      <strong>{{ mapping.table_name }}</strong>
                      <div class="matrix-table-code">{{ mapping.table_code }}</div>
                    </td>
                    <td class="col-all-employee">
                      <div class="matrix-cell">
                        <div class="matrix-ops-row">
                          <span
                            v-for="op in ALL_OPS"
                            :key="op"
                            :class="['matrix-op', getPermEntry(mapping, ALL_EMPLOYEE_ROLE).operations.includes(op) ? 'checked' : '']"
                            @click="toggleOp(mapping, ALL_EMPLOYEE_ROLE, op)"
                          >{{ op }}</span>
                        </div>
                        <div class="data-scope-wrap">
                          <span class="data-scope-label">📂</span>
                          <select
                            :value="getPermEntry(mapping, ALL_EMPLOYEE_ROLE).data_scope || 'self'"
                            @change="getPermEntry(mapping, ALL_EMPLOYEE_ROLE).data_scope = ($event.target as HTMLSelectElement).value"
                            class="data-scope-select"
                          >
                            <option v-for="s in DATA_SCOPES" :key="s.value" :value="s.value">{{ s.label }}</option>
                          </select>
                        </div>
                      </div>
                    </td>
                    <td v-for="role in docResult.roles" :key="role.role_code">
                      <div class="matrix-cell">
                        <div class="matrix-ops-row">
                          <span
                            v-for="op in ALL_OPS"
                            :key="op"
                            :class="['matrix-op', getPermEntry(mapping, role).operations.includes(op) ? 'checked' : '']"
                            @click="toggleOp(mapping, role, op)"
                          >{{ op }}</span>
                        </div>
                        <div class="data-scope-wrap">
                          <span class="data-scope-label">📂</span>
                          <select
                            :value="getPermEntry(mapping, role).data_scope || 'none'"
                            @change="getPermEntry(mapping, role).data_scope = ($event.target as HTMLSelectElement).value"
                            class="data-scope-select"
                          >
                            <option v-for="s in DATA_SCOPES" :key="s.value" :value="s.value">{{ s.label }}</option>
                          </select>
                        </div>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div v-else-if="!generating" class="doc-empty">
          <el-icon size="40"><Document /></el-icon>
          <p>点击「生成设计文档」<br>生成结构化的功能设计文档</p>
        </div>
      </div>
    </div>

    <!-- 全屏文档对话框 -->
    <el-dialog v-model="docFullscreen" fullscreen title="功能设计文档" class="doc-fullscreen-dialog">
      <template #header>
        <div style="display:flex;align-items:center;justify-content:space-between;padding-right:40px">
          <span style="font-size:16px;font-weight:600">功能设计文档</span>
          <div style="display:flex;gap:8px">
            <el-button size="small" @click="editMode = !editMode" :type="editMode ? 'warning' : ''">
              {{ editMode ? '完成编辑' : '编辑' }}
            </el-button>
            <el-button size="small" type="primary" @click="handleGenerateDoc" :loading="generating">
              <el-icon><Refresh /></el-icon> 根据对话更新
            </el-button>
          </div>
        </div>
      </template>
      <div v-if="docResult" class="doc-content doc-content-full">
        <div class="doc-section">
          <div class="section-title"><span class="section-icon">📱</span>应用信息</div>
          <div class="info-grid">
            <div class="info-item">
              <span class="label">应用编码</span>
              <input v-if="editMode" v-model="docResult.app_info.code" class="edit-input" />
              <span v-else class="value">{{ docResult.app_info.code }}</span>
            </div>
            <div class="info-item">
              <span class="label">应用名称</span>
              <input v-if="editMode" v-model="docResult.app_info.name" class="edit-input" />
              <span v-else class="value">{{ docResult.app_info.name }}</span>
            </div>
            <div class="info-item full">
              <span class="label">描述</span>
              <textarea v-if="editMode" v-model="docResult.app_info.description" class="edit-textarea" rows="2"></textarea>
              <span v-else class="value">{{ docResult.app_info.description }}</span>
            </div>
          </div>
        </div>
        <div class="doc-section">
          <div class="section-title"><span class="section-icon">👥</span>角色清单 <span class="count-badge">{{ docResult.roles.length }}</span></div>
          <div class="tag-list" v-if="!editMode">
            <el-tag v-for="role in docResult.roles" :key="role.role_code" size="small" :title="role.description">{{ role.role_name }}</el-tag>
          </div>
          <div class="role-table">
            <div v-for="(role, idx) in docResult.roles" :key="role.role_code" class="role-row">
              <input v-if="editMode" v-model="role.role_code" class="edit-input-sm" placeholder="编码" style="width:110px" />
              <span v-else class="role-code">{{ role.role_code }}</span>
              <input v-if="editMode" v-model="role.role_name" class="edit-input-sm" placeholder="角色名" style="width:90px" />
              <span v-else class="role-name">{{ role.role_name }}</span>
              <input v-if="editMode" v-model="role.description" class="edit-input" placeholder="职责描述" style="flex:1" />
              <span v-else class="role-desc">{{ role.description }}</span>
              <button v-if="editMode" class="del-item-btn" @click="docResult.roles.splice(idx, 1)">×</button>
            </div>
          </div>
          <button v-if="editMode" class="add-item-btn" @click="docResult.roles.push({ role_code: 'role_' + docResult.roles.length, role_name: '', description: '' })">+ 新增角色</button>
        </div>
        <div class="doc-section">
          <div class="section-title"><span class="section-icon">📚</span>数据字典 <span class="count-badge">{{ docResult.data_dictionary.length }}</span></div>
          <div class="dict-list">
            <div v-for="(d, di) in docResult.data_dictionary" :key="d.dict_code" class="dict-item">
              <div class="dict-header">
                <input v-if="editMode" v-model="d.dict_name" class="edit-input" style="width:120px" />
                <span v-else class="dict-name">{{ d.dict_name }}</span>
                <input v-if="editMode" v-model="d.dict_code" class="edit-input-sm" style="width:130px" />
                <span v-else class="dict-code">{{ d.dict_code }}</span>
                <button v-if="editMode" class="del-item-btn" @click="docResult.data_dictionary.splice(di, 1)" style="margin-left:auto">×</button>
              </div>
              <div v-if="editMode" class="dict-items-edit">
                <div v-for="(item, idx) in d.items" :key="idx" class="dict-item-row">
                  <input v-model="item.item_name" class="edit-input-sm" placeholder="选项名" />
                  <button class="del-item-btn" @click="d.items.splice(idx, 1)">×</button>
                </div>
                <button class="add-item-btn" @click="d.items.push({ item_code: 'opt_' + d.items.length, item_name: '' })">+ 添加选项</button>
              </div>
              <div v-else class="dict-items">
                <el-tag v-for="item in d.items" :key="item.item_code" size="small" type="info">{{ item.item_name }}</el-tag>
              </div>
            </div>
          </div>
          <button v-if="editMode" class="add-item-btn" @click="docResult.data_dictionary.push({ dict_code: 'dict_' + docResult.data_dictionary.length, dict_name: '新字典', items: [] })">+ 新增字典</button>
        </div>
        <div class="doc-section">
          <div class="section-title"><span class="section-icon">🗃️</span>数据表 <span class="count-badge">{{ docResult.tables.length }}</span></div>
          <div class="table-list">
            <div v-for="(t, ti) in docResult.tables" :key="t.table_code" class="table-item">
              <div class="table-header">
                <input v-if="editMode" v-model="t.table_name" class="edit-input" style="width:130px" />
                <span v-else class="table-name">{{ t.table_name }}</span>
                <el-tag size="small" :type="t.table_type === '子表' ? 'warning' : 'primary'">{{ t.table_type }}</el-tag>
                <input v-if="editMode" v-model="t.table_code" class="edit-input-sm" style="width:140px" />
                <span v-else class="table-code">{{ t.table_code }}</span>
                <button v-if="editMode" class="del-item-btn" @click="docResult.tables.splice(ti, 1)" style="margin-left:auto">×</button>
              </div>
              <div v-if="editMode" class="fields-edit">
                <div v-for="(f, idx) in t.fields" :key="idx" class="field-edit-row">
                  <input v-model="f.field_name" class="edit-input-sm" placeholder="字段名" />
                  <input v-model="f.data_type" class="edit-input-sm" placeholder="类型" style="width:80px" />
                  <button class="del-item-btn" @click="t.fields.splice(idx, 1)">×</button>
                </div>
                <button class="add-item-btn" @click="t.fields.push({ field_code: 'f_' + t.fields.length, field_name: '', data_type: '单行输入' })">+ 添加字段</button>
              </div>
              <div v-else>
                <div v-if="t.description" class="table-desc">{{ t.description }}</div>
                <div class="field-list">
                  <span v-for="f in t.fields" :key="f.field_code" class="field-chip" :title="`${f.field_name} (${f.data_type})`">{{ f.field_name }}</span>
                </div>
              </div>
            </div>
          </div>
          <button v-if="editMode" class="add-item-btn" @click="docResult.tables.push({ table_code: 't_new_' + docResult.tables.length, table_name: '新数据表', table_type: '主表', parent_table: '', description: '', fields: [] })">+ 新增数据表</button>
        </div>
        <!-- 业务流程 -->
        <div class="doc-section" v-if="docResult.flows?.length">
          <div class="section-title">
            <span class="section-icon">🔄</span>业务流程
            <span class="count-badge">{{ docResult.flows.length }}</span>
          </div>
          <div class="flow-list">
            <div v-for="flow in docResult.flows" :key="flow.flow_code" class="flow-item">
              <div class="flow-header">
                <span class="flow-name">{{ flow.flow_name }}</span>
              </div>
              <div v-if="flow.description" class="flow-desc">{{ flow.description }}</div>
              <div class="flow-steps">
                <div v-for="step in flow.steps" :key="step.step" class="flow-step">
                  <span class="step-num">{{ step.step }}</span>
                  <span class="step-action">{{ step.action }}</span>
                  <span class="step-role">{{ step.role }}</span>
                  <span v-if="step.status" class="step-status">→ {{ step.status }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="doc-section">
          <div class="section-title">
            <span class="section-icon">🔐</span>权限矩阵
            <button class="sync-matrix-btn" @click="syncMatrix" title="根据当前角色和主表重建矩阵">↻ 同步</button>
          </div>
          <div class="matrix-wrap">
            <table class="matrix-table">
              <thead>
                <tr>
                  <th>主表</th>
                  <th v-for="role in docResult.roles" :key="role.role_code">{{ role.role_name }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="mapping in mainTableMappings" :key="mapping.table_code">
                  <td>
                    <strong>{{ mapping.table_name }}</strong>
                    <div class="matrix-table-code">{{ mapping.table_code }}</div>
                  </td>
                  <td v-for="role in docResult.roles" :key="role.role_code">
                    <div class="matrix-cell">
                      <div class="matrix-ops-row">
                        <span
                          v-for="op in ALL_OPS"
                          :key="op"
                          :class="['matrix-op', getPermEntry(mapping, role).operations.includes(op) ? 'checked' : '']"
                          @click="toggleOp(mapping, role, op)"
                        >{{ op }}</span>
                      </div>
                      <div class="data-scope-wrap">
                        <span class="data-scope-label">📂</span>
                        <select
                          :value="getPermEntry(mapping, role).data_scope || 'none'"
                          @change="getPermEntry(mapping, role).data_scope = ($event.target as HTMLSelectElement).value"
                          class="data-scope-select"
                        >
                          <option v-for="s in DATA_SCOPES" :key="s.value" :value="s.value">{{ s.label }}</option>
                        </select>
                      </div>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button type="primary" @click="handleConfirm" :loading="confirming">确认生成并进入搭建 →</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, watch } from 'vue'

// ── 权限矩阵常量 ────────────────────────────────────────────────────────────
const ALL_OPS = ["暂存","新增","导入","复制新建","批量删除","批量同意","批量拒绝",
                 "查看","编辑","删除","查看审批历史","打印","日志","评论","导出"]

const ALL_EMPLOYEE_ROLE = { role_code: 'all_employee', role_name: '全部员工' }

const DATA_SCOPES = [
  { value: 'none',   label: '无权限' },
  { value: 'self',   label: '仅本人' },
  { value: 'dept',   label: '本部门' },
  { value: 'all',    label: '全公司' },
  { value: 'custom', label: '自定义' },
]
import { useRouter, useRoute } from 'vue-router'
import {
  ArrowLeft, Plus, Delete, Document, Close, Paperclip,
  Promotion, MagicStick, FullScreen, Warning, Refresh
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { usePreviewStore } from '@/stores/preview'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { requirementsApi, type RequirementsSession, type ChatMessage, type AnalysisResult } from '@/api/requirements'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const previewStore = usePreviewStore()

// ── State ──────────────────────────────────────────────────────────────────
const sessions = ref<RequirementsSession[]>([])
const currentSessionId = ref<number | null>(null)
const messages = ref<ChatMessage[]>([])
const inputText = ref('')
const uploadedFile = ref<File | null>(null)
const uploadedFilePreview = ref<string>('')  // 图片预览 data URL
const chatStreaming = ref(false)
const streamingText = ref('')

// 过滤空消息和纯 think 消息
const displayMessages = computed(() =>
  messages.value.filter(msg => {
    if (msg.role !== 'assistant') return true
    const content = msg.content || ''
    // 过滤掉空消息和纯 think 内容
    const cleaned = stripThink(content)
    return cleaned.length > 0
  })
)

// 过滤掉 <think>...</think> 思考内容，只显示实际回答
const displayStreamingText = computed(() => {
  let text = streamingText.value
  // 移除完整的 <think>...</think> 块
  text = text.replace(/<think>[\s\S]*?<\/think>/g, '')
  // 如果还有未闭合的 <think>（流式中间态），隐藏它后面的所有内容
  const openIdx = text.indexOf('<think>')
  if (openIdx >= 0) text = text.slice(0, openIdx)
  return text.trim()
})
const generating = ref(false)
const confirming = ref(false)
const docResult = ref<AnalysisResult | null>(null)
const messagesContainer = ref<HTMLElement | null>(null)
const inputRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const genProgress = ref(0)
const genStep = ref('')
const genError = ref('')
const docFullscreen = ref(false)
const editMode = ref(false)
const builderModelOptions = ref<BuilderModelOption[]>([])
const builderModelLoading = ref(false)
const updatingBuilderModel = ref(false)
const selectedBuilderModelId = ref<number | null>(null)
const persistedBuilderModelId = ref<number | null>(null)
let genTimer: ReturnType<typeof setInterval> | null = null

const userInitial = computed(() =>
  (userStore.user?.username || 'U').charAt(0).toUpperCase()
)

const docPanelVisible = computed(() =>
  generating.value || !!docResult.value || !!genError.value
)
const defaultBuilderModelId = computed(() =>
  builderModelOptions.value.find(option => option.is_default)?.id
  ?? builderModelOptions.value[0]?.id
  ?? null
)
const builderModelHint = computed(() => {
  if (builderModelLoading.value) return '正在加载可用模型...'
  if (builderModelOptions.value.length === 0) return '未配置可用模型，请前往环境管理配置'
  if (currentSessionId.value) return '切换后仅影响后续对话与文档生成'
  return '首条消息会使用当前选择的模型'
})

function normalizeDocResult(raw: any): AnalysisResult | null {
  if (!raw || typeof raw !== 'object') return null
  const hasCore =
    raw.app_info &&
    Array.isArray(raw.roles) &&
    Array.isArray(raw.data_dictionary) &&
    Array.isArray(raw.tables) &&
    Array.isArray(raw.role_table_mapping)
  if (!hasCore) return null
  return raw as AnalysisResult
}

function normalizeBuilderModelId(modelId?: number | null): number | null {
  const ids = new Set(builderModelOptions.value.map(option => option.id))
  if (modelId != null && ids.has(modelId)) return modelId
  return defaultBuilderModelId.value
}

function applyBuilderModelSelection(modelId?: number | null) {
  const normalized = normalizeBuilderModelId(modelId)
  selectedBuilderModelId.value = normalized
  persistedBuilderModelId.value = currentSessionId.value ? normalized : null
}

function formatBuilderModelOption(option: BuilderModelOption): string {
  return option.config_name
}

async function loadBuilderModelOptions() {
  builderModelLoading.value = true
  try {
    builderModelOptions.value = await llmConfigApi.listOptions('builder')
    selectedBuilderModelId.value = normalizeBuilderModelId(selectedBuilderModelId.value)
    if (currentSessionId.value) {
      persistedBuilderModelId.value = normalizeBuilderModelId(persistedBuilderModelId.value)
    }
  } catch {
    builderModelOptions.value = []
    selectedBuilderModelId.value = null
    persistedBuilderModelId.value = null
  } finally {
    builderModelLoading.value = false
  }
}

async function handleBuilderModelChange(nextValue: number | null) {
  selectedBuilderModelId.value = nextValue
  if (!currentSessionId.value) return

  const previousValue = persistedBuilderModelId.value
  updatingBuilderModel.value = true
  try {
    const { conversationApi } = await import('@/api/conversation')
    const updated = await conversationApi.updateModel(currentSessionId.value, nextValue)
    const normalized = normalizeBuilderModelId(updated.selected_llm_config_id)
    selectedBuilderModelId.value = normalized
    persistedBuilderModelId.value = normalized

    const sessionIdx = sessions.value.findIndex(session => session.id === currentSessionId.value)
    if (sessionIdx >= 0) {
      const session = sessions.value[sessionIdx]
      if (session) {
        session.selected_llm_config_id = updated.selected_llm_config_id ?? null
      }
    }
  } catch (e: any) {
    selectedBuilderModelId.value = normalizeBuilderModelId(previousValue)
    ElMessage.error(e?.response?.data?.detail || '切换模型失败')
  } finally {
    updatingBuilderModel.value = false
  }
}

// ── 权限矩阵 helpers ────────────────────────────────────────────────────────
const mainTableMappings = computed(() => {
  if (!docResult.value) return []
  const tables = Array.isArray((docResult.value as any).tables) ? (docResult.value as any).tables : []
  const mappings = Array.isArray((docResult.value as any).role_table_mapping) ? (docResult.value as any).role_table_mapping : []
  const mainCodes = new Set(
    tables.filter((t: any) => t.table_type === '主表').map((t: any) => t.table_code)
  )
  // If no explicit 主表 label, show all mappings
  if (mainCodes.size === 0) return mappings
  return mappings.filter((m: any) => mainCodes.has(m.table_code))
})

function getPermEntry(mapping: any, role: any) {
  if (!mapping.permissions) mapping.permissions = []
  let entry = mapping.permissions.find((p: any) => p.role_code === role.role_code)
  if (!entry) {
    const defaultScope = role.role_code === 'all_employee' ? 'self' : 'none'
    entry = { role_code: role.role_code, role_name: role.role_name, operations: [], data_scope: defaultScope }
    mapping.permissions.push(entry)
  }
  return entry
}

function toggleOp(mapping: any, role: any, op: string) {
  const entry = getPermEntry(mapping, role)
  const idx = entry.operations.indexOf(op)
  if (idx >= 0) entry.operations.splice(idx, 1)
  else entry.operations.push(op)
}

function syncMatrix() {
  if (!docResult.value) return
  const mainTables = docResult.value.tables.filter((t: any) => t.table_type === '主表')
  const tables = mainTables.length ? mainTables : docResult.value.tables
  // 全部员工始终作为第一列，后跟业务角色
  const allRoles = [ALL_EMPLOYEE_ROLE, ...docResult.value.roles]
  const existing = docResult.value.role_table_mapping || []
  docResult.value.role_table_mapping = tables.map((t: any) => {
    const found = existing.find((m: any) => m.table_code === t.table_code)
    return {
      table_code: t.table_code,
      table_name: t.table_name,
      permissions: allRoles.map((r: any) => {
        const ep = found?.permissions?.find((p: any) => p.role_code === r.role_code)
        const defaultScope = r.role_code === 'all_employee' ? 'self' : 'none'
        return ep || { role_code: r.role_code, role_name: r.role_name, operations: [], data_scope: defaultScope }
      })
    }
  })
}

// ── 文件消息识别 ──────────────────────────────────────────────────────────────
const FILE_MSG_RE = /\[上传文件：([^\]]+)\]/

function isFileMessage(content: string): boolean {
  return FILE_MSG_RE.test(content)
}
function extractFileName(content: string): string {
  return content.match(FILE_MSG_RE)?.[1] ?? ''
}
function extractUserText(content: string): string {
  // 返回 [上传文件：...] 之前的用户文字（如有）
  const idx = content.indexOf('[上传文件：')
  return idx > 0 ? content.slice(0, idx).trim() : ''
}

// ── Markdown 渲染（简单版）──────────────────────────────────────────────────
function stripThink(text: string): string {
  // 移除完整的 <think>...</think>
  let t = text.replace(/<think>[\s\S]*?<\/think>/g, '')
  // 移除未闭合的 <think>（流式中间态或截断）
  const idx = t.indexOf('<think>')
  if (idx >= 0) t = t.slice(0, idx)
  return t.trim()
}

function renderMarkdown(text: string): string {
  if (!text) return ''
  // 先过滤 think 内容再渲染
  const cleaned = stripThink(text)
  if (!cleaned) return '<span style="color:var(--t-text-muted);font-style:italic">（思考中未产生回复）</span>'
  return cleaned
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/^#{1,3}\s(.+)$/gm, '<strong>$1</strong>')
    .replace(/^[-•]\s(.+)$/gm, '• $1')
    .replace(/\n/g, '<br>')
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

// ── Auto-resize textarea ───────────────────────────────────────────────────
function autoResizeInput() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

// ── Scroll to bottom ───────────────────────────────────────────────────────
async function scrollToBottom() {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

// ── Load sessions list ─────────────────────────────────────────────────────
async function loadSessions() {
  try {
    sessions.value = await requirementsApi.listSessions()
  } catch {
    // ignore
  }
}

// ── Create new session ─────────────────────────────────────────────────────
async function createSession() {
  try {
    const session = await requirementsApi.createSession({
      selected_llm_config_id: selectedBuilderModelId.value ?? undefined,
    })
    sessions.value.unshift({ ...session, has_doc: false })
    currentSessionId.value = session.id
    messages.value = session.messages || []
    docResult.value = normalizeDocResult(session.doc_result)
    applyBuilderModelSelection(session.selected_llm_config_id)
    genError.value = ''
    await scrollToBottom()
  } catch {
    ElMessage.error('创建会话失败')
  }
}

// ── Load existing session ──────────────────────────────────────────────────
async function loadSession(id: number, force = false) {
  if (!force && currentSessionId.value === id) return
  try {
    const session = await requirementsApi.getSession(id)
    currentSessionId.value = id
    messages.value = session.messages || []
    docResult.value = normalizeDocResult(session.doc_result)
    applyBuilderModelSelection(session.selected_llm_config_id)
    genError.value = ''
    if (session.doc_result && !docResult.value) {
      genError.value = '该会话的历史设计文档数据异常，请点击“生成设计文档”重新生成。'
      const idx = sessions.value.findIndex(s => s.id === id)
      if (idx >= 0) {
        const session = sessions.value[idx]
        if (session) session.has_doc = false
      }
    }
    await scrollToBottom()
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || '未知错误'
    ElMessage.error(`加载会话失败：${detail}`)
  }
}

// ── Delete session ─────────────────────────────────────────────────────────
async function deleteSession(id: number) {
  await ElMessageBox.confirm('确定删除该会话吗？', '提示', { type: 'warning' })
  try {
    await requirementsApi.deleteSession(id)
    sessions.value = sessions.value.filter(s => s.id !== id)
    if (currentSessionId.value === id) {
      currentSessionId.value = null
      messages.value = []
      docResult.value = null
      selectedBuilderModelId.value = defaultBuilderModelId.value
      persistedBuilderModelId.value = null
    }
    ElMessage.success('已删除')
  } catch {
    ElMessage.error('删除失败')
  }
}

// ── Handle file select ─────────────────────────────────────────────────────
function setUploadedFile(file: File) {
  uploadedFile.value = file
  uploadedFilePreview.value = ''
  if (file.type.startsWith('image/')) {
    const reader = new FileReader()
    reader.onload = (ev) => { uploadedFilePreview.value = ev.target?.result as string }
    reader.readAsDataURL(file)
  }
}

async function handleFileSelect(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  target.value = ''
  setUploadedFile(file)
  // 选文件后自动发送，无需手动点击
  if (!currentSessionId.value) await createSession()
  await nextTick()
  await sendMessage()
}

function clearUploadedFile() {
  uploadedFile.value = null
  uploadedFilePreview.value = ''
}

// ── Handle paste (支持粘贴截图) ─────────────────────────────────────────────
async function handlePaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items) return
  for (const item of Array.from(items)) {
    if (item.kind === 'file' && item.type.startsWith('image/')) {
      e.preventDefault()
      const file = item.getAsFile()
      if (file) {
        // 生成带时间戳的文件名
        const ext = item.type.split('/')[1] || 'png'
        const namedFile = new File([file], `screenshot-${Date.now()}.${ext}`, { type: item.type })
        setUploadedFile(namedFile)
        // 粘贴截图：若输入框无文字则自动发送
        if (!inputText.value.trim()) {
          if (!currentSessionId.value) await createSession()
          await nextTick()
          await sendMessage()
        }
      }
      break
    }
  }
}

// ── Send message ─────────────────────────────────────────────────────────
// Returns true if AI responded with content, false on error/empty
async function sendMessage(): Promise<boolean> {
  if (chatStreaming.value) return false
  const text = inputText.value.trim()
  const file = uploadedFile.value
  if (!text && !file) return false
  if (!currentSessionId.value) return false

  // 乐观更新：添加用户消息
  const displayText = text || `已上传文件：${file?.name}`
  messages.value.push({ role: 'user', content: displayText })
  inputText.value = ''
  clearUploadedFile()
  autoResizeInput()
  await scrollToBottom()

  const token = localStorage.getItem('token') || ''
  chatStreaming.value = true
  streamingText.value = ''

  try {
    let url: string
    let body: BodyInit

    if (file) {
      // 含文件的消息
      const fd = new FormData()
      fd.append('file', file)
      if (text) fd.append('message', text)
      url = requirementsApi.chatWithFileUrl(currentSessionId.value)
      body = fd
    } else {
      // 纯文字消息
      url = requirementsApi.chatUrl(currentSessionId.value)
      body = JSON.stringify({ message: text })
    }

    const response = await fetch(url, {
      method: 'POST',
      headers: file
        ? { Authorization: `Bearer ${token}` }
        : { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body
    })

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (reader) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('event:')) {
          // event line
        } else if (line.startsWith('data:')) {
          const dataStr = line.slice(5).trim()
          if (!dataStr) continue
          try {
            const data = JSON.parse(dataStr)
            if (data.content) {
              streamingText.value += data.content
              await scrollToBottom()
            }
            if ('content' in data && !data.content) {
              // done event
            }
          } catch { /* ignore */ }
        }
      }
    }

    // 保存 AI 消息到本地（去掉 think 标签）
    const cleanedText = stripThink(streamingText.value)
    if (cleanedText) {
      messages.value.push({ role: 'assistant', content: cleanedText })
    } else if (streamingText.value) {
      // 只有思考内容没有实际回复，仍然保存原始内容（renderMarkdown 会处理显示）
      messages.value.push({ role: 'assistant', content: streamingText.value })
    }

    // 更新会话列表的更新时间
    const idx = sessions.value.findIndex(s => s.id === currentSessionId.value)
    if (idx >= 0) {
      const session = sessions.value[idx]
      if (!session) return !!streamingText.value
      session.updated_at = new Date().toISOString()
      // 更新标题（首条消息）
      if (messages.value.filter(m => m.role === 'user').length === 1) {
        session.title = displayText.slice(0, 30)
      }
    }
    return !!streamingText.value  // true = AI responded successfully
  } catch (e: any) {
    ElMessage.error('发送失败：' + (e.message || '未知错误'))
    return false
  } finally {
    chatStreaming.value = false
    streamingText.value = ''
    await scrollToBottom()
  }
}

// ── Generate design doc ────────────────────────────────────────────────────
async function handleGenerateDoc() {
  if (!currentSessionId.value || generating.value) return
  generating.value = true
  genProgress.value = 5
  genStep.value = '准备分析...'
  genError.value = ''

  genTimer = setInterval(() => {
    if (genProgress.value < 95) {
      // 80% 前快速推进，80-95% 极慢爬行，避免卡住感
      const step = genProgress.value < 80 ? Math.random() * 4 : Math.random() * 0.3
      genProgress.value = Math.min(genProgress.value + step, 95)
      if (genProgress.value > 20 && genProgress.value < 45) genStep.value = '分析对话内容...'
      else if (genProgress.value >= 45 && genProgress.value < 65) genStep.value = '提取业务结构...'
      else if (genProgress.value >= 65 && genProgress.value < 85) genStep.value = '生成设计文档...'
      else if (genProgress.value >= 85) genStep.value = 'AI 正在输出，请稍候...'
    }
  }, 400)

  const token = localStorage.getItem('token') || ''
  const url = requirementsApi.generateDocUrl(currentSessionId.value)

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json'
      }
    })

    if (!response.ok) {
      const errText = await response.text()
      throw new Error(`HTTP ${response.status}: ${errText}`)
    }

    const reader = response.body?.getReader()
    if (!reader) throw new Error('无法读取响应流')
    const decoder = new TextDecoder()
    let buffer = ''
    let currentEvent = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          const dataStr = line.slice(5).trim()
          if (!dataStr) continue
          try {
            const data = JSON.parse(dataStr)
            if (currentEvent === 'error' || data.message) {
              throw new Error(data.message || '生成失败')
            }
            if (data.doc_result) {
              docResult.value = data.doc_result
              const idx = sessions.value.findIndex(s => s.id === currentSessionId.value)
              if (idx >= 0) {
                const session = sessions.value[idx]
                if (session) session.has_doc = true
              }
            }
          } catch (parseErr: any) {
            if (parseErr.message !== 'Unexpected token') {
              throw parseErr
            }
          }
        }
      }
    }

    if (docResult.value) {
      genProgress.value = 100
      genStep.value = '生成完成！'
      ElMessage.success('设计文档生成成功！')
    } else {
      genError.value = '未能解析设计文档，请重试'
    }
  } catch (e: any) {
    genError.value = '生成失败：' + (e.message || '未知错误')
  } finally {
    if (genTimer) { clearInterval(genTimer); genTimer = null }
    generating.value = false
  }
}

// ── Confirm → export MD → go to ChatPage ──────────────────────────────────
async function handleConfirm() {
  if (!docResult.value) return
  confirming.value = true
  try {
    const { markdown } = await requirementsApi.exportMd(docResult.value)
    const appName = docResult.value.app_info.name || 'design'
    previewStore.pendingMarkdown = {
      filename: `${appName}.md`,
      content: markdown,
    }
    await router.push('/chat')
  } catch (e: any) {
    ElMessage.error('进入搭建失败：' + (e?.message || '未知错误'))
  } finally {
    confirming.value = false
  }
}

// ── User menu ──────────────────────────────────────────────────────────────
function handleUserCommand(cmd: string) {
  if (cmd === 'logout') {
    userStore.logout()
    router.push('/login')
  }
}

// ── 流式结束后自动补发滞留文件（粘贴图片时 AI 正在回复导致的滞留）──────────────
watch(chatStreaming, async (streaming) => {
  if (!streaming && uploadedFile.value) {
    await nextTick()
    await sendMessage()
  }
})

// ── Lifecycle ──────────────────────────────────────────────────────────────
onMounted(async () => {
  await loadBuilderModelOptions()
  await loadSessions()

  const prompt = route.query.prompt as string
  const hasFile = previewStore.pendingFile

  if (prompt || hasFile) {
    // 自动新建会话并发送第一条消息
    await createSession()

    if (hasFile) {
      uploadedFile.value = hasFile
      previewStore.pendingFile = null
    }

    if (prompt) {
      inputText.value = prompt
    }

    // 自动发送消息（不自动生成设计文档，由用户手动点击）
    await nextTick()
    await sendMessage()
  } else if (sessions.value.length > 0) {
    // 加载最近的会话
    const latestSession = sessions.value[0]
    if (latestSession) {
      await loadSession(latestSession.id)
    }
  }
})
</script>

<style scoped>
.req-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg-primary, #f8f9fa);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

/* ── Nav ── */
.nav-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  height: 56px;
  background: var(--bg-secondary, #fff);
  border-bottom: 1px solid var(--border-color, #e5e7eb);
  flex-shrink: 0;
}
.nav-left, .nav-right { display: flex; align-items: center; gap: 12px; }
.back-btn {
  width: 32px; height: 32px;
  border: none; background: none; cursor: pointer;
  border-radius: 6px; display: flex; align-items: center; justify-content: center;
  color: var(--text-secondary, #6b7280);
  transition: background 0.15s;
}
.back-btn:hover { background: var(--bg-hover, #f3f4f6); }
.logo-box {
  width: 28px; height: 28px;
  background: linear-gradient(135deg, #6366f1, #818cf8);
  border-radius: 7px; color: #fff; font-weight: 700; font-size: 13px;
  display: flex; align-items: center; justify-content: center;
}
.logo-text { font-weight: 600; font-size: 15px; color: var(--text-primary, #111); }
.user-btn {
  display: flex; align-items: center; gap: 8px;
  border: none; background: none; cursor: pointer; padding: 4px 8px;
  border-radius: 6px; color: var(--text-secondary, #6b7280);
}
.user-avatar {
  width: 26px; height: 26px;
  background: linear-gradient(135deg, #6366f1, #818cf8);
  border-radius: 50%; color: #fff; font-size: 11px; font-weight: 600;
  display: flex; align-items: center; justify-content: center;
}

/* ── Main Layout ── */
.main-layout {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* ── Sidebar ── */
.sidebar {
  width: 240px;
  background: var(--bg-secondary, #fff);
  border-right: 1px solid var(--border-color, #e5e7eb);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}
.new-session-btn {
  margin: 12px;
  padding: 10px 16px;
  background: linear-gradient(135deg, #6366f1, #818cf8);
  color: #fff;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: opacity 0.15s;
}
.new-session-btn:hover { opacity: 0.9; }
.session-list { flex: 1; overflow-y: auto; padding: 4px 8px; }
.session-item {
  padding: 10px 10px;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: background 0.15s;
  position: relative;
}
.session-item:hover { background: var(--bg-hover, #f3f4f6); }
.session-item.active { background: var(--accent-light, #eef2ff); }
.session-info { flex: 1; overflow: hidden; }
.session-title {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary, #111);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.session-meta {
  display: block;
  font-size: 11px;
  color: var(--text-muted, #9ca3af);
  margin-top: 2px;
}
.session-badges { display: flex; gap: 4px; }
.delete-btn {
  width: 24px; height: 24px;
  border: none; background: none; cursor: pointer;
  border-radius: 4px; color: var(--text-muted, #9ca3af);
  display: flex; align-items: center; justify-content: center;
  opacity: 0;
  transition: opacity 0.15s;
}
.session-item:hover .delete-btn { opacity: 1; }
.delete-btn:hover { color: #ef4444; background: #fee2e2; }
.empty-sessions {
  text-align: center;
  color: var(--text-muted, #9ca3af);
  font-size: 13px;
  padding: 32px 0;
}

/* ── Chat Area ── */
.chat-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}
.welcome-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: var(--text-secondary, #6b7280);
}
.welcome-icon { font-size: 48px; }
.welcome-state h2 {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary, #111);
  margin: 0;
}
.welcome-state p { text-align: center; line-height: 1.6; margin: 0; }
.start-btn {
  padding: 10px 24px;
  background: linear-gradient(135deg, #6366f1, #818cf8);
  color: #fff;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
}

/* ── Messages ── */
.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.message {
  display: flex;
  gap: 10px;
  max-width: 100%;
}
.message.user { flex-direction: row-reverse; }
.message-avatar {
  width: 32px; height: 32px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 600;
  flex-shrink: 0;
}
.message.assistant .message-avatar {
  background: linear-gradient(135deg, #6366f1, #818cf8);
  color: #fff;
}
.message.user .message-avatar {
  background: var(--bg-tertiary, #e5e7eb);
  color: var(--text-secondary, #6b7280);
}
.message-bubble {
  max-width: 72%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
}
.message.assistant .message-bubble {
  background: var(--bg-secondary, #fff);
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 2px 12px 12px 12px;
}
.message.user .message-bubble {
  background: linear-gradient(135deg, #6366f1, #818cf8);
  color: #fff;
  border-radius: 12px 2px 12px 12px;
}
.message-content :deep(strong) { font-weight: 600; }
.message-content :deep(code) {
  background: rgba(0,0,0,0.06); padding: 1px 4px; border-radius: 3px; font-size: 12px;
}
.message.user .message-content :deep(code) { background: rgba(255,255,255,0.2); }
.typing-cursor {
  display: inline-block;
  animation: blink 0.8s infinite;
  margin-left: 2px;
}
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
.thinking {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 12px 16px;
}
.dot {
  width: 6px; height: 6px;
  background: var(--text-muted, #9ca3af);
  border-radius: 50%;
  animation: bounce 1.2s infinite;
}
.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes bounce { 0%, 60%, 100% { transform: translateY(0); } 30% { transform: translateY(-6px); } }

/* ── Input Area ── */
.input-area {
  padding: 12px 20px 16px;
  border-top: 1px solid var(--border-color, #e5e7eb);
  background: var(--bg-secondary, #fff);
  flex-shrink: 0;
}
.model-picker-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  padding: 8px 12px;
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 12px;
  background: var(--bg-primary, #f8f9fa);
}
.model-picker-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.model-picker-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary, #111);
}
.model-picker-hint {
  font-size: 12px;
  color: var(--text-muted, #9ca3af);
}
.model-picker-select {
  width: min(460px, 60%);
  flex-shrink: 0;
}
.model-picker-select :deep(.el-select__wrapper) {
  min-height: 38px;
  border-radius: 12px;
  background: var(--bg-secondary, #fff);
  box-shadow: inset 0 0 0 1px rgba(99, 102, 241, 0.12);
}
.model-picker-select :deep(.el-select__selected-item),
.model-picker-select :deep(.el-select__placeholder) {
  color: var(--t-text-primary, #111);
}
.model-picker-select :deep(.el-select__caret),
.model-picker-select :deep(.el-select__suffix) {
  color: var(--t-text-muted, #9ca3af);
}
.model-option-row {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 4px 0;
}
.model-option-name {
  color: var(--text-primary, #111);
}
.model-option-meta {
  font-size: 12px;
  color: var(--text-muted, #9ca3af);
}
.file-badge-img {
  height: 40px;
  max-width: 80px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid #c7d2fe;
}
.file-badge {
  display: flex; align-items: center; gap: 6px;
  background: var(--accent-light, #eef2ff);
  border: 1px solid #c7d2fe;
  border-radius: 6px;
  padding: 4px 10px;
  margin-bottom: 8px;
  font-size: 12px;
  color: #6366f1;
}
.file-badge button {
  border: none; background: none; cursor: pointer; color: #6366f1;
  display: flex; align-items: center;
}
.file-msg-badge {
  display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
  font-size: 13px; color: #fff;
}
.file-msg-badge .el-icon { font-size: 15px; flex-shrink: 0; }
.file-msg-text { display: block; width: 100%; font-size: 12px; opacity: 0.85; margin-top: 2px; }
.input-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  background: var(--bg-primary, #f8f9fa);
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 12px;
  padding: 6px 10px;
}
.upload-label {
  cursor: pointer;
  color: var(--text-muted, #9ca3af);
  display: flex; align-items: center;
  padding: 4px;
  border-radius: 6px;
  transition: color 0.15s;
  flex-shrink: 0;
}
.upload-label:hover { color: #6366f1; }
.input-row textarea {
  flex: 1;
  border: none;
  background: transparent;
  resize: none;
  outline: none;
  font-size: 14px;
  line-height: 1.5;
  color: var(--text-primary, #111);
  min-height: 24px;
  max-height: 160px;
  overflow-y: auto;
  padding: 2px 0;
}
.input-row textarea::placeholder { color: var(--text-muted, #9ca3af); }
.send-btn {
  width: 34px; height: 34px;
  background: linear-gradient(135deg, #6366f1, #818cf8);
  border: none; border-radius: 8px;
  color: #fff; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  transition: opacity 0.15s;
}
.send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.action-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
}
@media (max-width: 900px) {
  .model-picker-row {
    flex-direction: column;
    align-items: stretch;
  }
  .model-picker-select {
    width: 100%;
  }
}
.gen-doc-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px;
  background: var(--bg-primary, #f8f9fa);
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  color: var(--text-primary, #111);
  transition: all 0.15s;
}
.gen-doc-btn:hover:not(:disabled) {
  border-color: #6366f1;
  color: #6366f1;
  background: #eef2ff;
}
.gen-doc-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.hint { font-size: 12px; color: var(--text-muted, #9ca3af); }

/* ── Doc Panel ── */
.doc-panel {
  width: 0;
  overflow: hidden;
  transition: width 0.3s ease;
  background: var(--bg-secondary, #fff);
  border-left: 1px solid var(--border-color, #e5e7eb);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}
.doc-panel.visible { width: 380px; }
.doc-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border-color, #e5e7eb);
  flex-shrink: 0;
}
.doc-header h3 { margin: 0; font-size: 15px; font-weight: 600; }
.doc-content {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.doc-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-muted, #9ca3af);
  font-size: 13px;
  text-align: center;
  padding: 24px;
}
.doc-section {
  background: var(--bg-primary, #f8f9fa);
  border-radius: 10px;
  padding: 12px 14px;
}
.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #111);
  margin-bottom: 10px;
}
.section-icon { font-size: 15px; }
.count-badge {
  background: #6366f1;
  color: #fff;
  border-radius: 9px;
  padding: 1px 7px;
  font-size: 11px;
  font-weight: 600;
}
.info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.info-item { display: flex; flex-direction: column; gap: 2px; }
.info-item.full { grid-column: 1 / -1; }
.label { font-size: 11px; color: var(--text-muted, #9ca3af); }
.value { font-size: 13px; font-weight: 500; color: var(--text-primary, #111); }
.tag-list { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.role-table { display: flex; flex-direction: column; gap: 6px; }
.role-row {
  display: grid;
  grid-template-columns: 100px 80px 1fr;
  gap: 8px;
  font-size: 12px;
  align-items: baseline;
}
.role-code { color: #6366f1; font-family: monospace; }
.role-name { font-weight: 500; color: var(--text-primary, #111); }
.role-desc { color: var(--text-secondary, #6b7280); }
.dict-list { display: flex; flex-direction: column; gap: 8px; }
.dict-item { background: var(--bg-secondary, #fff); border-radius: 6px; padding: 8px; }
.dict-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.dict-name { font-size: 12px; font-weight: 600; color: var(--text-primary, #111); }
.dict-code { font-size: 11px; color: var(--text-muted, #9ca3af); font-family: monospace; }
.dict-items { display: flex; flex-wrap: wrap; gap: 4px; }
.table-list { display: flex; flex-direction: column; gap: 8px; }
.table-item { background: var(--bg-secondary, #fff); border-radius: 6px; padding: 8px; }
.table-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.table-name { font-size: 13px; font-weight: 600; color: var(--text-primary, #111); }
.table-code { font-size: 11px; color: var(--text-muted, #9ca3af); font-family: monospace; margin-left: auto; }
.table-desc { font-size: 12px; color: var(--text-secondary, #6b7280); margin-bottom: 6px; }
.field-list { display: flex; flex-wrap: wrap; gap: 4px; }
.field-chip {
  background: var(--bg-primary, #f8f9fa);
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 4px;
  padding: 1px 7px;
  font-size: 11px;
  color: var(--text-secondary, #6b7280);
}
/* ── Permission Matrix ── */
.sync-matrix-btn {
  margin-left: 8px;
  background: transparent;
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  color: var(--text-secondary, #6b7280);
  cursor: pointer;
}
.sync-matrix-btn:hover { border-color: var(--el-color-primary, #409eff); color: var(--el-color-primary, #409eff); }
.matrix-wrap { overflow-x: auto; }
.matrix-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.matrix-table th,
.matrix-table td { padding: 8px 10px; border: 1px solid var(--border-color, #e5e7eb); vertical-align: top; }
.matrix-table th { background: var(--bg-secondary, #f9fafb); font-weight: 600; text-align: center; font-size: 11px; white-space: nowrap; }
.matrix-table th:first-child { text-align: left; }
.matrix-table-code { font-size: 10px; color: var(--text-secondary, #9ca3af); font-family: monospace; margin-top: 2px; }
.matrix-cell { display: flex; flex-direction: column; gap: 6px; min-width: 160px; }
.matrix-ops-row { display: flex; flex-wrap: wrap; gap: 3px; }
.matrix-op {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  border: 1px solid var(--border-color, #e5e7eb);
  cursor: pointer;
  user-select: none;
  color: var(--text-secondary, #6b7280);
  background: transparent;
  transition: all .1s;
}
.matrix-op:hover { border-color: var(--el-color-primary, #409eff); color: var(--el-color-primary, #409eff); }
.matrix-op.checked { background: var(--el-color-primary, #409eff); color: #fff; border-color: var(--el-color-primary, #409eff); }
.data-scope-wrap { display: flex; align-items: center; gap: 4px; padding-top: 4px; border-top: 1px dashed var(--border-color, #e5e7eb); }
.data-scope-label { font-size: 11px; color: var(--text-secondary, #9ca3af); }
.col-all-employee { background: var(--bg-tertiary, #f3f4f6); }
:root.dark .col-all-employee { background: #1a1d27; }
.data-scope-select {
  flex: 1;
  background: var(--bg-secondary, #f9fafb);
  color: var(--text-primary, #111827);
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 4px;
  padding: 2px 4px;
  font-size: 11px;
  color: var(--text-primary, #374151);
  outline: none;
  cursor: pointer;
}
.data-scope-select:focus { border-color: var(--el-color-primary, #409eff); }
.doc-skeleton { padding: 16px; }

/* ── Progress & Error ── */
.doc-progress {
  padding: 20px 16px 12px;
}
.gen-step-text {
  font-size: 12px;
  color: var(--text-secondary, #6b7280);
  margin-bottom: 8px;
  text-align: center;
}
.gen-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  margin: 12px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  font-size: 13px;
  color: #dc2626;
}
:root.dark .gen-error { background: #2d1515; border-color: #7f1d1d; color: #f87171; }

/* ── Edit mode inputs ── */
.edit-input {
  border: 1px solid #6366f1;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 13px;
  color: var(--text-primary, #111);
  background: var(--bg-primary, #fff);
  outline: none;
  width: 100%;
}
.edit-textarea {
  border: 1px solid #6366f1;
  border-radius: 4px;
  padding: 4px 6px;
  font-size: 13px;
  color: var(--text-primary, #111);
  background: var(--bg-primary, #fff);
  outline: none;
  width: 100%;
  resize: vertical;
  font-family: inherit;
}
.edit-input:focus, .edit-textarea:focus { border-color: #818cf8; box-shadow: 0 0 0 2px rgba(99,102,241,0.15); }

/* ── Edit controls for dict/fields ── */
.edit-input-sm {
  border: 1px solid #6366f1;
  border-radius: 4px;
  padding: 2px 5px;
  font-size: 12px;
  color: var(--text-primary, #111);
  background: var(--bg-primary, #fff);
  outline: none;
  flex: 1;
  min-width: 60px;
}
.edit-input-sm:focus { border-color: #818cf8; }
.dict-items-edit { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
.dict-item-row, .field-edit-row {
  display: flex; align-items: center; gap: 6px;
}
.del-item-btn {
  background: none; border: none; cursor: pointer;
  color: #9ca3af; font-size: 14px; padding: 0 4px;
  border-radius: 4px; line-height: 1;
  transition: color 0.15s;
}
.del-item-btn:hover { color: #ef4444; }
.add-item-btn {
  margin-top: 4px;
  background: none; border: 1px dashed #6366f1;
  color: #6366f1; font-size: 11px; padding: 3px 8px;
  border-radius: 4px; cursor: pointer;
  transition: background 0.15s;
  width: fit-content;
}
.add-item-btn:hover { background: rgba(99,102,241,0.08); }
.fields-edit { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }

/* ── Fullscreen dialog ── */
.doc-fullscreen-dialog .doc-content-full {
  max-width: 900px;
  margin: 0 auto;
  padding: 0 0 40px;
}

/* ── Dark mode ── */
:root.dark .req-page { --bg-primary: #0f1117; --bg-secondary: #1a1d27; --bg-hover: #1f2233; --bg-tertiary: #252836; --border-color: #2d3148; --text-primary: #f0f1f5; --text-secondary: #9ca3af; --text-muted: #6b7280; --accent-light: #1e2040; }
:root.dark .edit-input, :root.dark .edit-textarea { background: #1a1d27; color: #f0f1f5; }
:root.dark .data-scope-select { background: #252836; color: #f0f1f5; border-color: #2d3148; }

/* ── Modules ── */
.module-list { display: flex; flex-direction: column; gap: 12px; }
.module-item { border: 1px solid var(--border-color, #e5e7eb); border-radius: 8px; overflow: hidden; }
.module-header { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: var(--bg-secondary, #f9fafb); }
.module-name { font-weight: 600; font-size: 13px; color: var(--text-primary, #111827); }
.module-code { font-size: 11px; color: var(--text-secondary, #9ca3af); font-family: monospace; }
.module-desc { padding: 6px 12px; font-size: 12px; color: var(--text-secondary, #6b7280); border-bottom: 1px solid var(--border-color, #e5e7eb); }
.feature-list { padding: 6px 0; }
.feature-row { display: flex; align-items: flex-start; gap: 8px; padding: 5px 12px; border-bottom: 1px solid var(--border-color, #f3f4f6); }
.feature-row:last-child { border-bottom: none; }
.feature-name { font-size: 12px; font-weight: 500; color: var(--text-primary, #374151); white-space: nowrap; min-width: 110px; }
.feature-desc { font-size: 11px; color: var(--text-secondary, #6b7280); flex: 1; }
.feature-roles { display: flex; flex-wrap: wrap; gap: 3px; min-width: 80px; }

/* ── Flows ── */
.flow-list { display: flex; flex-direction: column; gap: 12px; }
.flow-item { border: 1px solid var(--border-color, #e5e7eb); border-radius: 8px; overflow: hidden; }
.flow-header { padding: 8px 12px; background: var(--bg-secondary, #f9fafb); }
.flow-name { font-weight: 600; font-size: 13px; color: var(--text-primary, #111827); }
.flow-desc { padding: 6px 12px; font-size: 12px; color: var(--text-secondary, #6b7280); border-bottom: 1px solid var(--border-color, #e5e7eb); }
.flow-steps { padding: 8px 12px; display: flex; flex-direction: column; gap: 4px; }
.flow-step { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.step-num { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; background: var(--el-color-primary, #6366f1); color: #fff; border-radius: 50%; font-size: 11px; flex-shrink: 0; }
.step-action { color: var(--text-primary, #374151); flex: 1; }
.step-role { color: var(--el-color-primary, #6366f1); font-size: 11px; padding: 1px 6px; border: 1px solid var(--el-color-primary, #6366f1); border-radius: 10px; white-space: nowrap; }
.step-status { color: var(--text-secondary, #9ca3af); font-size: 11px; white-space: nowrap; }
</style>
