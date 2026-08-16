import axios from 'axios'
import { API_PREFIX, getCommittedAuthToken } from '@/utils/request'

export interface StandaloneApaasApplication {
  appId?: string | number
  appName?: string | null
  appCode?: string | null
  description?: string | null
  status?: string | null
  updatedAt?: string | null
  already_imported?: boolean
  alreadyImported?: boolean
}

export interface StandaloneApaasApplicationPage {
  items: StandaloneApaasApplication[]
  page?: number
  pageSize?: number
  total?: number
}

function headers(): Record<string, string> {
  const token = getCommittedAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** The pure aPaaS deployment owns this proxy and its Builder AI session. */
export const standaloneApaasApi = {
  listApplications(page = 1, pageSize = 200) {
    return axios.get<StandaloneApaasApplicationPage | StandaloneApaasApplication[]>(
      `${API_PREFIX}/builder-ai/apaas-access/applications`,
      { params: { page, pageSize }, headers: headers() },
    ).then((response) => response.data)
  },
  importApplication(apaasAppId: string) {
    return axios.post(
      `${API_PREFIX}/builder-ai/apaas-access/applications/${encodeURIComponent(apaasAppId)}/import`,
      undefined,
      { headers: headers() },
    ).then((response) => response.data)
  },
}
