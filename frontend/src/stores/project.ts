import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

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

export const useProjectStore = defineStore('project', () => {
  const projects = ref<Project[]>([
    { id: 'p-default',  name: '得帆云示例租户',  customerName: '内部演示', stage: '已上线', progress: 100, appCount: 6,  deployCount: 12, memberCount: 4, envCount: 3, industryPackId: null },
    { id: 'p-auto',     name: '某汽车制造客户',  customerName: '汽车制造业', stage: '开发中', progress: 62,  appCount: 4,  deployCount: 9,  memberCount: 6, envCount: 3, industryPackId: 'pack-mfg' },
    { id: 'p-retail',   name: '某连锁零售客户',  customerName: '连锁零售业', stage: '测试中', progress: 78,  appCount: 7,  deployCount: 14, memberCount: 5, envCount: 3, industryPackId: 'pack-ops' },
    { id: 'p-logistic', name: '某物流客户',      customerName: '物流业',     stage: '设计中', progress: 24,  appCount: 2,  deployCount: 1,  memberCount: 3, envCount: 2, industryPackId: null },
  ])
  const currentProjectId = ref<string>(localStorage.getItem(STORAGE_KEY) ?? 'p-default')

  const currentProject = computed<Project | null>(
    () => projects.value.find(p => p.id === currentProjectId.value) ?? projects.value[0] ?? null,
  )

  function setCurrent(id: string) {
    currentProjectId.value = id
    localStorage.setItem(STORAGE_KEY, id)
  }

  function setProjects(next: Project[]) {
    projects.value = next
  }

  return { projects, currentProjectId, currentProject, setCurrent, setProjects }
})
