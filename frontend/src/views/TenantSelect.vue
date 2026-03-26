<template>
  <div class="tenant-select-container">
    <div class="select-box">
      <div class="select-header">
        <h1>选择组织</h1>
        <p>你属于多个组织，请选择要进入的组织</p>
      </div>

      <div class="tenant-list">
        <div
          v-for="tenant in tenants"
          :key="tenant.tenant_id"
          class="tenant-card"
          @click="handleSelect(tenant.tenant_id)"
        >
          <div class="tenant-icon">
            <span>{{ tenant.tenant_name.charAt(0) }}</span>
          </div>
          <div class="tenant-info">
            <div class="tenant-name">{{ tenant.tenant_name }}</div>
            <div class="tenant-code">{{ tenant.tenant_code }}</div>
          </div>
          <el-icon class="arrow-icon"><ArrowRight /></el-icon>
        </div>
      </div>

      <div class="select-footer">
        <el-button text @click="handleLogout">返回登录</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowRight } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import type { TenantOption } from '@/types'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const selectionToken = ref('')
const tenants = ref<TenantOption[]>([])

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
  } catch {
    ElMessage.error('数据解析失败')
    router.push('/login')
  }
})

const handleSelect = async (tenantId: number) => {
  try {
    await userStore.selectTenant(selectionToken.value, tenantId)
    ElMessage.success('登录成功')
    router.push('/')
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '选择租户失败')
  }
}

const handleLogout = () => {
  router.push('/login')
}
</script>

<style scoped>
.tenant-select-container {
  min-height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  background: var(--t-brand-gradient);
  padding: 20px;
}

.select-box {
  width: 100%;
  max-width: 500px;
  background: var(--t-bg-panel);
  backdrop-filter: blur(10px);
  border-radius: 16px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
  padding: 40px;
}

.select-header {
  text-align: center;
  margin-bottom: 32px;
}

.select-header h1 {
  margin: 0 0 8px 0;
  font-size: 28px;
  font-weight: 600;
  color: var(--t-text-primary);
}

.select-header p {
  margin: 0;
  font-size: 14px;
  color: var(--t-text-secondary);
}

.tenant-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 24px;
}

.tenant-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px;
  background: var(--t-bg-elevated);
  border: 1px solid var(--t-border-subtle);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.3s;
}

.tenant-card:hover {
  border-color: var(--t-brand);
  box-shadow: 0 2px 12px var(--t-brand-subtle);
  transform: translateY(-2px);
}

.tenant-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: var(--t-brand-gradient);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 20px;
  font-weight: 600;
  flex-shrink: 0;
}

.tenant-info {
  flex: 1;
}

.tenant-name {
  font-size: 16px;
  font-weight: 500;
  color: var(--t-text-primary);
  margin-bottom: 4px;
}

.tenant-code {
  font-size: 13px;
  color: var(--t-text-secondary);
}

.arrow-icon {
  font-size: 20px;
  color: var(--t-text-muted);
  transition: all 0.3s;
}

.tenant-card:hover .arrow-icon {
  color: var(--t-brand);
  transform: translateX(4px);
}

.select-footer {
  text-align: center;
  padding-top: 16px;
  border-top: 1px solid var(--t-border-subtle);
}
</style>
