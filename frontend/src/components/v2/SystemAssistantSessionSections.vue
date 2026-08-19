<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'
import type { RailSession } from '@/composables/railSessions'
import type { CodeRailSession, CodeRailSessionGroup } from './codeRailHistory'

const props = defineProps<{
  systemSessions: RailSession[]
  applicationGroups: CodeRailSessionGroup[]
  hiddenApplicationCount?: number
  activeSystemSessionId?: string
  /**
   * Keep the Code-route identity explicit at this rendering boundary.  The
   * outer rail also supplies its shared matcher, but a history row must still
   * be able to render selected when that callback is refreshed a tick later
   * than the route after iframe navigation.
   */
  activeApplicationShellSessionId?: string
  activeApplicationRuntimeSessionId?: string
  isApplicationSessionActive?: (session: RailSession) => boolean
}>()

const emit = defineEmits<{
  (event: 'new-system-session'): void
  (event: 'open-system-session', session: RailSession): void
  (event: 'rename-system-session', session: RailSession): void
  (event: 'archive-system-session', session: RailSession): void
  (event: 'open-application-session', session: RailSession): void
  (event: 'new-application-session', shellSessionId: string): void
  (event: 'archive-application-session', session: CodeRailSession): void
  (event: 'hide-application', logicalApplicationId: string): void
  (event: 'restore-applications'): void
}>()

const collapsed = ref(new Set<string>())
const sessionMenuOpenId = ref<string | null>(null)
const showAllSystemSessions = ref(false)
const expandedApplicationGroups = ref(new Set<string>())
const APPLICATION_VISIBLE_SESSION_LIMIT = 3

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

function applicationGroupKey(group: CodeRailSessionGroup): string {
  return `application:${group.logicalApplicationId}`
}

function groupHasLocation(group: CodeRailSessionGroup, location: 'local' | 'remote'): boolean {
  return group.availableLocations.includes(location)
}

function visibleApplicationSessions(group: CodeRailSessionGroup): CodeRailSession[] {
  if (expandedApplicationGroups.value.has(applicationGroupKey(group))) return group.items
  const recent = group.items.slice(0, APPLICATION_VISIBLE_SESSION_LIMIT)
  const active = group.items.find(session => props.isApplicationSessionActive?.(session))
  if (!active || recent.some(session => String(session.id) === String(active.id))) return recent
  return [...recent, active]
}

function hiddenApplicationSessionCount(group: CodeRailSessionGroup): number {
  return Math.max(0, group.items.length - visibleApplicationSessions(group).length)
}

function toggleApplicationSessions(group: CodeRailSessionGroup) {
  const key = applicationGroupKey(group)
  const next = new Set(expandedApplicationGroups.value)
  next.has(key) ? next.delete(key) : next.add(key)
  expandedApplicationGroups.value = next
}

function sessionRunning(session: RailSession): boolean {
  return ['running', 'processing'].includes(String(session.status || '').toLowerCase())
}

function applicationSessionActive(session: CodeRailSession): boolean {
  if (props.isApplicationSessionActive?.(session)) return true
  if (session.source !== 'code-agent') return false
  // Runtime IDs are globally unique.  The rail index can retain an older
  // shell public ID while the active Code URL has the newest public ID after a
  // rebind, so require the shell only for a shell-only route with no runtime.
  const activeRuntimeSessionId = String(props.activeApplicationRuntimeSessionId || '')
  if (activeRuntimeSessionId) {
    return String(session.runtimeSessionId || '') === activeRuntimeSessionId
  }
  return String(session.shellSessionId || '') === String(props.activeApplicationShellSessionId || '')
}

function toggleSessionMenu(session: RailSession) {
  const key = String(session.id)
  sessionMenuOpenId.value = sessionMenuOpenId.value === key ? null : key
}

function renameSession(session: RailSession) {
  sessionMenuOpenId.value = null
  emit('rename-system-session', session)
}

function archiveSystemSession(session: RailSession) {
  sessionMenuOpenId.value = null
  emit('archive-system-session', session)
}

function archiveApplicationSession(session: CodeRailSession) {
  sessionMenuOpenId.value = null
  emit('archive-application-session', session)
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
              <button type="button" role="menuitem" @click="archiveSystemSession(session)">
                <AppIcon name="archive" :size="14" />
                归档会话
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
              <span class="sas-app-identity">
                <span class="sas-app-name">{{ group.label }}</span>
              </span>
              <span
                v-if="groupHasLocation(group, 'remote')"
                class="sas-location-icon"
                title="远程环境"
                aria-label="远程环境"
              >
                <AppIcon name="globe" :size="12" />
              </span>
              <span
                v-if="groupHasLocation(group, 'local')"
                class="sas-location-icon"
                title="本机项目"
                aria-label="本机项目"
              >
                <AppIcon name="laptop" :size="12" />
              </span>
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
            <button
              type="button"
              class="sas-app-remove"
              title="从侧边栏移除；重新打开应用会自动恢复"
              aria-label="从侧边栏移除项目"
              @click="emit('hide-application', group.logicalApplicationId)"
            >
              <AppIcon name="x" :size="13" />
            </button>
          </div>
          <div v-if="!collapsed.has(applicationGroupKey(group))" class="sas-items app-items">
            <div
              v-for="session in visibleApplicationSessions(group)"
              :key="session.id"
              role="button"
              tabindex="0"
              class="sas-item app-item"
              :class="{ active: applicationSessionActive(session) }"
              :title="session.title || '未命名会话'"
              @click="emit('open-application-session', session)"
              @keydown.enter="emit('open-application-session', session)"
              @keydown.space.prevent="emit('open-application-session', session)"
            >
              <span class="sas-state" :class="{ running: sessionRunning(session) }" />
              <span class="sas-title">{{ session.title || '未命名会话' }}</span>
              <span
                class="sas-location-icon"
                :title="session.executionLocation === 'local' ? '本机项目' : '远程环境'"
                :aria-label="session.executionLocation === 'local' ? '本机项目' : '远程环境'"
              >
                <AppIcon :name="session.executionLocation === 'local' ? 'laptop' : 'globe'" :size="12" />
              </span>
              <div class="sas-manage" @click.stop>
                <button
                  type="button"
                  class="sas-more"
                  title="管理应用会话"
                  aria-label="管理应用会话"
                  :aria-expanded="sessionMenuOpenId === String(session.id)"
                  @click="toggleSessionMenu(session)"
                >
                  <AppIcon name="more" :size="14" />
                </button>
                <div v-if="sessionMenuOpenId === String(session.id)" class="sas-menu" role="menu">
                  <button type="button" role="menuitem" @click="archiveApplicationSession(session)">
                    <AppIcon name="archive" :size="14" />
                    归档会话
                  </button>
                </div>
              </div>
            </div>
            <div v-if="hiddenApplicationSessionCount(group)" class="sas-more-row">
              <button type="button" class="sas-more-sessions" @click="toggleApplicationSessions(group)">
                展开更多
                <span>（{{ hiddenApplicationSessionCount(group) }}）</span>
              </button>
            </div>
            <div
              v-else-if="expandedApplicationGroups.has(applicationGroupKey(group)) && group.items.length > APPLICATION_VISIBLE_SESSION_LIMIT"
              class="sas-more-row"
            >
              <button type="button" class="sas-more-sessions" @click="toggleApplicationSessions(group)">
                收起较早会话
              </button>
            </div>
          </div>
        </div>
        <div v-if="hiddenApplicationCount" class="sas-hidden-applications">
          <span>已移除 {{ hiddenApplicationCount }} 个项目</span>
          <button type="button" @click="emit('restore-applications')">全部恢复</button>
        </div>
        <div v-if="!applicationGroups.length" class="sas-empty">暂无应用会话</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.sas-sections { min-width: 0; display: flex; flex: 0 0 auto; flex-direction: column; gap: 5px; }
.sas-section + .sas-section { padding-top: 8px; border-top: 1px solid #e7ecf3; }
.sas-section-header, .sas-app-header { display: flex; align-items: center; min-width: 0; }
.sas-section-header { min-height: 27px; padding: 0 4px 3px; }
.sas-section-toggle, .sas-app-toggle { min-width: 0; display: flex; align-items: center; border: 0; background: transparent; cursor: pointer; }
.sas-section-toggle { flex: 1; gap: 6px; padding: 4px 2px; color: #708096; font: inherit; font-size: 10.5px; font-weight: 700; letter-spacing: .045em; text-align: left; }
.sas-section-toggle :deep(.app-icon), .sas-app-toggle :deep(.app-icon) { transition: transform .14s ease; }
.sas-section-toggle :deep(.app-icon.expanded), .sas-app-toggle :deep(.app-icon.expanded) { transform: rotate(90deg); }
.sas-count { margin-left: auto; color: #9aa5b5; font-size: 10px; font-weight: 500; letter-spacing: 0; }
.sas-icon-button, .sas-app-new, .sas-app-remove { display: grid; place-items: center; padding: 0; color: #637188; background: transparent; border: 1px solid transparent; border-radius: 6px; cursor: pointer; }
.sas-icon-button { width: 26px; height: 26px; }
.sas-icon-button:hover, .sas-app-new:hover { color: #1f56c7; background: #e9f1ff; border-color: #d4e2fb; }
.sas-items { display: flex; flex-direction: column; gap: 2px; }
/* Give each history row a quiet surface of its own: the rail and conversation
   canvas are both near-white, so a transparent row made the history hard to
   scan until hover.  Keep the contrast intentionally light. */
.sas-item { width: 100%; min-width: 0; min-height: 31px; display: flex; align-items: center; gap: 7px; padding: 4px 5px 4px 8px; color: #607086; background: #fbfcfe; border: 1px solid #edf1f5; border-radius: 7px; font: inherit; font-size: 12px; text-align: left; cursor: pointer; }
.sas-item:hover { color: #2458bd; background: #edf3ff; border-color: #dce8fb; }
.sas-item.active { color: #1f56c7; background: #e5efff; border-color: #cbdcf7; box-shadow: inset 3px 0 0 #2f65d5; font-weight: 600; }
.sas-state { width: 5px; height: 5px; flex: 0 0 auto; border-radius: 50%; background: #c2cad6; }
.sas-state.running { background: #2f65d5; box-shadow: 0 0 0 3px rgba(47, 101, 213, .12); animation: sas-pulse 1.6s ease-in-out infinite; }
.sas-title { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sas-manage { position: relative; flex: 0 0 auto; }
.sas-more { width: 22px; height: 22px; display: grid; place-items: center; padding: 0; opacity: 0; color: #758298; background: transparent; border: 0; border-radius: 6px; cursor: pointer; }
.sas-item:hover .sas-more, .sas-item.active .sas-more, .sas-more:focus-visible, .sas-more[aria-expanded="true"] { opacity: 1; }
.sas-more:hover { color: #1f56c7; background: #fff; }
.sas-menu { position: absolute; right: 0; top: 26px; z-index: 30; width: 112px; padding: 4px; border: 1px solid #dfe5ee; border-radius: 8px; background: #fff; box-shadow: 0 8px 24px rgba(28, 43, 68, .14); }
.sas-menu button { width: 100%; min-height: 30px; display: flex; align-items: center; gap: 8px; padding: 0 8px; color: #46556b; background: transparent; border: 0; border-radius: 6px; font: inherit; font-size: 12px; text-align: left; cursor: pointer; }
.sas-menu button:hover { color: #1f56c7; background: #edf3ff; }
.sas-menu button.danger { color: #bb3f3f; }
.sas-menu button.danger:hover { color: #a82f2f; background: #fff0f0; }
.sas-app-groups { display: flex; flex-direction: column; gap: 3px; }
.sas-app-header { min-height: 28px; border-radius: 7px; }
.sas-app-header:hover { background: #f3f6fa; }
.sas-app-toggle { flex: 1; gap: 5px; padding: 5px 6px; overflow: hidden; color: #65758a; font: inherit; font-size: 11px; text-align: left; }
.sas-app-identity { min-width: 0; flex: 1 1 auto; overflow: hidden; }
.sas-app-name { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sas-location-icon { display: inline-flex; flex: 0 0 auto; align-items: center; color: #92a0b3; }
.sas-location { max-width: 92px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sas-app-new { width: 23px; height: 23px; margin-right: 1px; opacity: 0; }
.sas-app-header:hover .sas-app-new, .sas-app-new:focus-visible { opacity: 1; }
.sas-app-remove { width: 23px; height: 23px; margin-right: 3px; opacity: 0; }
.sas-app-header:hover .sas-app-remove, .sas-app-remove:focus-visible { opacity: 1; }
.sas-app-remove:hover { color: #a34b4b; background: #fff1f1; border-color: #f2d7d7; }
.app-items { padding-left: 7px; }
.app-item { padding-left: 8px; }
.sas-empty { padding: 12px 8px; color: #9aa5b5; font-size: 11px; text-align: center; }
.sas-more-row { display: flex; justify-content: center; padding: 3px 0 4px; }
.sas-more-sessions { padding: 4px 8px; color: #718096; background: transparent; border: 0; border-radius: 6px; font: inherit; font-size: 11px; cursor: pointer; }
.sas-more-sessions:hover { color: #2458bd; background: #edf3ff; }
.sas-hidden-applications { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin: 4px 3px 0; padding: 6px 7px; color: #7d8999; background: #f4f6f9; border-radius: 7px; font-size: 10.5px; }
.sas-hidden-applications button { padding: 0; color: #3764bc; background: transparent; border: 0; font: inherit; cursor: pointer; }
.sas-hidden-applications button:hover { text-decoration: underline; }
html[data-theme="dark"] .sas-section + .sas-section { border-color: #273243; }
html[data-theme="dark"] .sas-section-toggle, html[data-theme="dark"] .sas-app-toggle, html[data-theme="dark"] .sas-item { color: #9eacc0; }
html[data-theme="dark"] .sas-item { background: #182230; border-color: #263448; }
html[data-theme="dark"] .sas-item:hover { color: #cbd8eb; background: #1d2838; border-color: #344966; }
html[data-theme="dark"] .sas-item.active { color: #d5e4ff; background: #283b5c; border-color: #3c5680; box-shadow: inset 3px 0 0 #7da5f8; }
html[data-theme="dark"] .sas-menu { background: #1b2431; border-color: #334155; }
html[data-theme="dark"] .sas-more-sessions { color: #9eacc0; }
html[data-theme="dark"] .sas-more-sessions:hover { color: #a9c5ff; background: #26344a; }
@keyframes sas-pulse { 0%, 100% { opacity: .65; } 50% { opacity: 1; } }
</style>
