# coding-v2 文件上传需求扩展方案（2026-04-22）

> 背景：当前 `POST /api/coding/v2/message` 的 `MessageRequest` 只接受 `message: str`，后端 V2 完全没做文件上传处理（对比老 `routes/coding.py` / `chat.py` / `requirements.py` / `applications.py` / `templates.py` 都有 `UploadFile` 端点，V2 重构时未迁过来）。本文档是针对"后续要支持文件上传"这一需求的扩展设计，**尚未实现**。

---

## 1. 先搞清楚"文件"在 V2 里扮演什么角色

不同文件类型走的路径完全不同，不要混为一谈：

| 文件类型 | 用途 | 处理方式 |
|---|---|---|
| **图片**（UI 参考图、截图） | brainstorm 参考"我想做成这样" | 多模态 LLM 直接 vision 输入 |
| **文档**（PDF/Word/Excel） | 需求文档、数据样例 | 服务端解析成文本 → 注入 prompt |
| **数据文件**（CSV/JSON） | Spec 阶段做字段推断 / coding 阶段初始化数据 | 存 workspace，agent 用 tool 读 |
| **代码/配置文件** | 参考既有实现 | 存 workspace，grep/read tool |
| **压缩包/模板** | 导入已有工程 | 解压到 workspace，走 scaffold |

**第一步应该是让用户明确："要支持哪类？"**——这决定了 80% 的设计。别一上来写"通用文件上传"。

---

## 2. 分三层扩展（对应三个 Agent 阶段）

### Layer 1：存储与引用（基础设施，所有阶段共用）

```
backend/app/models/attachment.py
  class Attachment:
    id, tenant_id, conversation_id, spec_id(nullable),
    kind(image/doc/data/code/archive),
    original_name, storage_path, mime, size,
    parsed_text(TEXT, nullable),   # 服务端解析后的文本（doc 类）
    metadata(JSON),                # {width,height} / {rows,cols} / {sheets:[]}
    created_at, uploaded_by
```

- 新增 `POST /api/coding/v2/attachments`（multipart），返回 `{attachment_id, kind, preview}`
- 存储：本地 `data/attachments/{tenant}/{yyyymm}/{uuid}` 或 OSS（看部署）
- **上传时立刻做解析**（PDF→text、xlsx→csv、image→dimension），失败就 `kind=unknown`，别拖到 agent 运行时才报错

### Layer 2：与 Agent 消息绑定

`MessageRequest` 扩展：

```python
class MessageRequest(BaseModel):
    conversation_id: Optional[int] = None
    message: str
    attachment_ids: list[int] = []    # 新增
    selected_model: Optional[int] = None
```

在 `_run_brainstorm_task` / `_resume_brainstorm_task` 里：

- **文本类附件**（doc/data/code）→ 拼进 initial user message，格式化为：

  ```
  用户需求：{message}
  附带文件：
  [文件1: requirements.pdf，解析摘要如下]
  ...（前 N 字符，超长截断 + 提供 read_attachment tool）
  ```

- **图片类**（image）→ 构造多模态 message：

  ```python
  {"role": "user", "content": [
      {"type": "text", "text": message},
      {"type": "image_url", "image_url": {"url": f"data:image/png;base64,..."}}
  ]}
  ```

  （**前提**：`_call_llm` / LLM client 要支持多模态；老 client 如果只收 text 得先改）

### Layer 3：Agent 侧工具

**BrainstormAgent** 新增 tool：

- `read_attachment(attachment_id, offset, length)` —— 超长 doc 不一次性塞 prompt，按需读
- `describe_image(attachment_id, question)` —— 仅当主 LLM 不支持 vision 时，调小多模态模型做一轮描述

**CodingAgent**：

- 生成代码需要参考样例数据时，spec_bridge 把 `attachment_ids` 写进 spec，CodingAgent 用 `read_workspace_context` 的扩展版读（或把文件预先拷到 workspace `.inputs/`）

**VerificationAgent**：通常不需要。

---

## 3. 与 V2 既有机制的兼容点（容易踩的坑）

基于交接文档里踩过的坑，提前规避：

1. **Snapshot**：`to_snapshot()` 要把 `attachment_ids` 序列化进去，否则 resume 后 agent 会忘掉附件
2. **Pause/Resume**：用户反问追加的新附件要能注入到 resume 的 tool_result 里（不只是纯文本答案）—— `resume_session` 签名要扩展 `user_answer` 为 `{text, attachment_ids}`
3. **事件流**：上传进度可以走独立 REST（不占 SSE），但附件被 agent "看到"时要 emit 事件 `brainstorm.attachment_referenced` 给前端高亮
4. **DB 事务**：如果解析失败要回滚存储文件（避免孤儿文件）
5. **Spec 持久化**：Spec 如果引用附件，`spec_service` 要把 attachment 一起做版本快照（或只存 id，但附件表加"不可删除"标记）

---

## 4. 分阶段落地（建议顺序）

| 阶段 | 范围 | 价值 | 复杂度 |
|---|---|---|---|
| **P1** | 只支持**图片**（vision 直传 LLM） | 90% 用户场景是"贴一张 UI 图说仿这个" | 低，不需要解析 |
| **P2** | 支持 **doc/data**（服务端解析成文本塞 prompt） | 覆盖需求文档、数据样例 | 中，要接 PDF/xlsx 解析库 |
| **P3** | 支持 **archive/workspace import**（解压到 workspace） | 从老项目迁移 | 高，涉及 scaffold 流程重叠 |

**强烈建议先做 P1**——后端改动最小（只改 `MessageRequest` + `_call_llm` 多模态格式化 + 存储层），且能立刻验证"上传文件后 agent 真的理解了"，不会像文档解析那样很容易 GIGO。

---

## 5. 需要用户先回答的几个问题

在动手前，建议先跟用户对齐：

1. **先支持哪类文件？**（图片最高优先级？）
2. **单轮上传 vs 整个 conversation 附着？**（附件是"这句话的上下文"还是"整个对话的参考"？）
3. **LLM 选型是否支持多模态？**（当前 MiniMax 配置有没有 vision 模型？没的话图片路径走不通）
4. **存储在哪？**（本地磁盘 vs OSS）
5. **文件大小/数量限制？**（影响 prompt token 预算）

这些答案决定了 schema 和 API 形态，别先写代码。

---

## 6. 当前相关代码锚点（方便后续实现定位）

- 入口路由：`backend/app/routes/coding_v2.py`（`MessageRequest` 在 L56，`_run_brainstorm_task` 在 L378，`_resume_brainstorm_task` 在 L417）
- Brainstorm agent：`backend/app/agents/brainstorm/`（agent.py / tools/ / prompts.py）
- Spec 持久化：`backend/app/services/spec_service.py`
- Session + snapshot：`backend/app/services/brainstorm_session_service.py`
- Base agent snapshot 机制：`backend/app/agents/base.py`（`to_snapshot` / `from_snapshot` / `run()` resume 分支）
- 前端入口：`frontend/src/views/coding-v2/CodingPageV2.vue` + `frontend/src/api/codingV2.ts`
- 老版文件上传（参考，别直接抄）：`backend/app/routes/coding.py` / `chat.py` / `requirements.py` / `applications.py` / `templates.py`
