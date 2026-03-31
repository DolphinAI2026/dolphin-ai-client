import * as vscode from 'vscode';
import { extractMentionedPaths } from './utils';

const EXCLUDE_PATTERN = '**/node_modules/**,**/dist/**,**/.git/**,**/*.zip,**/*.jar,**/*.war,**/target/**,**/build/**,**/.idea/**';
const MAX_FILE_CONTENT = 2600;
const MAX_SCAFFOLD_FILE_CONTENT = 9000; // Higher limit for structurally critical files
const MAX_FILES_TO_READ = 24;
const MAX_TOTAL_CONTENT = 36000;
const MAX_WORKSPACE_FILE_INDEX = 60;
const CACHE_TTL = 120_000; // 2 min
const SOURCE_FILE_RE = /\.(vue|js|jsx|ts|tsx|json|java|xml|yml|yaml|properties|scss|css|less|html)$/i;
const I18N_TASK_RE = /(国际化|i18n|多语言|语言包|locale|翻译|文案)/i;
const FORM_COMPONENT_TASK_RE = /(组件|widget|表单组件|form-component|render|渲染|upload|avatar|date|picker)/i;
const CONFIG_TASK_RE = /(componentModelField|配置文件|配置项|config|widget\.config|editor\.config|字段类型|数据模型|STRING|DATE|字段绑定)/i;
const STOP_WORDS = new Set([
  'src', 'form', 'component', 'widget', 'config', 'file', 'path', 'this', 'that',
  'date', 'range', 'string', 'model', 'field', 'type', 'please', 'help', 'code',
]);

interface CacheEntry {
  key: string;
  text: string;
  ts: number;
}

export class ContextBuilder {
  private cache: CacheEntry | null = null;
  private dirty = false;

  markDirty(): void {
    this.dirty = true;
  }

  async build(userMessage: string): Promise<string> {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders?.length) return '';

    const mentioned = extractMentionedPaths(userMessage);
    const cacheKey = this._buildCacheKey(mentioned, userMessage);

    if (this.cache && !this.dirty && this.cache.key === cacheKey && Date.now() - this.cache.ts < CACHE_TTL) {
      return this.cache.text;
    }

    try {
      const result = await this._buildContext(folders[0], mentioned, userMessage);
      this.cache = { key: cacheKey, text: result, ts: Date.now() };
      this.dirty = false;
      return result;
    } catch (err) {
      console.warn('[RuijingAI] contextBuilder failed', err);
      return '';
    }
  }

  private async _buildContext(folder: vscode.WorkspaceFolder, mentioned: string[], userMessage: string): Promise<string> {
    // Find all workspace files
    const allFiles = await vscode.workspace.findFiles(
      new vscode.RelativePattern(folder, '**/*'),
      `{${EXCLUDE_PATTERN}}`,
      500
    );

    const relativePaths = allFiles.map(f => vscode.workspace.asRelativePath(f, false)).sort();
    const isI18nTask = I18N_TASK_RE.test(userMessage);
    const isFormComponentTask = FORM_COMPONENT_TASK_RE.test(userMessage);
    const isConfigTask = CONFIG_TASK_RE.test(userMessage);
    const activeSourceFiles = vscode.window.visibleTextEditors
      .map(editor => vscode.workspace.asRelativePath(editor.document.uri, false))
      .filter(rel =>
        !!rel &&
        SOURCE_FILE_RE.test(rel) &&
        !rel.startsWith('.cursor/rules/') &&
        !rel.startsWith('.claude/rules/') &&
        !/\.(md|mdc|txt)$/i.test(rel)
      ) as string[];
    const searchTerms = this._extractSearchTerms(userMessage, mentioned, activeSourceFiles);

    // Decide which files to read
    const toRead: string[] = [];
    const pushUnique = (path: string) => {
      if (path && !toRead.includes(path)) toRead.push(path);
    };

    // Priority 1: files mentioned in user message
    for (const m of mentioned) {
      for (const candidate of this._expandMentionedPathCandidates(m)) {
        const matches = relativePaths.filter(p => p.endsWith(candidate) || p.includes(candidate));
        for (const match of matches.slice(0, 4)) pushUnique(match);
      }
    }

    // Priority 2: prompt-relevant files from path scoring
    const scoredFiles = relativePaths
      .filter(rel => SOURCE_FILE_RE.test(rel))
      .map(rel => ({
        rel,
        score: this._scorePath(rel, searchTerms, {
          activeSourceFiles,
          isConfigTask,
          isI18nTask,
          isFormComponentTask,
        }),
      }))
      .filter(item => item.score > 0)
      .sort((a, b) => b.score - a.score || a.rel.localeCompare(b.rel));

    for (const item of scoredFiles.slice(0, 12)) pushUnique(item.rel);

    // Priority 3: currently open editors
    for (const rel of activeSourceFiles) pushUnique(rel);

    // Priority 4: scaffold-aware — detect form-component workspace by apaas.json
    const isFormScaffold = relativePaths.includes('src/apaas.json');
    if (isFormScaffold) {
      const scaffoldFiles = [
        'src/apaas.json',
        'src/index.js',
        'src/form-component/form-widget/index.js',
        'src/form-component/form-editor/index.js',
        'src/form-component/index.js',
        'src/form-component-config/form-widget/index.js',
        'src/form-component-config/form-editor/index.js',
        'src/form-component-config/index.js',
      ];
      // Also find existing widget config files
      for (const p of relativePaths) {
        if (p.endsWith('.widget.config.js') || p.endsWith('.editor.config.js')) {
          if (!scaffoldFiles.includes(p)) scaffoldFiles.push(p);
        }
      }
      const orderedScaffoldFiles = scaffoldFiles
        .filter(sf => relativePaths.includes(sf))
        .sort((a, b) =>
          this._scorePath(b, searchTerms, { activeSourceFiles, isConfigTask, isI18nTask, isFormComponentTask })
          - this._scorePath(a, searchTerms, { activeSourceFiles, isConfigTask, isI18nTask, isFormComponentTask })
        );
      for (const sf of orderedScaffoldFiles) pushUnique(sf);

      if (isI18nTask) {
        const i18nFiles = [
          'src/form-component-local/index.js',
          'src/form-component-local/zh-CN/index.js',
          'src/form-component-local/en-US/index.js',
        ];
        for (const file of i18nFiles) if (relativePaths.includes(file)) pushUnique(file);
      }

      if (isFormComponentTask || isI18nTask) {
        const componentFiles = relativePaths.filter(p =>
          /^src\/form-component\/form-widget\/(edit|ide|read|list|print|search|search-ide)\/.+\.vue$/.test(p) ||
          /^src\/form-component\/form-editor\/.+\.vue$/.test(p)
        );
        const orderedComponentFiles = componentFiles.sort((a, b) =>
          this._scorePath(b, searchTerms, { activeSourceFiles, isConfigTask, isI18nTask, isFormComponentTask })
          - this._scorePath(a, searchTerms, { activeSourceFiles, isConfigTask, isI18nTask, isFormComponentTask })
        );
        for (const file of orderedComponentFiles) pushUnique(file);
      }
    }

    // Priority 5: important files
    const important = ['src/index.js', 'src/index.ts', 'src/main.ts', 'src/App.vue', 'package.json', 'pom.xml'];
    for (const imp of important) {
      if (relativePaths.includes(imp)) pushUnique(imp);
    }

    // Read file contents (limited)
    const excerpts: string[] = [];
    let totalLen = 0;
    for (const rel of toRead.slice(0, MAX_FILES_TO_READ)) {
      if (totalLen > MAX_TOTAL_CONTENT) break;
      try {
        const uri = vscode.Uri.joinPath(folder.uri, rel);
        const bytes = await vscode.workspace.fs.readFile(uri);
        let content = Buffer.from(bytes).toString('utf-8');
        // Structurally critical files (configs, apaas.json) get higher content limit
        const isStructuralFile =
          rel.endsWith('.widget.config.js') ||
          rel.endsWith('.editor.config.js') ||
          rel.endsWith('apaas.json') ||
          rel.includes('/form-component-local/');
        const maxContent = isStructuralFile ? MAX_SCAFFOLD_FILE_CONTENT : MAX_FILE_CONTENT;
        if (content.length > maxContent) {
          content = content.slice(0, maxContent) + '\n/* ... truncated ... */';
        }
        excerpts.push(`### ${rel}\n\`\`\`\n${content}\n\`\`\``);
        totalLen += content.length;
      } catch {
        // file not readable, skip
      }
    }

    // Load skill guides if available
    const skillSection = await this._loadSkills(folder, userMessage);

    const fileListStr = relativePaths.slice(0, MAX_WORKSPACE_FILE_INDEX).join('\n');
    const searchSummary = searchTerms.length ? `SEARCH_TERMS:\n${searchTerms.join(', ')}\n\n` : '';
    return `${searchSummary}RELEVANT_FILE_CONTENTS:\n${excerpts.join('\n\n')}\n\nWORKSPACE_FILE_INDEX(${relativePaths.length}):\n${fileListStr}${skillSection}`;
  }

  private _buildCacheKey(mentioned: string[], userMessage: string): string {
    const normalizedMessage = userMessage.toLowerCase().replace(/\s+/g, ' ').trim().slice(0, 240);
    return `${mentioned.slice().sort().join(',')}|${normalizedMessage}`;
  }

  private _expandMentionedPathCandidates(rawPath: string): string[] {
    const normalized = rawPath.replace(/:\\d+$/g, '').replace(/\\/g, '/');
    const candidates = new Set<string>([normalized]);

    const bundleSuffixes = ['.umd.min.js', '.umd.js', '.common.js', '.css'];
    for (const suffix of bundleSuffixes) {
      if (normalized.endsWith(suffix)) {
        candidates.add(normalized.slice(0, -suffix.length));
      }
    }

    const fileName = normalized.split('/').pop() || normalized;
    candidates.add(fileName);
    return [...candidates].filter(Boolean);
  }

  private _extractSearchTerms(userMessage: string, mentioned: string[], activeSourceFiles: string[]): string[] {
    const terms = new Set<string>();
    const text = userMessage || '';

    for (const path of mentioned) {
      for (const candidate of this._expandMentionedPathCandidates(path)) {
        candidate
          .split(/[\\/._-]+/)
          .filter(Boolean)
          .forEach(part => terms.add(part.toLowerCase()));
        terms.add(candidate.toLowerCase());
      }
    }

    for (const rel of activeSourceFiles.slice(0, 3)) {
      const fileName = rel.split('/').pop() || rel;
      fileName
        .replace(/\.(vue|js|jsx|ts|tsx|json)$/i, '')
        .split(/[._-]+/)
        .filter(Boolean)
        .forEach(part => terms.add(part.toLowerCase()));
    }

    const identifierMatches = text.match(/[A-Za-z][A-Za-z0-9_-]{2,}/g) || [];
    for (const match of identifierMatches) {
      const lower = match.toLowerCase();
      if (!STOP_WORDS.has(lower)) terms.add(lower);
    }

    const prioritized = [...terms]
      .filter(term => term.length >= 3)
      .sort((a, b) => b.length - a.length)
      .slice(0, 12);

    return prioritized;
  }

  private _scorePath(
    rel: string,
    searchTerms: string[],
    options: {
      activeSourceFiles: string[];
      isConfigTask: boolean;
      isI18nTask: boolean;
      isFormComponentTask: boolean;
    }
  ): number {
    const lower = rel.toLowerCase();
    let score = 0;

    if (options.activeSourceFiles.includes(rel)) score += 220;
    if (options.isConfigTask && (lower.endsWith('.widget.config.js') || lower.endsWith('.editor.config.js'))) score += 260;
    if (options.isConfigTask && lower.includes('/form-component-config/')) score += 180;
    if (options.isI18nTask && lower.includes('/form-component-local/')) score += 220;
    if (options.isFormComponentTask && lower.includes('/form-component/')) score += 80;
    if (options.isFormComponentTask && lower.includes('/form-widget/')) score += 90;
    if (options.isFormComponentTask && lower.includes('/form-editor/')) score += 70;

    for (const term of searchTerms) {
      if (!term) continue;
      if (lower === term) score += 240;
      else if (lower.endsWith(`/${term}`)) score += 180;
      else if (lower.includes(term)) score += term.length >= 10 ? 110 : 55;
    }

    return score;
  }

  private async _loadSkills(folder: vscode.WorkspaceFolder, userMessage: string): Promise<string> {
    try {
      const skillPattern = new vscode.RelativePattern(folder, '.claude/skills/*.skill.md');
      const skillFiles = await vscode.workspace.findFiles(skillPattern, undefined, 10);
      if (!skillFiles.length) return '';

      const parts: string[] = [];
      for (const sf of skillFiles.slice(0, 2)) {
        try {
          const bytes = await vscode.workspace.fs.readFile(sf);
          const content = Buffer.from(bytes).toString('utf-8');
          const rel = vscode.workspace.asRelativePath(sf, false);
          parts.push(`### SKILL: ${rel}\n${content.slice(0, 4000)}`);
        } catch {}
      }

      return parts.length ? `\n\nSKILL_GUIDES:\n${parts.join('\n\n')}` : '';
    } catch {
      return '';
    }
  }
}
