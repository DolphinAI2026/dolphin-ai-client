import { describe, expect, it } from 'vitest'
import { resolveAdminEditorState } from './backendConfigTab'

describe('resolveAdminEditorState', () => {
  it('有 url 时显示内嵌, 不带文案', () => {
    expect(resolveAdminEditorState({ ok: true, url: 'https://x/y' }))
      .toEqual({ url: 'https://x/y', msg: '' })
  })

  it('未部署: 用后端给的 message 作引导文案', () => {
    expect(resolveAdminEditorState({ ok: false, error_code: 'APP_NOT_DEPLOYED', message: '应用尚未部署到 aPaaS 平台' }))
      .toEqual({ url: '', msg: '应用尚未部署到 aPaaS 平台' })
  })

  it('ok 但缺 url: 当作未就绪, 落默认文案', () => {
    expect(resolveAdminEditorState({ ok: true }))
      .toEqual({ url: '', msg: '应用尚未部署到平台, 无法打开后台配置' })
  })

  it('null/undefined: 落默认文案', () => {
    expect(resolveAdminEditorState(null)).toEqual({ url: '', msg: '应用尚未部署到平台, 无法打开后台配置' })
    expect(resolveAdminEditorState(undefined)).toEqual({ url: '', msg: '应用尚未部署到平台, 无法打开后台配置' })
  })
})
