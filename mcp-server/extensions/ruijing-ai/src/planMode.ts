import * as vscode from 'vscode';
import { Plan, parseFileBlocks } from './responseParser';
import { LLMClient, ChatMessage } from './llmClient';
import { FileWriter } from './fileWriter';
import { ContextBuilder } from './contextBuilder';
import { GuidesLoader } from './guidesLoader';

export class PlanMode {
  private pendingPlan: Plan | null = null;

  constructor(
    private llmClient: LLMClient,
    private fileWriter: FileWriter,
    private contextBuilder: ContextBuilder,
    private guidesLoader: GuidesLoader,
  ) {}

  hasPending(): boolean {
    return this.pendingPlan !== null;
  }

  store(plan: Plan): void {
    this.pendingPlan = plan;
  }

  clear(): void {
    this.pendingPlan = null;
  }

  getPending(): Plan | null {
    return this.pendingPlan;
  }

  /**
   * Execute a confirmed plan: generate code for each file sequentially.
   */
  async execute(
    plan: Plan,
    model: string,
    stream: vscode.ChatResponseStream,
    token: vscode.CancellationToken,
  ): Promise<void> {
    this.pendingPlan = null;

    const applied: string[] = [];
    const skipped: { path: string; reason: string }[] = [];
    const generatedSummaries: { path: string; excerpt: string }[] = [];

    // Get workspace context and project guides
    const workspaceCtx = await this.contextBuilder.build(plan.userMsg || '');
    const guides = await this.guidesLoader.load();

    for (let i = 0; i < plan.files.length; i++) {
      if (token.isCancellationRequested) break;

      const file = plan.files[i];
      stream.progress(`生成中 (${i + 1}/${plan.files.length}) ${file.path}`);
      stream.markdown(`\n⏳ **生成中 (${i + 1}/${plan.files.length})** \`${file.path}\`...\n`);

      // Build per-file system prompt
      const otherFiles = plan.files
        .filter((_, idx) => idx !== i)
        .map(f => `- \`${f.path}\` — ${f.description}`)
        .join('\n');

      const prevSummary = generatedSummaries
        .map(s => `### ${s.path}\n\`\`\`\n${s.excerpt}\n\`\`\``)
        .join('\n');

      const fileRoleHint = this._getFileRoleHint(file.path);
      const sysContent = [
        '你是 IDE 代码修改代理。现在按照已确认的计划逐文件生成代码。',
        `当前任务：生成 FILE: ${file.path}`,
        `文件描述：${file.description}`,
        fileRoleHint ? `文件角色提示：${fileRoleHint}` : '',
        `\n整体计划：${plan.summary}`,
        `其他文件：\n${otherFiles}`,
        prevSummary ? `\n已生成的文件（供参考接口/类名）：\n${prevSummary}` : '',
        '\n输出格式：只输出这一个文件。先写 FILE: 路径，然后紧跟完整代码块。代码必须完整，不要省略任何部分。',
        guides ? `\nPROJECT_RULES:\n${guides}` : '',
      ].filter(Boolean).join('\n');

      const messages: ChatMessage[] = [
        { role: 'system', content: sysContent },
      ];
      if (workspaceCtx) {
        messages.push({ role: 'user', content: `当前工作区代码：\n${workspaceCtx.slice(0, 5000)}\n\n---\n请生成 ${file.path}` });
      } else {
        messages.push({ role: 'user', content: `请生成 ${file.path}：${file.description}\n\n原始需求：${plan.userMsg || ''}` });
      }

      // Stream LLM response
      let fileText = '';
      try {
        for await (const chunk of this.llmClient.stream({ model, messages, maxTokens: 8192, token })) {
          fileText += chunk;
          stream.markdown(chunk);
        }
      } catch (err: any) {
        skipped.push({ path: file.path, reason: err.message || 'LLM error' });
        stream.markdown(`\n⚠️ \`${file.path}\` 生成失败: ${err.message}\n`);
        continue;
      }

      // Parse and write
      const parsed = parseFileBlocks(fileText);
      if (parsed.edits.length > 0) {
        const result = await this.fileWriter.apply(parsed.edits);
        applied.push(...result.applied.map(a => a.path));
        skipped.push(...result.skipped);

        // Store summary for next file's context
        for (const ed of parsed.edits) {
          const lines = ed.content.split('\n');
          generatedSummaries.push({ path: ed.path, excerpt: lines.slice(0, 50).join('\n') });
        }

        stream.markdown(`\n✅ \`${file.path}\` 已写入\n`);
        this.contextBuilder.markDirty();
      } else {
        skipped.push({ path: file.path, reason: '未解析到文件内容' });
        stream.markdown(`\n⚠️ \`${file.path}\` 解析失败，跳过\n`);
      }
    }

    // Final summary
    const appliedList = applied.map(p => `- ✅ ${p}`).join('\n');
    const skippedList = skipped.map(s => `- ❌ ${s.path}: ${s.reason}`).join('\n');
    stream.markdown(
      `\n---\n**全部完成 (${applied.length}/${plan.files.length})**` +
      (appliedList ? `\n\n已写入：\n${appliedList}` : '') +
      (skippedList ? `\n\n未成功：\n${skippedList}` : '') +
      '\n'
    );
  }

  /**
   * Generate scaffold-aware hints based on file path patterns.
   * Not hardcoded to any specific scaffold — matches generic path patterns.
   */
  private _getFileRoleHint(filePath: string): string {
    if (filePath.endsWith('.widget.config.js')) {
      return '这是组件配置文件。严格遵循 PROJECT_RULES 中的 widget config 结构：version, code, desc, instance, component(所有渲染模式), widget(display/allow/default/validator/special/editor), componentModelField, client.mobile。';
    }
    const renderModeMatch = filePath.match(/form-widget\/(ide|edit|read|list|print|search|search-ide)\//);
    if (renderModeMatch) {
      const mode = renderModeMatch[1];
      const mixinMap: Record<string, string> = {
        'ide': 'FormWidgetMixin (@/mixin/form-widget.mixin)',
        'edit': 'FormWidgetMixin (@/mixin/form-widget.mixin)',
        'read': 'FormWidgetMixin (@/mixin/form-widget.mixin)',
        'list': '无mixin，使用 inject:[\'listEngine\'] + props:[\'componentConfig\',\'formValue\',\'propKey\']',
        'print': 'PrintWidgetMixin (@/mixin/print-widget.mixin)',
        'search': 'SearchWidgetMixin (@/mixin/search-widget.mixin)',
        'search-ide': 'SearchIdeWidgetMixin (@/mixin/search-ide-widget.mixin)',
      };
      return `这是 ${mode} 渲染模式组件。使用: ${mixinMap[mode] || '参考 PROJECT_RULES'}。参考 PROJECT_RULES 中的同模式组件示例。`;
    }
    if (filePath.endsWith('.editor.config.js')) {
      return '这是编辑器配置文件。必须包含 code, editorConfigType, componentName, configProperty 四个字段。';
    }
    if (/form-editor\/.*\.vue$/.test(filePath)) {
      return '这是表单设计器右侧属性面板组件。使用 EditorFormConfigMixin (@/mixin/form-config.mixin)。';
    }
    if (filePath === 'src/apaas.json') {
      return '平台元数据文件。保留已有内容，只添加/修改当前组件的条目。注意 type 字段要与 widget config 的 code 一致。';
    }
    if (/\/index\.js$/.test(filePath)) {
      return '聚合导出文件。导入并导出新组件，保留已有的导入不要删除。';
    }
    return '';
  }
}
