<template>
  <BuilderFrame :breadcrumbs="[{ label: 'AI Coding' }, { label: '新建' }]">
    <div class="ace">
      <h1 class="ace-title">想做个什么应用？</h1>
      <p class="ace-sub">一句话描述你的想法，AI 帮你从零搭起来。</p>
      <textarea
        v-model="idea" class="ace-input" rows="4" :disabled="creating"
        placeholder="例如：做一个报销系统，员工提交报销单、主管审批、财务打款，带统计看板"
        @keydown.meta.enter="onCreate" @keydown.ctrl.enter="onCreate"
      ></textarea>

      <!-- 场景推荐 -->
      <div class="ace-scenes">
        <span class="ace-scenes-label">试试这些场景</span>
        <div class="ace-chips">
          <button
            v-for="scene in SCENES" :key="scene.label" type="button"
            class="ace-chip" :disabled="creating"
            @click="pickScene(scene.prompt)"
          >{{ scene.label }}</button>
        </div>
      </div>

      <!-- 路径分级 -->
      <div class="ace-tier">
        <span class="ace-tier-label">交付路径</span>
        <div class="ace-seg" role="radiogroup" aria-label="交付路径">
          <button
            v-for="opt in TIER_OPTIONS" :key="opt.value" type="button"
            class="ace-seg-btn" :class="{ 'is-active': pathTier === opt.value }"
            role="radio" :aria-checked="pathTier === opt.value" :disabled="creating"
            @click="pathTier = opt.value"
          >{{ opt.label }}</button>
        </div>
        <span class="ace-tier-hint">{{ TIER_DESC[pathTier] }}</span>
      </div>

      <!-- 导入需求文档 -->
      <div class="ace-import">
        <button type="button" class="ace-import-toggle" :disabled="creating" @click="showImport = !showImport">
          <span class="ace-import-caret" :class="{ 'is-open': showImport }">▸</span>
          导入需求文档
          <span v-if="!showImport && importDoc.trim()" class="ace-import-badge">已填写</span>
        </button>
        <textarea
          v-if="showImport"
          v-model="importDoc" class="ace-input ace-import-input" rows="8" :disabled="creating"
          placeholder="粘贴已有的需求文档、PRD 或功能清单（纯文本）。AI 会以此作为详细需求一并参考。"
        ></textarea>
      </div>

      <div class="ace-actions">
        <button class="ace-go" :disabled="!canCreate || creating" @click="onCreate">
          {{ creating ? '创建中…' : '开始构建 →' }}
        </button>
        <span class="ace-hint">⌘/Ctrl + Enter</span>
      </div>
    </div>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import BuilderFrame from '@/components/BuilderFrame.vue'
import { onlineCodingApi } from '@/api/onlineCoding'

type PathTier = 'prototype' | 'mvp' | 'production'

interface SceneOption {
  label: string
  prompt: string
}

interface TierOption {
  value: PathTier
  label: string
}

const SCENES: SceneOption[] = [
  { label: 'CRM 客户管理', prompt: '做一个 CRM 客户管理系统：客户/联系人/商机管理，跟进记录，销售看板' },
  { label: '报销审批', prompt: '做一个报销系统：员工提交报销单、主管审批、财务打款，带统计看板' },
  { label: '博客', prompt: '做一个博客：文章发布与编辑、分类标签、评论、首页列表' },
  { label: '待办清单', prompt: '做一个待办清单应用：任务增删改查、完成状态、优先级、筛选' },
  { label: '电商后台', prompt: '做一个电商后台：商品管理、订单管理、库存、销售统计' },
  { label: '项目管理', prompt: '做一个项目管理工具：项目/任务看板、成员分配、进度跟踪' },
]

const TIER_OPTIONS: TierOption[] = [
  { value: 'prototype', label: '原型' },
  { value: 'mvp', label: 'MVP' },
  { value: 'production', label: '生产' },
]

const TIER_HINTS: Record<PathTier, string> = {
  prototype: '（倾向：快速可点的前端原型，mock 数据优先，先不接真后端）',
  mvp: '（倾向：可运行的最小完整版，含基本数据持久化）',
  production: '（倾向：完整可上线，注重健壮性与边界处理）',
}

const TIER_DESC: Record<PathTier, string> = {
  prototype: '快速可点的前端原型，mock 数据优先',
  mvp: '可运行的最小完整版，含基本数据持久化',
  production: '完整可上线，注重健壮性与边界处理',
}

const router = useRouter()
const idea = ref('')
const importDoc = ref('')
const pathTier = ref<PathTier>('mvp')
const showImport = ref(false)
const creating = ref(false)

const canCreate = computed(() => !!idea.value.trim() || !!importDoc.value.trim())

function pickScene(prompt: string) {
  idea.value = prompt
}

async function onCreate() {
  if (!canCreate.value || creating.value) return
  const tier = TIER_HINTS[pathTier.value]
  const parts = [tier, idea.value.trim()]
  if (importDoc.value.trim()) parts.push('\n参考需求文档：\n' + importDoc.value.trim())
  const task = parts.filter(Boolean).join(' ').trim()
  if (!task) return
  creating.value = true
  try {
    const ws = await onlineCodingApi.createWorkspace({ task })
    // 种首条 prompt：VibeChatPanel 挂载时自动读 sessionStorage 并发送
    sessionStorage.setItem(`vibe_pending_prompt_${ws.id}`, task)
    router.push(`/ai-coding/${ws.id}`)
  } catch (e: any) {
    ElMessage.error('创建失败：' + (e?.message || e))
    creating.value = false
  }
}
</script>

<style scoped>
.ace { max-width: 680px; margin: 8vh auto 0; padding: 0 24px; display: flex; flex-direction: column; }
.ace-title { font-size: 28px; font-weight: 700; color: var(--text-2); margin: 0 0 8px; }
.ace-sub { color: var(--text-3); margin: 0 0 24px; }
.ace-input { width: 100%; border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; font-size: 15px; line-height: 1.6; background: var(--surface-3); color: var(--text-2); resize: vertical; font-family: inherit; }
.ace-input:focus { outline: none; border-color: var(--brand); }

/* 场景推荐 */
.ace-scenes { margin-top: 18px; }
.ace-scenes-label { display: block; font-size: 12px; color: var(--text-4); margin-bottom: 8px; }
.ace-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.ace-chip { border: 1px solid var(--line); background: var(--surface-3); color: var(--text-3); border-radius: 999px; padding: 6px 14px; font-size: 13px; cursor: pointer; transition: background .15s, border-color .15s, color .15s; }
.ace-chip:hover:not(:disabled) { background: var(--brand-soft); border-color: var(--brand); color: var(--brand); }
.ace-chip:disabled { opacity: .5; cursor: default; }

/* 路径分级 */
.ace-tier { margin-top: 20px; display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.ace-tier-label { font-size: 12px; color: var(--text-4); }
.ace-seg { display: inline-flex; border: 1px solid var(--line); border-radius: 10px; overflow: hidden; background: var(--surface-3); }
.ace-seg-btn { border: 0; background: transparent; color: var(--text-3); padding: 7px 16px; font-size: 13px; font-weight: 500; cursor: pointer; transition: background .15s, color .15s; }
.ace-seg-btn + .ace-seg-btn { border-left: 1px solid var(--line); }
.ace-seg-btn:hover:not(.is-active):not(:disabled) { color: var(--text-2); }
.ace-seg-btn.is-active { background: var(--brand-soft); color: var(--brand); font-weight: 600; }
.ace-seg-btn:disabled { opacity: .5; cursor: default; }
.ace-tier-hint { font-size: 12px; color: var(--text-4); }

/* 导入需求文档 */
.ace-import { margin-top: 20px; }
.ace-import-toggle { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; color: var(--text-3); font-size: 13px; cursor: pointer; padding: 0; }
.ace-import-toggle:hover:not(:disabled) { color: var(--brand); }
.ace-import-toggle:disabled { opacity: .5; cursor: default; }
.ace-import-caret { display: inline-block; transition: transform .15s; font-size: 11px; }
.ace-import-caret.is-open { transform: rotate(90deg); }
.ace-import-badge { font-size: 11px; color: var(--brand); background: var(--brand-soft); border-radius: 999px; padding: 1px 8px; }
.ace-import-input { margin-top: 10px; }

.ace-actions { display: flex; align-items: center; gap: 12px; margin-top: 24px; }
.ace-go { border: 0; background: var(--brand); color: #fff; border-radius: 10px; padding: 10px 22px; font-size: 15px; font-weight: 600; cursor: pointer; }
.ace-go:disabled { opacity: .5; cursor: default; }
.ace-hint { color: var(--text-4); font-size: 12px; }
</style>
