# 交接：AI 生成 Skill（让桌面 agent 自动造技能）

- 日期: 2026-06-17
- 分支: `feat/desktop-login-mvp`（未并 dev；线上桌面已发 0.2.12）
- 给: 接手「AI 生成 skill」的新会话
- 相关 memory（新会话会自动加载 MEMORY.md 索引）: [[skill_upload_v1_2026_06_17]]、[[desktop_delivery_cockpit_2026_06_16]]、[[desktop_open_local_folder_2026_06_17]]、[[desktop_nearfield_hardening_2026_06_17]]

## 目标

让桌面 ai-builder 的 **agent 自动生成一个 skill**（`SKILL.md` + helper 文件）存进用户技能库——用户靠 AI 攒技能库，而不是只手动上传 zip。这是 SP4 技能库的「AI 创建」那一块（上传/使用已由另一会话做完，见下）。

## 起点：技能库现状（**别重建，复用**）

skill 格式 = **Claude Code 的 SKILL.md 格式**：每个 skill 是一个目录，含 `SKILL.md`（frontmatter `name` + `description`，扁平 key:value，手解析无 yaml 依赖）+ helper 文件（如 `helper.py`）。存在 `data_dir/skills/{platform,user}/<skill-name>/`（platform=种子如 docx-basic/pptx-basic；user=用户的如 mpp-parser/ppt）。

**🔑 关键：落盘原语已经全有**（`backend/app/ai_chat/skills.py` 的 `SkillRegistry`）——「AI 生成 skill」不用碰存储,主要是「生成内容 + 调这些原语」:
- `skills_root()` → data_dir/skills 路径
- `SkillRegistry.scan()` / `.get(name)` → 列/查
- `.create_user_skill(name)` → **建一个用户 skill 目录(含空 SKILL.md 骨架)** ← 生成流程的起点
- `.write_skill_file(name, rel, content)` → 写 SKILL.md / helper 文件
- `.update_skill_metadata(name, description=...)` → 改 frontmatter
- `.list_skill_files / read_skill_file / delete_skill_file / clone_skill`

后端路由 `backend/app/routes/skills.py`: `GET ""`(list) / `POST ""`(upload zip, 校验 SKILL.md frontmatter 必含 name+description、name 不含路径分隔防注入) / `DELETE /{name}`。
前端: `frontend/src/views/SkillLibraryPage.vue`(技能库页) + `SkillWorkspacePage.vue`(skill 编辑器) + `frontend/src/api/skills.ts`。agent 已能 `use_skill`。

## 「AI 生成 skill」要做什么（净增部分）

核心 = 给 agent 一条「把可复用的做法沉淀成 skill」的能力。最小实现可能就是:
1. **一个 agent 工具**(如 `create_skill`/`save_as_skill`): 入参 `name`(ASCII)/`description`/`instructions`(SKILL.md 正文)/可选 helper 文件列表 → 内部调 `SkillRegistry.create_user_skill` + `write_skill_file` 落盘 + 复用 upload 那套 frontmatter 校验。
2. **一个生成流程/提示**: agent 从「当前对话/刚完成的任务」提炼出 name/description/instructions/helper。`description` 要写好(决定以后 use_skill 触发准不准——这正是 skill-creator 的核心 know-how)。
3. **前端入口**: 比如会话里一个「把这次做的存成技能」按钮 / 或 agent 识别到可复用模式时主动建议。

## skill-creator(Anthropic skill)怎么用

产品 skill 跟 Claude Code skill **同格式**,所以 Anthropic 的 `skill-creator` skill 直接对得上。**建议新会话开工先 `Skill` 调一次 `anthropic-skills:skill-creator`**,吸收它关于「好 skill 怎么写」的原则(聚焦单一职责、description 写成「何时用」便于触发、helper 脚本而非长 prompt、可迭代 eval),把这些原则**灌进「AI 生成 skill」的生成提示**里。不一定是产品运行时调 skill-creator,而是用它的方法论指导我们生成出的 skill 质量。

## ⚠️ 协作前提(重要)

技能库这片代码(`routes/skills.py` / `ai_chat/skills.py` / `SkillLibraryPage.vue` / `api/skills.ts`)是**另一个会话**(标题 "AI-builder skills upload and PPT output")在活跃开发的。新会话做「AI 生成」会碰同片代码 → **开工前先跟那个会话对齐分工/确认它当前没在改这些文件**,避免撞车。本分支已叠了多个会话的工作(近场硬伤 + 打开本地文件夹 + skill 上传 + 我刚修的 external prompt)。

## 分支 & 发版状态

- 分支 `feat/desktop-login-mvp`,**未并 dev、未 push**。HEAD 附近 `5c1a7b85`(external prompt 修复),但另一会话可能又提交了(HEAD 一直在动)。
- **线上桌面已发 0.2.12**(公网 account-service `agent.dfy.../account-api/desktop-updates`,minisign 签名,两架构)。含本分支截至发版的全部。发版命令见下。
- ⚠️ 工作树有**并发未提交的 admin-spa/PlatformAdminEmbed 改动**(另一会话/Codex 的)——**别 `git add -A`,只提交自己改的文件**。
- ⚠️ `keys/release.env` 里有平台管理员密码明文(已 gitignore)。发版用 `VERSION=x NOTES=x bash scripts/release-desktop.sh`(它 `source` 或读 ADMIN_USER/ADMIN_PASS)。**密码助手自己不经手,让用户写文件**。

## 开工建议(brainstorm → spec → plan → subagent-driven)

1. 先 `Skill` 调 `superpowers:brainstorming`,把下面问号定下来:
   - **触发**: 用户主动点按钮存 / agent 主动建议 / 命令? 从哪提炼(当前对话 / 用户给描述 / 现有 workflow)?
   - **生成什么**: 只 SKILL.md,还是带 helper 脚本? agent 怎么判断哪部分可复用?
   - **校验**: 复用 upload 的 frontmatter 校验(name ASCII/不含路径分隔/含 name+description)。
   - **存哪**: `data_dir/skills/user/<name>/`(复用 create_user_skill)。
   - **skill-creator 原则**怎么灌进生成提示。
   - **MCP 接入**(skill_upload 的第二份 spec,未做)跟这个的关系——要不要顺带?
2. spec → writing-plans → subagent-driven 执行(跟近场硬伤/打开本地文件夹两轮同样的流程,质量稳)。

## 关键坑(踩过的)

- **skill name 必须 ASCII** + 不含路径分隔(frontmatter 注入越界防护,见 routes/skills.py 校验)。
- **改后端必重启 sidecar/进程**(`run.py` reload=False)才生效。
- **build_user_prompt 的 project_type if/elif 链**: 加新类型必须登记(我刚因 'external' 没登记踩了线上 bug)。若 skill 生成走 coding agent 路径,注意这点。
- **桌面验证法**(不重打包): 起 source sidecar(`PUBLIC_ACCOUNT_BASE_URL="" .venv/bin/python desktop_sidecar.py --port X --data-dir /tmp/y`)+ chrome MCP 连 `127.0.0.1:X`(__DESKTOP__ 已编译进 dist-desktop)。重打包 `scripts/build-desktop.sh`,先 `pkill -f "Builder.app/Contents/MacOS"`。
- **run_python 桌面修复**(`--run-script`)是 skill 执行的依赖,见 [[skill_upload_v1_2026_06_17]]。
- 前端 `vue-tsc` 项目级失效,用 `npm run build:nocheck`;后端全量基线 ~972 passed/1 预存(test_tool_registry)。
