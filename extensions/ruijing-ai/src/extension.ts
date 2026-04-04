import * as vscode from 'vscode';
import { ChatHandler } from './chatHandler';
import { ModelSelector } from './modelSelector';
import { Config } from './config';
import { LLMClient } from './llmClient';

export function activate(context: vscode.ExtensionContext) {
  console.log('[RuijingAI] Extension activating...');

  const config = new Config(context);
  const llmClient = new LLMClient(config);
  const modelSelector = new ModelSelector(config);
  const handler = new ChatHandler(config, modelSelector);

  // Register ChatParticipant
  const participant = vscode.chat.createChatParticipant('ruijing-ai.chat', handler.handle.bind(handler));
  participant.iconPath = vscode.Uri.joinPath(context.extensionUri, 'icon.png');
  participant.followupProvider = handler.getFollowupProvider();

  context.subscriptions.push(participant, modelSelector);

  // Load available models from backend
  modelSelector.loadModels(llmClient).catch(err => {
    console.warn('[RuijingAI] Failed to load models:', err);
  });

  console.log('[RuijingAI] Extension activated successfully');
}

export function deactivate() {
  console.log('[RuijingAI] Extension deactivated');
}
