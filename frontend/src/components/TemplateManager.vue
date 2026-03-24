<template>
  <el-dialog
    v-model="visible"
    title="模板管理"
    width="800px"
    :close-on-click-modal="false"
    class="template-manager-modal"
  >
    <!-- 工具栏 -->
    <div class="tm-toolbar">
      <el-button type="primary" size="small" @click="showEditor(null)">
        + 新建模板
      </el-button>
      <label class="tm-upload-btn">
        <input type="file" accept=".md" @change="handleUpload" hidden />
        <el-button size="small">上传 MD 文件</el-button>
      </label>
    </div>

    <!-- 模板列表 -->
    <div class="tm-list">
      <div v-for="t in templates" :key="t.code" class="tm-item">
        <div class="tm-item-info">
          <div class="tm-item-name">{{ t.name }}</div>
          <div class="tm-item-desc">{{ t.description || '暂无描述' }}</div>
          <div class="tm-item-meta">
            <span class="tm-tag">{{ t.category || '未分类' }}</span>
            <span class="tm-filename">{{ t.filename }}</span>
          </div>
        </div>
        <div class="tm-item-actions">
          <el-button size="small" text @click="showEditor(t)">编辑</el-button>
          <el-button size="small" text type="danger" @click="handleDelete(t)">删除</el-button>
        </div>
      </div>
      <div v-if="templates.length === 0" class="tm-empty">暂无模板</div>
    </div>

    <!-- 编辑器弹窗 -->
    <el-dialog
      v-model="editorVisible"
      :title="editingTemplate ? '编辑模板' : '新建模板'"
      width="700px"
      append-to-body
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-position="top" size="default">
        <div class="tm-form-row">
          <el-form-item label="模板名称" required class="tm-form-half">
            <el-input v-model="form.name" placeholder="如：CRM客户管理" />
          </el-form-item>
          <el-form-item label="编码" required class="tm-form-half">
            <el-input v-model="form.code" placeholder="如：crm" :disabled="!!editingTemplate" />
          </el-form-item>
        </div>
        <div class="tm-form-row">
          <el-form-item label="图标" class="tm-form-half">
            <el-select v-model="form.icon" placeholder="选择图标">
              <el-option label="👥 用户" value="users" />
              <el-option label="🔧 工具" value="wrench" />
              <el-option label="📋 剪贴板" value="clipboard" />
            </el-select>
          </el-form-item>
          <el-form-item label="分类" class="tm-form-half">
            <el-input v-model="form.category" placeholder="如：销售管理" />
          </el-form-item>
        </div>
        <el-form-item label="简短描述">
          <el-input v-model="form.description" placeholder="如：客户、联系人、跟进、合同" />
        </el-form-item>
        <el-form-item label="设计文档内容 (Markdown)" required>
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="15"
            placeholder="输入完整的 Markdown 设计文档..."
            class="tm-editor"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request'

interface TemplateItem {
  code: string
  name: string
  icon: string
  description: string
  category: string
  filename: string
}

const visible = defineModel<boolean>({ default: false })
const emit = defineEmits(['updated'])

const templates = ref<TemplateItem[]>([])
const editorVisible = ref(false)
const editingTemplate = ref<TemplateItem | null>(null)
const saving = ref(false)
const form = ref({
  name: '',
  code: '',
  icon: 'clipboard',
  description: '',
  category: '',
  content: '',
})

const loadTemplates = async () => {
  try {
    templates.value = await request.get<any, TemplateItem[]>('/templates')
  } catch (e) {
    templates.value = []
  }
}

watch(visible, (v) => {
  if (v) loadTemplates()
})

const showEditor = async (tpl: TemplateItem | null) => {
  editingTemplate.value = tpl
  if (tpl) {
    // 加载完整内容
    try {
      const detail = await request.get<any, any>(`/templates/${tpl.code}`)
      form.value = {
        name: detail.name,
        code: detail.code,
        icon: detail.icon || 'clipboard',
        description: detail.description || '',
        category: detail.category || '',
        content: detail.content || '',
      }
    } catch (e) {
      ElMessage.error('加载模板失败')
      return
    }
  } else {
    form.value = { name: '', code: '', icon: 'clipboard', description: '', category: '', content: '' }
  }
  editorVisible.value = true
}

const handleSave = async () => {
  if (!form.value.name || !form.value.code || !form.value.content) {
    ElMessage.warning('请填写名称、编码和文档内容')
    return
  }
  saving.value = true
  try {
    if (editingTemplate.value) {
      await request.put(`/templates/${editingTemplate.value.code}`, form.value)
      ElMessage.success('模板更新成功')
    } else {
      await request.post('/templates', form.value)
      ElMessage.success('模板创建成功')
    }
    editorVisible.value = false
    await loadTemplates()
    emit('updated')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

const handleDelete = async (tpl: TemplateItem) => {
  try {
    await ElMessageBox.confirm(`确定删除模板「${tpl.name}」？`, '删除确认', { type: 'warning' })
    await request.delete(`/templates/${tpl.code}`)
    ElMessage.success('删除成功')
    await loadTemplates()
    emit('updated')
  } catch (e) {
    // 取消或错误
  }
}

const handleUpload = async (e: Event) => {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  target.value = ''

  const formData = new FormData()
  formData.append('file', file)
  try {
    await request.post('/templates/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    ElMessage.success('上传成功')
    await loadTemplates()
    emit('updated')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '上传失败')
  }
}
</script>

<style scoped>
.tm-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}
.tm-upload-btn {
  cursor: pointer;
}
.tm-list {
  max-height: 400px;
  overflow-y: auto;
}
.tm-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border: 1px solid var(--el-border-color-lighter, #3a3a4a);
  border-radius: 8px;
  margin-bottom: 8px;
  background: var(--el-bg-color, #1e1e2e);
}
.tm-item-name {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 4px;
}
.tm-item-desc {
  font-size: 12px;
  color: var(--el-text-color-secondary, #999);
  margin-bottom: 4px;
}
.tm-item-meta {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: var(--el-text-color-placeholder, #666);
}
.tm-tag {
  background: var(--el-color-primary-light-9, #2a2a3a);
  padding: 1px 6px;
  border-radius: 4px;
}
.tm-item-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.tm-empty {
  text-align: center;
  color: var(--el-text-color-placeholder, #666);
  padding: 40px 0;
}
.tm-form-row {
  display: flex;
  gap: 12px;
}
.tm-form-half {
  flex: 1;
}
.tm-editor :deep(.el-textarea__inner) {
  font-family: 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.6;
}
</style>
