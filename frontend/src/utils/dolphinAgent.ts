import request from '@/utils/request'

const DOLPHIN_SCRIPT_ID = 'dolphin-agent-sdk'
const DOLPHIN_SERVER_URL = 'https://dolphin-trial.definesys.cn'
const DOLPHIN_AGENT_CODE = '030a123e61'
const DOLPHIN_BUTTON_TEXT = '问题助手'

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
let syncVersion = 0

function destroyDolphinAgent() {
  try {
    window.DolphinAgent?.destroy?.()
  } catch (error) {
    console.warn('[DolphinAgent] destroy failed', error)
  }
  initializedKey = ''
}

function loadDolphinSdk(): Promise<DolphinAgentGlobal> {
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
    script.src = `${DOLPHIN_SERVER_URL}/embed/sdk.js`
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

export async function initDolphinAgent(authToken: string | null | undefined, localTenantId: number | string | null | undefined) {
  if (typeof window === 'undefined') return
  const version = ++syncVersion
  if (!authToken || !localTenantId) {
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
  const apaasTenantId = String(credentials?.apaas_tenant_id || '').trim()
  if (!credentials?.connected || !apaasToken || !apaasTenantId) {
    destroyDolphinAgent()
    return
  }

  const nextKey = `${apaasTenantId}:${apaasToken}`
  if (nextKey === initializedKey) return

  try {
    const dolphinAgent = await loadDolphinSdk()
    if (version !== syncVersion) return
    destroyDolphinAgent()
    dolphinAgent.init({
      serverUrl: DOLPHIN_SERVER_URL,
      agentCode: DOLPHIN_AGENT_CODE,
      apaasToken,
      apaasTenantId,
      buttonText: DOLPHIN_BUTTON_TEXT,
    })
    initializedKey = nextKey
  } catch (error) {
    console.warn('[DolphinAgent] init failed', error)
  }
}
