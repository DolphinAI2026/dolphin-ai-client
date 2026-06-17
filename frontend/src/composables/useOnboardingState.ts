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
  try { hasEnv = (await listEnvs()).length > 0 } catch (e) { console.warn('[onboarding] 读取 aPaaS 环境失败, 视为未配置', e) }
  try { hasLlm = (await listLlms()).length > 0 } catch (e) { console.warn('[onboarding] 读取 LLM 配置失败, 视为未配置', e) }
  return { hasEnv, hasLlm, configured: hasEnv && hasLlm }
}

// 桌面首启缓存: 一旦确认已配齐(本会话内), 路由守卫不再每次导航重复拉取。登出时 reset。
let _onboardingConfirmed = false
export function isOnboardingConfirmed(): boolean { return _onboardingConfirmed }
export function markOnboardingConfirmed(): void { _onboardingConfirmed = true }
export function resetOnboardingCache(): void { _onboardingConfirmed = false }
