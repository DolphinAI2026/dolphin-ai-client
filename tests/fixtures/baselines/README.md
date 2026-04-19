# Agent 迁移基线

本目录存放 **VibeCodingAgent → CodingAgent 迁移前** 的行为基线，用于迁移后客观对比。

对应计划：见 `docs/internal/INTELLIGENT_DEV_AGENT_ARCHITECTURE_V1_2026-04-19.md` § 8 Phase 1.1d。

---

## 为什么需要基线

VibeCodingAgent 即将被迁移为继承 `BaseAgent` 的 `CodingAgent`。由于：
- 涉及大量代码重构（1348 行的 agent）
- LLM 调用从内嵌 httpx 改为 `LLMClient.chat_completion_stream(tools=...)`
- 事件格式通过 adapter 转换

**无基线的话，无法客观判断"迁移后行为是否一致"**。

---

## 录制什么

**当前基线**：`case_a_rating_star_run1` / `case_a_rating_star_run2`
- 需求："做一个星级评分组件，支持半星和自定义颜色"
- 场景：web_component_dual（最主流、最复杂的 7-scene 生成路径）
- 录 2 次作为 LLM 抖动基线

**为什么没有 Case B（backend_api）**：
- 尝试过 "开发一个订单查询后端接口..." 但 MiniMax 模型做 scene detection 时把所有输出塞进 `<think>` tag，正文为空 → fallback 到 web_component_dual
- 两次 run LLM 命名抖动严重（widget_code 不一致）
- backend_api 走独立的 `_scaffold_backend_api`（纯 Python 模板拷贝，无 LLM 参与），迁移前后行为由 Python 代码决定 — 不需要 LLM 基线
- Case A 已覆盖 95% agent 复杂度（7-scene 组件生成）

**迁移后如果 backend_api 也要 E2E 验证**，可以在迁移完成后再补录（届时可能换成不带 reasoning 的模型做 scene detection 更稳）。

---

## 录制前准备

### 1. 启动 backend（本地）

```bash
cd backend
venv/bin/python run.py
```

backend 必须能访问：
- 数据库（SQLite 或 MySQL）
- 至少一个配置好的 coding 模型（检查 `llm_configs` 表，记下 `id`）
- workspace 根目录可写（`$APAAS_WORKSPACE_ROOT` 或默认 `./workspaces`）

### 2. 设置环境变量

```bash
export BACKEND_URL="http://localhost:8000"
export CODING_MODEL="llmcfg:1"   # 替换为你租户的实际 model config id

# 认证：二选一
#   方式 A：浏览器登录后从 localStorage 复制 token
export AUTH_TOKEN="eyJ..."
#   方式 B：脚本自动签发（需要能 import backend 代码拿到 JWT_SECRET_KEY）
export RECORD_USER_ID=1
export RECORD_TENANT_ID=1
```

### 3. 检查脚本可用

```bash
python scripts/record_agent_baseline.py --help
```

---

## 录制命令

### Case A × 2

```bash
python scripts/record_agent_baseline.py \
    case_a_rating_star \
    --message "做一个星级评分组件，支持半星和自定义颜色" \
    --output tests/fixtures/baselines/case_a_rating_star_run1

# 等 5-15 分钟 LLM 跑完，看到 "✓ 录制完成" 后再跑第二次

python scripts/record_agent_baseline.py \
    case_a_rating_star \
    --message "做一个星级评分组件，支持半星和自定义颜色" \
    --output tests/fixtures/baselines/case_a_rating_star_run2
```

### Case B × 2

```bash
python scripts/record_agent_baseline.py \
    case_b_order_query \
    --message "开发一个订单查询后端接口，支持按日期和状态筛选" \
    --output tests/fixtures/baselines/case_b_order_query_run1

python scripts/record_agent_baseline.py \
    case_b_order_query \
    --message "开发一个订单查询后端接口，支持按日期和状态筛选" \
    --output tests/fixtures/baselines/case_b_order_query_run2
```

### 单次录制预计耗时

- LLM 实际跑：5-15 分钟（看模型和需求复杂度）
- 脚本其他开销：< 10 秒

---

## 录制产物目录结构

```
tests/fixtures/baselines/case_a_rating_star_run1/
├── events.jsonl                   # SSE 全部事件（每行一个 JSON）
├── metadata.json                  # 聚合元信息
├── workspace_tree.txt             # 文件清单 path<TAB>size<TAB>md5
├── workspace/                     # 关键配置文件完整拷贝
│   ├── shared/
│   │   └── widget.config.json
│   ├── web/src/
│   │   └── apaas.json
│   └── mobile/src/
│       └── apaas.json
└── recorded_at.txt                # 录制时间 + 环境信息
```

### metadata.json 样例

```json
{
  "case_name": "case_a_rating_star",
  "message": "做一个星级评分组件...",
  "model": "llmcfg:1",
  "duration_seconds": 432.5,
  "total_events": 287,
  "events_by_type": {
    "agent_thinking_delta": 180,
    "agent_tool": 22,
    "agent_result": 22,
    "step": 8,
    "done": 1
  },
  "event_type_sequence": ["step", "step", "agent_thinking", "agent_tool", ...],
  "tool_call_count": 22,
  "tool_names_called": ["glob_files", "read_file", "write_file", ...],
  "workspace_id": "1_a1b2c3d4",
  "ide_url": "http://code-server/?folder=...",
  "final_status": "success",
  "error_message": null
}
```

---

## 录完后提交

```bash
git add tests/fixtures/baselines/
git commit -m "ops: record VibeCodingAgent baseline for P1.1d migration

- case_a_rating_star (web_component_dual) × 2 runs
- case_b_order_query (backend_api) × 2 runs
- 用于 CodingAgent 迁移后客观对比"
```

---

## 迁移后对比（Stage 3 做）

CodingAgent 迁移完成后，按同样方式再录一次（命名 `case_*_migrated`），然后：

```bash
python scripts/compare_baseline.py \
    --baseline tests/fixtures/baselines/case_a_rating_star_run1 \
    --candidate tests/fixtures/baselines/case_a_rating_star_migrated \
    --baseline2 tests/fixtures/baselines/case_a_rating_star_run2
```

输出类似：

```
✓ final_status — both success
✓ event types (set) — 7 types 一致
✓ tool names (set) — 6 tools 一致
✓ tool_call_count — 22 vs 23 (±3)
✓ total_events — 287 vs 301 (±20%)
✓ workspace file paths — 68 files 一致
✓ widget.config.json 关键字段 — code/version/componentModelField/component 一致
✓ web/src/apaas.json 关键字段 — entry/outputName/templateType 一致

✅ PASS
```

对比规则：

| 规则 | 严格度 | 允许阈值 |
|---|---|---|
| final_status | 严格 | 必须都 `success` |
| event_types（集合） | 严格 | 集合一致 |
| tool_names（集合） | 严格 | 集合一致 |
| tool_call_count | 宽松 | ±3 |
| total_events | 宽松 | ±20% |
| workspace file paths | 严格 | 集合一致（>3 文件差异 fail）|
| widget.config.json | 严格 | code/version/componentModelField/component 字段一致 |
| apaas.json | 严格 | entry/outputName/templateType 字段一致 |

---

## 常见问题

**Q：录制一半报错怎么办？**  
A：清空 output 目录重录。脚本会提示"输出目录非空"。

**Q：auth token 在哪里拿？**  
A：浏览器打开 builder 前端，F12 → Application → Local Storage → 找 `token` 或 `auth_token`。或者用 `RECORD_USER_ID/RECORD_TENANT_ID` 让脚本自动签发。

**Q：我跑得很慢（>30 分钟未结束）？**  
A：基本是 LLM 429 或者模型本身卡顿。脚本默认 900s 超时，可以通过 `--timeout 1800` 加长。

**Q：两次 run 结果差异很大怎么办？**  
A：这说明 LLM 本身非确定性严重。记录下差异作为参考，迁移后 CodingAgent 的产出只要**接近**任一次基线即算通过。如果两次基线自己都不稳定，可以再录第 3 次提升置信度。

**Q：能不能只录一次？**  
A：不推荐。单次基线不知道"基线自身抖动边界"，迁移后一旦对不上就不好判断是迁移 bug 还是 LLM 抖动。录两次的成本只多 10-30 分钟，ROI 高。
