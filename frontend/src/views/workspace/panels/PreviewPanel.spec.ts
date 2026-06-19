import { describe, expect, it } from 'vitest'
import src from './PreviewPanel.vue?raw'

describe('PreviewPanel', () => {
  it('drives the workspace dev server via codingApi serve endpoints', () => {
    expect(src).toContain('codingApi')
    expect(src).toContain('startServe')
    expect(src).toContain('stopServe')
    expect(src).toContain('getServeStatus')
  })
  it('derives wsId from workspace binding', () => {
    expect(src).toMatch(/binding[\s\S]*workspaceId/)
  })
  it('shows the dev server in an iframe', () => {
    expect(src).toContain('<iframe')
    expect(src).toContain('devUrl')
  })
})
