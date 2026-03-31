import * as vscode from 'vscode';

/** Fixed-path guide files (Claude Code convention) */
const FIXED_GUIDE_FILES: { path: string; maxLen: number; label: string }[] = [
  { path: 'CLAUDE.md', maxLen: 5000, label: 'PROJECT_GUIDE' },
  { path: 'memory.md', maxLen: 2000, label: 'MEMORY' },
  { path: '.claude/rules/coding-style.rule.md', maxLen: 6000, label: 'RULE' },
  { path: '.claude/rules/mpaas-query-reference.rule.md', maxLen: 5000, label: 'RULE' },
  { path: '.claude/rules/dev-workflow.rule.md', maxLen: 3000, label: 'RULE' },
];

/** Glob patterns to discover rule files dynamically */
const RULE_GLOBS = [
  '.cursor/rules/**/*.mdc',    // Cursor rules
  '.cursor/rules/**/*.md',     // Cursor rules (md variant)
  '.claude/rules/**/*.md',     // Claude Code rules
  '.claude/rules/**/*.rule.md',// Claude Code rules
];

const MAX_RULE_FILES = 8;
const MAX_RULE_SIZE = 6000;
const MAX_ALWAYS_APPLY_SIZE = 35000; // alwaysApply: true files get a much higher limit
const MAX_TOTAL_GUIDES = 40000;      // total budget for all guides combined
const CACHE_TTL = 300_000; // 5 min

export class GuidesLoader {
  private cache: { text: string; ts: number } | null = null;

  invalidate(): void {
    this.cache = null;
  }

  async load(): Promise<string> {
    if (this.cache && Date.now() - this.cache.ts < CACHE_TTL) {
      return this.cache.text;
    }

    const folders = vscode.workspace.workspaceFolders;
    if (!folders?.length) return '';

    const root = folders[0];
    const parts: string[] = [];
    const loadedPaths = new Set<string>();

    // 1. Load fixed guide files
    for (const guide of FIXED_GUIDE_FILES) {
      try {
        const uri = vscode.Uri.joinPath(root.uri, guide.path);
        const bytes = await vscode.workspace.fs.readFile(uri);
        const content = Buffer.from(bytes).toString('utf-8');
        if (content.trim()) {
          parts.push(`## ${guide.label}: ${guide.path}\n${content.slice(0, guide.maxLen)}`);
          loadedPaths.add(guide.path);
        }
      } catch {
        // file doesn't exist, skip
      }
    }

    // 2. Discover rule files dynamically (.cursor/rules/*.mdc, .claude/rules/*.md, etc.)
    for (const glob of RULE_GLOBS) {
      try {
        const files = await vscode.workspace.findFiles(
          new vscode.RelativePattern(root, glob),
          undefined,
          MAX_RULE_FILES
        );
        for (const file of files) {
          const relPath = vscode.workspace.asRelativePath(file, false);
          if (loadedPaths.has(relPath)) continue;
          if (parts.length >= MAX_RULE_FILES) break;

          try {
            const bytes = await vscode.workspace.fs.readFile(file);
            let content = Buffer.from(bytes).toString('utf-8');

            // .mdc files may have YAML frontmatter — strip it but note metadata
            const frontmatterMatch = content.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
            let alwaysApply = false;
            if (frontmatterMatch) {
              const frontmatter = frontmatterMatch[1];
              content = frontmatterMatch[2];
              alwaysApply = /alwaysApply:\s*true/i.test(frontmatter);
            }

            if (content.trim()) {
              const limit = alwaysApply ? MAX_ALWAYS_APPLY_SIZE : MAX_RULE_SIZE;
              parts.push(`## RULE: ${relPath}\n${content.slice(0, limit)}`);
              loadedPaths.add(relPath);
            }
          } catch {
            // skip unreadable files
          }
        }
      } catch {
        // glob failed, skip
      }
    }

    // Budget guard: if total exceeds MAX_TOTAL_GUIDES, trim non-critical parts first
    let text = parts.join('\n\n');
    if (text.length > MAX_TOTAL_GUIDES && parts.length > 1) {
      // Remove non-alwaysApply parts from the end until within budget
      while (text.length > MAX_TOTAL_GUIDES && parts.length > 1) {
        const last = parts[parts.length - 1];
        // Keep parts that are large (likely alwaysApply guides)
        if (last.length < MAX_ALWAYS_APPLY_SIZE / 2) {
          parts.pop();
        } else {
          break;
        }
        text = parts.join('\n\n');
      }
      if (text.length > MAX_TOTAL_GUIDES) {
        text = text.slice(0, MAX_TOTAL_GUIDES);
      }
    }

    this.cache = { text, ts: Date.now() };
    console.log(`[RuijingAI] guidesLoader: loaded ${parts.length} guide/rule files, total ${text.length} chars`);
    return text;
  }
}
