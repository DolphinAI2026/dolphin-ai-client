export interface FormPreviewFieldLike {
  type: string
  width: number
  mobileWidth: number
}

interface RawFormPreviewComponent {
  type?: string
  width?: unknown
  mobile_width?: unknown
  mobileWidth?: unknown
}

const DESKTOP_WIDTH_VALUES = new Set([3, 4, 6, 8, 9, 12])
const MOBILE_WIDTH_VALUES = new Set([6, 12])

export const FULL_WIDTH_WIDGETS = new Set<string>([
  'textarea',
  'richtext',
  'static_text',
  'static_image',
  'divider',
  'placeholder',
  'collapse_layout',
  'tab_layout',
  'frame_layout',
  'template_file',
  'subtable',
  'data_select',
  'data_stat',
  'custom_dev',
])

export function isFullWidthWidget(type: string): boolean {
  return FULL_WIDTH_WIDGETS.has(type)
}

function normalizeGridWidth(value: unknown, fallback: number, allowed: Set<number>): number {
  const parsed = typeof value === 'number' ? value : Number.parseInt(String(value || ''), 10)
  return allowed.has(parsed) ? parsed : fallback
}

export function normalizeFormPreviewField(raw: RawFormPreviewComponent): FormPreviewFieldLike {
  const type = raw.type || 'text'
  const defaultWidth = isFullWidthWidget(type) ? 12 : 3
  return {
    type,
    width: normalizeGridWidth(raw.width, defaultWidth, DESKTOP_WIDTH_VALUES),
    mobileWidth: normalizeGridWidth(raw.mobile_width ?? raw.mobileWidth, 12, MOBILE_WIDTH_VALUES),
  }
}

export function formPreviewRowStyle(field: FormPreviewFieldLike): Record<string, string> {
  return {
    '--fbp-field-span': `span ${field.width}`,
    '--fbp-field-mobile-span': `span ${field.mobileWidth}`,
  }
}
