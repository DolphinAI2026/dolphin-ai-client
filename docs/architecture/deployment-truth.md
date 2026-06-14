# 部署真相(契约)

> 主计划 Phase 1 / Phase 2D。定义"一个自开发产物到底处于哪一态"的七级真相,杜绝 agent 把"build 过"说成"已发布"。
> `deployment_status_service` 是这些真相的唯一来源;agent 没有该服务的观测,不得断言任何上线态。

## 七级真相(逐级独立,不可跳级宣称)

| 级 | 状态 | 含义 | 真相来源 |
| --- | --- | --- | --- |
| 1 | `workspace_changed` | 本地工作区有改动(相对 git 基线) | AI Builder 本地 FS |
| 2 | `build_passed` | 本地 build 成功 | AI Builder 构建观测(可缓存) |
| 3 | `package_exists` | 生成了 zip/包产物 | AI Builder 本地 FS |
| 4 | `uploaded_to_asset_library` | 上传到资产库 | AI Builder 上传观测(可缓存) |
| 5 | `bound_to_app` | 绑定到某 aPaaS 应用 | `apaas_app_id` 绑定记录 |
| 6 | `deployed_to_apaas` | 部署进 aPaaS | aPaaS 动作结果 |
| 7 | `republished_visible` | republish 后运行态可见 | **aPaaS live 拉取 / 短 TTL,绝不信缓存** |

## 铁律

- **"build 过" ≠ "已发布"**:级 2 不得显示成级 6/7。
- **"上传资产库" ≠ "已 republish"**:级 4 不得显示成级 7。
- **AI Builder 自身观测(级 1-4)可缓存**;**aPaaS 侧真相(级 6-7)live 拉或短 TTL**,因为 aPaaS 是唯一真相源,缓存的"已发布"可能已失效。
- agent 回答上线相关问题时,必须引用其核实到的具体级别(如"已 build 通过,但尚未发布"),不得笼统说"已上线"。
- 状态服务给 UI 和 agent **同一个 payload**,避免两侧各自推断出不同真相。

## 现状(碎片化,Phase 2D 收口目标)

当前 push 的 commit / 本地 build / 生成包 / 上传资产 / 已发布 aPaaS 应用 是各自独立的真相,无单一状态契约——这正是 agent 误报"已发布"的结构根源。`deployment_status_service` 把级 1-7 统一成一个可查询的状态对象。
