<script setup lang="ts">
import { computed } from 'vue'
import { useSpecStore } from '@/stores/spec'
import GoalCard from './SpecCanvas/GoalCard.vue'
import RoleCard from './SpecCanvas/RoleCard.vue'
import ObjectCard from './SpecCanvas/ObjectCard.vue'
import DictCard from './SpecCanvas/DictCard.vue'
import PermissionCard from './SpecCanvas/PermissionCard.vue'

const spec = useSpecStore()

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
</script>

<template>
  <div class="spec-canvas">
    <header v-if="!spec.current" class="empty-state">
      <p>尚未开始 SPEC 设计 — 在左侧聊天框输入需求开始</p>
    </header>
    <template v-else>
      <header class="spec-canvas-header">
        <div>
          <span class="spec-canvas-kicker">SPEC 设计</span>
          <h2>{{ spec.current.goal?.title || '应用 SPEC' }}</h2>
        </div>
        <div class="spec-canvas-progress" aria-label="SPEC 完成度">
          <strong>{{ progress.pct }}%</strong>
          <span>{{ progress.confirmed }}/{{ progress.total }} 已采纳</span>
          <div class="spec-canvas-progress-track">
            <div class="spec-canvas-progress-fill" :style="{ width: `${progress.pct}%` }"></div>
          </div>
        </div>
      </header>
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
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 12px;
  background: var(--t-bg-panel);
}
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
  font-size: 18px;
  line-height: 1.35;
}
.spec-canvas-progress {
  width: 170px;
  flex-shrink: 0;
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
  .spec-canvas-progress {
    width: 100%;
    text-align: left;
  }
}
</style>
