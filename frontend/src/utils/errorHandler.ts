/**
 * 统一错误处理入口
 *
 * 现状（重构前）：前端 100+ 处使用 ElMessage.error / console.error / .catch，
 * 写法各异——有些吞了错误用户看不到、有些文案不一致、有些重复弹窗。
 *
 * 此模块提供一个集中入口：
 *   - 自动从 axios error / fetch Response / Error / unknown 里抽取可读文案
 *   - 默认弹 ElMessage + console.error，便于排查
 *   - 兼容现有 Token 过期匹配（保留匹配字符串）
 *
 * ⚠️ 本模块是新增项，不替换现有调用点；替换工作在第二轮。
 */

import { ElMessage } from 'element-plus'

// 与后端 error_messages.py::APAAS_TOKEN_MARKERS 保持一致
const APAAS_TOKEN_MARKERS = [
  'Token已过期或无效',
  'Token已过期',
  '重新连接APaaS平台',
]

export interface HandleErrorOptions {
  /** 用户可见的兜底文案，未能从 err 提取到 detail 时使用 */
  fallback?: string
  /** 是否弹 ElMessage，默认 true */
  toast?: boolean
  /** 是否打 console.error，默认 true */
  log?: boolean
  /** 前缀，例如 "切换模型失败"，最终文案为 `${prefix}: ${detail}` */
  prefix?: string
  /** 静默模式（不 toast 也不 log），只返回文案 */
  silent?: boolean
}

function stringifyErrorValue(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)

  const record = value as Record<string, unknown>
  for (const key of ['detail', 'message', 'error', 'reason', 'msg']) {
    const nested = stringifyErrorValue(record?.[key])
    if (nested) return nested
  }

  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

/**
 * 从任意错误对象中提取可读文案。
 *
 * 支持：
 *   - axios 错误：`err.response.data.detail | message | error`
 *   - 标准 Error：`err.message`
 *   - fetch Response 包装的 Error：尝试读 detail/message
 *   - 字符串：原样返回
 *   - 其他：JSON.stringify
 */
export function extractErrorMessage(err: unknown): string {
  if (err == null) return ''
  if (typeof err === 'string') return err

  const e = err as any

  // axios 错误优先级最高
  const data = e?.response?.data
  if (data) {
    const message = stringifyErrorValue(data)
    if (message) return message
  }

  if (e?.message) return String(e.message)

  return stringifyErrorValue(err)
}

/**
 * 判断消息是否来自 APaaS 平台 Token 失效。
 * 与后端 error_messages.is_apaas_token_error 对称。
 */
export function isApaasTokenError(message: string | undefined | null): boolean {
  if (!message) return false
  return APAAS_TOKEN_MARKERS.some((marker) => message.includes(marker))
}

/**
 * 统一错误处理。
 *
 * 用法：
 *   try { ... } catch (e) { handleError(e, { fallback: '切换模型失败' }) }
 *   try { ... } catch (e) { handleError(e, { prefix: '删除失败' }) }
 */
export function handleError(err: unknown, options: HandleErrorOptions = {}): string {
  const { fallback = '操作失败', toast = true, log = true, prefix, silent = false } = options

  const detail = extractErrorMessage(err) || fallback
  const message = prefix ? `${prefix}: ${detail}` : detail

  if (!silent) {
    if (log) {
      // 保留原始错误对象，方便排查
      console.error(prefix || fallback, err)
    }
    if (toast) {
      ElMessage.error(message)
    }
  }

  return message
}
