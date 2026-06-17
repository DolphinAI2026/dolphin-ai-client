// 桌面首次启动状态: 当前租户是否已配 aPaaS 环境 + LLM 模型。
// 注入 fetcher 便于单测; 默认用真实 API。
import { platformEnvApi } from '@/api/platformEnv'
import { llmConfigApi } from '@/api/llmConfig'

export interface OnboardingState {
  hasEnv: boolean
  hasLlm: boolean
  configured: boolean
}

export async function fetchOnboardingState(
  listEnvs: () => Promise<unknown[]> = async () => platformEnvApi.list(),
  listLlms: () => Promise<unknown[]> = async () => llmConfigApi.list(),
): Promise<OnboardingState> {
  let hasEnv = false
  let hasLlm = false
  try { hasEnv = (await listEnvs()).length > 0 } catch { hasEnv = false }
  try { hasLlm = (await listLlms()).length > 0 } catch { hasLlm = false }
  return { hasEnv, hasLlm, configured: hasEnv && hasLlm }
}
