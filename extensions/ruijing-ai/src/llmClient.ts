import * as vscode from 'vscode';
import { Config } from './config';
import { StreamingTagStripper } from './utils';

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface StreamOptions {
  model: string;
  messages: ChatMessage[];
  maxTokens?: number;
  token?: vscode.CancellationToken;
}

export interface CodingPipelineOptions {
  message: string;
  selectedModel?: string | null;
  conversationId?: number | null;
  projectId?: number | null;
  projectType?: string | null;
  quickCreate?: boolean;
  token?: vscode.CancellationToken;
}

export class LLMClient {
  constructor(private config: Config) {}

  /**
   * Stream LLM response, yielding cleaned text chunks.
   * Calls backend proxy: POST /chat/completions
   */
  async *stream(options: StreamOptions): AsyncGenerator<string, string> {
    const { model, messages, maxTokens = 4096, token } = options;

    const url = this.config.getEndpoint('/chat/completions');
    const headers = this.config.getHeaders();

    const body = JSON.stringify({
      model,
      messages,
      stream: true,
      max_tokens: maxTokens,
      tool_choice: 'none',
    });

    const controller = new AbortController();
    token?.onCancellationRequested(() => controller.abort());

    // Timeout after 120s
    const timeoutId = setTimeout(() => controller.abort(), 120_000);

    let response: Response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers,
        body,
        signal: controller.signal,
      });
    } catch (err: any) {
      clearTimeout(timeoutId);
      if (err.name === 'AbortError') return '';
      throw new Error(`LLM request failed: ${err.message}`);
    }

    clearTimeout(timeoutId);

    if (!response.ok) {
      let errText = '';
      try { errText = (await response.text()).slice(0, 300); } catch {}
      throw new Error(`LLM API ${response.status}: ${errText}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      // Non-streaming fallback
      try {
        const json = await response.json() as any;
        const content = json?.choices?.[0]?.message?.content || '';
        yield content;
        return content;
      } catch {
        return '';
      }
    }

    const decoder = new TextDecoder();
    const stripper = new StreamingTagStripper();
    let fullText = '';
    let buffer = '';
    let lastDataAt = Date.now();
    // 自适应超时：代码生成 45s，问答 15s，默认 30s
    const baseTimeout = (options.maxTokens ?? 0) > 4000 ? 45_000
      : (options.maxTokens ?? 0) < 500 ? 15_000
      : 30_000;

    try {
      while (true) {
        if (token?.isCancellationRequested) break;

        // 自适应 inactivity timeout（收到数据后重置）
        const elapsed = Date.now() - lastDataAt;
        const remainingTimeout = Math.max(5_000, baseTimeout - elapsed);
        const inactivityTimeout = new Promise<{ done: true; timeout: true }>(resolve =>
          setTimeout(() => resolve({ done: true, timeout: true }), remainingTimeout)
        );
        const readResult = reader.read();
        const result = await Promise.race([readResult, inactivityTimeout]) as any;

        if (result.timeout || result.done) {
          if (!result.done) {
            buffer += decoder.decode();
          }
          break;
        }

        lastDataAt = Date.now();
        buffer += decoder.decode(result.value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const payload = line.slice(6).trim();
          if (!payload || payload === '[DONE]') continue;

          try {
            const json = JSON.parse(payload);
            const content = json?.choices?.[0]?.delta?.content;
            if (content) {
              const filtered = stripper.push(content);
              if (filtered) {
                fullText += filtered;
                yield filtered;
              }
            }
          } catch {
            // ignore malformed SSE lines
          }
        }
      }
    } finally {
      try { reader.cancel(); } catch {}
    }

    // Flush remaining
    const remaining = stripper.flush();
    if (remaining) {
      fullText += remaining;
      yield remaining;
    }

    return fullText;
  }

  /**
   * Non-streaming LLM call. Returns full response text.
   */
  async complete(options: Omit<StreamOptions, 'token'>): Promise<string> {
    let fullText = '';
    for await (const chunk of this.stream(options)) {
      fullText += chunk;
    }
    return fullText;
  }

  /**
   * Stream coding pipeline events from the backend runtime.
   * This is the preferred path inside IDE workspaces because it shares
   * the same coding runtime as the web Chat mode.
   */
  async *streamCodingPipeline(options: CodingPipelineOptions): AsyncGenerator<any, void> {
    const { message, selectedModel, conversationId, projectId, projectType, quickCreate = false, token } = options;

    const url = this.config.getHarnessEndpoint('/pipeline');
    const headers = this.config.getHeaders();
    const body = JSON.stringify({
      message,
      selected_model: selectedModel || undefined,
      conversation_id: conversationId ?? this.config.get().conversationId ?? undefined,
      project_id: projectId ?? undefined,
      project_type: projectType ?? undefined,
      quick_create: quickCreate,
    });

    const controller = new AbortController();
    token?.onCancellationRequested(() => controller.abort());
    const timeoutId = setTimeout(() => controller.abort(), 300_000);

    let response: Response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers,
        body,
        signal: controller.signal,
      });
    } catch (err: any) {
      clearTimeout(timeoutId);
      if (err.name === 'AbortError') return;
      throw new Error(`Coding pipeline request failed: ${err.message}`);
    }

    clearTimeout(timeoutId);

    if (!response.ok) {
      let errText = '';
      try { errText = (await response.text()).slice(0, 500); } catch {}
      throw new Error(`Coding pipeline ${response.status}: ${errText}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      return;
    }

    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        if (token?.isCancellationRequested) break;
        const result = await reader.read();
        if (result.done) break;

        buffer += decoder.decode(result.value, { stream: true });
        const chunks = buffer.split('\n\n');
        buffer = chunks.pop() || '';

        for (const chunk of chunks) {
          const lines = chunk.split('\n');
          let eventName = 'message';
          const dataLines: string[] = [];

          for (const line of lines) {
            if (line.startsWith('event:')) {
              eventName = line.slice(6).trim();
            } else if (line.startsWith('data:')) {
              dataLines.push(line.slice(5).trim());
            }
          }

          if (eventName === 'ping') continue;

          const raw = dataLines.join('\n').trim();
          if (!raw || raw === '[DONE]') continue;

          try {
            yield JSON.parse(raw);
          } catch {
            // Ignore malformed event frames
          }
        }
      }
    } finally {
      try { reader.cancel(); } catch {}
    }
  }

  /**
   * Fetch available models from backend.
   */
  async fetchModels(): Promise<{ id: string; name?: string }[]> {
    try {
      const url = this.config.getEndpoint('/models');
      const resp = await fetch(url, { headers: this.config.getHeaders() });
      if (!resp.ok) return [];
      const data = await resp.json() as any;
      return data?.models || data?.data || [];
    } catch {
      return [];
    }
  }
}
