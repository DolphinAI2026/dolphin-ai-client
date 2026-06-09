<!-- frontend/src/components/states/ErrorCard.vue
     Shared error-card component · Phase 5 (Wave 1 完成态)
     Per design spec 08.5 章.

     Usage:
       <ErrorCard
         level="err"
         title="aPaaS Token 已过期"
         code="APAAS_TOKEN_EXPIRED_AND_REFRESH_FAILED"
         message="当前平台连接的 admin token 已过期，请联系管理员重新连接。"
         :actions="[
           { label: '去登录', primary: true, onClick: () => goLogin() },
           { label: '查看日志', onClick: () => showLog() },
         ]"
       />

     Levels:
       - 'err'  : 红色左色条 + err-soft icon — 阻断性错误
       - 'warn' : 橙色左色条 + warn-soft icon — 非阻断提醒
       - 'info' : 蓝色左色条 + brand-soft icon — 提示信息（重试中等）

     ErrorCard 是 inline 业务错卡片，不是 toast。
     ElMessage / ElNotification 调用保留 — 那些是短暂 toast，不归 ErrorCard 管。
-->
<template>
  <div class="error-card" :class="`is-${level}`">
    <div class="ec-head">
      <div class="ec-icon">
        <!-- err: i 圆 -->
        <svg v-if="level === 'err'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        <!-- warn: 三角 -->
        <svg v-else-if="level === 'warn'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        <!-- info: 重试圆环 -->
        <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
      </div>
      <h4>{{ title }}</h4>
      <span v-if="code" class="ec-code">{{ code }}</span>
    </div>
    <p class="ec-msg">{{ message }}</p>
    <div v-if="actions && actions.length" class="ec-actions">
      <button
        v-for="(act, i) in actions"
        :key="i"
        type="button"
        class="ec-btn"
        :class="{ 'is-primary': act.primary, 'is-danger': act.danger }"
        @click="act.onClick"
      >{{ act.label }}</button>
    </div>
  </div>
</template>

<script setup lang="ts">
interface ErrorCardAction {
  label: string
  primary?: boolean
  danger?: boolean
  onClick: () => void
}

defineProps<{
  level: 'err' | 'warn' | 'info'
  title: string
  code?: string
  message: string
  actions?: ErrorCardAction[]
}>()
</script>

<style scoped>
.error-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  padding: 24px;
  border-left: 3px solid var(--err);
  display: block;
}

.error-card.is-warn { border-left-color: var(--warn); }
.error-card.is-info { border-left-color: var(--brand); }

.ec-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.ec-icon {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--err-soft);
  color: var(--err);
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.is-warn .ec-icon { background: var(--warn-soft); color: var(--warn); }
.is-info .ec-icon { background: var(--brand-soft); color: var(--brand); }

.ec-head h4 {
  font-size: 15px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
  letter-spacing: -0.005em;
  margin: 0;
  line-height: 1.35;
  flex: 1;
  min-width: 0;
}

.ec-code {
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 11px;
  color: var(--text-3);
  font-weight: 500;
  background: var(--surface-3);
  padding: 2px 6px;
  border-radius: 3px;
  flex-shrink: 0;
  white-space: nowrap;
  max-width: 50%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ec-msg {
  font-size: 13.5px;
  color: var(--text-2);
  line-height: 1.6;
  margin: 0;
}

.ec-actions {
  margin-top: 14px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.ec-btn {
  height: 30px;
  padding: 0 14px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  font-family: inherit;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.ec-btn:hover {
  background: var(--surface-2);
  border-color: var(--line-strong);
  color: var(--text);
}

.ec-btn.is-primary {
  background: var(--brand);
  border-color: var(--brand);
  color: var(--text-inverse);
}

.ec-btn.is-primary:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
}

.ec-btn.is-danger {
  color: var(--err);
  border-color: var(--err-soft);
}

.ec-btn.is-danger:hover {
  background: var(--err-soft);
  border-color: var(--err);
  color: var(--err);
}

.ec-btn:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}
</style>
