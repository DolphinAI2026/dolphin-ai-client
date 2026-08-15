export function createLocalApplicationCode(name: string, suffix: string): string {
  const normalized = String(name || '')
    .trim()
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  const prefix = /^[a-z]/.test(normalized) ? normalized : 'code-app'
  return `${prefix.slice(0, 42)}-${suffix}`.slice(0, 50).replace(/-+$/g, '')
}

export function validateLocalApplicationCode(value: string): string {
  const code = String(value || '').trim()
  if (!code) return '请输入应用编码'
  if (code.length > 50) return '应用编码不能超过 50 个字符'
  if (!/^[a-z][a-z0-9-]*$/.test(code)) return '应用编码须以小写字母开头，只能包含小写字母、数字和连字符'
  return ''
}

export function joinLocalProjectPath(parent: string, appCode: string): string {
  const root = String(parent || '').trim().replace(/[\\/]+$/g, '')
  if (!root) return ''
  const separator = root.includes('\\') ? '\\' : '/'
  return `${root}${separator}${String(appCode || '').trim()}`
}
