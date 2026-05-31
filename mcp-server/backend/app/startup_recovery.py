"""启动时清理"悬挂"的 coding session。

背景：coding / verify 是 asyncio.create_task 起的后台任务，uvicorn --reload 或
崩溃重启时会被 SIGKILL，留下 coding_sessions.status='running' 的行，
conversation 永远停在 verify/generate 阶段，前端 SSE 流就此停滞。

本模块在 main.py lifespan startup 阶段扫一次：
- 若某 running 行对应的 conversation 最近一条 event 超过 STALE_MINUTES 没动静，
  判定为死任务
- 原子 UPDATE status='running'→'aborted'（WHERE status='running' 保证多 worker
  并发时只有一个 worker 抢到）
- 抢到的行补发 coding.failed 事件，前端 store 翻到 phase='failed'

【多 worker 说明】生产用 `--workers 2`，两个 worker 各自启动都会跑这个扫描。
UPDATE 原子性保证同一行只被一个 worker 标记；threshold 设 10 min 比较保守，
避免误杀真在跑但 LLM 长推理静默的任务。详见 DEPLOY.md 的"多进程 / 多 Pod"章节。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import text

from app.agents.db_publisher import get_db_publisher
from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# 一个 coding session 多久没产出 event 判定为死。
# 设得保守：coding.done → phase_changed(verify) 之间曾观察到 2min 间隔，
# LLM 单次响应最长见过 ~20s，留足余量。
STALE_MINUTES = 10


async def sweep_dead_coding_sessions() -> int:
    """清理悬挂 coding session。返回被清理的条数。

    幂等 + 多 worker 并发安全（靠原子 UPDATE）。
    """
    stale_before = datetime.utcnow() - timedelta(minutes=STALE_MINUTES)
    ended_at = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text("""
            SELECT *
            FROM (
                SELECT cs.id, cs.conversation_id,
                       COALESCE(
                           (SELECT MAX(created_at) FROM conversation_events
                            WHERE conversation_id = cs.conversation_id),
                           cs.created_at
                       ) AS last_activity_at
                FROM coding_sessions cs
                WHERE cs.status = 'running'
                  AND cs.created_at < :stale_before
            ) stale_sessions
            WHERE last_activity_at < :stale_before
        """), {"stale_before": stale_before})).mappings().all()

        if not rows:
            logger.info("startup recovery: no stale coding_sessions")
            return 0

        publisher = get_db_publisher()
        recovered = 0
        for row in rows:
            cs_id = row["id"]
            conv_id = row["conversation_id"]

            result = await db.execute(text("""
                UPDATE coding_sessions
                SET status = 'aborted',
                    error_message = '进程启动时发现悬挂任务（上次可能是 reload / 崩溃）',
                    ended_at = :ended_at
                WHERE id = :cs_id AND status = 'running'
            """), {"cs_id": cs_id, "ended_at": ended_at})
            await db.commit()
            if result.rowcount != 1:
                continue  # 另一个 worker 先抢到了

            try:
                await publisher.publish(
                    conversation_id=conv_id,
                    event_type="coding.failed",
                    agent="orchestrator",
                    session_id=cs_id,
                    data={
                        "message": "上次任务被中断（进程重启），请重新触发。",
                        "reason": "process_restart",
                        "coding_session_id": cs_id,
                    },
                    db=db,
                )
            except Exception as e:
                logger.warning(
                    "startup recovery: publish coding.failed for %s failed: %s",
                    cs_id, e,
                )
            recovered += 1
            logger.warning(
                "startup recovery: aborted coding_session=%s conv=%s "
                "(last_activity_at=%s)",
                cs_id, conv_id, row["last_activity_at"],
            )

        logger.warning(
            "startup recovery: aborted %d dead coding_sessions (threshold=%d min)",
            recovered, STALE_MINUTES,
        )
        return recovered
