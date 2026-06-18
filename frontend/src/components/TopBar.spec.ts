import { describe, expect, it } from 'vitest'
import topBarSource from './TopBar.vue?raw'

describe('TopBar brand mark', () => {
  it('uses the Ruijing whale mark instead of the legacy letter placeholder', () => {
    expect(topBarSource).toContain('ruijing-whale-mark.svg')
    expect(topBarSource).not.toContain('>A</div>')
  })
})
