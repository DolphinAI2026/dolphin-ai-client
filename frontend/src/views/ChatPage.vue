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
        <button class="nav-link" @click="router.push('/apps')">我的应用</button>
        <span class="dot" :class="{ active: store.connected }" @click="store.showConnectModal = true" style="cursor:pointer" :title="store.connected ? '已连接得帆云' : '未连接，点击连接'"></span>
      </div>
    </nav>

    <div class="main-area">
      <!-- 左侧对话区 -->
      <div class="chat-side">
        <div class="agent-tabs">
          <button v-for="(agent, key) in agents" :key="key" class="agent-tab" :class="{ active: currentAgent === key }" @click="switchAgent(key as string)">
            <span>{{ agent.icon }}</span>
            <span>{{ agent.name }}</span>
            <span v-if="currentAgent === key" class="active-dot"></span>
          </button>
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
        </div>

        <div class="input-bar">
          <div class="input-wrap">
            <label class="upload-btn" title="上传功能设计文档(.md)">
              <input type="file" accept=".md" @change="handleDocUpload" style="display:none" ref="fileInputRef" />
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
          <div v-show="store.previewTab === 'overview'" class="tab-content">
            <div class="overview-header">
              <h4>{{ store.preview.appName }}</h4>
              <span class="status-tag" :class="deployAllDone ? 'deployed' : store.currentApp?.status">
                {{ deployAllDone ? '已部署' : store.currentApp?.status === 'ready' ? '待生成' : store.currentApp?.status === 'conversation' ? '配置调整中' : '对话中' }}
              </span>
            </div>
            <div class="stat-grid">
              <div class="stat-card indigo"><div class="stat-num">{{ store.preview.models.length }}</div><div class="stat-label">数据模型</div></div>
              <div class="stat-card emerald"><div class="stat-num">{{ store.preview.roles.length }}</div><div class="stat-label">角色</div></div>
              <div class="stat-card amber"><div class="stat-num">{{ store.preview.dicts.length }}</div><div class="stat-label">数据字典</div></div>
              <div class="stat-card purple"><div class="stat-num">{{ store.preview.workflows.length }}</div><div class="stat-label">流程</div></div>
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
            <div v-if="deployAllDone && !hasConfigChanged" class="deployed-banner">✅ 已部署到平台</div>
            <button v-else-if="store.preview.models.length > 0 && (store.currentApp?.status === 'ready' || store.currentApp?.status === 'conversation' || hasConfigChanged)" class="gen-btn" :disabled="generating" @click="startGenerate">{{ generating ? '创建中...' : hasConfigChanged ? '⚡ 更新配置并部署' : existingAppId ? '⚡ 更新并生成' : '⚡ 开始生成' }}</button>
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
                  <div class="field-left"><span class="field-icon">{{ f.icon }}</span><span class="field-name">{{ f.name }}</span><span v-if="f.required" class="req">*</span></div>
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
                      <template v-else-if="f.type === '地理位置'">请选择位置 <span class="mock-arrow">📍</span></template>
                      <template v-else>请输入{{ f.name }}</template>
                    </div>
                  </template>
                </div>
              </div>
            </div>
          </div>

          <!-- 流程 -->
          <div v-show="store.previewTab === 'workflow'" class="tab-content">
            <div v-for="(wf, wi) in store.preview.workflows" :key="wi" class="wf-card">
              <div class="wf-header"><span class="wf-name">{{ wf.name }}</span><span class="wf-form">关联: {{ wf.form }}</span></div>
              <div class="wf-nodes">
                <template v-for="(nd, ni) in wf.nodes" :key="ni">
                  <div class="wf-node" :class="nd.type"><div>{{ nd.name }}</div><div v-if="nd.role" class="wf-role">{{ nd.role }}</div></div>
                  <div v-if="ni < wf.nodes.length - 1" class="wf-arrow">▼</div>
                </template>
              </div>
            </div>
            <div v-if="store.preview.workflows.length === 0" class="preview-empty small">暂无流程配置</div>
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

        <!-- 未连接提示 -->
        <div v-if="!store.connected && store.currentApp" class="connect-warn">
          <div class="warn-title">⚠ 未连接得帆云平台</div>
          <p>请先连接平台才能生成应用。</p>
          <button @click="store.showConnectModal = true" class="warn-link">连接平台</button>
        </div>
      </div>

      <!-- 第三栏：部署面板 -->
      <div class="deploy-side" :class="{ open: deployOpen }">
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
          <button class="dp-run-all" :disabled="deployExecuting !== null || deployAllDone" @click="deployRunAll">
            {{ deployAllDone ? '✓ 全部完成' : '▶ 一键执行' }}
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
                  <button v-else-if="s.status === 'completed'" class="ds-btn redo" @click="deployRedo(s.key)">↻</button>
                  <button v-else-if="s.status === 'error'" class="ds-btn retry" @click="deployExec(s.key)">重试</button>
                  <button v-else-if="s.deps_met" class="ds-btn run" @click="deployExec(s.key)">执行</button>
                  <span v-else class="ds-lock">🔒</span>
                </div>
              </div>
            </div>
          </template>
        </div>
        <div v-if="deployAllDone" class="deploy-done">
          🎉 部署完成！<button class="deploy-done-btn" @click="router.push('/apps')">查看应用 →</button>
        </div>
      </div>
    </div>

    <ConnectModal v-model="store.showConnectModal" />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, nextTick, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ArrowLeft, Promotion } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { usePreviewStore } from '@/stores/preview'
import { useUserStore } from '@/stores/user'
import { applicationApi } from '@/api/application'
import { conversationApi } from '@/api/conversation'
import ConnectModal from '@/components/ConnectModal.vue'
import type { Message } from '@/types'

const router = useRouter()
const route = useRoute()
const store = usePreviewStore()
const userStore = useUserStore()

const messagesRef = ref<HTMLElement>()
const fileInputRef = ref<HTMLInputElement>()
const inputText = ref('')
const isTyping = ref(false)
const currentAgent = ref('builder')

const agents: Record<string, { name: string; icon: string }> = {
  builder: { name: '搭建智能体', icon: '🤖' },
  assistant: { name: '辅助开发智能体', icon: '🛠️' },
  developer: { name: '复杂开发智能体', icon: '💻' }
}

const tabs = [
  { k: 'overview', l: '概览' }, { k: 'models', l: '模型' },
  { k: 'forms', l: '表单' }, { k: 'workflow', l: '流程' }, { k: 'perms', l: '权限' }
]

const messages = reactive<Message[]>([
  { id: 0, role: 'assistant', agent: 'builder', content: '你好！我是 aPaaS 搭建智能体，可以帮你通过对话的方式在得帆云平台上快速搭建应用。\n\n你可以告诉我想要创建什么系统，我会帮你理清需求并自动生成。\n\n比如：\n• "我想做一个客户管理系统"\n• "帮我搭建一个项目管理应用"\n• "创建一个售后服务工单系统"', created_at: '' }
])

const scrollToBottom = () => { nextTick(() => { if (messagesRef.value) messagesRef.value.scrollTop = messagesRef.value.scrollHeight }) }

const switchAgent = (key: string) => {
  currentAgent.value = key
  const greetings: Record<string, string> = {
    builder: '已切换到搭建智能体。告诉我你想创建什么应用？',
    assistant: '已切换到辅助开发智能体。我可以帮你完善已有应用：\n• 创建审批流程\n• 配置业务规则\n• 调整表单组件\n• 配置数据权限',
    developer: '已切换到复杂开发智能体。我可以帮你：\n• 自定义Vue组件\n• 后端接口集成\n• Groovy脚本编写'
  }
  messages.push({ id: Date.now(), role: 'assistant', agent: key, content: greetings[key], created_at: '' })
  scrollToBottom()
}

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms))

// 从AI回复中提取JSON配置（支持 preview 完整配置和 patch 增量修改）
const extractPreviewData = (content: string) => {
  // 提取所有 ```json 块
  const allMatches = [...content.matchAll(/```json\s*([\s\S]*?)```/g)]
  if (allMatches.length === 0) return

  for (const match of allMatches) {
    try {
      const parsed = JSON.parse(match[1].trim())
      console.log('extractPreviewData: parsed type =', parsed.type, parsed)

      // 完整配置模式
      if (parsed.type === 'preview' && parsed.data) {
        if (store.preview.models.length > 0) {
          console.warn('已有配置，忽略 LLM 重复输出的完整 JSON')
          continue
        }
        store.currentApp = { name: parsed.data.appName, status: 'ready' }
        store.preview.appName = parsed.data.appName || ''
        store.preview.roles = parsed.data.roles || []
        store.preview.dicts = parsed.data.dicts || []
        store.preview.models = parsed.data.models || []
        store.preview.workflows = parsed.data.workflows || []
        store.preview.permissions = parsed.data.permissions || []
        continue
      }

      // 增量 patch 模式
      if (parsed.type === 'patch' && parsed.actions) {
        console.log('Applying patch:', parsed.actions.length, 'actions')
        applyPatch(parsed.actions)
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
    store.currentApp = { name: store.preview.appName, status: 'ready' }
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
  if (confirm(`删除字典「${d.name}」？`)) {
    store.preview.dicts.splice(idx, 1)
  }
}

const conversationId = ref<number | null>(null)
const existingAppId = ref<number | null>(null)  // 从"继续完善"进来时，关联的已有应用ID
const generating = ref(false)

// ── 部署面板 ──
interface DeployStep { key: string; label: string; status: 'pending' | 'completed' | 'error'; deps_met: boolean; error?: string; result?: any }
const deployOpen = ref(false)
const deployAppId = ref<number | null>(null)
const deploySteps = ref<DeployStep[]>([])
const deployExecuting = ref<string | null>(null)

const deployDoneCount = computed(() => deploySteps.value.filter(s => s.status === 'completed').length)
const deployPercent = computed(() => deploySteps.value.length ? Math.round(deployDoneCount.value / deploySteps.value.length * 100) : 0)
const deployAllDone = computed(() => deploySteps.value.length > 0 && deployDoneCount.value === deploySteps.value.length)

// 检测配置是否有变更（对比当前 preview 和已部署的步骤）
const hasConfigChanged = computed(() => {
  if (!deploySteps.value.length) return false
  // 计算当前配置应有的步骤数：1(app) + 1(roles_dicts) + models + forms + workflows + 1(perms)
  const expectedSteps = 1 + 1 + store.preview.models.length + store.preview.models.length + store.preview.workflows.length + 1
  return expectedSteps !== deploySteps.value.length
})

const deployGroups = computed(() => {
  const defs = [
    { title: '初始化', icon: '🚀', test: (s: DeployStep) => s.key === 'create_app' },
    { title: '公共资源', icon: '📦', test: (s: DeployStep) => s.key === 'create_roles_dicts' },
    { title: '数据模型', icon: '🗃', test: (s: DeployStep) => s.key.startsWith('create_model:') },
    { title: '表单配置', icon: '📋', test: (s: DeployStep) => s.key.startsWith('create_form:') },
    { title: '审批流程', icon: '🔄', test: (s: DeployStep) => s.key.startsWith('create_workflow:') },
    { title: '权限配置', icon: '🔐', test: (s: DeployStep) => s.key === 'configure_permissions' },
  ]
  return defs.map(d => {
    const ss = deploySteps.value.filter(d.test)
    return { ...d, steps: ss, allDone: ss.length > 0 && ss.every(s => s.status === 'completed'), hasError: ss.some(s => s.status === 'error'), doneCount: ss.filter(s => s.status === 'completed').length }
  }).filter(d => d.steps.length > 0)
})

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
    if (resp.status === 'error') ElMessage.error(resp.error || '失败')
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
  for (const s of deploySteps.value) {
    if (s.status === 'completed') continue
    await loadDeployStatus()
    const fresh = deploySteps.value.find(x => x.key === s.key)
    if (!fresh?.deps_met) continue
    deployExecuting.value = s.key
    const resp = await applicationApi.executeStep(deployAppId.value!, s.key)
    await loadDeployStatus()
    if (resp.status === 'error') { ElMessage.error(resp.error + '，已暂停'); deployExecuting.value = null; return }
  }
  deployExecuting.value = null
  ElMessage.success('全部完成！')
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
  if (!store.connected) {
    ElMessage.warning('请先连接得帆云平台')
    store.showConnectModal = true
    return
  }
  generating.value = true
  try {
    const appCode = 'app' + Date.now().toString(36)
    const payload = {
      conversation_id: conversationId.value || 0,
      app_name: store.preview.appName,
      app_code: appCode,
      description: store.preview.appName,
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

const handleDocUpload = async (e: Event) => {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  target.value = '' // reset for re-upload

  const userMsgId = Date.now()
  messages.push({ id: userMsgId, role: 'user', content: `📄 上传设计文档: ${file.name}`, created_at: '' })

  // 结构化进度状态
  const progressMsgId = userMsgId + 1
  const phases = reactive<Record<string, { icon: string, label: string, status: string, detail: string }>>({
    skeleton: { icon: '📋', label: '提取骨架', status: 'pending', detail: '' },
    dicts: { icon: '📖', label: '字典选项', status: 'pending', detail: '' },
    models: { icon: '🗃', label: '模型字段', status: 'pending', detail: '' },
    workflows: { icon: '🔄', label: '流程设计', status: 'pending', detail: '' },
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

    const response = await fetch('/api/applications/upload-doc-with-conversation', {
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
                }
              }

              // 骨架完成时设置基础信息
              if (data.data?.appName && !store.preview.appName) {
                store.preview.appName = data.data.appName
                store.preview.roles = data.data.roles || []
                store.currentApp = { name: data.data.appName, status: 'conversation' }
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
        store.currentApp = { name: previewData.appName, status: 'conversation' }
        store.preview.appName = previewData.appName || ''
        store.preview.roles = previewData.roles || []
        store.preview.dicts = previewData.dicts || []
        store.preview.models = previewData.models || []
        store.preview.workflows = previewData.workflows || []
        store.preview.permissions = previewData.permissions || []
      }

      // 替换进度消息为完成总结
      if (pmsg) {
        phases.complete.status = 'done'
        phases.complete.detail = `${store.preview.models.length} 模型, ${store.preview.dicts.length} 字典, ${store.preview.roles.length} 角色`
        pmsg.content = buildProgressContent() + '\n\n你可以调整配置，或点击"开始生成"部署到平台。'
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
    const response = await fetch('/api/chat/generate-config', {
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
            store.currentApp = { name: store.preview.appName, status: 'conversation' }
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

          // 完整配置 → 最终覆盖
          if (evt.phase === 'complete' && evt.data) {
            const d = evt.data
            store.preview.appName = d.appName || store.preview.appName
            store.preview.roles = d.roles || store.preview.roles
            store.preview.dicts = d.dicts || store.preview.dicts
            store.preview.models = d.models || store.preview.models
            store.preview.workflows = d.workflows || []
            store.preview.permissions = d.permissions || []
            store.currentApp = { name: store.preview.appName, status: 'ready' }
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
  const res = await fetch('/api/conversations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    body: JSON.stringify({ agent_type: currentAgent.value })
  })
  if (res.ok) {
    const data = await res.json()
    conversationId.value = data.id
    // 更新 URL，刷新后能恢复对话
    router.replace(`/chat/${data.id}`)
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
    const response = await fetch('/api/chat/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({
        conversation_id: conversationId.value,
        message: text,
        ...(store.preview.appName ? { current_config: { ...store.preview } } : {})
      })
    })

    if (!response.ok) throw new Error('发送失败')

    isTyping.value = false
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
            if (parsed.type === 'message') {
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
              // 标记完成，设置正式id
              const lastMsg = messages[messages.length - 1]
              if (lastMsg && lastMsg.id === -1) lastMsg.id = Date.now()
              // 提取配置JSON
              extractPreviewData(assistantContent)
              // 如果提到了应用名但还没设置currentApp
              if (!store.currentApp && assistantContent.length > 50) {
                const appNameMatch = assistantContent.match(/搭建.*?[**](.+?)[**]/)
                if (appNameMatch) {
                  store.currentApp = { name: appNameMatch[1], status: 'talking' }
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
      const res = await fetch('/api/apaas/status', {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      if (res.ok) {
        const data = await res.json()
        store.connected = data.connected
      }
    }
  } catch (e) { /* ignore */ }

  // 如果URL带了对话ID，加载历史消息和预览数据
  const idParam = route.params.id as string
  if (idParam) {
    const cid = Number(idParam)
    if (!isNaN(cid)) {
      conversationId.value = cid
      // 检查是否从"继续完善"进来（带 app_id 参数）
      const appIdParam = route.query.app_id as string
      if (appIdParam) {
        existingAppId.value = Number(appIdParam)
      }
      try {
        // 加载历史消息
        const historyMessages = await conversationApi.getMessages(cid)
        if (historyMessages && historyMessages.length > 0) {
          // 清空默认欢迎消息，替换为历史记录
          messages.splice(0, messages.length)
          for (const msg of historyMessages) {
            // 系统消息不显示，但要提取其中的配置 JSON
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
            // 从assistant消息中提取预览数据
            if (msg.role === 'assistant') {
              extractPreviewData(msg.content)
            }
          }
          scrollToBottom()
        }
        // 如果历史消息中没有恢复出配置，尝试从关联应用的 config_preview 恢复
        if (!store.preview.appName && store.preview.models.length === 0) {
          try {
            // 查找和这个对话关联的应用
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
              store.currentApp = { name: store.preview.appName, status: 'ready' }
              if (linkedApp.id && typeof linkedApp.id === 'number') {
                existingAppId.value = linkedApp.id
              }
              console.log('Recovered config from linked application:', store.preview.appName)
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
          store.currentApp = { name: store.preview.appName, status: 'ready' }
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
    // 清空旧状态
    store.reset()
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
})
</script>

<style scoped>
.chat-page { height: 100vh; display: flex; flex-direction: column; background: #f9fafb; }
.nav-bar { display: flex; justify-content: space-between; align-items: center; padding: 8px 16px; background: #fff; border-bottom: 1px solid #e5e7eb; flex-shrink: 0; }
.nav-left, .nav-right { display: flex; align-items: center; gap: 10px; }
.back-btn { background: none; border: none; color: #9ca3af; cursor: pointer; padding: 4px; }
.back-btn:hover { color: #374151; }
.logo-box { width: 28px; height: 28px; background: #4f46e5; border-radius: 8px; display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 700; font-size: 12px; }
.logo-text { font-size: 14px; font-weight: 600; color: #1f2937; }
.nav-link { font-size: 12px; color: #6b7280; background: none; border: none; cursor: pointer; padding: 6px 12px; border-radius: 6px; }
.nav-link:hover { background: #f3f4f6; color: #374151; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #d1d5db; }
.dot.active { background: #10b981; }

.main-area { flex: 1; display: flex; overflow: hidden; position: relative; }

/* 左侧对话 */
.chat-side { flex: 1; display: flex; flex-direction: column; min-width: 0; min-width: 320px; }
.agent-tabs { display: flex; gap: 4px; padding: 8px 16px; background: #fff; border-bottom: 1px solid #f3f4f6; flex-shrink: 0; }
.agent-tab { display: flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 8px; font-size: 12px; font-weight: 500; background: none; border: none; color: #6b7280; cursor: pointer; }
.agent-tab:hover { background: #f3f4f6; }
.agent-tab.active { background: #eef2ff; color: #4338ca; }
.active-dot { width: 6px; height: 6px; border-radius: 50%; background: #10b981; }

.messages { flex: 1; overflow-y: auto; padding: 16px; }
.chat-bubble { margin-bottom: 16px; animation: fadeUp 0.3s ease-out; }
.chat-bubble.user { display: flex; justify-content: flex-end; }
.chat-bubble.assistant { display: flex; justify-content: flex-start; }
.bubble-inner { max-width: 80%; }
.agent-label { display: flex; align-items: center; gap: 4px; font-size: 11px; color: #9ca3af; margin-bottom: 4px; }
.bubble-content { padding: 10px 14px; border-radius: 14px; font-size: 13px; line-height: 1.6; }
.bubble-content.user { background: #4f46e5; color: #fff; border-bottom-right-radius: 4px; }
.bubble-content.assistant { background: #fff; border: 1px solid #e5e7eb; color: #374151; border-bottom-left-radius: 4px; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
@keyframes fadeUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

.typing-dot { width: 6px; height: 6px; border-radius: 50%; background: #94a3b8; display: inline-block; animation: pulseDot 1.4s infinite ease-in-out both; margin-right: 3px; }
.typing-dot:nth-child(1) { animation-delay: -0.32s; }
.typing-dot:nth-child(2) { animation-delay: -0.16s; }
@keyframes pulseDot { 0%,80%,100% { transform: scale(0); } 40% { transform: scale(1); } }

.input-bar { padding: 12px 16px; background: #fff; border-top: 1px solid #e5e7eb; flex-shrink: 0; }
.input-wrap { display: flex; align-items: center; gap: 8px; background: #f3f4f6; border-radius: 12px; padding: 8px 8px 8px 12px; border: 1px solid #e5e7eb; }
.input-wrap:focus-within { border-color: #a5b4fc; box-shadow: 0 0 0 3px rgba(99,102,241,0.1); }
.upload-btn { cursor: pointer; font-size: 18px; padding: 2px 4px; border-radius: 6px; opacity: 0.6; transition: opacity 0.2s; }
.upload-btn:hover { opacity: 1; background: #e5e7eb; }
.input-wrap input { flex: 1; background: transparent; border: none; outline: none; font-size: 13px; color: #374151; }
.input-wrap input::placeholder { color: #9ca3af; }
.send-btn { width: 32px; height: 32px; border-radius: 8px; background: #4f46e5; color: #fff; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; }
.send-btn.disabled { opacity: 0.4; cursor: not-allowed; }
.send-btn:hover:not(.disabled) { background: #4338ca; }

/* 右侧预览 */
.preview-side { flex: 1; background: #fff; border-left: 1px solid #e5e7eb; display: flex; flex-direction: column; min-width: 0; }
.preview-tabs { display: flex; border-bottom: 1px solid #e5e7eb; padding: 0 8px; flex-shrink: 0; }
.ptab { padding: 10px 12px; font-size: 12px; font-weight: 500; border: none; background: none; color: #9ca3af; cursor: pointer; border-bottom: 2px solid transparent; }
.ptab.active { color: #4f46e5; border-bottom-color: #4f46e5; }
.preview-empty { padding: 24px; text-align: center; color: #9ca3af; font-size: 13px; margin-top: 80px; }
.preview-empty .empty-icon { font-size: 40px; opacity: 0.4; margin-bottom: 12px; }
.preview-empty.small { margin-top: 0; padding: 32px; }
.preview-body { flex: 1; overflow-y: auto; }
.tab-content { padding: 16px; }

/* 概览 */
.overview-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.overview-header h4 { font-size: 14px; font-weight: 600; color: #1f2937; margin: 0; }
.status-tag { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.status-tag.ready { background: #ecfdf5; color: #059669; }
.status-tag.deployed { background: #dbeafe; color: #2563eb; }
.deployed-banner { text-align: center; padding: 10px; background: #eff6ff; color: #2563eb; border-radius: 12px; font-size: 13px; font-weight: 500; margin-top: 8px; }
.deployed-link { background: none; border: none; color: #4f46e5; cursor: pointer; font-size: 12px; text-decoration: underline; margin-left: 8px; }
.status-tag.talking { background: #eef2ff; color: #4f46e5; }
.stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 16px; }
.stat-card { border-radius: 8px; padding: 12px; text-align: center; }
.stat-card.indigo { background: #eef2ff; }
.stat-card.emerald { background: #ecfdf5; }
.stat-card.amber { background: #fffbeb; }
.stat-card.purple { background: #faf5ff; }
.stat-num { font-size: 20px; font-weight: 700; }
.stat-card.indigo .stat-num { color: #4f46e5; }
.stat-card.emerald .stat-num { color: #059669; }
.stat-card.amber .stat-num { color: #d97706; }
.stat-card.purple .stat-num { color: #7c3aed; }
.stat-label { font-size: 11px; color: #9ca3af; }
.sub-section { margin-bottom: 16px; }
.sub-title { font-size: 12px; font-weight: 500; color: #6b7280; margin-bottom: 8px; }
.tag-list { display: flex; flex-wrap: wrap; gap: 6px; }
.tag { font-size: 12px; background: #f3f4f6; color: #4b5563; padding: 4px 10px; border-radius: 6px; }
.dict-list { display: flex; flex-direction: column; gap: 6px; }
.dict-row { display: flex; align-items: center; gap: 6px; font-size: 12px; padding: 4px 8px; background: #f9fafb; border-radius: 4px; }
.dict-name { color: #374151; white-space: nowrap; }
.dict-opts { flex: 1; }
.dict-opts.empty { color: #dc2626; }
.edit-mini, .del-mini { background: none; border: none; cursor: pointer; font-size: 11px; padding: 2px; opacity: 0.4; transition: opacity 0.2s; flex-shrink: 0; }
.dict-row:hover .edit-mini, .dict-row:hover .del-mini { opacity: 1; }
.add-mini { background: none; border: 1px dashed #d1d5db; color: #6b7280; font-size: 11px; padding: 0 6px; border-radius: 4px; cursor: pointer; margin-left: 8px; }
.add-mini:hover { border-color: #4f46e5; color: #4f46e5; }
.tag.editable { cursor: pointer; transition: all 0.2s; }
.tag.editable:hover { background: #fef2f2; color: #dc2626; border-color: #fecaca; }
.tag.empty { background: #f9fafb; color: #9ca3af; font-style: italic; }
.dict-opts { color: #9ca3af; }
.assemble-btn { width: 100%; padding: 10px; background: #f59e0b; color: #fff; border: none; border-radius: 12px; font-size: 13px; font-weight: 500; cursor: pointer; margin-top: 8px; }
.assemble-btn:hover { background: #d97706; }
.assemble-progress { display: flex; align-items: center; gap: 8px; padding: 10px 12px; background: #fffbeb; border: 1px solid #fde68a; border-radius: 12px; font-size: 12px; color: #92400e; margin-top: 8px; }
.assemble-spinner { animation: spin 1s linear infinite; display: inline-block; font-size: 16px; }
.gen-btn { width: 100%; padding: 10px; background: #4f46e5; color: #fff; border: none; border-radius: 12px; font-size: 13px; font-weight: 500; cursor: pointer; margin-top: 8px; }
.gen-btn:hover { background: #4338ca; }

/* 模型 */
.model-card { border: 1px solid #e5e7eb; border-radius: 12px; overflow: hidden; margin-bottom: 12px; }
.model-header { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: #f9fafb; font-size: 12px; }
.model-name { font-weight: 600; color: #374151; }
.model-code { margin-left: auto; font-size: 10px; color: #9ca3af; font-family: monospace; }
.field-list { }
.field-row { display: flex; justify-content: space-between; align-items: center; padding: 6px 12px; border-top: 1px solid #f3f4f6; }
.field-row:hover { background: #f9fafb; }
.field-left { display: flex; align-items: center; gap: 8px; }
.field-icon { width: 16px; text-align: center; font-size: 10px; }
.field-name { font-size: 12px; color: #374151; }
.req { color: #ef4444; font-size: 10px; margin-left: 2px; }
.field-right { display: flex; align-items: center; gap: 6px; }
.ftag { font-size: 10px; padding: 1px 6px; border-radius: 3px; }
.ftag.dict { background: #fffbeb; color: #d97706; }
.ftag.ref { background: #eff6ff; color: #2563eb; }
.ftype { font-size: 10px; color: #9ca3af; }

/* 模型选择 */
.model-select-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; padding: 8px 12px; background: #f9fafb; border-radius: 8px; }
.model-select-all { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #374151; cursor: pointer; }
.model-select-all input { accent-color: #4f46e5; }
.model-select-tip { font-size: 11px; color: #9ca3af; }
.model-checkbox { display: flex; align-items: center; cursor: pointer; }
.model-checkbox input { accent-color: #4f46e5; width: 14px; height: 14px; }
.model-card.model-deselected { opacity: 0.45; }
.model-card.model-deselected:hover { opacity: 0.7; }

/* 表单 */
.form-selector { display: flex; gap: 4px; margin-bottom: 12px; overflow-x: auto; padding-bottom: 4px; }
.form-tab { font-size: 12px; padding: 4px 10px; border-radius: 8px; border: none; background: none; color: #6b7280; cursor: pointer; white-space: nowrap; }
.form-tab.active { background: #eef2ff; color: #4338ca; font-weight: 500; }
.form-preview { border: 1px solid #e5e7eb; border-radius: 12px; overflow: hidden; }
.form-title { background: #eef2ff; padding: 8px 16px; font-size: 12px; font-weight: 600; color: #4338ca; border-bottom: 1px solid #c7d2fe; }
.form-fields-grid { padding: 16px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.form-field { min-width: 0; }
.form-field.full-width { grid-column: 1 / -1; }
.form-label { font-size: 12px; color: #4b5563; margin-bottom: 4px; }
.form-mock { border: 1px solid #e5e7eb; border-radius: 8px; padding: 6px 10px; font-size: 12px; color: #9ca3af; background: #f9fafb; display: flex; justify-content: space-between; }
.form-mock.tall { min-height: 56px; }
.mock-auto { font-style: italic; color: #d1d5db; }
.mock-arrow { color: #9ca3af; }
.mock-link { color: #60a5fa; }
.mock-switch { color: #d1d5db; font-size: 10px; letter-spacing: -1px; }

/* 子表 */
.subtable-wrapper { border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }
.subtable { width: 100%; border-collapse: collapse; font-size: 12px; }
.subtable thead { background: #f3f4f6; }
.subtable th { padding: 6px 10px; text-align: left; font-weight: 500; color: #6b7280; border-bottom: 1px solid #e5e7eb; white-space: nowrap; }
.subtable td { padding: 6px 10px; border-bottom: 1px solid #f3f4f6; color: #374151; }
.subtable-idx { width: 32px; text-align: center; color: #9ca3af; }
.subtable-op { width: 48px; text-align: center; }
.subtable-del { color: #ef4444; cursor: pointer; font-size: 11px; }
.subtable-placeholder { color: #d1d5db; display: flex; justify-content: space-between; align-items: center; }
.subtable-data-selector { display: flex; justify-content: space-between; align-items: center; }
.subtable-add { padding: 8px; text-align: center; font-size: 12px; color: #4f46e5; cursor: pointer; border-top: 1px dashed #e5e7eb; }
.subtable-add:hover { background: #f9fafb; }

/* 流程 */
.wf-card { border: 1px solid #e5e7eb; border-radius: 12px; overflow: hidden; margin-bottom: 12px; }
.wf-header { display: flex; justify-content: space-between; padding: 8px 12px; background: #f9fafb; }
.wf-name { font-size: 12px; font-weight: 600; color: #374151; }
.wf-form { font-size: 10px; color: #9ca3af; }
.wf-nodes { display: flex; flex-direction: column; align-items: center; padding: 16px; gap: 4px; }
.wf-node { padding: 8px 16px; border-radius: 8px; font-size: 12px; font-weight: 500; text-align: center; min-width: 120px; }
.wf-node.start { background: #ecfdf5; color: #059669; border-radius: 20px; }
.wf-node.approve { background: #eef2ff; color: #4338ca; }
.wf-node.end { background: #f3f4f6; color: #6b7280; border-radius: 20px; }
.wf-role { font-size: 10px; opacity: 0.7; margin-top: 2px; }
.wf-arrow { color: #d1d5db; font-size: 12px; }

/* 权限 */
.perm-card { border: 1px solid #e5e7eb; border-radius: 12px; overflow: hidden; margin-bottom: 12px; }
.perm-header { padding: 8px 12px; background: #f9fafb; font-size: 12px; font-weight: 600; color: #374151; }
.perm-table { width: 100%; border-collapse: collapse; }
.perm-table th { font-size: 10px; color: #9ca3af; font-weight: 500; text-align: left; padding: 6px 12px; border-bottom: 1px solid #f3f4f6; }
.perm-table td { font-size: 12px; color: #374151; padding: 6px 12px; border-bottom: 1px solid #f9fafb; }
.data-tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; }
.data-tag.all { background: #fef2f2; color: #dc2626; }
.data-tag.dept { background: #fffbeb; color: #d97706; }
.data-tag.self { background: #eff6ff; color: #2563eb; }

.connect-warn { padding: 16px; }
.connect-warn > div { background: #fffbeb; border: 1px solid #fde68a; border-radius: 12px; padding: 12px; font-size: 12px; }
.warn-title { color: #92400e; font-weight: 500; margin-bottom: 4px; }
.connect-warn p { color: #b45309; margin: 0 0 8px; }
.warn-link { color: #92400e; text-decoration: underline; background: none; border: none; cursor: pointer; font-size: 12px; }

/* ── 部署面板（第三栏） ── */
.deploy-side {
  width: 0; min-width: 0; overflow: hidden; background: #fafbfc; border-left: 1px solid #eee;
  display: flex; flex-direction: column; transition: width 0.3s ease, min-width 0.3s ease;
}
.deploy-side.open { width: 340px; min-width: 340px; }
@media (max-width: 1200px) {
  .deploy-side.open { position: absolute; right: 0; top: 0; bottom: 0; z-index: 20; width: 360px; min-width: 360px; box-shadow: -4px 0 20px rgba(0,0,0,0.08); }
}

.deploy-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 16px 8px; }
.deploy-title { font-size: 14px; font-weight: 700; color: #111; }
.deploy-desc { font-size: 11px; color: #aaa; margin-top: 2px; }
.deploy-close { all: unset; cursor: pointer; color: #ccc; font-size: 16px; padding: 4px; }
.deploy-close:hover { color: #666; }

.deploy-progress { padding: 0 16px 8px; display: flex; align-items: center; gap: 8px; }
.dp-track { flex: 1; height: 3px; background: #eee; border-radius: 2px; overflow: hidden; }
.dp-fill { height: 100%; background: linear-gradient(90deg, #6366f1, #8b5cf6); border-radius: 2px; transition: width 0.5s; }
.dp-meta { font-size: 10px; color: #bbb; white-space: nowrap; }

.deploy-actions { padding: 0 16px 12px; }
.dp-run-all { width: 100%; padding: 8px; background: #111; color: #fff; border: none; border-radius: 8px; font-size: 12px; cursor: pointer; font-weight: 500; }
.dp-run-all:hover:not(:disabled) { background: #333; }
.dp-run-all:disabled { opacity: 0.35; cursor: not-allowed; }

.deploy-groups { flex: 1; overflow-y: auto; padding: 0 12px 12px; }
.dg { background: #fff; border: 1px solid #eee; border-radius: 10px; margin-bottom: 8px; overflow: hidden; }
.dg.done { border-color: #c6f6d5; }
.dg.err { border-color: #fed7d7; }
.dg-hd { display: flex; align-items: center; gap: 6px; padding: 10px 14px; background: #fafbfc; font-size: 12px; }
.dg-icon { font-size: 13px; }
.dg-name { font-weight: 600; color: #444; flex: 1; }
.dg-badge { font-size: 9px; padding: 1px 6px; border-radius: 99px; font-weight: 600; background: #f0f0f0; color: #999; }
.dg-badge.done { background: #e8faf0; color: #0a8; }
.dg-badge.err { background: #fff0f0; color: #e53; }

.ds { display: flex; align-items: center; padding: 7px 14px; gap: 10px; font-size: 12px; }
.ds + .ds { border-top: 1px solid #f7f7f7; }
.ds:hover { background: #fcfcfd; }
.ds-dot { width: 18px; height: 18px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 9px; font-weight: 700; color: #fff; flex-shrink: 0; }
.ds-dot.completed { background: #0a8; }
.ds-dot.error { background: #e53; }
.ds-dot.pending { background: #ddd; width: 7px; height: 7px; margin: 0 5.5px; }
.ds-dot.pulse { background: #6366f1; animation: dpulse 1.5s infinite; }
@keyframes dpulse { 0%,100% { box-shadow: 0 0 0 0 rgba(99,102,241,0.3); } 50% { box-shadow: 0 0 0 5px rgba(99,102,241,0); } }

.ds-body { flex: 1; min-width: 0; }
.ds-name { color: #333; }
.ds.completed .ds-name { color: #999; }
.ds.pending .ds-name { color: #ccc; }
.ds-err { font-size: 10px; color: #e53; margin-top: 1px; }

.ds-act { flex-shrink: 0; }
.ds-btn { border: none; cursor: pointer; border-radius: 5px; font-weight: 500; font-size: 11px; }
.ds-btn.run { padding: 3px 10px; background: #6366f1; color: #fff; }
.ds-btn.run:hover { background: #4f46e5; }
.ds-btn.retry { padding: 3px 10px; background: #e53; color: #fff; }
.ds-btn.redo { padding: 2px 5px; background: none; color: #ccc; font-size: 14px; }
.ds-btn.redo:hover { color: #6366f1; }
.ds-spin { display: inline-block; width: 14px; height: 14px; border: 2px solid #eee; border-top-color: #6366f1; border-radius: 50%; animation: spin 0.7s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.ds-lock { font-size: 11px; opacity: 0.2; }

.deploy-done { padding: 12px 16px; text-align: center; font-size: 13px; color: #0a8; font-weight: 500; }
.deploy-done-btn { background: #0a8; color: #fff; border: none; border-radius: 6px; padding: 5px 12px; font-size: 12px; cursor: pointer; margin-left: 8px; }
.deploy-done-btn:hover { background: #087; }
</style>
