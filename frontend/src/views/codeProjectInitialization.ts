import { ref } from 'vue'
import { codeRuntimeApi, type CodeSessionPurpose } from '@/api/codeRuntime'

export interface ProjectInitializationFrame {
  sessionRef: string
}

export function createProjectInitializationDispatcher() {
  const sessionPurposes = new Map<string, CodeSessionPurpose>()
  const dispatchesInFlight = new Set<string>()
  const retrySessionRef = ref('')
  const retryMessage = ref('')

  function rememberSessionPurpose(
    purpose: CodeSessionPurpose,
    ...sessionRefs: Array<string | null | undefined>
  ) {
    for (const sessionRef of sessionRefs) {
      const normalized = String(sessionRef || '').trim()
      if (normalized) sessionPurposes.set(normalized, purpose)
    }
  }

  function clearRetry(sessionRef: string) {
    if (retrySessionRef.value !== sessionRef) return
    retrySessionRef.value = ''
    retryMessage.value = ''
  }

  function dispatch(frame: ProjectInitializationFrame) {
    const sessionRef = frame.sessionRef
    if (
      sessionPurposes.get(sessionRef) !== 'project_initialization'
      || dispatchesInFlight.has(sessionRef)
    ) return
    dispatchesInFlight.add(sessionRef)
    void codeRuntimeApi.dispatchProjectInitialization(sessionRef)
      .then((response) => {
        if (response.state === 'retryable_failed') {
          retrySessionRef.value = sessionRef
          retryMessage.value = '项目初始化检查暂时无法发送，请重试'
          return
        }
        if (response.state === 'sent' || response.state === 'already_sent') {
          clearRetry(sessionRef)
        }
      })
      .catch((error: any) => {
        retrySessionRef.value = sessionRef
        retryMessage.value = error?.response?.data?.detail
          || error?.message
          || '项目初始化检查暂时无法发送，请重试'
      })
      .finally(() => {
        dispatchesInFlight.delete(sessionRef)
      })
  }

  function retry(frames: readonly ProjectInitializationFrame[]) {
    const frame = frames.find(candidate => candidate.sessionRef === retrySessionRef.value)
    if (frame) dispatch(frame)
  }

  return {
    dispatch,
    rememberSessionPurpose,
    retry,
    retryMessage,
    retrySessionRef,
  }
}
