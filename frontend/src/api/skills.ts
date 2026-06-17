import request from '@/utils/request'

// 技能库 API —— 对接后端 /api/skills（list/upload/delete）。
// request 已在响应拦截器里 unwrap 出 response.data，所以这里第二个泛型 = 后端真实返回体。
// baseURL 已是 /api，故路径写 /skills 即可。

export interface SkillItem {
  name: string
  description: string
  source: 'platform' | 'user'
  files: string[]
}

/** 列出全部技能（平台预置 + 本地上传）。 */
export async function listSkills(): Promise<SkillItem[]> {
  const data = await request.get<any, { skills?: SkillItem[] }>('/skills')
  return data?.skills || []
}

/** 上传一个技能 zip（含 SKILL.md frontmatter）。 */
export async function uploadSkill(file: File): Promise<{ ok: boolean; name: string }> {
  const fd = new FormData()
  fd.append('file', file)
  return request.post<any, { ok: boolean; name: string }>('/skills', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
}

/** 删除一个本地上传的技能（平台预置不可删，后端会拒绝）。 */
export async function deleteSkill(name: string): Promise<void> {
  await request.delete<any, { ok: boolean }>(`/skills/${encodeURIComponent(name)}`)
}
