import request from '@/utils/request'
import { assistantSettingsApi, type DolphinAssistantSetting } from '@/api/assistantSettings'

const DOLPHIN_SCRIPT_ID = 'dolphin-agent-sdk'
const DOLPHIN_SERVER_URL = String(import.meta.env.VITE_DOLPHIN_SERVER_URL || 'https://dolphin-trial.definesys.cn').trim()
const DOLPHIN_AGENT_CODE = String(import.meta.env.VITE_DOLPHIN_AGENT_CODE || '').trim()
const DOLPHIN_BUTTON_TEXT = String(import.meta.env.VITE_DOLPHIN_BUTTON_TEXT || '得小帆').trim()

interface DolphinAgentOptions {
  serverUrl: string
  agentCode: string
  apaasToken: string
  apaasTenantId: string
  buttonText: string
}

interface DolphinAgentGlobal {
  init: (options: DolphinAgentOptions) => void
  destroy?: () => void
}

interface ApaasEmbedCredentials {
  connected: boolean
  apaas_token?: string | null
  apaas_tenant_id?: string | null
}

declare global {
  interface Window {
    DolphinAgent?: DolphinAgentGlobal
  }
}

let sdkPromise: Promise<DolphinAgentGlobal> | null = null
let initializedKey = ''
let credentialsPromise: Promise<ApaasEmbedCredentials> | null = null
let credentialsPromiseKey = ''
let settingsPromise: Promise<DolphinAssistantSetting> | null = null
let settingsPromiseKey = ''
let syncVersion = 0

function destroyDolphinAgent() {
  try {
    window.DolphinAgent?.destroy?.()
  } catch (error) {
    console.warn('[DolphinAgent] destroy failed', error)
  }
  initializedKey = ''
}

function loadDolphinSdk(serverUrl: string): Promise<DolphinAgentGlobal> {
  if (window.DolphinAgent) return Promise.resolve(window.DolphinAgent)
  if (sdkPromise) return sdkPromise

  sdkPromise = new Promise((resolve, reject) => {
    const existingScript = document.getElementById(DOLPHIN_SCRIPT_ID) as HTMLScriptElement | null

    const handleLoaded = () => {
      if (window.DolphinAgent) {
        resolve(window.DolphinAgent)
      } else {
        reject(new Error('DolphinAgent SDK loaded but DolphinAgent is missing'))
      }
    }

    if (existingScript) {
      existingScript.addEventListener('load', handleLoaded, { once: true })
      existingScript.addEventListener('error', () => reject(new Error('DolphinAgent SDK failed to load')), { once: true })
      return
    }

    const script = document.createElement('script')
    script.id = DOLPHIN_SCRIPT_ID
    script.src = `${serverUrl}/embed/sdk.js`
    script.async = true
    script.onload = handleLoaded
    script.onerror = () => reject(new Error('DolphinAgent SDK failed to load'))
    document.body.appendChild(script)
  })

  return sdkPromise
}

async function fetchApaasEmbedCredentials(key: string) {
  if (!credentialsPromise || credentialsPromiseKey !== key) {
    credentialsPromiseKey = key
    credentialsPromise = request.get<any, ApaasEmbedCredentials>('/apaas/embed-credentials')
      .finally(() => {
        if (credentialsPromiseKey === key) {
          credentialsPromise = null
          credentialsPromiseKey = ''
        }
      })
  }
  return credentialsPromise
}

async function fetchDolphinSettings(key: string) {
  if (!settingsPromise || settingsPromiseKey !== key) {
    settingsPromiseKey = key
    settingsPromise = assistantSettingsApi.getDolphinPublic()
      .finally(() => {
        if (settingsPromiseKey === key) {
          settingsPromise = null
          settingsPromiseKey = ''
        }
      })
  }
  return settingsPromise
}

export async function initDolphinAgent(authToken: string | null | undefined, localTenantId: number | string | null | undefined) {
  if (typeof window === 'undefined') return
  const version = ++syncVersion
  if (!authToken || !localTenantId) {
    destroyDolphinAgent()
    return
  }

  const configured = await fetchDolphinSettings(`${localTenantId}:${authToken}`).catch((error) => {
    console.warn('[DolphinAgent] failed to fetch assistant settings', error)
    return null
  })
  if (version !== syncVersion) return
  const serverUrl = String(configured?.server_url || DOLPHIN_SERVER_URL || '').trim().replace(/\/+$/, '')
  const agentCode = String(configured?.agent_code || DOLPHIN_AGENT_CODE || '').trim()
  const configuredApaasTenantId = String(configured?.apaas_tenant_id || '').trim()
  const buttonText = String(configured?.button_text || DOLPHIN_BUTTON_TEXT || '得小帆').trim()
  const enabled = configured ? !!configured.enabled : !!DOLPHIN_AGENT_CODE
  if (!enabled || !serverUrl || !agentCode || (configured && !configuredApaasTenantId)) {
    destroyDolphinAgent()
    return
  }

  const credentialsKey = `${localTenantId}:${authToken}`
  const credentials = await fetchApaasEmbedCredentials(credentialsKey).catch((error) => {
    console.warn('[DolphinAgent] failed to fetch aPaaS credentials', error)
    return null
  })
  if (version !== syncVersion) return

  const apaasToken = String(credentials?.apaas_token || '').trim()
  const apaasTenantId = configuredApaasTenantId || String(credentials?.apaas_tenant_id || '').trim()
  if (!credentials?.connected || !apaasToken || !apaasTenantId) {
    destroyDolphinAgent()
    return
  }

  const nextKey = `${serverUrl}:${agentCode}:${buttonText}:${apaasTenantId}:${apaasToken}`
  if (nextKey === initializedKey) return

  try {
    const dolphinAgent = await loadDolphinSdk(serverUrl)
    if (version !== syncVersion) return
    destroyDolphinAgent()
    dolphinAgent.init({
      serverUrl,
      agentCode,
      apaasToken,
      apaasTenantId,
      buttonText,
    })
    initializedKey = nextKey
  } catch (error) {
    console.warn('[DolphinAgent] init failed', error)
  }
}
