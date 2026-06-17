<template>
  <BuilderFrame :breadcrumbs="[{ label: '技能库' }]">
    <template #actions>
      <button class="new-btn new-btn--ghost" @click="onNewBlank">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        新建空白
      </button>
      <el-upload
        :show-file-list="false"
        :before-upload="onUpload"
        accept=".zip,.skill"
        :disabled="uploading"
      >
        <button class="new-btn" :disabled="uploading">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          {{ uploading ? '上传中…' : '上传技能 (.zip/.skill)' }}
        </button>
      </el-upload>
    </template>

    <div class="skill-main builder-page">
      <div class="page-header">
        <div class="page-title">技能库</div>
        <div class="page-summary">{{ skills.length }} 个技能（平台预置 + 本地上传）</div>
      </div>

      <div class="content-wrap">
        <div v-if="loading" class="empty-state">
          <SkeletonCard :lines="4" with-footer />
        </div>
        <div v-else-if="skills.length === 0" class="empty-state">
          <EmptyState
            title="暂无技能"
            desc="上传一个技能 zip（内含 SKILL.md，frontmatter 须有 name + description），让 AI 在对话里调用它。"
          >
            <template #icon>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/></svg>
            </template>
          </EmptyState>
        </div>

        <el-table
          v-else
          :data="skills"
          stripe
          class="skill-table"
          row-key="name"
          :header-cell-style="{ background: 'var(--b-bg-sub)', color: 'var(--b-text-muted)', fontWeight: '700', fontSize: '12px' }"
        >
          <el-table-column prop="name" label="技能" min-width="200" show-overflow-tooltip />
          <el-table-column prop="description" label="说明" min-width="280" show-overflow-tooltip />
          <el-table-column label="来源" width="120">
            <template #default="{ row }">
              <el-tag :type="row.source === 'platform' ? 'info' : 'success'" size="small">
                {{ row.source === 'platform' ? '平台预置' : '本地上传' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="脚本/文件" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="skill-files">{{ filesSummary(row.files) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="240" align="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="edit(row)">编辑</el-button>
              <el-button v-if="row.source === 'platform'" link @click="onClone(row)">复制为我的技能</el-button>
              <el-button
                v-if="row.source === 'user'"
                link
                type="danger"
                @click="onDelete(row.name)"
              >删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import BuilderFrame from '@/components/BuilderFrame.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import SkeletonCard from '@/components/states/SkeletonCard.vue'
import { listSkills, uploadSkill, deleteSkill, createSkill, cloneSkill, type SkillItem } from '@/api/skills'

const router = useRouter()
const skills = ref<SkillItem[]>([])
const loading = ref(false)
const uploading = ref(false)

async function refresh() {
  loading.value = true
  try {
    skills.value = await listSkills()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载技能失败')
  } finally {
    loading.value = false
  }
}

// 文件列只展示顶层摘要的前几项，避免带 JRE/大量文件的 skill 把单元格撑爆。
function filesSummary(files?: string[]): string {
  if (!files || !files.length) return '—'
  const MAX = 6
  if (files.length <= MAX) return files.join(', ')
  return files.slice(0, MAX).join(', ') + ` 等 ${files.length} 项`
}

// el-upload :before-upload —— 返回 false 阻止其默认上传，自己走 API。
function onUpload(file: File): boolean {
  void doUpload(file)
  return false
}

async function doUpload(file: File) {
  uploading.value = true
  try {
    const r = await uploadSkill(file)
    ElMessage.success(`已上传技能「${r.name}」`)
    await refresh()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '上传失败')
  } finally {
    uploading.value = false
  }
}

async function onDelete(name: string) {
  try {
    await ElMessageBox.confirm(`删除技能「${name}」？`, '确认删除', { type: 'warning' })
  } catch {
    return // 用户取消
  }
  try {
    await deleteSkill(name)
    ElMessage.success('已删除')
    await refresh()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

function edit(row: SkillItem) {
  router.push(`/skills/${encodeURIComponent(row.name)}/workspace`)
}

async function onNewBlank() {
  let value: string
  try {
    const r = await ElMessageBox.prompt('技能名（英文/数字/连字符）', '新建空白 skill')
    value = r.value
  } catch {
    return // 用户取消
  }
  if (!value) return
  try {
    await createSkill(value)
    router.push(`/skills/${encodeURIComponent(value)}/workspace`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '新建失败')
  }
}

async function onClone(row: SkillItem) {
  let value: string
  try {
    const r = await ElMessageBox.prompt(`复制「${row.name}」为新技能，输入新名`, '复制为我的技能')
    value = r.value
  } catch {
    return // 用户取消
  }
  if (!value) return
  try {
    await cloneSkill(row.name, value)
    ElMessage.success('已复制')
    await refresh()
    router.push(`/skills/${encodeURIComponent(value)}/workspace`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '复制失败')
  }
}

onMounted(refresh)
</script>

<style scoped>
.skill-main {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 16px 24px 24px;
  overflow: auto;
}

.page-header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 16px;
}

.page-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--text, #111);
}

.page-summary {
  font-size: 13px;
  color: var(--text-3, #888);
}

.content-wrap {
  flex: 1;
  min-height: 0;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 0;
}

.skill-files {
  display: block;
  max-width: 100%;
  font-size: 12px;
  color: var(--text-2, #555);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.new-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-inverse, #fff);
  background: var(--brand, #1d4ed8);
  border: none;
  border-radius: var(--r-2, 6px);
  cursor: pointer;
  transition: background 0.14s ease;
}
.new-btn:hover:not(:disabled) {
  background: var(--brand-hover, #1e40af);
}
.new-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.new-btn--ghost {
  color: var(--text, #111);
  background: transparent;
  border: 1px solid var(--b-border, #d9d9d9);
}
.new-btn--ghost:hover:not(:disabled) {
  background: var(--b-bg-sub, #f5f5f5);
}

/* 表格操作列的 el-button link: 全局 builder.css 把 --primary/--danger 渲染成填充块,
   这里强制还原成无底色的文字链接(否则「编辑/删除」糊成纯色块、看不清字)。 */
.skill-main :deep(.el-button.is-link) {
  background: transparent !important;
  border: none !important;
  padding: 2px 6px !important;
  height: auto;
  color: var(--brand, #1d4ed8);
  font-weight: 600;
}
.skill-main :deep(.el-button.is-link:hover) {
  background: transparent !important;
  color: var(--brand-hover, #1e40af);
}
.skill-main :deep(.el-button--danger.is-link) {
  color: var(--err, #dc2626);
}
.skill-main :deep(.el-button--danger.is-link:hover) {
  color: var(--err, #dc2626);
  opacity: 0.85;
}
</style>
