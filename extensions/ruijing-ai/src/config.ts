import * as vscode from 'vscode';
import * as path from 'path';

export interface RuijingConfig {
  workspaceId: string;
  ideToken: string;
  apiBase: string;
  apiKey: string;
  model: string;
  autoMode: boolean;
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
    let fileConfig: Record<string, string> = {};
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

    return {
      workspaceId: fileConfig.workspaceId || '',
      ideToken: fileConfig.ideToken || '',
      apiBase: fileConfig.apiBase || vsConfig.get<string>('apiBase') || '',
      apiKey: fileConfig.apiKey || vsConfig.get<string>('apiKey') || '',
      model: fileConfig.model || vsConfig.get<string>('model') || 'MiniMax-M2.7',
      autoMode: vsConfig.get<boolean>('autoMode') ?? true,
    };
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
