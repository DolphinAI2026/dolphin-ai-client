# DevOps Workbench Handoff - 2026-04-27

## Branch And Worktree

- Worktree: `/Users/mars/Vibe Coding/Cursor/apaas-builder-ai-devops`
- Branch: `codex/devops-workbench`
- Base commit: `090dc59`

This worktree was created separately from `/Users/mars/Vibe Coding/apaas-builder-ai` so it does not overwrite the other Codex session's dirty worktree.

## Changed Files

- `frontend/src/views/BuilderDevOpsPage.vue`

## What Changed

The old `/devops` page was mostly a placeholder with mock tabs. It is now a real workbench-style page with:

- left-side DevOps navigation with counts
- top summary metrics for selected app, pending proposals, Git state, and delivery state
- overview delivery track
- proposal list with status filters
- apply history timeline
- Git repository panel with init repo, Git setup, and drift check actions
- pipeline stage view derived from proposal/Git/environment state
- run history derived from proposal/apply records
- environment topology panel
- approval center derived from actionable proposal statuses

## Reused Existing APIs

- `applicationApi.list()`
- `proposalsApi.list(applicationId)`
- `gitConnectionApi.initRepo(applicationId)`
- `gitConnectionApi.driftStatus(applicationId)`

No backend route was added for this pass.

## Intentional Product Direction

The page should feel like a backstage operations surface, not a marketing page. It should use existing Builder tokens, quiet surfaces, and task-oriented navigation.

Main rule: DevOps should make the current delivery state obvious without requiring explanatory copy.

## Integration Notes For The Other Codex Session

1. Merge only `frontend/src/views/BuilderDevOpsPage.vue` first.
2. If there is a conflict, prefer the other session's router/nav changes, then re-apply this file's internal page structure.
3. Do not move the AI Builder / 自开发 / Chat workbench entry logic into this page.
4. `/devops?tab=git-repo&application_id=<id>` remains the intended deep-link shape.
5. Backend can later replace the derived pipeline/run data with real run records without changing the page IA.

## Validation

Passed:

```bash
npm run build:nocheck --prefix frontend
```

Browser checked on the isolated dev server:

```text
http://127.0.0.1:5174/ai-builder/devops
http://127.0.0.1:5174/ai-builder/devops?tab=git-repo
http://127.0.0.1:5174/ai-builder/devops?tab=pipelines
```

Evidence screenshots were captured through Playwright as:

- `devops-workbench-1440.png`
- `devops-git-repo-1440.png`
- `devops-pipeline-1440.png`

Runtime console check: no errors. Only existing Vue Router `next()` deprecation warnings were observed.

Not passed as a clean repo-wide check:

```bash
npm run build --prefix frontend
```

The full build is blocked by existing repo-wide `vue-tsc` errors in unrelated files such as `ChatPage.vue`, `CodingPage.vue`, `StructuredDocDiffRenderer.vue`, `stores/spec.ts`, and others. The DevOps page was not the source of the observed type-check failures.

## Remaining Follow-Ups

- Add a backend run-history endpoint when pipeline execution becomes real.
- Add a backend environment topology endpoint if demo environment cards need to become tenant-specific.
- After merging with the other Codex session, open `/devops` and `/devops?tab=git-repo` in the browser against the live dev server for visual QA.
