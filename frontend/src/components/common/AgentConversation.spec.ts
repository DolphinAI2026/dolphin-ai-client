import { describe, expect, it } from 'vitest'
import src from './AgentConversation.vue?raw'

// 站内附件图片由原生 <img> 读取，必须用已验证的 per-tab committed token 组装 query。
describe('AgentConversation 附件图片鉴权', () => {
  it('有 withAuthToken: 给站内相对地址拼 token, 外链/blob/data 不动', () => {
    expect(src).toContain('function withAuthToken')
    expect(src).toMatch(/url\.startsWith\('\/'\)/)          // 仅站内相对址
    expect(src).toContain('getCommittedAuthTokenOrThrow')
    expect(src).not.toContain("localStorage.getItem('token')")
    expect(src).toMatch(/token=/)                            // 拼 token query
  })

  it('图片 <img> src 与预览列表都经 withAuthToken', () => {
    expect(src).toMatch(/:src="withAuthToken\(a\.url\)"/)
    expect(src).toMatch(/imageAttachmentUrls[\s\S]*withAuthToken/)
  })
})
