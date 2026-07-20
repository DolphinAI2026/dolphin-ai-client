# Task 2 Report: 应用级 Engineering Session 所有权

## 改动文件

- `backend/app/engineering_sessions/service.py`
- `backend/app/engineering_sessions/git_state.py`
- `backend/app/engineering_sessions/registry.py`
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
- 未实现 Task 3-6。

## 新增与增强测试

- `test_merge_with_origin_uses_local_base_for_lifecycle_and_dispose`
- `test_merge_uses_controlled_commit_identity`
- `test_non_conflict_merge_commit_failure_is_not_reported_as_conflict`
- `test_merge_conflict_with_abort_failure_blocks_session`
  - 覆盖 abort 非零返回。
  - 覆盖 abort 直接抛出 Git 异常。
- `test_dispose_retries_after_worktree_remove_succeeds_and_branch_delete_fails`
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

完整 Engineering Session 集合：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_models.py tests/test_engineering_sessions_service.py tests/test_engineering_sessions_cli.py -q
```

输出：

```text
192 passed in 44.95s
```
