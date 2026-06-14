# 回归检查清单(推 dev 前必过)

> 主计划 Phase 8。架构加固重构均"纯搬移/收口零行为变化"为原则,本清单是推送前的人工+自动核验底线。
> 自动门是硬性;浏览器项在改动触及对应 UI 时人工跑一遍。

## 自动验证门(每次推送前必跑,硬性)

```bash
# 后端(权威, 与前端 Codex 并发活动无关)
cd backend && ./.venv/bin/python -c "import app.main"        # import 完整
./.venv/bin/python -m pytest -q                              # 基线: 795 passed / 7 skipped / 0 failed
./.venv/bin/python -m py_compile app/main.py app/mcp_server.py

# 路由表等价(拆 routes 时):拆分前后必须 diff 为空
./.venv/bin/python -c "from app.main import app; print('\n'.join(sorted(f'{sorted(r.methods)} {r.path}' for r in app.routes if hasattr(r,'methods'))))"
#   当前应为 309 条

# 工具 drift(改 mcp_tools/yaml 时):启动日志须 "114 tools == FastMCP 114"
./.venv/bin/python -m pytest tests/test_tool_registry.py -q

# 前端(改前端时)
cd frontend && npx vue-tsc -b                                # exit 0
npx vite build                                               # 成功
npm run test -- --run                                        # vitest 全过
cd admin-spa && npm run build

git diff --check                                             # 无空白/冲突标记
```

预存基线:后端 **795 passed / 7 skipped / 0 failed**(7 skipped = llm_config 租户隔离待拍板,非坏)。要求"不新增失败",新增测试可增加 passed 数。

## 关键行为回归(改到对应链路时人工跑)

### 0-1 应用生成(★两条引擎都要测 —— 同一 config_preview 可经两路)
- [ ] ChatPage 上传 .md 设计文档 → 解析预览 → 开始构建(走 **step_executor 分步**)→ 应用建成
- [ ] AIChatPage 草稿就绪自动生成(走 **generator_v2 一把梭**)→ 应用建成
- [ ] 同份文档两条路结果一致(Phase 3 收口的权限/表单配置函数已共享 operations 实现)
- [ ] 非 .md 文件(Word/PDF/图片)上传 → 进聊天让 AI 整理成设计文档(xhh 功能)

### 配置 / aPaaS 锚定
- [ ] 配置改动锚定真实 `apaas_app_id`,不跨租户串号
- [ ] 6 个设计 tab(表单/列表/流程/数据模型/权限/自开发)切换无 console 错

### 自开发 / coding
- [ ] coding agent 默认 edit_file 局部补丁;write_file 整改写已有文件给出补丁守卫软警告(Phase 5)
- [ ] 文件树 / 源码 / diff 渲染正常;发只读问题;刷新后保会话与工作区
- [ ] 部署/发布状态不夸大("build 过"≠"已发布")

### 认证 / 租户(Phase 4C 拆 auth 包后)
- [ ] 登录(aPaaS 账号)/ 切租户 / 平台管理员租户下拉
- [ ] 登录校验空账号/空密码提示

## 收口不变量(架构加固专属)

- [ ] `generator_v2` 与 `step_executor` 对收口后的 5 个表单配置函数(parse_permission_ops / 表单标识固化 / canvas / save_retry / finalize)调用 `operations/` 单一实现(不再各持副本)
- [ ] auth / applications 拆包后路由表逐条不变(309 条)
- [ ] mcp 工具 114 个无 drift

## 已知延后项(非回归,需外部决策)

- 3-6/3-7 权限 payload 收口:等 apaas 平台确认 advanced 权限字段处理
- Phase 6 三套回放层合并:需产品决策(跨子系统)
- Phase 7 前端拆分(ChatPage/CodingPage):需与 Codex 错开前端活跃期
