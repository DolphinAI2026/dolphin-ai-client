<template>
  <BuilderFrame :breadcrumbs="[{ label: 'DevOps' }, { label: currentLabel }]">
    <template #actions>
      <button class="builder-btn" type="button" @click="active = 'runs'">
        <Refresh />
        刷新
      </button>
      <button class="builder-btn builder-btn-primary" type="button">
        <Plus />
        新建流水线
      </button>
    </template>

    <main class="devops-layout">
      <aside class="devops-side">
        <div class="side-label">DevOps</div>
        <button
          v-for="item in nav"
          :key="item.key"
          class="side-link"
          :class="{ active: active === item.key }"
          type="button"
          @click="active = item.key"
        >
          <component :is="item.icon" />
          {{ item.label }}
        </button>
      </aside>

      <section class="devops-main">
        <div class="builder-section-head">
          <div>
            <div class="builder-section-kicker">Pipeline</div>
            <h1 class="builder-section-title">{{ currentLabel }}</h1>
            <p class="builder-section-sub">用 mock 数据先把部署、环境和审批链路跑通。</p>
          </div>
        </div>

        <template v-if="active === 'overview' || active === 'envs'">
          <section class="env-flow">
            <article v-for="env in demoEnvironments" :key="env.key" class="builder-panel env-card">
              <div class="env-card-title">
                <span>{{ env.name }}</span>
                <span class="builder-dot" :class="{ warn: env.status === 'approval', ok: env.status === 'healthy' }" />
              </div>
              <div class="env-card-meta">{{ env.version }} · {{ env.apps }} apps · {{ env.status }}</div>
            </article>
          </section>
        </template>

        <section class="builder-panel">
          <table class="builder-table">
            <thead>
              <tr><th>流水线</th><th>应用</th><th>分支</th><th>状态</th><th>成功率</th><th>最后运行</th></tr>
            </thead>
            <tbody>
              <tr v-for="pipeline in demoPipelines" :key="pipeline.name">
                <td><strong>{{ pipeline.name }}</strong></td>
                <td>{{ pipeline.app }}</td>
                <td style="font-family: var(--b-mono)">{{ pipeline.branch }}</td>
                <td>
                  <span class="builder-tag">
                    <span class="builder-dot" :class="pipeline.status === '失败' ? 'err' : pipeline.status === '运行中' ? '' : 'ok'" />
                    {{ pipeline.status }}
                  </span>
                </td>
                <td style="font-family: var(--b-mono)">{{ pipeline.success }}</td>
                <td>{{ pipeline.time }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </section>
    </main>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Check, Files, Operation, Plus, Promotion, Refresh } from '@element-plus/icons-vue'
import BuilderFrame from '@/components/BuilderFrame.vue'
import { demoEnvironments, demoPipelines } from '@/data/builderMock'

const active = ref('overview')
const nav = [
  { key: 'overview', label: '总览', icon: Operation },
  { key: 'pipelines', label: '流水线', icon: Promotion },
  { key: 'runs', label: '运行历史', icon: Files },
  { key: 'envs', label: '环境拓扑', icon: Operation },
  { key: 'approvals', label: '审批中心', icon: Check },
]

const currentLabel = computed(() => nav.find(item => item.key === active.value)?.label ?? '总览')
</script>
