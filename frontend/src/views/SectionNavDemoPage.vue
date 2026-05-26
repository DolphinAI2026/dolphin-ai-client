<template>
  <!--
    SectionNavDemoPage.vue — 临时 demo 页, PR2a 验收用. PR2b 接入 ChatPage 后可删.
    路径: /ai-builder/section-nav-demo
  -->
  <div class="snv-demo">
    <SectionNav
      :current-section="currentSection"
      :current-tab="currentTab"
      :collapsed="collapsed"
      @switch-section="handleSwitch"
    />

    <main class="snv-demo-main">
      <header class="snv-demo-head">
        <h1>SectionNav PR2a Demo</h1>
        <p class="snv-demo-sub">
          5 section + 二级 sub-tab. 点一级展开 + 默认进第一个 tab. 点二级直接切.
        </p>
      </header>

      <section class="snv-demo-state">
        <h2>当前选中</h2>
        <ul class="snv-demo-kv">
          <li>
            <span class="k">currentSection</span>
            <code class="v">{{ currentSection || '(none)' }}</code>
          </li>
          <li>
            <span class="k">currentTab</span>
            <code class="v">{{ currentTab || '(none)' }}</code>
          </li>
          <li>
            <span class="k">collapsed</span>
            <code class="v">{{ collapsed }}</code>
            <button class="snv-demo-btn" @click="collapsed = !collapsed">
              切换折叠 (placeholder)
            </button>
          </li>
        </ul>
      </section>

      <section class="snv-demo-state">
        <h2>switch-section 事件历史</h2>
        <div v-if="!history.length" class="snv-demo-empty">
          (还没事件 — 点左边的 section / tab 试试)
        </div>
        <ol v-else class="snv-demo-log">
          <li v-for="(h, i) in history" :key="i">
            <span class="snv-demo-log-idx">#{{ history.length - i }}</span>
            <code>emit('switch-section', '{{ h.section }}', '{{ h.tab ?? '(undefined)' }}')</code>
            <span class="snv-demo-log-ts">{{ h.ts }}</span>
          </li>
        </ol>
        <button v-if="history.length" class="snv-demo-btn" @click="history = []">
          清空历史
        </button>
      </section>

      <section class="snv-demo-state">
        <h2>验收 checklist</h2>
        <ul class="snv-demo-check">
          <li>5 section 显示对: 数据 / 界面 / 逻辑 / 权限 / 扩展</li>
          <li>每 section 有对应 emoji icon: 📊 🎨 ⚙️ 🔒 🧩</li>
          <li>点一级 → 展开 + emit (section, tabs[0].code) + 视觉选中</li>
          <li>再点同一级 → 折叠 (选中保留)</li>
          <li>点二级 → emit (section, tab.code) + 二级选中态</li>
          <li>选中态: brand 色背景 + brand 字 + 左 3px brand 竖条</li>
          <li>hover: 浅灰 bg</li>
          <li>主题: 跟全站 light/dark 一起切 (不硬编码颜色)</li>
        </ul>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import SectionNav from '@/components/v2/SectionNav.vue'

const currentSection = ref<string>('data')
const currentTab = ref<string>('models')
const collapsed = ref(false)

interface Event { section: string; tab?: string; ts: string }
const history = ref<Event[]>([])

function handleSwitch(section: string, tab?: string) {
  currentSection.value = section
  currentTab.value = tab ?? ''
  history.value.unshift({
    section,
    tab,
    ts: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
  })
  // 上限 20 条避免视图爆炸
  if (history.value.length > 20) history.value = history.value.slice(0, 20)
}
</script>

<style scoped>
.snv-demo {
  display: flex;
  height: 100vh;
  background: var(--t-bg-app, #f5f7fc);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC',
               'Hiragino Sans GB', sans-serif;
}

.snv-demo-main {
  flex: 1;
  overflow-y: auto;
  padding: 32px 40px;
  color: var(--t-text-primary, #1e293b);
}

.snv-demo-head h1 {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 600;
  color: var(--t-text-primary, #1e293b);
}
.snv-demo-sub {
  margin: 0 0 24px;
  font-size: 13px;
  color: var(--t-text-secondary, #64748b);
}

.snv-demo-state {
  background: var(--t-bg-panel, #fff);
  border: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.08));
  border-radius: 8px;
  padding: 16px 20px;
  margin-bottom: 16px;
}
.snv-demo-state h2 {
  margin: 0 0 10px;
  font-size: 14px;
  font-weight: 600;
  color: var(--t-text-primary, #1e293b);
}

.snv-demo-kv {
  list-style: none;
  margin: 0;
  padding: 0;
}
.snv-demo-kv li {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 0;
  font-size: 13px;
}
.snv-demo-kv .k {
  width: 130px;
  color: var(--t-text-secondary, #64748b);
}
.snv-demo-kv .v {
  font-family: 'SF Mono', Monaco, 'Cascadia Mono', Consolas, monospace;
  background: var(--t-brand-subtle, rgba(79, 110, 247, 0.08));
  color: var(--t-brand, #4f6ef7);
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
}

.snv-demo-empty {
  font-size: 13px;
  color: var(--t-text-muted, #94a3b8);
  padding: 8px 0;
}

.snv-demo-log {
  list-style: none;
  margin: 0 0 10px;
  padding: 0;
  max-height: 320px;
  overflow-y: auto;
}
.snv-demo-log li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
  font-size: 12px;
  border-bottom: 1px dashed var(--t-border-subtle, rgba(99, 102, 241, 0.08));
}
.snv-demo-log li:last-child { border-bottom: none; }
.snv-demo-log code {
  font-family: 'SF Mono', Monaco, 'Cascadia Mono', Consolas, monospace;
  color: var(--t-text-primary, #1e293b);
  flex: 1;
}
.snv-demo-log-idx {
  color: var(--t-text-muted, #94a3b8);
  font-size: 11px;
  min-width: 28px;
}
.snv-demo-log-ts {
  color: var(--t-text-muted, #94a3b8);
  font-size: 11px;
}

.snv-demo-check {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--t-text-primary, #1e293b);
}

.snv-demo-btn {
  all: unset;
  cursor: pointer;
  display: inline-block;
  margin-left: 12px;
  padding: 4px 10px;
  border: 1px solid var(--t-border-strong, rgba(79, 110, 247, 0.2));
  border-radius: 5px;
  font-size: 12px;
  color: var(--t-brand, #4f6ef7);
  background: var(--t-bg-panel, #fff);
  transition: background 0.12s, border-color 0.12s;
}
.snv-demo-btn:hover {
  background: var(--t-brand-subtle, rgba(79, 110, 247, 0.08));
  border-color: var(--t-brand, #4f6ef7);
}
</style>
