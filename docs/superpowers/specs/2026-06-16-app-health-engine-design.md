# 应用体检引擎（App Health Engine）设计

- 日期：2026-06-16
- 状态：设计待评审（已据线上真实接口实测修订 + 多视角评审）
- 范围：v1 = 确定性体检引擎 + 结果落库（配置健康度 + 运行健康度）
- 关联方向：ai-builder 四大能力中「智能运维」（单应用体检）与「智能运营」（跨应用，v2）的地基

## 1. 背景与问题

当前「应用健康度分析」由 unified agent（gpt-5.5）调 MCP 读接口后**自由叙述并打分**：测量与判断揉在一次生成里 → 分数飘、不可复现、不可横比、不可追踪。运营恰恰要「可复现、可横比、可追踪」。

## 2. 核心原则

**测量与解读分离。**
- 测量 = 确定性代码（规则）。无 LLM、无随机、无引擎内部取时间 → 同输入必同输出。
- 解读 = LLM。在确定的指标 + findings 上写人话、排优先级、给修复建议。**分数与 findings 由引擎产出，LLM 不得发明。**

已有同款范式：`backend/app/services/lowcode_logs.py:build_lowcode_log_analysis`（纯 Python 规则）。

## 3. 目标 / 非目标

### v1 目标
1. 确定性体检引擎：输入应用结构 → `HealthReport`（总分 / 各维度分 / findings）。
2. 覆盖配置层 + 运行层，**只用单次 list 级调用就能拿到的数据**（无 N+1、无 mock、无非确定性数据源）。
3. 每次体检落一条快照，支撑趋势 / 横比 / diff。
4. 后端接口 + MCP 工具（供 agent 叙述）+ app 详情里「应用体检」面板。

### 非目标（明确推迟）
- 跨应用运营看板（基于快照聚合）→ v2。
- 需要 per-object 详情（N+1）的检查：流程节点级精细校验、事件触发/引用校验、事件执行历史、逐表单权限矩阵 → v2。
- 依赖平台暂不提供数据的检查：角色权限覆盖、模型主键、自开发构建状态、配置变更失败信号 → v2（待平台 API）。
- 真·用户使用量（数据日志插件常关闭）→ v2。
- 自动触发（发布后自动体检）、自动修复 → 后续。

## 4. 数据可行性（已实测，2026-06-16）

用后端既有 env 凭据实测 WMS 应用（apaas_app_id=854046919209517056）真实返回，结论：

| 数据 | 接口 | 实测可用字段 | v1 能做 | 拿不到 → 推迟 |
|---|---|---|---|---|
| 菜单 | `query_menus`（树，`submenus` 嵌套） | menuName / menuType / submenus / isEffective / menuDisplay | 空分组、命名缺失、停用 | （无扁平 parentId，孤儿不适用） |
| 数据模型 | `query_models(with_fields=False)` | **list 内直接含 fields/dataModelFields** / modelName / status | 无字段模型、停用模型 | 主键：字段无任何 PK 标记 → 推迟 |
| 字典 | `query_dicts` | dictionaryName / dictionaryStatus | 停用字典 | 空字典需逐字典查选项(N+1) → 推迟 |
| 角色 | `query_roles` | roleName / roleCode / status / **userCount** | 0 用户角色、停用角色 | 权限覆盖：无任何权限字段(只有 mock) → 推迟 |
| 流程 | `list_processes` | **list 内直接含 nodes + edges + status** | edge=0 断流、节点未连通、停用 | （拓扑可从 list 直接算，无需详情） |
| 业务事件 | `list_business_events` | eventType / status（WMS 无事件→维度 N/A） | 停用事件 | 触发/引用校验需详情(N+1) → 推迟 |
| 发布/版本 | `query_app_list`（取本应用条目） | **status / statusName(已上线) / currentVersion / lastUpdateDate** | 是否上线、是否有版本 | （平台自身状态，不受"平台直发"盲区影响） |
| 活跃/新鲜度 | 同上 `lastUpdateDate` | 应用最后更新时间（app 精确、稳定） | 距今天数超阈值 | （替代 operateLog：后者无 per-app 过滤、分页、非确定，弃用） |
| 部署记录 | 本地 `DeployRecord` | 仅本工具触发的部署，稀疏 | 仅作辅助，不作主源 | 平台直发不入库 → 不依赖它判发布 |

> 关键纠正：运行层不再依赖 operateLog（无 per-app 过滤、结果随分页/文本匹配漂移，破坏确定性），改用 `query_app_list` 的应用条目 status/version/lastUpdateDate —— app 精确且稳定。

## 5. 架构

```
apaas 读接口(每类一次 list 调用，并发) ──► HealthCollector ──► HealthEngine(纯规则) ──► HealthReport
                                                                          ├─► GET /applications/{id}/health（返回 + 落快照）
                                                                          ├─► MCP compute_app_health（agent 叙述用，不落库）
                                                                          └─► app_health_snapshot 表
```

新增模块 `backend/app/services/app_health/`：
- `collector.py`：IO 层。用现成 `APaaSClient` 读方法（`query_menus / query_models(with_fields=False) / query_dicts / query_roles / list_processes / list_business_events / query_app_list`）经 `call_apaas_with_relogin` 并发拉，组装 `AppSnapshotInput`（dataclass）。**每类数据一次 list 调用，无 per-object 展开。** 同时读本地 `DeployRecord` 作辅助。`as_of` 时间戳在此层确定并写入 input。
- `checks.py`：每个检查项一个纯函数 `(input) -> CheckResult`。无 IO、无取时间（用 input.as_of）。
- `engine.py`：跑全部检查 → 按维度/权重聚合 → `HealthReport`。含闸门与 N/A 归一。`ENGINE_VERSION` 常量在此。
- `weights.py`：维度/检查权重 + 阈值常量，集中一处。
- `types.py`：`CheckResult / DimensionScore / HealthReport / AppSnapshotInput`。

隔离：collector 可 mock；engine/checks 纯函数，单测无需网络。

## 6. 检查项目录（v1，全部单次 list 可算）

`CheckResult { id, dimension, status(pass|partial|fail|na), sub_score(0-100), severity(high|medium|low|none), metric, findings[] }`。

### 配置层
**菜单 menus**（`query_menus` 树）
- `menu.empty_group`：分组型菜单 `submenus` 为空（medium）
- `menu.naming`：menuName 为空/占位（low）
- `menu.disabled`：`isEffective=false` 的菜单（low）

**数据模型 models**（list 内含 fields）
- `model.no_fields`：fields/dataModelFields 为空的模型（high）
- `model.disabled`：`status` 非启用（low）

**字典 dicts**
- `dict.disabled`：`dictionaryStatus` 非启用（low）

**角色 roles**（list 内含 userCount）
- `role.no_users`：`userCount=0` 的角色（medium）
- `role.disabled`：`status` 非启用（low）

**审批流程 processes**（list 内含 nodes+edges+status）
- `process.no_edges`：节点数>1 但无 edges（**high，断流**）
- `process.disconnected`：存在不被任何 edge 连接的节点（high，从 list 的 nodes/edges 直接算）
- `process.disabled`：`status` 非启用（medium）

**业务事件 events**（无事件 → 维度 N/A）
- `event.disabled`：`status` 非启用的事件（low）

### 运行层（均取自 `query_app_list` 本应用条目）
**发布 deploy**
- `deploy.unpublished`：`statusName` 非「已上线」/`status` 非 RUNNING（high）
- `deploy.no_version`：无 `currentVersion`（medium）

**新鲜度 activity**
- `activity.stale`：距 `lastUpdateDate` 天数 >阈值（默认 90d，medium；用 input.as_of 计算）

每条产出：指标 → 比阈值 → 子分 + severity + 命中对象 + 建议修法。

## 7. 打分模型

### 子分 → 维度分
- 每 check 给 0–100 子分（pass=100；partial 按命中比例；fail 按严重度档位给低分）。
- 维度分 = 维度内各 check 子分加权平均（check 级权重默认相等，可调）。

### 维度分 → 总分
- 两桶：配置 60% / 运行 40%（桶级权重，可调）。
- 桶内维度默认权重（高=对错攸关）：配置桶 流程 high、模型 medium-high、菜单 medium、角色 medium、字典 low、事件 low；运行桶 发布 high、新鲜度 medium。
- 总分 = 两桶加权平均。

### 闸门（gating）
- 任一 `severity=high` finding → 其维度封顶（默认 ≤50），并置报告 `has_critical=true`（前端「有高优风险」徽标），**与总分档位独立**。
- 说明：`has_critical` 独立于等级带 —— 一个 70–84「良好」分仍可能带高优风险（被健康维度平均掉），这是预期、非矛盾。

### N/A 归一（判定顺序明确）
- **collector 先判**：某维度无对象（如无事件、无流程）或数据源拉取失败 → 维度 `na=true`，**直接跳过该维度全部 check**（禁止在空数据上跑 check 再聚合成 N/A）。
- N/A 维度从加权剔除，桶内/桶间权重对剩余维度**重新归一**，不扣分、不编数。

### 确定性保证
- 引擎全程无 `random`、无引擎内 `datetime.now()`；「距今天数」用 collector 传入的 `as_of`（input 的一部分）。
- `ENGINE_VERSION` 常量：规则/权重变更时递增。

## 8. 落库

新表 `app_health_snapshot`：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| tenant_id | int | 租户隔离（用 `resolve_effective_tenant_id`） |
| app_id | int FK | 我们的应用 id |
| apaas_app_id | str | 平台应用 id |
| created_at | datetime | 体检落库时间 |
| as_of | datetime | 打分用的参考时刻（保证历史快照可复现） |
| total_score | int / null | 0–100；全源失败时 null |
| grade | str | 健康/良好/中等/风险/严重 |
| has_critical | bool | 是否有高优风险 |
| dimensions | JSON | 各维度 `{score, weight_used(归一后实际权重), weight_base(配置权重), na}` |
| findings | JSON | finding 列表（severity/对象/建议） |
| data_coverage | JSON | 各源/维度是否拿到（解读"全量 vs 部分"） |
| engine_version | str | 规则版本（趋势区分"应用变差"与"规则变了"） |

- `weight` 歧义已消除：`weight_used`=N/A 归一后实际权重，`weight_base`=配置权重；趋势分析据 na 集合判断维度集是否变化。
- 保留 `engine_version` + `data_coverage` + `as_of`：均直接服务 v1 落库目标与 v2 趋势/横比（成本仅几列，不引入额外工具）。

支撑：单应用趋势（app_id + created_at）、跨应用横比（各 app 最新快照）、两次快照 diff。

## 9. 露出 / 触发 / 交互

- 接口 `GET /applications/{app_id}/health`：跑采集+引擎 → 返回 `HealthReport` + 落快照。支持 `?persist=false` 预览不落库。
- MCP 工具 `compute_app_health(app_id)`：**返回与接口完全相同的 `HealthReport` schema**，agent 据此叙述；该工具**不落库**（落库只由接口做，避免面板与 agent 同时跑产生双快照）。
- 前端「应用体检」面板（app 详情内）：总分 + 等级 + 高优风险徽标 + 维度记分卡 + findings 列表。替掉现在那张随机表。
- findings 排序：先 severity（高→中→低），同档内按维度目录顺序（§6）再按 sub_score 升序（最差在前）；按维度分组展示，组内带 severity 标。
- 交互状态（实现须覆盖）：
  - 加载中：体检要并发拉多个接口，给进度态（可能数秒）。
  - 部分数据：N/A 维度在记分卡里显式标「N/A · 数据不可用」，不显示为 0 分。
  - 错误：未绑 env / apaas_app_id 缺失 → 接口 400，面板内联提示（非 toast）。
  - 全源失败：total_score=null，面板提示「暂无法体检」，findings 区空。
  - 陈旧结果：面板默认展示最近一次快照 + 体检时间戳 + 「重新体检」按钮，明示结果可能非实时。
- 触发：v1 仅按需（面板按钮 / agent 调用）。

## 10. 错误处理
- 单源拉取失败 → 该维度 `coverage=unavailable` + N/A，不阻断整体。
- 未绑 env / apaas_app_id 缺失 → 400 明确提示。
- 全源失败 → 报告 total_score=null + data_coverage 全空。
- 体检只读，不改任何应用配置。

## 11. 测试策略
- 每个 check 用构造 fixture 单测（pass/partial/fail/na 各覆盖）。
- 聚合：维度加权、桶加权、闸门封顶、N/A 归一 各单测。
- 确定性守卫：同 fixture（含固定 as_of）连跑两次，报告**逐字节相等**。
- 落库 + 租户隔离 单测。
- collector 用 mock client；engine/checks 纯函数无需网络。

## 12. 待定 / v2
- 默认权重/阈值首版按本文，上线后据真实应用回看再调。
- v2：跨应用运营看板（健康分布/风险榜/趋势）基于 `app_health_snapshot`。
- v2（数据到位后）：模型主键、角色权限覆盖、逐表单权限、流程/事件详情级校验、事件执行历史、空字典、自开发构建状态、配置变更失败、真实使用量。
- v1.1：发布后自动体检；体检 diff 通知。
