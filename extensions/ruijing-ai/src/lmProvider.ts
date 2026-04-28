import * as vscode from 'vscode';
import { Config } from './config';

/**
 * 将后端注册为 VS Code Language Model Provider。
 * VS Code 1.95+ 要求 chatParticipants 必须有已注册的语言模型，
 * 否则会报 "Language model unavailable"。
 * 通过注册此 Provider，让 VS Code 将我们的后端视为可用的语言模型。
 */
export function registerLMProvider(context: vscode.ExtensionContext, config: Config): void {
  // 兼容性检查：旧版 VS Code / code-server 可能没有此 API
  if (typeof (vscode.lm as any)?.registerChatModelProvider !== 'function') {
    console.warn('[RuijingAI] vscode.lm.registerChatModelProvider not available, skipping');
    return;
  }

  try {
    const provider: vscode.LanguageModelChatProvider = {
      async provideLanguageModelResponse(
        messages: vscode.LanguageModelChatMessage[],
        _options: vscode.LanguageModelChatRequestOptions,
        _extensionId: string,
        progress: vscode.Progress<vscode.LanguageModelChatResponseTextPart | vscode.LanguageModelChatResponseToolCallPart>,
        token: vscode.CancellationToken,
      ): Promise<void> {
        const cfg = config.get();
        const apiBase = cfg.apiBase;

        if (!apiBase) {
          progress.report(new vscode.LanguageModelChatResponseTextPart(
            '后端 API 未配置，请在工作区 .vscode/ruijing-ai.json 中设置 apiBase。'
          ));
          return;
        }

        // 将 VS Code 消息格式转换为 OpenAI 格式
        const chatMessages = messages.map(m => {
          let role: string;
          if (m.role === vscode.LanguageModelChatMessageRole.User) {
            role = 'user';
          } else if (m.role === vscode.LanguageModelChatMessageRole.Assistant) {
            role = 'assistant';
          } else {
            role = 'system';
          }

          const content = m.content
            .map(p => (p instanceof vscode.LanguageModelTextPart ? p.value : ''))
            .join('');

          return { role, content };
        });

        const url = `${apiBase}/chat/completions`;
        const headers = config.getHeaders();

        const body = JSON.stringify({
          model: cfg.model || 'MiniMax-M2.7',
          messages: chatMessages,
          stream: true,
          max_tokens: 4096,
        });

        const controller = new AbortController();
        token.onCancellationRequested(() => controller.abort());

        let response: Response;
        try {
          response = await fetch(url, {
            method: 'POST',
            headers,
            body,
            signal: controller.signal,
          });
        } catch (err: any) {
          if (err.name !== 'AbortError') {
            progress.report(new vscode.LanguageModelChatResponseTextPart(
              `请求失败: ${err.message}`
            ));
          }
          return;
        }

        if (!response.ok || !response.body) {
          progress.report(new vscode.LanguageModelChatResponseTextPart(
            `API 错误 ${response.status}`
          ));
          return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        try {
          while (true) {
            if (token.isCancellationRequested) break;
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
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
                  progress.report(new vscode.LanguageModelChatResponseTextPart(content));
                }
              } catch {
                // 忽略格式错误的 SSE 行
              }
            }
          }
        } finally {
          try { reader.cancel(); } catch {}
        }
      },

      async provideTokenCount(
        _text: string | vscode.LanguageModelChatMessage,
        _token: vscode.CancellationToken,
      ): Promise<number> {
        // 粗略估算，不影响功能
        return 1000;
      },
    };

    const disposable = (vscode.lm as any).registerChatModelProvider(
      'apaas-builder.ruijing-ai',
      provider,
      {
        name: '睿鲸AI',
        version: '0.1.0',
        family: 'ruijing',
        maxInputTokens: 32000,
        maxOutputTokens: 4096,
        isDefault: true,
      },
    );

    context.subscriptions.push(disposable);
    console.log('[RuijingAI] Language model provider registered successfully');
  } catch (err) {
    console.warn('[RuijingAI] Failed to register LM provider:', err);
  }
}
