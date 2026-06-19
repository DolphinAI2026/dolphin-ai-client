import { defineAsyncComponent } from 'vue'
import { registerPanel } from './panelRegistry'

export function registerPhase1Panels(): void {
  registerPanel({ id: 'artifacts', label: '产物 / 设计文档', icon: 'file', group: 'common',
    availableWhen: () => true, component: defineAsyncComponent(() => import('./panels/ArtifactPanel.vue')) })
  registerPanel({ id: 'background-tasks', label: '后台任务', icon: 'broadcast', group: 'common',
    availableWhen: () => true, component: defineAsyncComponent(() => import('./panels/BackgroundTasksPanel.vue')) })
  registerPanel({ id: 'plan', label: 'Plan', icon: 'clipboard', group: 'common',
    availableWhen: () => true, component: defineAsyncComponent(() => import('./panels/PlanPanel.vue')) })
  // 代码面板(文件树 + 查看器): 仅 workspace 绑定可用
  registerPanel({ id: 'code', label: '代码', icon: 'coding', group: 'context',
    availableWhen: (b) => b.kind === 'workspace', component: defineAsyncComponent(() => import('./panels/CodeWorkspacePanel.vue')) })
}
