<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'
import type { RailSession, RailSessionGroup } from '@/composables/railSessions'

const props = defineProps<{
  systemSessions: RailSession[]
  applicationGroups: RailSessionGroup[]
  activeSystemSessionId?: string
}>()

const emit = defineEmits<{
  (event: 'new-system-session'): void
  (event: 'open-system-session', session: RailSession): void
  (event: 'rename-system-session', session: RailSession): void
  (event: 'delete-system-session', session: RailSession): void
  (event: 'open-application-session', session: RailSession): void
  (event: 'new-application-session', shellSessionId: string): void
}>()

const collapsed = ref(new Set<string>())
const sessionMenuOpenId = ref<string | null>(null)
const showAllSystemSessions = ref(false)

const visibleSystemSessions = computed(() => {
  if (showAllSystemSessions.value || props.systemSessions.length <= 3) return props.systemSessions
  const recent = props.systemSessions.slice(0, 3)
  const active = props.systemSessions.find(session => String(session.id) === String(props.activeSystemSessionId))
  if (!active || recent.some(session => String(session.id) === String(active.id))) return recent
  return [...recent, active]
})

const hiddenSystemSessionCount = computed(() =>
  Math.max(0, props.systemSessions.length - visibleSystemSessions.value.length),
)

function toggle(key: string) {
  const next = new Set(collapsed.value)
  next.has(key) ? next.delete(key) : next.add(key)
  collapsed.value = next
}

function applicationGroupKey(group: RailSessionGroup): string {
  return `application:${group.shellSessionId || group.label}`
}

function sessionRunning(session: RailSession): boolean {
  return ['running', 'processing'].includes(String(session.status || '').toLowerCase())
}

function toggleSessionMenu(session: RailSession) {
  const key = String(session.id)
  sessionMenuOpenId.value = sessionMenuOpenId.value === key ? null : key
}

function renameSession(session: RailSession) {
  sessionMenuOpenId.value = null
  emit('rename-system-session', session)
}

function deleteSession(session: RailSession) {
  sessionMenuOpenId.value = null
  emit('delete-system-session', session)
}
</script>

<template>
  <div class="sas-sections">
    <section class="sas-section" data-session-section="system">
      <div class="sas-section-header">
        <button type="button" class="sas-section-toggle" @click="toggle('system')">
          <AppIcon name="arrow-right" :size="12" :class="{ expanded: !collapsed.has('system') }" />
          <span>系统会话</span>
          <span class="sas-count">{{ systemSessions.length }}</span>
        </button>
        <button
          type="button"
          class="sas-icon-button"
          title="新建系统会话"
          aria-label="新建系统会话"
          @click="emit('new-system-session')"
        >
          <AppIcon name="plus" :size="15" />
        </button>
      </div>

      <div v-if="!collapsed.has('system')" class="sas-items">
        <div
          v-for="session in visibleSystemSessions"
          :key="session.id"
          class="sas-item"
          :class="{ active: activeSystemSessionId === String(session.id) }"
          :title="session.title || '未命名会话'"
          @click="emit('open-system-session', session)"
        >
          <span class="sas-state" :class="{ running: sessionRunning(session) }" />
          <span class="sas-title">{{ session.title || '未命名会话' }}</span>
          <div class="sas-manage" @click.stop>
            <button
              type="button"
              class="sas-more"
              title="管理系统会话"
              aria-label="管理系统会话"
              :aria-expanded="sessionMenuOpenId === String(session.id)"
              @click="toggleSessionMenu(session)"
            >
              <AppIcon name="more" :size="14" />
            </button>
            <div v-if="sessionMenuOpenId === String(session.id)" class="sas-menu" role="menu">
              <button type="button" role="menuitem" @click="renameSession(session)">
                <AppIcon name="edit" :size="14" />
                重命名
              </button>
              <button type="button" class="danger" role="menuitem" @click="deleteSession(session)">
                <AppIcon name="x" :size="14" />
                删除
              </button>
            </div>
          </div>
        </div>
        <div v-if="hiddenSystemSessionCount" class="sas-more-row">
          <button type="button" class="sas-more-sessions" @click="showAllSystemSessions = true">
            展开更多
            <span>（{{ hiddenSystemSessionCount }}）</span>
          </button>
        </div>
        <div v-else-if="showAllSystemSessions && systemSessions.length > 3" class="sas-more-row">
          <button type="button" class="sas-more-sessions" @click="showAllSystemSessions = false">
            收起较早会话
          </button>
        </div>
        <div v-if="!systemSessions.length" class="sas-empty">暂无系统会话</div>
      </div>
    </section>

    <section class="sas-section application" data-session-section="application">
      <div class="sas-section-header">
        <button type="button" class="sas-section-toggle" @click="toggle('applications')">
          <AppIcon name="arrow-right" :size="12" :class="{ expanded: !collapsed.has('applications') }" />
          <span>应用会话</span>
          <span class="sas-count">{{ applicationGroups.reduce((sum, group) => sum + group.items.length, 0) }}</span>
        </button>
      </div>

      <div v-if="!collapsed.has('applications')" class="sas-app-groups">
        <div v-for="group in applicationGroups" :key="applicationGroupKey(group)" class="sas-app-group">
          <div class="sas-app-header">
            <button type="button" class="sas-app-toggle" @click="toggle(applicationGroupKey(group))">
              <AppIcon
                name="arrow-right"
                :size="11"
                :class="{ expanded: !collapsed.has(applicationGroupKey(group)) }"
              />
              <span>{{ group.label }}</span>
              <span class="sas-count">{{ group.items.length }}</span>
            </button>
            <button
              v-if="group.shellSessionId"
              type="button"
              class="sas-app-new"
              title="在此应用中新建会话"
              aria-label="在此应用中新建会话"
              @click="emit('new-application-session', group.shellSessionId)"
            >
              <AppIcon name="plus" :size="13" />
            </button>
          </div>
          <div v-if="!collapsed.has(applicationGroupKey(group))" class="sas-items app-items">
            <button
              v-for="session in group.items"
              :key="session.id"
              type="button"
              class="sas-item app-item"
              :title="session.title || '未命名会话'"
              @click="emit('open-application-session', session)"
            >
              <span class="sas-state" :class="{ running: sessionRunning(session) }" />
              <span class="sas-title">{{ session.title || '未命名会话' }}</span>
            </button>
          </div>
        </div>
        <div v-if="!applicationGroups.length" class="sas-empty">暂无应用会话</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.sas-sections { display: flex; flex-direction: column; gap: 8px; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: thin; scrollbar-color: #cfd7e3 transparent; }
.sas-sections::-webkit-scrollbar { width: 5px; }
.sas-sections::-webkit-scrollbar-thumb { background: #cfd7e3; border-radius: 999px; }
.sas-section + .sas-section { padding-top: 8px; border-top: 1px solid #e7ecf3; }
.sas-section-header, .sas-app-header { display: flex; align-items: center; min-width: 0; }
.sas-section-header { min-height: 28px; padding: 0 4px 4px; }
.sas-section-toggle, .sas-app-toggle { min-width: 0; display: flex; align-items: center; border: 0; background: transparent; cursor: pointer; }
.sas-section-toggle { flex: 1; gap: 6px; padding: 4px 2px; color: #6f7d91; font: inherit; font-size: 10.5px; font-weight: 700; letter-spacing: .04em; text-align: left; }
.sas-section-toggle :deep(.app-icon), .sas-app-toggle :deep(.app-icon) { transition: transform .14s ease; }
.sas-section-toggle :deep(.app-icon.expanded), .sas-app-toggle :deep(.app-icon.expanded) { transform: rotate(90deg); }
.sas-count { margin-left: auto; color: #9aa5b5; font-size: 10px; font-weight: 500; letter-spacing: 0; }
.sas-icon-button, .sas-app-new { display: grid; place-items: center; padding: 0; color: #637188; background: transparent; border: 1px solid transparent; border-radius: 6px; cursor: pointer; }
.sas-icon-button { width: 26px; height: 26px; }
.sas-icon-button:hover, .sas-app-new:hover { color: #1f56c7; background: #e9f1ff; border-color: #d4e2fb; }
.sas-items { display: flex; flex-direction: column; gap: 1px; }
.sas-item { width: 100%; min-width: 0; min-height: 30px; display: flex; align-items: center; gap: 8px; padding: 4px 5px 4px 8px; color: #68768a; background: transparent; border: 0; border-radius: 7px; font: inherit; font-size: 12px; text-align: left; cursor: pointer; }
.sas-item:hover { color: #2458bd; background: #edf3ff; }
.sas-item.active { color: #1f56c7; background: #e5efff; font-weight: 600; }
.sas-state { width: 5px; height: 5px; flex: 0 0 auto; border-radius: 50%; background: #c2cad6; }
.sas-state.running { background: #2f65d5; box-shadow: 0 0 0 3px rgba(47, 101, 213, .12); animation: sas-pulse 1.6s ease-in-out infinite; }
.sas-title { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sas-manage { position: relative; flex: 0 0 auto; }
.sas-more { width: 22px; height: 22px; display: grid; place-items: center; padding: 0; opacity: 0; color: #758298; background: transparent; border: 0; border-radius: 6px; cursor: pointer; }
.sas-item:hover .sas-more, .sas-item.active .sas-more, .sas-more[aria-expanded="true"] { opacity: 1; }
.sas-more:hover { color: #1f56c7; background: #fff; }
.sas-menu { position: absolute; right: 0; top: 26px; z-index: 30; width: 112px; padding: 4px; border: 1px solid #dfe5ee; border-radius: 8px; background: #fff; box-shadow: 0 8px 24px rgba(28, 43, 68, .14); }
.sas-menu button { width: 100%; min-height: 30px; display: flex; align-items: center; gap: 8px; padding: 0 8px; color: #46556b; background: transparent; border: 0; border-radius: 6px; font: inherit; font-size: 12px; text-align: left; cursor: pointer; }
.sas-menu button:hover { color: #1f56c7; background: #edf3ff; }
.sas-menu button.danger { color: #bb3f3f; }
.sas-menu button.danger:hover { color: #a82f2f; background: #fff0f0; }
.sas-app-groups { display: flex; flex-direction: column; gap: 4px; }
.sas-app-header { min-height: 27px; }
.sas-app-toggle { flex: 1; gap: 5px; padding: 4px 6px; overflow: hidden; color: #758297; font: inherit; font-size: 11px; text-align: left; }
.sas-app-toggle > span:not(.app-icon):not(.sas-count) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sas-app-new { width: 23px; height: 23px; margin-right: 3px; }
.app-items { padding-left: 7px; }
.app-item { padding-left: 8px; }
.sas-empty { padding: 12px 8px; color: #9aa5b5; font-size: 11px; text-align: center; }
.sas-more-row { display: flex; justify-content: center; padding: 3px 0 4px; }
.sas-more-sessions { padding: 4px 8px; color: #718096; background: transparent; border: 0; border-radius: 6px; font: inherit; font-size: 11px; cursor: pointer; }
.sas-more-sessions:hover { color: #2458bd; background: #edf3ff; }
html[data-theme="dark"] .sas-section + .sas-section { border-color: #273243; }
html[data-theme="dark"] .sas-section-toggle, html[data-theme="dark"] .sas-app-toggle, html[data-theme="dark"] .sas-item { color: #9eacc0; }
html[data-theme="dark"] .sas-sections { scrollbar-color: #3b485a transparent; }
html[data-theme="dark"] .sas-sections::-webkit-scrollbar-thumb { background: #3b485a; }
html[data-theme="dark"] .sas-item:hover { color: #cbd8eb; background: #1d2838; }
html[data-theme="dark"] .sas-item.active { color: #a9c5ff; background: #22304a; }
html[data-theme="dark"] .sas-menu { background: #1b2431; border-color: #334155; }
html[data-theme="dark"] .sas-more-sessions { color: #9eacc0; }
html[data-theme="dark"] .sas-more-sessions:hover { color: #a9c5ff; background: #26344a; }
@keyframes sas-pulse { 0%, 100% { opacity: .65; } 50% { opacity: 1; } }
</style>
