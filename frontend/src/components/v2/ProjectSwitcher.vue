<script setup lang="ts">
import { ref } from 'vue'
import { useProjectStore } from '@/stores/project'

const store = useProjectStore()
const open = ref(false)

function pick(id: string) {
  store.setCurrent(id)
  open.value = false
}
const stageBadgeClass = (stage: string) => ({
  '已上线': 'badge-emerald',
  '开发中': 'badge-amber',
  '测试中': 'badge-sky',
  '设计中': 'badge-brand',
  '维护中': 'badge-outline',
}[stage] ?? 'badge-outline')
</script>

<template>
  <div class="proj-switch-wrap">
    <button class="proj-switch" @click="open = !open">
      <span class="proj-switch-bar" />
      <span class="proj-switch-name">{{ store.currentProject?.name ?? '未选择' }}</span>
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6" /></svg>
    </button>
    <div v-if="open" class="proj-pop" @click.self="open = false">
      <div class="proj-pop-panel">
        <div class="proj-pop-head">切换项目</div>
        <button v-for="p in store.projects" :key="p.id" class="proj-pop-item" :class="{ active: p.id === store.currentProjectId }" @click="pick(p.id)">
          <span class="proj-pop-bar" />
          <span class="proj-pop-name">{{ p.name }}</span>
          <span class="badge" :class="stageBadgeClass(p.stage)">{{ p.stage }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.proj-switch-wrap { position: relative; }
.proj-switch { display: inline-flex; align-items: center; gap: 8px; height: 30px; padding: 0 10px 0 6px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--text); font-size: 13px; font-weight: 600; cursor: pointer; font-family: inherit; transition: border-color 0.12s, background 0.12s; }
.proj-switch:hover { border-color: var(--border-strong); background: var(--surface-2); }
.proj-switch-bar { display: inline-block; width: 3px; height: 14px; border-radius: 2px; background: var(--brand-500); }
.proj-switch-name { letter-spacing: -0.005em; }
.proj-pop { position: fixed; inset: 0; z-index: 200; }
.proj-pop-panel { position: absolute; top: 44px; left: 20px; width: 320px; background: var(--glass-strong); backdrop-filter: blur(20px); border: 1px solid var(--border-strong); border-radius: 12px; box-shadow: var(--shadow-lg); overflow: hidden; }
.proj-pop-head { font-size: 11px; font-weight: 600; letter-spacing: 0.10em; text-transform: uppercase; color: var(--text-3); padding: 10px 14px 6px; }
.proj-pop-item { width: 100%; display: flex; align-items: center; gap: 10px; padding: 8px 14px; background: transparent; border: none; color: var(--text); font-size: 13px; cursor: pointer; text-align: left; }
.proj-pop-item:hover, .proj-pop-item.active { background: var(--brand-soft); }
.proj-pop-bar { width: 3px; height: 14px; border-radius: 2px; background: var(--brand-500); }
.proj-pop-name { flex: 1; }
</style>
