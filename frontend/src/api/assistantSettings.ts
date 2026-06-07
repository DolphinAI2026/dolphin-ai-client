import request from '@/utils/request'

export interface DolphinAssistantSetting {
  tenant_id?: number
  enabled: boolean
  server_url: string
  agent_code: string
  apaas_tenant_id?: string
  button_text: string
  configured?: boolean
  updated_at?: string | null
}

export const assistantSettingsApi = {
  getDolphin: () => request.get<any, DolphinAssistantSetting>('/assistant-settings/dolphin'),
  saveDolphin: (data: DolphinAssistantSetting) =>
    request.put<any, DolphinAssistantSetting>('/assistant-settings/dolphin', data),
  getDolphinPublic: () =>
    request.get<any, DolphinAssistantSetting>('/assistant-settings/dolphin/public'),
}
