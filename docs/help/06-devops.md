# DevOps (`/devops`)

应用变更的"提案 → 审批 → Apply → Git → 平台部署"全链路控制台。

## 核心概念：ChangeProposal

每次想改已上线应用的 SPEC，就走一个**提案**：

```
draft SPEC ──[promote]──> open ──[approve]──> approved ──[apply]──> applied
                              ↘                                  ↘
                            changes_requested                  apply_failed
```

字段：
- **draft_spec_id**：要发布的 draft（`builder_specs.kind='draft'`）
- **base_canonical_spec_id**：对比基线（上次 apply 的 canonical）
- **validation_report**：第一道门校验（completeness / consistency / naming / markdown）
- **apply_plan**：第二道门生成的 ops 列表（含可逆性标记 green/yellow/red）
- **apply_log**：apply 执行记录
- **git_branch / git_pr_url**：promote 时自动 push `spec/proposal-{id}` 分支 + open PR

## 8 个二级导航

| Tab | 内容 |
|---|---|
| **总览** | 4 状态卡 + 交付轨道 4 步可视化 + 最近活动 |
| **提案** | 当前应用所有提案表格，支持按状态过滤 |
| **Apply 历史** | 已 applied 提案的时间线 |
| **Git 仓库** | git provider / 分支 / 漂移检测 / 一键初始化仓库 |
| **流水线** | 5 阶段看板（SPEC 回灌 → 评审 → Apply → Git 沉淀 → 发布环境），实时由 proposal 状态推导 |
| **运行历史** | proposal / apply 记录表（后续接 CI/CD 真实历史） |
| **环境拓扑** | 平台环境列表（默认环境 + 状态点 + base_url） |
| **审批中心** | **跨应用聚合**：当前 tenant 下所有需要"推一把"的提案（actionable=open/changes_requested/approved/apply_failed） |

## 典型流程：从 0 创建一个提案

1. 在 AI 搭建编辑应用 SPEC（自动生成 `kind='draft'` 的 BuilderSpec）
2. 进 `/devops`
3. 顶部应用选择器选这个应用（默认选第一个）
4. 点「+ 创建提案」按钮 → 弹 dialog 填 title + description（可选）
5. 提交 → 后端：
   - 自动找 application 最新 draft spec（无 draft 抛 422）
   - 跑第一道门校验
   - 校验通过 → status=`open`，否则 `draft`（带 issues）
   - 如果应用已绑定 git_repo_url，自动 push `spec/proposal-{id}` 分支 + open PR/MR
6. 自动跳 `/proposals/{id}` 详情页

## 提案详情 (`/proposals/:id`)

- 左：description + 变更 ops 摘要（reversibility 徽章 green/yellow/red）
- 右：第一道门校验报告 + 评审区 + 操作区
- **评审**：maintainer+ 角色可 approve / request_changes，creator 不能自审
- **重新校验**：手动重跑第一道门
- **Apply 到 canonical**：approved 状态出现按钮 → 触发 apply 流程（含 `confirm_irreversible` 二次确认）

## Git 集成

- 项目级 git connection（PAT / Token）一次配置
- 应用级初始化仓库：DevOps Git tab 一键 init repo
- 漂移检测：检查 builder SPEC 是否与 git HEAD 一致
- promote 自动 push 分支
- apply 成功自动 merge PR + tag canonical commit

## 审批中心使用

切到「审批中心」tab：
- 跨当前 tenant 所有应用列出 actionable 提案
- 每条显示：状态徽章 + 标题 + 来源应用名 + 创建时间
- 点击进详情 → 评审

## 当前应用卡快捷链接

总览顶部「当前应用」卡片有 3 个快捷链接：
- **编辑 SPEC →**：去 AI 搭建编辑（智能跳转：已部署进 SPEC update 工作台，未部署进搭建会话）
- **应用列表 →**：返回 `/apps`
- **平台 ↗**：跳到 aPaaS 平台运行界面（如已部署）

## 二级导航支持收起

顶部「«」按钮收起左侧导航成 60px 窄条，icon + count 浮在右上角。状态 localStorage 持久化（key: `devops:side-collapsed`）。
