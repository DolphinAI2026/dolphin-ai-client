# aPaaS 原生多产物分解 + 单页预览(设计)

> 2026-06-20。源自「两端招聘系统」dogfood 找短板(见 `docs/competitive-analysis-2026-06-20.md` + memory `recruit_dogfood_gaps_2026_06_20`)。用户选定方向 A(aPaaS 原生多产物分解),贴平台护城河,不偏向通用 app 生成器。

## 背景与问题

实测:把「招聘系统,管理端+用户端两端」喂给 coding 流水线,被**塌缩成单个 `form-page` 产物**(一个 698 行 Vue,currentRole 切换 + 内存 mock CRUD),还静默报 clean/done。根因(已 root-cause 到 file:line):`ProjectType`(`workspace.py:272`)/`SceneType`(`scenes.py:10`)/`create_workspace` 三层锁死「一工作区 = 一个 aPaaS 单扩展产物」,场景检测(`pipeline.py:965`)只能从单产物白名单里挑一个,多端请求无处落地。

G4「交付诚实声明」已修(commit `8481b506`):让系统**对收窄诚实**,但不解决「真能做两端」。本设计解决后者。

## 目标 / 非目标

**目标**
- 多端/多页请求 → 不塞单页、不拒绝,而是**分解成多个 aPaaS 单扩展产物**(管理端=若干 form-list/menu-page,用户端=mobile-page),挂在一个 Project 下分组。
- 每个产物可本地预览(并入 G3:单页 scene 的真 mount preview harness + 自动起 serve)。
- 永不更糟:分解失败/不适用 → 回落现有单产物路径 + G4 诚实声明。

**非目标**
- 不做「通用单体两端工程脚手架」(含路由的独立 app)——那把产品推向竞品最强的通用赛道,明确避开。
- 不做跨产物的共享数据层/统一后端(各产物仍是 aPaaS 扩展,数据走平台)。
- MVP 不做深度前端分组 UX(项目分组已有 `list_project_workspaces`,够用;富展示作后续)。

## 架构与组件

四个新/改动单元,职责单一、接口清晰:

### 1. 多端信号检测(复用,不新增)
复用 `app/coding/delivery_honesty._has_multi_end_signal(requirement)`(已测)。**唯一的分解门**:仅强信号(显式「两端/双端/多页/完整系统」,或「管理侧词 + 用户侧词」同现)才进分解路径;弱信号/普通单页请求行为完全不变。

### 2. 分解器 `app/coding/decompose.py`(新)
- 纯逻辑 + 一次 LLM 调用。输入:原始请求 + 可用 scene 清单。输出:校验后的计划。
- 计划 schema:`{ "artifacts": [ {"name": str, "side": "admin"|"user", "scene": <单产物 scene 值>, "sub_request": str}, ... ] }`,**1 < N ≤ 4**。
- `scene` 必须 ∈ 现有单产物 scene 白名单(form-list / menu-page / mobile-page / form-page);非法 scene → 该项丢弃或回落 form-page。
- 纯函数 `parse_decomposition(raw_json, available_scenes) -> Plan|None`(可单测,不调 LLM):解析 + 校验 + 上限裁剪 + 非法剔除;空/非法 → None。
- `async decompose(requirement, llm_cfg) -> Plan|None`:拼 prompt(给正反例:招聘=管理端多 form-list + 用户端 mobile-page;普通「做个登录页」= None 不分解)+ 调 LLM + `parse_decomposition`。任何异常 → None(回落,不中断)。

### 3. 编排器 `app/coding/orchestrate.py`(新,在 pipeline 之上)
- `async run_multi_artifact(params, db) -> AsyncIterator[event]`:
  1. `decompose()`;为 None → 直接委托现有 `run_coding_pipeline`(单产物 + G4),return。
  2. 新建一个 Project 行(owner=`params.user_id`,tenant=`params.tenant_id`,name 取自请求摘要),拿到 `project_id` 作分组;emit「已分解为 N 个产物」计划事件。
  3. 顺序 for each artifact:`create_workspace(scene, project_id=P)` → 跑单产物 codegen(复用现有生成原语,sub_request 作 message)→ 透传该产物事件(带 artifact 序号/名,前端可分组)。
  4. 末尾 emit 汇总:N 个产物清单(名/side/scene/workspace_id)+ 项目 P + 每个的预览端口。
- 失败隔离:某个产物生成失败 → 记错继续下一个,汇总里标注失败项(不整体崩)。

### 4. 路由接线
现有 coding/harness 入口在进 `run_coding_pipeline` 前加判断:首轮(非 iteration)+ 多端强信号 → 走 `run_multi_artifact`;否则原样。iteration(已有 workspace)永不分解。

### G3 并入:单页 scene 本地预览
- 给单页 CLI 模板(form-page/form-list/menu-page/mobile-page)补真 mount 的 `preview/index.html` + `preview/main.js`(复用 form-component-dual 现成内联模板,`workspace.py:3831/3855`),并在模板 `package.json` 加 `preview` 脚本 → `_resolve_serve_command`(`workspace.py:1809`)的「优先 preview 脚本」分支即对单页生效,起真页面而非 UMD 白屏。
- 编排器每个产物生成后自动 `start_serve`(失败仅记日志),汇总带回真实 port。
- ⚠️`_serve_processes` 是类级 dict:N 个产物 = N 个 serve 子进程 + N 个端口,需确认端口分配(`_next_port`)与进程回收不泄漏;并发会话同理。

## 数据流

```
用户请求 → [多端强信号?]
  否 → run_coding_pipeline(单产物) + G4 诚实声明           (现状不变)
  是 → decompose() → None? → 同上(回落)
                   → Plan(N) → 建 Project P
                       → for artifact in Plan:
                           create_workspace(scene, project_id=P)
                           单产物 codegen(sub_request) → 产物 + start_serve
                       → 汇总事件(N 产物 + P + 各 port)
```

## 错误处理
- decompose 任何失败/超时/空 → 回落单产物路径(永不更糟)。
- 单个产物生成失败 → 隔离,继续其余,汇总标注。
- start_serve 失败 → 非致命,该产物标「未起预览」,不阻断。
- 全程不改 G4 / autofix / done 结构;分解路径有自己的汇总事件。

## 测试策略
- `parse_decomposition` 纯函数单测:合法计划解析 / 上限裁剪(>4)/ 非法 scene 剔除 / 空→None / N≤1→None(不值得分解)。
- `_has_multi_end_signal` 已测(复用)。
- 编排器单测:mock decompose 返回 2 产物 + mock 单产物生成 → 断言建了 N workspace、同一 project_id、emit 了计划+汇总事件、失败产物被隔离。
- G3:`_resolve_serve_command` 对带 preview 脚本的单页模板走 preview 分支(单测)。
- **端到端验证**:重跑招聘 dogfood,断言产出 N 个产物(管理端 form-list + 用户端 mobile-page)挂同一 project,各有 port,而非一个塞满的文件。

## MVP 范围与分阶段
- **Stage 1 分解器**:decompose.py + parse 纯函数 + prompt + 单测。(不接线,可独立验证)
- **Stage 2 编排器**:run_multi_artifact + Project 分组 + N 次生成 + 事件 + 单测。
- **Stage 3 路由接线**:入口判断 + 端到端 dogfood 验证。
- **Stage 4 G3 预览**:单页模板 preview harness + 编排自动 serve + 单测。
- 后续(非本轮):前端分组富展示、跨产物字典/模型复用、分解计划用户可编辑确认门。

## 风险
- 分解质量:LLM 可能过度/不足拆分 → 上限 N≤4 + scene 白名单校验 + 回落兜底;后续可加用户确认门。
- 成本/时延:N 次 codegen = N× token + 串行耗时(招聘约 4×~4min)→ 可接受(完整系统),后续可并行化。
- 端口/进程:N serve 子进程的端口分配与回收(`_serve_processes` 类级 dict 并发)需在 Stage 4 核实。
- 误触发:强信号门保守,但仍可能误判 → 只在强信号 + 首轮触发;iteration 永不分解。
