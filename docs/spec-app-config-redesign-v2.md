# 应用配置中心重设计 SPEC v2

> 2026-05-26 / Writer: Claude (orchestrator)
> Round 1 终稿 — 基于 reviewer 15 issues 修订 v1
> v1: docs/spec-app-config-redesign-v1.md (保留作历史)

---

## 🆕 v1 → v2 关键变化 (Changelog)

| Issue # | 严重 | 处理 |
|---|---|---|
| #1 PR2 LOC 低估 | 🔴 | PR2 拆 3 子 PR (2a/2b/2c) + LOC 上调 3-5x |
| #2 chat history 工具引用 | 🔴 | 因 #3 改"软引导", 此问题消失 |
| **#3 硬切白名单 → 软引导** | 🔴 | **采纳** — 工具全可见, section 只走 system prompt hint |
| #4 tool_registry 跨进程 | 🔴 | 改 YAML 文件 + 两边各 load + CI 校验 |
| #5 多用户并发 | 🔴 | P0 加单用户假设 + advisory lock; 多人协作 P3 |
| #6 iframe 未保存编辑 | 🟡 | 切 section 前 postMessage 探活 + confirm 弹窗 |
| #7 section 顺序无依据 | 🟡 | 加 telemetry (section_enter / section_dwell_ms) |
| #8 4 入口保留矛盾 | 🟡 | 明说 "P0 保留, P3 评估收敛" + 给条件 |
| #9 验收不可自动化 | 🟡 | E2E 改 chrome-devtools-mcp 脚本 |
| #10 回滚缺失 | 🟡 | 加 `?legacy=1` feature flag + 回滚矩阵 |
| #11 移动端 | 🟡 | P0 加 min-width 约束 fallback 老页面; responsive P2 |
| #12 extension E0 跳走断点 | 🟡 | 新标签打开 + 双向 deeplink, ConfigAssistant 不丢上下文 |
| #13 浮动 vs 侧栏 | 🟢 | §7.3 加理由 + P1 A/B 测 |
| #14 PR7 拆 P0 | 🟢 | `update_apaas_app_info` 上提 P0 |
| #15 session schema | 🟢 | 加 `current_section` 列 |

新增章节: §13 "明确不做" / §14 "feature flag + 回滚矩阵" / §15 "telemetry 设计"

---

## 0. 背景 (同 v1, 略)

---

## 1. 顶层架构 (修订)

### 1.1 三区布局 (基本同 v1)

```
+---------------------------------------------------------------------------+
| TopBar: [< 返] [图书借阅管理系统] [→ 自开发] [🚀 部署] [⏱ 历史] [更多]  |
+--------+--------------------------------------------------+---------------+
| 📊数据 |                                                  |  ConfigAssis  |
| 🎨界面 |  Section 主区域 (iframe 或自建 UI)              |  tant 浮动    |
| ⚙️逻辑 |                                                  |  (FAB 默认收  |
| 🔒权限 |                                                  |  起, 打开后   |
| 🧩扩展 |                                                  |  position:    |
|        |                                                  |  fixed)       |
+--------+--------------------------------------------------+---------------+
```

### 1.2 ⭐ v2 关键架构变更: 软引导白名单 (Issue #3)

**v1 设计 (废)**: 切 section → 硬切 ConfigAssistant 工具白名单, 不在白名单的工具 AI 看不见。

**v2 设计 (采纳 reviewer)**: ConfigAssistant **永远看全套 62 个工具**, section 只通过 system prompt 注入 "**focus hint**":

```
<!-- backend 注入到 system prompt 顶部 -->
当前用户聚焦的配置区域: {{section_name}}.
建议优先使用以下工具完成用户意图: {{section_preferred_tools}}.
其他工具仍可用, 但若用户问的事跨区域, 主动建议用户切到对应 section.
```

**好处**:
- AI 不"失忆" — 用户在 ui section 问"刚改的字段为啥没生效", AI 还能调 `list_apaas_app_models` 答
- 跨 section 对话天然支持 (Issue #2 消失)
- tool_registry 复杂度降低: 只需要 "tool → section affinity" 标签, 不需要 "section → strict whitelist"
- 跟 Retool / Cursor / GitHub Copilot Chat 实证模式对齐

**代价**:
- AI 可能在 ui section 时调 data 类工具 (用户其实想"加字段") — 但这是**好事** (不要求用户先切 section), 只在 system prompt 提醒 "下次类似操作可切到 data section, 体验更聚焦"
- LLM context 长度: 62 tool schemas 全发, 不裁剪 — gpt-5.5 / claude 长 context 都 OK

### 1.3 全套白名单还是要管理 (#4 跨进程)

仍然需要 `tool_registry`, 但变成**软标签**:

```yaml
# backend/tool_registry.yaml — 单一真相
tools:
  list_apaas_app_models:
    sections: [data, permission]      # affinity 标签 (软)
    agents: [builder, coding, config] # 可见 agent 列表
    category: introspection
    description: "..."
  deploy_application:
    sections: [global]
    agents: [builder, config]
    category: lifecycle
```

**跨进程一致性方案**:
- YAML 文件提交在 git, build 时 backend 跟 mcp_server **各自 load**
- CI 加 test: 两边 load 出来的工具集 diff = 0
- 部署时 backend image + mcp_server image 都基于同一 commit hash
- 不用 DB 表 (热改不是 must-have, 加新工具走部署 ok)

---

## 2. 5 个 Section (修订)

### Section A — 📊 数据 (data)
**affinity 工具** (system prompt 优先推荐, 共 14):
```yaml
data:
  - list_apaas_app_models, list_apaas_models_in_env
  - update_apaas_app_model, add_apaas_model_field
  - update_apaas_model_field, disable_apaas_model_field
  - list_apaas_app_dicts, create_apaas_app_dict, update_apaas_app_dict
  - disable_apaas_app_dict, add_apaas_dict_option
  - update_apaas_dict_option, disable_apaas_dict_option
  - list_apaas_app_menus    # 字段绑表单时要查菜单
```

**主区域 UI**: iframe 嵌平台 `/admin/app-store/edit-app?currentStepIndex=1`

---

### Section B — 🎨 界面 (ui)
**affinity 工具** (共 20):
```yaml
ui:
  - list_apaas_app_menus, list_apaas_form_components, list_apaas_form_views
  - create_apaas_form_menu, create_apaas_self_dev_menu, delete_apaas_app_menu
  - create_apaas_menu_group, set_apaas_menu_parent, rename_apaas_menu
  - update_apaas_form_component, bind_apaas_form_field_to_dict
  - build_apaas_feature_from_spec
  - browser_*  # 浏览器辅助 (菜单拖排序等 MCP 不覆盖场景)
```

**主区域 UI**: 沿用现有 ApaasMenuSidebar + 平台 iframe (已实现)

---

### Section C — ⚙️ 逻辑 (logic)
**affinity 工具** (16): set_apaas_app_process + 业务事件 13 个 + 通用读 2 个

---

### Section D — 🔒 权限 (permission)
**affinity 工具** (8): 角色 CRUD + 字段权限

**P0 待补 (Issue #14 上提)**:
- `set_apaas_menu_role_visibility` — 菜单可见性
- `set_apaas_data_permission` — 数据权限

---

### Section E — 🧩 扩展 (extension)
**P0 选 E0 (新标签跳走)** ⭐ Issue #12 调整:

**v1 设计 (废)**: 直接跳 `/coding`, 当前 tab 切走 → ConfigAssistant 关掉 → 回来时丢上下文

**v2 设计**:
- Section E 主区域显**两张大卡片**:
  - 卡 1: 「→ 用 ai-coding 写自开发包」按钮 → `window.open('/ai-coding/chat?app_id=N&from=extension', '_blank')` — **新标签**打开
  - 卡 2: 「→ 平台自开发资源管理」按钮 → 新标签打开 iframe URL
- ConfigAssistant 留在当前 tab 不动, 上下文不丢
- 跳走的 ai-coding agent 完成 publish 后, **后端通过 WebSocket 或轮询通知** ConfigAssistant tab: "扩展资源已更新, 是否 republish?"

**affinity 工具** (5): list_dev_scenes / get_dev_scene_spec / get_dev_scene_full_workflow / list_apaas_app_dev_kits / list_apaas_resource_pool_kits

**P2 升级到 E1 (真嵌入)**: 见 §8 PR8

---

### 顶部 CTA (修订)

**新增 (Issue #14 上提 P0)**: `update_apaas_app_info` MCP — 顶部"编辑应用名/图标/描述"小按钮用

**全局 affinity** (`section: global`, 任何 section AI 都优先想到):
```yaml
global:
  - deploy_application, publish_application
  - list_deploy_records, rollback_application
  - republish_apaas_app, get_apaas_app_overview
  - update_apaas_app_info     # 新增
```

---

## 3. ConfigAssistant 跨 Section 行为 (大改)

### 3.1 工具发现 — 软引导

```
请求 POST /api/applications/{id}/config-chat-stream
  body: { message: "...", section: "ui", history: [...] }

backend 行为:
  1. Load tool_registry.yaml
  2. Tool list 发给 LLM = 全套 62 个工具 schema (不裁剪)
  3. System prompt 顶部注入:
     "当前用户在 ui section. 优先用: [build_apaas_feature_from_spec,
      update_apaas_form_component, ...] (这 20 个最匹配 ui 场景).
      其他工具仍可调, 但若用户意图跨 section, 主动建议切."
  4. AI 自由选工具
```

### 3.2 Section 切换不影响 chat session

(Issue #2 消失) — 工具全可见, history 里的旧工具引用不会"失效"。

### 3.3 跨 section 自动建议

AI 在 ui section 听到 "我要加个新流程审批" → 主动说 "这是逻辑 section 的事, 我帮你切过去? [切到逻辑]" → 前端收到 `suggest_section_switch` 事件后弹按钮。

---

## 4. 4 个 Chat 入口收敛方案 (修订 Issue #8)

### 4.1 为啥 P0 不收敛

**理由 1 — 工程成本**: 收敛 = 删掉 OnlineCodingPage 24 处前端调用 + 重写 CodingPage 用户流程 + dolphin 重新调试 agent 边界 — **2 周工作量**, P0 1 周拉不完

**理由 2 — agent 边界已合理**: codebase 实测发现 ai-builder/ai-coding/vibe-coding 三 agent 白名单**重叠 28 个 + 各专 18/34/11**, 是有 design intent 的分工 (建应用 vs 写自开发包 vs 独立项目), 不是历史包袱

**理由 3 — 用户认知问题靠 UI 不靠收敛**: 增加 banner + Landing 入口卡片 + cross-link 已经能解 80%

### 4.2 P3 评估收敛的触发条件

- 半年内统计: 4 个入口的活跃用户数 / 单次会话切入口的频率
- 如果发现 > 30% 用户开 ChatPage 又开 CodingPage 做同一件事 → 收敛信号强
- 如果用户跨入口痛点反馈 > 5 条 → 收敛信号强
- 都不达标 → 维持 4 个

### 4.3 P0 必做 (PR4)

- AIChatPage 上方 banner: "已经有应用？→ 点应用名进应用配置中心"
- ChatPage 扩展 section 提示: "需要写代码？→ ai-coding agent"
- Landing 重画入口卡: 4 个入口 + "我该用哪个?" 决策树

---

## 5. 4 套白名单合并方案 (修订 Issue #4)

### 5.1 单一真相: YAML 文件 (改 v1 的 Python dict)

`backend/tool_registry.yaml`:
```yaml
# Single source of truth for all MCP tool metadata.
# Loaded at startup by both backend + mcp_server.
# CI test 保证两边 diff = 0.
version: 1
tools:
  list_apaas_apps_in_env:
    sections: [global]
    agents: [builder, coding, config]
    category: introspection
  build_apaas_feature_from_spec:
    sections: [ui]
    agents: [config]
    category: feature_builder
  # ... 114 个工具
```

### 5.2 派生视图 (build-time)

新增 `backend/app/tool_registry.py`:
```python
import yaml
from pathlib import Path

_REGISTRY: dict = None

def load():
    global _REGISTRY
    if _REGISTRY is None:
        with open(Path(__file__).parent.parent / "tool_registry.yaml") as f:
            _REGISTRY = yaml.safe_load(f)
    return _REGISTRY

def tools_for_section(section: str) -> list[str]:
    """affinity 工具列表 (软引导用, 不是硬白名单)"""
    return [
        name for name, meta in load()["tools"].items()
        if section in meta.get("sections", []) or "global" in meta.get("sections", [])
    ]

def tools_for_agent(agent: str) -> list[str]:
    """agent prompt 用的可见工具列表"""
    return [
        name for name, meta in load()["tools"].items()
        if agent in meta.get("agents", [])
    ]
```

### 5.3 mcp_server 也 load 同一 YAML

`backend/app/mcp_server.py` 启动时也 `tool_registry.load()`, CI 测两个 service load 出来的 tool dict equal。

### 5.4 agent prompt 生成

`docs/skills/ai-builder/prompt.template.md` (手写 — 不含工具列表):
```markdown
你是 aPaaS 应用搭建专家...
## 你的工具
<!-- AUTO_GENERATED_TOOLS_START -->
[ai-builder agent 可见工具列表会自动插这里]
<!-- AUTO_GENERATED_TOOLS_END -->
...
```

部署脚本 `scripts/build_prompts.py`:
```python
# python scripts/build_prompts.py
# 读 prompt.template.md + tool_registry.yaml → 拼成 prompt.md
```

加 git pre-commit hook 自动跑。

---

## 6. v1 / v2 / online_coding 决策 (同 v1, 略)

---

## 7. UI 低保真 (修订 Issue #6 / #11 / #13)

### 7.1 切 section 防丢未保存编辑 (Issue #6)

```js
// 切 section 前
async function switchSection(newSection) {
  // 1. 向当前 iframe postMessage 探活
  iframe.contentWindow.postMessage({type: 'check_dirty'}, '*')
  // 2. 等 100ms iframe 回执 {dirty: true/false}
  const dirty = await waitDirtyResponse(100)
  if (dirty) {
    // 3. 弹 confirm "你在当前页面有未保存内容, 切走会丢失. 继续?"
    if (!confirm("未保存内容会丢失, 继续?")) return
  }
  // 4. 切 section URL + 通知 ConfigAssistant
  currentSection.value = newSection
  iframe.src = SECTION_IFRAME_URL[newSection]
  configAssistantApi.setSection(newSection)
}
```

平台 iframe 内部要响应 `check_dirty` postMessage — 用 inject script (我们已经在 platform_proxy.py 注入了, 加一段监听)。

### 7.2 移动端 / 窄屏 (Issue #11)

**P0 约束**:
- min-width: 1280px
- 窄于 1280 显 banner: "应用配置中心需要 1280px+ 宽屏, 当前过窄, 已为你切到老视图"
- 自动 fallback: 加 `?legacy=1` → 走老 ChatPage

**P2 真 responsive**: section nav 折叠抽屉 + ConfigAssistant 全屏抽屉

### 7.3 ConfigAssistant 浮动 vs 侧栏 (Issue #13)

**v2 决定 P0 保持浮动**, 理由:
- 已实现 (commit 36720a5 浮动模式)
- 用户多次 review 时调过 (overlay → split 模式), 体验已迭代过
- 浮动 + split 模式实际占的视觉空间跟侧栏常驻差不多

**P1 加 A/B 测**: 用 feature flag `?ca=sidebar` 让 5% 用户试侧栏常驻, measure 切换频率 / 平均会话时长 → 数据决定 P2 改不改

---

## 8. 实施 PR 切分 (修订 Issue #1 — LOC 重估 + PR2 拆 3 子 PR)

### 🔥 P0 (3 周, 不是原来 1 周)

#### PR1 — `tool_registry.yaml` + load 模块 (3 天)
- 写 yaml + load function
- mcp_server + backend 都 import
- 新加 `/api/applications/{id}/config-chat-stream` 接 `section` 参数
- 老 `_CONFIG_CHAT_TOOL_WHITELIST` 改成 `tool_registry.tools_for_agent("config")`
- CI: 两边 load 后 tool dict diff = 0
- **预期 LOC**: ~600 行 yaml + 300 行 python + 200 行测试 = 1100
- **风险低**: ConfigAssistant 行为不变 (派生白名单跟现状对齐)

#### PR2a — 抽 `SectionNav.vue` 子组件 (2 天)
- 单纯抽组件, 不接逻辑
- 渲染 5 section 按钮 + 二级 sub-tab
- props: `current-section`, emit: `switch-section`
- ChatPage 用现有 ApaasMenuSidebar **保持原位**, 暂不替换
- 新组件独立路由 `?demo=section-nav` 测渲染
- **预期 LOC**: 新组件 ~400 行 + ChatPage 0 改
- **风险低**: ChatPage 不动

#### PR2b — ChatPage 接 SectionNav + section state (5 天)
- ChatPage 加 `currentSection` ref + localStorage 持久化
- SectionNav 替换 ApaasMenuSidebar (但 ApaasMenuSidebar 作为 ui-菜单 sub-tab 嵌入)
- 切 section 换 iframe URL
- **加 Issue #6 防丢编辑 postMessage**
- **加 Issue #11 min-width 1280 fallback `?legacy=1`**
- **预期 LOC**: ChatPage +1500/-800 (reviewer 说 800 不可信, 这次按 6x 估)
- **风险高**: 触发 ChatPage 联动 bug; 需要 feature flag 兜底

#### PR2c — ConfigAssistant section-aware system prompt (2 天)
- backend `/config-chat-stream` 收 `section` → 拼 system prompt focus hint
- 不再硬切 tool list
- ConfigAssistant 前端发 `section` 参数
- **预期 LOC**: backend 200 + frontend 100
- **风险低**: 工具行为不变, 只是 prompt 多 1 段

#### PR3 — 顶部 CTA + `update_apaas_app_info` (2 天, Issue #14 上提)
- 部署 / 历史按钮 (复用 DeployHistoryDrawer)
- 新 MCP `update_apaas_app_info` (改应用名/图标/描述)
- breadcrumb 接 update_apaas_app_info
- **预期 LOC**: 250

#### PR6 — extension section E0 新标签跳走 (1 天, Issue #12 修)
- 显两卡片, 跳走时新 tab
- WebSocket 通知 ConfigAssistant "外部资源已更新" — 用 SSE 现有的也行
- **预期 LOC**: 200

### P0 总 LOC 估: ~4500 (v1 估 ~1700 — 多 2.6x, 跟 reviewer #1 警告对齐)
### P0 总时间: 3 周 (含测试 + bug 修)

### 🟢 P1 (2 周)
- PR4 banner / Landing 入口卡 (3 天)
- PR5 agent prompt 自动生成 (4 天)
- PR7 补缺口工具 set_apaas_menu_role_visibility / set_apaas_data_permission (3 天)
- PR-telemetry (Issue #7): section_enter / dwell_ms 埋点 + 看板 (2 天)
- PR-mobile-fallback (Issue #11): P1 加 responsive minimal (2 天)

### 🟡 P2 (1 月+)
- PR8 extension E1 真嵌入 IDE iframe + Coding sub-agent
- PR-multi-user (Issue #5): 多人协作 (advisory lock + WebSocket 广播)
- PR-AB-sidebar (Issue #13): 浮动 vs 侧栏 A/B 测

### 🔵 P3 (随缘)
- PR9 v1 / v2 / online_coding 退役决策
- PR-collapse-chat-entries: 4 入口收敛到 2 (Issue #8 评估后)

---

## 9. 关键决策 (修订 + 扩充)

### 9.1 已决策 (含 reviewer 推动的)

| 决策 | 选择 | 来源 |
|---|---|---|
| 顶层 section 数 | 5 + 1 顶部 CTA | web research 行业惯例 |
| Coding 入口 | 保留 + 融入扩展 section | 用户要求 |
| 数据 vs 界面 | 严格分离 | web research |
| **白名单切换** | **软引导, 不硬切** | **reviewer #3 ⭐** |
| **tool_registry 格式** | **YAML 文件 + 两边 load** | **reviewer #4** |
| v1/v2/online_coding | 并存 + 决策文档 | codebase 补盘 |
| ConfigAssistant 位置 | P0 浮动 / P1 A/B 测 | reviewer #13 |
| 4 chat 入口 | P0 保留 + UI 引导, P3 评估 | reviewer #8 |
| 多用户并发 | P0 单用户假设, P2 真做 | reviewer #5 |
| 移动端 | P0 fallback / P1 minimal / P2 真 responsive | reviewer #11 |
| Extension E0 | 新标签跳走 + WebSocket 通知 | reviewer #12 |
| Section 顺序 | data→ui→logic→permission→extension + telemetry 监 | reviewer #7 |

### 9.2 待用户拍板 (减到 3 个)

**Q1 — Section 中文命名**:
- A. 数据 / 界面 / 逻辑 / 权限 / 扩展 (短, icon 配)
- B. 数据模型 / 界面设计 / 业务逻辑 / 权限管理 / 扩展开发 (跟平台对齐)
- 我倾向 A — 短 + icon 表达足够; 用户首次进会 hover 看说明就懂

**Q2 — P0 时长 3 周接受吗?**
- reviewer 论证清楚了原 1 周低估了
- 我估 3 周 (PR1 3天 + PR2a 2天 + PR2b 5天 + PR2c 2天 + PR3 2天 + PR6 1天 + buffer/测试 1.5 周)
- 你想压回 2 周需要砍 PR2c (软引导)或者 PR3 (顶部 CTA) — 不建议砍

**Q3 — Extension E0 主区域 UI**:
- A. 两大卡片跳走 (我推荐, 简单)
- B. 显平台自开发资源管理 iframe (用户感觉"留在主流程")
- C. 显当前应用已 attach 的 dev kit 列表 (我们查 list_apaas_app_dev_kits 自己渲染)
- A 跟 reviewer 一致, B/C 也有道理但工作量多

---

## 10. 工程量估算 (修订)

| Phase | 估时 | LOC |
|---|---|---|
| P0 (3 周) | 4500 LOC | 5 PR (1, 2a, 2b, 2c, 3, 6) |
| P1 (2 周) | 2500 LOC | 5 PR |
| P2 (1 月+) | 5000 LOC | 3 PR |
| P3 (随缘) | 不预估 | 2 PR |

---

## 11. 验收标准 (修订 Issue #9 — 自动化优先)

### P0 验收 (E2E + unit)

#### E2E (chrome-devtools-mcp 脚本)
```javascript
// tests/e2e/section-switch.spec.ts
test("切 section, iframe URL 跟着切", async () => {
  await page.goto("/ai-builder/chat?app_id=13")
  await page.click('[data-section="ui"]')
  expect(page.url()).toContain("section=ui")
  expect(page.frameLocator(".platform-iframe").locator("body"))
    .toBeVisible() // iframe 重新 load
})

test("Section A 切到 B, dirty editor 弹 confirm", async () => {
  // 平台 iframe 注 mock dirty=true
  // 切 section
  expect(page.locator(".el-message-box")).toContainText("未保存内容")
})

test("窄屏 fallback 老视图", async () => {
  await page.setViewportSize({width: 1100, height: 800})
  await page.goto("/ai-builder/chat?app_id=13")
  expect(page.url()).toContain("legacy=1")
})
```

#### Unit (pytest)
```python
# tests/test_tool_registry.py
def test_registry_load_consistent():
    """backend 跟 mcp_server load 出的工具集相同"""
    from backend.app.tool_registry import load
    backend_tools = set(load()["tools"].keys())
    # mcp_server 进程跑同样的 load (用 subprocess 模拟)
    assert backend_tools == _mcp_server_tools()

def test_section_affinity_complete():
    """每个工具至少属于一个 section 或 global"""
    for name, meta in load()["tools"].items():
        assert meta.get("sections"), f"{name} 没 sections 标签"

def test_section_chat_stream_includes_focus_hint():
    """/config-chat-stream?section=ui 的 system prompt 含 ui focus hint"""
    resp = client.post("/api/applications/13/config-chat-stream",
                       json={"message": "...", "section": "ui"})
    # 解 SSE 第一帧
    assert "聚焦的配置区域: ui" in first_sse_frame
```

### P1 验收
- Tool registry 加新工具 → 自动派生 4 入口 (test 跑过)
- Section telemetry 看板能看 section_enter top 3

### P2 验收
- Extension section 嵌 code-server, 完整 publish 链路
- 多人并发 advisory lock 拒第二个 session

---

## 12. 回滚矩阵 + Feature Flag (新加 Issue #10)

### 12.1 Feature flags

| Flag | 作用 | 触发 |
|---|---|---|
| `?legacy=1` | ChatPage 走老视图, 不进 5 section | 用户手动 / 窄屏自动 |
| `?ca=sidebar` | ConfigAssistant 用侧栏不浮动 | P1 A/B 测 |
| `?section=...` | 直接进某 section | URL 分享 / 客服引导 |

### 12.2 回滚矩阵

| PR | 上线后撞坑 | 回滚动作 |
|---|---|---|
| PR1 (registry) | 工具 schema 错 | git revert + redeploy backend (~10 min) |
| PR2a (SectionNav 抽组件) | 渲染错 | git revert (不影响主流程) |
| PR2b (ChatPage 接 section) | 切 section 卡死 | Nginx 临时改 `ChatPage` route 用 `?legacy=1` redirect 全量用户 → 等 fix |
| PR2c (system prompt hint) | AI 回复变差 | backend feature flag `CA_SECTION_HINT=false` |
| PR3 (顶部 CTA) | 部署按钮误触发 | 撤销该按钮 UI |
| PR6 (extension 跳走) | 新 tab 没回流 | feature flag `EXT_OPEN_NEW_TAB=false`, 回当前 tab |

### 12.3 一律: PR 上线前给 5% 灰度

backend 加 cookie-based gradual rollout middleware:
```python
@app.middleware("http")
async def feature_rollout(request, call_next):
    user_id = ...
    if hash(user_id) % 100 < settings.new_chatpage_pct:
        request.state.use_new_chatpage = True
```

P0 上线初期 `new_chatpage_pct = 5`, 1 周后看错误率 → 加到 20% → 50% → 100%.

---

## 13. 明确不做 (新加)

P0 / P1 范围内**明确不做**, 防 scope creep:

- ❌ **移动端真 responsive** — P2
- ❌ **多人并发编辑** — P2 (P0 单用户假设, advisory lock 拒第二个)
- ❌ **AI sub-agent 嵌套调用** — P3 (Extension section 不开 sub-agent)
- ❌ **跨应用 chat** — P3 (一个 ChatPage 一个 app_id, 不切应用)
- ❌ **应用模板市场重做** — 跟本 SPEC 无关
- ❌ **v1 coding.py 退役** — codebase 补盘证明还活跃, 暂不动

---

## 14. Telemetry 设计 (新加 Issue #7)

### 14.1 埋点列表

| 事件 | 字段 | 用途 |
|---|---|---|
| `section_enter` | app_id, section, from_section, ts | 看用户进 section 顺序 |
| `section_dwell_ms` | app_id, section, duration_ms | 看哪个 section 占用时间最多 |
| `chat_in_section` | app_id, section, message_count | 看 AI 在哪个 section 用得多 |
| `tool_call` | app_id, section, tool_name, ok | 看每 section AI 真用的工具 (验证 affinity 标签准确性) |
| `section_switch_with_dirty` | app_id, dirty_section | Issue #6 dirty 频率 |
| `legacy_fallback` | app_id, reason, viewport_width | 窄屏 fallback 频率 |
| `extension_jump_out` | app_id, target | 扩展 section 跳走频率 |

### 14.2 仪表盘

- backend `/api/admin/section-telemetry` endpoint, 内置 React 看板 (复用 BuilderDevOpsPage)
- 2 周采集后 review:
  - Affinity 标签是否需要调 (e.g. browser_snapshot 在 ui section 用 80% 还是 logic section 50%)
  - Section 顺序是否符合用户心智

---

## 15. 下一步

### Round 1 完成 ✓
- v1 写好 ✓
- reviewer 审 ✓ — 15 issues
- v2 修订 ✓ — 全部 Critical + Major 都回应

### Round 2 (实现) — 你拍板后启动
1. 你 review v2 + 回 Q1-Q3 3 个待定决策
2. 我 spawn 4 个并行 dev agent (按 PR 拆分独立 worktree):
   - PR1 worktree: tool_registry
   - PR2a worktree: SectionNav 抽组件 (这步可以跟 PR1 并行)
   - PR3 worktree: 顶部 CTA + update_apaas_app_info
   - PR6 worktree: extension section 跳走
3. PR2b 跟 PR2c 必须等 PR1 (registry) + PR2a (SectionNav) 完成才能上, 串行
4. 每 PR 完成后 spawn tester (chrome-devtools-mcp E2E) 验
5. 每 PR 完成后 spawn `ce-correctness-reviewer` cold-start 看代码质量

### Round 3 (P1) — P0 上线后启动
- 看 telemetry / 用户反馈
- 决定 P1 优先级

---

(SPEC v2 — 等你拍板)

---

## 附录: Reviewer issues 全表

(见 §0 v1→v2 Changelog 表)

**Verdict from reviewer**: "v1 可以进 v2 修订, 但 #1/#3/#5/#9/#10 必修"

**v2 状态**: 5 Critical 全修, 7 Major 全回应, 3 Minor 全采纳。
