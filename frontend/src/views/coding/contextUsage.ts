// coding 上下文用量纯函数(token 显示 + 换 session 告警,#2)。

/** 格式化 token 数:<1000 原样;否则千位带 k(一位小数、去尾 .0)。 */
export function formatTokenCount(n: number): string {
  if (n < 1000) return `${n}`
  return `${(n / 1000).toFixed(1).replace(/\.0$/, '')}k`
}

/** 当前上下文占用比 = contextTokens / budget;budget<=0 时返 0(除零安全)。 */
export function contextRatio(contextTokens: number, budget: number): number {
  return budget > 0 ? contextTokens / budget : 0
}

/** 占用级别:>=1 危险(超预算/压缩线) / >=0.8 警告 / 否则正常。 */
export function contextLevel(ratio: number): 'ok' | 'warn' | 'danger' {
  if (ratio >= 1) return 'danger'
  if (ratio >= 0.8) return 'warn'
  return 'ok'
}
