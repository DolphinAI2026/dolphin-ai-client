import { defineAsyncComponent } from 'vue'
import { registerPanel } from './panelRegistry'

export function registerPhase1Panels(): void {
  registerPanel({ id: 'artifacts', label: '产物 / 设计文档', icon: 'file', group: 'common',
    availableWhen: () => true, component: defineAsyncComponent(() => import('./panels/ArtifactPanel.vue')) })
  registerPanel({ id: 'background-tasks', label: '后台任务', icon: 'broadcast', group: 'common',
    availableWhen: () => true, component: defineAsyncComponent(() => import('./panels/BackgroundTasksPanel.vue')) })
  registerPanel({ id: 'plan', label: 'Plan', icon: 'clipboard', group: 'common',
    availableWhen: () => true, component: defineAsyncComponent(() => import('./panels/PlanPanel.vue')) })
  // stub: 仅验证 registry 按绑定点亮/置灰; Phase 2 用真 Files/Diff/... 替换。
  registerPanel({ id: 'stub-code', label: '代码(P2)', icon: 'coding', group: 'context',
    availableWhen: (b) => b.kind === 'workspace', component: defineAsyncComponent(() => import('./panels/PlanPanel.vue')) })
}
