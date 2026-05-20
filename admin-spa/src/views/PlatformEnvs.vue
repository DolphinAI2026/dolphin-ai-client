<template>
  <PlaceholderView
    title="平台环境 + Dolphin Agent 配置（待迁移）"
    subtitle="从 ai-builder PlatformEnvs.vue (1700 行 / 4 Tabs) 复制改造"
    description="Phase 4.2 实现"
    :icon="Setting"
    :todo-hint="todo"
  />
</template>

<script setup lang="ts">
import { Setting } from '@element-plus/icons-vue'
import PlaceholderView from '@/components/PlaceholderView.vue'

const todo = [
  'TODO Phase 4.2：',
  '- Tab1 平台环境：GET/POST/PUT /api/platform-envs/* + alias 字段维护',
  '- Tab2 dolphin agent：GET/POST/PUT /api/tenant-dolphin-agents/* + 顺序拖动',
  '- Tab3 LLM 配置 → 抽出到独立 LlmConfigs.vue 页',
  '- Tab4 登录调试日志（只读）',
  '',
  '工作量：~1500 行 Vue + 完整 element-plus 表单 + 表格交互',
  '过渡期：可走 ai-builder 老 admin 维护，新 admin 在此页占位',
].join('\n')
</script>
