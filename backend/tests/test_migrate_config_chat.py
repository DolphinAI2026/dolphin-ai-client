"""B1: config_chat_* → ai_chat_* 一次性幂等迁移测试

验收条件:
1. config_chat_sessions / config_chat_messages 复制到 ai_chat_sessions / ai_chat_messages
2. tool_trace_json → ai_chat_tool_calls 行
3. change_plan_json + actions_summary_json 折进 ai_chat_messages.extra_meta
4. migrated_session_id 回写（幂等标记）
5. app_id 正确传递
6. 第二次运行幂等（不重复插入）
7. tool_call 字段保真（tool_name / status / result_text / duration_ms）
8. 增量迁移：第一次迁完后新增的 config 会话在第二次调用时被迁移
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from app.database import Base, _migrate_config_chat_to_ai_chat
import app.models.ai_chat  # noqa: F401  (register tables)
import app.models.config_chat  # noqa: F401


@pytest.mark.asyncio
async def test_migration_copies_and_is_idempotent():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "INSERT INTO config_chat_sessions(id,app_id,tenant_id,user_id,title,created_at,updated_at) "
            "VALUES (1,42,7,3,'调字段','2026-06-01 00:00:00','2026-06-01 00:00:00')"))
        await conn.execute(text(
            "INSERT INTO config_chat_messages(id,session_id,role,content,created_at) "
            "VALUES (1,1,'user','把电话改必填','2026-06-01 00:00:00')"))
        trace_json = '[{"tool_name":"update_apaas_model_field","args":{"env_id":5},"ok":true,"summary":"ok","duration_ms":120}]'
        plan_json = '{"changes":[1]}'
        summary_json = '["电话改必填"]'
        await conn.execute(
            text(
                "INSERT INTO config_chat_messages(id,session_id,role,content,tool_trace_json,change_plan_json,actions_summary_json,created_at) "
                "VALUES (2,1,'assistant','已改',:trace,:plan,:summary,'2026-06-01 00:00:00')"
            ),
            {"trace": trace_json, "plan": plan_json, "summary": summary_json},
        )
        await _migrate_config_chat_to_ai_chat(conn)
        n1 = (await conn.execute(text("SELECT COUNT(*) FROM ai_chat_sessions"))).scalar()
        m1 = (await conn.execute(text("SELECT COUNT(*) FROM ai_chat_messages"))).scalar()
        t1 = (await conn.execute(text("SELECT COUNT(*) FROM ai_chat_tool_calls"))).scalar()
        marker = (await conn.execute(text("SELECT migrated_session_id FROM config_chat_sessions WHERE id=1"))).scalar()
        new_app_id = (await conn.execute(text("SELECT app_id FROM ai_chat_sessions LIMIT 1"))).scalar()
        new_extra = (await conn.execute(text("SELECT extra_meta FROM ai_chat_messages WHERE role='assistant'"))).scalar()
        # tool_call 字段保真验证
        tc_row = (await conn.execute(text(
            "SELECT tool_name, status, result_text, duration_ms FROM ai_chat_tool_calls LIMIT 1"
        ))).fetchone()
        assert tc_row[0] == "update_apaas_model_field"
        assert tc_row[1] == "success"   # ok=true → success
        assert tc_row[2] == "ok"        # result_text = summary
        assert tc_row[3] == 120
        await _migrate_config_chat_to_ai_chat(conn)  # second run — idempotent
        n2 = (await conn.execute(text("SELECT COUNT(*) FROM ai_chat_sessions"))).scalar()

    assert n1 == 1 and m1 == 2 and t1 == 1
    assert marker is not None
    assert new_app_id == 42
    assert new_extra and "电话改必填" in new_extra  # change_plan/actions_summary folded into extra_meta
    assert n2 == 1  # idempotent


@pytest.mark.asyncio
async def test_incremental_migration_picks_up_new_sessions():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "INSERT INTO config_chat_sessions(id,app_id,tenant_id,user_id,title,created_at,updated_at) "
            "VALUES (1,42,7,3,'s1','2026-06-01 00:00:00','2026-06-01 00:00:00')"))
        await _migrate_config_chat_to_ai_chat(conn)
        assert (await conn.execute(text("SELECT COUNT(*) FROM ai_chat_sessions"))).scalar() == 1
        # 第一次迁完后又来一条新 config 会话
        await conn.execute(text(
            "INSERT INTO config_chat_sessions(id,app_id,tenant_id,user_id,title,created_at,updated_at) "
            "VALUES (2,43,7,3,'s2','2026-06-02 00:00:00','2026-06-02 00:00:00')"))
        await _migrate_config_chat_to_ai_chat(conn)
        n = (await conn.execute(text("SELECT COUNT(*) FROM ai_chat_sessions"))).scalar()
        migrated_markers = (await conn.execute(text(
            "SELECT COUNT(*) FROM config_chat_sessions WHERE migrated_session_id IS NOT NULL"))).scalar()
    assert n == 2          # 新会话被增量迁移
    assert migrated_markers == 2
