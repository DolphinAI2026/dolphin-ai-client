# Handoff — 2026-06-05 应用生成/表单渲染系列修复

> 接手须知:本会话很长,覆盖多个 bug。核心是「全量生成的应用表单在 apaas 低代码后台渲染不出来」的根因定位 + 修复。所有改动在 `dev` 分支,**有 4 个 commit 待推 origin/dev**。

## 0. 当前状态(最重要)

- 分支 `dev`,HEAD = `a1d8b153`,**领先 origin/dev 4 个 commit,0 落后,工作树干净**。
- **待推**(本会话后半段的全部修复,都未 push):
  - `d8cf4ed0` fix(theme): 暗色 trace 抽屉补 `--t-bg-soft/--t-border-soft/--t-bg-active` token
  - `f3dd250e` fix(generate): 发布状态硬门 + 轮询引导(生成没完别 publish)
  - `3a546040` fix(generate): 去掉 webFormSettings/mobileFormSettings 注入(表单设计器画布空白根因)
  - `a1d8b153` fix(generate): 下拉按名绑字典 + 可复用就地修复脚本
- **下一步第一件事**:`git push origin dev`(用户已认可这些修复,只是会话不够了没推)。
- 之前已推到 `32fbdc6a`(merge):含延迟工具/ToolSearch + 写后表单刷新修复 + 删冗余 UI + merge 别人 8 commit。
- ⚠️ `backend/run.py` 是 `reload=False` —— **改后端必 `preview_stop`+`preview_start` backend** 才生效。本地 DB = SQLite `/tmp/fb_demo.db`。.venv = py3.13。

## 1. 本会话做完的事(按主题)

### A. 延迟工具 / ToolSearch(claude-js 借鉴 #1,已推)
`run_agent` 每轮把 ~118 工具 schema 全量内联 → 改成核心 ~14 常驻 + 长尾延迟,模型用 `search_tools` 按需激活。已实现+live 验证。来源调研 `docs/research-claude-js-harness-borrow-2026-06-05.md`。#2 上下文压缩、#3 大结果落盘 **未做**(后续)。

### B. 写后表单预览不刷新(已推,`1867624`)
根因 = `section_content.py:_safe_call_mcp_tool` 有 **180s TTL 缓存**,配置写经 agent/MCP 路径不 invalidate 它 → 前端刷新命中旧缓存返 stale。修:`get_form_detail` 加 `force` 参 + `FormDesignerPanel` 软刷(silent reload)+ `refreshNonce` 多档重试带 force。详见 memory `section_content_180s_cache_stale_after_write`。

### C. 删设计面板冗余 UI(已推,`be4f09f`)
按用户框选删:顶栏「→自开发」按钮(+死函数 handoffToCodingForAppDev)、菜单 form_id 哈希、各面板「业务视角预览/只读视图」banner、表单头 leave_apply·字段数 meta、列表「N 列」。

### D. 🎯 应用生成三大 bug(本会话核心,待推)

**D1. 生成没跑完就宣布"已上线"(`f3dd250e`)**
- 根因(从 app_id=8 的 agent_step trace 定位):`deploy_application` 把后台生成(generator_v2)起来后 25s 早返(status=generating),agent 只等 ~30s 就 `publish_application` + 宣布"已完成上线" —— 9 个表单要 ~2.5min 才生成完,发了半成品。
- 修:发布路由(`routes/applications/__init__.py` `publish_application`)加状态硬门 —— status 在 `generating/in_progress` 时返 **409**;MCP `publish_application` 捕获 409 → 返 `STILL_GENERATING` + 引导轮询;`get_application` 未完成时带 `generation_progress`(角色/字典/模型/表单 X/Y);`deploy_application` 早返提示改为"轮询到 status=completed 才算就绪,别用 apaas_app_id 判断完成"。
- 测试:`backend/tests/test_publish_status_gate.py`(6 个,过)。

**D2. 🔥 全量生成的表单在低代码后台画布空白/选不出来(`3a546040`)**
- **根因(肉眼+可逆实测坐实)**:全量生成给表单 `detailPage` 注入空的 `webFormSettings={}` / `mobileFormSettings={}`;apaas 把空 {} 展开成 `formTitleConfigList` 指向**不存在的 "formName" 标题组件**,表单设计器加载时崩(控制台报 `需要renderLogic` / `engineContext null` / widget `focusStyle` undefined),画布显"暂无数据"=字段渲染不出来。原生 + 对话(`build_apaas_feature_from_spec`)建的表单**都不带这俩**,所以一直正常。
- 这俩是 commit `1880c145`("improve form config quality")加的,弄巧成拙。`apaas_client`/`operations` 不引用它们,保存接口也不需要。
- 修:`generator_v2._force_form_identity` + `step_executor._apply_form_identity_to_form_config` 不再 setdefault `webFormSettings/mobileFormSettings`(保留 `previewLanguage/formVersionConfig`)。测试 `backend/tests/test_form_no_webform_settings_injection.py`(2 个,过)。
- ⚠️ 关键教训:**formContext 接口返 200 ≠ 设计器画布能渲染**。坏表单 formContext 也是 200;画布崩是客户端渲染错,**只能用 Claude in Chrome 开 apaas 后台肉眼看 / 读它控制台**。我一度因为只看 formContext 误判 webFormSettings 无害,后来肉眼测才抓到。

**D3. 下拉选项是空的 / 没绑字典(`a1d8b153`)**
- 根因:spec 经常没把下拉字段连到字典(模型字段缺 `field.dict`),导致 `generator_v2._rebind_dicts_on_forms` 的 `label_dict` 为空 → 下拉组件 `source=None`、绑不上字典。
- ⚠️ **更正一个误判**:字典本身**是有选项的** —— 之前以为"0 选项"是因为 `query_dicts` 不内联返回选项,要用 `query_dict_options(app_id, dict_id)` 查才看得到。所以 `_seed_dict_options` 没问题,真问题只有"下拉没绑上"。
- 修:`_rebind_dicts_on_forms` 给 `label_dict` 加"**字典名 == 组件 label**"兜底映射,即使 spec 没连,下拉也绑到同名字典(字段「报修类型」↔ 字典「报修类型」)。

### E. 可复用就地修复脚本(`a1d8b153` 内)
`backend/scripts/repair_form_render_and_dropdowns.py` —— **不重新生成**,给一个 app 就地修它所有表单:
```
cd backend && .venv/bin/python scripts/repair_form_render_and_dropdowns.py <apaas_app_id> <env_id>
```
逐表单:① 删 `detailPage.webFormSettings/mobileFormSettings`(治画布崩)② 按名把下拉绑到字典(治下拉空)。formContext 500 的(被手动编辑污染)会跳过并提示重新生成。
- 实测 app9「设备报修管理」(apaas `850744994011545600` env 59):跑完 3 个下拉全绑、设计器画布完整渲染。✅
- **用户要求**:把其它"昨天 bug(1880c145)之后生成、表单还没被删"的应用也跑这个脚本修。下一个 session 可问用户要 app 列表批量跑。

## 2. 验证现状 / 用户在做什么

- 用户说"此前的不管了"(app8 研发实验室那 9 个表单的菜单已被用户测试时删了,只剩 11 模型+分组菜单+2 测试表单;不修了,需要时重新生成 —— 代码已修,重新生成会是好的)。
- 用户正在**自己测试验证**修复效果(全量建新应用 → 看表单渲染 + 下拉)。
- app9「设备报修管理」是本会话建的干净修复样本,设计器能渲染、下拉已绑。

## 3. 待办 / 下一步

1. **`git push origin dev`**(4 个 commit)—— 第一件事。
2. 用户测试反馈:如新建应用还有问题,继续查(全量路径 = `deploy_application` → SSE `/generate` → `generator_v2`)。
3. 跑修复脚本修用户其它受影响的应用(问用户要 apaas_app_id 列表)。
4. claude-js 借鉴 #2(上下文压缩)、#3(大结果落盘)未做。
5. 配置助手 D 收尾:删旧 `_config_chat_event_stream` 死码(非阻塞)。
6. (可选)把就地修复做成正式 endpoint/MCP 工具,让产品能自愈 1880c145~修复窗口内生成的应用。

## 4. 诊断手法(下个 session 复用)

- **直连 apaas**:`from app.coding.apaas_tools import call_apaas_with_relogin` + `AsyncSessionLocal`,`await call_apaas_with_relogin(env_id, db, lambda c: c.query_form_config(app, form))` 等。绕过路由 180s 缓存,看 apaas 真值。
- **关键 apaas client 方法**:`query_form_config`(=formContext,设计器加载用,简表)、`query_detail_page_config`(=detailPageConfigById,详,500 时也能读)、`query_dicts`(不含选项)、`query_dict_options(app,dict_id)`(含选项)、`query_menus`、`save_form_config`、`add_dict_option`。
- **执行记录**:SQLite `/tmp/fb_demo.db` 的 `agent_run`/`agent_step`(trace,tool_name/args_json/result_text)、`applications`(status/apaas_app_id/config_preview/generation_state)。
- **肉眼看 apaas 后台**:Claude in Chrome(用户浏览器已登 apaas-trial)。表单设计器 URL:`https://apaas-trial.definesys.cn/platform/<tenant>/default/data-model-fn-config?appId=<apaasAppId>&menuId=<menuId>&formId=<formId>`。读 `read_console_messages` 看设计器报错(渲染崩的根因常在这)。
- **判定"表单能渲染"**:formContext 200 不够(坏表单也 200);要么肉眼看画布(不是"暂无数据"),要么看控制台无 renderLogic/engineContext 错。

## 5. 文件改动速查(本会话核心 4 commit)

- `backend/app/routes/applications/__init__.py` — publish 状态硬门
- `backend/app/mcp_server.py` — publish_application 409 处理 / get_application 进度 / deploy 引导
- `backend/app/generator_v2.py` — 去 webFormSettings 注入 + 下拉按名绑字典
- `backend/app/step_executor.py` — 去 webFormSettings 注入
- `backend/scripts/repair_form_render_and_dropdowns.py` — 就地修复脚本(新)
- `frontend/src/styles/theme-vars.css` — 暗色 token 别名
- `backend/tests/test_publish_status_gate.py` / `test_form_no_webform_settings_injection.py` — 回归测试
