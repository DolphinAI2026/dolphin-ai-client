# Cloud Deploy Validation - 2026-04-27

## Scope

- Target: `https://agent.dfy.definesys.cn/ai-builder/`
- Backend service: `apaas-builder-backend.service`
- Web IDE service: `apaas-code-server.service`
- Legacy duplicate IDE service: `apaas-builder-ide.service` disabled/inactive

No credentials are recorded in this document.

## Deployed Changes

- Backend: added Vibe Coding API and compatibility migration coverage for current application/conversation schema.
- Frontend: changed Vibe Coding new-workspace entry from repository-import-first to chat/SPEC-first.
- Web IDE extension: current `ruijing-ai` build deployed in code-server extension directory.

## Production Service Checks

| Check | Result |
| --- | --- |
| Backend systemd status | active |
| Code-server systemd status | active |
| Duplicate old IDE service | inactive |
| Local backend health | `200` |
| Public backend health | `200` |
| Public frontend entry | `200` |
| Backend port | `8003` |
| Code-server port | `8080` |
| Nginx HTTPS | `443` |

## API Smoke Results

All 14 smoke checks passed after applying the database compatibility migration.

| Flow | Check | Result |
| --- | --- | --- |
| Infrastructure | Cloud health | pass |
| 0-1 low-code | Coding scenes API | pass |
| 0-1 low-code | Application list API | pass |
| 0-1 low-code | Requirements conversation create | pass |
| 0-1 low-code | Draft application auto-create | pass |
| Low-code secondary dev | Coding workspace create | pass |
| Low-code secondary dev | Coding workspace file list | pass |
| Full-code vibe coding | Public Git repository import | pass with Gitee mirror |
| Full-code vibe coding | Imported file read | pass |
| Full-code vibe coding | IDE URL generation | pass |
| Cleanup | Vibe Coding workspace delete | pass |
| Cleanup | Coding workspace delete | pass |
| Cleanup | Draft app delete | pass |
| Cleanup | Temporary conversation DB cleanup | pass |

## Frontend Evidence

- Chat-first Vibe Coding entry: `docs/internal/test-evidence-2026-04-27/cloud-online-new-chat-first-1440.png`

Validated text checks:

- `先把需求聊清楚`: present
- `开发 SPEC`: present
- `代码仓库` as secondary setup: present
- Old hero `先把需求和仓库接进来`: absent

## Remaining Environment Note

GitHub access from the ECS host timed out during `git ls-remote`, while Gitee and GitCode were reachable. Full-code import was therefore verified against `https://gitee.com/mirrors/git.git`. GitHub repository import requires either network/proxy improvement on ECS or use of a reachable Git provider/mirror.
