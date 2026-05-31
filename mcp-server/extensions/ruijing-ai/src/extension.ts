import * as vscode from 'vscode';
import { ChatHandler } from './chatHandler';
import { ModelSelector } from './modelSelector';
import { Config } from './config';
import { LLMClient } from './llmClient';
import { registerLMProvider } from './lmProvider';

export function activate(context: vscode.ExtensionContext) {
  console.log('[RuijingAI] Extension activating...');

  const config = new Config(context);
  const llmClient = new LLMClient(config);
  const modelSelector = new ModelSelector(config);
  const handler = new ChatHandler(config, modelSelector);

  // 注册后端为 VS Code Language Model Provider（VS Code 1.95+ 要求）
  // 不注册则 chatParticipant 报 "Language model unavailable"
  registerLMProvider(context, config);

  // Register ChatParticipant
  const participant = vscode.chat.createChatParticipant('ruijing-ai.chat', handler.handle.bind(handler));
  participant.iconPath = vscode.Uri.joinPath(context.extensionUri, 'icon.png');
  participant.followupProvider = handler.getFollowupProvider();

  context.subscriptions.push(participant, modelSelector);

  // Load available models from backend
  modelSelector.loadModels(llmClient).catch(err => {
    console.warn('[RuijingAI] Failed to load models:', err);
  });

  // 工作区切换时重新读 config 并刷新模型列表
  // 解决 code-server 启动时 workspaceFolders[0] 为空目录、
  // 用户点 IDE 链接后才切换到真实工作区的问题
  context.subscriptions.push(
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      config.invalidate();
      modelSelector.loadModels(llmClient).catch(err => {
        console.warn('[RuijingAI] Failed to reload models after workspace change:', err);
      });
    })
  );

  console.log('[RuijingAI] Extension activated successfully');
}

export function deactivate() {
  console.log('[RuijingAI] Extension deactivated');
}
