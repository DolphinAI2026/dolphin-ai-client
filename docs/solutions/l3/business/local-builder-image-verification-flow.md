---
asset_kind: business-flow
asset_id: business-flow.local-builder-image-verification
knowledge_level: L3
source_spec_ref: docs/superpowers/specs/2026-08-11-local-builder-image-verification-design.md
source_spec_hash: sha256:8b760b70977ca147df38ef59e523abab8f76050a7073b10f04a1b059567b06f5
phase_id: 2026-08-11-local-builder-image-verification
revision: 1
status: ready_for_review
change_type: added
source_section_refs:
  - "实现操作矩阵"
  - "无副作用边界"
  - "验收标准"
relations:
  - type: supports
    target: spec.2026-08-11-local-builder-image-verification
---

# Builder 本地镜像验证 CLI 流程

## 背景/Context

开发者需要验证当前提交能否构建为本地 Builder 镜像，同时保持镜像仓库、Kubernetes 和线上
发布状态不变。该资产只把 source Spec 的 CLI 操作投影为 Builder 可消费的 typed flow，不
代表用户业务流程，也不增加页面、表单或发布职责。

## 方案/Solution

流程按输入校验、HEAD 快照构建、本地 inspect、结果写入和工作区不变性验证顺序执行。任何
失败都关闭在本地，不进入登录、推送、Kubernetes 或线上恢复路径。

## flow_model

```yaml
schema_version: flow-model/v1
flow_code: local-builder-image-verification
flow_type: local-cli-verification
trigger: 开发者运行 scripts/verify_local_builder_image.sh
actors:
  - local-developer
source_refs:
  - "实现操作矩阵"
  - "无副作用边界"
  - "验收标准"
operations:
  - operation_id: local-verify.validate-input
    trigger: 独立入口启动
    source_sections:
      - "入口与输入契约"
      - "执行流程"
    api_contract:
      status: not_applicable
      evidence: 本操作不调用应用 API 或远程控制面
    client_contract:
      status: covered
      evidence: scripts/verify_local_builder_image.sh 校验路径、CLI、平台和镜像标签
    table_contract:
      status: not_applicable
      evidence: 本操作不读写数据库表
    test_contract:
      status: covered
      evidence: backend/tests/test_local_builder_image_verification.py 参数化非法输入和路径安全测试
    rollback_contract:
      status: covered
      evidence: 删除独立入口即可移除本操作，不需要远程回滚
    audit_contract:
      status: covered
      evidence: 失败 JSON 使用稳定 error_code，结果写入失败只输出脱敏 stderr 诊断
  - operation_id: local-verify.build-head
    trigger: 输入校验通过
    source_sections:
      - "构建调用"
      - "构建脚本兼容增强"
    api_contract:
      status: not_applicable
      evidence: 本操作只调用仓库内共享构建脚本
    client_contract:
      status: covered
      evidence: PUSH=0 和 EXPECTED_BUILD_SHA 绑定当前 HEAD archive
    table_contract:
      status: not_applicable
      evidence: 本操作不读写数据库表
    test_contract:
      status: covered
      evidence: Docker、Podman、hostile env 和确定性 HEAD 竞态测试
    rollback_contract:
      status: covered
      evidence: 删除 EXPECTED_BUILD_SHA 可选断言后现有调用恢复原行为
    audit_contract:
      status: covered
      evidence: source_sha、image、platform 和 build_failed/head_changed 进入结果 JSON
  - operation_id: local-verify.inspect-image
    trigger: 构建成功且 HEAD 未变化
    source_sections:
      - "构建后校验"
    api_contract:
      status: not_applicable
      evidence: inspect 只读取本地容器引擎镜像元数据
    client_contract:
      status: covered
      evidence: Docker 和 Podman 使用 image inspect --format '{{.Id}}'
    table_contract:
      status: not_applicable
      evidence: 本操作不读写数据库表
    test_contract:
      status: covered
      evidence: 精确 argv、非零、空输出、多行和非法 image ID 测试
    rollback_contract:
      status: covered
      evidence: 删除独立入口即停止本地 inspect，不修改线上状态
    audit_contract:
      status: covered
      evidence: 成功结果记录严格匹配 sha256 格式的 image_id
  - operation_id: local-verify.write-result
    trigger: 成功或受控失败形成终态
    source_sections:
      - "结果 JSON 契约"
    api_contract:
      status: not_applicable
      evidence: 结果写入固定本地临时目录，不调用远程 API
    client_contract:
      status: covered
      evidence: Python json 序列化、0600 权限、同目录原子 rename 和唯一 result_path locator
    table_contract:
      status: not_applicable
      evidence: 本操作不读写数据库表
    test_contract:
      status: covered
      evidence: 全错误码字段矩阵、权限、敏感哨兵、路径逃逸和 ENOTDIR 测试
    rollback_contract:
      status: covered
      evidence: 删除结果文件功能不需要远程回滚
    audit_contract:
      status: covered
      evidence: apaas-builder-local-image-verification/v1 白名单字段和禁止字段合同
  - operation_id: local-verify.preserve-worktree
    trigger: 整次本地验证运行
    source_sections:
      - "Git 工作区"
      - "测试设计"
    api_contract:
      status: not_applicable
      evidence: 本操作不调用应用 API 或远程控制面
    client_contract:
      status: covered
      evidence: Git 只允许 rev-parse 和 archive，不执行写操作
    table_contract:
      status: not_applicable
      evidence: 本操作不读写数据库表
    test_contract:
      status: covered
      evidence: staged、unstaged、untracked、ignored 状态字节和 checksum 前后完全相等
    rollback_contract:
      status: covered
      evidence: 发现工作区变化即测试失败，不以 reset、clean 或 stash 恢复
    audit_contract:
      status: covered
      evidence: 测试证据绑定运行前后 git status 和文件 checksum
```

## 决策依据/Rationale

Builder 当前 typed operation contract 只存在于 `business-flow.operations`。使用单一 CLI flow
可以让实现计划直接消费五项操作，同时避免创建不存在的页面、表单、业务对象或线上发布流。

## 后续避坑/Lessons

- 不把“本地”解释为完全离线；基础镜像和依赖可以只读下载。
- 不把这个 typed flow 扩展成镜像推送或 Kubernetes 发布入口。
- 不用 Git 写操作修复测试造成的工作区变化；任何变化都应直接判定实现不合格。
