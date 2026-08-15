import axios from 'axios'
import { controlPlaneCodeAuthorization, getControlPlaneCodeSession } from '@/utils/controlPlaneCodeSession'
import { getCommittedAuthToken } from '@/utils/request'

export interface ControlPlaneApaasApplication {
  appId: string
  appName: string
  appCode?: string | null
  description?: string | null
  status?: string | null
  updatedAt?: string | null
  alreadyImported?: boolean
}

export interface ControlPlaneApaasApplicationPage {
  items: ControlPlaneApaasApplication[]
  page: number
  pageSize: number
  total: number
}

function apiBaseUrl(): string {
  const configured = String(import.meta.env.VITE_CONTROL_PLANE_API_URL || '').trim()
  return configured.replace(/\/+$/, '')
}

function headers(): Record<string, string> {
  const auth = controlPlaneCodeAuthorization()
  const token = getCommittedAuthToken()
  const session = getControlPlaneCodeSession()
  return {
    ...(auth || (token ? { Authorization: `Bearer ${token}` } : {})),
    ...(session?.tenantId ? { 'X-Tenant-Id': session.tenantId } : {}),
  }
}

export const controlPlaneApaasApi = {
  listApplications(page = 1, pageSize = 200) {
    return axios.get<ControlPlaneApaasApplicationPage>(
      `${apiBaseUrl()}/api/apaas-access/organization-applications`,
      { params: { page, pageSize }, headers: headers() },
    ).then((response) => response.data)
  },
  importApplication(appId: string) {
    return axios.post<ControlPlaneApaasApplication>(
      `${apiBaseUrl()}/api/apaas-access/organization-applications/${encodeURIComponent(appId)}/import`,
      undefined,
      { headers: headers() },
    ).then((response) => response.data)
  },
}
