# 桌面端 Skill 上传 v1 设计（直出 PPT/Word）

> 状态：设计已与用户确认，待评审 → writing-plans。
> 日期：2026-06-17　分支基线：feat/desktop-login-mvp
> 关联方向：[[desktop_delivery_cockpit_2026_06_16]] 的 SP4「技能库」具体化（v1，桌面）。

## 1. 背景与目标

ai-builder 的 AI 助手（unified `run_agent`，走 omnigate / gpt-5.5）目前只预设了低代码相关工具，产物只能写文本（md/py/html/…，存 `ai_chat_artifacts.content` 文本字段）。交付过程刚需「直出 Word / PPT」做不到，也没有「像 Claude Desktop 那样上传自定义能力」的入口。

本 spec 让**桌面端**能上传/使用「能跑脚本的 skill 包」，第一个落地场景＝**上传一个品牌 PPT/Word skill，对话里被引用后直接产出可下载的 .pptx/.docx**。全程不改 ai-builder 代码——「会写什么格式」从代码搬到用户可上传的 skill 里。

成功判据：用户把一个 `SKILL.md + helper.py + template.pptx` 的 zip 传进桌面端 →「技能库」里出现 → 对话里说「导成 XX 品牌 PPT」→ 模型自动（或 @ 强指）引用该 skill → 跑脚本 → 右侧出现可下载的 `.pptx`。

## 2. 已确认的关键决策

| # | 决策 | 取值 |
|---|------|------|
| 1 | v1 能力边界 | **能跑脚本**（直出 pptx/docx），含底座：run_python 桌面修复 + 二进制产物 |
| 2 | 包格式/录入 | **SKILL.md + 文件 打 zip 上传**（Claude Code 风格，可复用现有/社区 skill） |
| 3 | 作用域/分发 | **桌面本地 + 平台预置下发**；用户也能本地加私有 skill |
| 4 | 对话引用方式 | **自动渐进披露 + @ 可强指** |
| 5 | 存储/运行架构 | **路线1：文件系统 skill 库**（不进 DB；云端将来另做存储层） |
| 6 | 代码执行信任门 | **透明不拦截**（对齐 open-local-folder 姿态；详情页可见会跑哪些脚本） |

## 3. 非目标（YAGNI，本 spec 不做）

- 云端多租户的 skill 上传 / 沙箱执行 / 共享（**云端另开 spec**；v1 仅桌面）。
- 用户↔用户 skill 互享、租户级共享、skill 市场。
- skill 版本管理 / 回滚 / 依赖声明、`allowed-tools` 强制白名单（v1 只读 instructions，不强制约束工具集）。
- AI 自动生成 skill 包。
- MCP 外部服务器接入（**第二份 spec**）。
- 把现有 `ConfigAssistantSkill`（AI 自学的文字流程，DB 存）与上传 skill 包合并——两者并存、概念不同，v1 不动它。

## 4. 安全前提（为什么 v1 桌面是安全的）

skill 能跑任意 Python = 在执行机上运行用户代码。**桌面 = 单用户、自己的机器、可信**，等同 Claude Desktop 跑本地 MCP/skill，可接受。**云端多租户不可信**——但 v1 **没有**云端 skill 上传入口（SkillRegistry 只扫桌面本地目录，云端目录不存在 → 空集 → 整套功能在云端自动 no-op）。因此 v1 不引入新的云端攻击面。云端开放须配沙箱，留给后续 spec。

## 5. 架构总览

```
用户上传 zip ─► /skills 端点校验+解压 ─► data_dir/skills/user/<name>/
平台预置 ──────────────────────────────► data_dir/skills/platform/<name>/  (随包发/将来拉)
                                                 │
                              SkillRegistry.scan() 解析 frontmatter
                                                 │  [{name, description, dir, source}]
run_agent 组 prompt ─► 注入 skill 清单(name+desc, 渐进披露)
                                                 │
用户说「导成XX PPT」/ @指定 ─► 模型调 use_skill(name)
   └─ 读完整 SKILL.md 进上下文 + 拷 skill 文件到会话 workspace ─► 返回正文+文件清单
                                                 │
模型按手册调 run_python(跑 helper, 桌面用冻结解释器+已打包的 python-pptx/docx)
   └─ 产出 workspace/xxx.pptx ─► 模型调 save_binary_artifact(file) 登记
                                                 │
前端产物面板 ─► GET .../artifacts/<f>/download 流式二进制下载
```

组件清单（新增 / 改造）：

1. **SkillRegistry**（新）— 扫描 skill 目录、解析 frontmatter。
2. **skill 清单注入**（改 agent.py）— 渐进披露。
3. **`use_skill` 工具**（改 tools.py）— 展开 SKILL.md + 落文件到 workspace。
4. **run_python 桌面修复**（改 tools.py + desktop_sidecar.py）。
5. **二进制产物**（改 model + tools.py + routes + 前端）。
6. **`/skills` 端点 + 「技能库」前端页 + @ 引用**（新/改）。
7. **平台预置分发**（v1 随包发）。

## 6. 数据 / 存储模型

### 6.1 Skill 包目录布局（不进 DB）
桌面 `data_dir` = `~/.ruijing-builder`（见 `desktop_sidecar.py` build_env；可由 `--data-dir` 改）。

```
data_dir/skills/
  platform/<skill-name>/   # 平台预置, 只读
  user/<skill-name>/       # 用户上传, 可删
```

每个 `<skill-name>/` 至少含 `SKILL.md`：

```markdown
---
name: 鲁信供应链POC-PPT
description: 按鲁信品牌生成 POC 演示 PPT；输入需求要点，输出 .pptx
version: 1            # 可选
---
（正文：怎么一步步做 —— 版式规则、调用哪个 helper、产出文件名约定…）
```

同目录可带任意 helper 脚本 / 模板 / 资源（`helper.py`、`template.pptx`、`assets/`）。**格式与 Claude Code skill 一致**，社区/现有 skill 可直接丢进来。

skill 目录根由一个 helper 解析：`DESKTOP_MODE`/frozen 时取 `data_dir/skills`；否则取环境变量 `RUIJING_SKILLS_DIR` 或仓库内 dev 目录（便于本地开发/测试）。目录不存在 → 返回空集，全链路 no-op。

### 6.2 `AIChatArtifact` 扩展（支持二进制）
当前 `content: BigText` 只能存文本。新增三列（参照 `AIChatAttachment.file_path` 既有模式）：

| 列 | 类型 | 说明 |
|----|------|------|
| `storage` | String(10), default `"text"` | `"text"`＝沿用 content；`"file"`＝二进制落盘 |
| `file_path` | String(1000), nullable | `storage="file"` 时指向 `session.workspace_dir` 下的文件 |
| `size_bytes` | BigInteger, default 0 | 文件大小 |

迁移：项目**无 alembic**，靠 `Base.metadata.create_all`（`database.py:63`）建表——但 create_all **不会给已存在的表加列**。故：新装/空库（含每台新桌面）自动带新列；**已有库**需在 `database.py` 启动初始化里加幂等 `ALTER TABLE ai_chat_artifacts ADD COLUMN ...`（沿用该文件 line 170/187 既有的「确保列/索引存在」模式，SQLite 与 MySQL 都要兼容）。三列均带默认值、向后兼容（老产物 `storage` 默认 `"text"`）。文本产物路径完全不变。

## 7. 组件详细设计

### 7.1 SkillRegistry（新文件 `backend/app/ai_chat/skills.py`）
纯文件系统读取，无状态、无 DB：

- `skills_root() -> Path | None`：解析 skill 根目录（见 6.1），不存在返 None。
- `scan() -> list[Skill]`：遍历 `platform/` + `user/`，每个子目录读 `SKILL.md` frontmatter，得 `Skill(name, description, dir, source, files)`。frontmatter 缺 `name`/`description` 的包跳过并 `log.warning`（坏包不炸全局）。`name` 去重：user 覆盖 platform 同名（本地优先）。
- `get(name) -> Skill | None`：按 name 取。
- `read_skill_md(name) -> str`：读完整 SKILL.md 正文（去 frontmatter）。

`Skill` 是轻量 dataclass。扫描每轮 agent turn 调一次（量小、纯本地 IO），不缓存（保证上传后即时可见）。

### 7.2 Skill 清单注入（改 `backend/app/ai_chat/agent.py`）
位置：`run_agent` 组 system_prompt 处（现 line ~597-600 拼 `build_app_context_block` 之后，**与 app 锁定无关、无条件注入**——Word/PPT skill 在自由会话也要可用）。

新增 `build_skill_manifest(skills) -> str`（放 skills.py 或 tools.py，与 `build_deferred_manifest` 同风格）：

```
## 可用技能(Skill)
需要某个技能时, 先调 use_skill(name) 读取它的完整说明再按其执行:
- 鲁信供应链POC-PPT: 按鲁信品牌生成 POC 演示 PPT；输入需求要点，输出 .pptx  [平台预置]
- 我的周报模板: ...  [本地上传]
```

仅在 `scan()` 非空时注入（空集不加任何文本）。这就是渐进披露：平时只见 name+desc，不吃完整手册 token。

### 7.3 `use_skill` 工具（改 `backend/app/ai_chat/tools.py`）
加进 `TOOL_SCHEMAS` + `TOOL_HANDLERS`。因 `CORE_TOOL_NAMES` 自动含全部 base 本地工具名（`_BASE_LOCAL_NAMES`），use_skill 自动进核心集、每轮可用，无需额外接线。

- schema：`use_skill(name: string)`，description 说明「读取某技能的完整说明并把它的文件准备到工作目录，之后按说明执行」。
- handler `execute_use_skill(args, session, db)`：
  1. `SkillRegistry.get(name)`；找不到回可读错误（列出可用 skill 名）。
  2. 把该 skill 目录内**除 SKILL.md 外的文件**拷到 `session.workspace_dir`（确保 `workspace_dir` 已初始化，见 ai_chat.py `_ensure_workspace`）。同名冲突放进子目录 `skill_<name>/` 隔离，避免覆盖会话已有文件。
  3. 返回：完整 SKILL.md 正文 + 「已就绪文件清单（含在 workspace 的相对路径）」+ 一句「这些脚本将由 run_python 在本机执行（来源：平台预置/本地上传）」（透明门）。

### 7.4 run_python 桌面修复（改 `tools.py` + `desktop_sidecar.py`）
**根因**：`execute_run_python`（tools.py:325）用 `sys.executable -c code`；桌面 PyInstaller onefile 下 `sys.executable` = sidecar 二进制（不是 python 解释器），且它只认 `--port/--data-dir` → `unrecognized arguments: -c`。

**修法**：让 sidecar 二进制自己能当解释器用（它内部就是 python + 已打包 pandas/openpyxl/python-pptx/python-docx）。

1. `desktop_sidecar.py` `main()`：argparse 增 `--run-script <path>`。**在 build_env / 起 uvicorn 之前**判断：若提供 `--run-script`，用 `runpy.run_path(path, run_name="__main__")` 执行该脚本（继承父进程给的 cwd / stdout / stderr），执行完 `sys.exit(0)`；异常则打印 traceback 到 stderr、`sys.exit(1)`。**不**起 uvicorn、**不**建 DB。
2. `execute_run_python`：用 `getattr(sys, "frozen", False)` 判断是否冻结态：
   - 冻结（桌面）：把 code 写到 `workspace/.run_<uuid>.py`，`create_subprocess_exec(sys.executable, "--run-script", tmp, cwd=workspace, ...)`，跑完删临时文件。
   - 非冻结（dev/云端）：维持现状 `sys.executable -c code`。
   - 其余（30s 超时、kill、stdout/stderr 捕获、8000 字符截断）不变。

这样 skill 的 helper 能直接 `import pptx`（已在 ruijing-sidecar.spec 打包，前一轮已修 excludes）。

### 7.5 二进制产物（改 model + tools.py + routes + 前端）
1. **model**：6.2 的三列。
2. **新工具 `save_binary_artifact`**（tools.py，进 CORE）：`save_binary_artifact(source_path: string, filename?: string)` —— 把 skill 脚本刚写进 workspace 的文件登记为可下载产物：校验 `source_path` 在 `workspace_dir` 内（防越界）、文件存在；写一条 `AIChatArtifact(storage="file", file_path=…, format=后缀, size_bytes=…, version=同名+1)`；返回确认 + 触发右栏刷新（沿用 write_artifact 后的 `artifact_created` SSE，见 agent.py）。
3. **下载端点**（routes/ai_chat.py 新增）：`GET /sessions/{id}/artifacts/{filename}/download` —— `storage="file"` 用 `FileResponse` 流式返回（MIME 由后缀猜，pptx/docx/xlsx 给正确类型 + `Content-Disposition: attachment`）；`storage="text"` 回退返回 content（保持现有文本下载可用）。
4. **前端**：产物面板「下载」按钮——文本沿用现有 blob；`storage="file"`（`_artifact_to_dict` 透出 `storage`/`size_bytes`）走新下载端点。

### 7.6 `/skills` 端点 + 「技能库」页 + @ 引用
- **后端**（新 router `backend/app/routes/skills.py`，挂 `/skills`）：
  - `GET /skills` → `SkillRegistry.scan()` 列表（name/description/source/files）。
  - `POST /skills`（multipart zip）→ 校验：解压后存在合法 `SKILL.md`（有 name/description）；安全解压（拒绝 `..`/绝对路径，防 zip slip）；落 `user/<name>/`；返回登记结果。
  - `DELETE /skills/{name}` → 仅允许删 `source="user"`；platform 只读拒删。
- **前端**：新增「技能库」设置页（主 frontend，桌面壳设置入口）——列平台预置 + 我的；用户 skill 可上传 zip / 删；点开可看 SKILL.md + 文件清单（透明门）。
- **@ 引用**：`UnifiedChatComposer`（前一轮刚加过拖拽）加 `@` 选单列 registry skill；选中 → 在该条消息注入「本次请使用 skill `<name>`」前缀指令，引导模型先 `use_skill`。

### 7.7 平台预置分发
- **v1**：平台预置 skill 随桌面包发——打进默认 `skills/platform/`（构建脚本把仓库内 `desktop/preset-skills/` 拷进包），随你已有的桌面自动更新升级。
- **v1b（后置，可选）**：从平台端点拉 skill 包到 `skills/platform/`，复用桌面自动更新/federation 的拉取通道，不必重发整包。

## 8. 数据流（端到端示例）

1. 用户在「技能库」上传 `鲁信供应链POC-PPT.zip`（SKILL.md + helper.py + template.pptx）→ 落 `user/鲁信供应链POC-PPT/`。
2. 对话：「把这份 POC 需求导成鲁信品牌 PPT」。
3. run_agent 注入 skill 清单 → 模型识别 → `use_skill("鲁信供应链POC-PPT")`。
4. handler 读 SKILL.md + 把 helper.py/template.pptx 拷进 workspace，返回手册+路径。
5. 模型按手册 `run_python`（桌面走 `--run-script`，`import pptx` 可用）→ 生成 `workspace/鲁信供应链POC.pptx`。
6. 模型 `save_binary_artifact("鲁信供应链POC.pptx")` → 登记 file 产物 → 右栏刷新。
7. 用户点下载 → `/artifacts/鲁信供应链POC.pptx/download` 流式拿到 .pptx。

## 9. 错误处理
- 坏 skill 包（无 SKILL.md / frontmatter 缺字段）：扫描时跳过 + warning；上传时直接拒绝并回可读原因。
- zip slip / 越界路径：上传解压、`save_binary_artifact` 的 `source_path` 都做 workspace/目标目录边界校验。
- run_python 桌面执行失败（缺库/脚本报错）：stderr 原样回模型（沿用现有捕获），不吞。
- use_skill 找不到 name：回错误并列出可用 skill。
- 云端无 skills 目录：registry 空、不注入、use_skill 不可触发——静默 no-op，不报错。

## 10. 测试策略
- `SkillRegistry.scan()`：正常包、缺字段坏包跳过、user 覆盖 platform 同名、目录不存在返空。
- `execute_use_skill`：展开返回 SKILL.md 正文、文件拷进 workspace、找不到 name 报错。
- run_python 桌面分支：monkeypatch `sys.frozen=True` + 桩 `sys.executable`，断言走 `--run-script`；`desktop_sidecar --run-script` 真跑一个临时脚本验证 stdout（非冻结也能测 runpy 路径）。
- 二进制产物：`save_binary_artifact` 越界拒绝、正常登记 `storage="file"`；下载端点对 file/text 各返正确响应 + MIME。
- `/skills`：上传合法/非法 zip、zip slip 拒绝、删 user 成功 / 删 platform 拒绝。
- 端到端：一个最小真 PPT skill（python-pptx 写 1 页）在**本地 dev 解释器**跑通 use_skill→run_python→save_binary_artifact→download。
- 诚实边界：桌面冻结态的真验证仍需 macOS `scripts/build-desktop.sh` 重打包后实测（CI/人工），本环境给不了。

## 11. 文件改动落点
- 新增 `backend/app/ai_chat/skills.py`（SkillRegistry + manifest）。
- 新增 `backend/app/routes/skills.py`（/skills CRUD），并在 main.py 挂载。
- 改 `backend/app/ai_chat/tools.py`：`use_skill` / `save_binary_artifact` schema+handler；`execute_run_python` 冻结分支。
- 改 `backend/desktop_sidecar.py`：`--run-script` 子命令。
- 改 `backend/app/ai_chat/agent.py`：注入 skill 清单。
- 改 `backend/app/models/ai_chat.py`：`AIChatArtifact` 加 storage/file_path/size_bytes（+迁移）。
- 改 `backend/app/routes/ai_chat.py`：`_artifact_to_dict` 透出 storage/size；新增 download 端点。
- 前端：新增「技能库」页 + api；`UnifiedChatComposer` 加 @ 选单；产物面板二进制下载。
- 预置 skill：`desktop/preset-skills/`（v1 一个 PPT、一个 Word 试点）+ 构建脚本拷贝。
- 测试若干（见 §10）。

## 12. 分期
- **v1**：§7.1–7.6 全部 + §7.7 的 v1（随包预置）。交付物＝桌面端能上传 skill、对话引用、直出可下载 PPT/Word。
- **v1b（可选后置）**：平台端点动态拉 skill。
- **后续独立 spec**：① 云端 skill（沙箱 + 多租户 + 共享）；② MCP 外部服务器接入。
