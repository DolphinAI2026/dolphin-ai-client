import { describe, it, expect } from 'vitest'
import src from './CodingPage.vue?raw'

describe('CodingPage skill 接线', () => {
  it('imports listSkills from skills api', () => {
    expect(src).toContain("from '@/api/skills'")
    expect(src).toMatch(/listSkills\s*\(/)
  })

  it('binds :skills and @skill-picked on the composer', () => {
    expect(src).toContain(':skills="availableSkills"')
    expect(src).toContain('@skill-picked="onSkillPicked"')
  })

  it('onSkillPicked prepends 请使用技能 prefix to userInput', () => {
    expect(src).toMatch(/function onSkillPicked/)
    expect(src).toContain('请使用技能')
    expect(src).toMatch(/userInput\.value/)
  })
})
