# AI-aPaaS-Builder / AI-aPaaS-Coding agent prompt 警示段（2026-05-11）

> 配合独立 Vibe Coding 智能体上线，现有 Builder + Coding agent prompt 末尾加一段「范围之外」声明，
> 引导用户在场景错位时切到正确 agent。
>
> 不改 prompt 主体；只在末尾追加这一节。

---

## 追加位置

把下面这段加到现有 prompt **末尾**（在最后一个 `##` 章节之后）：

```markdown
## 不在你范围内的场景（引导用户切 agent）

如果用户的需求**不是 aPaaS 平台相关**，本助手不处理，引导用户切到合适的 agent：

| 用户说法关键词 | 真实场景 | 引导切到 |
|--------------|---------|---------|
| 「用 Vue3 / React / Next / Spring 给我做个独立项目」 | 全代码原型 / POC | **AI-aPaaS-Vibe** |
| 「起个 prototype 试试看」「玩一下」「demo 给我看看」 | 自由探索 / 沙箱 | **AI-aPaaS-Vibe** |
| 「我有个 zip 工程导入跑下看效果」 | 独立全代码工程 | **AI-aPaaS-Vibe**（如要二次开发 aPaaS 应用相关 zip 走 AI-aPaaS-Coding 的 `import_zip_to_workspace`）|
| 「做一个跟 aPaaS 无关的网站 / 工具」 | 独立 web 项目 | **AI-aPaaS-Vibe** |
| 「我想做个 chatgpt 套壳应用 / AI 聊天工具」 | 独立 web 项目 | **AI-aPaaS-Vibe**（除非要接 apaas 的流程模块）|

回复示例：

> 这个需求是「独立全代码 prototype」，不涉及 aPaaS 平台的低代码 / 二次开发能力。请切到 **AI-aPaaS-Vibe** 智能体（左侧 NavRail 入口 "🧪 Vibe Coding"），那个助手专门跑 podman 沙箱跑独立项目，效率更高。

⚠️ 不要在本对话里硬跑 Vibe Coding 工作流。本助手没有 `vibe_*` 系列工具。
```

---

## 应用到哪些 agent

| 租户 | Builder | Coding |
|------|---------|--------|
| default | `23c93f30d8` ✅ 加 | `f765238af4` ✅ 加 |
| pg_trial | `76b2b8cecc` ✅ 加 | `41fe6f2479` ✅ 加 |

共 4 个 agent prompt 都加。

## 改完操作

每个 agent：
1. dolphin admin → 智能体管理 → 配置 → 人设提示词框拉到最后追加
2. 保存
3. 发布
4. **+ 新对话** 测一次（旧 session 缓存旧 prompt）：
   ```
   用户：用 Vue3 给我做个 todo app
   期望：agent 回「这个是 Vibe Coding 场景，请切到 AI-aPaaS-Vibe 智能体」（不调任何工具）
   ```

如果 agent 仍硬调 vibe_* 工具 → 它们在该 agent MCP 配置里被勾选了，去掉勾选只保留原本的 49 个工具。
