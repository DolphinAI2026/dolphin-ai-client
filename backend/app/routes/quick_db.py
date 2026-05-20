"""
DB 问数 wizard 的后端 — **薄收口版本**：

    POST /api/quick-db/test-connection
        填完 DB 连接 → 真实连库 → 拉 information_schema 看有哪些表
        顺便跑一次 table_classifier 把分类（green/yellow/red/skip）一并返回，
        前端 Step 2 直接渲染 health badge。
        返回: {ok, db_type, db_label, tables, classifications}

    POST /api/quick-db/build-spec
        用户走完 4 步 wizard 后调一次：拉 schema → 分类 → 生成 SPEC v2 markdown，
        返回 {spec_md, app_name, app_code, db_label}。
        前端拿到 spec_md 后包成 File 走 ChatPage 的 "上传 .md" 主线，
        最终 generator_v2 接管创建应用 —— 不再在这里跑 orchestrator。

历史背景：之前这里有 /start + /stream/{task_id} SSE 自实现 orchestrator
（datasource + model + form 一条龙建），跟 ChatPage 的主线生成器是两条路。
2026-05-19 收敛：wizard 只负责把 DB schema 翻译成 SPEC markdown，
之后完全交给 ChatPage / generator_v2 主线，避免双轨维护。

当前 MVP 只支持 MYSQL（已有 aiomysql 依赖）。其他 DB 类型返回 501。
"""
from __future__ import annotations
import asyncio
import logging
import re
import uuid
from typing import Annotated, Literal, Optional, Any

import aiomysql
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.models import User
from app.auth import get_current_user
from app.deps import get_auth_context, AuthContext

# table_classifier 已落地，spec_builder 可能由并行 agent 在写 —— 用 try/except
# 兜住，让后端在两个 module 都缺时仍能启动。
try:
    from app.quick_db.table_classifier import classify_tables  # type: ignore
except ImportError:  # pragma: no cover
    def classify_tables(schemas: dict[str, dict]) -> dict[str, dict]:  # type: ignore
        return {}

try:
    from app.quick_db.spec_builder import build_spec_markdown  # type: ignore
except ImportError:  # pragma: no cover
    async def build_spec_markdown(  # type: ignore
        *,
        db_label: str,
        app_name: str,
        app_code: str,
        hint: str,
        schemas: dict[str, dict],
        classifications: dict[str, dict],
        selected_tables: list[str],
    ) -> str:
        # 降级 stub：spec_builder 还没写完时给出最朴素的 placeholder，
        # 让前端能把"流程跑通"看见错误，而不是后端 500。
        head = (
            f"# {app_name}\n\n"
            f"> 自动生成自 {db_label}（spec_builder 模块缺失，落到 stub）\n\n"
        )
        body = "\n".join(f"- 选中表：{t}" for t in selected_tables)
        return head + body + "\n"


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quick-db", tags=["quick-db"])


# ─── schemas ───────────────────────────────────────────────────────────────

# 数据库类型 — aPaaS 真实 dropdown 大小写敏感（实测）：
# MYSQL / PostgreSQL / SQLServer / ORACLE / DAMENG / KingBase
DbType = Literal["MYSQL", "PostgreSQL", "SQLServer", "ORACLE", "DAMENG", "KingBase"]


class DbConnReq(BaseModel):
    type: DbType
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    database: str = Field(min_length=1)
    username: str = Field(min_length=1)
    password: str
    alias: Optional[str] = None


class TableInfo(BaseModel):
    name: str
    fields: int


class TestConnResp(BaseModel):
    ok: bool
    db_type: str
    db_label: str             # "host:port/db" 用于前端显示
    tables: list[TableInfo] = []
    classifications: dict[str, Any] = {}  # {table_name: {health, badge, reason, flags}}
    error: Optional[str] = None


class BuildSpecReq(BaseModel):
    # 二选一：直接传 db 凭证（新建模式）或者 connection_id（用已保存连接）
    db: Optional[DbConnReq] = None
    connection_id: Optional[int] = None
    tables: list[str]                              # 用户勾选的表名
    hint: str = ""                                 # 一句话业务描述（驱动字段语义推断）
    style: Literal["oa", "dashboard", "mobile"] = "oa"
    app_name: Optional[str] = None                 # 留空则用 DB 名


class BuildSpecResp(BaseModel):
    ok: bool
    spec_md: str = ""        # 生成的 SPEC v2 markdown
    app_name: str = ""
    app_code: str = ""       # kebab-case
    db_label: str = ""
    error: Optional[str] = None


# ─── routes ────────────────────────────────────────────────────────────────


@router.post("/test-connection", response_model=TestConnResp)
async def test_connection(
    payload: DbConnReq,
    user: Annotated[User, Depends(get_current_user)],
):
    """实际连 DB 拉表清单 + 一次 schema 拉满字段元数据 + 跑分类器。

    凭证只在这次调用内存里，不存任何地方 —— 用户真"生成应用"时由 SPEC → generator_v2
    主线建数据源时才会持久化。
    """
    db_label = f"{payload.host}:{payload.port}/{payload.database}"
    logger.info("quick-db test-connection by user=%s db=%s type=%s",
                user.id, db_label, payload.type)

    if payload.type != "MYSQL":
        return TestConnResp(
            ok=False,
            db_type=payload.type,
            db_label=db_label,
            error=f"暂未支持 {payload.type}（MVP 阶段只接通 MySQL，PostgreSQL/Oracle/SQLServer 在路线图上）",
        )

    try:
        tables = await _list_mysql_tables(
            host=payload.host,
            port=payload.port,
            user=payload.username,
            password=payload.password,
            db_name=payload.database,
        )
    except (aiomysql.OperationalError, asyncio.TimeoutError) as e:
        return TestConnResp(
            ok=False, db_type=payload.type, db_label=db_label,
            error=f"连不上：{e}",
        )
    except Exception as e:
        logger.exception("test-connection unexpected error")
        return TestConnResp(
            ok=False, db_type=payload.type, db_label=db_label,
            error=f"未预期错误：{type(e).__name__}: {e}",
        )

    # 拉到表了再多跑一次 schema 拉字段元数据，给分类器用。
    # 真表多（67 张）时这步也只是一次 information_schema query，便宜。
    classifications: dict[str, Any] = {}
    if tables:
        try:
            table_names = [t.name for t in tables]
            schemas = await _query_mysql_schemas(
                host=payload.host, port=payload.port,
                user=payload.username, password=payload.password,
                db_name=payload.database, tables=table_names,
            )
            classifications = dict(classify_tables(schemas))  # 转成普通 dict 给 pydantic
        except Exception as e:
            # 分类失败不阻塞主流程 —— 前端拿不到 badge 但表清单照常给。
            logger.warning("quick-db classify failed (continuing without badges): %s", e)

    return TestConnResp(
        ok=True, db_type=payload.type, db_label=db_label,
        tables=tables, classifications=classifications,
    )


@router.post("/build-spec", response_model=BuildSpecResp)
async def build_spec(
    payload: BuildSpecReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """把用户选好的表 + 业务描述翻成 SPEC v2 markdown，**不创建任何 aPaaS 资源**。

    前端拿到 spec_md 后会把它包成一个 .md File 塞进 previewStore.pendingFile，
    跳到 /chat → ChatPage 用 uploadDocFile 走主线 generator_v2 接管。

    支持两种凭证来源：
    - payload.db: 直接传明文凭证（wizard "新建连接" 模式）
    - payload.connection_id: 引用已保存的 db_connections 记录（wizard "已有连接" 模式）
    """
    # ── Step 0: 解出 (db_type, host, port, database, username, password) ─────────
    db_type: str
    host: str
    port: int
    database: str
    username: str
    password: str
    if payload.connection_id:
        # 用已保存连接：从 db_connections 表加载 + 解密密码
        from app.database import AsyncSessionLocal
        from app.models import DbConnection
        from app.crypto import decrypt_password
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            q = await db.execute(
                select(DbConnection).where(
                    DbConnection.id == payload.connection_id,
                    DbConnection.tenant_id == ctx.tenant_id,
                )
            )
            conn = q.scalar_one_or_none()
        if not conn:
            return BuildSpecResp(ok=False, error=f"找不到 db_connection id={payload.connection_id}")
        if not conn.password_enc:
            return BuildSpecResp(ok=False, error=f"连接 {conn.name} 没有保存密码，请去「数据库连接」编辑补全")
        db_type = conn.db_type
        host = conn.host; port = conn.port
        database = conn.database_name
        username = conn.username
        try:
            password = decrypt_password(conn.password_enc)
        except Exception as e:
            return BuildSpecResp(ok=False, error=f"密码解密失败: {e}")
    elif payload.db:
        db_type = payload.db.type
        host = payload.db.host; port = payload.db.port
        database = payload.db.database
        username = payload.db.username
        password = payload.db.password
    else:
        return BuildSpecResp(ok=False, error="必须传 db 凭证或 connection_id")

    db_label = f"{host}:{port}/{database}"
    logger.info(
        "quick-db build-spec by user=%s tenant=%s db=%s conn_id=%s tables=%d hint_len=%d",
        ctx.user.id, ctx.tenant_id, db_label, payload.connection_id,
        len(payload.tables), len(payload.hint),
    )

    if db_type != "MYSQL":
        return BuildSpecResp(
            ok=False, db_label=db_label,
            error=f"暂未支持 {db_type}（MVP 阶段只接通 MySQL）",
        )
    if not payload.tables:
        return BuildSpecResp(
            ok=False, db_label=db_label, error="至少要勾选一张表",
        )

    # 1. 拉 schemas
    try:
        schemas = await _query_mysql_schemas(
            host=host, port=port,
            user=username, password=password,
            db_name=database, tables=payload.tables,
        )
    except (aiomysql.OperationalError, asyncio.TimeoutError) as e:
        return BuildSpecResp(ok=False, db_label=db_label, error=f"连不上 DB：{e}")
    except Exception as e:
        logger.exception("build-spec query schema failed")
        return BuildSpecResp(
            ok=False, db_label=db_label,
            error=f"读 DB schema 失败: {type(e).__name__}: {e}",
        )

    if not schemas:
        return BuildSpecResp(
            ok=False, db_label=db_label,
            error="读不到任何字段元数据（表名不存在？）",
        )

    # 2. 分类
    classifications = dict(classify_tables(schemas))

    # 3. 派生 app 标识
    app_name = payload.app_name or f"DB-{database}"
    app_code = _derive_app_code(database)

    # 4. 生成 SPEC markdown
    try:
        spec_md = await build_spec_markdown(
            db_label=db_label, app_name=app_name, app_code=app_code,
            hint=payload.hint, schemas=schemas, classifications=classifications,
            selected_tables=payload.tables,
        )
    except Exception as e:
        logger.exception("build-spec markdown render failed")
        return BuildSpecResp(
            ok=False, db_label=db_label,
            error=f"生成 SPEC 失败: {type(e).__name__}: {e}",
        )

    return BuildSpecResp(
        ok=True, spec_md=spec_md, app_name=app_name,
        app_code=app_code, db_label=db_label,
    )


# ─── helpers ───────────────────────────────────────────────────────────────


def _derive_app_code(database: str) -> str:
    """aPaaS app_code 规则：**kebab-case**（实测连字符 OK，下划线被 bizCode 7012 拒）。

    历史成功示例: `talent-mgmt`, `expense-mgmt`。
    qdb- 前缀让运维一眼能看出"DB 问数 wizard 产出"，6 位随机后缀避撞重名。
    """
    safe = re.sub(r"[^a-z0-9]", "-", database.lower()).strip("-") or "db"
    suffix = "".join(chr(ord('a') + (b % 26)) for b in uuid.uuid4().bytes[:6])
    return f"qdb-{safe}-{suffix}"


# ─── DB schema 读取（直连客户 DB） ─────────────────────────────────────


async def _query_mysql_schemas(
    host: str, port: int, user: str, password: str, db_name: str, tables: list[str],
) -> dict[str, dict]:
    """批量拉指定表的字段元数据。一次 information_schema query 拿全。

    返回: {table_name: {"pk": pk_field_or_none, "fields": [{name, type, nullable, comment, is_pk}]}}
    """
    if not tables:
        return {}
    conn: Optional[aiomysql.Connection] = None
    try:
        conn = await asyncio.wait_for(
            aiomysql.connect(
                host=host, port=port, user=user, password=password, db=db_name,
                charset="utf8mb4", autocommit=True,
            ),
            timeout=10.0,
        )
        async with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(tables))
            await cur.execute(
                f"""
                SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_COMMENT, COLUMN_KEY
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({placeholders})
                ORDER BY TABLE_NAME, ORDINAL_POSITION
                """,
                (db_name, *tables),
            )
            rows = await cur.fetchall()

        result: dict[str, dict] = {t: {"pk": None, "fields": []} for t in tables}
        for tn, cn, ct, nullable, comment, key in rows:
            is_pk = key == "PRI"
            field = {
                "name": cn,
                "type": ct,
                "nullable": nullable == "YES",
                "comment": (comment or "").strip(),
                "is_pk": is_pk,
            }
            result.setdefault(tn, {"pk": None, "fields": []})["fields"].append(field)
            if is_pk and not result[tn]["pk"]:
                result[tn]["pk"] = cn
        return result
    finally:
        if conn is not None:
            conn.close()


async def _list_mysql_tables(
    host: str, port: int, user: str, password: str, db_name: str,
) -> list[TableInfo]:
    """通过 information_schema 一次 query 同时拿表名 + 字段数。

    用 10s connect timeout — 客户内网 DB 慢但不要无限挂死。
    凭证不存日志、不存 DB；连接 close 后即抛弃。
    """
    conn: Optional[aiomysql.Connection] = None
    try:
        conn = await asyncio.wait_for(
            aiomysql.connect(
                host=host, port=port, user=user, password=password, db=db_name,
                charset="utf8mb4", autocommit=True,
            ),
            timeout=10.0,
        )
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT
                    t.TABLE_NAME,
                    (SELECT COUNT(*) FROM information_schema.COLUMNS c
                     WHERE c.TABLE_SCHEMA = t.TABLE_SCHEMA AND c.TABLE_NAME = t.TABLE_NAME) AS field_count
                FROM information_schema.TABLES t
                WHERE t.TABLE_SCHEMA = %s AND t.TABLE_TYPE = 'BASE TABLE'
                ORDER BY t.TABLE_NAME
                """,
                (db_name,),
            )
            rows = await cur.fetchall()
        return [TableInfo(name=r[0], fields=int(r[1])) for r in rows]
    finally:
        if conn is not None:
            conn.close()
