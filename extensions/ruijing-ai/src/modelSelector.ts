import * as vscode from 'vscode';
import { Config } from './config';
import { LLMClient } from './llmClient';

interface ModelInfo {
  id: string;
  name?: string;
  provider?: string;
}

export class ModelSelector implements vscode.Disposable {
  private statusBarItem: vscode.StatusBarItem;
  private models: ModelInfo[] = [];
  private selectedModel: string | null = null;
  private autoMode = true;
  private disposables: vscode.Disposable[] = [];

  // Known model preferences
  private static readonly EDIT_MODELS = ['claude-sonnet-4-6', 'claude-sonnet-4', 'gpt-5.4', 'gpt-4o'];
  private static readonly CHAT_MODELS = ['qwen3-coder-next', 'qwen-plus', 'gpt-5.4', 'MiniMax-M2.7'];

  constructor(private config: Config) {
    this.statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    this.statusBarItem.command = 'ruijing-ai.selectModel';
    this.statusBarItem.tooltip = '睿鲸AI: 选择模型';
    this.updateLabel();
    this.statusBarItem.show();

    const cmd = vscode.commands.registerCommand('ruijing-ai.selectModel', () => this.showPicker());
    this.disposables.push(cmd, this.statusBarItem);
  }

  /**
   * Resolve the model to use based on intent.
   */
  resolve(isEdit: boolean): string {
    const cfg = this.config.get();

    if (!this.autoMode && this.selectedModel) {
      return this.selectedModel;
    }

    const preferred = isEdit ? ModelSelector.EDIT_MODELS : ModelSelector.CHAT_MODELS;

    for (const pref of preferred) {
      const matched = this.findModelByNeedle(pref);
      if (matched) return matched.id;
    }

    const configured = this.findModelByNeedle(cfg.model);
    if (configured) return configured.id;

    return cfg.model || 'MiniMax-M2.7';
  }

  async loadModels(llmClient: LLMClient): Promise<void> {
    this.models = await llmClient.fetchModels();
    this.autoMode = this.config.get().autoMode;
    this.updateLabel();
  }

  private updateLabel(): void {
    if (this.autoMode) {
      this.statusBarItem.text = '$(sparkle) Auto';
    } else {
      const name = this.findModelByNeedle(this.selectedModel || this.config.get().model)?.name
        || this.selectedModel
        || this.config.get().model;
      // Shorten model name for display
      const short = name.replace(/^claude-/, '').replace(/^gpt-/, 'GPT-').slice(0, 15);
      this.statusBarItem.text = `$(sparkle) ${short}`;
    }
  }

  private findModelByNeedle(needle: string | null | undefined): ModelInfo | undefined {
    const normalized = (needle || '').trim().toLowerCase();
    if (!normalized) return undefined;

    return this.models.find(model => {
      const id = (model.id || '').toLowerCase();
      const name = (model.name || '').toLowerCase();
      return id === normalized || name === normalized || id.includes(normalized) || name.includes(normalized);
    });
  }

  private async showPicker(): Promise<void> {
    const items: vscode.QuickPickItem[] = [
      {
        label: '$(sparkle) Auto（推荐）',
        description: 'Edit 用 Claude Sonnet，Chat 用 Qwen',
        picked: this.autoMode,
      },
      { label: '', kind: vscode.QuickPickItemKind.Separator },
    ];

    for (const model of this.models) {
      items.push({
        label: model.name || model.id,
        description: model.provider || '',
        picked: !this.autoMode && this.selectedModel === model.id,
      });
    }

    if (this.models.length === 0) {
      items.push({
        label: this.config.get().model,
        description: '默认模型',
      });
    }

    const picked = await vscode.window.showQuickPick(items, {
      title: '睿鲸AI: 选择模型',
      placeHolder: '选择 AI 模型',
    });

    if (!picked) return;

    if (picked.label.includes('Auto')) {
      this.autoMode = true;
      this.selectedModel = null;
    } else {
      this.autoMode = false;
      const model = this.models.find(m => (m.name || m.id) === picked.label);
      this.selectedModel = model?.id || picked.label;
    }

    this.updateLabel();
  }

  dispose(): void {
    for (const d of this.disposables) d.dispose();
  }
}
