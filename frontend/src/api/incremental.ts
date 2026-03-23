/**
 * 增量更新 API
 */

import request from '@/utils/request'

export interface ChangeItem {
  name: string
  code: string
  change_type: 'added' | 'modified' | 'deleted'
  remote_id?: string
  old_value?: Record<string, any>
  new_value?: Record<string, any>
}

export interface DictOptionChange extends ChangeItem {
  dict_code: string
}

export interface DictChange extends ChangeItem {
  option_changes: DictOptionChange[]
}

export interface FieldChange extends ChangeItem {
  model_code: string
  field_type?: string
}

export interface ModelChange extends ChangeItem {
  field_changes: FieldChange[]
}

export interface FormComponentChange extends ChangeItem {
  form_code: string
  component_type?: string
  model_field?: string
  table_model_code?: string
  is_sub_table: boolean
  changed_properties: string[]
}

export interface FormChange extends ChangeItem {
  menu_id?: string
  model_code?: string
  component_changes: FormComponentChange[]
}

export interface ProcessChange extends ChangeItem {
  form_code?: string
}

export interface DiffResponse {
  has_changes: boolean
  summary: string
  role_changes: ChangeItem[]
  dict_changes: DictChange[]
  model_changes: ModelChange[]
  form_changes: FormChange[]
  process_changes: ProcessChange[]
  warnings: string[]
  unsupported_changes: string[]
}

export interface ExecuteRequest {
  new_config: any
  skip_roles?: boolean
  skip_dicts?: boolean
  skip_models?: boolean
  skip_forms?: boolean
  skip_processes?: boolean
}

export interface ExecuteResponse {
  success: boolean
  results: {
    roles: string[]
    dicts: string[]
    models: string[]
    forms: string[]
    processes: string[]
  }
  errors: string[]
  warnings: string[]
}

export interface RemoteData {
  roles: any[]
  dicts: any[]
  dict_options: Record<string, any[]>
  models: any[]
  forms: any[]
  processes: any[]
}

export interface StreamProgressEvent {
  stage?: string
  status?: 'running' | 'done'
  step?: string
  current?: number
  total?: number
  detail?: string
  type?: 'complete' | 'error'
  message?: string
  result?: ExecuteResponse
}

export const incrementalApi = {
  /**
   * 计算配置差异
   */
  computeDiff(appId: number, newConfig: any) {
    return request.post<any, DiffResponse>(`/applications/${appId}/incremental/diff`, {
      new_config: newConfig
    })
  },

  /**
   * 预览增量更新（与 diff 相同，语义用于执行前预览）
   */
  previewUpdate(appId: number, newConfig: any) {
    return request.post<any, DiffResponse>(`/applications/${appId}/incremental/preview`, {
      new_config: newConfig
    })
  },

  /**
   * 执行增量更新
   */
  executeUpdate(appId: number, newConfig: any, options?: {
    skipRoles?: boolean
    skipDicts?: boolean
    skipModels?: boolean
    skipForms?: boolean
    skipProcesses?: boolean
  }) {
    return request.post<any, ExecuteResponse>(`/applications/${appId}/incremental/execute`, {
      new_config: newConfig,
      skip_roles: options?.skipRoles,
      skip_dicts: options?.skipDicts,
      skip_models: options?.skipModels,
      skip_forms: options?.skipForms,
      skip_processes: options?.skipProcesses
    })
  },

  /**
   * 流式执行增量更新（SSE）
   * @param appId 应用ID
   * @param newConfig 新配置
   * @param token 认证token
   * @param onProgress 进度回调
   * @param onComplete 完成回调
   * @param onError 错误回调
   */
  executeUpdateStream(
    appId: number,
    newConfig: any,
    token: string,
    onProgress: (event: StreamProgressEvent) => void,
    onComplete: (result: ExecuteResponse) => void,
    onError: (message: string) => void
  ): () => void {
    const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
    const configParam = encodeURIComponent(JSON.stringify(newConfig))
    const url = `${baseUrl}/api/applications/${appId}/incremental/execute-stream?token=${token}&new_config=${configParam}`

    const eventSource = new EventSource(url)

    eventSource.addEventListener('progress', (e) => {
      try {
        const data = JSON.parse(e.data)
        onProgress(data)
      } catch (err) {
        console.error('Failed to parse progress event:', err)
      }
    })

    eventSource.addEventListener('done', (e) => {
      try {
        const data = JSON.parse(e.data)
        eventSource.close()
        if (data.result) {
          onComplete(data.result)
        } else {
          onComplete({ success: true, results: { roles: [], dicts: [], models: [], forms: [], processes: [] }, errors: [], warnings: [] })
        }
      } catch (err) {
        console.error('Failed to parse done event:', err)
        eventSource.close()
      }
    })

    eventSource.addEventListener('error', (e) => {
      try {
        // @ts-ignore
        if (e.data) {
          // @ts-ignore
          const data = JSON.parse(e.data)
          onError(data.message || '未知错误')
        } else {
          onError('连接错误')
        }
      } catch {
        onError('连接错误')
      }
      eventSource.close()
    })

    eventSource.onerror = () => {
      eventSource.close()
    }

    // 返回取消函数
    return () => {
      eventSource.close()
    }
  },

  /**
   * 获取平台远程数据
   */
  getRemoteData(appId: number) {
    return request.get<any, RemoteData>(`/applications/${appId}/incremental/remote-data`)
  }
}

export default incrementalApi
