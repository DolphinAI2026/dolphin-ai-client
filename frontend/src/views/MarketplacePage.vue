<template>
  <BuilderFrame :breadcrumbs="[{ label: '组件市场' }]">
    <template #actions>
      <button class="btn btn-secondary mp-action-btn" type="button" @click="showMyComponents = !showMyComponents">
        {{ showMyComponents ? '浏览市场' : '我的发布' }}
      </button>
    </template>

    <main class="marketplace-page builder-page" data-design="v2">
    <!-- Search & Filters -->
    <div class="mp-toolbar">
      <el-input
        v-model="keyword"
        placeholder="搜索组件名称、描述、标签..."
        :prefix-icon="Search"
        clearable
        class="mp-search"
        @input="debouncedSearch"
      />
      <el-select v-model="selectedCategory" placeholder="全部分类" clearable class="mp-category" @change="loadComponents">
        <el-option label="全部分类" value="" />
        <el-option label="表单组件" value="form-component" />
        <el-option label="页面" value="form-page" />
        <el-option label="列表视图" value="form-list" />
        <el-option label="后端接口" value="backend-api" />
      </el-select>
      <el-select v-model="sortBy" class="mp-sort" @change="loadComponents">
        <el-option label="最新发布" value="latest" />
        <el-option label="最多下载" value="popular" />
      </el-select>
    </div>

    <!-- Component Grid -->
    <div class="mp-content" v-loading="loading">
      <div v-if="components.length === 0 && !loading" class="mp-empty">
        <EmptyState
          :variant="(keyword || selectedCategory) ? 'filtered' : 'first'"
          :title="showMyComponents
            ? '还没有发布的组件'
            : (keyword || selectedCategory) ? '没有匹配的组件' : '暂无组件'"
          :desc="showMyComponents
            ? '在 AI Builder 或 AI Coding 里完成一个组件后，回这里发布。'
            : (keyword || selectedCategory) ? '换个关键词，或者把需要的功能讲给 AI 让它生成。' : '快来发布第一个吧！'"
        >
          <template #icon>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>
          </template>
          <template v-if="keyword || selectedCategory" #cta>
            <el-button @click="() => { keyword = ''; selectedCategory = ''; loadComponents() }">清空搜索</el-button>
          </template>
        </EmptyState>
      </div>

      <div v-else class="mp-grid">
        <div
          v-for="comp in components"
          :key="comp.id"
          class="mp-card"
          @click="openDetail(comp)"
        >
          <div class="mp-card-header">
            <div class="mp-card-icon" v-html="categorySvg(comp.category)"></div>
            <div class="mp-card-meta">
              <h4 class="mp-card-name">{{ comp.name }}</h4>
              <span class="mp-card-version">v{{ comp.version }}</span>
            </div>
          </div>
          <p class="mp-card-desc">{{ comp.description || '暂无描述' }}</p>
          <div class="mp-card-tags" v-if="comp.tags && comp.tags.length">
            <el-tag
              v-for="tag in comp.tags.slice(0, 3)"
              :key="tag"
              size="small"
              type="info"
              class="mp-tag"
            >{{ tag }}</el-tag>
          </div>
          <div class="mp-card-footer">
            <span class="mp-card-author">{{ comp.author_name || '匿名' }}</span>
            <span class="mp-card-downloads">
              <el-icon><Download /></el-icon> {{ comp.download_count }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Detail Dialog -->
    <el-dialog
      v-model="detailVisible"
      :title="selectedComp?.name || '组件详情'"
      width="680px"
      class="mp-dialog"
      :close-on-click-modal="true"
    >
      <div v-if="selectedComp" class="mp-detail">
        <div class="mp-detail-head">
          <div class="mp-detail-icon" v-html="categorySvg(selectedComp.category)"></div>
          <div class="mp-detail-info">
            <h2>{{ selectedComp.name }}</h2>
            <div class="mp-detail-meta">
              <el-tag size="small">{{ categoryLabel(selectedComp.category) }}</el-tag>
              <span>v{{ selectedComp.version }}</span>
              <span>{{ selectedComp.author_name || '匿名' }}</span>
              <span>下载 {{ selectedComp.download_count }} 次</span>
            </div>
          </div>
        </div>

        <div class="mp-detail-desc">{{ selectedComp.description || '暂无描述' }}</div>

        <div v-if="selectedComp.tags && selectedComp.tags.length" class="mp-detail-tags">
          <el-tag v-for="tag in selectedComp.tags" :key="tag" size="small" class="mp-tag">{{ tag }}</el-tag>
        </div>

        <div v-if="selectedComp.readme" class="mp-detail-readme">
          <h4>README</h4>
          <pre class="mp-readme-content">{{ selectedComp.readme }}</pre>
        </div>

        <div class="mp-detail-actions">
          <el-button type="primary" @click="downloadComponent(selectedComp)" :loading="downloading">
            <el-icon><Download /></el-icon> 下载组件
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
    </main>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Download } from '@element-plus/icons-vue'
import { marketplaceApi, type MarketplaceComponent } from '@/api/marketplace'
import { useUserStore } from '@/stores/user'
import BuilderFrame from '@/components/BuilderFrame.vue'
import EmptyState from '@/components/states/EmptyState.vue'

const userStore = useUserStore()
const currentUserId = computed(() => userStore.user?.id)

const keyword = ref('')
const selectedCategory = ref('')
const sortBy = ref('latest')
const loading = ref(false)
const components = ref<MarketplaceComponent[]>([])
const showMyComponents = ref(false)

const detailVisible = ref(false)
const selectedComp = ref<MarketplaceComponent | null>(null)
const downloading = ref(false)

let searchTimer: ReturnType<typeof setTimeout> | null = null

function debouncedSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => loadComponents(), 300)
}

async function loadComponents() {
  loading.value = true
  try {
    if (showMyComponents.value) {
      components.value = await marketplaceApi.listMine()
    } else {
      components.value = await marketplaceApi.list({
        keyword: keyword.value || undefined,
        category: selectedCategory.value || undefined,
        sort: sortBy.value,
      })
    }
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

async function downloadComponent(comp: MarketplaceComponent) {
  downloading.value = true
  try {
    await marketplaceApi.download(comp.id)
    // 更新下载计数
    comp.download_count++
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
    loadComponents()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e.message || '下架失败')
    }
  }
}

function categorySvg(cat: string): string {
  const grad = '<defs><linearGradient id="catG" x1="0" y1="0" x2="24" y2="24"><stop offset="0%" stop-color="#7c3aed"/><stop offset="100%" stop-color="#6366f1"/></linearGradient></defs>'
  const svgs: Record<string, string> = {
    'form-component': `<svg width="22" height="22" viewBox="0 0 24 24" fill="none">${grad}<path d="M3.5 3.5H10.5V10.5H3.5V3.5ZM13.5 3.5H20.5V10.5H13.5V3.5ZM3.5 13.5H10.5V20.5H3.5V13.5ZM16 13.5V20.5M13 17H19" stroke="url(#catG)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    'form-page': `<svg width="22" height="22" viewBox="0 0 24 24" fill="none">${grad}<path d="M14 2H6C5.46957 2 4.96086 2.21071 4.58579 2.58579C4.21071 2.96086 4 3.46957 4 4V20C4 20.5304 4.21071 21.0391 4.58579 21.4142C4.96086 21.7893 5.46957 22 6 22H18C18.5304 22 19.0391 21.7893 19.4142 21.4142C19.7893 21.0391 20 20.5304 20 20V8L14 2Z" stroke="url(#catG)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M14 2V8H20M16 13H8M16 17H8M10 9H8" stroke="url(#catG)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    'form-list': `<svg width="22" height="22" viewBox="0 0 24 24" fill="none">${grad}<path d="M8 6H21M8 12H21M8 18H21M3 6H3.01M3 12H3.01M3 18H3.01" stroke="url(#catG)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    'backend-api': `<svg width="22" height="22" viewBox="0 0 24 24" fill="none">${grad}<path d="M12 15C13.6569 15 15 13.6569 15 12C15 10.3431 13.6569 9 12 9C10.3431 9 9 10.3431 9 12C9 13.6569 10.3431 15 12 15Z" stroke="url(#catG)" stroke-width="1.5"/><path d="M19.4 15C19.2669 15.3016 19.2272 15.6362 19.286 15.9606C19.3448 16.285 19.4995 16.5843 19.73 16.82L19.79 16.88C19.976 17.0657 20.1235 17.2863 20.2241 17.5291C20.3248 17.7719 20.3766 18.0322 20.3766 18.295C20.3766 18.5578 20.3248 18.8181 20.2241 19.0609C20.1235 19.3037 19.976 19.5243 19.79 19.71C19.6043 19.896 19.3837 20.0435 19.1409 20.1441C18.8981 20.2448 18.6378 20.2966 18.375 20.2966C18.1122 20.2966 17.8519 20.2448 17.6091 20.1441C17.3663 20.0435 17.1457 19.896 16.96 19.71L16.9 19.65C16.6643 19.4195 16.365 19.2648 16.0406 19.206C15.7162 19.1472 15.3816 19.1869 15.08 19.32C14.7842 19.4468 14.532 19.6572 14.3543 19.9255C14.1766 20.1938 14.0813 20.5082 14.08 20.83V21C14.08 21.5304 13.8693 22.0391 13.4942 22.4142C13.1191 22.7893 12.6104 23 12.08 23C11.5496 23 11.0409 22.7893 10.6658 22.4142C10.2907 22.0391 10.08 21.5304 10.08 21V20.91C10.0723 20.579 9.96512 20.258 9.77251 19.9887C9.5799 19.7194 9.31074 19.5143 9 19.4C8.69838 19.2669 8.36381 19.2272 8.03941 19.286C7.71502 19.3448 7.41568 19.4995 7.18 19.73L7.12 19.79C6.93425 19.976 6.71368 20.1235 6.47088 20.2241C6.22808 20.3248 5.96783 20.3766 5.705 20.3766C5.44217 20.3766 5.18192 20.3248 4.93912 20.2241C4.69632 20.1235 4.47575 19.976 4.29 19.79C4.10405 19.6043 3.95653 19.3837 3.85588 19.1409C3.75523 18.8981 3.70343 18.6378 3.70343 18.375C3.70343 18.1122 3.75523 17.8519 3.85588 17.6091C3.95653 17.3663 4.10405 17.1457 4.29 16.96L4.35 16.9C4.58054 16.6643 4.73519 16.365 4.794 16.0406C4.85282 15.7162 4.81312 15.3816 4.68 15.08C4.55324 14.7842 4.34276 14.532 4.07447 14.3543C3.80618 14.1766 3.49179 14.0813 3.17 14.08H3C2.46957 14.08 1.96086 13.8693 1.58579 13.4942C1.21071 13.1191 1 12.6104 1 12.08C1 11.5496 1.21071 11.0409 1.58579 10.6658C1.96086 10.2907 2.46957 10.08 3 10.08H3.09C3.42099 10.0723 3.742 9.96512 4.0113 9.77251C4.28059 9.5799 4.48572 9.31074 4.6 9C4.73312 8.69838 4.77282 8.36381 4.714 8.03941C4.65519 7.71502 4.50054 7.41568 4.27 7.18L4.21 7.12C4.02405 6.93425 3.87653 6.71368 3.77588 6.47088C3.67523 6.22808 3.62343 5.96783 3.62343 5.705C3.62343 5.44217 3.67523 5.18192 3.77588 4.93912C3.87653 4.69632 4.02405 4.47575 4.21 4.29C4.39575 4.10405 4.61632 3.95653 4.85912 3.85588C5.10192 3.75523 5.36217 3.70343 5.625 3.70343C5.88783 3.70343 6.14808 3.75523 6.39088 3.85588C6.63368 3.95653 6.85425 4.10405 7.04 4.29L7.1 4.35C7.33568 4.58054 7.63502 4.73519 7.95941 4.794C8.28381 4.85282 8.61838 4.81312 8.92 4.68H9C9.29577 4.55324 9.54802 4.34276 9.72569 4.07447C9.90337 3.80618 9.99872 3.49179 10 3.17V3C10 2.46957 10.2107 1.96086 10.5858 1.58579C10.9609 1.21071 11.4696 1 12 1C12.5304 1 13.0391 1.21071 13.4142 1.58579C13.7893 1.96086 14 2.46957 14 3V3.09C14.0013 3.41179 14.0966 3.72618 14.2743 3.99447C14.452 4.26276 14.7042 4.47324 15 4.6C15.3016 4.73312 15.6362 4.77282 15.9606 4.714C16.285 4.65519 16.5843 4.50054 16.82 4.27L16.88 4.21C17.0657 4.02405 17.2863 3.87653 17.5291 3.77588C17.7719 3.67523 18.0322 3.62343 18.295 3.62343C18.5578 3.62343 18.8181 3.67523 19.0609 3.77588C19.3037 3.87653 19.5243 4.02405 19.71 4.21C19.896 4.39575 20.0435 4.61632 20.1441 4.85912C20.2448 5.10192 20.2966 5.36217 20.2966 5.625C20.2966 5.88783 20.2448 6.14808 20.1441 6.39088C20.0435 6.63368 19.896 6.85425 19.71 7.04L19.65 7.1C19.4195 7.33568 19.2648 7.63502 19.206 7.95941C19.1472 8.28381 19.1869 8.61838 19.32 8.92V9C19.4468 9.29577 19.6572 9.54802 19.9255 9.72569C20.1938 9.90337 20.5082 9.99872 20.83 10H21C21.5304 10 22.0391 10.2107 22.4142 10.5858C22.7893 10.9609 23 11.4696 23 12C23 12.5304 22.7893 13.0391 22.4142 13.4142C22.0391 13.7893 21.5304 14 21 14H20.91C20.5882 14.0013 20.2738 14.0966 20.0055 14.2743C19.7372 14.452 19.5268 14.7042 19.4 15Z" stroke="url(#catG)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  }
  const defaultSvg = `<svg width="22" height="22" viewBox="0 0 24 24" fill="none">${grad}<path d="M20.5 7.27783L12 12.0001M12 12.0001L3.49997 7.27783M12 12.0001L12 21.5001M21 16.0586V7.94153C21 7.59889 21 7.42757 20.9495 7.27477C20.9049 7.13959 20.8318 7.01551 20.7354 6.91082C20.6263 6.79248 20.4766 6.70928 20.177 6.54288L12.777 2.43177C12.4934 2.27421 12.3516 2.19543 12.2015 2.16454C12.0685 2.13721 11.9315 2.13721 11.7986 2.16454C11.6484 2.19543 11.5066 2.27421 11.223 2.43177L3.82297 6.54288C3.52345 6.70928 3.37369 6.79248 3.26463 6.91082C3.16816 7.01551 3.09515 7.13959 3.05048 7.27477C3 7.42757 3 7.59889 3 7.94153V16.0586C3 16.4013 3 16.5726 3.05048 16.7254C3.09515 16.8606 3.16816 16.9847 3.26463 17.0893C3.37369 17.2077 3.52345 17.2909 3.82297 17.4573L11.223 21.5684C11.5066 21.726 11.6484 21.8047 11.7986 21.8356C11.9315 21.863 12.0685 21.863 12.2015 21.8356C12.3516 21.8047 12.4934 21.726 12.777 21.5684L20.177 17.4573C20.4766 17.2909 20.6263 17.2077 20.7354 17.0893C20.8318 16.9847 20.9049 16.8606 20.9495 16.7254C21 16.5726 21 16.4013 21 16.0586Z" stroke="url(#catG)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`
  return svgs[cat] || defaultSvg
}

function categoryLabel(cat: string): string {
  const labels: Record<string, string> = {
    'form-component': '表单组件',
    'form-page': '页面',
    'form-list': '列表视图',
    'backend-api': '后端接口',
  }
  return labels[cat] || cat
}

// Watch showMyComponents toggle
import { watch } from 'vue'
watch(showMyComponents, () => loadComponents())

onMounted(() => loadComponents())
</script>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Reference: design-spec/06-data-marketplace.html · FRAME 06.3 BROWSE (mkt-grid / mkt-card / mkt-cover).
   Preserved:
     - All class names (template引用)
     - BuilderFrame wrap (flex:1 fill main area)
     - Element Plus :deep overrides (search / select / dialog / loading / tag)
   Refreshed:
     - card surface + line border + r-4 + sh-2 / hover lift 1px + brand-ring border + sh-3
     - cover area = 120px linear-gradient(surface-2 → surface-3) + monoline icon
     - tag/version pill = mono font + brand-soft + brand text (matches spec.tag)
     - footer counts = mono tnum
     - search/select inputs = surface-2 fill + r-2 + line border + brand-ring focus
     - removed: brand-300 ref / rose ref / 100vh / heavy box-shadow dark glow
*/

/* ============ Layout ============ */
/* Wrapped in BuilderFrame → fills workbench main area, not 100vh. */
.marketplace-page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface-2);
  color: var(--text);
}

/* Topbar #actions slot button. */
.mp-action-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  height: 30px;
  padding: 0 var(--s-3);
  border: 1px solid var(--line);
  border-radius: var(--r-2);
  background: var(--surface);
  color: var(--text-2);
  font-size: var(--t-small);
  font-weight: var(--fw-medium);
  cursor: pointer;
  font-family: inherit;
  transition: border-color 0.14s var(--ease),
              background 0.14s var(--ease),
              color 0.14s var(--ease);
}
.mp-action-btn:hover {
  color: var(--brand);
  border-color: var(--brand-ring);
  background: var(--brand-soft);
}
.mp-action-btn:focus-visible {
  outline: 2px solid var(--line-focus);
  outline-offset: 2px;
}

/* ============ Toolbar ============ */
.mp-toolbar {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  padding: var(--s-4) var(--s-6);
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}

.mp-search {
  flex: 1;
  max-width: 480px;
}

.mp-search :deep(.el-input__wrapper) {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--r-2);
  box-shadow: none !important;
  transition: border-color 0.14s var(--ease),
              background 0.14s var(--ease);
}

.mp-search :deep(.el-input__wrapper:hover) {
  border-color: var(--line-strong);
}

.mp-search :deep(.el-input__wrapper.is-focus) {
  border-color: var(--brand-ring);
  background: var(--surface);
}

.mp-search :deep(.el-input__inner) {
  color: var(--text);
  font-size: var(--t-body);
}

.mp-search :deep(.el-input__inner::placeholder) {
  color: var(--text-4);
}

.mp-search :deep(.el-input__prefix .el-icon) {
  color: var(--text-3);
}

.mp-category,
.mp-sort {
  width: 140px;
}

.mp-category :deep(.el-input__wrapper),
.mp-sort :deep(.el-input__wrapper) {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--r-2);
  box-shadow: none !important;
  transition: border-color 0.14s var(--ease),
              background 0.14s var(--ease);
}

.mp-category :deep(.el-input__wrapper:hover),
.mp-sort :deep(.el-input__wrapper:hover) {
  border-color: var(--line-strong);
}

.mp-category :deep(.el-input__wrapper.is-focus),
.mp-sort :deep(.el-input__wrapper.is-focus) {
  border-color: var(--brand-ring);
  background: var(--surface);
}

.mp-category :deep(.el-input__inner),
.mp-sort :deep(.el-input__inner) {
  color: var(--text);
  font-size: var(--t-body);
}

/* ============ Content ============ */
.mp-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--s-6);
}

.mp-content::-webkit-scrollbar {
  width: 6px;
}
.mp-content::-webkit-scrollbar-track {
  background: transparent;
}
.mp-content::-webkit-scrollbar-thumb {
  background: var(--line);
  border-radius: 3px;
}
.mp-content::-webkit-scrollbar-thumb:hover {
  background: var(--line-strong);
}

/* ============ Empty State ============ */
.mp-empty {
  text-align: center;
  padding: 100px 0;
  color: var(--text-3);
}

.mp-empty-icon {
  margin-bottom: var(--s-5);
  opacity: 0.5;
  color: var(--text-4);
}

.mp-empty p {
  font-size: var(--t-body);
  color: var(--text-2);
  margin: 0;
}

/* ============ Grid (3 列 cards) ============ */
.mp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
}

/* Card structure (spec.mkt-card): cover area (120px gradient) + body.
   Existing template doesn't have a cover wrapper — emulate via .mp-card-header
   while keeping that class as the body header. */
.mp-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4);
  padding: var(--s-4) var(--s-4) var(--s-4);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  box-shadow: var(--sh-1);
  transition: border-color 0.14s var(--ease),
              box-shadow 0.14s var(--ease),
              transform 0.14s var(--ease);
}

.mp-card:hover {
  border-color: var(--brand-ring);
  box-shadow: var(--sh-3);
  transform: translateY(-1px);
}

.mp-card-header {
  display: flex;
  align-items: center;
  gap: var(--s-3);
}

.mp-card-icon {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, var(--surface-2) 0%, var(--surface-3) 100%);
  border: 1px solid var(--line);
  border-radius: var(--r-3);
  color: var(--text-3);
  flex-shrink: 0;
}

.mp-card-meta {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-2);
}

.mp-card-name {
  font-size: var(--t-body);
  font-weight: var(--fw-semibold);
  color: var(--text);
  letter-spacing: -0.005em;
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
}

/* Version pill — mono font + brand-soft chip per spec.tag */
.mp-card-version {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  background: var(--brand-soft);
  color: var(--brand);
  border-radius: var(--r-1);
  font-size: 10.5px;
  font-family: var(--font-mono);
  font-weight: var(--fw-semibold);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.mp-card-desc {
  font-size: var(--t-small);
  color: var(--text-3);
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.55;
  min-height: 34px;
}

.mp-card-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.mp-tag {
  background: var(--surface-3) !important;
  border-color: var(--line) !important;
  color: var(--text-2) !important;
  border-radius: var(--r-1) !important;
  font-size: 10.5px !important;
  font-weight: var(--fw-medium) !important;
}

.mp-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11.5px;
  color: var(--text-3);
  margin-top: auto;
  padding-top: var(--s-2);
  border-top: 1px solid var(--line);
}

.mp-card-footer > span:first-child {
  font-weight: var(--fw-medium);
  color: var(--text-2);
}

.mp-card-downloads {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--text-3);
}

/* ============ Detail Dialog ============ */
.mp-dialog :deep(.el-dialog) {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-5);
  box-shadow: var(--sh-5);
  overflow: hidden;
}

.mp-dialog :deep(.el-dialog__header) {
  border-bottom: 1px solid var(--line);
  padding: var(--s-4) var(--s-5);
  margin: 0;
}

.mp-dialog :deep(.el-dialog__title) {
  color: var(--text);
  font-weight: var(--fw-semibold);
  font-size: var(--t-h3);
  letter-spacing: -0.01em;
}

.mp-dialog :deep(.el-dialog__headerbtn .el-icon) {
  color: var(--text-3);
}
.mp-dialog :deep(.el-dialog__headerbtn:hover .el-icon) {
  color: var(--text);
}

.mp-dialog :deep(.el-dialog__body) {
  color: var(--text-2);
  padding: var(--s-5);
}

.mp-detail {
  display: flex;
  flex-direction: column;
  gap: var(--s-5);
}

.mp-detail-head {
  display: flex;
  align-items: center;
  gap: var(--s-4);
}

.mp-detail-icon {
  width: 56px;
  height: 56px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, var(--surface-2) 0%, var(--surface-3) 100%);
  border: 1px solid var(--line);
  border-radius: var(--r-4);
  color: var(--text-3);
}

.mp-detail-info h2 {
  margin: 0 0 6px;
  font-size: var(--t-h3);
  font-weight: var(--fw-bold);
  color: var(--text);
  letter-spacing: -0.01em;
}

.mp-detail-meta {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  font-size: var(--t-small);
  color: var(--text-3);
}

.mp-detail-meta :deep(.el-tag) {
  background: var(--brand-soft);
  border-color: var(--brand-soft);
  color: var(--brand);
  border-radius: var(--r-1);
  font-family: var(--font-mono);
  font-weight: var(--fw-semibold);
}

.mp-detail-desc {
  font-size: var(--t-body);
  color: var(--text-2);
  line-height: 1.7;
}

.mp-detail-tags {
  display: flex;
  gap: var(--s-2);
  flex-wrap: wrap;
}

.mp-detail-readme h4 {
  margin: 0 0 var(--s-2);
  color: var(--text);
  font-size: var(--t-body);
  font-weight: var(--fw-semibold);
  letter-spacing: -0.005em;
}

.mp-readme-content {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--r-3);
  padding: var(--s-4);
  font-size: var(--t-mono);
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 300px;
  overflow-y: auto;
  font-family: var(--font-mono);
  line-height: 1.6;
}

.mp-readme-content::-webkit-scrollbar {
  width: 4px;
}
.mp-readme-content::-webkit-scrollbar-thumb {
  background: var(--line);
  border-radius: 2px;
}

.mp-detail-actions {
  display: flex;
  gap: var(--s-3);
  padding-top: var(--s-3);
  border-top: 1px solid var(--line);
}

.mp-detail-actions :deep(.el-button--primary) {
  background: var(--brand) !important;
  border: 1px solid var(--brand) !important;
  border-radius: var(--r-2) !important;
  color: var(--text-inverse) !important;
  font-weight: var(--fw-semibold);
  letter-spacing: 0.01em;
  box-shadow: var(--sh-brand);
  transition: background 0.14s var(--ease),
              box-shadow 0.14s var(--ease);
}

.mp-detail-actions :deep(.el-button--primary:hover) {
  background: var(--brand-hover) !important;
  border-color: var(--brand-hover) !important;
  box-shadow: var(--sh-3);
}

.mp-detail-actions :deep(.el-button--danger) {
  border-radius: var(--r-2) !important;
  background: var(--surface) !important;
  border: 1px solid var(--err) !important;
  color: var(--err) !important;
  font-weight: var(--fw-medium);
}

.mp-detail-actions :deep(.el-button--danger:hover) {
  background: var(--err-soft) !important;
  border-color: var(--err) !important;
}

/* ============ Element Plus Dropdown Override ============ */
.marketplace-page :deep(.el-select-dropdown) {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-3);
  box-shadow: var(--sh-3);
}

.marketplace-page :deep(.el-select-dropdown__item) {
  color: var(--text-2);
  font-size: var(--t-body);
}

.marketplace-page :deep(.el-select-dropdown__item:hover),
.marketplace-page :deep(.el-select-dropdown__item.selected) {
  background: var(--brand-soft);
  color: var(--brand);
}

/* ============ Loading Override ============ */
.mp-content :deep(.el-loading-mask) {
  background: rgba(248, 250, 252, 0.7);
  backdrop-filter: blur(2px);
}

.mp-content :deep(.el-loading-spinner .path) {
  stroke: var(--brand);
}

.mp-content :deep(.el-loading-text) {
  color: var(--text-2);
}

html[data-theme="dark"] .mp-content :deep(.el-loading-mask) {
  background: rgba(11, 18, 36, 0.7);
}
</style>
