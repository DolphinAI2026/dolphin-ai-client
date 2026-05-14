# vibe-coding 工作流 — Skill

> v1.0 / 2026-05-14
> 给 vibe-coding agent 引用。

---

## 工作流分支

按需求复杂度走不同分支：

```
用户需求
  │
  ├─ < 3 文件 / 一句话能说清    →  直接动手（4.1）
  ├─ 3-15 文件 / 多模块         →  SPEC 简版（4.2）
  └─ 15+ 文件 / 多端 / 复杂业务 →  SPEC 完整版（4.3）
```

---

## 4.1 简单需求直接动手

**示例**：「做个 todo list Vue 项目」

```
1. vibe_create_workspace(template="vue3-vite", project_name="my-todo")
   返回 ws_id (oc_xxx)
2. vibe_get_workspace_status(ws_id) 看脚手架文件
3. vibe_edit_file 改 App.vue 加 todo 逻辑（或 vibe_write_file 整文件覆盖）
4. vibe_run_command("npm install") 装依赖
5. vibe_run_command("npm run dev") 起 dev server
6. vibe_http_check(url="http://localhost:5173", expect_status=200)
7. 告诉用户：「dev server 已启动：http://localhost:5173」
```

---

## 4.2 中等需求 — SPEC 简版

**示例**：「做个用户管理 dashboard，登录 + 用户列表 + 增删改查」

### Step 1：起项目 + 列 task

```
vibe_create_workspace(template="vue3-vite", project_name="user-mgmt-dash")

vibe_todo_write(todos=[
  {"task": "写 PRODUCT.md 跟用户对齐", "status": "in_progress"},
  {"task": "脚手架 + UI 库选型", "status": "pending"},
  {"task": "路由 + 登录页", "status": "pending"},
  {"task": "用户列表页", "status": "pending"},
  {"task": "用户表单（新增/编辑）", "status": "pending"},
  {"task": "API mock 或后端对接", "status": "pending"},
  {"task": "整体跑通验收", "status": "pending"},
])
```

### Step 2：写 SPEC 跟用户对齐

```
vibe_write_file(
  file_path=".specs/PRODUCT.md",
  content="# 用户管理 Dashboard\n\n## 目标\n...\n\n## 用户场景\n...\n\n## 核心字段\n..."
)
```

把内容贴给用户："我先按这个 SPEC 做，OK 走？"

### Step 3：按 task 一个个推进

每完成一个：
```
vibe_todo_write(todos=[更新 status=completed]) 
+ 告诉用户「task X 完成 — 当前进度 3/7」
```

### Step 4：跑通验收

```
vibe_run_command("npm run dev")
vibe_http_check
vibe_run_command("npm run lint")
vibe_run_command("npm run test")  如果有
```

---

## 4.3 复杂需求 — SPEC 完整版

**示例**：「做个团队任务管理 SaaS，含登录 / 团队 / 项目 / 任务 / 评论 / 通知 / 后端 API」

### 完整 .specs/ 结构

```
.specs/
├── PRODUCT.md          # 产品目标 + 用户角色 + 核心场景
├── ARCHITECTURE.md     # 技术栈选型 + 模块划分 + 部署架构
├── DATA_MODEL.md       # 数据库表 + 实体关系
├── API.md              # API 端点 + 请求/响应 schema
├── UI.md               # 主要页面 + 组件拆解
└── TASKS.md            # 拆解的 task 列表（顺序 + 依赖）
```

### 每写一份等用户确认

不准跳过用户 review 一口气把 6 份 SPEC 都写出来 — 工作量大且容易跑偏。

```
1. 写 PRODUCT.md → 给用户 review → 同意
2. 写 ARCHITECTURE.md → review → 同意
3. ...
6. 写 TASKS.md → review → 同意 → 才开始动手
```

### Spec-driven 核心原则

参考 Addy Osmani spec-driven-development MIT v0.6.0（39.1k⭐）：

- **写 SPEC 比写代码花的时间多** — 这是 feature 不是 bug
- **SPEC 是 LLM 友好的需求格式** — 完整 + 可机器解析
- **改 SPEC 比改代码便宜** — 早期发现的问题在 SPEC 阶段免费
- **SPEC 写完直接喂给 agent 一气呵成** — 不再 prompt-by-prompt 引导

---

## 验收标准

完成 = 全部满足：

1. ✓ `vibe_run_command("npm run dev")` 跑得起来
2. ✓ `vibe_http_check` 主页面 200
3. ✓ 核心用户路径手动走通（用 vibe_http_check 或者描述给用户测）
4. ✓ `npm run lint` / `npm run typecheck` 通过（如果配了）
5. ✓ `vibe_todo_write` 全部 task status=completed
6. ✓ README.md 写了怎么跑 / 怎么部署

少一项都不算完成。

---

## 常见陷阱

| 陷阱 | 怎么躲 |
|---|---|
| 不写 SPEC 直接堆代码 → 改起来痛苦 | 复杂需求强制 .specs/ |
| 跑 npm install 失败 | 看 error 是 registry 问题还是依赖冲突；中国用户可能要配 npm 镜像 |
| dev server 起来了但 http_check 报 404 | 检查 baseURL / vite.config.js 里的 base 设置 |
| Vue 2 vs Vue 3 混淆 | 默认 Vue 3，如果用户明说 Vue 2 再切 |
| TypeScript 严格模式报 N 个错 | 先跑 `tsc --noEmit` 看清楚，分批修；急用先 `// @ts-ignore` 标记 |
| port 占用 | dev server 默认 5173/3000，被占了换 5174/3001 |
| 装包慢 | 中国镜像：`npm config set registry https://registry.npmmirror.com` |

---

## 边界铁律

| 需求 | 处理 |
|---|---|
| 「做个跟 aPaaS 集成的看板」 | 拆 — 看板逻辑你做（vibe），aPaaS 部分让用户切 ai-coding agent |
| 「上传到 apaas 平台」 | 不是 vibe 的活，让用户切 ai-coding |
| 「改 aPaaS 应用的某个字段」 | ai-builder 的活 |

转交：
> 「这个需求里 X 部分跟 aPaaS 平台耦合，我这边不能直接做。请你切到 ai-coding agent 处理那部分，我这边只负责 Y 部分（独立可跑的项目）。」

---

## 跟 ai-coding 的核心区别

| 维度 | ai-coding | vibe-coding |
|---|---|---|
| Workspace 前缀 | `1_xxx` | `oc_xxx` |
| 工具集 | 30+ 个（含 aPaaS 工具） | 11 个 vibe_* |
| 技术栈 | Vue 2.7 + Element UI + papaas 4.1.1-rc + Java 8 | 任意（默认 Vue 3 + Vite + TS） |
| 最终产物 | apaas 自开发模版包 zip（挂到应用） | 独立可跑的项目（git 仓库） |
| 部署 | 上传 apaas 平台 → 自开发模版包 → 应用挂载 | 自由 — docker / pm2 / vercel ... |
