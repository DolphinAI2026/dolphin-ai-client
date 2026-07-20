# Task 2 Report: 应用级 Engineering Session 所有权

## 改动文件

- `backend/app/engineering_sessions/service.py`
- `backend/app/engineering_sessions/git_state.py`
- `backend/app/engineering_sessions/models.py`
- `backend/app/engineering_sessions/registry.py`
- `backend/tests/test_engineering_sessions_models.py`
- `backend/tests/test_engineering_sessions_service.py`
- `.superpowers/sdd/task-2-report.md`

## 修复摘要

- 带 `origin` 的仓库在本地 control worktree/base branch 完成 merge 后，使用本地
  `refs/heads/<base>` 的祖先关系驱动 `merged_retained` 与 dispose 门禁。
  `git_state.merged_to_base` 仍保留既有远端优先基线语义，远端未推进不会再阻止本地
  merge 生命周期完成。
- merge commit 复用 checkpoint 的受控 Git 身份：
  `ai-builder <ai-builder@local>`，并禁用提交签名。
- 新增确定性的未合并索引检测。只有存在 unmerged index entries 才映射为
  `WORKTREE_MERGE_CONFLICT`；identity、hook、签名等非内容冲突失败保持
  `git_error`/`GitCommandError` 语义。
- merge 失败后的 `git merge --abort` 若返回失败或抛出异常，返回独立错误码
  `WORKTREE_MERGE_ABORT_FAILED`，并把 session 持久化为
  `blocked_retained`、关闭 cleanup 建议。后续 merge/dispose 不会误认为 control
  worktree 已恢复。
- dispose 改为按现存资源分步执行：worktree 已移除时继续检查并删除 branch、prune；
  branch 已删除时继续 prune。任何中间失败均保留 registry 记录，允许同一
  `dispose(session_id)` 重试。
- dispose 全部成功后删除 registry 记录，避免留下仍声称可运行的 session。
- merge abort 恢复失败新增向后兼容的持久化原因
  `recovery_reason=merge_abort_failed`。当 control worktree 已由人工或外部清理、
  不再存在 Git operation 时，`resume`、`sync` 或再次 `merge` 会只解除该特定
  阻塞；其他来源的 `blocked_retained` 不会自动解除。
- 带 `origin` 的 session 在 merge 后执行 `archive` 时，会继续使用
  `merged_commit` 对本地 base branch 的祖先验证，保持 `merged_retained`。
  `git_state.merged_to_base` 的远端优先语义未改变。
- dispose 在目标 branch 存在 prunable worktree 管理记录时，先执行
  `git worktree prune --expire now` 并重读 worktree 状态，再删除 branch。
  prune 中途失败会保留 branch 与 registry，可用同一 `dispose(session_id)` 重试。
- 本地 base 与 session branch 都存在时，生命周期恢复直接检查 branch 是否已成为
  本地 base 的祖先，不再要求 `merged_commit` 已持久化。为避免把尚无 session
  提交的新建 branch 误判为已合并，存在有效 `base_commit` 时还要求 branch 相对
  该提交确有新增提交。branch 已删除时仍使用 `merged_commit` 回退。
- `ensure_application_session` 在 registry 列表读取出现任何
  `last_read_errors` 或 `last_unreadable_ids` 时 fail closed，并在创建 session、
  branch 或 worktree 前抛出 `SessionRegistryError`。
- 未实现 Task 3-6。

## 新增与增强测试

- `test_merge_with_origin_uses_local_base_for_lifecycle_and_dispose`
- `test_merge_uses_controlled_commit_identity`
- `test_non_conflict_merge_commit_failure_is_not_reported_as_conflict`
- `test_merge_conflict_with_abort_failure_blocks_session`
  - 覆盖 abort 非零返回。
  - 覆盖 abort 直接抛出 Git 异常。
- `test_dispose_retries_after_worktree_remove_succeeds_and_branch_delete_fails`
- `test_engineering_session_recovery_reason_is_backward_compatible`
- `test_merge_abort_failure_recovers_after_control_operation_is_cleared`
- `test_manual_blocked_session_without_recovery_reason_stays_blocked`
- `test_merge_with_origin_archive_stays_merged_and_can_dispose`
- `test_dispose_prunes_missing_worktree_metadata_before_branch_delete`
  - 覆盖首次 prune 成功。
  - 覆盖首次 prune 失败后使用同一 session 重试成功。
- `test_ensure_application_session_fails_closed_for_unreadable_registry`
- `test_origin_merge_recovers_without_persisted_merged_commit`
  - 覆盖 registry 中 `merged_commit` 字段缺失。
  - 覆盖 registry 中 `merged_commit: null`。
  - 依次覆盖 `sync`、`archive` 与 `dispose`。
- 增强既有 dispose 成功测试，断言 registry 记录已删除。

## RED 证据

命令：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_service.py -q -k 'merge_with_origin_uses_local_base_for_lifecycle_and_dispose or merge_uses_controlled_commit_identity or non_conflict_merge_commit_failure_is_not_reported_as_conflict or merge_conflict_with_abort_failure_blocks_session or dispose_retries_after_worktree_remove_succeeds_and_branch_delete_fails'
```

输出：

```text
FFFFF
5 failed, 167 deselected in 3.00s
```

失败分别证明：

- 带 origin 的本地 merge 返回 `running`。
- merge commit 缺少受控身份。
- pre-merge hook 失败被误报为 `WORKTREE_MERGE_CONFLICT`。
- abort 失败仍返回 `WORKTREE_MERGE_CONFLICT` 且未持久化阻塞。
- worktree 已删除后第二次 dispose 被 `missing_worktree` 门禁拒绝。

补充 abort 异常 RED：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_service.py::test_merge_conflict_with_abort_failure_blocks_session -q
```

输出：

```text
.F
1 failed, 1 passed in 1.38s
```

失败证明 `git merge --abort` 直接抛出异常时仍会绕过稳定错误码和阻塞持久化。

第二轮 service 场景 RED：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_models.py::test_engineering_session_recovery_reason_is_backward_compatible tests/test_engineering_sessions_service.py -q -k 'merge_abort_failure_recovers_after_control_operation_is_cleared or manual_blocked_session_without_recovery_reason_stays_blocked or merge_with_origin_archive_stays_merged_and_can_dispose or dispose_prunes_missing_worktree_metadata_before_branch_delete'
```

输出：

```text
F.FFF
4 failed, 1 passed, 174 deselected in 2.92s
```

失败分别证明：

- abort 失败未持久化可识别的恢复原因。
- origin merge 后 archive 错误降级为 `abandoned_retained`。
- dispose 未在 branch delete 前处理 prunable worktree 管理记录。
- prune 首次失败后的重试路径不可完成。

第二轮模型兼容性 RED：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_models.py::test_engineering_session_recovery_reason_is_backward_compatible -q
```

输出：

```text
1 failed in 0.11s
```

失败证明旧 registry payload 加载后的 session 尚无向后兼容的恢复原因字段。

第三轮有效 RED：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_service.py -q -k 'ensure_application_session_fails_closed_for_unreadable_registry or origin_merge_recovers_without_persisted_merged_commit'
```

输出：

```text
FFF
3 failed, 178 deselected in 2.21s
```

失败分别证明：

- 损坏 registry 记录存在时，`ensure_application_session` 未抛错并继续创建。
- 带 origin 的本地 merge 在 `merged_commit` 字段缺失时，`sync` 保持
  `running`。
- 带 origin 的本地 merge 在 `merged_commit: null` 时，`sync` 保持
  `running`。

## GREEN 证据

新增核心场景：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_service.py -q -k 'merge_with_origin_uses_local_base_for_lifecycle_and_dispose or merge_uses_controlled_commit_identity or non_conflict_merge_commit_failure_is_not_reported_as_conflict or merge_conflict_with_abort_failure_blocks_session or dispose_retries_after_worktree_remove_succeeds_and_branch_delete_fails'
```

输出：

```text
5 passed, 167 deselected in 3.48s
```

abort 返回失败与异常失败：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_service.py::test_merge_conflict_with_abort_failure_blocks_session -q
```

输出：

```text
2 passed in 0.97s
```

Task 2 service 聚焦集合：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_service.py -q -k 'ensure_application_session or merge_keeps_worktree or merge_with_origin or merge_uses_controlled or merge_conflict or non_conflict_merge or dispose_refuses_dirty or dispose_removes_clean or dispose_retries'
```

输出：

```text
14 passed, 158 deselected in 4.89s
```

Task 2 CLI 聚焦集合：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_cli.py -q -k 'cli_merge_keeps_worktree_and_dispose_removes_it or cli_merge_conflict_uses_worktree_merge_conflict_error_code'
```

输出：

```text
2 passed, 12 deselected in 2.48s
```

第二轮模型兼容性：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_models.py::test_engineering_session_recovery_reason_is_backward_compatible -q
```

输出：

```text
1 passed in 0.09s
```

第二轮新增 service 场景：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_service.py -q -k 'merge_abort_failure_recovers_after_control_operation_is_cleared or manual_blocked_session_without_recovery_reason_stays_blocked or merge_with_origin_archive_stays_merged_and_can_dispose or dispose_prunes_missing_worktree_metadata_before_branch_delete'
```

输出：

```text
5 passed, 173 deselected in 3.73s
```

第二轮 service 广泛回归：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_service.py -q -k 'blocked or merge or dispose or archive'
```

输出：

```text
53 passed, 125 deselected in 18.40s
```

第二轮 models 与 CLI 回归：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_models.py tests/test_engineering_sessions_cli.py -q
```

输出：

```text
20 passed in 8.50s
```

第三轮新增场景：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_service.py -q -k 'ensure_application_session_fails_closed_for_unreadable_registry or origin_merge_recovers_without_persisted_merged_commit'
```

输出：

```text
3 passed, 178 deselected in 1.80s
```

第三轮既有 ensure 生命周期回归：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_service.py -q -k 'ensure_application_session_reuses_the_same_worktree or ensure_application_session_is_unique_across_concurrent_services or ensure_application_session_rejects_duplicate_active_ownership'
```

输出：

```text
3 passed, 178 deselected in 0.96s
```

第三轮 Task 2 聚焦回归：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_service.py -q -k 'ensure_application_session or merge_with_origin or origin_merge_recovers_without_persisted_merged_commit or archive or dispose'
```

输出：

```text
31 passed, 150 deselected in 10.66s
```

完整 Engineering Session 集合：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_models.py tests/test_engineering_sessions_service.py tests/test_engineering_sessions_cli.py -q
```

输出：

```text
201 passed in 51.73s
```
