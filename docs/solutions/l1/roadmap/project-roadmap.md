# Project Roadmap

本工作区使用 Builder 管理独立、可审查的工程 phase。

## Phases

| Phase | 状态 | 依赖 | Spec |
| --- | --- | --- | --- |
| Builder 租户 URL 公共 UUID | ready_for_review | 无 | `docs/superpowers/specs/2026-07-20-builder-tenant-url-public-uuid-design.md` |
| Builder 本地镜像验证模式 | ready_for_review | 无 | `docs/superpowers/specs/2026-08-11-local-builder-image-verification-design.md` |

## 维护规则

- `docs/assets/builder/roadmap.yaml` 是机器可读 phase 状态的唯一事实源。
- phase 发布后保持 `phase_id` 稳定。
- 每个 phase 的实现只消费其当前 Spec、derivation 和 phase metadata。
