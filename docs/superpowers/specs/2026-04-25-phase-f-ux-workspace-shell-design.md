# Phase F — UX 整体优化（WorkspaceShell + 简单/专业双轨）设计 Spec

**Date**: 2026-04-25
**Status**: Approved (brainstorm 阶段已锁)
**Branch base**: `claude/coding-shell-alignment` (HEAD `049898f`，主干 = ABCDE 5 phase 完整产物)
**Predecessors**:
- `docs/superpowers/specs/2026-04-25-collab-spec-git-integration-design.md`（ABCDE 协作 + git 设计）
- 5 个 HANDOFF 文档（A/B/C/D/E + ABCD 总览）

---

## 0. 一句话目标

把当前"4 个独立 page 跳来跳去 + 5-stage 瀑布心智 + 应用上下文不联动"的 UX 问题一次性解决：新建 `/work/:appId` 一站式工作台 WorkspaceShell（左 Chat / 中 Preview / 右 Activity），同时引入"简单 / 专业"双模式开关，**简单模式不绕开 ABCDE 安全门**。

---

## 1. 根因诊断 — 为什么需要 Phase F

现状（巡礼 5 个 page 后总结）：
- **Apps** 列表卡片信息密度低（看不到协作者 / git 状态 / 待评审提案数）
- **ChatPage** 还是 5-stage PhaseBar 瀑布心智（理解需求→SPEC设计→配置生成→自开发→部署），跟 ABCDE 落地的"提案制 + draft/canonical"完全不对齐
- **CodingPage** 是独立 page，workspace 入口和 chat 上下文分离
- **DevOps** 顶部的应用切换下拉跟 Apps/Chat/Coding 的"当前 app"不联动
- **ProjectOverview** 4 个 entry card 是被动跳转，不是工作台
- 每个 page 的 alert/confirm 都是原生浏览器对话框，dark 模式不兼容、风格不统一

主流 Vibe Coding 工具（Bolt / Lovable / v0 / Cursor / Copilot Workspace）的共识：
- 单 chat 入口驱动多 panel
- live preview 实时同步
- 提案 / 审批 / git 这些"工程心智"按需展开，不强加给业务用户

ABCDE 已经把"提案制 + git 双向同步 + 真接平台部署"的工程 backbone 做完了——Phase F 的任务就是给这套强 backbone **配一层符合主流心智的 UX 表层**。

---

## 2. 六个核心架构决策（已锁）

### F1. 用户定位 = C 双轨（简单模式 + 专业模式并存）
不强迫所有人走重工程流；同时不丢弃 ABCDE 的协作能力。

### F2. 边界 = D 角色 + 动作 双层（不绕开安全门）
- contributor 默认进简单模式 / maintainer+ 默认进专业模式
- 简单模式 ≠ 自动 apply。**不可逆 modal 永远弹**，approve gate 永远在
- 简单模式只是把"AI 替你点了多余的按钮 + 隐藏了不必要的页面跳转"

### F3. 实施范围 = 跳过 F.1，直接做 F.2 大手笔
原本规划的"F.1 渐进改造（5 天）+ F.2 WorkspaceShell（10 天）"两期，**用户决定砍 F.1 直接做 F.2**。F.1 必要的前置依赖（应用上下文 store + 统一弹窗）合并到 F.2 第一周。

### F4. 简单模式审批 = D 不绕 approve，但用 in-chat 快捷批准
chat 流里 AI 准备好 proposal → 推到 chat 卡片 → 用户在 chat 内点 Approve → 自动 apply。**不出 chat 流**，但审批 gate 保留。AI 不冒充 user 身份审批。

### F5. mode toggle 持久化 = A 全局 user setting + per-app 覆盖
- 新用户默认 "简单"
- user settings 里能改全局默认
- 每个 application owner 能设这个应用的默认模式（覆盖 user 默认）
- 实际生效 = `app_default ?? user_default ?? "simple"`

### F6. PreviewPanel Deploy tab = X 真 iframe 嵌入实际部署的 aPaaS 应用
URL = `application.platform_url + "/app/" + application.apaas_app_id`（具体 URL 模式按 aPaaS 平台实际接口调整）。  
**风险**：跨域 / X-Frame-Options / aPaaS session cookie 共享 — 在 §11 风险章节展开。

---

## 3. WorkspaceShell 整体形状

新建路由：`/work/:appId`

```
┌──────────────────────────────────────────────────────────────────┐
│ ← 资产管理系统  [简单 ●─○ 专业]  alice + bob + 3   ◐ Synced     │  顶栏
├──────────────┬────────────────────────────┬──────────────────────┤
│              │                            │                      │
│  ChatPanel   │   PreviewPanel             │  ActivityPanel       │
│  ────────    │   ─────────────            │  ──────────          │
│              │   [SPEC] [Deploy] [Code]   │                      │
│  消息流      │                            │  📋 当前草稿         │
│              │   tab: SPEC                │  ├ 修改 3 处         │
│  AI: 我建议... │                            │  └ [Promote ↗]       │
│              │   (5 类卡片视图)            │                      │
│  user: ...   │                            │  🔍 待评审 (1)        │
│              │   tab: Deploy              │  └ #cp_a3f2 ...      │
│              │   <iframe                  │     [Approve ✓]      │
│              │     src="platform_url/     │                      │
│              │           app/{apaas_id}"  │  ✅ 已部署            │
│              │   />                       │  └ canonical v8 · 2h │
│              │                            │                      │
│              │   tab: Code                │  📊 历史 ↗           │
│              │   workspace 文件树+Monaco   │  🔧 高级 ↗           │
│              │                            │                      │
│  [输入框 ▶ ] │                            │                      │
└──────────────┴────────────────────────────┴──────────────────────┘
```

**简单模式 vs 专业模式差异**（仅右侧 ActivityPanel 行为）：

| 项 | 简单模式 | 专业模式 |
|----|----------|----------|
| 当前草稿 | 显示，"Promote" 按钮在 chat 内随 AI 卡片出现 | 显示，"Promote" 按钮在 ActivityPanel |
| 待评审提案 | **不展示**（chat 里推送"等待 X 审批"） | 完整列表 + reviewer 名字 + 状态 badge |
| Approve 按钮 | 在 chat 内嵌入卡片（D 决策） | 在 ProposalDetail 老页面 + ActivityPanel 内嵌 |
| 已部署 | 显示版本号 + apply 时间 | 同左 + git tag + git PR 链接 |
| 历史 commits / git 状态 | 折叠在 "高级 ↗" 链接后 | 默认展开 |

**老路由保留**：
- `/chat/:id` `/coding` `/devops` `/proposals/:id` `/project/:id` 全保留作为"高级"入口
- `/apps` 卡片点击默认跳 `/work/:appId`（不点"在 Chat 里打开"则用老路径）
- NavRail 保留，可直接进老 page（向后兼容）

---

## 4. 数据模型变更

### 4.1 新增

**`UserPreference`** — 用户级偏好设置：

```python
class UserPreference(Base):
    __tablename__ = "user_preferences"
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), primary_key=True)
    default_mode: Mapped[str] = mapped_column(String(20), default="simple")  # 'simple' | 'pro'
    # 未来扩展点：theme / language / etc
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```

### 4.2 改动

**`Application`** — 加 `default_mode` 列（nullable，None = 跟随 user preference）：

```python
default_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 'simple' | 'pro' | None
```

迁移：`backend/scripts/migrate_phase_f.sql`：

```sql
CREATE TABLE IF NOT EXISTS user_preferences (
  user_id INT NOT NULL PRIMARY KEY,
  default_mode VARCHAR(20) NOT NULL DEFAULT 'simple',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_user_pref_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE applications ADD COLUMN default_mode VARCHAR(20) NULL AFTER status;

INSERT IGNORE INTO __builder_migrations (name, applied_at) VALUES ('migrate_phase_f', NOW());
```

---

## 5. API 表面（新增）

```
GET    /api/me/preferences                       拿当前用户偏好
PUT    /api/me/preferences                       改 default_mode
GET    /api/applications/{id}/default-mode       拿应用默认模式
PATCH  /api/applications/{id}/default-mode       改应用默认模式（owner only）
GET    /api/applications/{id}/work-state         一站式聚合：当前 draft + 待评审 + 已部署 + git 状态 (BFF 风)
```

**`/api/applications/{id}/work-state` 返回结构**（BFF 接口，让前端 WorkspaceShell 一次性拿全）：

```python
{
    "application": { id, app_name, app_code, status, ... },
    "current_draft": { id, version, completeness, ... } | null,
    "canonical": { id, version, applied_at, ... } | null,
    "open_proposals": [...],          # status in (open, changes_requested, approved)
    "applied_history": [...],          # 最近 5 个 applied proposals
    "git": { repo_url, default_branch, last_sync_sha, drift } | null,
    "members": [...],                  # 合并 inherited + direct + creator
    "effective_mode": "simple" | "pro",
    "user_role_on_app": "owner" | "maintainer" | "contributor" | "viewer",
}
```

---

## 6. 前端组件结构

```
frontend/src/views/
├── WorkspaceShell.vue           ← 新主页面 /work/:appId
└── (老页面保留)

frontend/src/components/workspace/
├── ChatPanel.vue                ← 抽出原 ChatPage 的 chat 部分（消息流 + composer）
├── PreviewPanel.vue             ← 容器，含 SPEC/Deploy/Code 三 tab
├── PreviewPanel/
│   ├── SpecView.vue             ← 复用现有 SpecCanvas / spec/*Card
│   ├── DeployIframe.vue         ← 新：iframe + 错误处理 + auth 兜底
│   └── CodeView.vue             ← 抽出现有 CodingPage 的 workspace 文件树 + Monaco
├── ActivityPanel.vue            ← 新：聚合 draft/proposals/deploy/git 状态卡片
├── ActivityPanel/
│   ├── DraftCard.vue
│   ├── ProposalCard.vue         ← 内嵌 Approve/Request changes 按钮（D 决策）
│   ├── DeployedCard.vue
│   └── GitStatusCard.vue
├── ModeToggle.vue               ← 顶栏的简单/专业切换
└── WorkspaceTopBar.vue          ← 顶栏：app 名 + ModeToggle + 成员头像组 + git 状态

frontend/src/stores/
├── workspace.ts                 ← 新：当前 appId + work-state + 模式 + Approve 流（in-chat）
└── userPreference.ts            ← 新：global default_mode

frontend/src/components/         ← 既有，加：
├── BaseDialog.vue               ← 新：替换 alert/confirm 的统一组件（dark 兼容）
└── BaseToast.vue                ← 同上（替 alert 用）
```

---

## 7. 模式切换机制

### 7.1 effective mode 计算

```typescript
function effectiveMode(
  userPref: 'simple' | 'pro',
  appDefault: 'simple' | 'pro' | null,
  currentRole: ProjectRole,
): 'simple' | 'pro' {
  // owner+ 不强制 simple；contributor 即使 user pref='pro' 也只能进 simple（防止误操作）
  if (!roleAtLeast(currentRole, 'maintainer')) return 'simple'
  // owner+ 看 app default 优先，再 user pref
  return appDefault ?? userPref
}
```

### 7.2 toggle 行为
- 顶栏 `[简单 ●─○ 专业]` switch
- contributor：toggle 是 **disabled**（hover 提示"需 maintainer+ 权限"）
- maintainer+：toggle 切换会触发 `PATCH /api/applications/{id}/default-mode`（写 app 级别）
- 同时 settings 页有"我的默认模式"开关（写 user pref）

### 7.3 模式切换不重载页面
WorkspaceShell 是同一组件，模式切换仅改 ActivityPanel 内部 v-if 显隐 + ChatPanel 的 in-chat 卡片样式。

---

## 8. In-chat Approve 卡片设计（F4 决策的具体落地）

简单模式下，AI 完成一轮编辑后会推送一张 chat 卡片：

```
┌───────────────────────────────────────────────────┐
│ 🤖 AI: 我已经把"客户分类"字段加到 Customer 对象上 │
│                                                   │
│ ┌─ 提案预览 ─────────────────────────────────┐  │
│ │ 标题：加客户分类字段                          │  │
│ │ 变更：1 处 (add_field, 可逆 🟢)               │  │
│ │ 影响：✅ 全部可逆，可放心 apply                │  │
│ │                                                │  │
│ │ [Promote & Approve & Apply ✓]  [先 Promote]   │  │
│ └────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────┘
```

**简单模式下的"Promote & Approve & Apply ✓"按钮逻辑**：
1. 调 `POST /api/applications/{id}/proposals` （promote）
2. 后端立刻校验通过 → 自动 review (action=approve, body="in-chat quick approve") with **当前用户身份**
3. 调 `POST /api/proposals/{id}/apply`
4. 如果 has_irreversible，弹**不可逆 modal**（必须保留）+ 用户二次确认 → 真 apply
5. ActivityPanel 同步显示进度

**专业模式下的同款卡片**：
- 不显示"Promote & Approve & Apply ✓" 按钮
- 仅显示"Promote ↗"，让用户去 ActivityPanel / ProposalDetail 走完整流程

---

## 9. PreviewPanel Deploy iframe 实现细节

### 9.1 URL 构造

```typescript
function buildDeployUrl(app: Application): string | null {
  if (!app.platform_url || !app.apaas_app_id) return null
  // aPaaS 平台的应用入口 URL 模式（按实际平台调整）
  return `${app.platform_url.replace(/\/+$/, '')}/app/${app.apaas_app_id}`
}
```

### 9.2 跨域 / X-Frame-Options 处理

aPaaS 平台可能配 `X-Frame-Options: SAMEORIGIN` 拒绝 iframe 嵌入。处理：

1. **首选**：协调 aPaaS 平台运维加 `Content-Security-Policy: frame-ancestors 'self' <builder-domain>`
2. **fallback**：iframe 加 `onload` 检测，1 秒内未加载成功 → 替换为"在新窗口打开"按钮 + 错误提示
3. **完全不行**：DeployPanel 退化到 X→Y（仅显示部署元信息 + 跳转链接）

### 9.3 Auth 兜底

iframe 内 aPaaS 平台需要自己的 session cookie。如果用户未在 aPaaS 平台登录：
- iframe 显示登录页 → 用户登录后保留 session
- DeployIframe 组件检测 iframe load event，提供"刷新""新窗口打开"选项

### 9.4 安全

- iframe 加 `sandbox="allow-same-origin allow-scripts allow-forms allow-popups"`（按需调整）
- 不传 token 在 URL（保护凭证）

---

## 10. 实施分期 + 工程量估计（10 天）

按"先骨架 → 后填充 → 再优化"切：

### Week 1（前 5 天）— 骨架

| Day | 范围 |
|-----|------|
| 1 | DB migration（user_preferences + applications.default_mode） + ORM + UserPreference / Application APIs |
| 2 | `/api/applications/{id}/work-state` BFF 端点 + 前端 workspace store + ModeToggle 组件 |
| 3 | WorkspaceShell.vue 路由 + 三栏 layout + 老路由保留逻辑（`/apps` 卡片跳转规则） |
| 4 | ChatPanel.vue 抽出 + ActivityPanel.vue 骨架 + 4 张子卡片 |
| 5 | PreviewPanel.vue 骨架 + SpecView 复用既有 SpecCanvas + tab 切换 |

### Week 2（后 5 天）— 填充

| Day | 范围 |
|-----|------|
| 6 | DeployIframe.vue + URL 构造 + load 错误处理 + sandbox |
| 7 | CodeView.vue 抽出（从老 CodingPage workspace 部分） |
| 8 | In-chat Approve 卡片（PromoteApprovaApplyCard.vue）+ 简单模式自动流（promote→review→apply 三步串联） |
| 9 | BaseDialog/BaseToast 统一弹窗 + 替换 ~10 处 alert/confirm（MembersPanel / DriftBanner / Sync 按钮 / OAuth callback / ProjectGitSetup / WorkspaceShell 等） |
| 10 | 回归 + dark 模式 smoke + handoff |

---

## 11. 风险 + 缓解

| 风险 | 缓解 |
|------|------|
| **iframe 跨域被 aPaaS 平台拒绝** | 先尝试协调平台 X-Frame-Options；不行就自动 fallback 到"在新窗口打开"模式（不影响其他功能） |
| **In-chat Approve 卡片让用户误以为"自动批准"** | 卡片明确写"我帮你跑完 promote→approve→apply 三步"+ 不可逆 modal 永远弹（强化人工确认感） |
| **work-state BFF 端点 N+1 查询** | 单查询用 join + 显式 limit；apply_history 限 5 条 |
| **老 ChatPage 不能立即下线** | Phase F 仅"导流"到 WorkspaceShell；老 page 至少保留 1 个版本周期，用户反馈稳定后再下线 |
| **简单模式漏掉 git 状态导致 drift** | DriftBanner 在简单模式也显示（drift 是安全问题，不能为了体验隐藏） |
| **mode toggle 在 contributor 上 disabled 让人困惑** | hover 显示"需 maintainer+ 权限"；不允许时点击有 toast 提示 |
| **WorkspaceShell 大组件性能** | 三个 panel 各自独立 lazy load + computed 缓存；切换 tab 不重新拉数据 |

---

## 12. 不在范围内（Out of scope）

明确划出去（留 Phase G+ 或不做）：
- **完整 PR-style review UI**（diff 行内 comment 等）—— ProposalDetailPage 既有 v1 够用
- **多 chat tab 并行**（一个 app 同时开多个对话）—— 简化为单 chat session
- **AI 主动建议 / 自动 promote 提示**（"我看你 30 分钟没操作，要不要 promote？"）—— v2
- **MobileShell**（移动端适配）—— 桌面优先，移动端单独 spec
- **collaborative cursor**（多人同时编辑 SPEC 看到对方光标）—— 协作纵深，v2
- **iframe 内 deep linking**（直接打开应用的某个表单）—— v2

---

## 13. 验收标准

每个 Day 必须满足：
- DB migration 幂等（runner 重跑不报错）
- 后端 pytest 不回归（基线 199 + Phase F 新增 ~10 tests）
- 前端 vue-tsc 干净
- WorkspaceShell 在 light + dark 双模式渲染干净
- 简单模式 in-chat approve 走通：promote → 自动 review → 不可逆 modal → apply
- 专业模式：ActivityPanel 完整列出 proposals + 跳老 page 链接工作

最终 e2e（Day 10）：
- 用真 application 在 WorkspaceShell 内编辑 SPEC → 简单模式一键 apply → ActivityPanel 实时更新已部署版本
- 切到专业模式 → 看到完整提案 / git 链接 / reviewer 列表
- 切到 contributor 用户 → toggle disabled，仅简单模式可用
- iframe Deploy tab：尝试加载 platform_url → 成功嵌入 / 失败 fallback 都验证

---

## 14. 决策日志

| # | 决策 | 否决方案 | 锁定理由 |
|---|------|----------|----------|
| F1 | C 双轨（简单 + 专业） | A 纯业务 / B 纯开发 | ABCDE 工程能力做完了，配 UX 表层成本远低于推倒重来 |
| F2 | D 安全门绝不绕开 | A 全自动 apply | 低代码 apply 不可逆，AI 全自动 = 数据风险 |
| F3 | 跳过 F.1 直接做 F.2 | A 渐进改造 / C 分两期 | 用户决策：要大手笔 |
| F4 | D in-chat 快捷 approve | A AI 自动 approve | 不绕 approve gate + 不冒充用户身份 |
| F5 | A 全局 user setting + per-app 覆盖 | B 仅 per-app / C 仅 user | 双层心智符合 GitHub/Linear 习惯 |
| F6 | X 真 iframe live preview | Y 静态状态卡 / Z 起步 Y | 真 live preview 是 Bolt 心智核心，Y 体验差距大 |

---

## 15. 下一步

完成本 spec 评审后，进入 `writing-plans` 流程，按 §10 Day 1-10 顺序产出 implementation plan。
