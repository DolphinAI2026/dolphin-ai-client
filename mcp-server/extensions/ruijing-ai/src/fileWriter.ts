import * as vscode from 'vscode';
import { FileEdit } from './responseParser';

export interface ApplyResult {
  applied: { path: string; action: string }[];
  skipped: { path: string; reason: string }[];
}

export class FileWriter {
  /**
   * Apply file edits using VS Code's WorkspaceEdit API.
   * This is the official way to create/modify files in VS Code.
   */
  async apply(edits: FileEdit[]): Promise<ApplyResult> {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders?.length) {
      return { applied: [], skipped: [{ path: '', reason: 'No workspace folder' }] };
    }

    const root = folders[0].uri;
    const applied: { path: string; action: string }[] = [];
    const skipped: { path: string; reason: string }[] = [];

    for (const edit of edits.slice(0, 12)) {
      const relPath = edit.path.trim().replace(/\\/g, '/').replace(/^\/+/, '');
      if (!relPath || relPath.includes('..')) {
        skipped.push({ path: relPath || '(empty)', reason: 'Invalid path' });
        continue;
      }

      if (edit.action === 'delete') {
        try {
          const uri = vscode.Uri.joinPath(root, relPath);
          await vscode.workspace.fs.delete(uri, { recursive: true });
          applied.push({ path: relPath, action: 'delete' });
        } catch (err: any) {
          skipped.push({ path: relPath, reason: err.message || 'Delete failed' });
        }
        continue;
      }

      if (!edit.content) {
        skipped.push({ path: relPath, reason: 'Missing content' });
        continue;
      }

      try {
        const uri = vscode.Uri.joinPath(root, relPath);
        const wsEdit = new vscode.WorkspaceEdit();
        const content = Buffer.from(edit.content, 'utf-8');

        // createFile with overwrite handles both create and update
        wsEdit.createFile(uri, {
          overwrite: true,
          ignoreIfExists: false,
          contents: content,
        });

        const ok = await vscode.workspace.applyEdit(wsEdit);
        if (ok) {
          applied.push({ path: relPath, action: edit.action });
        } else {
          skipped.push({ path: relPath, reason: 'applyEdit returned false' });
        }
      } catch (err: any) {
        skipped.push({ path: relPath, reason: err.message || 'Write failed' });
      }
    }

    return { applied, skipped };
  }
}
