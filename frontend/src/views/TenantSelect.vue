<template>
  <div class="tenant-select-container">
    <div class="select-box">
      <div class="select-header">
        <h1>选择组织</h1>
        <p>你属于多个组织，请选择要进入的组织</p>
      </div>

      <div class="tenant-list">
        <button
          v-for="tenant in tenants"
          :key="tenant.tenant_id"
          type="button"
          class="tenant-card"
          :disabled="selectionPending"
          @click="handleSelect(tenant)"
        >
          <div class="tenant-icon">
            <span>{{ tenant.tenant_name.charAt(0) }}</span>
          </div>
          <div class="tenant-info">
            <div class="tenant-name">{{ tenant.tenant_name }}</div>
            <div class="tenant-code">{{ tenant.tenant_code }}</div>
          </div>
          <el-icon class="arrow-icon"><ArrowRight /></el-icon>
        </button>
      </div>

      <div class="select-footer">
        <el-button text :disabled="selectionPending" @click="handleLogout">返回登录</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { isNavigationFailure, useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowRight } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import type { TenantOption } from '@/types'
import { resolveLoginTenant, safeLoginRedirectPath } from '@/router/loginRedirect'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const selectionToken = ref('')
const tenants = ref<TenantOption[]>([])
const selectionPending = ref(false)
let selectionGeneration = 0
let selectionController: AbortController | null = null

const cancelSelectionOperation = () => {
  selectionGeneration += 1
  selectionController?.abort()
  selectionController = null
}

const isAbortError = (error: unknown) => (
  (error as { name?: string })?.name === 'AbortError'
  || (error as { code?: string })?.code === 'ERR_CANCELED'
)

const handleSelect = async (tenant: TenantOption) => {
  if (selectionPending.value) return
  selectionController?.abort()
  const generation = ++selectionGeneration
  const controller = new AbortController()
  selectionController = controller
  selectionPending.value = true
  let commit: Awaited<ReturnType<typeof userStore.selectTenant>> | null = null
  const isCurrentOperation = () => (
    generation === selectionGeneration
    && selectionController === controller
    && !controller.signal.aborted
  )
  try {
    commit = await userStore.selectTenant(
      selectionToken.value,
      tenant.tenant_id,
      tenant.tenant_public_id,
      controller.signal,
    )
    if (!isCurrentOperation()) {
      commit.rollback()
      return
    }

    const navigationFailure = await router.replace(
      safeLoginRedirectPath(route.query.redirect) || '/',
    )
    if (isNavigationFailure(navigationFailure)) {
      commit.rollback()
      if (isCurrentOperation()) {
        ElMessage.error('登录导航未完成，请重试')
      }
      return
    }

    commit.finalize()
    if (isCurrentOperation()) {
      ElMessage.success('登录成功')
    }
  } catch (error: any) {
    commit?.rollback()
    if (isCurrentOperation() && !isAbortError(error)) {
      ElMessage.error(error.response?.data?.detail || '选择租户失败')
    }
  } finally {
    if (generation === selectionGeneration) {
      selectionPending.value = false
      if (selectionController === controller) {
        selectionController = null
      }
    }
  }
}

onBeforeUnmount(cancelSelectionOperation)

onMounted(() => {
  selectionToken.value = route.query.token as string
  const tenantsStr = route.query.tenants as string
  if (!selectionToken.value || !tenantsStr) {
    ElMessage.error('无效的访问')
    router.push('/login')
    return
  }
  try {
    tenants.value = JSON.parse(tenantsStr)
    const targetTenant = resolveLoginTenant(route.query.redirect, tenants.value)
    if (targetTenant) {
      void handleSelect(targetTenant)
    }
  } catch {
    ElMessage.error('数据解析失败')
    router.push('/login')
  }
})

const handleLogout = () => {
  if (selectionPending.value) return
  cancelSelectionOperation()
  const redirect = safeLoginRedirectPath(route.query.redirect)
  router.push({ path: '/login', query: redirect ? { redirect } : {} })
}
</script>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   - Background gradient: indigo --t-brand-gradient → v3 brand blue gradient
   - All --t-* tokens → v3 surface/text/line/brand
   - Radii/spacing → v3 r/s tokens; shadow → --sh-4; transitions → --ease
*/
.tenant-select-container {
  min-height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  background: linear-gradient(135deg, var(--brand) 0%, var(--brand-hover) 100%);
  padding: var(--s-5, 20px);
}

.select-box {
  width: 100%;
  max-width: 500px;
  background: var(--surface);
  backdrop-filter: blur(10px);
  border: 1px solid var(--line);
  border-radius: var(--r-5, 16px);
  box-shadow: var(--sh-4);
  padding: var(--s-10, 40px);
}

.select-header {
  text-align: center;
  margin-bottom: var(--s-8, 32px);
}

.select-header h1 {
  margin: 0 0 var(--s-2, 8px) 0;
  font-size: 28px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
  letter-spacing: -0.02em;
}

.select-header p {
  margin: 0;
  font-size: var(--t-body, 14px);
  color: var(--text-3);
  line-height: 1.55;
}

.tenant-list {
  display: flex;
  flex-direction: column;
  gap: var(--s-3, 12px);
  margin-bottom: var(--s-6, 24px);
}

.tenant-card {
  width: 100%;
  color: inherit;
  font: inherit;
  text-align: left;
  display: flex;
  align-items: center;
  gap: var(--s-4, 16px);
  padding: var(--s-4, 16px);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  cursor: pointer;
  transition: border-color 0.18s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.18s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              transform 0.18s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.tenant-card:hover:not(:disabled) {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-ring), var(--sh-2);
  transform: translateY(-2px);
}

.tenant-card:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.tenant-card:disabled {
  cursor: wait;
  opacity: 0.65;
}

.tenant-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--r-4, 12px);
  background: linear-gradient(135deg, var(--brand) 0%, var(--brand-hover) 100%);
  box-shadow: var(--sh-brand);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-inverse, #fff);
  font-size: 20px;
  font-weight: var(--fw-semibold, 600);
  flex-shrink: 0;
}

.tenant-info {
  flex: 1;
  min-width: 0;
}

.tenant-name {
  font-size: 16px;
  font-weight: var(--fw-medium, 500);
  color: var(--text);
  margin-bottom: 4px;
  letter-spacing: -0.005em;
}

.tenant-code {
  font-size: 13px;
  color: var(--text-3);
  font-family: var(--font-mono);
}

.arrow-icon {
  font-size: 20px;
  color: var(--text-4);
  transition: color 0.18s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              transform 0.18s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.tenant-card:hover:not(:disabled) .arrow-icon {
  color: var(--brand);
  transform: translateX(4px);
}

.select-footer {
  text-align: center;
  padding-top: var(--s-4, 16px);
  border-top: 1px solid var(--line);
}
</style>
