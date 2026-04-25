<script setup lang="ts">
import { computed } from 'vue'
import { useSpecStore } from '@/stores/spec'

const spec = useSpecStore()

const completenessPct = computed(() => {
  const c = spec.completeness
  if (!c || c.total === 0) return 0
  return Math.round((c.confirmed / c.total) * 100)
})

const sections = computed(() => {
  const by = spec.completeness?.by_section ?? {}
  return Object.entries(by).map(([key, [confirmed, total]]) => ({
    key, label: sectionLabel(key), confirmed, total,
    pct: total === 0 ? 0 : Math.round((confirmed / total) * 100),
  }))
})

function sectionLabel(key: string): string {
  return ({
    goal: '业务目标', roles: '角色', objects: '数据对象',
    fields: '字段', dicts: '字典', permissions: '权限',
  } as Record<string, string>)[key] || key
}
</script>

<template>
  <aside class="spec-inspector" v-if="spec.current">
    <!-- 完成度 -->
    <section class="inspector-section">
      <h4 class="inspector-h">完成度</h4>
      <div class="completeness-ring">
        <span class="completeness-num">{{ spec.completeness?.confirmed ?? 0 }}/{{ spec.completeness?.total ?? 0 }}</span>
        <span class="completeness-pct">{{ completenessPct }}%</span>
      </div>
      <ul class="completeness-by-section">
        <li v-for="s in sections" :key="s.key">
          <span class="sec-label">{{ s.label }}</span>
          <span class="sec-progress">{{ s.confirmed }}/{{ s.total }}</span>
          <div class="sec-bar"><div class="sec-bar-fill" :style="{ width: s.pct + '%' }"></div></div>
        </li>
      </ul>
    </section>

    <!-- 待决策 -->
    <section class="inspector-section">
      <h4 class="inspector-h">待决策 <span class="inspector-count">{{ spec.pendingDecisions.length }}</span></h4>
      <ul class="decisions-list">
        <li v-for="d in spec.pendingDecisions" :key="d.id" class="decision-item" :class="{ blocking: d.blocking }">
          <header>
            <span class="decision-topic">{{ d.topic }}</span>
            <span v-if="d.blocking" class="blocking-tag">阻塞</span>
          </header>
          <p v-if="d.why_blocking" class="decision-why">{{ d.why_blocking }}</p>
          <ol v-if="d.options.length" class="decision-options">
            <li v-for="(opt, i) in d.options" :key="i">{{ opt }}</li>
          </ol>
        </li>
      </ul>
      <p v-if="spec.pendingDecisions.length === 0" class="empty-text">所有决策已解决</p>
    </section>

    <!-- 版本时间线（Phase β 占位，γ 实现 fork 后填充） -->
    <section class="inspector-section">
      <h4 class="inspector-h">版本</h4>
      <p class="version-current">v{{ spec.current?.version ?? 1 }}</p>
      <p v-if="spec.current?.parent_spec_id" class="version-parent">基于 {{ spec.current.parent_spec_id }}</p>
    </section>
  </aside>
</template>

<style scoped>
.spec-inspector {
  width: 280px;
  flex-shrink: 0;
  border-left: 1px solid var(--t-border-subtle);
  padding: 16px 14px;
  background: var(--t-bg-panel);
  overflow-y: auto;
  font-size: 13px;
}
.inspector-section { margin-bottom: 24px; }
.inspector-h { margin: 0 0 8px 0; font-size: 13px; color: var(--t-text-primary); display: flex; align-items: center; gap: 6px; }
.inspector-count { background: var(--t-bg-input); color: var(--t-text-secondary); padding: 1px 7px; border-radius: 10px; font-size: 11px; }
.completeness-ring { display: flex; align-items: baseline; gap: 8px; padding: 8px 0; }
.completeness-num { font-size: 22px; font-weight: 700; color: var(--t-brand); font-family: monospace; }
.completeness-pct { font-size: 14px; color: var(--t-text-secondary); }
.completeness-by-section { list-style: none; padding: 0; margin: 0; }
.completeness-by-section li { display: grid; grid-template-columns: 80px 50px 1fr; align-items: center; gap: 6px; padding: 4px 0; font-size: 12px; }
.sec-label { color: var(--t-text-secondary); }
.sec-progress { font-family: monospace; color: var(--t-text-primary); text-align: right; }
.sec-bar { height: 4px; background: var(--t-bg-input); border-radius: 2px; overflow: hidden; }
.sec-bar-fill { height: 100%; background: var(--t-brand); transition: width 0.3s; }

.decisions-list { list-style: none; padding: 0; margin: 0; }
.decision-item { padding: 8px 10px; margin-bottom: 6px; background: var(--t-bg-input); border-radius: var(--t-radius-sm); border-left: 3px solid var(--t-text-muted); }
.decision-item.blocking { border-left-color: var(--t-warning); background: var(--t-warning-subtle); }
.decision-item header { display: flex; align-items: center; gap: 6px; }
.decision-topic { font-weight: 500; color: var(--t-text-primary); }
.blocking-tag { background: var(--t-warning); color: white; font-size: 10px; padding: 1px 5px; border-radius: 3px; }
.decision-why { margin: 4px 0; font-size: 12px; color: var(--t-text-secondary); }
.decision-options { margin: 4px 0 0 18px; padding: 0; font-size: 12px; color: var(--t-text-secondary); }
.decision-options li { margin-bottom: 2px; }

.empty-text { color: var(--t-text-muted); font-size: 12px; }
.version-current { font-family: monospace; font-size: 14px; color: var(--t-text-primary); margin: 0; }
.version-parent { font-size: 11px; color: var(--t-text-muted); margin: 4px 0 0; }

@media (max-width: 1280px) {
  .spec-inspector { display: none; }  /* hide on small screens; Phase γ adds drawer toggle */
}
</style>
