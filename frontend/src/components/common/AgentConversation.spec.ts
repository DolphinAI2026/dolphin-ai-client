import { describe, expect, it } from 'vitest'
import src from './AgentConversation.vue?raw'

// 2026-06-19: 对话里上传的图片「加载失败」根因 = <img> GET 取 /api/.../raw 要鉴权 header,
// 原生 <img> 带不了 → 401。前端给站内 /api 相对附件地址拼 ?token=(后端 /raw 用
// auth_from_header_or_query 接住), token 只在内存渲染期拼、不落消息历史/DB。
describe('AgentConversation 附件图片鉴权', () => {
  it('有 withAuthToken: 给站内相对地址拼 token, 外链/blob/data 不动', () => {
    expect(src).toContain('function withAuthToken')
    expect(src).toMatch(/url\.startsWith\('\/'\)/)          // 仅站内相对址
    expect(src).toContain("localStorage.getItem('token')")  // token 来源(不落库)
    expect(src).toMatch(/token=/)                            // 拼 token query
  })

  it('图片 <img> src 与预览列表都经 withAuthToken', () => {
    expect(src).toMatch(/:src="withAuthToken\(a\.url\)"/)
    expect(src).toMatch(/imageAttachmentUrls[\s\S]*withAuthToken/)
  })
})
