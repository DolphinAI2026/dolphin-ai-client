# Agent Run 状态机(契约)

> 主计划 Phase 1。定义一次 agent run 的合法状态与转移。当前 6 套 agent 循环的 run 语义各异(MAX_TURNS 25/30/12/8/4、abort 四套、retry 只 BaseAgent 有、观测只 1/6 接 recorder),本契约是 Phase X 收敛它们的目标语义,也是本计划期内 UI 区分 run 阶段的依据。

## 状态

| 状态 | 含义 |
| --- | --- |
| `created` | run 已建,未开始 |
| `planning` | LLM 思考/规划中(尚未调工具) |
| `running_tools` | 正在执行工具调用 |
| `waiting_user` | 等用户澄清/确认(ask_user 门) |
| `applying` | 应用 workspace patch / 写 aPaaS 配置 |
| `verifying` | 验 build / deploy / 产物 |
| `completed` | 正常完成 |
| `failed` | 出错终止 |
| `cancelled` | 用户中断 |

## 合法转移

```
created → planning
planning → running_tools | waiting_user | completed | failed
running_tools → planning | applying | waiting_user | failed | cancelled
waiting_user → planning            (用户回答后续轮)
applying → verifying | running_tools | failed | cancelled
verifying → completed | running_tools | failed
running_tools/applying/verifying/planning → cancelled   (任意活动态可被中断)
```

非法转移示例(契约测试须拒绝):`completed → running_tools`、`cancelled → applying`、`failed → completed`、跳过 `created` 直接进 `running_tools`。

## 不变量

- **中断保留已完成工具产出,但不能伪装完成**:`cancelled`/`failed` 的 run 不得对外报 `completed`;已完成的 tool step 输出保留可查。
- **`waiting_user` 与 `running_tools` 必须可区分**(UI 需求):前者是阻塞等输入,后者是进行中。
- **现状映射**:`AgentRun.status` 当前枚举是 `running/success/error/aborted`(observability),本契约是其细化目标。Phase X 前,unified run_agent 的 abort 出口已记 `aborted`,可作 `cancelled` 来源。

## 当前实现锚点(供 Phase X 收敛参考)

- unified:`ai_chat/agent.py` `run_agent`(MAX_TURNS=25,abort_event 逐点,接 recorder)。
- coding:`agents/coding/agent.py` CodingAgent(max_turns=30,on_context_overflow,InMemoryTraceWriter 不落库)。
- builder:`builder_spec/agent.py` SpecAgent(max_turns=12,spec_patch 即时落库)。
- read/grounded:`coding/pipeline.py` 内嵌子循环(max_turns 8/4)。
