import { describe, expect, it } from 'vitest'
import formDesignerPanelSource from './FormDesignerPanel.vue?raw'
import {
  formPreviewRowStyle,
  normalizeFormPreviewField,
} from './formPreviewLayout'

describe('formPreviewLayout', () => {
  it('maps an explicit width to a 12-column desktop grid span', () => {
    const field = normalizeFormPreviewField({
      type: 'text',
      width: 3,
      mobile_width: 12,
    })

    expect(field.width).toBe(3)
    expect(field.mobileWidth).toBe(12)
    expect(formPreviewRowStyle(field)).toEqual({
      '--fbp-field-span': 'span 3',
      '--fbp-field-mobile-span': 'span 12',
    })
  })

  it('keeps full-width widgets on one row without exposing platform helper text', () => {
    const field = normalizeFormPreviewField({
      type: 'textarea',
      helperText: 'external helper text',
    } as any)

    expect(field.width).toBe(12)
    expect('helperText' in field).toBe(false)
    expect(formPreviewRowStyle(field)).toEqual({
      '--fbp-field-span': 'span 12',
      '--fbp-field-mobile-span': 'span 12',
    })
  })

  it('falls back to quarter-row desktop columns for ordinary fields without a platform width', () => {
    const field = normalizeFormPreviewField({
      type: 'text',
    })

    expect(field.width).toBe(3)
    expect(field.mobileWidth).toBe(12)
  })

  it('does not infer layout from caller-specific metadata', () => {
    const field = normalizeFormPreviewField({
      sourceComponentKind: 'multi-line-text',
    } as any)

    expect(field.type).toBe('text')
    expect(field.width).toBe(3)
  })

  it('wires span styles into the real form preview grid', () => {
    expect(formDesignerPanelSource).toContain(':style="formPreviewRowStyle(f)"')
    expect(formDesignerPanelSource).toContain('grid-template-columns: repeat(12, minmax(0, 1fr));')
    expect(formDesignerPanelSource).toContain('grid-column: var(--fbp-field-span, span 3);')
  })
})
