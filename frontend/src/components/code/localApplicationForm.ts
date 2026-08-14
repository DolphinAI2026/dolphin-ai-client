import type { LocalApplicationDirectoryMode } from '@/api/codeRuntime'

export const LOCAL_APPLICATION_PATH_MESSAGES: Record<string, string> = {
  LOCAL_APPLICATION_PATH_NOT_ABSOLUTE: '请选择绝对路径的项目目录',
  LOCAL_APPLICATION_PATH_NOT_FOUND: '所选项目目录不存在',
  LOCAL_APPLICATION_PATH_NOT_DIRECTORY: '所选路径不是目录',
  LOCAL_APPLICATION_PATH_UNREADABLE: '所选项目目录不可读',
  LOCAL_APPLICATION_PATH_ALREADY_BOUND: '所选项目目录已绑定到其他应用',
}

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

export function localApplicationProjectPath(
  directoryMode: LocalApplicationDirectoryMode,
  selectedDirectory: string,
  appCode: string,
): string {
  return directoryMode === 'existing_directory'
    ? String(selectedDirectory || '').trim()
    : joinLocalProjectPath(selectedDirectory, appCode)
}

export function describeLocalApplicationError(detail: unknown): string {
  const text = String(detail || '').trim()
  const code = Object.keys(LOCAL_APPLICATION_PATH_MESSAGES).find(candidate => text.includes(candidate))
  return code ? LOCAL_APPLICATION_PATH_MESSAGES[code] : text
}
