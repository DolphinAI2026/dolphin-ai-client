<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import LandingComposer from '@/components/v2/LandingComposer.vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import { usePreviewStore } from '@/stores/preview'

const router = useRouter()
const previewStore = usePreviewStore()
const fileInputRef = ref<HTMLInputElement | null>(null)

const FLOW_STEPS = [
  { icon: 'chat', title: '描述需求', desc: '业务目标与材料' },
  { icon: 'doc', title: '构建应用', desc: '页面 / 表单 / 流程' },
  { icon: 'cube', title: '调用 MCP', desc: '后端工具补齐配置' },
  { icon: 'rocket', title: '部署上线', desc: '使用平台管理中的环境' },
]

const ICONS: Record<string, string> = {
  chat: '<path d="M21 12a8 8 0 0 1-11.9 7L4 21l1.6-4.4A8 8 0 1 1 21 12z"/>',
  doc: '<path d="M7 3h8l4 4v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M14 3v5h5"/><path d="M9 13h6"/><path d="M9 17h4"/>',
  cube: '<path d="M20.5 7.5 12 12 3.5 7.5"/><path d="M12 12v9"/><path d="M21 8v8l-9 5-9-5V8l9-5z"/>',
  rocket: '<path d="M4.5 16.5 3 21l4.5-1.5"/><path d="M8 16 4 12l8.5-8.5c2.5-2.5 6-1.5 8 .5 2 2 3 5.5.5 8L12 20l-4-4z"/><path d="M14 6l4 4"/>',
}

function renderIcon(name: string): string {
  const inner = ICONS[name] ?? ''
  return `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
}

function openUpload() {
  fileInputRef.value?.click()
}

function handleFileUpload(event: Event) {
  const target = event.target as HTMLInputElement
  const files = Array.from(target.files || [])
  target.value = ''
  if (!files.length) return

  const file = files[0]
  if (!file) return
  if (!/\.(md|markdown)$/i.test(file.name)) {
    ElMessage.warning('当前首页直达 Builder 仅支持 .md / .markdown 文件')
    return
  }

  previewStore.pendingFile = file
  router.push({ path: '/chat', query: { from: 'upload' } })
}
</script>

<template>
  <WorkbenchShell>
    <main class="landing" data-design="v2">
      <div class="landing-inner">
        <section class="hero">
          <div class="ai-mark">AI</div>
          <div class="eyebrow">RUIJING AI · BUILDER + CODING</div>
          <h1>把想法交给<span>睿鲸AI</span><br />自动构建可上线应用</h1>
          <p>支持 .md 设计文档上传，单 .md 直接走 AI Builder 秒级生成。</p>
        </section>

        <LandingComposer @upload-file="openUpload" />

        <section class="flow" aria-label="构建流程">
          <template v-for="(step, index) in FLOW_STEPS" :key="step.title">
            <article class="flow-card">
              <div class="flow-icon" v-html="renderIcon(step.icon)" />
              <div>
                <h2>{{ step.title }}</h2>
                <p>{{ step.desc }}</p>
              </div>
            </article>
            <div v-if="index < FLOW_STEPS.length - 1" class="flow-arrow" aria-hidden="true">→</div>
          </template>
        </section>

        <input
          ref="fileInputRef"
          type="file"
          accept=".md,.markdown"
          hidden
          @change="handleFileUpload"
        />
      </div>
    </main>
  </WorkbenchShell>
</template>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Preserved (don't change):
     - hero + composer-mount + 4 flow-cards layout
     - All class names (.landing/.hero/.ai-mark/.eyebrow/.flow/.flow-card/.flow-icon/.flow-arrow)
     - Responsive breakpoints 1180/760 + dark-theme overrides
   Refreshed:
     - bg radial uses --brand-soft (blue-50) instead of indigo brand-soft-2
     - hardcoded rgba(91,91,214,X) → --brand-ring / --brand-glow / --brand-soft
     - linear-gradient(--brand-400,--brand-700) → (--blue-500,--blue-800) to match design-spec hero brand
     - radius 14/15px → var(--r-5,16px) outer / var(--r-4,12px) inner
     - weights 850/820/650/620 → capped at fw-bold(700)/fw-semibold(600)/fw-medium(500) per v3 4-档
     - flow-arrow grey #9690b0 → var(--text-4)
*/
.landing {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  background:
    radial-gradient(ellipse 760px 380px at 50% 8%, var(--brand-soft), transparent 70%),
    linear-gradient(180deg, var(--bg) 0%, var(--surface-3) 100%);
}

.landing-inner {
  width: min(100%, 1040px);
  margin: 0 auto;
  padding: 42px 40px 44px;
}

.hero {
  width: min(100%, 920px);
  margin: 0 auto 20px;
  text-align: center;
}

.ai-mark {
  width: 58px;
  height: 58px;
  display: grid;
  place-items: center;
  margin: 0 auto 16px;
  border-radius: var(--r-5, 16px);
  color: #fff;
  background: linear-gradient(135deg, var(--blue-500, #3B82F6), var(--blue-800, #1E40AF));
  box-shadow: 0 14px 30px -10px var(--brand-glow), inset 0 -1px 0 rgba(255, 255, 255, 0.22);
  font-size: 24px;
  font-weight: var(--fw-bold, 700);
  letter-spacing: -0.02em;
}

.eyebrow {
  margin-bottom: 14px;
  color: var(--brand-text);
  font-size: var(--t-micro, 11px);
  font-weight: var(--fw-bold, 700);
  letter-spacing: 0.24em;
}

.hero h1 {
  margin: 0;
  color: var(--text);
  font-size: clamp(28px, 3.2vw, 44px);
  line-height: 1.12;
  font-weight: var(--fw-bold, 700);
  letter-spacing: -0.02em;
}

.hero h1 span {
  color: var(--brand);
}

.hero p {
  margin: 16px 0 0;
  color: var(--text-2);
  font-size: var(--t-body, 14px);
  line-height: 1.55;
  font-weight: var(--fw-regular, 400);
}

.flow {
  width: min(100%, 920px);
  display: grid;
  grid-template-columns: 1fr 28px 1fr 28px 1fr 28px 1fr;
  align-items: center;
  gap: 10px;
  margin: 18px auto 0;
}

.flow-card {
  min-width: 0;
  min-height: 96px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  box-shadow: var(--sh-2);
  transition: border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              transform 0.12s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.flow-card:hover {
  border-color: var(--brand-ring);
  box-shadow: var(--sh-3);
  transform: translateY(-1px);
}

.flow-icon {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: #fff;
  border-radius: var(--r-3, 8px);
  background: linear-gradient(135deg, var(--blue-500, #3B82F6), var(--blue-800, #1E40AF));
  box-shadow: var(--sh-brand);
}

.flow-card h2 {
  margin: 0;
  color: var(--text);
  font-size: var(--t-body, 14px);
  line-height: 1.25;
  font-weight: var(--fw-semibold, 600);
  letter-spacing: -0.005em;
}

.flow-card p {
  margin: 6px 0 0;
  color: var(--text-3);
  font-size: var(--t-small, 12.5px);
  line-height: 1.5;
  font-weight: var(--fw-regular, 400);
}

.flow-arrow {
  color: var(--text-4);
  text-align: center;
  font-size: 22px;
  font-weight: var(--fw-regular, 400);
}

html[data-theme="dark"] .landing {
  background:
    radial-gradient(ellipse 760px 380px at 50% 8%, var(--brand-soft), transparent 70%),
    var(--bg-app);
}

html[data-theme="dark"] .flow-card {
  background: var(--surface);
}

@media (max-width: 1180px) {
  .landing-inner {
    padding: 34px 24px 42px;
  }

  .flow {
    grid-template-columns: 1fr 1fr;
  }

  .flow-arrow {
    display: none;
  }
}

@media (max-width: 760px) {
  .landing-inner {
    padding: 28px 16px 36px;
  }

  .flow {
    grid-template-columns: 1fr;
  }

  .flow-card {
    min-height: 92px;
  }
}
</style>
