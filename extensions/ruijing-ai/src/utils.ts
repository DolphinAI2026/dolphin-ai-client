/** Remove <think>...</think> blocks from LLM output */
export function stripThinkTags(text: string): string {
  return text.replace(/<think>[\s\S]*?<\/think>/gi, '');
}

/** Remove tool_call related tags */
export function stripToolCalls(text: string): string {
  return text
    .replace(/\[?\/?TOOL_CALL\]/gi, '')
    .replace(/<minimax:tool_call>[\s\S]*?<\/minimax:tool_call>/gi, '')
    .replace(/minimax:tool_call/gi, '')
    .replace(/<\/?invoke[^>]*>/gi, '')
    .replace(/\{"tool"\s*[=:>]+\s*"[^"]*"\s*,\s*"path"\s*[=:>]+\s*"[^"]*"\s*\}/g, '');
}

/** Full clean of LLM response text */
export function cleanResponse(text: string): string {
  return stripToolCalls(stripThinkTags(text)).replace(/^\s*[\r\n]+/gm, '').trim();
}

/**
 * Streaming tag stripper — state machine that filters <think> and tool_call
 * blocks on-the-fly as chunks arrive.
 */
export class StreamingTagStripper {
  private buffer = '';
  private inTag = false;
  private tagType: 'think' | 'toolcall' | null = null;

  private static readonly OPEN_PATTERNS = [
    { open: '<think>', close: '</think>', type: 'think' as const },
    { open: '<minimax:tool_call>', close: '</minimax:tool_call>', type: 'toolcall' as const },
  ];

  push(chunk: string): string {
    this.buffer += chunk;
    let output = '';

    while (this.buffer.length > 0) {
      if (this.inTag && this.tagType) {
        const closeTag = StreamingTagStripper.OPEN_PATTERNS.find(p => p.type === this.tagType)?.close || '';
        const closeIdx = this.buffer.indexOf(closeTag);
        if (closeIdx === -1) {
          // Still inside tag, wait for more data
          if (this.buffer.length > 10000) {
            // Safety: flush if buffer too large
            this.buffer = '';
            this.inTag = false;
            this.tagType = null;
          }
          break;
        }
        // Skip everything up to and including close tag
        this.buffer = this.buffer.slice(closeIdx + closeTag.length);
        this.inTag = false;
        this.tagType = null;
        continue;
      }

      // Look for opening tags
      let bestIdx = -1;
      let bestPattern: (typeof StreamingTagStripper.OPEN_PATTERNS)[0] | null = null;
      for (const pat of StreamingTagStripper.OPEN_PATTERNS) {
        const idx = this.buffer.indexOf(pat.open);
        if (idx !== -1 && (bestIdx === -1 || idx < bestIdx)) {
          bestIdx = idx;
          bestPattern = pat;
        }
      }

      if (bestIdx === -1) {
        // No tags found — output everything except last few chars (might be partial tag)
        const safe = Math.max(0, this.buffer.length - 30);
        output += this.buffer.slice(0, safe);
        this.buffer = this.buffer.slice(safe);
        break;
      }

      // Output everything before the tag
      output += this.buffer.slice(0, bestIdx);
      this.buffer = this.buffer.slice(bestIdx + bestPattern!.open.length);
      this.inTag = true;
      this.tagType = bestPattern!.type;
    }

    return output;
  }

  flush(): string {
    const remaining = this.buffer;
    this.buffer = '';
    this.inTag = false;
    this.tagType = null;
    if (this.inTag) return ''; // discard unclosed tag content
    return remaining;
  }
}

/** Extract file paths mentioned in user message */
export function extractMentionedPaths(text: string): string[] {
  const matches = text.match(/[A-Za-z0-9_\-./]+\.\w{1,8}/g) || [];
  return [...new Set(matches)].filter(m => !m.startsWith('http') && m.includes('/') || m.includes('.'));
}

/** Check if user message indicates code editing intent */
export function isEditIntent(text: string): boolean {
  const editPatterns = /(修改|修复|改一下|改下|调整|fix|bug|创建|新增|开发|实现|搭建|编写|生成|写一个|写个|帮我写|做一个|做个|build|create|implement|develop|delete|删除|去掉|加上|加个|添加|增加|替换|改成|改为|加注释|写注释|加comment|重构|refactor|优化|整理|格式化|补充|完善|更新|升级|迁移|移动|重命名|rename|注释|comment|加一下|改一下|写一下|补一下)/i;
  return editPatterns.test(text);
}

/** Check if user message is a plan confirmation */
export function isConfirmation(text: string): boolean {
  return /^(确认|应用|apply|yes|ok|接受|accept|好的|行|可以|没问题|开始|go|start|开始吧|开干|冲)/i.test(text.trim());
}

/** Check if user message is a cancellation */
export function isCancellation(text: string): boolean {
  return /^(取消|拒绝|cancel|no|reject|算了|不要|不用了)/i.test(text.trim());
}
