import request from '@/utils/request'
import type { PublicBuilderAuthSettings } from '@/types'

export const authSettingsApi = {
  getPublic() {
    return request.get<any, PublicBuilderAuthSettings>('/auth/settings/public', { authPolicy: 'public' })
  }
}
