# 「得小帆·共性能力」hub 设计 — 2026-06-26

## 背景与目标

得小帆的「共性能力」(技能 / 知识 / MCP / AI 网关)目前散在四个不一致的入口里。RailSidebar 早有
一个「得小帆·共性能力」入口(`components/v2/RailSidebar.vue` `hubNavItem`),但 Phase 1 偷懒**直链
到 `/skills`**,注释明写「完整 4-tab hub 后续」「技能 / MCP / AI 网关 / 知识库」。知识库又另挂了一个
独立的 `/knowledge` 侧栏入口。

**目标**:把这四个能力收进一个统一的 hub 页,顶部 4 个 tab,补齐当初规划但延后的「完整 hub」。

## 现状(实现时据此对齐)

| 能力 | 现住处 | 类型 | 访问 |
|---|---|---|---|
| 技能库 | `/skills` → `views/SkillLibraryPage.vue` | 主 app 原生页 | `requiresAuth`(所有人) |
| 知识库 | `/knowledge` → `views/KnowledgeBasePage.vue` | 主 app 原生页 | `requiresPlatformAdmin`;`desktop:'hidden'` |
| MCP(平台版) | admin-spa `/admin/mcp` → `admin-spa/src/views/McpServices.vue` | admin-spa(iframe 内嵌) | 平台管理员 |
| AI 网关(平台版) | admin-spa `/admin/llm-configs` → `admin-spa/src/views/LlmConfigs.vue` | admin-spa(iframe 内嵌) | 平台管理员 |

> MCP/AI 网关另有「原生但语义不对」的版本(原生 `/admin/mcp` McpToolsPage 所有人可见 /
> `/platform-envs?tab=llm` 租户级)。**本期 hub 用平台版 admin-spa 页**(已与用户确认),原生那两版本期不动(见「非目标」)。

admin-spa 内嵌机制(已存在,复用):`views/PlatformAdminEmbed.vue` + `views/platformAdminEmbedState.ts`
的 `buildPlatformAdminIframeSrc({origin, baseUrl, adminPath, token})` → 拼出
`{origin}{base}/admin{adminPath}?embed=1&handoff_token={token}`;admin-spa 全局守卫吃 `handoff_token`
落 `admin_token` 免登。admin sub-path 可单独深链内嵌。

## 设计

### 1. 形态与路由

- 新建 hub 页 `frontend/src/views/CapabilitiesHubPage.vue`,路由 `/hub`,顶部一排 tab(参照
  `PlatformEnvs.vue` 的 tab 写法),tab 状态走 `?tab=` 查询参数(`skills`/`knowledge`/`mcp`/`gateway`)。
- hub 路由 meta **只 `requiresAuth`**(否则普通用户连技能库都进不去),**权限在 tab 层做**。
- RailSidebar「得小帆·共性能力」`hubNavItem.path` 由 `/skills` 改 `/hub`;**删掉单独的 `/knowledge`
  侧栏入口**(footer 那条 `v-if="user.isPlatformAdmin"` 的「平台知识库」)。
- 向后兼容:`/skills`→`/hub?tab=skills`、`/knowledge`→`/hub?tab=knowledge` 用 router redirect
  (保留路由 name 不破坏现有 `router.push('/skills')` / 书签 / 深链)。

### 2. 四个 tab:内容 + 权限

| tab key | 标签 | 内容 | 可见条件 |
|---|---|---|---|
| `skills` | 技能库 | 原生组件 `<SkillLibraryPage>` **就地渲染**(import 复用) | 所有登录用户 |
| `knowledge` | 知识库 | 原生组件 `<KnowledgeBasePage>` 就地渲染 | `isPlatformAdmin` ∧ 非桌面隐藏 |
| `mcp` | MCP | `<AdminSpaEmbedFrame admin-path="/mcp" chromeless>` | `isPlatformAdmin` ∧ 非桌面隐藏 |
| `gateway` | AI 网关 | `<AdminSpaEmbedFrame admin-path="/llm-configs" chromeless>` | `isPlatformAdmin` ∧ 非桌面隐藏 |

- tab 列表 = 上述按「可见条件」过滤后的有序子集。普通用户进 hub 只看到「技能库」;管理员看 4 个。
- 默认 tab:无 `?tab=` 或 `?tab=` 指向不可见 tab 时,回落到**当前用户第一个可见 tab**(即技能库)。
  普通用户硬塞 `?tab=knowledge` → 回落技能库,不渲染受限内容。
- 技能库 / 知识库 tab 是**就地渲染原生组件**,不走 iframe(它们本就是主 app 页);切 tab 用 `v-if`/
  `v-show` 控制挂载(知识库较重,用 `v-if` 懒挂)。

### 3. AdminSpaEmbedFrame.vue + admin-spa「无壳」内嵌(关键改动)

- 新建 `frontend/src/components/common/AdminSpaEmbedFrame.vue`:props `adminPath: string`、`chromeless?: boolean`;
  内部用 `buildPlatformAdminIframeSrc`(复用)+ 一个 `<iframe>`。当 `chromeless` 时,给拼出的 URL
  追加 `&chromeless=1`。token 取 `localStorage.getItem('token')`(同 PlatformAdminEmbed)。
- **为何新加 `chromeless=1` 而不复用 `embed=1`**:现有 `/platform-admin/*` 整体内嵌也用 `embed=1`,
  且**依赖** admin-spa 自带侧栏导航(那是平台管理的完整外壳)。若让 `embed=1` 去壳会破坏它。故用
  **独立标志 `chromeless=1`**:hub 的 MCP/网关 tab 用之;`/platform-admin` 整体入口保持带壳不变。
- admin-spa 改布局组件(AdminLayout / 等价):读 `route.query.chromeless==='1'`,为真时**只渲染
  `<router-view>` 内容,不渲染自己的侧栏 + 头部**。McpServices / LlmConfigs 页本身不改。
  - chromeless 持久性:admin-spa handoff 守卫清 query 时只 `delete cleanedQuery.handoff_token`、其余 query
    原样保留(见 admin-spa router beforeEach),故 `chromeless` 在 replace 后仍在 `route.query` 里,直接读
    `route.query.chromeless` 可靠,**无需** sessionStorage。布局组件用 `computed(() => route.query.chromeless === '1')`
    保证响应式。

### 4. 桌面端降级 + 向后兼容

- 桌面包不发 admin-spa,且知识库 `desktop:'hidden'`。tab「可见条件」含「非桌面隐藏」→ **桌面端 hub
  只显技能库**,等价于今天的 `/skills`,自然降级,无白屏/坏 iframe。
- 老 `/skills` `/knowledge` 经 redirect 进 hub 对应 tab;`router.push('/skills')` 等现有调用不破。
- `/admin/mcp`(原生 McpToolsPage)、`/platform-envs`(PlatformEnvs)、`/platform-admin/*`(整体内嵌)
  **本期都不动**,各自路由保留。

## 非目标(YAGNI / 后续)

- **不清理 MCP/AI 网关的「双版本」**:原生 `/admin/mcp`、`/platform-envs?tab=llm` 与 admin-spa 平台版
  并存的去重,是独立、有风险的清理(涉及租户级 vs 平台级语义),单开一轮,不并入本期(避免大改污染 review)。
- 不做 hub 弹窗形态(早期注释提过「弹窗」)—— 页面 + tab 更可深链、更一致,弃用弹窗。
- 不动后端、不动各能力页自身逻辑(只挪入口 + 加内嵌外壳)。

## 文件结构 / 影响面

主 app(`frontend/`):
- 新增 `views/CapabilitiesHubPage.vue`(hub 外壳 + tab 条 + tab 内容分发)。
- 新增 `components/common/AdminSpaEmbedFrame.vue`(adminPath + chromeless → iframe)。
- 新增 `composables/useCapabilitiesHub.ts`(纯函数:tab 定义、按权限/桌面过滤可见 tab、`?tab=` 归一/回落、
  老路径→hub tab 映射)—— 便于 vitest 纯函数测。
- 改 `router/index.ts`:加 `/hub` 路由;`/skills`、`/knowledge` 改 redirect 到 hub tab。
- 改 `components/v2/RailSidebar.vue`:`hubNavItem.path`→`/hub`;删独立 `/knowledge` footer 入口。

admin-spa(`admin-spa/`):
- 改布局组件(AdminLayout 或等价):`chromeless=1` 时去侧栏/头部,只渲染内容;handoff 守卫保留 `chromeless`。

后端:无改动。

## 修订(2026-06-26 实现后)

- **「AI 网关」tab 改用原生「模型配置」而非 admin-spa 内嵌**。原设计把 AI 网关 tab 内嵌 admin-spa
  `/llm-configs`(平台版),但经核实:`llm_configs` 表**按租户隔离**,admin-spa 那版解析到平台管理的
  租户上下文 → 显示的不是用户会话租户实际在用的模型(出现「0 个配置」而原生 `/platform-envs?tab=llm`
  有 gpt-5.5 的困惑)。「AI 网关」与「模型配置」本是同一张表、同一接口,「网关」只是配置里 base_url
  指向 omnigate。故 AI 网关 tab 改渲染**原生 `<PlatformEnvs only="llm" />`**(给 PlatformEnvs 加 `only`
  prop:只显模型配置、隐藏 tab 条与平台环境),显示用户本租户真实模型,且**可见性放宽到租户管理员**
  (模型配置本就是各租户自管)。MCP tab 仍内嵌 admin-spa(chromeless)不变。
- **「MCP」tab 也改用原生 `McpToolsPage` 而非 admin-spa 内嵌**。原内嵌方案(iframe + chromeless 去壳)在
  实测中把整个 admin-spa 平台管理控制台(它自己的侧栏 + 8 个 nav + 顶部 tab)套进 MCP tab = "应用套应用"。
  既然 AI 网关已原生,MCP 同样改原生 `McpToolsPage`(主 app 既有的 MCP 工具页)。
- **admin-spa 内嵌整套移除**:四个 tab 全部就地渲染主 app 原生组件(技能库/知识库/McpTools/PlatformEnvs),
  **不再有任何 iframe / admin-spa 内嵌**。随之删除 `AdminSpaEmbedFrame.vue`、回滚 `buildPlatformAdminIframeSrc`
  的 `chromeless` 参数与 admin-spa `AdminLayout` 的 `chromeless` 去壳改动(无人再用)。原 §3「chromeless 内嵌」
  整节作废。
- **附带修复**:全局 `.el-button.is-link` 未重置 `--primary/--danger` 的实心背景(带 !important)→ link 型按钮
  变实心色块、文字色=背景色不可见(暗色尤甚)。`styles/builder.css` 给 is-link 补 `background/border 透明 !important`。

## 测试

- 前端 vitest(纯函数,`useCapabilitiesHub.ts`):①普通用户可见 tab = [skills];②平台管理员 = [skills,
  knowledge, mcp, gateway];③桌面 = [skills];④`?tab=knowledge` 普通用户 → 回落 skills;⑤老路径映射
  `/skills→skills`、`/knowledge→knowledge`。
- 前端 `AdminSpaEmbedFrame` iframe src 拼接:`chromeless` 时含 `&chromeless=1` + `handoff_token`。
- admin-spa 单测/组件测:`chromeless=1` 时不渲染侧栏/头部,只渲染 `<router-view>`;无 `chromeless` 时照旧带壳。
- `npm run build:nocheck` 主 app + admin-spa 各自构建过。
- 真机验收(用户):管理员开 hub 见 4 tab,技能/知识就地渲染、MCP/网关无壳内嵌且免登可操作;普通用户只见
  技能库 tab;老链接 `/skills` `/knowledge` 正常进对应 tab;`/platform-admin` 整体入口仍带壳正常。

## 已确认决策

- hub 装 4 tab(一步到位),非 2 tab。
- MCP/AI 网关用**平台版 admin-spa 页内嵌为 tab**(非跳转、非原生页)。
- 用独立 `chromeless=1` 标志去 admin-spa 壳,不复用 `embed=1`(保护现有 `/platform-admin` 整体内嵌)。
- hub 形态 = 页面 + `?tab=` 顶部 tab 条(非弹窗);路由 `/hub`;老路径重定向。
