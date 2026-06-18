// 把后端两类事件(manual run_result / C5 autofix_round)归一成统一 RunResult。
export interface RunResult {
  source: 'manual' | 'autofix'
  dev_url: string
  status: 'running' | 'ok' | 'error'
  log_tail: string[]
  errors: string[]
  capture_available: boolean
  round: number | null
}

const AUTOFIX_STATUS: Record<string, RunResult['status']> = {
  verifying: 'running', clean: 'ok', fixing: 'error', repeated: 'error', exhausted: 'error',
}

export function normalizeRunResult(ev: any): RunResult {
  const errors: string[] = Array.isArray(ev?.errors) ? ev.errors : []
  if (ev?.type === 'autofix_round') {
    return {
      source: 'autofix',
      dev_url: String(ev.dev_url || ''),
      status: AUTOFIX_STATUS[ev.status] || 'running',
      log_tail: [],
      errors,
      capture_available: ev.capture_available ?? false,
      round: typeof ev.round === 'number' ? ev.round : null,
    }
  }
  // manual run_result
  const st = ev?.status
  return {
    source: 'manual',
    dev_url: String(ev?.dev_url || ''),
    status: (st === 'ok' || st === 'error' || st === 'running') ? st : 'running',
    log_tail: Array.isArray(ev?.log_tail) ? ev.log_tail : [],
    errors,
    capture_available: ev?.capture_available ?? false,
    round: null,
  }
}
