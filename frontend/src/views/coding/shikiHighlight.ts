import { createHighlighter, type Highlighter } from 'shiki'

const LANGS = ['vue', 'typescript', 'javascript', 'json', 'html', 'css', 'less', 'markdown', 'bash', 'python']
const THEMES = ['github-light', 'github-dark']

let hlPromise: Promise<Highlighter> | null = null
function getHighlighter(): Promise<Highlighter> {
  if (!hlPromise) hlPromise = createHighlighter({ themes: THEMES, langs: LANGS })
  return hlPromise
}

const EXT_LANG: Record<string, string> = {
  vue: 'vue', ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript',
  json: 'json', html: 'html', css: 'css', less: 'less', md: 'markdown',
  sh: 'bash', bash: 'bash', py: 'python',
}

export function langForPath(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() || ''
  return EXT_LANG[ext] || 'text'
}

const MAX_HIGHLIGHT_BYTES = 400_000

export async function highlightCode(code: string, path: string, dark: boolean): Promise<string> {
  const theme = dark ? 'github-dark' : 'github-light'
  if (code.length > MAX_HIGHLIGHT_BYTES) {
    const esc = code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    return `<pre class="shiki-plain"><code>${esc}</code></pre>`
  }
  const hl = await getHighlighter()
  const lang = hl.getLoadedLanguages().includes(langForPath(path) as any) ? langForPath(path) : 'text'
  return hl.codeToHtml(code, { lang, theme })
}
