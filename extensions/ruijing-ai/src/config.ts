import * as vscode from 'vscode';
import * as path from 'path';

export interface RuijingConfig {
  workspaceId: string;
  ideToken: string;
  apiBase: string;
  harnessApiBase: string;
  apiKey: string;
  model: string;
  conversationId: number | null;
  autoMode: boolean;
  onlineMode: boolean;
}

export class Config {
  private _cached: RuijingConfig | null = null;
  private _cachedAt = 0;

  constructor(private context: vscode.ExtensionContext) {}

  get(): RuijingConfig {
    if (this._cached && Date.now() - this._cachedAt < 30_000) {
      return this._cached;
    }
    this._cached = this._load();
    this._cachedAt = Date.now();
    return this._cached;
  }

  invalidate(): void {
    this._cached = null;
  }

  private _load(): RuijingConfig {
    const vsConfig = vscode.workspace.getConfiguration('ruijing-ai');

    // Try reading .vscode/ruijing-ai.json from workspace
    let fileConfig: Record<string, any> = {};
    const folders = vscode.workspace.workspaceFolders;
    if (folders?.length) {
      try {
        const configPath = path.join(folders[0].uri.fsPath, '.vscode', 'ruijing-ai.json');
        const fs = require('fs');
        if (fs.existsSync(configPath)) {
          fileConfig = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
        }
      } catch {
        // ignore
      }
    }

    const workspaceId = this._asString(fileConfig.workspaceId);
    const runtimeMode = this._asString(fileConfig.runtimeMode);
    const apiBase = this._asString(fileConfig.apiBase) || vsConfig.get<string>('apiBase') || '';

    return {
      workspaceId,
      ideToken: this._asString(fileConfig.ideToken),
      apiBase,
      harnessApiBase: this._asString(fileConfig.harnessApiBase) || this._deriveHarnessApiBase(apiBase),
      apiKey: this._asString(fileConfig.apiKey) || vsConfig.get<string>('apiKey') || '',
      model: this._asString(fileConfig.model) || vsConfig.get<string>('model') || 'MiniMax-M2.7',
      conversationId: this._parseConversationId(fileConfig.conversationId),
      autoMode: vsConfig.get<boolean>('autoMode') ?? true,
      onlineMode: this._parseBoolean(fileConfig.onlineMode)
        || runtimeMode === 'online-coding'
        || workspaceId.startsWith('oc_'),
    };
  }

  async updateWorkspaceConfig(patch: Partial<RuijingConfig>): Promise<void> {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders?.length) return;

    const fs = require('fs');
    const configPath = path.join(folders[0].uri.fsPath, '.vscode', 'ruijing-ai.json');
    let current: Record<string, any> = {};
    try {
      if (fs.existsSync(configPath)) {
        current = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
      }
    } catch {
      current = {};
    }

    const next = {
      ...current,
      ...patch,
    };

    fs.mkdirSync(path.dirname(configPath), { recursive: true });
    fs.writeFileSync(configPath, JSON.stringify(next, null, 2), 'utf-8');
    this.invalidate();
  }

  private _parseConversationId(value: unknown): number | null {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
    return null;
  }

  private _parseBoolean(value: unknown): boolean {
    if (typeof value === 'boolean') return value;
    if (typeof value === 'string') return value.trim().toLowerCase() === 'true';
    return false;
  }

  private _asString(value: unknown): string {
    return typeof value === 'string' ? value : '';
  }

  private _deriveHarnessApiBase(apiBase: string): string {
    return (apiBase || '').replace('/api/coding/', '/api/harness/coding/');
  }

  /** Build the IDE proxy URL for a given workspace */
  getEndpoint(path: string): string {
    const cfg = this.get();
    if (cfg.workspaceId && cfg.apiBase) {
      return `${cfg.apiBase}/workspace/${cfg.workspaceId}/ide${path}`;
    }
    if (cfg.apiBase) {
      return `${cfg.apiBase}${path}`;
    }
    return path;
  }

  getHarnessEndpoint(path: string): string {
    const cfg = this.get();
    const base = cfg.harnessApiBase || this._deriveHarnessApiBase(cfg.apiBase);
    if (cfg.workspaceId && base) {
      return `${base}/workspace/${cfg.workspaceId}/ide${path}`;
    }
    if (base) {
      return `${base}${path}`;
    }
    return path;
  }

  getHeaders(): Record<string, string> {
    const cfg = this.get();
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (cfg.ideToken) {
      headers['X-Vibe-IDE-Token'] = cfg.ideToken;
      headers['Authorization'] = `Bearer ${cfg.ideToken}`;
    } else if (cfg.apiKey) {
      headers['Authorization'] = `Bearer ${cfg.apiKey}`;
    }
    return headers;
  }
}
