# 新客户开通 SOP

> 给一个新客户开 ai-builder + dolphin agent + apaas 平台的 trial 环境完整流程。
>
> 基于 2026-05-11 / 05-12 实测开过 4 个客户（default / pg_trial / 得克 / 白客松 / 上汽大乘用车）总结的踩坑指南。
>
> **预计耗时**：30-60 分钟（不算等外部团队回信息）

---

## 总体架构 — 1:1:1 强绑

```
新客户 = 1 个 ai-builder tenant
         ↔ 1 个 apaas 平台环境（独立 base_url + tenant_id + service_token）
         ↔ 1 个 dolphin customer（独立 customer_name + 3 个独占 agent + 用户隔离）
```

任何一条线断 → dolphin agent 调 MCP 工具撞「环境别名 X 不存在」/「无权访问」/「token 过期」。

---

## Phase 0 · 准备阶段：拿 4 组信息（开工前必齐）

| # | 信息项 | 谁给 |
|---|--------|------|
| 1 | 客户中文名 + 英文 slug（必须小写字母+数字+`_`/`-`） | 你定 |
| 2 | apaas 环境凭证：`base_url` + `平台租户 21 位 bigint id` + `username` + `password`（或 `service_token`） | 得帆 apaas 团队（让客户跟他们采购/开通） |
| 3 | dolphin customer + 3 agent_code：`customer_name`（中文）+ `dolphin_tenant_code`（英文 slug）+ Builder/Coding/Vibe 3 个独占 agent_code（10 位 hex） | dolphin 团队（要 dolphin trial 超管权限） |
| 4 | 客户租户管理员 username（要跟 apaas + dolphin 同名同人） | 客户自己定 |

⚠️ **不拿齐前不要动 DB / 不要点 UI 新建**，否则会留半拉子脏数据（你要清理）。

### 给得帆 apaas 团队的 ticket 模板

```
请给 <客户名> 开通 apaas trial 平台租户，回提供：
  - apaas tenant id（21 位 bigint string）
  - apaas base_url（如 https://apaas-trial.definesys.cn/backend）
  - 管理员 username + 初始 password（如 saic / welcome1）
  - service_token（可选，账密能自动登就不必需）
  - 客户租户管理员的 apaas 平台账号（让客户能登 apaas 后台看数据）
```

### 给 dolphin 团队的 ticket 模板

```
请为 customer="<客户名>" / dolphin_tenant_code="<slug>" 配 3 个 agent：

【克隆模板】
  - Builder ← 23c93f30d8
  - Coding  ← f765238af4
  - Vibe    ← 51ebb5937b

【每个 agent 配齐 3 件套】
1. MCP 服务：apaas-builder-ai-mcp
   URL: https://agent.dfy.definesys.cn/mcp-server/api/mcp/mcp
   - Builder/Coding 勾全部 60 工具
   - Vibe 只勾 9 个 vibe_* 工具
2. Skill：
   - Builder/Coding → ai-builder-unified（最新版 v0.1.3）
   - Vibe → ai-builder-unified-fork (= spec-driven-development)
3. **全局记忆**：加一行 `env: <slug>` ⭐ 这条容易漏！
   key=env, value=<slug>（跟 ai-builder platform_envs.alias 完全一致）

【发布 + 回我】
  - 3 个 agent_code（10 位 hex）
  - customer_name 确认
  - 给客户管理员开 dolphin trial 用户账号（username 跟 apaas 那边同人）
```

---

## Phase 1 · ai-builder admin UI 操作（10 分钟）

### Step 1: 新建租户

URL: `https://agent.dfy.definesys.cn/ai-builder/admin/tenants`

点「新建租户」填表单：

| 字段 | 值 |
|------|---|
| 租户名称 | 客户中文名（如「上汽大乘用车」）|
| 租户编码 | 客户英文 slug（如 `saic_pass_car`）— **唯一不可改一次填对** |
| 低代码应用数量上限 | 100（默认）|
| Vibe Coding 工作区上限 | 50（默认）|
| 自开发组件数量上限 | 100（默认）|
| 联系人姓名 / 邮箱 | 客户实际对接人 |

保存 → 列表会显示「⚠️ 缺 N 项」 — 正常，下一步补齐。

### Step 2: 新建 apaas 平台环境

URL: `https://agent.dfy.definesys.cn/ai-builder/platform-envs?tab=envs`

⚠️ **关键容易踩坑**：不要重复点「新增」按钮，会建多条同 tenant 行 → 后续 tenants.apaas_env_id 指向错（自动指 is_default=1 那个）

新增表单：

| 字段 | 值 |
|------|---|
| 所属租户 | 选刚建的客户 |
| 环境名 | 「<客户名> apaas 环境」 |
| base_url | 得帆给的 |
| 平台租户 ID | 得帆给的 21 位 bigint |
| **环境别名 alias** ⭐ | **`<客户 slug>` 跟租户 tenant_code 一致（如 `saic` / `fudan`）— dolphin agent 全局记忆 `env: <alias>` 反查 key**，全局唯一 |
| 用户名 | 得帆给的（如 `saic`）|
| 密码 | 得帆给的（如 `welcome1`） |
| 设为默认 | ✓ |

保存 → 后端自动用账密 login apaas 拿 token → status 变 `connected`。

> 📜 历史背景：commit `66f9cad` 之前 ai-builder admin UI 没 alias 输入框，每次都要 SSH 走 `UPDATE platform_envs SET alias='...'`。复旦试用接入实测后修了 — 现在 UI 直接填，撞别名 400 友好提示。

### Step 3: 加 3 个 dolphin agent NavRail 入口

URL: `https://agent.dfy.definesys.cn/ai-builder/platform-envs?tab=dolphin`

点「新增」3 次，每次填：

| 字段 | Builder | Coding | Vibe |
|------|---------|--------|------|
| display_name | 智能搭建 | 低代码自开发 | Vibe Coding |
| agent_code | dolphin 给的 Builder code | Coding code | Vibe code |
| instance_id | `ai-apaas-builder` | `ai-apaas-coding` | `ai-apaas-vibe` |
| nav_path | `/ai-copilot` | `/ai-coding` | `/agent/vibe-coding` |
| nav_icon | Files | Edit | Box |
| sort_order | 10 | 20 | 30 |
| is_default | ✓ | | |

### Step 4: 编辑租户补 dolphin customer 字段

回租户列表点「编辑」该客户：

| 字段 | 值 |
|------|---|
| dolphin_customer_name | 跟 dolphin 团队约定的（如「上汽大乘用车」）|
| dolphin_tenant_code | dolphin 给的 slug |
| dolphin_server_url | `https://dolphin-trial.definesys.cn` |

保存后租户列表状态变 **✓ 已绑定**（跟 default / pg_trial 一样）。

---

## Phase 2 · 验证（5 分钟）

### 1. ai-builder backend 1:1:1 健康检查

```bash
ssh -i ~/.ssh/apaas_deploy_rsa root@101.132.123.203
tail -50 /root/apaas-builder-mcp-server/backend/logs/uvicorn-8004.log | grep "1:1:1"
# 期望：[tenant 1:1:1 健康检查] tenant id=<新> code=<slug> OK (apaas_env=<env_id>, customer=<名>)
```

⚠️ backend 启动时一次性做健康检查 — 如果你刚补完字段没重启，看不到 OK，**重启 backend** 或者忽略（运行时不会卡）。

### 2. backend 实测 list_apaas_apps(env=<alias>)

```bash
TOKEN=$(curl -sS -X POST http://127.0.0.1:8004/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -sS -X POST http://127.0.0.1:8004/api/mcp/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_apaas_apps","arguments":{"env":"<slug>"}}}'

# 期望 result.content[0].text 含 {"ok": true, "env": "<slug>", "apps": [], "total": 0}
```

如果撞「环境别名 X 不存在」→ 看下面【故障排查】。

### 3. 客户首次登入

让客户管理员浏览器打开 `https://agent.dfy.definesys.cn/ai-builder/`：
1. dolphin SSO 自动 mirror 创建 ai-builder 用户绑 apaas_user_id
2. 进客户租户工作台 → 左侧 NavRail 看到 3 个入口
3. 点 Builder → dolphin 浮窗 customer = <客户名>，能跟 agent 对话

### 4. 实测「做一个员工通讯录」

```
用户: 给我做一个员工通讯录应用
agent: <写 spec md → STEP 1.5 check_model_codes → 完整 SPEC 展示给你审>
用户: OK 按这个 SPEC 来
agent: <generate_app_from_doc → 在客户 apaas 环境真创建应用>
```

---

## 🚨 故障排查

### 撞「环境别名 X 不存在」

**99% 真因**：`platform_envs.alias` 没填或填错。

```bash
mysql -uapaas -papaas2024 apaas_builder -e "
  SELECT id, tenant_id, env_name, alias, status, is_default
  FROM platform_envs WHERE tenant_id = <客户 tenant_id>;
"
# 检查：
# 1. alias 列是不是想要的字符串（如 saic）— NULL 就是没填
# 2. 是不是有多行（重复建过）— 留一行删其余
# 3. is_default=1 那行 + tenants.apaas_env_id 指向是否一致
```

修：
```sql
UPDATE platform_envs SET alias = 'saic' WHERE id = <真正要用的 env_id>;
UPDATE tenants SET apaas_env_id = <env_id> WHERE id = <客户 tenant_id>;
```

### 撞「token 过期 / 401 Unauthorized」

backend 调 apaas API 时 token 失效。

```bash
mysql -uapaas -papaas2024 apaas_builder -e "
  SELECT id, username, status, LENGTH(token) AS token_len, LENGTH(password_enc) AS pwd_enc_len
  FROM platform_envs WHERE id = <env_id>;
"
# 1. status 应是 connected（不是 disconnected）
# 2. token_len > 0（有 token）
# 3. pwd_enc_len > 0（有加密密码 — 自动重 login 兜底）
```

如果 token=NULL 或 status=disconnected：
- 在 admin UI 进该 env 「测试连接」按钮重 login
- 或者改 username/password 重新保存触发自动 login

### 撞「dolphin agent 找不到 saic」

agent 那边的全局记忆缺 `env: <slug>`。

不能 SSH 修，**找 dolphin 团队**：
```
请给 customer=<客户名> 下的 3 个 agent 都加全局记忆 `env: <slug>` —
此前漏配，导致 agent 调 list_apaas_apps 时不传 env 参数撞错。
```

### 撞「跨 tenant 串号」（用户 A 看到 B 的应用）

```bash
mysql -uapaas -papaas2024 apaas_builder -e "
  SELECT id, tenant_name, tenant_code, apaas_env_id, dolphin_customer_name,
         dolphin_tenant_code FROM tenants WHERE id=<客户>;
"
# 必须 4 个字段都非 NULL，且都跟其他客户不一样
```

如果任一字段为 NULL → 1:1:1 没配齐 → 走 STEP 5 编辑租户补全。

---

## 共享资源（不需要为新客户配）

- ❌ ECS / mysql / nginx / podman — 全共享
- ❌ mcp-server backend 60 工具 — 共享
- ❌ skill ai-builder-unified / ai-builder-unified-fork — 共享
- ❌ Vibe Coding 镜像 — 共享，自动按 tenant_id 物理目录隔离
- ❌ MCP URL `https://agent.dfy.definesys.cn/mcp-server/api/mcp/mcp` — 共享

---

## 配额建议

trial 阶段：

| 配额 | 默认 | 推荐 |
|------|------|------|
| max_applications | 100 | trial 给 10（防误建一堆 zombie 应用） |
| max_workspaces | 50 | trial 给 5 |
| max_components | 100 | trial 给 10 |

正式签约后再放开（admin UI 编辑租户改配额）。

---

## 长期 todo（开 N 个客户后再做）

1. ~~**前端 PlatformEnvs.vue 表单加 alias 输入框**~~ ✅ 复旦试用接入时完成（commit `66f9cad`）
2. **admin SPA mcp-server Phase 4.2** — 写完整 PlatformEnvs 替代老 ai-builder frontend
3. **写 dolphin 团队自助 portal** — 让 dolphin trial 用户自己克隆 agent 不用每次找团队（dolphin 团队配合）
4. **加 `tenants` schema UNIQUE 约束**：(dolphin_customer_name, dolphin_tenant_code) 防止串号
5. ~~`platform_envs.alias` UNIQUE 约束~~ ✅ 已有 + commit `66f9cad` 加了 UI 友好 400 错误提示

---

## 实测开通的客户清单

| tenant_id | tenant_code | 中文名 | apaas_env_id | alias | dolphin_customer | 开通日期 |
|-----------|-------------|--------|--------------|-------|-----------------|---------|
| 1 | default | 体验租户 | 1 | default | 得帆体验 | 系统建 |
| 2 | pg_trial | 宝洁（中国）有限公司 | 22 | baogong | 宝洁（中国）有限公司 | 2026-05-09 |
| 3 | bkbs | 白客松比赛 | - | - | - | 2026-05-03 |
| 4 | deckers | 得克 | - | - | - | 2026-05-07 |
| 6 | definesys | 上海得帆智能科技有限公司 | - | - | - | 2026-05-08 |
| 7 | saic_pass_car | 上汽大乘用车 | 28 | saic | 上汽大乘用车 | 2026-05-12 |
| 8 | fudan | 复旦大学 | 31 | fudan | 复旦大学 | 2026-05-12 |

3/4/6 三个状态「缺 N 项」可以按本 SOP 补齐。

---

## 复旦试用接入实测复盘（2026-05-12）

按 SOP 走完后撞 2 个 onboarding bug，本 commit (`66f9cad`) 已修。后续不会再撞。

| Bug | 真因 | 修复 |
|-----|------|------|
| `list_apaas_apps(env="fudan")` 报「环境别名 fudan 不存在」| ai-builder admin UI 平台环境表单没 alias 输入框 — 用户以为自动生成（实际 NULL），mcp 工具按 alias 反查找不到 | SQL `UPDATE platform_envs SET alias='fudan'` 立刻解燃眉 + 前后端补 alias UI 字段（commit `66f9cad`） |
| 「添加智能体」弹窗 instance_id select 没有 vibe 选项 | 前端 `PlatformEnvs.vue:189-190` 硬编码只 2 个 option（builder/coding），用户没意识到 `allow-create` 能直接打字 | 加第 3 个 option `ai-apaas-vibe（全代码 / Vibe Coding 沙箱）`（commit `66f9cad`） |

**Vibe agent 设计补充**：
- admin / baogong 共享全局 vibe agent `51ebb5937b`
- saic / fudan 各自有私有 vibe agent（SAIC 还没建；fudan 是 `cf30f3e495`）
- 两种模式都 OK — 共享省事，私有可定制 prompt
