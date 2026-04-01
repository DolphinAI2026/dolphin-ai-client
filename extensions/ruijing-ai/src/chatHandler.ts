import * as vscode from 'vscode';
import { Config } from './config';
import { LLMClient, ChatMessage } from './llmClient';
import { ContextBuilder } from './contextBuilder';
import { GuidesLoader } from './guidesLoader';
import { parseResponse } from './responseParser';
import { FileWriter } from './fileWriter';
import { PlanMode } from './planMode';
import { ModelSelector } from './modelSelector';
import { isEditIntent, isConfirmation, isCancellation, cleanResponse } from './utils';

const SYSTEM_PROMPT = `你是集成在 VS Code 风格 IDE 里的中文编程助手。你可以回答问题，也可以直接修改代码文件。

## 你的能力
你能自主判断用户的意图并选择合适的响应方式：

### 模式 A：对话（用户在提问/讨论/看代码/看报错）
直接用 markdown 回答。不要输出 FILE 块。

### 模式 B：代码生成（用户确认了方案，或明确要求改代码/写代码/修bug）
按以下格式输出文件：
## 总结：简短描述
FILE: src/相对路径/Xxx.java
\`\`\`java
// 文件完整内容
\`\`\`
代码块必须包含文件完整内容，不要省略、不要用 // ... 代替。不需要改的文件不要输出。

### 模式 C：方案规划（用户描述了一个新需求，需要创建多个文件）
先输出实现方案（不写代码），让用户确认后再生成：
## 实现方案：简短描述
1. \`文件路径\` — 文件职责说明
2. \`文件路径\` — 文件职责说明
请用户确认后开始生成。

## 重要规则
- 只要用户要求对代码做任何修改（包括加注释、重构、格式化、修bug、加功能），都必须用模式 B 输出完整 FILE 块
- 如果上一轮你已经输出了方案，用户说「确认/开始/好的/ok」，直接进入模式 B 生成代码
- 如果用户说「改一下/修复/直接改/加注释/优化」等，直接进入模式 B
- 只有用户纯粹在问问题、看代码、看报错时才用模式 A
- 永远不要在模式 A 中输出代码块来展示修改后的代码——如果要展示修改，就用模式 B 的 FILE 格式

## 其他
- 默认中文回答
- 不要输出 <think>、TOOL_CALL 等标记
- 不要说无法访问文件，基于已提供的代码上下文回答
- 如果用户没有显式给文件路径，先结合 WORKSPACE_CONTEXT 里已有的文件列表、当前打开的源码文件和项目规则，自主定位最相关的源码文件
- 如果 WORKSPACE_CONTEXT 里的 RELEVANT_FILE_CONTENTS 已经包含候选源码、配置文件或语言包，就视为你已经拿到了文件内容，不要再次要求用户手动粘贴同一个文件
- 不要轻易要求用户手动粘贴文件内容；只有当工作区上下文里确实没有相关文件，或者文件明确缺失时，才说明缺少什么
- 如果当前看到的是 \`.umd.js\`、\`.common.js\`、\`.min.js\`、\`dist/\`、\`build/\` 之类构建产物，请优先回溯 \`src/\` 下源码和配置文件，不要把构建产物当成唯一编辑目标`;

export class ChatHandler {
  private llmClient: LLMClient;
  private contextBuilder: ContextBuilder;
  private guidesLoader: GuidesLoader;
  private fileWriter: FileWriter;
  private planMode: PlanMode;
  private modelsLoaded = false;
  private externalHistoryNoticeShown = new Set<string>();

  constructor(
    private config: Config,
    private modelSelector: ModelSelector,
  ) {
    this.llmClient = new LLMClient(config);
    this.contextBuilder = new ContextBuilder();
    this.guidesLoader = new GuidesLoader();
    this.fileWriter = new FileWriter();
    this.planMode = new PlanMode(this.llmClient, this.fileWriter, this.contextBuilder, this.guidesLoader);
  }

  /**
   * Main chat request handler — registered as ChatParticipant handler.
   */
  async handle(
    request: vscode.ChatRequest,
    context: vscode.ChatContext,
    stream: vscode.ChatResponseStream,
    token: vscode.CancellationToken,
  ): Promise<vscode.ChatResult> {
    // Lazy-load models on first request
    if (!this.modelsLoaded) {
      this.modelsLoaded = true;
      this.modelSelector.loadModels(this.llmClient).catch(() => {});
    }

    const userMsg = request.prompt.trim();
    if (!userMsg) {
      stream.markdown('请输入您的问题或需求。');
      return {};
    }

    if (this._canUseCodingPipeline()) {
      if (this.planMode.hasPending()) {
        this.planMode.clear();
      }

      try {
        this._announceExternalHistoryContext(context, stream);
        await this._handleViaCodingPipeline(userMsg, stream, token);
        return {};
      } catch (err: any) {
        console.warn('[RuijingAI] coding pipeline fallback to legacy mode', err);
        stream.markdown(`\n\n⚠️ 统一 Coding Runtime 暂时不可用，已回退到本地兼容模式。\n`);
      }
    }

    try {
      // Handle pending plan confirmation/cancellation
      if (this.planMode.hasPending()) {
        if (isConfirmation(userMsg)) {
          const plan = this.planMode.getPending()!;
          const model = this.modelSelector.resolve(true);
          stream.markdown('📋 计划已确认，开始逐文件生成...\n');
          await this.planMode.execute(plan, model, stream, token);
          return {};
        }
        if (isCancellation(userMsg)) {
          this.planMode.clear();
          stream.markdown('已取消计划，文件未变动。');
          return {};
        }
        // User sent something else — clear pending plan, process as new request
        this.planMode.clear();
      }

      // Build context
      const [workspaceCtx, guides] = await Promise.all([
        this.contextBuilder.build(userMsg),
        this.guidesLoader.load(),
      ]);

      // Determine model
      const needsCodeModel = isEditIntent(userMsg);
      const model = this.modelSelector.resolve(needsCodeModel);

      // Scope edit requests: if user asks to edit but doesn't specify a file,
      // auto-scope to the active editor file to avoid blowing up context
      let effectiveMsg = userMsg;
      const activeEditor = vscode.window.activeTextEditor;
      const activeFilePath = activeEditor
        ? vscode.workspace.asRelativePath(activeEditor.document.uri, false)
        : undefined;
      const activeFileIsGenerated = activeFilePath ? this._isGeneratedArtifact(activeFilePath) : false;

      if (needsCodeModel && activeFilePath && !this._mentionsSpecificFile(userMsg) && this._shouldScopeToActiveFile(activeFilePath)) {
        // User said something broad like "加注释" without specifying a file
        // → scope to the current file, include its full content
        let activeFileContent = '';
        if (activeEditor) {
          activeFileContent = activeEditor.document.getText();
          if (activeFileContent.length > 8000) {
            activeFileContent = activeFileContent.slice(0, 8000) + '\n/* ... truncated ... */';
          }
        }
        effectiveMsg = `${userMsg}\n\n请只针对当前打开的文件操作: ${activeFilePath}\n\n当前文件完整内容:\n\`\`\`\n${activeFileContent}\n\`\`\``;
      } else if (needsCodeModel && !this._mentionsSpecificFile(userMsg)) {
        effectiveMsg = `${userMsg}\n\n请先根据当前工作区已有源码和规则文件，自主定位最相关的实现文件与国际化文件；除非工作区中确实不存在，否则不要要求用户手动提供文件内容。${
          activeFileIsGenerated ? '\n\n注意：当前激活文件看起来是构建产物或打包输出，请不要围绕它定位，优先寻找 src/ 下的源码、配置文件和语言包。' : ''
        }`;
      }

      // Build messages
      const messages = this._buildMessages(effectiveMsg, workspaceCtx, guides, context);

      // Stream LLM response — increase maxTokens when guides are large (e.g. form component guide)
      const maxTokens = guides.length > 10000 ? 8192 : 4096;
      let fullText = '';
      for await (const chunk of this.llmClient.stream({ model, messages, maxTokens, token })) {
        fullText += chunk;
        stream.markdown(chunk);
      }

      if (!fullText) {
        stream.markdown('模型未返回内容，请重试。');
        return {};
      }

      // Parse response to detect FILE blocks or plan
      const parsed = parseResponse(fullText, activeFilePath);

      if (parsed.type === 'edits') {
        // Apply file edits
        const result = await this.fileWriter.apply(parsed.edits);
        this.contextBuilder.markDirty();

        const appliedList = result.applied.map(a => `- ✅ ${a.path}`).join('\n');
        const skippedList = result.skipped.map(s => `- ❌ ${s.path}: ${s.reason}`).join('\n');
        if (appliedList || skippedList) {
          stream.markdown(
            `\n\n---\n**文件操作结果：**` +
            (appliedList ? `\n${appliedList}` : '') +
            (skippedList ? `\n${skippedList}` : '') +
            '\n'
          );
        }
      } else if (parsed.type === 'plan') {
        // Store plan for confirmation
        parsed.plan.userMsg = userMsg;
        this.planMode.store(parsed.plan);
        stream.markdown('\n\n---\n输入 **确认** 开始逐文件生成代码，或 **取消** 放弃。也可以回复调整要求。\n');
      }
      // type === 'chat' → already displayed via streaming

      return {};
    } catch (err: any) {
      console.error('[RuijingAI] handler error', err);
      stream.markdown(`\n\n❌ 错误: ${err.message || '未知错误'}`);
      return {};
    }
  }

  /**
   * Provide followup buttons for plan confirmation.
   */
  getFollowupProvider(): vscode.ChatFollowupProvider {
    return {
      provideFollowups: (_result, _context, _token) => {
        if (this.planMode.hasPending()) {
          return [
            { prompt: '确认', label: '✅ 确认开始生成' },
            { prompt: '取消', label: '❌ 取消计划' },
          ];
        }
        return [];
      },
    };
  }

  private _canUseCodingPipeline(): boolean {
    const cfg = this.config.get();
    return !!(cfg.workspaceId && cfg.ideToken && (cfg.harnessApiBase || cfg.apiBase));
  }

  private _buildPipelineMessage(userMsg: string): string {
    const activeEditor = vscode.window.activeTextEditor;
    const activeFilePath = activeEditor
      ? vscode.workspace.asRelativePath(activeEditor.document.uri, false)
      : '';

    if (!activeFilePath) return userMsg;

    if (this._isGeneratedArtifact(activeFilePath)) {
      return `${userMsg}\n\n补充上下文：当前激活文件是构建产物 ${activeFilePath}，请优先检查 src/ 下源码、配置文件和入口文件，不要围绕构建产物修改。`;
    }

    return `${userMsg}\n\n补充上下文：当前打开文件为 ${activeFilePath}。如果本次需求与它相关，请优先检查它以及相邻的源码、配置和入口文件。`;
  }

  private async _handleViaCodingPipeline(
    userMsg: string,
    stream: vscode.ChatResponseStream,
    token: vscode.CancellationToken,
  ): Promise<void> {
    const needsCodeModel = isEditIntent(userMsg);
    const model = this.modelSelector.resolve(needsCodeModel);
    const effectiveMsg = this._buildPipelineMessage(userMsg);
    let sawThinkingDelta = false;
    let sawVisibleOutput = false;
    let sawNarrativeOutput = false;

    for await (const event of this.llmClient.streamCodingPipeline({
      message: effectiveMsg,
      selectedModel: model,
      conversationId: this.config.get().conversationId,
      token,
    })) {
      const eventType = event?.type || '';

      if (eventType === 'step') {
        const step = event.step || '';
        const status = event.status || '';
        const text = this._formatPipelineStep(step, status, event.data || {});
        if (text) {
          sawVisibleOutput = true;
          stream.markdown(text);
        }
        continue;
      }

      if (eventType === 'content') {
        const content = cleanResponse(String(event.content || ''));
        if (content.trim()) {
          sawVisibleOutput = true;
          sawNarrativeOutput = true;
          stream.markdown(content);
        }
        continue;
      }

      if (eventType === 'agent_thinking_delta') {
        const delta = cleanResponse(String(event.content || ''));
        if (delta) {
          sawThinkingDelta = true;
          sawVisibleOutput = true;
          sawNarrativeOutput = true;
          stream.markdown(delta);
        }
        continue;
      }

      if (eventType === 'agent_thinking') {
        if (sawThinkingDelta) continue;
        const content = cleanResponse(String(event.content || ''));
        if (content.trim()) {
          sawVisibleOutput = true;
          sawNarrativeOutput = true;
          stream.markdown(content);
        }
        continue;
      }

      if (eventType === 'agent_tool') {
        const toolLabel = event.tool_display || event.tool || '工具';
        const preview = String(event.input_preview || '').trim();
        sawVisibleOutput = true;
        stream.markdown(preview
          ? `\n\n🔧 **${toolLabel}** \`${preview}\`\n`
          : `\n\n🔧 **${toolLabel}**\n`);
        continue;
      }

      if (eventType === 'agent_result') {
        const preview = String(event.output_preview || '').trim();
        if (preview) {
          sawVisibleOutput = true;
          stream.markdown(event.is_error
            ? `\n> ❌ ${preview}\n\n`
            : `\n> ✅ ${preview}\n\n`);
        }
        continue;
      }

      if (eventType === 'agent_done') {
        const result = cleanResponse(String(event.result || ''));
        if (result.trim() && result.trim().toLowerCase() !== 'completed' && !sawNarrativeOutput) {
          sawVisibleOutput = true;
          sawNarrativeOutput = true;
          stream.markdown(`\n\n${result}\n`);
        }
        continue;
      }

      if (eventType === 'agent_error' || eventType === 'error') {
        throw new Error(event.message || 'Coding pipeline failed');
      }

      if (eventType === 'scene_detected' || eventType === 'done') {
        if (event.conversation_id) {
          await this.config.updateWorkspaceConfig({ conversationId: Number(event.conversation_id) });
        }
        continue;
      }
    }

    if (!sawVisibleOutput) {
      stream.markdown('已处理完成。');
    }
  }

  private _formatPipelineStep(step: string, status: string, data: Record<string, any>): string {
    if (step === 'detect_scene' && status === 'running') {
      return '\n\n🔍 正在识别开发场景...\n';
    }
    if (step === 'detect_scene' && status === 'done') {
      return `\n\n✅ 已识别场景：${data.scene_type || 'coding'}\n`;
    }
    if (step === 'create_workspace' && status === 'running') {
      return '\n\n📁 正在创建工作区与初始化脚手架...\n';
    }
    if (step === 'create_workspace' && status === 'done') {
      const name = data.display_name || data.project_name || data.workspace_id || '工作区';
      return `\n\n✅ 工作区已就绪：**${name}**\n`;
    }
    if (step === 'generate' && status === 'running') {
      return '\n\n🤖 正在分析代码并执行修改...\n';
    }
    if (step === 'generate' && status === 'done') {
      return '\n\n✅ 本轮编码已完成\n';
    }
    if (step === 'build' && status === 'running') {
      return '\n\n🏗️ 正在构建打包...\n';
    }
    if (step === 'build' && status === 'done') {
      return '\n\n✅ 构建完成\n';
    }
    if (step === 'debug' && status === 'running') {
      return '\n\n🧪 正在启动调试环境...\n';
    }
    if (step === 'debug' && status === 'done') {
      return '\n\n✅ 调试环境已启动\n';
    }
    return '';
  }

  private _buildMessages(
    userMsg: string,
    workspaceCtx: string,
    guides: string,
    context: vscode.ChatContext,
  ): ChatMessage[] {
    // System prompt with project guides
    const sysContent = [
      SYSTEM_PROMPT,
      workspaceCtx ? `\nWORKSPACE_CONTEXT:\n${workspaceCtx.slice(0, 18000)}` : '',
      guides ? `\nPROJECT_RULES:\n${guides}` : '',
    ].filter(Boolean).join('\n');

    const messages: ChatMessage[] = [
      { role: 'system', content: sysContent },
    ];

    // Add conversation history: prefer in-IDE history, fall back to external chat-history.json
    const hasIdeHistory = context.history.length > 0;

    if (hasIdeHistory) {
      // Use code-server's own Chat history
      for (const turn of context.history.slice(-6)) {
        if (turn instanceof vscode.ChatRequestTurn) {
          messages.push({ role: 'user', content: turn.prompt.slice(0, 1500) });
        } else if (turn instanceof vscode.ChatResponseTurn) {
          let text = '';
          for (const part of turn.response) {
            if (part instanceof vscode.ChatResponseMarkdownPart) {
              text += part.value.value;
            }
          }
          if (text) {
            messages.push({ role: 'assistant', content: text.slice(0, 2000) });
          }
        }
      }
    } else {
      // No in-IDE history — inject external history from .vscode/chat-history.json
      const externalHistoryPayload = this._loadExternalChatHistoryPayload();
      if (externalHistoryPayload.messages.length > 0) {
        messages.push({
          role: 'system',
          content: `以下是用户在 AI Coding 对话中的历史记录（来自 Web 端），请结合这些上下文回答：`,
        });
        for (const msg of externalHistoryPayload.messages.slice(-8)) {
          messages.push({ role: msg.role as 'user' | 'assistant', content: msg.content.slice(0, 2000) });
        }
      }
    }

    // Current user message
    messages.push({ role: 'user', content: userMsg });

    // Guard total size
    // Budget guard: trim workspace context first to preserve guides (which carry scaffold knowledge)
    const totalSize = messages.reduce((acc, m) => acc + m.content.length, 0);
    if (totalSize > 80000) {
      const excess = totalSize - 80000;
      const maxCtx = Math.max(4000, 18000 - excess);
      messages[0] = {
        role: 'system',
        content: [
          SYSTEM_PROMPT,
          workspaceCtx ? `\nWORKSPACE_CONTEXT (trimmed):\n${workspaceCtx.slice(0, maxCtx)}` : '',
          guides ? `\nPROJECT_RULES:\n${guides}` : '',
        ].filter(Boolean).join('\n'),
      };
    }

    return messages;
  }

  private _announceExternalHistoryContext(
    context: vscode.ChatContext,
    stream: vscode.ChatResponseStream,
  ) {
    if (context.history.length > 0) return;
    const payload = this._loadExternalChatHistoryPayload();
    if (!payload.messages.length) return;

    const key = this._getExternalHistoryNoticeKey();
    if (this.externalHistoryNoticeShown.has(key)) return;
    this.externalHistoryNoticeShown.add(key);

    stream.markdown(
      `\n\nℹ️ 已加载当前工作区最近 ${payload.messages.length} 条 AI Coding 历史作为上下文。受 IDE 原生聊天面板限制，旧消息不会自动回放显示在这里。\n\n`,
    );
  }

  private _getExternalHistoryNoticeKey(): string {
    const cfg = this.config.get();
    if (cfg.workspaceId) return cfg.workspaceId;
    const folders = vscode.workspace.workspaceFolders;
    return folders?.[0]?.uri.fsPath || 'default';
  }

  /** Load external chat history from .vscode/chat-history.json (written by backend pipeline) */
  private _loadExternalChatHistoryPayload(): { conversationId: number | null; messages: Array<{ role: string; content: string }> } {
    try {
      const folders = vscode.workspace.workspaceFolders;
      if (!folders?.length) return { conversationId: null, messages: [] };
      const path = require('path');
      const fs = require('fs');
      const historyPath = path.join(folders[0].uri.fsPath, '.vscode', 'chat-history.json');
      if (!fs.existsSync(historyPath)) return { conversationId: null, messages: [] };
      const data = JSON.parse(fs.readFileSync(historyPath, 'utf-8'));
      if (Array.isArray(data?.messages)) {
        return {
          conversationId: Number.isFinite(Number(data.conversation_id)) ? Number(data.conversation_id) : null,
          messages: data.messages.filter((m: any) => m.role && m.content),
        };
      }
    } catch {
      // ignore
    }
    return { conversationId: null, messages: [] };
  }

  /** Check if user message mentions a specific file path */
  private _mentionsSpecificFile(text: string): boolean {
    // Matches patterns like "xxx.vue", "xxx.js", "src/xxx", etc.
    return /[A-Za-z0-9_\-]+\.\w{1,6}/.test(text) || /\bsrc\//.test(text);
  }

  /** Only auto-scope to active file when it looks like a real source/config file. */
  private _shouldScopeToActiveFile(activeFilePath: string): boolean {
    const normalized = activeFilePath.replace(/\\/g, '/');
    if (/^\.cursor\/rules\//.test(normalized) || /^\.claude\/rules\//.test(normalized)) {
      return false;
    }
    if (this._isGeneratedArtifact(normalized)) {
      return false;
    }
    if (/\.(md|mdc|txt)$/i.test(normalized)) {
      return false;
    }
    return /\.(vue|js|jsx|ts|tsx|json|java|xml|yml|yaml|properties|scss|css|less|html)$/i.test(normalized);
  }

  private _isGeneratedArtifact(filePath: string): boolean {
    const normalized = filePath.replace(/\\/g, '/').toLowerCase();
    if (/(^|\/)(dist|build|coverage|out|target|tmp|temp)\//.test(normalized)) {
      return true;
    }
    if (/(^|\/)public\//.test(normalized) && !normalized.startsWith('src/')) {
      return true;
    }
    return /\.(umd(\.min)?|common|min|bundle)\.js$/i.test(normalized);
  }
}
