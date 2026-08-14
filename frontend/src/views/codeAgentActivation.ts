export type CodeAgentActivationResult<T> =
  | { status: 'current'; value: T }
  | { status: 'stale' }

export interface CodeAgentActivationCoordinator {
  activate<T>(
    shellSessionRef: string,
    isCurrent: () => boolean,
    operation: () => Promise<T>,
  ): Promise<CodeAgentActivationResult<T>>
}

export function createCodeAgentActivationCoordinator(): CodeAgentActivationCoordinator {
  const pendingTurns = new Map<string, Promise<void>>()

  return {
    async activate<T>(shellSessionRef, isCurrent, operation) {
      const key = String(shellSessionRef || '').trim()
      const previousTurn = pendingTurns.get(key)
      let releaseTurn!: () => void
      const currentTurn = new Promise<void>((resolve) => {
        releaseTurn = resolve
      })
      pendingTurns.set(key, currentTurn)

      try {
        if (previousTurn) await previousTurn
        if (!isCurrent()) return { status: 'stale' }

        const value = await operation()
        if (!isCurrent()) return { status: 'stale' }
        return { status: 'current', value }
      } finally {
        releaseTurn()
        if (pendingTurns.get(key) === currentTurn) pendingTurns.delete(key)
      }
    },
  }
}
