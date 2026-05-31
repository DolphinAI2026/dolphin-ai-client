import { API_PREFIX } from '@/utils/request'

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
}
