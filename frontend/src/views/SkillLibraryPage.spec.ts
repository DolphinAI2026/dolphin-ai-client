import { describe, expect, it } from 'vitest'
import skillLibrarySource from './SkillLibraryPage.vue?raw'

describe('SkillLibraryPage web upload affordance', () => {
  it('keeps skill upload available with web-compatible copy', () => {
    expect(skillLibrarySource).toContain('上传技能 (.zip/.skill)')
    expect(skillLibrarySource).toContain('用户上传')
    expect(skillLibrarySource).not.toContain('本地上传')
    expect(skillLibrarySource).not.toContain('非桌面端')
  })
})
