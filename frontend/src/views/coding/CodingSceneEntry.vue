<template>
  <div class="cse code-scope">
    <div class="cse-inner">
      <!-- hero -->
      <div class="cse-hero">
        <div class="cse-hero-icon" v-html="iconSvg('coding', 30, 2.2)"></div>
        <span class="cse-tag"><span v-html="iconSvg('coding', 13, 1.9)"></span> 二次开发</span>
        <h1 class="cse-h1">配置装不下的,写代码搞定</h1>
        <p class="cse-sub">在已有应用上做定制页面、可复用组件、复杂接口。对话即生成代码,配在线 IDE 实时预览,产物可装回应用、跨应用复用。</p>
      </div>

      <!-- mode cards -->
      <div class="cse-modes">
        <button
          v-for="m in MODES" :key="m.id"
          class="cse-mode" :class="{ on: mode === m.id }"
          @click="mode = m.id as 'bound' | 'lib'"
        >
          <div class="cse-mode-top">
            <span class="cse-mode-icon" :class="{ on: mode === m.id }" v-html="iconSvg(m.icon, 14, 2)"></span>
            <span class="cse-mode-title" :class="{ on: mode === m.id }">{{ m.title }}</span>
            <span v-if="mode === m.id" class="cse-mode-check" v-html="iconSvg('check', 14, 2.6)"></span>
          </div>
          <div class="cse-mode-desc">{{ m.desc }}</div>
        </button>
      </div>

      <!-- target row -->
      <div class="cse-target">
        <span class="cse-target-label">{{ mode === 'bound' ? '目标应用' : '产物去向' }}</span>
        <template v-if="mode === 'bound'">
          <select v-if="apps.length" v-model="targetAppId" class="cse-target-select">
            <option v-for="a in apps" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
          <span v-else class="cse-target-chip"><span v-html="iconSvg('building', 13, 2)"></span> 未绑定应用</span>
          <span class="cse-target-hint">复用其模型 / 接口 / 枚举</span>
        </template>
        <template v-else>
          <span class="cse-target-chip"><span v-html="iconSvg('store', 13, 2)"></span> 自开发资产库</span>
          <span class="cse-target-hint">跨应用复用,可装进任意应用</span>
        </template>
      </div>

      <!-- input -->
      <div class="cse-input-card">
        <textarea
          v-model="input"
          class="cse-textarea"
          :placeholder="mode === 'bound'
            ? '描述要做的定制页面或组件。例:给商机做一个按阶段分列、卡片可拖拽换阶段的看板,拖到「赢单」时弹确认框。'
            : '描述一个通用组件。例:一个支持多选 + 异步加载的客户树组件,可在任意应用里引用。'"
        ></textarea>
        <div class="cse-input-foot">
          <span class="cse-input-hint"><span v-html="iconSvg('terminal', 15, 1.7)"></span> {{ mode === 'bound' ? '复用应用已有模型 / 接口' : '零依赖 · 可跨应用复用' }}</span>
          <button class="cse-send" :disabled="!input.trim()" @click="submit()">
            开始开发 <span v-html="iconSvg('send', 16, 2)"></span>
          </button>
        </div>
      </div>

      <!-- examples -->
      <div class="cse-examples">
        <button v-for="ex in examples" :key="ex" class="cse-ex" @click="submit(ex)">{{ ex }}</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'

const props = withDefaults(defineProps<{
  apps?: { id: number; name: string }[]
  defaultAppId?: number | null
}>(), { apps: () => [], defaultAppId: null })

const emit = defineEmits<{ (e: 'submit', payload: { mode: 'bound' | 'lib'; appId: number | null; text: string }): void }>()

const mode = ref<'bound' | 'lib'>('bound')
const targetAppId = ref<number | null>(props.defaultAppId ?? (props.apps[0]?.id ?? null))
const input = ref('')

// apps 异步加载:到货后(且用户还没选)默认选中 defaultAppId 或第一个,避免「目标应用」空选
watch(() => props.apps, (apps) => {
  if (targetAppId.value == null && apps.length) targetAppId.value = props.defaultAppId ?? apps[0].id
}, { immediate: true })

const MODES = [
  { id: 'bound', icon: 'building', title: '在应用上定制', desc: '绑定一个已有应用 · 复用其模型与接口' },
  { id: 'lib', icon: 'box', title: '做通用组件', desc: '不绑应用 · 进自开发资产库跨应用复用' },
]

const examples = computed(() =>
  mode.value === 'bound'
    ? ['给销售 CRM 加一个拖拽换阶段的商机看板', '商机详情页加一个回款计划子表', '客户列表加一个高级筛选侧栏']
    : ['多选 + 异步加载的客户树组件', 'OCR 识别的发票上传卡片', '带倒计时的 SLA 状态条'],
)

function submit(text?: string) {
  const t = (text ?? input.value).trim()
  if (!t) return
  emit('submit', { mode: mode.value, appId: mode.value === 'bound' ? targetAppId.value : null, text: t })
}

const ICON_PATHS: Record<string, string> = {
  coding: '<path d="m8 17-5-5 5-5"/><path d="m16 7 5 5-5 5"/><path d="m13 4-2 16"/>',
  building: '<path d="M5 21V4a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v17"/><path d="M15 9h3a1 1 0 0 1 1 1v11"/><path d="M8 7h2M8 11h2M8 15h2"/><path d="M3 21h18"/>',
  box: '<path d="M12 2 3 7v10l9 5 9-5V7z"/><path d="M3 7l9 5 9-5"/><path d="M12 12v10"/>',
  store: '<path d="M3 9 5 4h14l2 5"/><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9"/><path d="M3 9h18"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  send: '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/>',
  terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M13 15h4"/>',
}
function iconSvg(name: string, size: number, stroke: number): string {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round">${ICON_PATHS[name] || ''}</svg>`
}
</script>

<style scoped>
/* justify-content: safe center —— 内容比可视区高时退化为顶端对齐(不再把 hero/textarea 顶部裁掉),
   矮屏/缩放下也不会「左上角被挡住」;放得下时与 center 表现一致。 */
.cse { height: 100%; overflow-y: auto; background: var(--bg-app); display: flex; flex-direction: column; align-items: center; justify-content: safe center; padding: 40px; }
.cse-inner { width: min(100%, 760px); }

.cse-hero { text-align: center; margin-bottom: 26px; }
.cse-hero-icon { width: 60px; height: 60px; border-radius: 16px; margin: 0 auto 18px; display: grid; place-items: center; color: #fff; background: linear-gradient(145deg, var(--blue-800), var(--blue-950)); box-shadow: var(--sh-brand-lg); }
.cse-tag { display: inline-flex; align-items: center; gap: 6px; height: 26px; padding: 0 10px; border-radius: 999px; font-size: 12.5px; font-weight: 600; color: var(--brand); background: var(--brand-soft); border: 1px solid var(--brand-soft-2); font-family: var(--font-sans); margin-bottom: 14px; }
.cse-h1 { font-size: 34px; font-weight: 700; letter-spacing: -0.02em; margin: 6px 0 10px; font-family: var(--font-sans); color: var(--text); }
.cse-sub { font-size: 15px; color: var(--text-2); line-height: 1.6; max-width: 560px; margin: 0 auto; }

.cse-modes { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }
.cse-mode { text-align: left; cursor: pointer; padding: 12px 14px; border-radius: 12px; background: var(--surface); border: 1.5px solid var(--line-strong); transition: all 0.15s var(--ease, ease); font-family: inherit; }
.cse-mode.on { background: var(--brand-soft); border-color: var(--brand); }
.cse-mode-top { display: flex; align-items: center; gap: 8px; margin-bottom: 5px; }
.cse-mode-icon { width: 26px; height: 26px; border-radius: 7px; display: grid; place-items: center; background: var(--surface-3); color: var(--text-3); }
.cse-mode-icon.on { background: var(--blue-950); color: #fff; }
.cse-mode-title { font-size: 13.5px; font-weight: 700; color: var(--text); }
.cse-mode-title.on { color: var(--brand); }
.cse-mode-check { margin-left: auto; color: var(--brand); display: inline-grid; place-items: center; }
.cse-mode-desc { font-size: 11.5px; color: var(--text-3); line-height: 1.45; padding-left: 34px; }

.cse-target { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; padding: 11px 14px; background: var(--surface); border: 1px solid var(--line-strong); border-radius: 12px; box-shadow: var(--sh-1); flex-wrap: wrap; }
.cse-target-label { font-size: 11.5px; color: var(--text-3); font-weight: 600; font-family: var(--font-sans); white-space: nowrap; }
.cse-target-chip { display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px; font-weight: 600; color: var(--brand); padding: 5px 11px; border-radius: 999px; background: var(--brand-soft); white-space: nowrap; }
.cse-target-select { font-size: 12.5px; font-weight: 600; color: var(--brand); padding: 5px 11px; border-radius: 999px; background: var(--brand-soft); border: 1px solid var(--brand-soft-2); cursor: pointer; max-width: 240px; }
.cse-target-hint { font-size: 11.5px; color: var(--text-4); white-space: nowrap; }

.cse-input-card { background: var(--surface); border: 1px solid var(--line-strong); border-radius: 18px; padding: 18px; box-shadow: var(--sh-4); }
.cse-textarea { width: 100%; min-height: 90px; border: none; outline: none; resize: none; font-family: var(--font-sans); font-size: 14px; line-height: 1.65; color: var(--text); background: transparent; }
.cse-textarea::placeholder { color: var(--text-4); }
.cse-input-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 10px; padding-top: 12px; border-top: 1px solid var(--line); }
.cse-input-hint { display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--text-3); font-weight: 500; font-family: var(--font-sans); }
.cse-send { display: inline-flex; align-items: center; gap: 8px; height: 40px; padding: 0 16px; border-radius: 8px; border: none; cursor: pointer; font-size: 13.5px; font-weight: 600; font-family: var(--font-sans); color: #fff; background: var(--blue-950); box-shadow: var(--sh-3); transition: transform 0.15s; }
.cse-send:hover:not(:disabled) { transform: translateY(-1px); }
.cse-send:disabled { opacity: 0.5; cursor: not-allowed; }

.cse-examples { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 18px; }
.cse-ex { font-size: 12px; color: var(--text-2); padding: 8px 13px; border-radius: 999px; background: var(--surface); border: 1px solid var(--line); cursor: pointer; font-family: var(--font-sans); font-weight: 500; }
.cse-ex:hover { border-color: var(--brand-ring); color: var(--brand); }
</style>
