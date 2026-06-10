import * as vscode from 'vscode';
import { Config } from './config';

/**
 * 把后端注册为 VS Code 语言模型 Provider（vendor = "copilot"），让内置 Agent 聊天直接用它。
 *
 * ⚠️ code-server 4.112 / VS Code 1.112 用的是 `registerLanguageModelChatProvider`
 * （不是更早的 `registerChatModelProvider`）。生效还需要两件构建期的事（见
 * scripts/patch_vscode_chat_enable.js）：
 *   1. product.json `extensionAllowedProposedApi['apaas-builder.ruijing-ai'] = ['chatProvider']` 放行 proposed API
 *   2. product.json 的 `defaultChatAgent` 重指向 apaas-builder.ruijing-ai / ruijing-ai.chat
 * 以及 package.json 声明 `enabledApiProposals` + `contributes.languageModelChatProviders`。
 *
 * 与本地实证可用的 minimax-chat-provider 同构，区别：流式打**后端** getEndpoint('/chat/completions')
 * （带 ideToken，租户鉴权），而非直连 api.minimax.chat。
 */
export function registerLMProvider(context: vscode.ExtensionContext, config: Config): void {
  const lm = vscode.lm as any;
  const hasNewApi = lm && typeof lm.registerLanguageModelChatProvider === 'function';
  const hasOldApi = lm && typeof lm.registerChatModelProvider === 'function';
  if (!hasNewApi && !hasOldApi) {
    console.warn('[RuijingAI] no language-model provider API available, skipping');
    return;
  }
  if (lm) {
    const methods = Object.keys(lm).filter((k) => typeof lm[k] === 'function');
    console.log('[RuijingAI] vscode.lm methods:', methods.join(', '));
  }

  const textPart = (s: string): any => {
    const V = vscode as any;
    const Ctor = V.LanguageModelTextPart || V.LanguageModelChatResponseTextPart;
    return Ctor ? new Ctor(s) : s;
  };

  // 共用：把消息流式打到后端 chat/completions（OpenAI 兼容、SSE）
  async function streamFromBackend(
    rawMessages: any[],
    progress: vscode.Progress<any>,
    token: vscode.CancellationToken,
  ): Promise<void> {
    const cfg = config.get();
    if (!cfg.apiBase) {
      progress.report(textPart('后端 API 未配置，请在工作区 .vscode/ruijing-ai.json 中设置 apiBase。'));
      return;
    }
    // getEndpoint 会拼出 `${apiBase}/workspace/${wsId}/ide/chat/completions`（后端真实路由）
    const url = config.getEndpoint('/chat/completions');
    const headers = config.getHeaders();
    const body = JSON.stringify({
      model: cfg.model || 'MiniMax-M2.7',
      messages: formatMessages(rawMessages),
      stream: true,
      max_tokens: 8192,
    });

    const controller = new AbortController();
    token.onCancellationRequested(() => controller.abort());

    let response: Response;
    try {
      response = await fetch(url, { method: 'POST', headers, body, signal: controller.signal });
    } catch (err: any) {
      if (err?.name !== 'AbortError') progress.report(textPart(`请求失败: ${err?.message || err}`));
      return;
    }
    if (!response.ok || !response.body) {
      progress.report(textPart(`API 错误 ${response.status}`));
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
            if (content) progress.report(textPart(content));
          } catch {
            /* 忽略坏 SSE 行 */
          }
        }
      }
    } finally {
      try {
        reader.cancel();
      } catch {
        /* ignore */
      }
    }
  }

  function modelInfo() {
    const cfg = config.get();
    return {
      id: 'ruijing-ai',
      name: cfg.model || '睿鲸AI',
      family: 'copilot',
      version: '1.0',
      maxInputTokens: 128000,
      maxOutputTokens: 8192,
      isDefault: true,
      isUserSelectable: true,
      capabilities: { imageInput: false, toolCalling: true },
    };
  }

  try {
    if (hasNewApi) {
      const provider: any = {
        provideLanguageModelChatInformation(_options: any, _token: vscode.CancellationToken) {
          return [modelInfo()];
        },
        async provideLanguageModelChatResponse(
          _info: any,
          messages: any[],
          _options: any,
          progress: vscode.Progress<any>,
          token: vscode.CancellationToken,
        ) {
          await streamFromBackend(messages, progress, token);
        },
        provideTokenCount(_info: any, text: any, _token: vscode.CancellationToken) {
          const s = typeof text === 'string' ? text : text?.value || text?.content || '';
          return Math.ceil(String(s).length / 3);
        },
      };
      context.subscriptions.push(lm.registerLanguageModelChatProvider('copilot', provider));
      console.log('[RuijingAI] registered language model provider (copilot vendor, new API)');
    } else {
      // 旧 1.95 风格兜底
      const provider: any = {
        async provideLanguageModelResponse(
          messages: any[],
          _options: any,
          _extensionId: string,
          progress: vscode.Progress<any>,
          token: vscode.CancellationToken,
        ) {
          await streamFromBackend(messages, progress, token);
        },
        async provideTokenCount() {
          return 1000;
        },
      };
      context.subscriptions.push(
        lm.registerChatModelProvider('apaas-builder.ruijing-ai', provider, {
          name: '睿鲸AI',
          version: '0.1.0',
          family: 'ruijing',
          maxInputTokens: 32000,
          maxOutputTokens: 4096,
          isDefault: true,
        }),
      );
      console.log('[RuijingAI] registered chat model provider (legacy API)');
    }
  } catch (err) {
    console.warn('[RuijingAI] Failed to register LM provider:', err);
  }
}

/** VS Code 消息 → OpenAI {role, content}。兼容 number(枚举 User=1/Assistant=2/System=0) 与字符串 role、parts 数组。 */
function formatMessages(messages: any[]): Array<{ role: string; content: string }> {
  if (!messages) return [];
  return messages.map((m: any) => {
    let role = 'user';
    if (m.role !== undefined) {
      if (typeof m.role === 'number') role = m.role === 2 ? 'assistant' : m.role === 0 ? 'system' : 'user';
      else if (typeof m.role === 'string') role = m.role;
    }
    let content = '';
    if (typeof m.content === 'string') content = m.content;
    else if (Array.isArray(m.content))
      content = m.content.map((p: any) => (typeof p === 'string' ? p : p?.value || p?.text || '')).join('');
    else if (m.text) content = m.text;
    else if (m.content?.value) content = m.content.value;
    return { role, content };
  });
}
