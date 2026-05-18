<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/project'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import ShellTopBar from '@/components/v2/ShellTopBar.vue'

const route = useRoute()
const router = useRouter()
const store = useProjectStore()
const activeTab = ref<'overview' | 'apps' | 'members' | 'industry' | 'env'>('overview')

const project = computed(() => store.projects.find(p => p.id === route.params.id))

watch(() => route.params.id, (id) => {
  if (typeof id === 'string') store.setCurrent(id)
}, { immediate: true })

const milestones = computed(() => ([
  { title: '需求确认', status: 'done', date: '2026-04-10' },
  { title: 'SPEC v1 完成', status: 'done', date: '2026-04-22' },
  { title: '测试环境上线', status: 'doing', date: '2026-05-12' },
  { title: '生产上线', status: 'planned', date: '2026-06-05' },
]))
const activity = computed(() => ([
  { who: 'mars', what: '提交 SPEC v3 草稿', when: '2 分钟前' },
  { who: '客户业务方', what: '审批通过资产报废流程', when: '今天 09:32' },
  { who: '陈青羽', what: '更新设备模型字段', when: '昨天 17:45' },
]))
</script>

<template>
  <WorkbenchShell>
    <ShellTopBar />
    <div class="page">
      <div class="page-pad">
        <div class="page-head">
          <div>
            <div class="page-crumb"><a @click.prevent="router.push('/projects')">项目</a> · <b>{{ project?.name ?? '未找到' }}</b></div>
            <h1 class="page-title">{{ project?.name ?? '未找到项目' }}</h1>
            <div class="page-subtitle">{{ project?.customerName }}</div>
          </div>
          <div class="page-head-actions">
            <button class="btn btn-secondary">项目设置</button>
            <button class="btn btn-primary">进入对话</button>
          </div>
        </div>

        <div class="tabs">
          <button v-for="t in [
            { k: 'overview', l: '概览' },
            { k: 'apps',     l: '应用' },
            { k: 'members',  l: '成员与角色' },
            { k: 'industry', l: '行业包绑定' },
            { k: 'env',      l: '环境与部署' },
          ]" :key="t.k" class="tab" :class="{ active: activeTab === t.k }" @click="activeTab = t.k as any">{{ t.l }}</button>
        </div>

        <section v-if="activeTab === 'overview'" class="tab-pane">
          <div class="overview-grid">
            <div class="card card-pad">
              <div class="section-title">里程碑</div>
              <div class="milestones">
                <div v-for="m in milestones" :key="m.title" class="milestone" :class="m.status">
                  <div class="milestone-dot" />
                  <div class="milestone-body"><div class="milestone-title">{{ m.title }}</div><div class="milestone-date">{{ m.date }}</div></div>
                </div>
              </div>
            </div>
            <div class="card card-pad">
              <div class="section-title">最近活动</div>
              <div class="activity">
                <div v-for="a in activity" :key="a.who + a.what" class="activity-row">
                  <div class="activity-avatar">{{ a.who.slice(0, 1) }}</div>
                  <div class="activity-body"><div><b>{{ a.who }}</b> {{ a.what }}</div><div class="activity-when">{{ a.when }}</div></div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section v-else-if="activeTab === 'apps'" class="tab-pane">
          <div class="card card-pad">
            <div class="section-title">本项目下的应用 <span class="section-title-count">{{ project?.appCount ?? 0 }}</span></div>
            <div class="page-subtitle">即将在 P1 后期接入 <code>api/application.ts</code> 实际数据，并按 <code>project_id</code> 过滤。</div>
          </div>
        </section>

        <section v-else-if="activeTab === 'members'" class="tab-pane">
          <div class="card card-pad">
            <div class="section-title">成员与项目角色 <span class="section-title-count">{{ project?.memberCount ?? 0 }}</span></div>
            <div class="page-subtitle">项目角色（项目负责人 / 实施顾问 / 前端 / 后端 / 客户业务方 / 客户 IT / 观察员）用于权限和通知，不影响 UI 隐藏。完整成员管理在 P2 完成。</div>
          </div>
        </section>

        <section v-else-if="activeTab === 'industry'" class="tab-pane">
          <div class="card card-pad">
            <div class="section-title">行业包绑定</div>
            <div class="page-subtitle">绑定后 AI Builder 在新建应用时会优先复用包内业务对象 / 流程 / 字典。当前绑定：{{ project?.industryPackId ?? '未绑定' }}。完整绑定 UI 在 P3 完成。</div>
          </div>
        </section>

        <section v-else-if="activeTab === 'env'" class="tab-pane">
          <div class="card card-pad">
            <div class="section-title">平台环境</div>
            <div class="page-subtitle">本项目使用 {{ project?.envCount ?? 0 }} 个环境（开发 / 测试 / 生产）。完整环境状态与部署历史在 <a @click.prevent="router.push('/runtime')">/运行与发布</a> 维护。</div>
          </div>
        </section>
      </div>
    </div>
  </WorkbenchShell>
</template>

<style scoped>
.page { overflow-y: auto; min-height: 0; background: var(--bg-app); height: 100%; flex: 1; }
.page-pad { padding: 28px 32px 40px; max-width: 1320px; margin: 0 auto; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 22px; }
.page-crumb { font-size: 12px; color: var(--text-3); margin-bottom: 4px; }
.page-crumb a { color: var(--text-2); cursor: pointer; }
.page-crumb a:hover { color: var(--brand-text); }
.page-crumb b { color: var(--text); font-weight: 600; }
.page-title { font-size: 24px; font-weight: 600; color: var(--text); letter-spacing: -0.02em; line-height: 1.2; margin: 0; }
.page-subtitle { font-size: 13px; color: var(--text-2); margin-top: 4px; max-width: 760px; }
.page-head-actions { display: flex; gap: 8px; }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin: 4px 0 18px; }
.tab { height: 36px; padding: 0 14px; background: transparent; border: none; border-bottom: 2px solid transparent; color: var(--text-2); font-size: 13px; font-weight: 500; cursor: pointer; font-family: inherit; }
.tab:hover { color: var(--text); }
.tab.active { color: var(--brand-text); border-bottom-color: var(--brand); }
.tab-pane { display: flex; flex-direction: column; gap: 18px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow-xs); }
.card-pad { padding: 18px; }
.section-title { font-size: 14px; font-weight: 600; color: var(--text); display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.section-title-count { font-size: 12px; color: var(--text-3); font-weight: 500; }
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 32px; padding: 0 14px; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; border: 1px solid transparent; background: transparent; color: var(--text); font-family: inherit; }
.btn-primary { background: var(--brand); color: #fff; }
.btn-primary:hover { background: var(--brand-hover); }
.btn-secondary { background: var(--surface); color: var(--text); border-color: var(--border-strong); box-shadow: var(--shadow-xs); }
.btn-secondary:hover { background: var(--surface-2); }
.overview-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 18px; }
.milestones { display: flex; flex-direction: column; gap: 10px; }
.milestone { display: flex; align-items: center; gap: 12px; padding: 8px 4px; }
.milestone-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--surface-3); border: 2px solid var(--border-strong); flex-shrink: 0; }
.milestone.done .milestone-dot { background: var(--emerald); border-color: var(--emerald); }
.milestone.doing .milestone-dot { background: var(--amber); border-color: var(--amber); animation: pulse 1.6s infinite; }
.milestone-body { flex: 1; }
.milestone-title { font-size: 13px; font-weight: 500; color: var(--text); }
.milestone-date { font-size: 11.5px; color: var(--text-3); font-family: var(--d-font-mono); margin-top: 2px; }
@keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 var(--amber-bg); } 50% { box-shadow: 0 0 0 8px transparent; } }
.activity { display: flex; flex-direction: column; gap: 12px; }
.activity-row { display: flex; gap: 10px; align-items: flex-start; }
.activity-avatar { width: 24px; height: 24px; border-radius: 50%; background: linear-gradient(135deg, var(--brand-400), var(--brand-600)); color: #fff; font-size: 11px; font-weight: 600; display: grid; place-items: center; flex-shrink: 0; }
.activity-body { font-size: 12.5px; color: var(--text); line-height: 1.5; }
.activity-when { font-size: 11px; color: var(--text-3); margin-top: 2px; }
</style>
