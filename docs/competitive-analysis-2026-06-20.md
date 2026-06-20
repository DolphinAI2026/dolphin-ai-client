# 睿鲸 AI Builder Desktop 竞品深度分析(vs Codex / Claude Code / 腾讯 WorkBuddy)

> 2026-06-20。方法:9-agent workflow —— 4 个 grounding agent 读 ai-builder 真实代码(壳/sidecar/更新/登录、coding 内核、工作区 UX、aPaaS 领域护城河),3 个 agent 做竞品画像(Codex/Claude Code 知识+web 核实,WorkBuddy 重点 web 调研),1 个综合 + 1 个对抗核验官专门挑错(防夸大 ai-builder、防臆测竞品)。下文 severity 与措辞**已吃进对抗核验的修正**,不是综合 agent 的原话。

## 一句话判断

ai-builder 不该跟 Codex / Claude Code / WorkBuddy 拼通用 coding 内核(子代理并行、动态规划、代码库语义索引、云端 agent、生态规模——平台级产品用海量资源+模型训练堆出来的,追不平也不必追,目标用户是低代码配置型用户和交付团队,不是要在任意仓库跑几十轮重构的工程师)。**通用层做减法守及格线,领域层 + 交付驾驶舱做加法建壁垒。** 先清「出不了门」的硬门槛(Apple 签名/公证、私有化/Windows),再把交付标准化层从 PPT 立成 MVP。

## 维度差距表(severity 已按对抗核验修正)

| 维度 | ai-builder 相对三方 | 程度 |
|---|---|---|
| 1 Agent 内核/coding loop | 固定流水线(场景→SPEC→codegen),无动态 plan、无子代理并行、轮数封顶 25/30。有意取舍,非买单点 | moderate |
| 2 上下文工程 | 压缩分层扎实(轮内+出轮 compact 落库+413 重试),但代码库检索=纯正则 grep 截断、无跨会话项目记忆 | moderate |
| 3 模型与扩展 | 128 MCP 工具 + tool_registry 单一真相源 + ToolSearch + 按租户隔离 + skill 库。已对齐 Claude Code 范式 | minor(够用) |
| 4 工作区/IDE | git 改动基线机制是亮点,但无内置终端、编辑器是死代码、新旧工作区双轨没收口 | moderate |
| 5 原生桌面 | 薄壳+sidecar+自动更新+信任边界都干净,但**无 Apple 签名/公证**=撞 Gatekeeper | **critical** |
| 6 运行验证 | 运行态前端自愈(CDP 抓错回灌)是真亮点,**但只在 dev 模式,打包态因排除 playwright 全降级** | moderate |
| 7 领域专精 | aPaaS 私有协议逆向 + 0-1 生成 + 四配置面板。三方全缺席 | **ahead(护城河)** |
| 8 协作/交付 | git 托管+后台任务有,但交付驾驶舱(脊柱/闸口/交付物模板)零代码=PPT。两头空窗 | major |
| 9 安全沙箱 | 身份/密钥/信任边界严谨,但 **run_command 裸跑 shell,无 OS 级沙箱**(可逃逸工作区) | major |
| 10 生态/社区 | 封闭垂直产品,无公共市场。但 to-B 不必比 | minor |

## 逐维度详情

**1 Agent 内核** — Codex/CC=leading(子代理嵌套、plan、云端并行);WorkBuddy=strong(Craft/Plan/Ask 三模式)。ai-builder 双 agent 架构(BaseAgent 13 hook+状态机+suspend/resume),但规划是固定流水线、无 fan-out、自主深度被轮数上限+nudge 催写压短。**真正的 major 是 Builder 侧还没收口到 BaseAgent(无跨请求恢复)这个工程债**,而非通用深度(那是有意取舍)。建议:轻量 plan-mode(brainstorm 出可见 TODO)+ Builder 收口 BaseAgent。子代理并行靠后。

**2 上下文工程** — CC=leading(auto compact/microcompact + CLAUDE.md 分层记忆 + checkpoint/rewind);WorkBuddy=strong(MEMORY.md+每日日志+30天蒸馏+Checkpoints,口径未独立验证)。ai-builder 压缩扎实,但**代码库检索是纯 Python os.walk+正则 grep(截 200 命中/5000 字符),落后一个量级**;无跨会话项目记忆。建议:ripgrep 打包进 sidecar(立竿见影)+ 项目级 PROJECT.md 记忆。语义/向量索引 ROI 低,延后。

**3 模型与扩展** — 三方都 leading。ai-builder 这维度基本对齐:tool_registry 单一真相源、ToolSearch 渐进披露、按租户模型隔离、reasoning/MiniMax think 剥离、文件系统 skill 库 + AI 生成 skill。差距在生态规模(无公共市场)和插件版本化打包,非内核。建议:别大投;把领域 skill 沉淀成可分发 skill 包(喂交付技能库),做内部 SkillHub 雏形。

**4 工作区/IDE** — Codex/CC=strong/leading(IDE 扩展+内置终端+深度 git+worktree)。亮点:**git 基线改动机制**(把 git 当透明改动数据库,checkpoint 让本轮改动语义恒定+M/A/D 徽标+逐文件 diff+接受变更),review 体验直追 Cursor;且四配置面板反超 WorkBuddy/Codex。缺口:无内置终端、CodeMirror 是死代码、Plan 面板 placeholder、新旧工作区双轨未收口(用户实际落在弱的旧页)。建议排序:① 双轨收口(零新功能高收益)② 接已就绪的实时日志 SSE ③ 内置终端(配沙箱)。

**5 原生桌面** — CC=leading(签名+公证+stapled+多形态),是 ai-builder 对标标杆。ai-builder 壳/sidecar/更新/信任边界都干净,但**Apple 代码签名+公证完全缺失=企业交付硬门槛**(用户撞 Gatekeeper 必须右键/xattr);离线登录不可用、仅 macOS、首启 health 轮询 60s 超时静默退出。建议:立刻办 Developer ID 证书做签名+公证(纯流程/花钱,无技术风险,ROI 最高)。

**6 运行验证** — Codex=strong(云端跑测试迭代开 PR)。亮点:**运行态前端自愈 `drive_coding_with_autofix`**(build + 无头 CDP 抓 console/network → fix_hint 回灌 + 同错收敛),比 Codex/CC 默认不带运行态抓错更进一步——**但仅 dev 模式;打包态 excludes playwright 导致 CDP 全降级(capture_available=false),正是交付形态失效**。且无单测执行回路。建议:打包态内置 headless Chromium(SP3)保住自愈 + cli 模板补 preview harness 治白屏 + 加 npm test/pytest 通用回路。

**7 领域专精(护城河)** — 三方 absent。ai-builder 深护城河:`apaas_client.py` 2901 行命中 108 私有端点 + 1418 行流程翻译器(simpleRule op 码全抓包实证)+ 6 文档 parser + 0-1 文档生成应用(经多轮真实生产 bug 打磨)+ 四配置面板只读深链 + 应用体检记分卡 + 双 ID 鉴权/401 自愈/业务事件 Python 规范逆向知识。**风险:护城河深但窄,强绑单一闭源得帆 aPaaS,换平台则全废,可迁移性低=天花板。** 建议:主力压这里;中期把对 aPaaS 的硬编码抽象成平台适配层(端点/payload/鉴权做成 driver),从「深而窄」变「深而可复制」。

**8 协作/交付** — 三方 strong(云端 agent/PR/定时/团队审计;WorkBuddy 企业版项目流水线+上下文交接,口径未独立验证)。ai-builder:GitLab/GitHub 双托管 + 后台任务 + agent trace Phase1 埋点;**但交付驾驶舱核心(脊柱/阶段闸口/交付物模板/交付技能/知识库 SP2-SP5)零实体零路由=PPT**。两头空窗:通用协作不如三方,自己的差异化交付层还没动工。建议:别拼通用云端协作,把 SP2-SP5 从 PPT 变 MVP(交付项目实体+阶段闸口+交付物模板,复用 skill 库当交付技能)——产品命门,应优先于追平通用层。

**9 安全沙箱** — Codex=leading(三档 sandbox + OS 级强制 Seatbelt/Landlock+seccomp/Windows Sandbox + 默认断网 + 多档审批);CC=leading(参数级权限+破坏性命令拦截)。ai-builder 身份/密钥/信任边界严谨(本地 sidecar 票据与共享后端 issuer 白名单硬隔离 + fail-fast + federation 禁提权 + per-instance 高熵密钥 0o600 + 仅绑 127.0.0.1),**但 run_command 是裸 create_subprocess_shell,命令本身无约束(cd/绝对路径可逃逸工作区)**。建议:桌面态给 run_command 套 macOS sandbox-exec(限可写目录=工作区+默认断网+破坏性命令二次确认),直接抄 Codex。客户机跑 AI 命令前的安全必修课。

**10 生态/社区** — 三方 leading。ai-builder 封闭垂直产品,内部文档厚但无公共市场。to-B 不必比。建议:精力收敛到内部——做交付团队的 skill/知识库市场(与维度 8 共建)。

## 被对抗核验戳破的「别自己骗自己」

1. **运行态自愈别当卖点吹** — autofix 只在 dev 模式有效,打包成 .app 后 CDP 全降级。亮点恰恰在「真正交付给客户的那个形态」失效,承诺只兑现一半。
2. **交付驾驶舱目前是 PPT** — SP2-SP5 零实体零路由,只有设计稿,不能算护城河,只能算「应做未做」。现在桌面端本质=「把在线版装进了 .app」。
3. **WorkBuddy 是 medium 可信度** — 腾讯 CodeBuddy 团队 2026-03 发的「AI 原生桌面智能体工作台」,内核跟 Claude Code 高度同构(MEMORY.md 记忆+30天蒸馏、Checkpoints、Craft/Plan/Ask、SKILL.md+SkillHub 市场、企业版项目流水线)已成体系。具体数字(7 万技能/3000 万下载、Craft<10 分钟)是公开口径未独立验证。结论:**你一直在学的 Claude Code 范式,WorkBuddy 已经做齐了。**

## 比工程差距更要命的战略盲点(对抗核验补,最值钱)

工程差距(签名、ripgrep、沙箱)都能修。真正该担心的:

- **私有化/信创部署** — 客户是国产低代码(得帆 aPaaS)交付,大概率要内网/私有化,但登录默认走公网 federation、核心 LLM 走 omnigate 公网网关、离线登录不可用。对央国企客户,这比 Apple 签名更可能是真实卡点。
- **只有 macOS,没有 Windows** — 国产 to-B(尤其政企)主力是 Windows + 可能信创环境。这是和目标市场的根本错配,不是「跨平台缺失一句话」。
- **成本账没人算** — 大仓导航靠 LLM 盲读(无索引)+ 固定多轮流水线,每生成一应用烧多少 token vs 竞品,是客户续费关键,目前空白。
- **数据合规/可审计** — 客户业务数据经第三方 LLM 网关 + 生成代码在客户机执行(run_command 无沙箱),合规/数据驻留/审计是央国企硬性准入。
- **最大威胁不是这三家,是得帆自己** — Codex/CC/WorkBuddy 都不碰 aPaaS,威胁不到。能一夜清空护城河的是**得帆 aPaaS 自身(或其生态)内建 AI 配置助手**。护城河深而窄、强绑单一平台,这才是存亡级风险。

## 行动排序(三档,别混着排)

**A. 「出不了门」硬门槛(先清)**
- Apple Developer ID 签名 + 公证 + stapler。纯流程+花钱,零技术风险,ROI 最高,不签名等于交付不出去。
- 私有化/离线登录开关 + Windows 打包评估。看客户结构,可能比签名还前置。

**B. 护城河加法(押资源)**
- 交付标准化层 SP2-SP5 从 PPT 变 MVP(交付项目实体 + 阶段闸口 + 交付物模板,复用 skill 库)。唯一差异化卖点,优先于追平通用层。
- aPaaS 硬编码抽象成平台适配层(driver 化端点/payload/鉴权),对冲得帆自建风险。

**C. 通用层守及格线(低成本补,别多投)**
- run_command 套 macOS sandbox-exec(限可写目录+默认断网+破坏性命令二次确认)。
- ripgrep 替正则 grep + 项目级记忆文件(对标 CLAUDE.md)。
- 新旧工作区双轨收口 + 接已就绪的实时日志 SSE(零新功能)。
- 打包态内置 headless Chromium(SP3)保住 autofix 不降级。
- 内置终端、轻量 plan-mode、Builder 收口 BaseAgent —— 靠后。

## 附录:护城河证据(file:line,grounding 实读)

- `backend/app/apaas_client.py`(~2901 行,108 私有端点)+ 流程翻译器(~1418 行,simpleRule op 码抓包实证)
- 0-1 文档生成:6 文档 parser + 标准 6 章节 markdown→解析六域→草稿→部署 aPaaS
- 桌面壳:`src-tauri/src/lib.rs:45-138`(pick_free_port/wait_healthy/kill_sidecar_deep)、`backend/desktop_sidecar.py`、`backend/app/runtime.py:35-83`(is_frozen≠is_desktop 门面)
- 自动更新:`scripts/release-desktop.sh`、`backend/app/routes/desktop_updates.py:26-129`、`tauri.conf.json:32-37`(minisign pubkey)
- 信任边界:`backend/app/auth.py:97-99/221-231`、`backend/app/routes/desktop_auth.py:38-92`、`backend/app/desktop_accounts.py`
- 打包态降级:`docs/handoff-2026-06-18-desktop-run-debug.md §4`、`backend/ruijing-sidecar.spec:94-97`(excludes playwright)

**竞品画像来源**:Codex — openai.com/index/introducing-codex, developers.openai.com/codex/cli;Claude Code — code.claude.com/docs, platform.claude.com/docs/managed-agents;WorkBuddy — codebuddy.cn/docs/workbuddy/Overview, cloud.tencent.com/developer/article/2638618 & 2656859(medium 可信度,具体数字未独立验证)。
