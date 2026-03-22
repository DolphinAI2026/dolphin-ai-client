<template>
  <div class="marketplace-page">
    <!-- Header -->
    <header class="mp-header">
      <div class="mp-header-left">
        <el-button text @click="$router.back()">
          <el-icon><ArrowLeft /></el-icon>
        </el-button>
        <h3 class="mp-title">组件市场</h3>
        <el-tag size="small" type="warning">Beta</el-tag>
      </div>
      <div class="mp-header-right">
        <el-button size="small" @click="showMyComponents = !showMyComponents" class="mp-btn">
          {{ showMyComponents ? '浏览市场' : '我的发布' }}
        </el-button>
        <el-button size="small" @click="$router.push('/coding')" class="mp-btn">
          <el-icon><Monitor /></el-icon> Vibe Coding
        </el-button>
      </div>
    </header>

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
        <div class="mp-empty-icon">📦</div>
        <p>{{ showMyComponents ? '你还没有发布任何组件' : '暂无组件，快来发布第一个吧！' }}</p>
      </div>

      <div v-else class="mp-grid">
        <div
          v-for="comp in components"
          :key="comp.id"
          class="mp-card"
          @click="openDetail(comp)"
        >
          <div class="mp-card-header">
            <div class="mp-card-icon">{{ categoryIcon(comp.category) }}</div>
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
          <div class="mp-detail-icon">{{ categoryIcon(selectedComp.category) }}</div>
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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Monitor, Search, Download } from '@element-plus/icons-vue'
import { marketplaceApi, type MarketplaceComponent } from '@/api/marketplace'
import { useUserStore } from '@/stores/user'

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

function categoryIcon(cat: string): string {
  const icons: Record<string, string> = {
    'form-component': '🧩',
    'form-page': '📄',
    'form-list': '📋',
    'backend-api': '⚙️',
  }
  return icons[cat] || '📦'
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
.marketplace-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #0a0a0a;
  color: #e0e0e0;
}

/* ============ Header ============ */
.mp-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-bottom: 1px solid #1e1e1e;
  background: #111;
  height: 48px;
  flex-shrink: 0;
}

.mp-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.mp-title {
  font-size: 16px;
  font-weight: 600;
  background: linear-gradient(135deg, #f093fb, #f5576c);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin: 0;
}

.mp-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mp-btn {
  border-color: #333;
  background: #1a1a1a;
  color: #ccc;
}

.mp-btn:hover {
  border-color: #555;
  background: #252525;
  color: #fff;
}

/* ============ Toolbar ============ */
.mp-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 24px;
  border-bottom: 1px solid #1a1a1a;
  background: #0d0d0d;
}

.mp-search {
  flex: 1;
  max-width: 480px;
}

.mp-search :deep(.el-input__wrapper) {
  background: #1a1a1a;
  border-color: #333;
  box-shadow: none;
}

.mp-search :deep(.el-input__inner) {
  color: #e0e0e0;
}

.mp-category,
.mp-sort {
  width: 140px;
}

.mp-category :deep(.el-input__wrapper),
.mp-sort :deep(.el-input__wrapper) {
  background: #1a1a1a;
  border-color: #333;
  box-shadow: none;
}

.mp-category :deep(.el-input__inner),
.mp-sort :deep(.el-input__inner) {
  color: #e0e0e0;
}

/* ============ Content ============ */
.mp-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.mp-empty {
  text-align: center;
  padding: 80px 0;
  color: #666;
}

.mp-empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

/* ============ Grid ============ */
.mp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.mp-card {
  background: #151515;
  border: 1px solid #222;
  border-radius: 12px;
  padding: 20px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.mp-card:hover {
  border-color: #444;
  background: #1a1a1a;
  transform: translateY(-2px);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
}

.mp-card-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.mp-card-icon {
  font-size: 28px;
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #1e1e1e;
  border-radius: 10px;
  flex-shrink: 0;
}

.mp-card-meta {
  flex: 1;
  min-width: 0;
}

.mp-card-name {
  font-size: 15px;
  font-weight: 600;
  color: #eee;
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mp-card-version {
  font-size: 12px;
  color: #666;
}

.mp-card-desc {
  font-size: 13px;
  color: #888;
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.5;
}

.mp-card-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.mp-tag {
  background: #1e1e1e !important;
  border-color: #333 !important;
  color: #aaa !important;
}

.mp-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: #666;
  margin-top: auto;
}

.mp-card-downloads {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* ============ Detail Dialog ============ */
.mp-dialog :deep(.el-dialog) {
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 12px;
}

.mp-dialog :deep(.el-dialog__header) {
  border-bottom: 1px solid #222;
}

.mp-dialog :deep(.el-dialog__title) {
  color: #eee;
}

.mp-dialog :deep(.el-dialog__body) {
  color: #ccc;
}

.mp-detail {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.mp-detail-head {
  display: flex;
  align-items: center;
  gap: 16px;
}

.mp-detail-icon {
  font-size: 36px;
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #222;
  border-radius: 12px;
}

.mp-detail-info h2 {
  margin: 0 0 6px;
  font-size: 20px;
  color: #eee;
}

.mp-detail-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  color: #888;
}

.mp-detail-desc {
  font-size: 14px;
  color: #aaa;
  line-height: 1.6;
}

.mp-detail-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.mp-detail-readme h4 {
  margin: 0 0 8px;
  color: #ccc;
}

.mp-readme-content {
  background: #111;
  border: 1px solid #222;
  border-radius: 8px;
  padding: 16px;
  font-size: 13px;
  color: #aaa;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 300px;
  overflow-y: auto;
}

.mp-detail-actions {
  display: flex;
  gap: 12px;
  padding-top: 8px;
  border-top: 1px solid #222;
}
</style>
