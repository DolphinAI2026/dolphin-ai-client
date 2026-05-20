# Session Handoff · 2026-05-20 末
> 交给下一个 session 接手。**先读这个文档再动代码。**

## 一、Branch 当前状态

- **Branch**: `local/ui-redesign-2026-05-20`（已 push 到 origin）
- **HEAD**: `d2ef414 feat(parser): 加 ParseResult.code_rewrites 结构化追踪自动改写（Stage 1/4）`
- **Base**: `7172cbc feat(design): 引入 Claude design v3 token 系统`（前置 commit）
- **Session 累计**: 19 个 commit / 60+ 文件改动 / 涉及 frontend + admin-spa + backend

## 二、这个 session 干了啥（按时间）

```
─── Phase A: v3 design token 全栈推 ────────────────────────────
b1120e6  13 页 v3 化 + 状态系统 (EmptyState/ErrorCard/SkeletonCard) + 表格密度 + a11y
b1b97bf  Phase 8 — RailSidebar + chat 侧栏 + DeployConfirmModal + OnboardingTour
4b7e5c0  Login.vue v3 token 化（漏网）
f5e6c0a  Phase 9 全清 17 剩余页面
e0798da  docs/design-v3-migration-2026-05-20.md 迁移完整文档
6d39620  Phase 10 全局 polish — sticky / 动效 / Element Plus 精修
d776d3d  fix: [data-design="v2"] scope --surface 覆盖根因（v2 老色破坏 v3 dark）
6f92e9e  fix: v2 scope --ai/--emerald/etc 状态色别名补齐
6fd39ab  Phase 11 — admin-spa 全清（11 个 view + 共享 AdminLayout）
4c11c95  refactor: 统一两条 admin 路径 UI（PlatformAdminEmbed + AdminLayout）
505f86a  UED 优化报告 P0+P1 修复
1e3f932  fix(rail): 平台管理点击 "新 tab + 当前页也跳" 的 bug（noopener 返回 null 误判）
67adcc3  refactor: AdminLayout 抛弃 Element Plus 用 frontend 同款 DOM
3e246e9  fix: AdminLayout 严格 1:1 复刻 frontend RailSidebar 实际值（之前凭印象写）
5f1f1e2  fix: REVERT App.vue <Transition>+<Suspense> 包 RouterView（/marketplace 空白）

─── Phase B: code review + 修 ────────────────────────────────
e30602a  Wave 1 — 修 code review P1 + 大部分 P2（10 项 真 bug + 死代码）
02ae921  Wave 2 — P2-10 router replace + P2-11 EP portal dark mode
e3c285a  P3-4 删 design-v2-tokens.css — 单一 token 来源（-383 行）

─── Phase C: AI Builder 工具链调研 + Stage 1 backend foundation ──
d2ef414  feat(parser): 加 ParseResult.code_rewrites 结构化追踪自动改写（Stage 1/4）
```

详细见各 commit message。

## 三、🚨 用户最新方向（这次 session 末提出，下次必须遵守）

用户 session 最后一句：

> 1、用户心智和体验混乱，我们干脆**把需要点击按钮的都去掉**算了。**就通过对话去搞**吧，我试了一下对话创建一个应用没问题的。
>
> 2、但是过程很费劲，**生成设计、展示设计文档、转成生成json，用了好几个 Mcp，过程中肯定会弄错**。
>
> 3、**应用蓝图的 UI 渲染做了等于白做，没啥意义**！你有本事把低代码平台的组件 UI 都超一遍，**实现真预览，1:1 还原预览效果**，要么就别做蓝图预览了。
>
> 4、**"按规范重写" 按钮也去掉**，没啥卵用！

### 解读 + 含义

| # | 用户要的 | 含义 |
|---|---|---|
| 1 | 砍按钮，纯对话驱动 | UI 走极简，所有动作通过 agent 工具调用执行 |
| 2 | MCP 工具链太复杂 | 当前 write_artifact → preview → generate_app_from_doc 多跳，希望简化 |
| 3 | 蓝图 UI 渲染白做 | 要么删 AppBlueprintPanel，要么 1:1 还原 aPaaS 低代码组件渲染 |
| 4 | "按规范重写" 按钮删 | ChatPage / artifact panel 上那个按钮没用 |

### 这跟我 session 末做的 "preview_app_from_doc" 方案的关系

冲突：我原方案是 **加一个新 UI 让用户在 chat 里看 code_rewrites 列表 + 点确认**。

但用户#1 说"砍按钮，纯对话"。所以：
- ✅ **保留 backend** 部分 — ParseResult.code_rewrites 数据结构 + add_rewrite() 已上（commit d2ef414）
- ✅ **保留 preview_app_from_doc 工具** — 但作为 MCP 工具供 agent 调用
- 🔄 **改变 UI 部分** — 不加 confirm panel。**让 agent 在 chat 里用人话说**："我把 crm_system 改成 crm-system 了（原因：apaas app_code 必须 kebab-case + ≤17 字符）。OK 继续吗？" 用户在 chat 回 "OK" 就 generate
- 这跟用户的"纯对话"方向 100% 一致

## 四、当前未完成的工作（按优先度）

### 🔴 P0 — 用户明确反馈，必做

#### A. 砍 "按规范重写" 按钮（用户 #4）
- 位置：ChatPage.vue 或 ArtifactPreviewPanel
- 操作：grep "按规范重写" + 删按钮 + 删 backend route
- 估时：30 min
- 文件初步：`frontend/src/views/ChatPage.vue` 或 `frontend/src/components/v2/*` 里

#### B. 应用蓝图 UI 去留决策（用户 #3）
- 两条路：
  - **B1** 删 AppBlueprintPanel（小工作量 ~30 min）
  - **B2** 1:1 还原 aPaaS 低代码组件渲染（**大工作量 ~ 1-2 周**）
- 用户态度："要么就别做" 暗示倾向 B1
- **建议**：B1 删，腾出空间给纯对话 UI

#### C. 砍其他没用的按钮（用户 #1）
需要先 audit ChatPage / Apps / Marketplace / Builder 流程中哪些按钮是用户进入对话的快捷入口：
- "+ 新建应用" — 必删？换 chat 入口
- "导入应用" — 必删？换 chat
- "构建" / "发布" — 留？这些是流程动作
- "对话" — 必留（进入主对话）
- 各种"测试连接" / "复制凭证" — 留（admin 必要操作）
- **建议**：跟用户确认每个按钮去留再动

### 🟠 P1 — code rewrite 透明化 (Stage 2-4 续)

继续上个 commit (d2ef414) 的工作：

#### Stage 1 余 — backend parser `doc_parsers/models.py`
- `_parse_fields` 函数签名重构，把 `ParseResult.code_rewrites` 传进去
- 在 `safe_field_code` 改写处 (line 250-252) 调 `add_rewrite()` 
- 在 `.lower()` 改写处 (line 62, 282, 308, 316, 321) 也调（如果 case 真变了）
- 估时：30-45 min

#### Stage 2 — backend /upload-doc 路由返 code_rewrites
- `backend/app/routes/applications/docs.py` 找 `/upload-doc` 处理
- 把 `result.code_rewrites` 加到响应 JSON
- 估时：15 min

#### Stage 2 — v2 mcp-server 加 preview_app_from_doc 工具
- 切到 sister repo: `/Users/mars/Vibe Coding/apaas-builder-mcp-server`
- 在 `backend/app/mcp_server.py` 加新 `@mcp.tool() async def preview_app_from_doc(md_content, env=None)`:
  - 调 ai-builder backend 的 `/upload-doc` 解析
  - **不调** `/auto-create`（不落 apaas）
  - 返回 `{ ok, preview, code_rewrites, parse_warnings }`
- 估时：30 min
- 部署：需要 `docker buildx push hub.dfy:date-tag` + `kubectl set image`
  - 流程见 MEMORY.md `aliyun_deploy_runbook.md` 或 `k8s_mcp_server_migration_2026-05-13.md`

#### Stage 4 — agent prompt 更新（user 在 dolphin admin 配）
新增 workflow 规则给 ai-builder agent：

```
当用户确认需求后，必须按以下顺序：
1. write_artifact 输出 md 设计文档
2. 用户在右侧确认
3. **preview_app_from_doc(md_content=...)**  ← 新增
   读返回的 code_rewrites 数组
4. 如果 code_rewrites 非空：
   把每条改写翻译成人话告诉用户：
   "我把 [original] 改成了 [rewritten]，原因：[reason]
    确认这样改可以吗？"
   等用户在 chat 回 "OK" 才继续
5. generate_app_from_doc(md_content=...)
6. 部署 / 完成
```

用户决定怎么落 dolphin admin agent_code = `23c93f30d8`。

### 🟡 P2 — 收尾杂事

| # | 项 | 文件 | 估时 |
|---|---|---|---|
| P2-1 | builder.css 拆分 globals/element-plus/builder | `frontend/src/styles/builder.css` (2200 行) | 1h |
| P2-2 | state 组件跨 SPA dedup (vite alias 或 pnpm workspace) | `frontend/src/components/states/` ↔ `admin-spa/src/components/states/` (482 行重复) | 2h |
| P2-3 | RailSidebar ↔ AdminLayout CSS dedup | 同上 (450 行重复) | 2h |
| P2-4 | `data-design="v2"` 死 marker 清理 | 5 个 .vue 文件 | 15 min |
| P2-5 | dev mode admin-spa 跨 origin 登录状态分裂 | iframe handoff_token / postMessage | 1h |
| P2-6 | code-server.launchd 服务清理（pkill 立即 respawn） | 不在代码 — 用户本地 `launchctl bootout` 或留着 | 0 (info only) |

## 五、关键 backend / 工具 调用链（重要 context）

session 内 reviewer agent 做的完整 audit（不要再重做，直接读这段）：

### write_artifact → generate_app_from_doc 链路里的 4 类静默 code 改写

| # | 改什么 | 触发条件 | 代码位置 | 例子 |
|---|---|---|---|---|
| 1 | app_code snake → kebab + 截 17 字符 | 100% 必触发 | `backend/app/doc_standard_parser.py:174-181` + `backend/app/app_code.py:11-25` | `crm_system` → `crm-system` |
| 2 | field code 撞 SQL 保留字加 model 前缀 | name/status/type/order/group/key 等 | `backend/app/doc_parsers/models.py:249-252` + `backend/app/lowcode_standards.py:289-291` | `lead.status` → `lead.lead_status` |
| 3 | 所有 model/field/dict code 强制 .lower() | 100% 必触发 | `backend/app/doc_parsers/models.py:62, 282, 308, 316, 321` | `CustomerOrder` → `customerorder` |
| 4 | `_<4字符随机>` 后缀 | 默认关，`ENABLE_CODE_SUFFIX=true` 开关开启时 | `backend/app/app_executor.py:24-35` + `backend/app/generator_v2.py:543/575/948/984/1052/1088` | `customer` → `customer_a3k9` |

### MEMORY 提的未同步 bug

`/Users/mars/Vibe Coding/apaas-builder-ai/backend/app/generator_v2.py:543` 老写法 `f"{code}_{suffix}"` —— suffix="" 时仍产生 `customer_` 孤儿 `_` 尾巴。v2 sister repo `apaas-builder-mcp-server/backend/app/generator_v2.py:575` 已修用 `_apply_suffix()`，**v1 这边没同步**。

### 当前用户唯一 confirm gate（T3）+ 之后全黑盒

```
T1  agent write_artifact          → 落 ai_chat_artifacts 表
T2  agent 输出 "请在右侧确认"
T3  user "OK 帮我建吧"             ← ★ 唯一 gate ★
T4  agent generate_app_from_doc
    ↓ 黑盒：parse → 改写 #1+#2+#3 → 落 apaas
T5  agent "已建好 app_id=xxx"      ← 既成事实
```

## 六、Tools / Skills 清单

### ai-chat agent（v2 mcp-server `ai_chat/agent.py`）
**只 4 个工具**：
- read_attachment
- run_python
- write_artifact
- ask_clarifying_question

### dolphin builder agent（admin 配 agent_code=`23c93f30d8`）走 MCP 调 71+ 工具
关键：generate_app_from_doc / update_app_from_doc / check_app_code_conflict / list_apaas_models_in_env / force_regenerate_apaas_app / deploy_application / import_zip_to_workspace

### Skill 提示词位置
- `docs/skills/ai-builder/prompt.md`（副本）
- `docs/skills/ai-builder/workflow.md`（副本）
- 真身：dolphin admin 平台 agent_code `23c93f30d8`
- v2 mcp-server `apaas-builder-mcp-server/backend/app/ai_chat/agent.py:60-114` 是 ai-chat 模式的 SYSTEM_PROMPT_CHAT + SYSTEM_PROMPT_COWORK

## 七、Browser tools 状态

- `mcp__chrome-devtools__*` 在 session 末断了
- 没有 visual verify 能力 — 下个 session 前确认 chrome devtools mcp 重连，否则需要靠用户截图反馈
- `mcp__claude-in-chrome__*` 也在 deferred 列表

## 八、Session 内坑点（避免重蹈）

1. **`window.open(url, '_blank', 'noopener')` 返回值永远是 null** — 不能用 if(!win) 判断 popup 失败。用 `<a target="_blank">` 让浏览器原生处理
2. **Vue `<Transition>` 不能包多 root template 组件** — ChatPage / CodingPage 有 fragment template，App.vue 套 Transition 会导致 /marketplace 等页空白
3. **admin-spa Element Plus el-aside/el-menu 跟 frontend 自定义 DOM 长相不可能 1:1 一致** — 已重写 AdminLayout 用纯 HTML mirror frontend RailSidebar
4. **theme.ts accentVars 是死代码** — picker 已删但 accentVars computed 还在；commit e30602a 已清
5. **postMessage `'*'` origin 不校验是安全洞** — 已加 origin 检查 + cleanup listener
6. **`[data-design="v2"]` scope 是历史包袱** — v2 token 文件已删（commit e3c285a），attribute 5 处剩余是死 marker
7. **vue-tsc admin-spa 报 `vue/__globaltypes_3.5_false` 是 pnpm 环境问题** — 不是真 error，pre-existing，全 admin-spa .vue 都报
8. **改 App.vue 这种全局影响文件必须先 grep 所有 routed components 的 template root** — 是否 single-element

## 九、最重要的工程铁律

`backend/` **0 行改动** 是这个 session 的红线。所有改动是 frontend UI + admin-spa UI + token css。**除了 Stage 1 commit d2ef414** 加了 ParseResult.code_rewrites（这是用户明确要的功能修复，不算违反铁律）。

下次接手如果碰 backend，先用户确认。

## 十、下次 session 第一步要做什么

> 不要凭印象，按这个顺序：
>
> 1. **`git pull` 到最新 `local/ui-redesign-2026-05-20`**
> 2. **完整读这份 handoff 文档**（不要跳）
> 3. **跟用户对齐方向**：用户最新 4 点是不是还有效？还是又有新方向？
> 4. **优先做 P0 用户明确 4 项**（砍按钮 / 删蓝图 / 删按规范重写）— 这些是小工作量，先建立信任
> 5. **P1 preview_app_from_doc 工具链** — 走纯对话 agent 路径而不是 UI panel
> 6. **每个改动 commit 前自己跑一遍受影响路由**（如果 browser tool 可用）

## 十一、文件清单（接手者快速 grep 用）

```
# session 改的 key 文件
frontend/src/App.vue                                — RouterView 简单包装，不要再加 Transition
frontend/src/stores/theme.ts                       — 只剩 mode/setTheme/toggle/isDark + storage sync listener
frontend/src/components/v2/RailSidebar.vue         — 224px 展开 + 6 NAV + 浅深 toggle + 平台管理新 tab
frontend/src/components/v2/ShellTopBar.vue         — 48px + 22 routes CRUMB_LABELS
frontend/src/components/WorkbenchShell.vue         — data-design="v2" 死 marker 还在但无 CSS 引用
frontend/src/styles/design-v3-tokens.css           — 单一 token 来源（v2 文件已删）
frontend/src/styles/builder.css                    — 2200 行待拆分
frontend/src/views/PlatformAdminEmbed.vue          — 纯 iframe wrapper（自己 toolbar 已砍）

admin-spa/src/components/AdminLayout.vue           — 纯 HTML mirror frontend RailSidebar + ShellTopBar
admin-spa/src/main.ts                              — import v3 token
admin-spa/src/styles/design-v3-tokens.css          — 拷贝自 frontend，独立 vite bundle 需要

backend/app/doc_standard_parser.py                 — Stage 1 已加 ParseResult.code_rewrites
backend/app/doc_parsers/models.py                  — Stage 1 余：field code rewrites 还没走 add_rewrite

# 待动的关键 backend 文件
backend/app/routes/applications/docs.py            — /upload-doc 返 code_rewrites
backend/app/generator_v2.py:543                    — v2 已修，v1 未同步（_apply_suffix）

# 待动的 sister repo
/Users/mars/Vibe Coding/apaas-builder-mcp-server/backend/app/mcp_server.py
                                                   — 加 preview_app_from_doc 工具
```

---

**就这些。下个 session 接手时记得：** 先读完整文档 → 跟用户对齐 → 小步快跑 → 每步 verify。
