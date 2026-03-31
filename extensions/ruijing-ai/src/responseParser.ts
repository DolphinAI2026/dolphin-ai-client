export interface FileEdit {
  path: string;
  content: string;
  action: 'write' | 'create' | 'delete';
}

export interface Plan {
  summary: string;
  files: { path: string; description: string }[];
  userMsg?: string;
}

export type ParseResult =
  | { type: 'chat' }
  | { type: 'edits'; edits: FileEdit[]; summary: string }
  | { type: 'plan'; plan: Plan };

/**
 * Parse LLM response to determine if it contains FILE blocks, a plan, or plain chat.
 * @param activeFilePath - path of the currently active editor file (for fallback detection)
 */
export function parseResponse(text: string, activeFilePath?: string): ParseResult {
  // Try FILE blocks first
  const edits = parseFileBlocks(text);
  if (edits.edits.length > 0) {
    return { type: 'edits', edits: edits.edits, summary: edits.summary };
  }

  // Try plan format
  const plan = parsePlan(text);
  if (plan.files.length > 0) {
    return { type: 'plan', plan };
  }

  // Fallback: detect large code blocks without FILE: prefix
  // If user has a file open and response contains substantial code, treat as edit
  if (activeFilePath) {
    const fallbackEdits = parseCodeBlocksFallback(text, activeFilePath);
    if (fallbackEdits.length > 0) {
      return { type: 'edits', edits: fallbackEdits, summary: '' };
    }
  }

  return { type: 'chat' };
}

/**
 * Fallback: extract large code blocks from response and associate with active file.
 * Only triggers when:
 * 1. There's a code block with >10 lines
 * 2. The code looks like a full file (has <template>, <script>, export, package, import, etc.)
 */
export function parseCodeBlocksFallback(text: string, activeFilePath: string): FileEdit[] {
  const codeBlockPattern = /```[\w]*\n([\s\S]*?)```/g;
  let match: RegExpExecArray | null;
  const candidates: string[] = [];

  while ((match = codeBlockPattern.exec(text)) !== null) {
    const content = match[1];
    const lines = content.split('\n').length;
    if (lines < 10) continue;

    // Check if it looks like a full file
    const fullFileIndicators = [
      /^<template>/m,           // Vue SFC
      /^<script/m,              // Vue/Svelte SFC
      /^import\s/m,             // JS/TS module
      /^export\s+(default|class|function|const)/m, // JS/TS export
      /^package\s+\w/m,         // Java/Go
      /^(public|private)\s+(class|interface)/m, // Java
      /^#(include|import|pragma)/m, // C/C++
      /^(def|class)\s+\w/m,     // Python
    ];

    if (fullFileIndicators.some(pat => pat.test(content))) {
      candidates.push(content);
    }
  }

  if (candidates.length === 1) {
    // Single full-file code block → apply to active file
    return [{
      path: activeFilePath,
      content: candidates[0],
      action: 'write',
    }];
  }

  return [];
}

/**
 * Parse FILE: path + code block format from LLM response.
 * Format:
 *   ## Summary text
 *   FILE: src/path/File.java
 *   ```java
 *   // full file content
 *   ```
 */
export function parseFileBlocks(text: string): { edits: FileEdit[]; summary: string } {
  const edits: FileEdit[] = [];
  let summary = '';

  // Extract summary
  const summaryMatch = text.match(/^##\s*(?:总结|Summary|概要)[：:]\s*(.+)/m);
  if (summaryMatch) {
    summary = summaryMatch[1].trim();
  }

  // Match FILE: path followed by code block
  const filePattern = /FILE:\s*([^\n]+)\s*\n\s*```[\w]*\n([\s\S]*?)```/g;
  let match: RegExpExecArray | null;

  while ((match = filePattern.exec(text)) !== null) {
    const path = match[1].trim().replace(/^[`'"]+|[`'"]+$/g, '').replace(/^\/+/, '');
    const content = match[2];

    if (path && content && !path.includes('..')) {
      edits.push({
        path,
        content,
        action: 'write',
      });
    }
  }

  return { edits, summary };
}

/**
 * Parse plan format from LLM response.
 * Format:
 *   ## 实现方案：description
 *   1. `path/to/file.java` — description
 *   2. `path/to/file2.java` — description
 */
export function parsePlan(text: string): Plan {
  const files: { path: string; description: string }[] = [];

  // Extract summary
  let summary = '';
  const summaryMatch = text.match(/^##\s*(?:实现方案|计划|Plan)[：:]\s*(.+)/m);
  if (summaryMatch) {
    summary = summaryMatch[1].trim();
  }

  // Match numbered items with backtick-quoted paths
  const itemPattern = /^\s*\d+\.\s*`([^`]+)`\s*[—\-–]\s*(.+)/gm;
  let match: RegExpExecArray | null;

  while ((match = itemPattern.exec(text)) !== null) {
    const path = match[1].trim().replace(/^\/+/, '');
    const description = match[2].trim();
    if (path && description) {
      files.push({ path, description });
    }
  }

  return { summary, files };
}
