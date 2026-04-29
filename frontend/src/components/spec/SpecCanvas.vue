<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useSpecStore } from '@/stores/spec'
import { specTitle } from '@/utils/specDocument'
import GoalCard from './SpecCanvas/GoalCard.vue'
import RoleCard from './SpecCanvas/RoleCard.vue'
import ObjectCard from './SpecCanvas/ObjectCard.vue'
import DictCard from './SpecCanvas/DictCard.vue'
import PermissionCard from './SpecCanvas/PermissionCard.vue'
import SpecDocumentRenderer from './SpecDocumentRenderer.vue'

type ViewMode = 'document' | 'review'

const spec = useSpecStore()
const viewMode = ref<ViewMode>('document')
const confirmingAll = ref(false)

const props = withDefaults(defineProps<{
  configGenerating?: boolean
}>(), {
  configGenerating: false,
})

const emit = defineEmits<{
  (event: 'generate-config'): void
}>()

const progress = computed(() => {
  const confirmed = spec.completeness?.confirmed ?? 0
  const total = spec.completeness?.total ?? 0
  return {
    confirmed,
    total,
    pct: total === 0 ? 0 : Math.round((confirmed / total) * 100),
  }
})

const sections = computed(() => [
  { key: 'goal', label: '业务目标', count: spec.current?.goal ? 1 : 0 },
  { key: 'roles', label: '角色', count: spec.current?.roles.length ?? 0 },
  { key: 'objects', label: '数据对象', count: spec.current?.objects.length ?? 0 },
  { key: 'dicts', label: '数据字典', count: spec.current?.dicts.length ?? 0 },
  { key: 'permissions', label: '权限', count: spec.current?.permissions.length ?? 0 },
])

const unconfirmedCount = computed(() => Math.max(0, progress.value.total - progress.value.confirmed))
const pendingDecisions = computed(() => spec.pendingDecisions.filter((decision) => !decision.resolved))
const blockingDecisionCount = computed(() => pendingDecisions.value.filter((decision) => decision.blocking).length)
const canConfirmDraft = computed(() =>
  progress.value.total > 0 && unconfirmedCount.value > 0 && blockingDecisionCount.value === 0
)
const canGenerateConfig = computed(() =>
  progress.value.total > 0 && unconfirmedCount.value === 0 && blockingDecisionCount.value === 0
)
const primaryActionLabel = computed(() => {
  if (props.configGenerating) return '正在生成配置...'
  if (canGenerateConfig.value) return '生成配置预览'
  if (blockingDecisionCount.value > 0) return '先处理待确认问题'
  if (canConfirmDraft.value) return '确认此版本'
  return '等待草案生成'
})
const primaryActionDisabled = computed(() =>
  props.configGenerating || (!canConfirmDraft.value && !canGenerateConfig.value)
)
const documentTitle = computed(() => specTitle(spec.current))

async function confirmWholeDraft() {
  if (!spec.current || confirmingAll.value || unconfirmedCount.value === 0) return
  confirmingAll.value = true
  try {
    await spec.confirmAll()
    ElMessage.success('已确认此版本设计草案')
  } catch (e: unknown) {
    ElMessage.error(`确认失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    confirmingAll.value = false
  }
}

async function handlePrimaryAction() {
  if (canGenerateConfig.value) {
    emit('generate-config')
    return
  }
  if (canConfirmDraft.value) {
    await confirmWholeDraft()
  }
}
</script>

<template>
  <div class="spec-canvas">
    <header v-if="!spec.current" class="empty-state">
      <p>尚未开始 SPEC 设计 — 在左侧聊天框输入需求开始</p>
    </header>
    <template v-else>
      <header class="spec-canvas-header">
        <div class="spec-canvas-title">
          <span class="spec-canvas-kicker">AI 设计文档草案</span>
          <h2>{{ documentTitle }}</h2>
          <p v-if="canGenerateConfig">文档已确认。下一步生成低代码配置预览，然后进入构建部署。</p>
          <p v-else>先按完整文档审阅；需要调整时直接在左侧对话说明，AI 会重写草案。</p>
        </div>
        <div class="spec-canvas-actions">
          <div class="spec-canvas-progress" aria-label="设计草案确认度">
            <strong>{{ progress.pct }}%</strong>
            <span>{{ progress.confirmed }}/{{ progress.total }} 已确认</span>
            <div class="spec-canvas-progress-track">
              <div class="spec-canvas-progress-fill" :style="{ width: `${progress.pct}%` }"></div>
            </div>
          </div>
          <div class="spec-view-toggle" aria-label="SPEC 展示方式">
            <button type="button" :class="{ active: viewMode === 'document' }" @click="viewMode = 'document'">文档</button>
            <button type="button" :class="{ active: viewMode === 'review' }" @click="viewMode = 'review'">审查项</button>
          </div>
          <button
            type="button"
            class="confirm-draft-btn"
            :class="{ 'next-step': canGenerateConfig }"
            :disabled="confirmingAll || primaryActionDisabled"
            @click="handlePrimaryAction"
          >
            {{ primaryActionLabel }}
          </button>
        </div>
      </header>

      <SpecDocumentRenderer v-if="viewMode === 'document'" :spec="spec.current" />

      <template v-else>
        <section v-for="sec in sections" :key="sec.key" class="canvas-section">
          <header class="section-header">
            <h3>{{ sec.label }} <span class="section-count">{{ sec.count }}</span></h3>
          </header>
          <div class="section-body">
            <GoalCard v-if="sec.key === 'goal' && spec.current.goal" :goal="spec.current.goal" />
            <template v-else-if="sec.key === 'roles'">
              <RoleCard v-for="role in spec.current.roles" :key="role.code" :role="role" />
            </template>
            <template v-else-if="sec.key === 'objects'">
              <ObjectCard v-for="obj in spec.current.objects" :key="obj.code" :object="obj" />
            </template>
            <template v-else-if="sec.key === 'dicts'">
              <DictCard v-for="dict in spec.current.dicts" :key="dict.code" :dict="dict" />
            </template>
            <template v-else-if="sec.key === 'permissions'">
              <PermissionCard v-for="perm in spec.current.permissions" :key="perm.object_code" :permission="perm" />
            </template>
            <p v-else class="empty-section">暂无</p>
          </div>
        </section>
      </template>
    </template>
  </div>
</template>

<style scoped>
.spec-canvas {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px 36px;
  background: var(--t-bg-base);
}
.empty-state {
  text-align: center;
  color: var(--t-text-muted);
  margin-top: 60px;
  font-size: 14px;
}

.spec-canvas-header {
  max-width: 980px;
  margin: 0 auto 18px;
  padding: 16px 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 12px;
  background: var(--t-bg-panel);
}
.spec-canvas-title { min-width: 0; }
.spec-canvas-kicker {
  display: block;
  margin-bottom: 6px;
  color: var(--t-text-muted);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
}
.spec-canvas-header h2 {
  margin: 0;
  color: var(--t-text-primary);
  font-size: 20px;
  line-height: 1.35;
}
.spec-canvas-title p {
  margin: 6px 0 0;
  color: var(--t-text-secondary);
  font-size: 12px;
  line-height: 1.5;
}
.spec-canvas-actions {
  width: 260px;
  flex-shrink: 0;
  display: grid;
  gap: 8px;
}
.spec-canvas-progress {
  display: grid;
  gap: 5px;
  text-align: right;
}
.spec-canvas-progress strong {
  color: var(--t-text-primary);
  font-size: 22px;
  line-height: 1;
}
.spec-canvas-progress span {
  color: var(--t-text-muted);
  font-size: 11px;
}
.spec-canvas-progress-track {
  height: 5px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--t-bg-input);
}
.spec-canvas-progress-fill {
  height: 100%;
  border-radius: inherit;
  background: var(--t-brand);
}
.spec-view-toggle {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  padding: 3px;
  border: 1px solid #dbe3f0;
  border-radius: 10px;
  background: #f1f5fb;
}
.spec-view-toggle button,
.confirm-draft-btn {
  border: 0 !important;
  border-radius: 8px;
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
  font-weight: 700;
}
.spec-view-toggle button {
  height: 28px;
  color: #64748b;
  background: transparent !important;
}
.spec-view-toggle button.active {
  color: #3152d4;
  background: #fff !important;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
}
.confirm-draft-btn {
  height: 34px;
  color: #fff;
  background: #4f63ff !important;
}
.confirm-draft-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  background: #9aa6bd !important;
}

.canvas-section {
  max-width: 980px;
  margin: 0 auto 22px;
}
.section-header h3 {
  margin: 0 0 10px 0;
  font-size: 13px;
  color: var(--t-text-primary);
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-weight: 800;
}
.section-count {
  font-size: 12px;
  color: var(--t-text-muted);
  background: var(--t-bg-input);
  padding: 1px 8px;
  border-radius: 10px;
}
.section-body { display: flex; flex-direction: column; gap: 10px; }
.empty-section { color: var(--t-text-muted); font-size: 13px; padding: 8px 0; }

@media (max-width: 900px) {
  .spec-canvas { padding: 16px; }
  .spec-canvas-header {
    flex-direction: column;
    gap: 14px;
  }
  .spec-canvas-actions {
    width: 100%;
  }
  .spec-canvas-progress {
    text-align: left;
  }
}
</style>
