import request from '@/utils/request'
import { API_PREFIX } from '@/utils/request'

export interface CodingRunStatus {
  running: boolean
  last_seq: number
  run_id: string | null
}

/**
 * Harness Coding Pipeline — 替代旧的 /coding/auto-pipeline
 *
 * 请求参数与旧端点完全一致，SSE 返回格式也一致（通过 CodingSSEAdapter 翻译）。
 */
export const harnessApi = {
  /**
   * 发起 coding pipeline（SSE 流式返回）
   * 等效于旧的 POST /api/coding/auto-pipeline
   */
  codingPipelineUrl: `${API_PREFIX}/harness/coding/pipeline`,

  /** 该会话是否有在跑的 coding run（切回会话时据此决定是否重连续看） */
  getCodingRunStatus(conversationId: number): Promise<CodingRunStatus> {
    return request.get(`/harness/coding/run-status?conversation_id=${conversationId}`)
  },

  /** 重连在跑 run 的 SSE URL（给 fetch 用，事件与 pipeline 同构；补 seq>afterSeq + 跟实时） */
  codingAttachUrl(conversationId: number, afterSeq: number): string {
    return `${API_PREFIX}/harness/coding/attach?conversation_id=${conversationId}&after_seq=${afterSeq}`
  },

  /** 显式停止在跑 run（停止键）。run 现在后台续跑，断 SSE 不再停它，必须显式取消。 */
  stopCodingRun(conversationId: number): Promise<{ ok: boolean; stopped: boolean }> {
    return request.post(`/harness/coding/stop?conversation_id=${conversationId}`)
  },
}
