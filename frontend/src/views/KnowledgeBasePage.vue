<template>
  <BuilderFrame :breadcrumbs="[{ label: '平台' }, { label: '平台知识库' }]">
    <template #actions>
      <el-button @click="load" :loading="loading">刷新</el-button>
      <el-button type="primary" @click="openCreate">新建文档</el-button>
    </template>
    <div class="knowledge-page builder-page">
      <div class="knowledge-header">
        <div>
          <h1>平台知识库</h1>
          <p>管理 AI Agent 可检索的平台知识文档，用于搭建、二次开发和平台规范指引。</p>
        </div>
      </div>

      <!-- 筛选栏 -->
      <div class="filter-bar">
        <el-select v-model="filterCategory" placeholder="全部分类" clearable style="width: 160px" @change="load">
          <el-option label="搭建" value="搭建" />
          <el-option label="二次开发" value="二次开发" />
          <el-option label="平台规范" value="平台规范" />
        </el-select>
        <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width: 140px" @change="load">
          <el-option label="已发布" value="published" />
          <el-option label="草稿" value="draft" />
        </el-select>
        <el-button @click="load" :loading="loading">应用筛选</el-button>
      </div>

      <div class="knowledge-panel">
        <el-table v-loading="loading" :data="docs" stripe row-key="id">
          <template #empty>
            <div style="padding: 32px; color: var(--text-3); text-align: center;">
              <div>{{ (filterCategory || filterStatus) ? '没有匹配的文档' : '还没有知识文档' }}</div>
              <el-button v-if="!(filterCategory || filterStatus)" type="primary" style="margin-top: 12px" @click="openCreate">新建文档</el-button>
            </div>
          </template>
          <el-table-column prop="slug" label="Slug" min-width="160">
            <template #default="{ row }">
              <code class="doc-slug">{{ row.slug }}</code>
            </template>
          </el-table-column>
          <el-table-column prop="title" label="标题" min-width="200" />
          <el-table-column prop="category" label="分类" width="120" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.status === 'published' ? 'success' : 'info'" size="small">
                {{ row.status === 'published' ? '已发布' : '草稿' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="更新时间" min-width="170">
            <template #default="{ row }">
              {{ formatDate(row.updated_at) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
              <el-button link type="danger" size="small" @click="confirmDelete(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 新建 / 编辑对话框 -->
      <el-dialog
        v-model="dialogVisible"
        :title="editTarget ? `编辑文档 — ${editTarget.title}` : '新建知识文档'"
        width="640px"
        :close-on-click-modal="false"
      >
        <el-form :model="form" label-position="top">
          <el-form-item label="Slug（唯一标识）" required>
            <el-input
              v-model="form.slug"
              placeholder="小写字母、数字、- ，唯一不可改"
              maxlength="128"
              :disabled="!!editTarget"
            />
          </el-form-item>
          <el-form-item label="标题" required>
            <el-input v-model="form.title" placeholder="文档标题" maxlength="255" />
          </el-form-item>
          <el-form-item label="分类" required>
            <el-select v-model="form.category" style="width: 100%" placeholder="选择分类">
              <el-option label="搭建" value="搭建" />
              <el-option label="二次开发" value="二次开发" />
              <el-option label="平台规范" value="平台规范" />
            </el-select>
          </el-form-item>
          <el-form-item label="摘要">
            <el-input v-model="form.summary" placeholder="简短描述，供列表展示" maxlength="512" />
          </el-form-item>
          <el-form-item label="标签（逗号分隔）">
            <el-input v-model="form.tags" placeholder="如：表单,流程,权限" maxlength="255" />
          </el-form-item>
          <el-form-item label="正文（Markdown）" required>
            <el-input
              v-model="form.body_md"
              type="textarea"
              :rows="12"
              placeholder="支持 Markdown 格式"
            />
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="form.status" style="width: 160px">
              <el-option label="草稿" value="draft" />
              <el-option label="已发布" value="published" />
            </el-select>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="submitForm">
            {{ editTarget ? '保存' : '创建' }}
          </el-button>
        </template>
      </el-dialog>
    </div>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import BuilderFrame from '@/components/BuilderFrame.vue'
import {
  listKnowledgeDocs,
  createKnowledgeDoc,
  updateKnowledgeDoc,
  deleteKnowledgeDoc,
  type KnowledgeDoc,
} from '@/api/knowledge'

const loading = ref(false)
const saving = ref(false)
const docs = ref<KnowledgeDoc[]>([])

const filterCategory = ref('')
const filterStatus = ref('')

// 新建/编辑对话框
const dialogVisible = ref(false)
const editTarget = ref<KnowledgeDoc | null>(null)
const form = ref<Partial<KnowledgeDoc>>({
  slug: '',
  title: '',
  category: '',
  summary: '',
  tags: '',
  body_md: '',
  status: 'draft',
})

async function load() {
  loading.value = true
  try {
    const params: { category?: string; status?: string } = {}
    if (filterCategory.value) params.category = filterCategory.value
    if (filterStatus.value) params.status = filterStatus.value
    docs.value = await listKnowledgeDocs(params)
  } catch (err: any) {
    ElMessage.error(err?.message || '加载知识文档失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editTarget.value = null
  form.value = { slug: '', title: '', category: '', summary: '', tags: '', body_md: '', status: 'draft' }
  dialogVisible.value = true
}

function openEdit(row: KnowledgeDoc) {
  editTarget.value = row
  form.value = {
    slug: row.slug,
    title: row.title,
    category: row.category,
    summary: row.summary,
    tags: row.tags || '',
    body_md: row.body_md,
    status: row.status,
  }
  dialogVisible.value = true
}

async function submitForm() {
  if (!form.value.slug?.trim()) { ElMessage.warning('请填写 Slug'); return }
  if (!form.value.title?.trim()) { ElMessage.warning('请填写标题'); return }
  if (!form.value.category) { ElMessage.warning('请选择分类'); return }
  if (!form.value.body_md?.trim()) { ElMessage.warning('请填写正文'); return }
  saving.value = true
  try {
    if (editTarget.value) {
      const updated = await updateKnowledgeDoc(editTarget.value.slug, form.value)
      const idx = docs.value.findIndex((d) => d.id === updated.id)
      if (idx >= 0) docs.value[idx] = updated
      ElMessage.success('已保存')
    } else {
      const created = await createKnowledgeDoc(form.value)
      docs.value = [created, ...docs.value]
      ElMessage.success(`文档「${created.title}」已创建`)
    }
    dialogVisible.value = false
  } catch (err: any) {
    ElMessage.error(err?.message || (editTarget.value ? '保存失败' : '创建失败'))
  } finally {
    saving.value = false
  }
}

async function confirmDelete(row: KnowledgeDoc) {
  try {
    await ElMessageBox.confirm(
      `确认删除文档「${row.title}」？此操作不可撤销。`,
      '删除文档',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch { return }
  try {
    await deleteKnowledgeDoc(row.slug)
    docs.value = docs.value.filter((d) => d.id !== row.id)
    ElMessage.success('已删除')
  } catch (err: any) {
    ElMessage.error(err?.message || '删除失败')
  }
}

function formatDate(value?: string | null): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return value
  }
}

onMounted(() => {
  load()
})
</script>

<style scoped>
.knowledge-page {
  padding: 24px;
  font-family: var(--font-sans);
  color: var(--text);
}

.knowledge-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 20px;
}
.knowledge-header h1 {
  font-size: var(--t-h2);
  font-weight: var(--fw-bold);
  letter-spacing: -0.02em;
  color: var(--text);
  margin: 0 0 6px;
}
.knowledge-header p {
  color: var(--text-3);
  font-size: 13.5px;
  line-height: 1.55;
  margin: 0;
  max-width: 720px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  margin-bottom: 14px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4);
}

.knowledge-panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4);
  overflow: hidden;
}

.knowledge-panel :deep(.el-table) {
  --el-table-header-bg-color: var(--surface-2);
  --el-table-header-text-color: var(--text-2);
  --el-table-bg-color: var(--surface);
  --el-table-tr-bg-color: var(--surface);
  --el-table-row-hover-bg-color: var(--surface-2);
  --el-table-border-color: var(--line);
  --el-table-text-color: var(--text);
  background: var(--surface);
  font-size: 13px;
  color: var(--text);
}
.knowledge-panel :deep(.el-table th.el-table__cell) {
  background: var(--surface-2);
  color: var(--text-2);
  font-weight: var(--fw-semibold);
  font-size: 11.5px;
  letter-spacing: 0.02em;
  border-bottom: 1px solid var(--line);
}
.knowledge-panel :deep(.el-table td.el-table__cell) {
  border-bottom: 1px solid var(--line);
  color: var(--text);
}
.knowledge-panel :deep(.el-button.is-link) {
  font-weight: var(--fw-medium);
  font-size: 12.5px;
}

.doc-slug {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 11.5px;
  background: var(--surface-3);
  padding: 2px 6px;
  border-radius: var(--r-1);
  color: var(--text-2);
}
</style>
