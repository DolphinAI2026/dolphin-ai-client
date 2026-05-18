<!-- frontend/src/views/v2/IndustryPage.vue -->
<!--
  Industry Knowledge Base — answers customer's question:
    "如果我想沉淀我们行业（制造 / 零售 / 物流…）的最佳实践，
     像 Palantir 那样有自己的 Ontology + 共用业务对象图谱，怎么办？"

  Renders:
    * top concept strip (5-step value chain)
    * 4 industry packs (制造装备 / 客户运营 / 智慧物流 / 政企服务)
    * for selected pack: Ontology SVG graph + workflows + dicts + howto
  Seed data inline (data.js lines 785-861). All buttons are UI stubs until
  backend `/api/industry-packs` lands. See P2 plan.
-->
<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import ShellTopBar from '@/components/v2/ShellTopBar.vue'
import { useIndustryStore } from '@/stores/industry'
import type {
  IndustryPack,
  OntologyEntity,
  OntologyRelation,
} from '@/api/industry'

const store = useIndustryStore()

const selectedId = ref<string>('pkg-mfg')

// Fallback empty pack — keeps template typesafe before the first fetch resolves.
const EMPTY_PACK: IndustryPack = {
  id: '', name: '', code: '', tone: 'brand', version: '',
  installed: false, default: false, summary: '',
  stats: { entities: 0, relations: 0, workflows: 0, dicts: 0, forms: 0, roles: 0 },
  adopted: [], maintainer: '', updated: '',
}

const cur = computed<IndustryPack>(
  () => store.packs.find(p => p.id === selectedId.value) || store.packs[0] || EMPTY_PACK
)
const ont = computed(() => store.getOntology(selectedId.value))

// Resolve entity helper for SVG relations
function findEntity(code: string): OntologyEntity | undefined {
  return ont.value.entities.find(e => e.code === code)
}
function relMid(r: OntologyRelation): { x1: number; y1: number; x2: number; y2: number; mx: number; my: number } | null {
  const f = findEntity(r.from)
  const t = findEntity(r.to)
  if (!f || !t) return null
  const x1 = f.x + 60, y1 = f.y + 26
  const x2 = t.x + 60, y2 = t.y + 26
  return { x1, y1, x2, y2, mx: (x1 + x2) / 2, my: (y1 + y2) / 2 }
}

onMounted(async () => {
  await store.fetchPacks()
  // Prefer the default pack as the initial selection; fall back to first.
  const def = store.packs.find(p => p.default) || store.packs[0]
  if (def) selectedId.value = def.id
  if (selectedId.value) await store.fetchOntology(selectedId.value)
})

// Lazy-fetch ontology when the user clicks a different pack
watch(selectedId, async (id) => {
  if (!id) return
  if (store.ontologyByPack[id]) return  // already cached
  await store.fetchOntology(id)
})

function onImportZip() { ElMessage.info('企业包导入功能即将上线') }
function onDeriveNew()  { ElMessage.info('派生新包向导即将上线') }
function onExportZip()  { ElMessage.info(`正在导出 ${cur.value.name} ${cur.value.version}...`) }
function onDerivePack() { ElMessage.info('派生企业包向导即将上线') }
async function onInstall() {
  if (cur.value.installed || !cur.value.id) return
  const ok = await store.install(cur.value.id)
  if (ok) {
    ElMessage.success(`${cur.value.name} ${cur.value.version} 已安装到当前租户`)
  } else {
    ElMessage.error(store.error || '安装失败')
  }
}
function onBrowseCommunity() { ElMessage.info('社区包浏览即将上线') }

// Icon set — same 24 viewBox / 1.6 stroke as RailSidebar / AgentsPage.
const ICONS: Record<string, string> = {
  upload:   '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>',
  plus:     '<path d="M12 5v14"/><path d="M5 12h14"/>',
  check:    '<path d="m5 13 4 4 10-10"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
  copy:     '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  chevronR: '<path d="m9 6 6 6-6 6"/>',
  industry: '<path d="M3 21V11l6-4v4l6-4v4l6-4v14H3z"/><path d="M7 17h2"/><path d="M11 17h2"/><path d="M15 17h2"/>',
  network:  '<circle cx="12" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="19" r="2"/><path d="M12 7v3"/><path d="M12 10 6 17"/><path d="M12 10l6 7"/>',
  flow:     '<path d="M5 6h6v4H5z"/><path d="M13 14h6v4h-6z"/><path d="M8 10v4h8"/>',
  dict:     '<path d="M4 19V5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1-2-2z"/><path d="M8 7h6"/><path d="M8 11h6"/>',
  sparkle:  '<path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/><path d="M19 17l1 3 3 1-3 1-1 3-1-3-3-1 3-1z"/>',
}
function renderIcon(name: string, size = 16) {
  const inner = ICONS[name] || ''
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
}
</script>

<template>
  <WorkbenchShell>
    <ShellTopBar />
    <div class="page">
      <div class="page-pad">
        <div class="page-head">
          <div>
            <h1 class="page-title">
              行业知识库
              <el-tooltip
                content="Ontology = 行业模型 / 业务对象图谱。把业务里的实体、关系、流程沉淀成标准包，新建应用一键复用。"
                placement="bottom"
              >
                <span class="badge badge-brand" style="margin-left: 10px; vertical-align: middle; cursor: help;">行业模型 · Beta</span>
              </el-tooltip>
            </h1>
            <div class="page-subtitle">
              <b>把行业最佳实践沉淀成可复用的"行业包"。</b>
              包含 <b>业务对象</b>、<b>对象关系</b>、<b>标准流程</b>、<b>行业字典</b>，
              在新建应用时一键复用。客户可基于已有包派生企业专属包。
            </div>
          </div>
          <div style="display: flex; gap: 8px;">
            <button class="btn btn-secondary" @click="onImportZip">
              <span class="icon" v-html="renderIcon('upload', 13)" /> 导入企业包 (.zip)
            </button>
            <button class="btn btn-primary" @click="onDeriveNew">
              <span class="icon" v-html="renderIcon('plus', 13)" /> 派生新包
            </button>
          </div>
        </div>

        <!-- Top concept strip -->
        <div class="industry-concept">
          <div class="industry-concept-pill">
            <span class="industry-concept-num">01</span>
            <div><b>业务对象</b><span>带字段的标准实体</span></div>
          </div>
          <span class="icon concept-arrow" v-html="renderIcon('chevronR', 14)" />
          <div class="industry-concept-pill">
            <span class="industry-concept-num">02</span>
            <div><b>对象关系</b><span>1:n · n:m · 自引用</span></div>
          </div>
          <span class="icon concept-arrow" v-html="renderIcon('chevronR', 14)" />
          <div class="industry-concept-pill">
            <span class="industry-concept-num">03</span>
            <div><b>标准流程</b><span>含 SLA 与角色</span></div>
          </div>
          <span class="icon concept-arrow" v-html="renderIcon('chevronR', 14)" />
          <div class="industry-concept-pill">
            <span class="industry-concept-num">04</span>
            <div><b>行业字典</b><span>标准状态码 / 行业代码</span></div>
          </div>
          <span class="icon concept-arrow" v-html="renderIcon('chevronR', 14)" />
          <div class="industry-concept-pill industry-concept-pill-final">
            <span class="industry-concept-num">→</span>
            <div><b>新应用秒级起步</b><span>AI Builder 自动复用</span></div>
          </div>
        </div>

        <!-- Pack list -->
        <div class="section-head">
          <div class="section-title">
            行业包 <span class="section-title-count">{{ store.packs.length }}</span>
          </div>
          <div style="display: flex; gap: 8px; align-items: center;">
            <span class="badge badge-emerald">
              <span class="badge-dot" />已安装 {{ store.installedCount }}
            </span>
            <button class="section-action" @click="onBrowseCommunity">浏览社区包 →</button>
          </div>
        </div>

        <div class="industry-pack-grid">
          <button
            v-for="p in store.packs"
            :key="p.id"
            class="industry-pack-card"
            :class="{ 'is-selected': selectedId === p.id }"
            @click="selectedId = p.id"
          >
            <div class="industry-pack-head">
              <div :class="['industry-pack-icon', `tone-${p.tone}`]" v-html="renderIcon('industry', 18)" />
              <div style="flex: 1; min-width: 0;">
                <div class="industry-pack-name">
                  {{ p.name }}
                  <span v-if="p.default" class="badge badge-brand" style="margin-left: 4px;">默认</span>
                </div>
                <div class="industry-pack-meta">
                  <span class="mono">{{ p.code }}</span>
                  <span>·</span>
                  <span class="mono">{{ p.version }}</span>
                  <span>·</span>
                  <span>更新 {{ p.updated }}</span>
                </div>
              </div>
              <span v-if="p.installed" class="badge badge-emerald">
                <span class="icon" v-html="renderIcon('check', 10)" /> 已安装
              </span>
              <span v-else class="badge">未安装</span>
            </div>
            <div class="industry-pack-summary">{{ p.summary }}</div>
            <div class="industry-pack-stats">
              <div><b>{{ p.stats.entities }}</b> 业务对象</div>
              <div><b>{{ p.stats.relations }}</b> 关系</div>
              <div><b>{{ p.stats.workflows }}</b> 流程</div>
              <div><b>{{ p.stats.dicts }}</b> 字典</div>
              <div><b>{{ p.stats.forms }}</b> 表单</div>
              <div><b>{{ p.stats.roles }}</b> 角色</div>
            </div>
            <div class="industry-pack-foot">
              <span class="industry-pack-by">{{ p.maintainer }}</span>
              <span v-if="p.adopted.length > 0" class="industry-pack-adopt">
                已被 {{ p.adopted.length }} 个客户 / 应用采用
              </span>
            </div>
          </button>
        </div>

        <!-- Selected pack detail -- Ontology view -->
        <div class="industry-detail">
          <div class="industry-detail-head">
            <div>
              <div class="industry-detail-title">
                <span
                  :class="['industry-pack-icon', `tone-${cur.tone}`]"
                  style="width: 28px; height: 28px; border-radius: 8px;"
                  v-html="renderIcon('industry', 14)"
                />
                {{ cur.name }} · Ontology
                <span class="mono" style="font-size: 12px; color: var(--text-3); font-weight: 500; margin-left: 6px;">
                  {{ cur.code }} {{ cur.version }}
                </span>
              </div>
              <div style="font-size: 12.5px; color: var(--text-2); margin-top: 4px;">{{ cur.summary }}</div>
            </div>
            <div style="display: flex; gap: 6px;">
              <button class="btn btn-secondary btn-sm" @click="onExportZip">
                <span class="icon" v-html="renderIcon('download', 12)" /> 导出 .zip
              </button>
              <button class="btn btn-secondary btn-sm" @click="onDerivePack">
                <span class="icon" v-html="renderIcon('copy', 12)" /> 派生企业包
              </button>
              <button class="btn btn-primary btn-sm" :disabled="cur.installed" @click="onInstall">
                <template v-if="cur.installed">
                  <span class="icon" v-html="renderIcon('check', 12)" /> 已安装到当前租户
                </template>
                <template v-else>
                  <span class="icon" v-html="renderIcon('download', 12)" /> 安装到当前租户
                </template>
              </button>
            </div>
          </div>

          <div class="industry-onto-grid">
            <!-- Left: Graph -->
            <div class="industry-onto-graph card">
              <div class="industry-onto-graph-head">
                <span class="icon" v-html="renderIcon('network', 13)" />
                <b>业务对象关系图</b>
                <span style="margin-left: auto; font-size: 11px; color: var(--text-3);">
                  {{ ont.entities.length }} 对象 · {{ ont.relations.length }} 关系
                </span>
              </div>
              <svg class="industry-onto-svg" viewBox="0 0 620 480" preserveAspectRatio="xMidYMid meet">
                <defs>
                  <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
                    <path d="M0 0 L10 5 L0 10 z" fill="var(--text-3)" />
                  </marker>
                </defs>
                <!-- Relations -->
                <template v-for="(r, i) in ont.relations" :key="`r-${i}`">
                  <g v-if="relMid(r)" class="industry-onto-edge">
                    <line
                      :x1="relMid(r)!.x1" :y1="relMid(r)!.y1"
                      :x2="relMid(r)!.x2" :y2="relMid(r)!.y2"
                      stroke="var(--border-strong)" stroke-width="1"
                      :stroke-dasharray="r.from === 'work_order' ? '0' : '3 3'"
                      marker-end="url(#arr)"
                    />
                    <text
                      :x="relMid(r)!.mx" :y="relMid(r)!.my"
                      fill="var(--text-3)" font-size="9" text-anchor="middle"
                      class="mono"
                    >{{ r.label }}</text>
                  </g>
                </template>
                <!-- Entities -->
                <g
                  v-for="e in ont.entities"
                  :key="e.code"
                  :class="['industry-onto-node', `industry-onto-node-${e.tone}`, { 'is-hot': e.hot }]"
                >
                  <rect :x="e.x" :y="e.y" width="120" height="52" rx="10" />
                  <text
                    :x="e.x + 60" :y="e.y + 20"
                    text-anchor="middle" font-size="12" font-weight="600" fill="currentColor"
                  >{{ e.name }}</text>
                  <text
                    :x="e.x + 60" :y="e.y + 36"
                    text-anchor="middle" font-size="10" fill="var(--text-3)" class="mono"
                  >{{ e.code }} · {{ e.fields }}f</text>
                </g>
              </svg>
              <div class="industry-onto-graph-foot">
                <span>提示：点击节点可查看字段定义 · 关系标签为语义动词</span>
              </div>
            </div>

            <!-- Right: lists -->
            <div class="industry-onto-side">
              <div class="card card-pad">
                <div class="industry-onto-side-head">标准流程 · {{ ont.workflows.length }}</div>
                <div class="industry-onto-list">
                  <div v-for="(w, i) in ont.workflows" :key="`w-${i}`" class="industry-onto-row">
                    <span class="icon" style="color: var(--brand-text);" v-html="renderIcon('flow', 12)" />
                    <div style="flex: 1; min-width: 0;">
                      <div style="font-size: 12.5px; font-weight: 500;">{{ w.name }}</div>
                      <div style="font-size: 10.5px; color: var(--text-3);">{{ w.nodes }} 节点 · SLA {{ w.sla }}</div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="card card-pad">
                <div class="industry-onto-side-head">
                  关键字典 · {{ ont.dictHighlight.length }}
                  <span style="font-weight: 500; color: var(--text-3);">/ 共 {{ cur.stats.dicts }}</span>
                </div>
                <div class="industry-onto-list">
                  <div v-for="(d, i) in ont.dictHighlight" :key="`d-${i}`" class="industry-onto-row">
                    <span class="icon" style="color: var(--brand-text);" v-html="renderIcon('dict', 12)" />
                    <div style="flex: 1; min-width: 0;">
                      <div style="font-size: 12.5px; font-weight: 500;">{{ d.name }}</div>
                      <div style="font-size: 10.5px; color: var(--text-3);" class="mono">{{ d.code }} · {{ d.items }} 项</div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="industry-howto">
                <div class="industry-howto-head">
                  <span class="icon" v-html="renderIcon('sparkle', 13)" />
                  客户如何沉淀自己的行业
                </div>
                <ol class="industry-howto-list">
                  <li><b>派生</b> 基于「{{ cur.name }}」一键派生「企业专属包」</li>
                  <li><b>扩展</b> 在派生包里增减对象、字段、关系、字典、流程</li>
                  <li><b>验证</b> 用 1-2 个真实应用试用 → SPEC 自动注释为复用</li>
                  <li><b>发布</b> 发布回平台，租户内 / 跨租户均可订阅升级</li>
                </ol>
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  </WorkbenchShell>
</template>

<style scoped>
/* Page chrome */
.page { overflow-y: auto; min-height: 0; background: var(--bg-app); height: 100%; flex: 1; }
.page-pad { padding: 28px 32px 40px; max-width: 1320px; margin: 0 auto; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 22px; }
.page-title { font-size: 22px; font-weight: 600; color: var(--text); letter-spacing: -0.02em; line-height: 1.2; margin: 0; }
.page-subtitle { font-size: 13px; color: var(--text-2); margin-top: 4px; max-width: 760px; line-height: 1.55; }
.page-subtitle b { color: var(--text); font-weight: 600; }

/* Buttons */
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  height: 32px; padding: 0 14px; border-radius: 8px;
  font-size: 13px; font-weight: 500; cursor: pointer;
  border: 1px solid transparent; background: transparent; color: var(--text); font-family: inherit;
  white-space: nowrap; transition: background 0.12s, border-color 0.12s, box-shadow 0.12s;
}
.btn-sm { height: 26px; padding: 0 10px; font-size: 12px; border-radius: 6px; }
.btn-primary { background: var(--brand); color: #fff; box-shadow: 0 1px 2px rgba(28, 21, 73, 0.16), inset 0 -1px 0 rgba(0, 0, 0, 0.15); }
.btn-primary:hover { background: var(--brand-hover); box-shadow: 0 2px 6px var(--brand-ring); }
.btn-primary:disabled { background: var(--surface-3); color: var(--text-3); cursor: not-allowed; box-shadow: none; }
.btn-secondary { background: var(--surface); border-color: var(--border-strong); }
.btn-secondary:hover { border-color: var(--text-4); }
.btn .icon { display: inline-flex; align-items: center; }
.btn .icon :deep(svg) { display: block; }

/* Cards */
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow-xs); }
.card-pad { padding: 16px; }

/* Section heads */
.section-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-top: 22px; margin-bottom: 10px;
}
.section-title { font-size: 14px; font-weight: 600; color: var(--text); display: flex; align-items: center; gap: 8px; }
.section-title-count { font-size: 12px; color: var(--text-3); font-weight: 500; }
.section-action {
  background: transparent; border: 0; cursor: pointer;
  color: var(--brand-text); font-size: 12px; font-weight: 500; font-family: inherit;
  padding: 2px 4px; border-radius: 4px;
}
.section-action:hover { color: var(--brand); }

/* Badges */
.badge {
  display: inline-flex; align-items: center; gap: 4px;
  height: 20px; padding: 0 7px; border-radius: 5px;
  font-size: 11px; font-weight: 500;
  background: var(--surface-3); color: var(--text-2);
  border: 1px solid transparent;
}
.badge-brand { background: var(--brand-soft); color: var(--brand-text); }
.badge-emerald { background: var(--emerald-bg); color: var(--emerald); }
.badge-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: currentColor;
}
.badge .icon { display: inline-flex; align-items: center; }
.badge .icon :deep(svg) { display: block; }

/* Concept strip */
.industry-concept {
  display: flex; align-items: center; gap: 8px;
  padding: 14px 16px; background: var(--surface-2);
  border: 1px solid var(--border); border-radius: 12px;
  margin-bottom: 6px; flex-wrap: wrap;
}
.industry-concept-pill {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 12px; background: var(--surface);
  border: 1px solid var(--border); border-radius: 999px;
  font-size: 12px; color: var(--text);
}
.industry-concept-pill div { display: flex; flex-direction: column; line-height: 1.3; }
.industry-concept-pill b { font-size: 12.5px; font-weight: 600; color: var(--text); }
.industry-concept-pill span:not(.industry-concept-num) { font-size: 10.5px; color: var(--text-3); margin-top: 1px; }
.industry-concept-num {
  font-family: var(--d-font-mono); font-size: 11px; font-weight: 700;
  color: var(--brand-text); background: var(--brand-soft);
  padding: 2px 7px; border-radius: 4px;
}
.industry-concept-pill-final { background: var(--brand-soft); border-color: var(--brand-200); }
.industry-concept-pill-final b { color: var(--brand-text); }
.industry-concept-pill-final .industry-concept-num { background: var(--brand); color: #fff; }
.concept-arrow { display: inline-flex; align-items: center; color: var(--text-4); }
.concept-arrow :deep(svg) { display: block; }

/* Pack grid */
.industry-pack-grid {
  display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin-top: 12px;
}
.industry-pack-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 16px; text-align: left; cursor: pointer; font-family: inherit;
  color: var(--text); display: flex; flex-direction: column; gap: 10px;
  transition: border-color 0.14s, box-shadow 0.14s, transform 0.14s; width: 100%;
}
.industry-pack-card:hover { border-color: var(--border-strong); box-shadow: var(--shadow-md); }
.industry-pack-card.is-selected { border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-ring); }
.industry-pack-head { display: flex; align-items: center; gap: 10px; }
.industry-pack-icon {
  width: 36px; height: 36px; border-radius: 9px;
  display: grid; place-items: center; color: #fff; flex-shrink: 0;
}
.industry-pack-icon :deep(svg) { display: block; }
.industry-pack-icon.tone-amber   { background: linear-gradient(135deg, #FBBF24, #D97706); }
.industry-pack-icon.tone-sky     { background: linear-gradient(135deg, #38BDF8, #0284C7); }
.industry-pack-icon.tone-emerald { background: linear-gradient(135deg, #34D399, #10A37F); }
.industry-pack-icon.tone-rose    { background: linear-gradient(135deg, #F87171, #DC2626); }
.industry-pack-icon.tone-brand   { background: linear-gradient(135deg, var(--brand-400), var(--brand-600)); }
.industry-pack-name { font-size: 14px; font-weight: 600; color: var(--text); }
.industry-pack-meta { font-size: 11px; color: var(--text-3); display: flex; align-items: center; gap: 4px; flex-wrap: wrap; margin-top: 2px; }
.industry-pack-summary { font-size: 12.5px; color: var(--text-2); line-height: 1.55; }
.industry-pack-stats {
  display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px;
  padding: 8px 10px; background: var(--surface-2); border-radius: 8px;
  font-size: 11px; color: var(--text-3);
}
.industry-pack-stats b { color: var(--text); font-weight: 600; font-size: 13px; display: block; }
.industry-pack-foot { display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 11px; color: var(--text-3); }
.industry-pack-adopt { background: var(--brand-soft); color: var(--brand-text); padding: 2px 8px; border-radius: 999px; font-weight: 500; }

/* Detail */
.industry-detail { margin-top: 22px; }
.industry-detail-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 12px; margin-bottom: 14px; flex-wrap: wrap;
}
.industry-detail-title {
  display: flex; align-items: center; gap: 10px;
  font-size: 18px; font-weight: 600; letter-spacing: -0.015em;
}

/* Ontology grid */
.industry-onto-grid {
  display: grid; grid-template-columns: 1.4fr 1fr; gap: 18px;
}
.industry-onto-graph {
  display: flex; flex-direction: column;
  overflow: hidden;
}
.industry-onto-graph-head {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 16px; border-bottom: 1px solid var(--border);
  font-size: 13px; color: var(--text);
}
.industry-onto-graph-head .icon { display: inline-flex; align-items: center; color: var(--text-2); }
.industry-onto-graph-head .icon :deep(svg) { display: block; }
.industry-onto-svg {
  width: 100%; height: 480px;
  background:
    linear-gradient(var(--surface-2) 1px, transparent 1px) 0 0 / 24px 24px,
    linear-gradient(90deg, var(--surface-2) 1px, transparent 1px) 0 0 / 24px 24px;
  background-color: var(--surface);
}
.industry-onto-node rect {
  fill: var(--surface);
  stroke: var(--border-strong); stroke-width: 1.5;
}
.industry-onto-node-brand rect   { stroke: var(--brand-400); }
.industry-onto-node-sky rect     { stroke: var(--sky); }
.industry-onto-node-amber rect   { stroke: var(--amber); }
.industry-onto-node-rose rect    { stroke: var(--rose); }
.industry-onto-node-emerald rect { stroke: var(--emerald); }
.industry-onto-node.is-hot rect {
  stroke: var(--brand); stroke-width: 2;
  filter: drop-shadow(0 0 0 3px var(--brand-ring));
}
.industry-onto-node-brand   { color: var(--brand-text); }
.industry-onto-node-sky     { color: var(--sky); }
.industry-onto-node-amber   { color: var(--amber); }
.industry-onto-node-rose    { color: var(--rose); }
.industry-onto-node-emerald { color: var(--emerald); }
.industry-onto-graph-foot {
  padding: 8px 16px; border-top: 1px solid var(--border);
  font-size: 11px; color: var(--text-3);
}

.industry-onto-side { display: flex; flex-direction: column; gap: 14px; }
.industry-onto-side-head {
  font-size: 12.5px; font-weight: 600; color: var(--text);
  margin-bottom: 8px;
}
.industry-onto-list { display: flex; flex-direction: column; gap: 6px; }
.industry-onto-row {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 10px; background: var(--surface-2);
  border-radius: 7px;
}
.industry-onto-row .icon { display: inline-flex; align-items: center; }
.industry-onto-row .icon :deep(svg) { display: block; }

.industry-howto {
  padding: 16px; border-radius: 12px;
  background: var(--ai-soft); border: 1px solid var(--ai-soft-2);
}
.industry-howto-head {
  display: flex; align-items: center; gap: 6px;
  font-size: 12.5px; font-weight: 600; color: var(--ai-text);
}
.industry-howto-head .icon { display: inline-flex; align-items: center; }
.industry-howto-head .icon :deep(svg) { display: block; }
.industry-howto-list {
  margin: 8px 0 0; padding-left: 18px;
  font-size: 12px; color: var(--text-2); line-height: 1.8;
}
.industry-howto-list b { color: var(--ai-text); font-weight: 600; }
.industry-howto-list li::marker { color: var(--ai); font-weight: 700; }

.mono { font-family: var(--d-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace); }
</style>
