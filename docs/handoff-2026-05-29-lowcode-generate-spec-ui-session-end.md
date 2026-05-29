# 交接 — 2026-05-29 低代码 generate / SPEC / UI 修复 session

> 接手第一眼：本文件 + `git log --oneline origin/local/ui-redesign-2026-05-20 -30`。
> 分支 `local/ui-redesign-2026-05-20` **已 push origin**，HEAD = `5fa71d5`。
> 工作树干净。preview 托管 backend(8000)+frontend(5173)。

## ⚠️ 头号注意：本分支是「共享」的
这条分支上**同时有另一条并行 session 在做 Vibe Coding 删除 / ai-coding 重构**（commit 里
那串 `refactor(...) (vibe 删除 N/n)` + `feat(ai-coding) ①/⑧` + `4add5d5 docs: handoff
2026-05-29 — Vibe 砍掉` 都是它的，不是本 session）。两条线交织在同一分支。

**铁律**：在这分支提交**一律用 `git commit <path1> <path2>`（路径限定）**，**绝不要裸 `git commit`/`git add -A`**——
我这 session 第一次裸 commit 把对方 16 个 staged 删除文件一起卷进去了（已 `reset --soft` 拆开重提）。

## 本 session 干了啥（11 个 commit，全是低代码线，跟 vibe 删除无关）
按主题：

### A. 大文档生成的两个根因（用户实测 inn-idm 残缺/重复）
- `c772cf1` **appCode = 应用身份**：同租户同 app_code 撞了 → 复用同一应用 + 按 code 增量合并
  config（模型/表单/角色/字典/权限），**永不建 -v1**。两条创建路径都改了：`auto-create`
  + `deploy-from-artifact`（`backend/app/routes/applications/__init__.py`，加了
  `_extract_preview_data` / `_merge_preview_data`）。配额改成仅真正新建时校验。
- `4e243bc` **超大文档原样喂 generate**：AI-chat agent 老路径 `read_attachment`(截断 3 万字)
  + `write_artifact`(LLM 重抄) 把 33 万字文档摘掉只剩残篇。新增本地工具
  `create_artifact_from_attachment`（`backend/app/ai_chat/tools.py`）服务端整篇原样复制进
  artifact；agent prompt（`backend/app/ai_chat/agent.py`）改用它 + 禁止给 appCode 加 -v1/拆批。
  实测真 33 万字 → artifact 一字不差 → `parse_document` 还原 **132 模型 / 42 表单**。

### B. 进度/状态显示真实化
- `a1965e4` **进度面板按 apaas 真实对象重建**（`backend/app/routes/generation_steps.py`）：
  修「服务端 generate-run 跑完面板仍显 1/182」。completed→全标完成；进行中/失败→查 apaas
  真有的模型/角色/字典/菜单标完成（8s 进程缓存）。
- `040b718` **failed/生成中 应用别显示成"草稿"**（`section_content.py` publish-status +
  `ChatPage.vue` 状态 chip）：真实态 failed→"生成失败"(apaas 已建一部分→"部分失败")+重试按钮；
  generating→"生成中…"。

### C. apaas 可靠性
- `da001c4` **读接口撞 401 自动重登重试**（`backend/app/coding/apaas_tools.py` 加
  `_relogin_apaas_env` + `call_apaas_with_relogin`；`section_content.py` `_safe_call_mcp_tool`
  + 3 个直调 client 的读接口都接）。token 过期用户无感。实测改坏 token → 两条路径都自愈。

### D. #2「上传新 md 更新已有应用」入口（完整 diff/审核管线早已存在，只是入口是孤儿）
- `8ffc202` 顶部工具栏加「更新文档」按钮接回孤儿 `triggerDocVersionUpload`（后端
  `upload-doc-version` → diff → change_plan → 审核 → execute 全在，走的是好解析器 `parse_document`）。
- `c4dc49c` 用户反馈：挪到右侧**配置助手面板**顶部 ⬆ 图标（emit `upload-doc` → ChatPage）。
- spec 文档：`docs/superpowers/specs/2026-05-29-doc-upload-update-entry-design.md`。

### E. UI 收尾
- `d1565ef` **配置助手改真·浮动 overlay**（`ChatPage.vue` `.ca-floating` position:absolute
  top:48px）：原来是 flex sibling 挤压顶部工具栏，现在落在 48px TopBar 下、不占 flex 宽。
- `8965a55` **退休老 md-viewer**（平铺 SPEC dump，一闪而过那个）：读 SPEC 统一走「设计」tab
  (SpecDesignPanel，结构化+用对话改+确认并生成+导出.md)；草稿应用 `restoreActiveViewForApp`
  改路由到 platform + topTab='spec'。
- `5fa71d5` 退休后补加载占位「⏳ 正在进入应用…」：填掉 activeView='builder' 加载窗口的白屏。

## 当前环境/数据状态
- **env 49（产品租户 / apaas-trial.definesys.cn）token 已刷新**（原过期，导致用户撞 401）。
  有 admin 账号密码可自动重登。
- **inn-idm（app_22）已补全成完整 132 模型 / 42 表单**（原 9 模型 failed → 原地 generate-run
  幂等补全 → apaas_app_id=847803124843282432，deploy_record id=3 success，status=completed）。
- **租户 63 有个 `talent-mgmt` 重复应用(count=2)** — Fix1 之前留下的脏数据，**没清**。
- preview：backend serverId `0bf43afe`(8000)、frontend `5aeef22f`(5173)。launch.json 有
  backend/frontend/admin-spa/code-server。**backend 只能由 preview 起，别再 nohup 第二个**（撞 8000）。
- 测试库：本地 MySQL `apaas_builder`（user=apaas）。测试用 JWT：user_id=1 + tenant_id=63。

## 留尾 / 下一步（按优先级）
1. **🔴 app-config 页加载慢（用户原话"停一会儿"）**：Network 抓到 `applications` 1.5MB **×2**、
   `app detail`(/22) 948kB **×2**、`doc-versions` 1MB，还有个 `status`(application.ts:62) 一直
   **pending**。加载占位只消了白屏观感，**没提速**。查：为啥重复请求 + pending status 卡没卡加载链。
2. **deploy_from_artifact 换解析器**：有个 spawned task chip。`deploy_from_artifact`
   （`__init__.py` ~2235）还在用旧 `parse_design_doc`（对 535KB 文档解析出 3 个垃圾模型），
   应换成 `doc_pipeline.parse_document`（好解析器，132 模型）。主路径 `generate_app_from_doc`
   已经用好解析器了，只剩这条。
3. **#2 真·端到端验**：「上传文档」按钮 → 上传改过的 md → change_plan 审核 → execute，我只验了
   后端 diff 核心（9→132 出 123 actions）+ 按钮渲染，**没在浏览器点完整流程**（弹原生文件框 preview 点不了）。
4. **草稿应用验证**：退休 md-viewer 后草稿走 platform+设计 tab，**没拿真草稿测**（app_22 是已部署）。
   注意：草稿在 platform 视图下 功能/数据源 tab 会空（没 apaas），可能要加空态。
5. **failed 红 chip 视觉**：部分失败/生成失败+重试，只验了后端 4 态 e2e，没浏览器截图（没现成 failed app）。
6. **存量脏数据**：talent-mgmt 重复 2 个 + 可考虑清理；platform-admin 配额管理 UI（用户提过，没做）。

## 关键事实（别重新踩）
- `parse_document`（`app/doc_pipeline.py`）= **好解析器**，35 万字标准文档 → 132 模型；
  `parse_design_doc`（`app/doc_parser.py`）= **旧烂的**，同文档 → 3 垃圾模型。别再用后者。
- **generate 是幂等的**：`step_executor.execute_create_model` 撞"编码重复"→复用+补字段；
  generate-run 复用现有 apaas_app_id。所以"补全/重跑"安全，不用删应用（apaas 也删不掉应用）。
- apaas 字典字段名是 `dictionaryName/dictionaryCode`（不是 name/code）——查对象时注意。
- 视图路由：`activeView`('builder'/'platform'/'coding') × `topTab`('design'=功能designers /
  'spec'=设计 SpecDesignPanel / datasource / 权限 / 日志)。platform-shell v-show activeView==='platform'。
  builder-content（md-viewer 退休后只剩 deploy-hero + 加载占位 + deploy-side 时间线）v-show activeView==='builder'。
