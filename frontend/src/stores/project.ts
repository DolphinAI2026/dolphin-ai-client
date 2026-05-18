import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { projectsApi, type Project as ApiProject } from '@/api/projects'

export interface Project {
  id: string
  name: string
  customerName: string
  stage: '设计中' | '开发中' | '测试中' | '已上线' | '维护中'
  progress: number
  appCount: number
  deployCount: number
  memberCount: number
  envCount: number
  industryPackId?: string | null
}

const STORAGE_KEY = 'aPaaS:currentProjectId'

function mapApiProject(p: ApiProject): Project {
  const connected = !!p.platform_connected
  return {
    id: String(p.id),
    name: p.name,
    customerName: p.description || p.platform_app_name || '—',
    stage: connected ? '已上线' : '设计中',
    progress: connected ? 100 : 30,
    appCount: 0,
    deployCount: 0,
    memberCount: 0,
    envCount: connected ? 1 : 0,
    industryPackId: null,
  }
}

export const useProjectStore = defineStore('project', () => {
  const projects = ref<Project[]>([])
  const currentProjectId = ref<string>(localStorage.getItem(STORAGE_KEY) ?? '')
  const loading = ref(false)
  const error = ref<string | null>(null)
  let fetched = false

  const currentProject = computed<Project | null>(
    () => projects.value.find(p => p.id === currentProjectId.value) ?? projects.value[0] ?? null,
  )

  function setCurrent(id: string) {
    currentProjectId.value = id
    localStorage.setItem(STORAGE_KEY, id)
  }

  async function fetchProjects(force = false) {
    if (fetched && !force) return
    loading.value = true
    error.value = null
    try {
      const raw = await projectsApi.list()
      const list: ApiProject[] = Array.isArray(raw)
        ? raw
        : ((raw as any)?.items || (raw as any)?.projects || [])
      projects.value = list.map(mapApiProject)
      fetched = true
      // If currentProjectId no longer matches any project, reset to first (or empty)
      if (!projects.value.find(p => p.id === currentProjectId.value)) {
        const nextId = projects.value[0]?.id ?? ''
        currentProjectId.value = nextId
        if (nextId) localStorage.setItem(STORAGE_KEY, nextId)
        else localStorage.removeItem(STORAGE_KEY)
      }
    } catch (e: any) {
      error.value = e?.message || 'fetch projects failed'
    } finally {
      loading.value = false
    }
  }

  function setProjects(next: Project[]) {
    projects.value = next
  }

  return {
    projects,
    currentProjectId,
    currentProject,
    loading,
    error,
    setCurrent,
    fetchProjects,
    setProjects,
  }
})
