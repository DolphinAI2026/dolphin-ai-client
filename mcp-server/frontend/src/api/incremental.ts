/**
 * 增量更新 API
 */

import request, { API_PREFIX } from '@/utils/request'

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

export interface VersionInfo {
  id: number
  version: number
  source: string
  summary: string
  created_at: string
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
    const controller = new AbortController()
    const url = `${API_PREFIX}/applications/${appId}/incremental/execute-stream`
    let finished = false

    const emitEvent = (eventName: string, rawData: string) => {
      try {
        const data = rawData ? JSON.parse(rawData) : {}
        if (eventName === 'progress') {
          onProgress(data)
          return
        }
        if (eventName === 'done') {
          finished = true
          onComplete(
            data.result || {
              success: true,
              results: { roles: [], dicts: [], models: [], forms: [], processes: [] },
              errors: [],
              warnings: []
            }
          )
          controller.abort()
          return
        }
        if (eventName === 'error') {
          finished = true
          onError(data.message || '未知错误')
          controller.abort()
        }
      } catch (err) {
        console.error(`Failed to parse ${eventName} event:`, err, rawData)
        if (eventName === 'error') {
          finished = true
          onError('连接错误')
          controller.abort()
        }
      }
    }

    const processChunk = (chunk: string) => {
      let eventName = 'message'
      const dataLines: string[] = []

      for (const line of chunk.split(/\r?\n/)) {
        if (!line || line.startsWith(':')) continue
        if (line.startsWith('event:')) {
          eventName = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trimStart())
        }
      }

      if (dataLines.length > 0) {
        emitEvent(eventName, dataLines.join('\n'))
      }
    }

    void fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        Authorization: `Bearer ${token}`
      },
      body: JSON.stringify({ new_config: newConfig }),
      signal: controller.signal
    }).then(async (response) => {
      if (!response.ok) {
        let message = '连接错误'
        try {
          const data = await response.json()
          message = data.detail || data.message || message
        } catch {
          try {
            const text = await response.text()
            if (text) message = text
          } catch {
            // ignore
          }
        }
        finished = true
        onError(message)
        return
      }

      if (!response.body) {
        finished = true
        onError('连接错误')
        return
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')

        let separatorIndex = buffer.indexOf('\n\n')
        while (separatorIndex !== -1) {
          const chunk = buffer.slice(0, separatorIndex)
          buffer = buffer.slice(separatorIndex + 2)
          processChunk(chunk)
          if (finished) return
          separatorIndex = buffer.indexOf('\n\n')
        }
      }

      if (buffer.trim()) {
        processChunk(buffer)
      }

      if (!finished) {
        onError('连接中断')
      }
    }).catch((error) => {
      if (controller.signal.aborted || finished) return
      console.error('Incremental stream request failed:', error)
      onError('连接错误')
    })

    return () => {
      controller.abort()
    }
  },

  /**
   * 获取平台远程数据
   */
  getRemoteData(appId: number) {
    return request.get<any, RemoteData>(`/applications/${appId}/incremental/remote-data`)
  },

  /**
   * 预览平台同步差异
   */
  syncPreview(appId: number) {
    return request.get<any, {
      platform_config: any
      local_config: any
      diff: DiffResponse
    }>(`/applications/${appId}/incremental/sync-preview`)
  },

  /**
   * 应用平台同步
   */
  syncApply(appId: number, strategy: 'platform_wins' | 'local_wins' = 'platform_wins') {
    return request.post<any, { success: boolean; message: string; config?: any }>(
      `/applications/${appId}/incremental/sync-apply`,
      { strategy }
    )
  },

  /**
   * 选择性执行增量更新
   */
  executeUpdateSelective(appId: number, newConfig: any, selectedChanges: {
    type: string
    code: string
    change_type: string
  }[]) {
    return request.post<any, ExecuteResponse>(`/applications/${appId}/incremental/execute`, {
      new_config: newConfig,
      selected_changes: selectedChanges,
    })
  },

  /**
   * 获取版本历史
   */
  getVersionHistory(appId: number, limit = 50) {
    return request.get<any, { versions: VersionInfo[] }>(
      `/applications/${appId}/incremental/versions?limit=${limit}`
    )
  },

  /**
   * 获取指定版本配置
   */
  getVersionConfig(appId: number, version: number) {
    return request.get<any, { version: number; config: any }>(
      `/applications/${appId}/incremental/versions/${version}`
    )
  },

  /**
   * 回滚到指定版本
   */
  rollbackToVersion(appId: number, targetVersion: number) {
    return request.post<any, { success: boolean; message: string; diff: DiffResponse; config: any }>(
      `/applications/${appId}/incremental/rollback`,
      { target_version: targetVersion }
    )
  },

  /**
   * 三方冲突检测
   */
  checkConflicts(appId: number, incomingConfig: any, baseVersion?: number) {
    return request.post<any, {
      has_conflicts: boolean
      conflicts: any[]
      safe_incoming: any[]
      safe_current: any[]
    }>(`/applications/${appId}/incremental/check-conflicts`, {
      incoming_config: incomingConfig,
      base_version: baseVersion,
    })
  }
}

export default incrementalApi
