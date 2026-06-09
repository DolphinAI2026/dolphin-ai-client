// frontend/src/components/v2/config-assistant/composables/useDynamicExamples.ts
//
// 2026-05-19 image #36 — 例子 chip 按当前应用真实 SPEC 动态生成, 不再写死
// "人员档案" 这种跨应用无关的内容. 失败/无 SPEC 时 fallback 到能力提示 chip.
// 2026-05-24 从 ConfigAssistantPanel.vue 抽出 (refactor #9).

import { onMounted, ref, watch, type Ref } from 'vue'
import { applicationApi } from '@/api/application'
import type { Example } from '../types'

export function useDynamicExamples(applicationId: Ref<number | undefined>) {
  // Fallback 通用能力 chip (无 SPEC / 接口失败时显示)
  const examples = ref<Example[]>([
    { id: 'cap-field', text: '把 [模型].[字段] 改成必填' },
    { id: 'cap-role', text: '加一个角色叫"XX管理员"' },
    { id: 'cap-dict', text: '[字典名] 字典加一个"XX"选项' },
  ])

  async function loadDynamicExamples() {
    if (!applicationId.value) return
    try {
      const app = (await applicationApi.get(applicationId.value)) as any
      const data = app?.config_preview?.data || app?.config_preview || {}
      const models: any[] = Array.isArray(data.models) ? data.models : []
      const dicts: any[] = Array.isArray(data.dicts) ? data.dicts : []
      const next: Example[] = []

      // 改字段必填: 用 first model 的 first field
      const m0 = models[0]
      const f0 = m0?.fields?.[0] || m0?.field_list?.[0]
      if (m0 && f0) {
        const mn = m0.label || m0.name || m0.code
        const fn = f0.label || f0.name || f0.code
        next.push({ id: 'ex-field', text: `把${mn}的${fn}改成必填` })
      }
      // 加角色: 通用模板
      next.push({ id: 'ex-role', text: '加一个角色叫"运维管理员"' })
      // 改字典选项: 用 first dict
      const d0 = dicts[0]
      if (d0) {
        const dn = d0.label || d0.name || d0.code
        next.push({ id: 'ex-dict', text: `${dn} 字典加一个"XX"选项` })
      }

      if (next.length > 0) examples.value = next
    } catch {
      // 保持 fallback chip
    }
  }

  onMounted(loadDynamicExamples)
  watch(applicationId, loadDynamicExamples)

  return { examples, loadDynamicExamples }
}
