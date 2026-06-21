import { ref } from 'vue'
import { projectsApi } from '@/api/projects'
import { buildArtifacts, resolveDependencies, type ArtifactVM, type Mode } from '@/composables/projectVM'

const MODE_GROUP_LABEL: Record<Mode, string> = {
  build: '低代码产物 · Builder',
  lowcode: '低代码二开 · Builder',
  fullcode: '全代码产物 · Code',
  agent: '智能体 · Agent',
}
const MODE_ORDER: Mode[] = ['build', 'lowcode', 'fullcode', 'agent']

async function safe<T>(p: Promise<T>, fallback: T): Promise<T> {
  try {
    return await p
  } catch {
    return fallback
  }
}

export async function buildProjectView(projectId: number, api = projectsApi) {
  const [project, workspaces, members, edges] = await Promise.all([
    safe(api.get(projectId), null as any),
    safe(api.listWorkspaces(projectId), [] as any[]),
    safe(api.listMembers(projectId), [] as any[]),
    safe(api.listDependencies(projectId), [] as any[]),
  ])

  const artifacts = project ? buildArtifacts(project, workspaces) : []
  const groups = MODE_ORDER
    .map(mode => ({
      mode,
      label: MODE_GROUP_LABEL[mode],
      artifacts: artifacts.filter(a => a.mode === mode),
    }))
    .filter(g => g.artifacts.length > 0)

  const dependencies = resolveDependencies(edges, artifacts)

  return {
    project,
    groups,
    members,
    dependencies,
    error: project ? null : ('not_found' as const),
  }
}

export function useProjectArtifacts(projectId: number) {
  const project = ref<any>(null)
  const groups = ref<Array<{ mode: Mode; label: string; artifacts: ArtifactVM[] }>>([])
  const members = ref<any[]>([])
  const dependencies = ref<ReturnType<typeof resolveDependencies>>([])
  const loading = ref(true)
  const error = ref<string | null>(null)

  async function load() {
    loading.value = true
    const r = await buildProjectView(projectId)
    project.value = r.project
    groups.value = r.groups
    members.value = r.members
    dependencies.value = r.dependencies
    error.value = r.error
    loading.value = false
  }

  return { project, groups, members, dependencies, loading, error, load }
}
