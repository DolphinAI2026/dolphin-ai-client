<template>
  <div class="req-page">
    <div class="main-layout">
      <!-- 左侧 Sidebar（Claude 风格） -->
      <aside class="sidebar">
        <div class="sidebar-top">
          <button class="back-btn" @click="router.push('/')" title="返回首页">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M10 12L6 8l4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
          <button class="new-session-btn" @click="createSession">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
            新建分析
          </button>
        </div>

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
            <div class="session-actions">
              <span v-if="s.has_doc" class="doc-dot" title="已生成文档" @click.stop="loadSession(s.id, true); docFullscreen = true"></span>
              <button class="del-btn" @click.stop="deleteSession(s.id)" title="删除">
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
              </button>
            </div>
          </div>
          <div v-if="sessions.length === 0" class="empty-sessions">
            暂无历史记录
          </div>
        </div>

        <div class="sidebar-bottom">
          <ThemeToggle />
          <el-dropdown @command="handleUserCommand" trigger="click">
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
      </aside>

      <!-- 中间：对话区域 -->
      <div class="chat-area">
        <!-- 无会话时的引导（Claude 风格欢迎页） -->
        <div v-if="!currentSessionId" class="welcome-state">
          <div class="welcome-content">
            <div class="welcome-logo">
              <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
                <rect width="40" height="40" rx="10" fill="currentColor" opacity="0.1"/>
                <path d="M12 20h16M20 12v16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </div>
            <h1 class="welcome-title">需求分析</h1>
            <p class="welcome-desc">与 AI 对话，逐步梳理您的业务需求</p>
            <div class="suggestion-cards">
              <button class="suggestion-card" @click="startWithPrompt('我想搭建一个')">
                <span class="card-icon">💡</span>
                <span class="card-text">描述一个业务系统</span>
              </button>
              <button class="suggestion-card" @click="triggerFileUpload">
                <span class="card-icon">📄</span>
                <span class="card-text">上传需求文档</span>
              </button>
              <button class="suggestion-card" @click="startWithPrompt('帮我分析一下以下需求：')">
                <span class="card-icon">🔍</span>
                <span class="card-text">分析已有需求</span>
              </button>
            </div>
          </div>
        </div>

        <!-- 对话内容 -->
        <template v-else>
          <div class="messages-scroll" ref="messagesContainer">
            <div class="messages-inner">
              <div
                v-for="(msg, idx) in displayMessages"
                :key="idx"
                class="message"
                :class="msg.role"
              >
                <div class="msg-icon" v-if="msg.role === 'assistant'">
                  <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                    <rect width="18" height="18" rx="4" fill="var(--c-brand)" opacity="0.15"/>
                    <path d="M5.5 9h7M9 5.5v7" stroke="var(--c-brand)" stroke-width="1.5" stroke-linecap="round"/>
                  </svg>
                </div>
                <div class="msg-body">
                  <div v-if="msg.role === 'user' && isFileMessage(msg.content)" class="file-msg">
                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M9 1H4a1 1 0 00-1 1v12a1 1 0 001 1h8a1 1 0 001-1V5L9 1z" stroke="currentColor" stroke-width="1.2"/><path d="M9 1v4h4" stroke="currentColor" stroke-width="1.2"/></svg>
                    <span>{{ extractFileName(msg.content) }}</span>
                    <span v-if="extractUserText(msg.content)" class="file-text">{{ extractUserText(msg.content) }}</span>
                  </div>
                  <div v-else class="msg-content" v-html="renderMarkdown(msg.content || '')"></div>
                </div>
              </div>

              <!-- 流式打字中 -->
              <div v-if="chatStreaming && displayStreamingText" class="message assistant">
                <div class="msg-icon">
                  <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                    <rect width="18" height="18" rx="4" fill="var(--c-brand)" opacity="0.15"/>
                    <path d="M5.5 9h7M9 5.5v7" stroke="var(--c-brand)" stroke-width="1.5" stroke-linecap="round"/>
                  </svg>
                </div>
                <div class="msg-body">
                  <div class="msg-content" v-html="renderMarkdown(displayStreamingText)"></div>
                  <span class="typing-cursor"></span>
                </div>
              </div>
              <div v-if="chatStreaming && !displayStreamingText" class="message assistant">
                <div class="msg-icon">
                  <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                    <rect width="18" height="18" rx="4" fill="var(--c-brand)" opacity="0.15"/>
                    <path d="M5.5 9h7M9 5.5v7" stroke="var(--c-brand)" stroke-width="1.5" stroke-linecap="round"/>
                  </svg>
                </div>
                <div class="msg-body thinking-dots">
                  <span class="dot"></span><span class="dot"></span><span class="dot"></span>
                </div>
              </div>
            </div>
          </div>

          <!-- 输入区域（Claude 风格） -->
          <div class="input-wrapper">
            <div class="input-card">
              <!-- 已上传文件提示 -->
              <div v-if="uploadedFile" class="file-badge">
                <template v-if="uploadedFilePreview">
                  <img :src="uploadedFilePreview" class="file-thumb" />
                </template>
                <template v-else>
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M9 1H4a1 1 0 00-1 1v12a1 1 0 001 1h8a1 1 0 001-1V5L9 1z" stroke="currentColor" stroke-width="1.2"/><path d="M9 1v4h4" stroke="currentColor" stroke-width="1.2"/></svg>
                </template>
                <span class="file-name">{{ uploadedFile.name }}</span>
                <button class="file-remove" @click="clearUploadedFile">
                  <svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
                </button>
              </div>

              <div class="input-row">
                <label class="attach-btn" title="上传需求文档">
                  <input
                    type="file"
                    accept=".md,.pdf,.docx,.doc,.txt,.markdown,.png,.jpg,.jpeg,.gif,.webp"
                    @change="handleFileSelect"
                    ref="fileInputRef"
                    hidden
                  />
                  <svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M15.5 8.5l-6.4 6.4a3.5 3.5 0 01-5-5l6.4-6.4a2.2 2.2 0 013.1 3.1L7.2 13a.9.9 0 01-1.3-1.3l5.5-5.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
                </label>
                <textarea
                  v-model="inputText"
                  placeholder="描述您的业务需求..."
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
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M14 2L7 9M14 2l-4.5 12-2-5.5L2 6.5 14 2z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>
                </button>
              </div>

              <div class="input-footer">
                <button
                  class="gen-doc-btn"
                  @click="handleGenerateDoc"
                  :disabled="generating || messages.length < 2"
                >
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M13.5 7.5L8 2 2.5 7.5M8 2v11" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
                  {{ generating ? '生成中...' : (docResult ? '更新文档' : '生成设计文档') }}
                </button>
                <span v-if="messages.length < 2" class="input-hint">先开始对话，再生成设计文档</span>

                <div class="model-selector">
                  <el-select
                    v-model="selectedBuilderModelId"
                    popper-class="model-select-dropdown"
                    size="small"
                    placeholder="模型"
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
                      <div class="model-opt">
                        <span class="model-opt-name">{{ option.config_name }}</span>
                        <span class="model-opt-meta">{{ option.provider }} / {{ option.model }}</span>
                      </div>
                    </el-option>
                  </el-select>
                </div>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- 生成进度浮层 -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="generating" class="gen-overlay">
          <div class="gen-card">
            <div class="gen-spinner"></div>
            <div class="gen-step">{{ genStep }}</div>
            <el-progress :percentage="Math.round(genProgress)" :striped="true" :striped-flow="true" :duration="5" status="" style="width:240px" />
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 全屏文档对话框 -->
    <el-dialog v-model="docFullscreen" fullscreen title="功能设计文档" class="doc-fullscreen-dialog">
      <template #header>
        <div class="doc-dialog-header">
          <span class="doc-dialog-title">功能设计文档</span>
          <div class="doc-dialog-actions">
            <el-button size="small" @click="editMode = !editMode" :type="editMode ? 'warning' : ''">
              {{ editMode ? '完成编辑' : '编辑' }}
            </el-button>
            <el-button size="small" @click="handleGenerateDoc" :loading="generating">
              <el-icon><Refresh /></el-icon> 根据对话更新
            </el-button>
          </div>
        </div>
      </template>

      <!-- 错误提示 -->
      <div v-if="genError && !generating" class="gen-error">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.3"/><path d="M8 5v3M8 10v.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        <span>{{ genError }}</span>
        <el-button size="small" text type="primary" @click="handleGenerateDoc">重试</el-button>
      </div>

      <div v-if="docResult" class="doc-content doc-content-full">
        <!-- 应用信息 -->
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

      <div v-else-if="!generating && !genError" class="doc-empty-state">
        <p>暂无文档内容，请先通过对话生成设计文档</p>
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
import { handleError } from '@/utils/errorHandler'
import { useUserStore } from '@/stores/user'
import { usePreviewStore } from '@/stores/preview'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { requirementsApi, type RequirementsSession, type ChatMessage, type AnalysisResult } from '@/api/requirements'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'
import {
  normalizeDocResult as _normalizeDocResult,
  formatBuilderModelOption,
  isFileMessage,
  extractFileName,
  extractUserText,
  stripThink,
  renderMarkdown,
  formatDate,
} from '@/utils/requirements'

const normalizeDocResult = (raw: any): AnalysisResult | null =>
  _normalizeDocResult<AnalysisResult & { [k: string]: unknown }>(raw) as AnalysisResult | null

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
const uploadedFilePreview = ref<string>('')
const chatStreaming = ref(false)
const streamingText = ref('')

const displayMessages = computed(() =>
  messages.value.filter(msg => {
    if (msg.role !== 'assistant') return true
    const content = msg.content || ''
    const cleaned = stripThink(content)
    return cleaned.length > 0
  })
)

const displayStreamingText = computed(() => {
  let text = streamingText.value
  text = text.replace(/<think>[\s\S]*?<\/think>/g, '')
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
    handleError(e, { fallback: '切换模型失败' })
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

function autoResizeInput() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

async function scrollToBottom() {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

// ── Welcome 快捷方法 ──────────────────────────────────────────────────────
async function startWithPrompt(prompt: string) {
  await createSession()
  inputText.value = prompt
  await nextTick()
  inputRef.value?.focus()
}

function triggerFileUpload() {
  createSession().then(() => {
    nextTick(() => fileInputRef.value?.click())
  })
}

// ── Load sessions list ─────────────────────────────────────────────────────
async function loadSessions() {
  try {
    sessions.value = await requirementsApi.listSessions()
  } catch {
    // ignore
  }
}

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
      genError.value = '该会话的历史设计文档数据异常，请点击"生成设计文档"重新生成。'
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
  if (!currentSessionId.value) await createSession()
  await nextTick()
  await sendMessage()
}

function clearUploadedFile() {
  uploadedFile.value = null
  uploadedFilePreview.value = ''
}

async function handlePaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items) return
  for (const item of Array.from(items)) {
    if (item.kind === 'file' && item.type.startsWith('image/')) {
      e.preventDefault()
      const file = item.getAsFile()
      if (file) {
        const ext = item.type.split('/')[1] || 'png'
        const namedFile = new File([file], `screenshot-${Date.now()}.${ext}`, { type: item.type })
        setUploadedFile(namedFile)
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

async function sendMessage(): Promise<boolean> {
  if (chatStreaming.value) return false
  const text = inputText.value.trim()
  const file = uploadedFile.value
  if (!text && !file) return false
  if (!currentSessionId.value) return false

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
      const fd = new FormData()
      fd.append('file', file)
      if (text) fd.append('message', text)
      url = requirementsApi.chatWithFileUrl(currentSessionId.value)
      body = fd
    } else {
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

    const cleanedText = stripThink(streamingText.value)
    if (cleanedText) {
      messages.value.push({ role: 'assistant', content: cleanedText })
    } else if (streamingText.value) {
      messages.value.push({ role: 'assistant', content: streamingText.value })
    }

    const idx = sessions.value.findIndex(s => s.id === currentSessionId.value)
    if (idx >= 0) {
      const session = sessions.value[idx]
      if (!session) return !!streamingText.value
      session.updated_at = new Date().toISOString()
      if (messages.value.filter(m => m.role === 'user').length === 1) {
        session.title = displayText.slice(0, 30)
      }
    }
    return !!streamingText.value
  } catch (e: any) {
    ElMessage.error('发送失败：' + (e.message || '未知错误'))
    return false
  } finally {
    chatStreaming.value = false
    streamingText.value = ''
    await scrollToBottom()
  }
}

async function handleGenerateDoc() {
  if (!currentSessionId.value || generating.value) return
  generating.value = true
  genProgress.value = 5
  genStep.value = '准备分析...'
  genError.value = ''

  genTimer = setInterval(() => {
    if (genProgress.value < 95) {
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
    let validationPayload: any = null

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
            if (currentEvent === 'validation_required' || data.needs_user_input || data.validation?.needs_user_input) {
              validationPayload = data.validation || data
              continue
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

    if (validationPayload) {
      const message = validationPayload.assistant_message || '设计文档预检发现编码冲突，请先补充新的模型或字段编码。'
      genProgress.value = 100
      genStep.value = '等待补充编码'
      genError.value = message
      messages.value.push({ role: 'assistant', content: message })
      ElMessage.warning('需要先确认编码后再生成设计文档')
      await scrollToBottom()
      return
    }

    if (docResult.value) {
      genProgress.value = 100
      genStep.value = '生成完成！'
      ElMessage.success('设计文档生成成功！')
      // 自动打开全屏文档弹窗
      docFullscreen.value = true
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

function handleUserCommand(cmd: string) {
  if (cmd === 'logout') {
    userStore.logout()
    router.push('/login')
  }
}

watch(chatStreaming, async (streaming) => {
  if (!streaming && uploadedFile.value) {
    await nextTick()
    await sendMessage()
  }
})

onMounted(async () => {
  await loadBuilderModelOptions()
  await loadSessions()

  const prompt = route.query.prompt as string
  const hasFile = previewStore.pendingFile

  if (prompt || hasFile) {
    await createSession()

    if (hasFile) {
      uploadedFile.value = hasFile
      previewStore.pendingFile = null
    }

    if (prompt) {
      inputText.value = prompt
    }

    await nextTick()
    await sendMessage()
  } else if (sessions.value.length > 0) {
    const latestSession = sessions.value[0]
    if (latestSession) {
      await loadSession(latestSession.id)
    }
  }
})
</script>

<style scoped>
/* ═══════════════════════════════════════════════════════════════════════════
   Design tokens — aligned with project theme-vars.css (--t-* tokens)
   ═══════════════════════════════════════════════════════════════════════════ */
.req-page {
  --c-bg: var(--t-bg-base, #f4f5f7);
  --c-bg-sidebar: var(--t-bg-panel, #ffffff);
  --c-bg-card: var(--t-bg-elevated, #ffffff);
  --c-bg-user-msg: var(--t-bg-input, #f0f1f4);
  --c-bg-hover: var(--t-bg-panel-hover, #f0f1f4);
  --c-bg-active: var(--t-brand-subtle, rgba(99, 102, 241, 0.08));
  --c-text: var(--t-text-primary, #1a1a2e);
  --c-text-secondary: var(--t-text-secondary, #6b7280);
  --c-text-muted: var(--t-text-muted, #9ca3af);
  --c-border: var(--t-border-subtle, rgba(0, 0, 0, 0.06));
  --c-border-strong: var(--t-border-strong, rgba(0, 0, 0, 0.12));
  --c-brand: var(--t-brand, #6366f1);
  --c-brand-light: var(--t-brand-light, #818cf8);
  --c-brand-subtle: var(--t-brand-subtle, rgba(99, 102, 241, 0.08));

  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--c-bg);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  color: var(--c-text);
}

/* ── Layout ── */
.main-layout {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* ═══════════════════════════════════════════════════════════════════════════
   Sidebar (Claude style)
   ═══════════════════════════════════════════════════════════════════════════ */
.sidebar {
  width: 260px;
  background: var(--c-bg-sidebar);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  border-right: 1px solid var(--c-border);
}
.sidebar-top {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 12px 8px;
}
.back-btn {
  width: 34px;
  height: 34px;
  border: none;
  background: none;
  cursor: pointer;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--c-text-secondary);
  transition: all 0.15s;
  flex-shrink: 0;
}
.back-btn:hover {
  background: var(--c-bg-hover);
  color: var(--c-text);
}
.new-session-btn {
  flex: 1;
  padding: 8px 14px;
  background: var(--c-bg-card);
  color: var(--c-text);
  border: 1px solid var(--c-border);
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.15s;
}
.new-session-btn:hover {
  border-color: var(--c-border-strong);
  background: var(--c-bg-hover);
}

/* Session list */
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px;
}
.session-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: background 0.15s;
  position: relative;
}
.session-item:hover {
  background: var(--c-bg-hover);
}
.session-item.active {
  background: var(--c-bg-active);
}
.session-info {
  flex: 1;
  overflow: hidden;
}
.session-title {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--c-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.session-meta {
  display: block;
  font-size: 11px;
  color: var(--c-text-muted);
  margin-top: 2px;
}
.session-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}
.doc-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #10b981;
  cursor: pointer;
  flex-shrink: 0;
}
.del-btn {
  width: 24px;
  height: 24px;
  border: none;
  background: none;
  cursor: pointer;
  border-radius: 4px;
  color: var(--c-text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: all 0.15s;
}
.session-item:hover .del-btn {
  opacity: 1;
}
.del-btn:hover {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
}
.empty-sessions {
  text-align: center;
  color: var(--c-text-muted);
  font-size: 13px;
  padding: 32px 0;
}

/* Sidebar bottom */
.sidebar-bottom {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid var(--c-border);
}
.user-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  border: none;
  background: none;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 8px;
  color: var(--c-text);
  transition: background 0.15s;
  flex: 1;
  min-width: 0;
}
.user-btn:hover {
  background: var(--c-bg-hover);
}
.user-avatar {
  width: 28px;
  height: 28px;
  background: var(--c-brand);
  border-radius: 50%;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.user-name {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ═══════════════════════════════════════════════════════════════════════════
   Chat Area
   ═══════════════════════════════════════════════════════════════════════════ */
.chat-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
  background: var(--c-bg);
}

/* ── Welcome state ── */
.welcome-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.welcome-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  max-width: 480px;
  padding: 0 24px;
}
.welcome-logo {
  color: var(--c-brand);
  margin-bottom: 4px;
}
.welcome-title {
  font-size: 28px;
  font-weight: 600;
  color: var(--c-text);
  margin: 0;
  letter-spacing: -0.02em;
}
.welcome-desc {
  font-size: 15px;
  color: var(--c-text-secondary);
  margin: 0;
  text-align: center;
}
.suggestion-cards {
  display: flex;
  gap: 10px;
  margin-top: 12px;
  flex-wrap: wrap;
  justify-content: center;
}
.suggestion-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: var(--c-bg-card);
  border: 1px solid var(--c-border);
  border-radius: 12px;
  cursor: pointer;
  font-size: 13px;
  color: var(--c-text);
  transition: all 0.15s;
}
.suggestion-card:hover {
  border-color: var(--c-border-strong);
  background: var(--c-bg-hover);
  transform: translateY(-1px);
}
.card-icon {
  font-size: 16px;
}

/* ── Messages ── */
.messages-scroll {
  flex: 1;
  overflow-y: auto;
  scroll-behavior: smooth;
}
.messages-inner {
  max-width: 720px;
  margin: 0 auto;
  padding: 24px 24px 16px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.message {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
.message.user {
  flex-direction: row-reverse;
}
.msg-icon {
  flex-shrink: 0;
  margin-top: 2px;
}
.msg-body {
  max-width: 85%;
  font-size: 14.5px;
  line-height: 1.65;
}
.message.assistant .msg-body {
  color: var(--c-text);
}
.message.user .msg-body {
  background: var(--c-bg-user-msg);
  padding: 10px 16px;
  border-radius: 18px 4px 18px 18px;
  color: var(--c-text);
}
.msg-content :deep(strong) {
  font-weight: 600;
}
.msg-content :deep(code) {
  background: var(--c-brand-subtle);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 13px;
  font-family: 'SF Mono', Menlo, monospace;
}
.msg-content :deep(em) {
  font-style: italic;
}

/* File message */
.file-msg {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.file-text {
  display: block;
  width: 100%;
  font-size: 12px;
  opacity: 0.75;
  margin-top: 2px;
}

/* Typing */
.typing-cursor {
  display: inline-block;
  width: 2px;
  height: 16px;
  background: var(--c-brand);
  margin-left: 2px;
  vertical-align: text-bottom;
  animation: blink 0.8s infinite;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
.thinking-dots {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 0;
}
.dot {
  width: 6px;
  height: 6px;
  background: var(--c-text-muted);
  border-radius: 50%;
  animation: bounce 1.2s infinite;
}
.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes bounce {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-6px); }
}

/* ═══════════════════════════════════════════════════════════════════════════
   Input Area (Claude style)
   ═══════════════════════════════════════════════════════════════════════════ */
.input-wrapper {
  flex-shrink: 0;
  padding: 0 24px 20px;
  display: flex;
  justify-content: center;
}
.input-card {
  width: 100%;
  max-width: 720px;
  background: var(--c-bg-card);
  border: 1px solid var(--c-border);
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
}
.file-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--c-border);
  font-size: 12px;
  color: var(--c-text-secondary);
}
.file-thumb {
  height: 32px;
  max-width: 56px;
  object-fit: cover;
  border-radius: 4px;
}
.file-name {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.file-remove {
  border: none;
  background: none;
  cursor: pointer;
  color: var(--c-text-muted);
  display: flex;
  align-items: center;
  padding: 2px;
  border-radius: 4px;
}
.file-remove:hover {
  color: #ef4444;
}
.input-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 10px 14px;
}
.attach-btn {
  cursor: pointer;
  color: var(--c-text-muted);
  display: flex;
  align-items: center;
  padding: 4px;
  border-radius: 6px;
  transition: color 0.15s;
  flex-shrink: 0;
}
.attach-btn:hover {
  color: var(--c-text);
}
.input-row textarea {
  flex: 1;
  border: none;
  background: transparent;
  resize: none;
  outline: none;
  font-size: 14px;
  line-height: 1.5;
  color: var(--c-text);
  min-height: 22px;
  max-height: 160px;
  overflow-y: auto;
  padding: 2px 0;
  font-family: inherit;
}
.input-row textarea::placeholder {
  color: var(--c-text-muted);
}
.send-btn {
  width: 32px;
  height: 32px;
  background: var(--c-text);
  border: none;
  border-radius: 8px;
  color: var(--c-bg);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: opacity 0.15s;
}
.send-btn:disabled {
  opacity: 0.25;
  cursor: not-allowed;
}
.send-btn:not(:disabled):hover {
  opacity: 0.85;
}
.input-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 14px 10px;
  border-top: 1px solid var(--c-border);
}
.gen-doc-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  background: none;
  border: 1px solid var(--c-border);
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  color: var(--c-text-secondary);
  transition: all 0.15s;
}
.gen-doc-btn:hover:not(:disabled) {
  border-color: var(--c-brand);
  color: var(--c-brand);
}
.gen-doc-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.input-hint {
  font-size: 11px;
  color: var(--c-text-muted);
}
.model-selector {
  margin-left: auto;
}
.model-selector :deep(.el-select) {
  width: 140px;
}
.model-selector :deep(.el-select__wrapper) {
  min-height: 28px;
  border-radius: 8px;
  background: transparent;
  border: 1px solid var(--c-border);
  box-shadow: none;
  font-size: 12px;
}
.model-selector :deep(.el-select__wrapper:hover) {
  border-color: var(--c-border-strong);
}
.model-opt {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 2px 0;
}
.model-opt-name {
  font-size: 13px;
  color: var(--c-text);
}
.model-opt-meta {
  font-size: 11px;
  color: var(--c-text-muted);
}

/* ═══════════════════════════════════════════════════════════════════════════
   Generate overlay
   ═══════════════════════════════════════════════════════════════════════════ */
.gen-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}
.gen-card {
  background: var(--c-bg-card);
  border-radius: 16px;
  padding: 28px 32px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12);
}
.gen-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--c-border);
  border-top-color: var(--c-brand);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.gen-step {
  font-size: 13px;
  color: var(--c-text-secondary);
}
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.2s;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}

/* ═══════════════════════════════════════════════════════════════════════════
   Document fullscreen dialog (reuse existing, style tweaks)
   ═══════════════════════════════════════════════════════════════════════════ */
.doc-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-right: 40px;
}
.doc-dialog-title {
  font-size: 16px;
  font-weight: 600;
}
.doc-dialog-actions {
  display: flex;
  gap: 8px;
}
.gen-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  margin: 12px auto;
  max-width: 900px;
  background: rgba(239, 68, 68, 0.06);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 8px;
  font-size: 13px;
  color: #dc2626;
}
:root.dark .gen-error {
  background: rgba(239, 68, 68, 0.08);
  border-color: rgba(239, 68, 68, 0.25);
  color: #f87171;
}
.doc-empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  color: var(--c-text-muted);
  font-size: 14px;
}
.doc-content-full {
  max-width: 900px;
  margin: 0 auto;
  padding: 0 0 40px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.doc-section {
  background: var(--c-bg);
  border-radius: 12px;
  padding: 16px 18px;
}
.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--c-text);
  margin-bottom: 12px;
}
.section-icon { font-size: 16px; }
.count-badge {
  background: var(--c-brand);
  color: #fff;
  border-radius: 9px;
  padding: 1px 7px;
  font-size: 11px;
  font-weight: 600;
}
.info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.info-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.info-item.full { grid-column: 1 / -1; }
.label {
  font-size: 11px;
  color: var(--c-text-muted);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.value {
  font-size: 13px;
  font-weight: 500;
  color: var(--c-text);
}
.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.role-table {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.role-row {
  display: grid;
  grid-template-columns: 100px 80px 1fr;
  gap: 8px;
  font-size: 12px;
  align-items: baseline;
}
.role-code { color: var(--c-brand); font-family: 'SF Mono', Menlo, monospace; font-size: 12px; }
.role-name { font-weight: 500; color: var(--c-text); }
.role-desc { color: var(--c-text-secondary); }
.dict-list { display: flex; flex-direction: column; gap: 8px; }
.dict-item { background: var(--c-bg-card); border-radius: 8px; padding: 10px; }
.dict-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.dict-name { font-size: 13px; font-weight: 600; color: var(--c-text); }
.dict-code { font-size: 11px; color: var(--c-text-muted); font-family: 'SF Mono', Menlo, monospace; }
.dict-items { display: flex; flex-wrap: wrap; gap: 4px; }
.table-list { display: flex; flex-direction: column; gap: 10px; }
.table-item { background: var(--c-bg-card); border-radius: 8px; padding: 10px; }
.table-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.table-name { font-size: 13px; font-weight: 600; color: var(--c-text); }
.table-code { font-size: 11px; color: var(--c-text-muted); font-family: 'SF Mono', Menlo, monospace; margin-left: auto; }
.table-desc { font-size: 12px; color: var(--c-text-secondary); margin-bottom: 6px; }
.field-list { display: flex; flex-wrap: wrap; gap: 4px; }
.field-chip {
  background: var(--c-bg);
  border: 1px solid var(--c-border);
  border-radius: 4px;
  padding: 1px 7px;
  font-size: 11px;
  color: var(--c-text-secondary);
}

/* Permission matrix */
.sync-matrix-btn {
  margin-left: 8px;
  background: transparent;
  border: 1px solid var(--c-border);
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  color: var(--c-text-secondary);
  cursor: pointer;
}
.sync-matrix-btn:hover { border-color: var(--c-brand); color: var(--c-brand); }
.matrix-wrap { overflow-x: auto; }
.matrix-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.matrix-table th,
.matrix-table td { padding: 8px 10px; border: 1px solid var(--c-border); vertical-align: top; }
.matrix-table th { background: var(--c-bg-card); font-weight: 600; text-align: center; font-size: 11px; white-space: nowrap; }
.matrix-table th:first-child { text-align: left; }
.matrix-table-code { font-size: 10px; color: var(--c-text-muted); font-family: 'SF Mono', Menlo, monospace; margin-top: 2px; }
.matrix-cell { display: flex; flex-direction: column; gap: 6px; min-width: 160px; }
.matrix-ops-row { display: flex; flex-wrap: wrap; gap: 3px; }
.matrix-op {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  border: 1px solid var(--c-border);
  cursor: pointer;
  user-select: none;
  color: var(--c-text-secondary);
  background: transparent;
  transition: all .1s;
}
.matrix-op:hover { border-color: var(--c-brand); color: var(--c-brand); }
.matrix-op.checked { background: var(--c-brand); color: #fff; border-color: var(--c-brand); }
.data-scope-wrap { display: flex; align-items: center; gap: 4px; padding-top: 4px; border-top: 1px dashed var(--c-border); }
.data-scope-label { font-size: 11px; color: var(--c-text-muted); }
.col-all-employee { background: var(--c-bg-hover); }
.data-scope-select {
  flex: 1;
  background: var(--c-bg-card);
  color: var(--c-text);
  border: 1px solid var(--c-border);
  border-radius: 4px;
  padding: 2px 4px;
  font-size: 11px;
  outline: none;
  cursor: pointer;
}
.data-scope-select:focus { border-color: var(--c-brand); }

/* Edit mode inputs */
.edit-input {
  border: 1px solid var(--c-brand);
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 13px;
  color: var(--c-text);
  background: var(--c-bg-card);
  outline: none;
  width: 100%;
}
.edit-textarea {
  border: 1px solid var(--c-brand);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
  color: var(--c-text);
  background: var(--c-bg-card);
  outline: none;
  width: 100%;
  resize: vertical;
  font-family: inherit;
}
.edit-input:focus, .edit-textarea:focus {
  border-color: var(--c-brand-light);
  box-shadow: 0 0 0 2px var(--c-brand-subtle);
}
.edit-input-sm {
  border: 1px solid var(--c-brand);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 12px;
  color: var(--c-text);
  background: var(--c-bg-card);
  outline: none;
  flex: 1;
  min-width: 60px;
}
.edit-input-sm:focus { border-color: var(--c-brand-light); }
.dict-items-edit { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
.dict-item-row, .field-edit-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.del-item-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--c-text-muted);
  font-size: 14px;
  padding: 0 4px;
  border-radius: 4px;
  line-height: 1;
  transition: color 0.15s;
}
.del-item-btn:hover { color: #ef4444; }
.add-item-btn {
  margin-top: 4px;
  background: none;
  border: 1px dashed var(--c-brand);
  color: var(--c-brand);
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
  width: fit-content;
}
.add-item-btn:hover { background: var(--c-brand-subtle); }
.fields-edit { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }

/* Flows */
.flow-list { display: flex; flex-direction: column; gap: 12px; }
.flow-item { border: 1px solid var(--c-border); border-radius: 8px; overflow: hidden; }
.flow-header { padding: 8px 12px; background: var(--c-bg-card); }
.flow-name { font-weight: 600; font-size: 13px; color: var(--c-text); }
.flow-desc { padding: 6px 12px; font-size: 12px; color: var(--c-text-secondary); border-bottom: 1px solid var(--c-border); }
.flow-steps { padding: 8px 12px; display: flex; flex-direction: column; gap: 4px; }
.flow-step { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.step-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  background: var(--c-brand);
  color: #fff;
  border-radius: 50%;
  font-size: 11px;
  flex-shrink: 0;
}
.step-action { color: var(--c-text); flex: 1; }
.step-role {
  color: var(--c-brand);
  font-size: 11px;
  padding: 1px 6px;
  border: 1px solid var(--c-brand);
  border-radius: 10px;
  white-space: nowrap;
}
.step-status { color: var(--c-text-muted); font-size: 11px; white-space: nowrap; }

/* ── Scrollbar ── */
.messages-scroll::-webkit-scrollbar,
.session-list::-webkit-scrollbar {
  width: 6px;
}
.messages-scroll::-webkit-scrollbar-thumb,
.session-list::-webkit-scrollbar-thumb {
  background: var(--c-border);
  border-radius: 3px;
}
.messages-scroll::-webkit-scrollbar-track,
.session-list::-webkit-scrollbar-track {
  background: transparent;
}
</style>
