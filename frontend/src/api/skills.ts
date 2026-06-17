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

// —— Skill IDE：文件 CRUD / 元数据 / 新建 / 克隆 ——
// 与 /skills 端点一致：request 已 unwrap 出 response.data，第二个泛型 = 后端真实返回体。

export interface SkillFileContent {
  path: string
  content: string
}

/** 列出某技能目录内全部文件的相对路径（含 SKILL.md 与嵌套）。 */
export async function listSkillFiles(name: string): Promise<string[]> {
  const data = await request.get<any, { files?: string[] }>(`/skills/${encodeURIComponent(name)}/files`)
  return data?.files || []
}

/** 读取技能内某个文件内容。 */
export async function readSkillFile(name: string, path: string): Promise<SkillFileContent> {
  return request.get<any, SkillFileContent>(`/skills/${encodeURIComponent(name)}/file`, { params: { path } })
}

/** 写入技能内某个文件（user 技能；平台预置后端会拒绝）。 */
export async function writeSkillFile(name: string, path: string, content: string): Promise<void> {
  await request.post<any, { ok: boolean }>(`/skills/${encodeURIComponent(name)}/file`, { path, content })
}

/** 删除技能内某个文件（SKILL.md 不可删；平台预置后端会拒绝）。 */
export async function deleteSkillFile(name: string, path: string): Promise<void> {
  await request.delete<any, { ok: boolean }>(`/skills/${encodeURIComponent(name)}/file`, { params: { path } })
}

/** 更新技能元数据（SKILL.md frontmatter；平台预置后端会拒绝）。 */
export async function updateSkillMetadata(
  name: string,
  meta: { description?: string; tags?: string[]; display_name?: string },
): Promise<void> {
  await request.put<any, { ok: boolean }>(`/skills/${encodeURIComponent(name)}/metadata`, meta)
}

/** 新建空白 user 技能（骨架 SKILL.md）。 */
export async function createSkill(name: string): Promise<string> {
  const r = await request.post<any, { name: string }>('/skills/new', { name })
  return r.name
}

/** 复制任意技能（含平台预置）为一个 user 技能。 */
export async function cloneSkill(name: string, newName: string): Promise<string> {
  const r = await request.post<any, { name: string }>(`/skills/${encodeURIComponent(name)}/clone`, { new_name: newName })
  return r.name
}
