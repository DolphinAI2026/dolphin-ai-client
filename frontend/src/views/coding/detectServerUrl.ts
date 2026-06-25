/**
 * 从终端输出里识别 dev server 地址。覆盖 vite(Local:)/ vue-cli·webpack(App running at)/
 * npm preview / 裸 127.0.0.1。剥 ANSI 色码,取**最后一个**命中(应对端口被占自增、多行打印)。
 * 纯函数,单测覆盖;TerminalTab 负责跨帧缓冲后调它。
 */
const SERVER_URL_RE =
  /(?:Local|App running at|➜\s*Local|Network)[:\s]+(https?:\/\/(?:localhost|127\.0\.0\.1):(\d+)\/?)/gi

export function stripAnsi(s: string): string {
  // eslint-disable-next-line no-control-regex
  return s.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, '')
}

export function detectServerUrl(buf: string): { url: string; port: number } | null {
  const text = stripAnsi(buf)
  let m: RegExpExecArray | null
  let last: RegExpExecArray | null = null
  SERVER_URL_RE.lastIndex = 0
  while ((m = SERVER_URL_RE.exec(text)) !== null) last = m
  if (!last) return null
  try {
    return { url: new URL(last[1]).origin + '/', port: Number(last[2]) }
  } catch {
    return null
  }
}
