# Addy Osmani agent-skills — Vibe Coding 用 3 个核心 skill

> 来源：[github.com/addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) — **39.1k stars**，MIT，v0.6.0 (2026-04-28)
>
> 作者 [Addy Osmani](https://addyosmani.com) — Google Chrome 团队 lead，Web Performance / Frontend 大佬。
>
> 原 repo 全 22 skill 覆盖 Define → Plan → Build → Verify → Review → Ship 完整 SDLC，我们 cherry-pick 跟 **「先做设计后开发」** 直接相关的 3 个，给 Vibe Coding agent 用。

## 我们选了哪 3 个

| Skill | 干嘛 | 何时触发 |
|-------|------|---------|
| `idea-refine.md` | 把用户模糊想法 → 锐化为可建的概念（divergent → convergent → 1-pager） | 用户给的需求模糊：「做个 todo app」「整个 dashboard 试试看」「我想要一个聊天工具」 |
| `spec-driven-development.md` ⭐ | 写 6 章节 spec 文档（Objective / Tech Stack / Commands / Structure / Style / Testing / Boundaries / Success / Open Questions），人审通过才进 code 阶段 | 任何 > 30 分钟 / 多文件改动 / 架构决策 |
| `planning-and-task-breakdown.md` | spec → 拆分原子任务（每个 <5 文件，带 acceptance / verify / files） | 拿到 spec 但任务复杂，需要切分 |

**推荐串联顺序**：用户模糊 → `idea-refine` 锐化 → `spec-driven-development` 写 spec + 人审 → `planning-and-task-breakdown` 拆任务 → 调 `vibe_*` 工具实现。

## 改造点（适配 dolphin）

| 原 skill | 改动 | 原因 |
|---------|------|------|
| `spec-driven-development.md` | **0 改动**，原文照搬 | 完全自包含，无外部 script / resource 引用 |
| `idea-refine.md` | 删 1 行 `bash /mnt/skills/user/idea-refine/scripts/idea-refine.sh` | dolphin skill 不能执行外部 shell；该行只是「可选辅助脚本」，删掉不影响 prompt 主体 |
| `planning-and-task-breakdown.md` | 0 改动 | 无外部引用 |

## 上传 dolphin 步骤

dolphin admin → **Skills 管理 → 新建 SKILL_STORE skill**：

### Skill 1: 上传 `spec-driven-development.md`（必上 ⭐）

- 编码：`spec-driven-development`
- 名称：`规范驱动开发（Addy Osmani v0.6.0）`
- 描述：`Creates specs before coding. 任何 > 30min / 多文件 / 架构决策的任务先写 6 章节 spec，人审通过才进 code`
- 内容：复制 `spec-driven-development.md` 全文粘贴
- 关联到：**AI-aPaaS-Vibe** 智能体（agent_code=`51ebb5937b`）

### Skill 2 (可选): 上传 `idea-refine.md`

需求模糊时让 agent 先锐化。如果你的用户都是「会写清楚需求」的类型可跳过；如果用户经常说「做个东西试试」就上。

### Skill 3 (可选): 上传 `planning-and-task-breakdown.md`

复杂多步项目时让 agent 自己拆任务。Vibe Coding 多数是 prototype（任务相对小），可先观察 spec-driven 单 skill 跑通后再决定要不要叠加。

## Vibe agent prompt 怎么配合 skill

当前 `agent-vibe-coding-v1.prompt.md`（5/11 commit `da139c6`）已经写了 Vibe 工具调用 SOP，**没有 spec 阶段**。

上传 skill 后，**Vibe agent prompt 加一句**让 agent 知道何时调 skill：

```markdown
## 何时调用 skill

- 用户给的需求**模糊**（「做个 todo」「试试看」无明确 spec）→ 先调 `idea-refine` skill 锐化
- 用户给的需求**清晰但工程量大**（> 30 分钟 / 多文件 / 涉及架构）→ 调 `spec-driven-development` skill 写 spec 让用户审
  - 用户审通过后才进 `vibe_create_sandbox` 起沙箱阶段
- 需求**很小很清晰**（"做个静态 Hello World 页面"）→ 跳过 spec 直接起沙箱

⚠️ 不要把 spec 跳过当作"提高效率"。一份 15 分钟的 spec 能避免 2 小时的返工。
```

加这段到 `agent-vibe-coding-v1.prompt.md` 末尾，重新发布 agent 即可。

## License & Attribution

[addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) MIT License © Addy Osmani。

我们没有 fork repo，只 cherry-pick 3 个 SKILL.md 直接放进本仓库（属于 MIT 允许的 "redistribute" 行为）。原文 `idea-refine.md` 有 1 行无关 shell 脚本调用被删（不影响 prompt 内容主体）。

如要拉全 22 skill 看其它（test-driven-development / code-review / security-and-hardening / api-and-interface-design 等很多 good stuff），原 repo:

```bash
git clone https://github.com/addyosmani/agent-skills /tmp/agent-skills
ls /tmp/agent-skills/skills/
```

## 后续想叠加的其它 skill 候选

按对 Vibe Coding 的相关性排：

| Skill | 价值 | 建议 |
|-------|------|------|
| `frontend-ui-engineering` | 前端 UI 工程最佳实践 | Vibe 多数是前端 prototype，相关性高 |
| `test-driven-development` | TDD | 如果用户希望 sandbox 跑测试 |
| `api-and-interface-design` | API / 接口设计 | 全栈 prototype（带 backend）需要 |
| `incremental-implementation` | 增量实现 | Build 阶段细节，agent 自然能做 |
| `security-and-hardening` | 安全 | prototype 阶段可跳 |

Phase 6.x 实测后视用户需求增量上。
