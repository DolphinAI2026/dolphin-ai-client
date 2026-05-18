<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore, type Project } from '@/stores/project'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import ShellTopBar from '@/components/v2/ShellTopBar.vue'

const router = useRouter()
const store = useProjectStore()

onMounted(() => {
  store.fetchProjects()
})

const stageClass: Record<string, string> = {
  '已上线': 'badge-emerald',
  '开发中': 'badge-amber',
  '测试中': 'badge-sky',
  '设计中': 'badge-brand',
  '维护中': 'badge-outline',
}
function open(p: Project) { router.push(`/projects/${p.id}`) }
function newProject() { /* P2: open project create modal */ }
</script>

<template>
  <WorkbenchShell>
    <ShellTopBar />
    <div class="page">
      <div class="page-pad">
        <div class="page-head">
          <div>
            <h1 class="page-title">项目</h1>
            <div class="page-subtitle">按客户实施分组的工作空间，每个项目包含多个应用、SPEC 版本、成员、行业包绑定与目标环境。</div>
          </div>
          <button class="btn btn-primary" @click="newProject">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14"/><path d="M5 12h14"/></svg>
            新建项目
          </button>
        </div>

        <div v-if="store.loading && !store.projects.length" class="proj-empty">加载中…</div>
        <div v-else-if="store.error && !store.projects.length" class="proj-empty proj-empty-error">加载项目失败：{{ store.error }}</div>
        <div v-else-if="!store.projects.length" class="proj-empty">暂无项目，点击右上角“新建项目”开始。</div>
        <div v-else class="proj-grid">
          <button v-for="p in store.projects" :key="p.id" class="card card-interactive proj-card" @click="open(p)">
            <div class="proj-card-head">
              <div class="proj-card-bar" />
              <div class="proj-card-name">{{ p.name }}</div>
              <span class="badge" :class="stageClass[p.stage]">{{ p.stage }}</span>
            </div>
            <div class="proj-card-customer">{{ p.customerName }}</div>
            <div class="proj-card-progress">
              <div class="proj-card-progress-track">
                <div class="proj-card-progress-fill" :style="{ width: p.progress + '%' }" />
              </div>
              <div class="proj-card-progress-text">{{ p.progress }}%</div>
            </div>
            <div class="proj-card-stats">
              <div><b>{{ p.appCount }}</b> 应用</div>
              <div><b>{{ p.deployCount }}</b> 部署</div>
              <div><b>{{ p.memberCount }}</b> 成员</div>
              <div><b>{{ p.envCount }}</b> 环境</div>
            </div>
          </button>
        </div>
      </div>
    </div>
  </WorkbenchShell>
</template>

<style scoped>
.page { overflow-y: auto; min-height: 0; background: var(--bg-app); height: 100%; flex: 1; }
.page-pad { padding: 28px 32px 40px; max-width: 1320px; margin: 0 auto; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 22px; }
.page-title { font-size: 22px; font-weight: 600; color: var(--text); letter-spacing: -0.02em; line-height: 1.2; margin: 0; }
.page-subtitle { font-size: 13px; color: var(--text-2); margin-top: 4px; max-width: 760px; }
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 32px; padding: 0 14px; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; border: 1px solid transparent; background: transparent; color: var(--text); transition: background 0.12s, border-color 0.12s, transform 0.12s, box-shadow 0.12s; white-space: nowrap; font-family: inherit; }
.btn-primary { background: var(--brand); color: #fff; box-shadow: 0 1px 2px rgba(28, 21, 73, 0.16), inset 0 -1px 0 rgba(0, 0, 0, 0.15); }
.btn-primary:hover { background: var(--brand-hover); box-shadow: 0 2px 6px var(--brand-ring); }
.proj-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }
.proj-empty { padding: 48px 16px; text-align: center; font-size: 13px; color: var(--text-3); border: 1px dashed var(--border); border-radius: 12px; background: var(--surface); }
.proj-empty-error { color: var(--danger, #c44); border-color: var(--danger, #c44); }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow-xs); padding: 18px; text-align: left; cursor: pointer; font-family: inherit; color: var(--text); width: 100%; }
.card-interactive { transition: border-color 0.14s, box-shadow 0.14s, transform 0.14s; }
.card-interactive:hover { border-color: var(--border-strong); box-shadow: var(--shadow-md); }
.proj-card-head { display: flex; align-items: center; gap: 8px; }
.proj-card-bar { width: 3px; height: 16px; border-radius: 2px; background: var(--brand-500); }
.proj-card-name { flex: 1; font-size: 14.5px; font-weight: 600; color: var(--text); letter-spacing: -0.01em; }
.proj-card-customer { font-size: 12px; color: var(--text-3); margin-top: 6px; }
.proj-card-progress { display: flex; align-items: center; gap: 10px; margin-top: 14px; }
.proj-card-progress-track { flex: 1; height: 4px; background: var(--surface-3); border-radius: 2px; overflow: hidden; }
.proj-card-progress-fill { height: 100%; background: var(--brand); border-radius: 2px; transition: width 0.3s var(--ease, ease-out); }
.proj-card-progress-text { font-size: 11.5px; font-family: var(--d-font-mono); color: var(--text-2); }
.proj-card-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 14px; font-size: 11.5px; color: var(--text-3); }
.proj-card-stats b { color: var(--text); font-weight: 600; }
.badge { display: inline-flex; align-items: center; gap: 4px; height: 20px; padding: 0 7px; border-radius: 5px; font-size: 11px; font-weight: 500; background: var(--surface-3); color: var(--text-2); border: 1px solid transparent; }
</style>
