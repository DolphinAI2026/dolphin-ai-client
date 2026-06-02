<template>
  <div v-if="visible" class="im-overlay" @click="$emit('close')">
    <div class="im-card" @click.stop>
      <!-- header -->
      <div class="im-head">
        <span class="im-head-icon" v-html="iconSvg('store', 20, 2)"></span>
        <div class="im-head-text">
          <div class="im-title">{{ mode === 'lib' ? '发布到资产库' : '装回应用' }}</div>
          <div class="im-sub">{{ kitName }}<template v-if="mode !== 'lib' && appName"> → {{ appName }}</template></div>
        </div>
        <span class="im-badge" :class="compiled ? 'is-ok' : 'is-err'">
          <span v-html="iconSvg(compiled ? 'check' : 'x', 12, 2.6)"></span>
          {{ compiled ? '编译通过' : '编译失败' }}
        </span>
      </div>

      <!-- consequences -->
      <div class="im-body">
        <div v-for="r in rows" :key="r.title" class="im-row">
          <span class="im-row-icon" v-html="iconSvg(r.icon, 14, 2)"></span>
          <div class="im-row-text">
            <div class="im-row-title">{{ r.title }}</div>
            <div class="im-row-desc">{{ r.desc }}</div>
          </div>
        </div>
      </div>

      <!-- footer -->
      <div class="im-foot">
        <button class="im-btn im-ghost" :disabled="loading" @click="$emit('close')">取消</button>
        <button class="im-btn im-dark" :disabled="!compiled || loading" @click="$emit('confirm')">
          <span v-if="!loading" v-html="iconSvg('check', 15, 2.4)"></span>
          {{ loading ? (mode === 'lib' ? '发布中…' : '装回中…') : (mode === 'lib' ? '确认发布' : '确认装回') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
export interface InstallRow { icon: string; title: string; desc: string }

withDefaults(defineProps<{
  visible: boolean
  /** 'bound' = 装回应用 / 'lib' = 发布到资产库 */
  mode?: 'bound' | 'lib'
  kitName?: string
  appName?: string
  rows?: InstallRow[]
  compiled?: boolean
  loading?: boolean
}>(), {
  mode: 'bound', kitName: '', appName: '', rows: () => [], compiled: true, loading: false,
})

defineEmits<{ (e: 'close'): void; (e: 'confirm'): void }>()

// 自包含图标(stroke, 24 grid)— 取自设计原型 components.jsx ICON_PATHS
const ICON_PATHS: Record<string, string> = {
  store: '<path d="M3 9 5 4h14l2 5"/><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9"/><path d="M3 9h18"/>',
  doc: '<path d="M6 2h8l4 4v16H6z"/><path d="M14 2v4h4"/>',
  flow: '<circle cx="5" cy="12" r="2.5"/><circle cx="19" cy="6" r="2.5"/><circle cx="19" cy="18" r="2.5"/><path d="M7.4 11 16.6 6.8M7.4 13l9.2 4.2"/>',
  lock: '<rect x="4.5" y="10" width="15" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  x: '<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>',
}
function iconSvg(name: string, size: number, stroke: number): string {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round">${ICON_PATHS[name] || ''}</svg>`
}
</script>

<style scoped>
.im-overlay {
  position: fixed; inset: 0; z-index: 1200;
  background: rgba(8, 16, 36, 0.55); backdrop-filter: blur(6px);
  display: grid; place-items: center;
  animation: im-fade 0.18s;
}
.im-card {
  width: min(92%, 480px); background: var(--surface);
  border-radius: 18px; box-shadow: var(--sh-5); overflow: hidden;
  animation: im-pop 0.25s var(--ease-spring);
}
.im-head {
  display: flex; align-items: center; gap: 12px;
  padding: 18px 20px; border-bottom: 1px solid var(--line);
}
.im-head-icon {
  width: 40px; height: 40px; border-radius: 11px; flex-shrink: 0;
  display: grid; place-items: center; background: var(--blue-950); color: #fff;
}
.im-head-text { flex: 1; min-width: 0; }
.im-title { font-size: 16px; font-weight: 700; letter-spacing: -0.01em; color: var(--text); }
.im-sub { font-size: 11.5px; color: var(--text-3); font-family: var(--font-mono); margin-top: 2px; }
.im-badge {
  display: inline-flex; align-items: center; gap: 5px; flex-shrink: 0;
  font-size: 11px; font-weight: 600; padding: 4px 9px; border-radius: 999px; white-space: nowrap;
}
.im-badge.is-ok { color: var(--ok); background: var(--ok-soft); }
.im-badge.is-err { color: var(--err); background: var(--err-soft); }

.im-body { padding: 16px; }
.im-row { display: flex; align-items: flex-start; gap: 11px; padding: 9px 8px; }
.im-row-icon {
  width: 26px; height: 26px; border-radius: 7px; flex-shrink: 0;
  display: grid; place-items: center; background: var(--brand-soft); color: var(--brand);
}
.im-row-text { flex: 1; min-width: 0; }
.im-row-title { font-size: 12.5px; font-weight: 600; color: var(--text); }
.im-row-desc { font-size: 11.5px; color: var(--text-3); margin-top: 1px; line-height: 1.45; }

.im-foot { display: flex; gap: 10px; padding: 0 20px 20px; justify-content: flex-end; }
.im-btn {
  display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 14px;
  border-radius: 8px; font-size: 12.5px; font-weight: 600; cursor: pointer;
  border: 1px solid transparent; transition: all 0.15s var(--ease, ease);
}
.im-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.im-ghost { background: var(--surface); color: var(--text-2); border-color: var(--line-strong); }
.im-ghost:hover:not(:disabled) { border-color: var(--brand-ring); color: var(--brand); }
.im-dark { background: var(--blue-950); color: #fff; font-family: var(--font-mono); }
.im-dark:hover:not(:disabled) { transform: translateY(-1px); }

@keyframes im-fade { from { opacity: 0; } to { opacity: 1; } }
@keyframes im-pop { from { opacity: 0; transform: translateY(12px) scale(0.97); } to { opacity: 1; transform: none; } }
</style>
