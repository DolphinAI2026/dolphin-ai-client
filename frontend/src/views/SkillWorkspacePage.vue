<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import FileTree from '@/views/coding/FileTree.vue'
import { buildFileTree, compactTree } from '@/views/coding/fileTree'
import CodeEditor from '@/components/common/CodeEditor.vue'
import { renderMd } from '@/utils/markdown'
import {
  listSkills, listSkillFiles, readSkillFile, writeSkillFile, deleteSkillFile,
  updateSkillMetadata, type SkillItem,
} from '@/api/skills'

const route = useRoute(); const router = useRouter()
const name = computed(() => String(route.params.name || ''))
const meta = ref<SkillItem | null>(null)
const readonly = computed(() => meta.value?.source === 'platform')

const paths = ref<string[]>([])
const tree = computed(() => compactTree(buildFileTree(paths.value)))
// FileTree 需要 changed(Set) 必填项; skill 工作区无 git 改动概念, 传空集。
const emptyChanged = new Set<string>()
const selected = ref('')
const content = ref('')
const dirty = ref(false)
const desc = ref(''); const tagsText = ref('')

const isMd = computed(() => selected.value.toLowerCase().endsWith('.md'))

async function loadMeta() {
  const all = await listSkills()
  meta.value = all.find(s => s.name === name.value) || null
  desc.value = meta.value?.description || ''
}
async function loadTree() { paths.value = await listSkillFiles(name.value) }
async function openFile(p: string) {
  if (dirty.value && !(await confirmDiscard())) return
  selected.value = p
  try { content.value = (await readSkillFile(name.value, p)).content; dirty.value = false }
  catch (e: any) { ElMessage.error(e?.response?.data?.detail || '读取失败'); content.value = '' }
}
async function confirmDiscard(): Promise<boolean> {
  try { await ElMessageBox.confirm('当前文件有未保存改动，放弃?', '提示', { type: 'warning' }); return true }
  catch { return false }
}
async function save() {
  if (readonly.value) { ElMessage.warning('平台预置只读，先「复制为我的技能」'); return }
  try { await writeSkillFile(name.value, selected.value, content.value); dirty.value = false; ElMessage.success('已保存'); await loadTree() }
  catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
}
async function saveMeta() {
  if (readonly.value) return
  try {
    await updateSkillMetadata(name.value, { description: desc.value, tags: tagsText.value.split(',').map(s => s.trim()).filter(Boolean) })
    ElMessage.success('元数据已保存'); await loadMeta()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
}
async function newFile() {
  if (readonly.value) return
  try {
    const { value } = await ElMessageBox.prompt('新文件相对路径（如 scripts/run.py）', '新建文件')
    if (!value) return
    await writeSkillFile(name.value, value, ''); await loadTree(); await openFile(value)
  } catch (e: any) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(e?.response?.data?.detail || '新建失败')
  }
}
async function delFile() {
  if (readonly.value || !selected.value) return
  try {
    await ElMessageBox.confirm(`删除 ${selected.value}?`, '确认', { type: 'warning' })
    await deleteSkillFile(name.value, selected.value); selected.value = ''; content.value = ''; dirty.value = false; await loadTree()
  } catch (e: any) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

onMounted(async () => {
  await loadMeta(); await loadTree()
  if (paths.value.includes('SKILL.md')) await openFile('SKILL.md')
})
</script>

<template>
  <div class="skill-ws">
    <header class="sw-top">
      <button class="sw-back" @click="router.push('/skills')">← 返回技能库</button>
      <span class="sw-name">{{ name }}</span>
      <span v-if="readonly" class="sw-ro">平台预置 · 只读</span>
      <div class="sw-actions">
        <button @click="newFile" :disabled="readonly">新建文件</button>
        <button @click="delFile" :disabled="readonly || !selected">删除</button>
        <button class="sw-save" @click="save" :disabled="readonly || !selected">保存</button>
      </div>
    </header>
    <div class="sw-body">
      <aside class="sw-tree">
        <FileTree :tree="tree" :changed="emptyChanged" :selected="selected" @select="openFile" />
      </aside>
      <section class="sw-editor">
        <CodeEditor v-model="content" :filename="selected" :readonly="readonly" @update:modelValue="dirty = true" />
      </section>
      <section v-if="isMd" class="sw-preview" v-html="renderMd(content)"></section>
    </div>
    <footer class="sw-meta">
      <label>描述 <input v-model="desc" :disabled="readonly" /></label>
      <label>标签 <input v-model="tagsText" :disabled="readonly" placeholder="逗号分隔" /></label>
      <button @click="saveMeta" :disabled="readonly">保存元数据</button>
    </footer>
  </div>
</template>

<style scoped>
.skill-ws { display: flex; flex-direction: column; height: 100%; }
.sw-top, .sw-meta { display: flex; align-items: center; gap: 12px; padding: 8px 12px; border-bottom: 1px solid var(--line, #e5e7eb); }
.sw-meta { border-top: 1px solid var(--line, #e5e7eb); border-bottom: 0; }
.sw-meta input { border: 1px solid var(--line, #ddd); border-radius: 6px; padding: 4px 8px; }
.sw-name { font-weight: 600; }
.sw-ro { font-size: 12px; color: #b26a00; background: #fff3e0; padding: 2px 8px; border-radius: 10px; }
.sw-actions { margin-left: auto; display: flex; gap: 8px; }
.sw-body { flex: 1; display: flex; min-height: 0; }
.sw-tree { width: 240px; flex: none; border-right: 1px solid var(--line, #e5e7eb); overflow: auto; }
.sw-editor { flex: 1; min-width: 0; }
.sw-preview { flex: 1; min-width: 0; overflow: auto; padding: 16px; border-left: 1px solid var(--line, #e5e7eb); }
</style>
