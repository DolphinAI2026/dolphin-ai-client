<template>
  <BuilderFrame :breadcrumbs="[{ label: '组件市场' }]">
    <main class="marketplace-page builder-page">
      <section class="marketplace-header page-head">
        <div>
          <h1 class="page-title">组件市场</h1>
          <p class="page-subtitle">{{ marketSummary }}</p>
        </div>
      </section>

      <section class="marketplace-toolbar" aria-label="组件筛选和操作">
        <div class="marketplace-tabs" role="tablist" aria-label="组件分类">
          <button
            v-for="item in categories"
            :key="item.key"
            class="marketplace-tab"
            type="button"
            :class="{ active: selectedCategory === item.key }"
            role="tab"
            :aria-selected="selectedCategory === item.key"
            @click="selectedCategory = item.key"
          >
            <span>{{ item.label }}</span>
            <span v-if="item.count" class="marketplace-tab-count">{{ item.count }}</span>
          </button>
        </div>

        <div class="marketplace-toolbar-right">
          <el-input
            v-model="keyword"
            :prefix-icon="Search"
            placeholder="搜索组件名称、标签..."
            clearable
            class="market-search"
          />
          <button class="btn btn-secondary marketplace-toolbar-action" type="button" @click="$router.push('/coding')">
            <el-icon><Monitor /></el-icon>
            <span>AI Coding</span>
          </button>
          <button class="btn btn-primary marketplace-toolbar-action" type="button" @click="publishTip">
            <el-icon><Upload /></el-icon>
            <span>发布组件</span>
          </button>

          <div class="marketplace-view-toggle" aria-label="视图切换">
            <button
              class="marketplace-view-btn"
              :class="{ active: viewMode === 'list' }"
              type="button"
              title="列表视图"
              @click="viewMode = 'list'"
            >
              <el-icon><List /></el-icon>
            </button>
            <button
              class="marketplace-view-btn"
              :class="{ active: viewMode === 'card' }"
              type="button"
              title="卡片视图"
              @click="viewMode = 'card'"
            >
              <el-icon><Grid /></el-icon>
            </button>
          </div>
        </div>
      </section>

      <section class="marketplace-content" :class="`is-${viewMode}`" v-loading="loading">
        <div v-if="visibleComponents.length === 0 && !loading" class="empty-state">
          <div class="empty-icon">组</div>
          <strong>暂无组件</strong>
          <span>从 AI Coding 发布组件后，会在这里沉淀为团队资产。</span>
        </div>

        <div v-else-if="viewMode === 'list'" class="marketplace-table">
          <div class="marketplace-table-head">
            <span>组件</span>
            <span>分类</span>
            <span>版本</span>
            <span>标签</span>
            <span>下载</span>
            <span>更新</span>
            <span aria-hidden="true"></span>
          </div>

          <div
            v-for="comp in visibleComponents"
            :key="comp.id"
            class="marketplace-row"
            role="button"
            tabindex="0"
            @click="openDetail(comp)"
            @keyup.enter="openDetail(comp)"
          >
            <div class="marketplace-row-main">
              <span class="marketplace-avatar" :style="componentAccentStyle(comp)">{{ componentInitial(comp) }}</span>
              <span class="marketplace-row-copy">
                <strong>{{ comp.name }}</strong>
                <span>{{ comp.description || '暂无描述' }}</span>
              </span>
            </div>

            <div>
              <span class="marketplace-stage-pill">{{ categoryLabel(comp.category) }}</span>
            </div>

            <div class="marketplace-version">v{{ comp.version || '1.0.0' }}</div>

            <div class="marketplace-tags">
              <span v-for="tag in normalizedTags(comp).slice(0, 3)" :key="tag">{{ tag }}</span>
            </div>

            <div class="marketplace-downloads">
              <el-icon><Download /></el-icon>
              <span>{{ comp.download_count || 0 }}</span>
            </div>

            <div class="marketplace-updated">{{ componentUpdatedLabel(comp) }}</div>

            <div class="marketplace-row-actions" @click.stop>
              <button class="marketplace-mini-action primary" type="button" @click="downloadComponent(comp)">下载</button>
              <button class="marketplace-mini-action" type="button" @click="openDetail(comp)">详情</button>
              <el-dropdown
                v-if="comp.author_id === currentUserId"
                trigger="click"
                placement="bottom-end"
                @command="() => unpublishComponent(comp)"
              >
                <button class="marketplace-mini-action marketplace-more-action" type="button" title="更多操作" aria-label="更多操作">
                  <el-icon><MoreFilled /></el-icon>
                </button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="unpublish" class="marketplace-more-danger">下架组件</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
        </div>

        <div v-else class="component-grid">
          <article
            v-for="comp in visibleComponents"
            :key="comp.id"
            class="component-card"
            @click="openDetail(comp)"
          >
            <div class="card-head">
              <div class="card-icon" :class="categoryTone(comp.category)">
                <el-icon><component :is="categoryIcon(comp.category)" /></el-icon>
              </div>
              <div class="card-title">
                <h2>{{ comp.name }}</h2>
                <div>
                  <span class="category-chip">{{ categoryLabel(comp.category) }}</span>
                  <span class="version">v{{ comp.version || '1.0.0' }}</span>
                </div>
              </div>
            </div>
            <p class="card-desc">{{ comp.description || '暂无描述' }}</p>
            <div class="card-tags">
              <span v-for="tag in normalizedTags(comp).slice(0, 3)" :key="tag">{{ tag }}</span>
            </div>
            <footer class="card-footer">
              <span class="author">{{ comp.author_name || 'AI Coding' }}</span>
              <span class="downloads">
                <el-icon><Download /></el-icon>
                {{ comp.download_count || 0 }}
              </span>
            </footer>
          </article>
        </div>
      </section>
    </main>

    <el-dialog
      v-model="detailVisible"
      :title="selectedComp?.name || '组件详情'"
      width="680px"
      class="market-dialog"
      :close-on-click-modal="true"
    >
      <div v-if="selectedComp" class="detail-panel">
        <div class="detail-head">
          <div class="card-icon large" :class="categoryTone(selectedComp.category)">
            <el-icon><component :is="categoryIcon(selectedComp.category)" /></el-icon>
          </div>
          <div>
            <h2>{{ selectedComp.name }}</h2>
            <p>
              {{ categoryLabel(selectedComp.category) }} · v{{ selectedComp.version || '1.0.0' }} ·
              {{ selectedComp.author_name || 'AI Coding' }}
            </p>
          </div>
        </div>
        <p class="detail-desc">{{ selectedComp.description || '暂无描述' }}</p>
        <div class="card-tags">
          <span v-for="tag in normalizedTags(selectedComp)" :key="tag">{{ tag }}</span>
        </div>
        <pre v-if="selectedComp.readme" class="readme">{{ selectedComp.readme }}</pre>
        <div class="detail-actions">
          <el-button type="primary" :loading="downloading" @click="downloadComponent(selectedComp)">
            <el-icon><Download /></el-icon>
            下载组件
          </el-button>
          <el-button
            v-if="selectedComp.author_id === currentUserId"
            type="danger"
            plain
            @click="unpublishComponent(selectedComp)"
          >
            下架
          </el-button>
        </div>
      </div>
    </el-dialog>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Box, Collection, Download, Grid, List, Monitor, MoreFilled, Search, Tickets, Upload } from '@element-plus/icons-vue'
import { marketplaceApi, type MarketplaceComponent } from '@/api/marketplace'
import { useUserStore } from '@/stores/user'
import BuilderFrame from '@/components/BuilderFrame.vue'

const userStore = useUserStore()
const currentUserId = computed(() => userStore.user?.id)

const keyword = ref('')
const selectedCategory = ref('')
const sortBy = ref<'latest' | 'popular'>('latest')
const viewMode = ref<'list' | 'card'>('list')
const loading = ref(false)
const components = ref<MarketplaceComponent[]>([])
const detailVisible = ref(false)
const selectedComp = ref<MarketplaceComponent | null>(null)
const downloading = ref(false)

const categoryDefs = [
  { key: '', label: '全部' },
  { key: 'form-component', label: '表单组件' },
  { key: 'form-page', label: '页面' },
  { key: 'backend-api', label: '后端接口' },
]

const categories = computed(() =>
  categoryDefs.map(item => ({
    ...item,
    count: item.key ? components.value.filter(comp => comp.category === item.key).length : components.value.length,
  })),
)

const marketSummary = computed(() => {
  const total = components.value.length
  const formCount = components.value.filter(comp => comp.category === 'form-component').length
  const pageCount = components.value.filter(comp => comp.category === 'form-page').length
  return `${total} 个组件 · ${formCount} 个表单组件 · ${pageCount} 个页面`
})

const visibleComponents = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  const rows = components.value.filter(comp => {
    const hitCategory = !selectedCategory.value || comp.category === selectedCategory.value
    const source = `${comp.name} ${comp.description || ''} ${normalizedTags(comp).join(' ')}`.toLowerCase()
    return hitCategory && (!text || source.includes(text))
  })

  return [...rows].sort((a, b) => {
    if (sortBy.value === 'popular') return (b.download_count || 0) - (a.download_count || 0)
    return new Date(b.published_at || b.updated_at || 0).getTime() - new Date(a.published_at || a.updated_at || 0).getTime()
  })
})

async function loadComponents() {
  loading.value = true
  try {
    components.value = await marketplaceApi.list({ sort: 'latest' })
  } catch (e: any) {
    ElMessage.error(e.message || '加载组件列表失败')
  } finally {
    loading.value = false
  }
}

function openDetail(comp: MarketplaceComponent) {
  selectedComp.value = comp
  detailVisible.value = true
}

function publishTip() {
  ElMessage.info('请在 AI Coding 工作区生成组件后发布到组件市场')
}

async function downloadComponent(comp: MarketplaceComponent) {
  downloading.value = true
  try {
    await marketplaceApi.download(comp.id)
    comp.download_count = (comp.download_count || 0) + 1
    ElMessage.success('下载成功')
  } catch (e: any) {
    ElMessage.error(e.message || '下载失败')
  } finally {
    downloading.value = false
  }
}

async function unpublishComponent(comp: MarketplaceComponent) {
  try {
    await ElMessageBox.confirm('确定要下架此组件吗？此操作不可恢复。', '确认下架', { type: 'warning' })
    await marketplaceApi.unpublish(comp.id)
    ElMessage.success('已下架')
    detailVisible.value = false
    await loadComponents()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e.message || '下架失败')
  }
}

function normalizedTags(comp: MarketplaceComponent) {
  return comp.tags?.length ? comp.tags : [categoryLabel(comp.category)]
}

function categoryLabel(cat: string): string {
  const labels: Record<string, string> = {
    'form-component': '表单组件',
    'form-page': '页面',
    'form-list': '列表视图',
    'backend-api': '后端接口',
  }
  return labels[cat] || '组件'
}

function categoryTone(cat: string) {
  if (cat === 'form-page') return 'tone-amber'
  if (cat === 'backend-api') return 'tone-red'
  if (cat === 'form-component') return 'tone-purple'
  return 'tone-green'
}

function categoryIcon(cat: string) {
  if (cat === 'form-page') return Collection
  if (cat === 'backend-api') return Tickets
  if (cat === 'form-component') return Grid
  return Box
}

const COMPONENT_ACCENTS = ['#1D4ED8', '#047857', '#B45309', '#0E7490', '#C2410C', '#7C3AED']

function nameHash(name: string): number {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return h
}

function componentInitial(comp: MarketplaceComponent): string {
  const source = String(comp.name || comp.category || '组').trim()
  const first = Array.from(source).find(char => char.trim()) || '组'
  return /[a-z]/.test(first) ? first.toUpperCase() : first
}

function componentAccentStyle(comp: MarketplaceComponent) {
  const seed = comp.name || comp.category || String(comp.id)
  return { background: COMPONENT_ACCENTS[nameHash(seed) % COMPONENT_ACCENTS.length] }
}

function normalizeTimestamp(value?: string | null) {
  if (!value) return ''
  const normalized = String(value).trim()
  const hasTimezone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(normalized)
  const isDateTime = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(normalized)
  return isDateTime && !hasTimezone ? `${normalized.replace(' ', 'T')}Z` : normalized
}

function componentTimeMs(value?: string | null) {
  const normalized = normalizeTimestamp(value)
  if (!normalized) return 0
  const time = new Date(normalized).getTime()
  return Number.isFinite(time) ? time : 0
}

function relativeTime(value?: string | null) {
  if (!value) return '-'
  const time = componentTimeMs(value)
  if (!Number.isFinite(time) || time <= 0) return String(value).slice(0, 16)
  const diffMs = Date.now() - time
  if (diffMs < 60_000) return '刚刚'
  const minutes = Math.floor(diffMs / 60_000)
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  if (hours < 48) return '昨天'
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} 天前`
  return String(value).slice(0, 10)
}

function componentUpdatedLabel(comp: MarketplaceComponent) {
  return relativeTime(comp.published_at || comp.updated_at)
}

onMounted(loadComponents)
</script>

<style scoped>
.marketplace-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 22px 28px 32px;
}

.marketplace-header {
  max-width: 1240px;
  width: 100%;
  min-height: 0;
  margin: 0 auto;
  padding: 0;
  background: transparent;
  position: static;
  backdrop-filter: none;
}

.marketplace-header h1 {
  margin: 0;
  color: var(--text);
  font-size: var(--t-h2, 24px);
  line-height: 1.25;
  font-weight: var(--fw-bold, 700);
  letter-spacing: -0.01em;
}

.marketplace-header p {
  margin: 6px 0 0;
  color: var(--text-3);
  font-size: 13px;
  line-height: normal;
}

.marketplace-toolbar {
  max-width: 1240px;
  width: 100%;
  margin: 8px auto 2px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.marketplace-toolbar-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-shrink: 0;
}

.marketplace-toolbar-action {
  height: 36px;
  padding: 0 16px;
  border-radius: var(--r-3, 8px);
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
}

.marketplace-tabs {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  border-bottom: 1px solid var(--line);
  padding: 0;
  background: transparent;
}

.marketplace-tab {
  position: relative;
  min-width: 58px;
  height: 36px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--text-3);
  font: inherit;
  font-size: 13px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 14px;
  transition: color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.marketplace-tab:hover:not(.active) {
  color: var(--text);
}

.marketplace-tab.active {
  color: var(--brand);
  font-weight: var(--fw-semibold, 600);
}

.marketplace-tab.active::after {
  content: '';
  position: absolute;
  left: 6px;
  right: 6px;
  bottom: -1px;
  height: 2px;
  background: var(--brand);
  border-radius: 1px;
}

.marketplace-tab-count {
  min-width: 18px;
  padding: 1px 6px;
  border-radius: var(--r-full, 999px);
  background: var(--surface-2);
  color: var(--text-3);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 15px;
}

.marketplace-tab.active .marketplace-tab-count {
  background: var(--brand-soft);
  color: var(--brand);
}

.market-search {
  width: 260px;
}

.marketplace-view-toggle {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface-2);
  padding: 2px;
  flex-shrink: 0;
}

.marketplace-view-btn {
  width: 32px;
  height: 28px;
  border: 0;
  border-radius: var(--r-2, 6px);
  background: transparent;
  color: var(--text-3);
  display: grid;
  place-items: center;
  cursor: pointer;
}

.marketplace-view-btn:hover:not(.active) {
  color: var(--text);
}

.marketplace-view-btn.active {
  background: var(--surface);
  color: var(--brand);
  box-shadow: var(--sh-1);
}

.marketplace-content {
  max-width: 1240px;
  width: 100%;
  margin: 0 auto;
}

.marketplace-table {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
  box-shadow: var(--sh-1);
}

.marketplace-table-head,
.marketplace-row {
  display: grid;
  grid-template-columns:
    minmax(260px, 1.35fr)
    minmax(92px, 0.42fr)
    minmax(80px, 0.34fr)
    minmax(190px, 0.76fr)
    minmax(72px, 0.32fr)
    minmax(84px, 0.36fr)
    minmax(168px, 0.58fr);
  align-items: center;
  column-gap: 14px;
}

.marketplace-table-head {
  min-height: 36px;
  padding: 0 14px;
  border-bottom: 1px solid var(--line);
  color: var(--text-3);
  font-size: 12px;
  font-weight: var(--fw-medium, 500);
  background: var(--surface-2);
}

.marketplace-row {
  min-height: 64px;
  padding: 9px 14px;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
  outline: none;
}

.marketplace-row:last-child {
  border-bottom: 0;
}

.marketplace-row:hover,
.marketplace-row:focus-visible {
  background: var(--surface-2);
}

.marketplace-row-main {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 11px;
}

.marketplace-avatar {
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  border-radius: var(--r-3, 8px);
  display: grid;
  place-items: center;
  color: var(--text-inverse, #fff);
  font-size: 13px;
  font-weight: var(--fw-bold, 700);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.18);
}

.marketplace-row-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.marketplace-row-copy strong {
  min-width: 0;
  color: var(--text);
  font-size: 14px;
  font-weight: var(--fw-semibold, 600);
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.marketplace-row-copy span {
  min-width: 0;
  color: var(--text-3);
  font-size: 12px;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.marketplace-stage-pill {
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--r-full, 999px);
  background: var(--brand-soft);
  color: var(--brand);
  padding: 0 10px;
  font-size: 11.5px;
  font-weight: var(--fw-semibold, 600);
  white-space: nowrap;
}

.marketplace-version,
.marketplace-downloads,
.marketplace-updated {
  color: var(--text-3);
  font-size: 12.5px;
}

.marketplace-downloads {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.marketplace-tags {
  min-width: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}

.marketplace-tags span,
.card-tags span,
.category-chip,
.version {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 8px;
  border-radius: var(--r-1, 4px);
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 11px;
  font-weight: var(--fw-medium, 500);
  white-space: nowrap;
}

.marketplace-row-actions {
  min-width: 0;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.marketplace-mini-action {
  min-height: 30px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: var(--surface);
  color: var(--text-2);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 12px;
  font-family: inherit;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  white-space: nowrap;
}

.marketplace-mini-action:hover {
  border-color: var(--brand-ring);
  color: var(--brand);
  background: var(--brand-soft);
}

.marketplace-mini-action.primary {
  background: var(--brand);
  border-color: var(--brand);
  color: var(--text-inverse, #fff);
}

.marketplace-mini-action.primary:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
  color: var(--text-inverse, #fff);
}

.marketplace-more-action {
  width: 30px;
  min-width: 30px;
  padding: 0;
  color: var(--text-3);
}

:deep(.marketplace-more-danger) {
  color: var(--err);
}

.component-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.component-card {
  min-height: 220px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  box-shadow: var(--sh-1);
  cursor: pointer;
  transition: transform 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.component-card:hover {
  transform: translateY(-1px);
  border-color: var(--brand-ring);
  box-shadow: var(--sh-2);
}

.card-head {
  display: flex;
  align-items: center;
  gap: 14px;
}

.card-icon {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: var(--r-3, 8px);
  color: #fff;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.18);
}

.card-icon.large {
  width: 56px;
  height: 56px;
}

.tone-purple { background: linear-gradient(180deg, #766bf1, #5750d8); }
.tone-green { background: linear-gradient(180deg, #2ecb97, #18a978); }
.tone-amber { background: linear-gradient(180deg, #ffb321, #ee9200); }
.tone-red { background: linear-gradient(180deg, #ff6565, #ef3f4b); }

.card-title {
  min-width: 0;
}

.card-title h2 {
  margin: 0 0 8px;
  color: var(--text);
  font-size: 16px;
  line-height: 1.25;
  font-weight: var(--fw-semibold, 600);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.version {
  margin-left: 8px;
}

.card-desc {
  min-height: 48px;
  margin: 0;
  color: var(--text-2);
  font-size: 13px;
  line-height: 1.6;
}

.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: auto;
  padding-top: 16px;
  border-top: 1px solid var(--line);
  color: var(--text-3);
  font-size: 12.5px;
}

.author {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.downloads {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: 0 0 auto;
}

.empty-state {
  min-height: 486px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  color: var(--text-3);
  box-shadow: var(--sh-1);
}

.empty-icon {
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  border-radius: var(--r-3, 8px);
  color: #fff;
  background: var(--brand);
  font-weight: var(--fw-bold, 700);
}

.empty-state strong {
  color: var(--text);
  font-size: 17px;
  margin-top: 6px;
}

.detail-panel {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.detail-head {
  display: flex;
  align-items: center;
  gap: 14px;
}

.detail-head h2 {
  margin: 0 0 4px;
  font-size: 22px;
}

.detail-head p,
.detail-desc {
  margin: 0;
  color: var(--text-3);
  line-height: 1.7;
}

.readme {
  max-height: 240px;
  overflow: auto;
  margin: 0;
  padding: 14px;
  border-radius: var(--r-3, 8px);
  color: var(--text);
  background: var(--surface-2);
  white-space: pre-wrap;
}

.detail-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

:deep(.el-input__wrapper) {
  height: 36px;
  border-radius: var(--r-3, 8px);
  background: #fff;
  box-shadow: 0 0 0 1px var(--line) inset !important;
}

.btn {
  min-height: 34px;
  border: 1px solid transparent;
  border-radius: var(--r-3, 8px);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 14px;
  font: inherit;
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  cursor: pointer;
}

.btn-primary {
  background: var(--brand);
  color: var(--text-inverse, #fff);
  border-color: var(--brand);
}

.btn-primary:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
}

.btn-secondary {
  background: var(--surface);
  color: var(--text-2);
  border-color: var(--line);
}

.btn-secondary:hover {
  color: var(--brand);
  background: var(--brand-soft);
  border-color: var(--brand-ring);
}

@media (max-width: 1180px) {
  .component-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .marketplace-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .marketplace-toolbar-right {
    flex-wrap: wrap;
    justify-content: flex-start;
  }
}

@media (max-width: 760px) {
  .marketplace-page {
    padding: 18px 16px 28px;
  }

  .marketplace-tabs {
    width: 100%;
    overflow-x: auto;
  }

  .market-search {
    width: 100%;
  }

  .marketplace-table-head {
    display: none;
  }

  .marketplace-table {
    border: 0;
    background: transparent;
    box-shadow: none;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .marketplace-row {
    min-height: 0;
    border: 1px solid var(--line);
    border-radius: var(--r-4, 12px);
    background: var(--surface);
    grid-template-columns: 1fr;
    row-gap: 10px;
    padding: 12px;
  }

  .marketplace-row-actions {
    justify-content: flex-start;
    margin-left: 45px;
  }

  .component-grid {
    grid-template-columns: 1fr;
  }
}
</style>
