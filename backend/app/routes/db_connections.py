"""
数据库连接管理 API 路由 — platform_envs 的兄弟模块。

- 7 个 endpoint，全部 tenant scope + auth required
- password 用 fernet 加密（复用 app.crypto）
- 表清单 + 分类复用 app.routes.quick_db 内部函数 (_list_mysql_tables / _query_mysql_schemas)
  以及 app.quick_db.table_classifier.classify_tables
- response 一律不返 password；DB 列名 database_name → API 字段 alias 回 `database`
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import encrypt_password, decrypt_password
from app.database import get_db
from app.deps import (
    AuthContext,
    get_auth_context,
    is_control_plane_context,
    resolve_effective_tenant_id,
)
from app.models import DbConnection

# 直接复用 quick_db 的 MySQL 读取实现，避免 connector 重复造轮子。
from app.routes.quick_db import _list_mysql_tables, _query_mysql_schemas

try:
    from app.quick_db.table_classifier import classify_tables  # type: ignore
except ImportError:  # pragma: no cover
    def classify_tables(schemas: dict[str, dict]) -> dict[str, dict]:  # type: ignore
        return {}


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/db-connections", tags=["db-connections"])


def _reject_control_plane_local_database(ctx: AuthContext) -> None:
    if is_control_plane_context(ctx):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CONTROL_PLANE_REMOTE_MANAGEMENT_REQUIRED",
                "message": "远程数据库连接由 Control Plane 管理，本地 Builder 不使用租户 SQLite 配置",
            },
        )


async def _local_database_tenant_id(db: AsyncSession, ctx: AuthContext) -> int:
    _reject_control_plane_local_database(ctx)
    return await resolve_effective_tenant_id(db, ctx)


# ============================================================
# 请求/响应模型
# ============================================================

DbType = Literal["MYSQL", "PostgreSQL", "SQLServer", "ORACLE", "DAMENG", "KingBase"]


class DbConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    db_type: DbType
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    database: str = Field(min_length=1)  # 内部存 database_name
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    description: Optional[str] = None


class DbConnectionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    db_type: Optional[DbType] = None
    host: Optional[str] = Field(default=None, min_length=1)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    database: Optional[str] = Field(default=None, min_length=1)
    username: Optional[str] = Field(default=None, min_length=1)
    password: Optional[str] = Field(default=None, min_length=1)  # 省略则保留原密码
    description: Optional[str] = None


class DbConnectionResp(BaseModel):
    id: int
    name: str
    db_type: str
    host: str
    port: int
    database: str  # 来自 database_name
    username: str
    description: Optional[str] = None
    status: str
    last_tested_at: Optional[str] = None
    table_count: int = 0
    created_at: str


class TestResp(BaseModel):
    ok: bool
    table_count: int = 0
    error: Optional[str] = None


class TablesResp(BaseModel):
    tables: list[dict[str, Any]]  # [{name, fields}, ...]
    classifications: dict[str, Any]


# ============================================================
# Helpers
# ============================================================


def _to_resp(conn: DbConnection) -> DbConnectionResp:
    return DbConnectionResp(
        id=conn.id,
        name=conn.name,
        db_type=conn.db_type,
        host=conn.host,
        port=conn.port,
        database=conn.database_name,
        username=conn.username,
        description=conn.description,
        status=conn.status,
        last_tested_at=conn.last_tested_at.isoformat() if conn.last_tested_at else None,
        table_count=conn.table_count or 0,
        created_at=conn.created_at.isoformat() if conn.created_at else "",
    )


async def _get_owned_conn(
    db: AsyncSession,
    conn_id: int,
    tenant_id: int,
) -> DbConnection:
    result = await db.execute(
        select(DbConnection).where(
            DbConnection.id == conn_id,
            DbConnection.tenant_id == tenant_id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="数据库连接不存在")
    return conn


async def _probe_mysql_tables(
    conn: DbConnection,
    password: str,
) -> list[Any]:
    """连库拉表清单（仅 MYSQL 真实连接，其它类型先回空，不抛 500）。"""
    if conn.db_type != "MYSQL":
        # 占位：未来接 PostgreSQL / SQLServer / Oracle 等 driver 时这里扩展
        raise NotImplementedError(f"暂未支持 {conn.db_type}（MVP 阶段只接通 MySQL）")
    return await _list_mysql_tables(
        host=conn.host,
        port=conn.port,
        user=conn.username,
        password=password,
        db_name=conn.database_name,
    )


# ============================================================
# CRUD 接口
# ============================================================


@router.post("", response_model=DbConnectionResp)
async def create_db_connection(
    data: DbConnectionCreate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """创建数据库连接（password 必填，存 fernet 加密）。"""
    tenant_id = await _local_database_tenant_id(db, ctx)
    conn = DbConnection(
        tenant_id=tenant_id,
        created_by_user_id=ctx.user.id,
        name=data.name,
        db_type=data.db_type,
        host=data.host,
        port=data.port,
        database_name=data.database,
        username=data.username,
        password_enc=encrypt_password(data.password),
        description=data.description,
        status="active",
    )
    db.add(conn)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"名称已存在: {data.name}")
    await db.refresh(conn)
    return _to_resp(conn)


@router.get("", response_model=list[DbConnectionResp])
async def list_db_connections(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出当前租户的所有数据库连接（不返 password）。"""
    tenant_id = await _local_database_tenant_id(db, ctx)
    result = await db.execute(
        select(DbConnection)
        .where(DbConnection.tenant_id == tenant_id)
        .order_by(DbConnection.created_at.desc())
    )
    return [_to_resp(c) for c in result.scalars().all()]


@router.get("/{conn_id}", response_model=DbConnectionResp)
async def get_db_connection(
    conn_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """单条详情（不返 password）。"""
    tenant_id = await _local_database_tenant_id(db, ctx)
    conn = await _get_owned_conn(db, conn_id, tenant_id)
    return _to_resp(conn)


@router.put("/{conn_id}", response_model=DbConnectionResp)
async def update_db_connection(
    conn_id: int,
    data: DbConnectionUpdate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """更新；password 省略则保留原密码，传新值则重新加密。"""
    tenant_id = await _local_database_tenant_id(db, ctx)
    conn = await _get_owned_conn(db, conn_id, tenant_id)

    if data.name is not None:
        conn.name = data.name
    if data.db_type is not None:
        conn.db_type = data.db_type
    if data.host is not None:
        conn.host = data.host
    if data.port is not None:
        conn.port = data.port
    if data.database is not None:
        conn.database_name = data.database
    if data.username is not None:
        conn.username = data.username
    if data.password is not None:
        conn.password_enc = encrypt_password(data.password)
    if data.description is not None:
        conn.description = data.description

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"名称已存在: {data.name}")
    await db.refresh(conn)
    return _to_resp(conn)


@router.delete("/{conn_id}")
async def delete_db_connection(
    conn_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """删除连接。"""
    tenant_id = await _local_database_tenant_id(db, ctx)
    conn = await _get_owned_conn(db, conn_id, tenant_id)
    await db.delete(conn)
    await db.commit()
    return {"ok": True}


# ============================================================
# 连接测试 + 表清单
# ============================================================


@router.post("/{conn_id}/test", response_model=TestResp)
async def test_db_connection(
    conn_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """重新测试连接 → 成功更新 last_tested_at + table_count，失败仅标 disconnected 不抛 500。"""
    tenant_id = await _local_database_tenant_id(db, ctx)
    conn = await _get_owned_conn(db, conn_id, tenant_id)

    if not conn.password_enc:
        conn.status = "disconnected"
        await db.commit()
        return TestResp(ok=False, table_count=0, error="未保存密码，无法测试")

    try:
        password = decrypt_password(conn.password_enc)
        tables = await _probe_mysql_tables(conn, password)
        conn.last_tested_at = datetime.utcnow()
        conn.table_count = len(tables)
        conn.status = "active"
        await db.commit()
        return TestResp(ok=True, table_count=len(tables))
    except NotImplementedError as e:
        # 类型未支持也算 disconnected — 但写 error 给前端
        conn.status = "disconnected"
        await db.commit()
        return TestResp(ok=False, table_count=0, error=str(e))
    except Exception as e:
        logger.warning("db-connection %s test failed: %s", conn_id, e)
        conn.status = "disconnected"
        await db.commit()
        return TestResp(ok=False, table_count=0, error=f"{type(e).__name__}: {e}")


@router.get("/{conn_id}/tables", response_model=TablesResp)
async def list_db_tables(
    conn_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """拉表清单 + 分类结果（复用 quick_db 路径）。"""
    tenant_id = await _local_database_tenant_id(db, ctx)
    conn = await _get_owned_conn(db, conn_id, tenant_id)

    if not conn.password_enc:
        raise HTTPException(status_code=400, detail="未保存密码，无法读取表清单")

    password = decrypt_password(conn.password_enc)

    try:
        tables = await _probe_mysql_tables(conn, password)
    except NotImplementedError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.warning("db-connection %s list tables failed: %s", conn_id, e)
        conn.status = "disconnected"
        await db.commit()
        raise HTTPException(status_code=400, detail=f"读取表清单失败: {type(e).__name__}: {e}")

    # tables 是 TableInfo(name, fields) 列表（fields = int 字段计数）
    tables_payload = [{"name": t.name, "fields": t.fields} for t in tables]

    classifications: dict[str, Any] = {}
    if tables and conn.db_type == "MYSQL":
        try:
            schemas = await _query_mysql_schemas(
                host=conn.host,
                port=conn.port,
                user=conn.username,
                password=password,
                db_name=conn.database_name,
                tables=[t.name for t in tables],
            )
            classifications = dict(classify_tables(schemas))
        except Exception as e:
            # 分类失败不致命 — 前端拿不到 badge 但表清单照常给。
            logger.warning("db-connection %s classify failed: %s", conn_id, e)

    # 顺手把 last_tested_at / table_count 也刷一下
    conn.last_tested_at = datetime.utcnow()
    conn.table_count = len(tables)
    conn.status = "active"
    await db.commit()

    return TablesResp(tables=tables_payload, classifications=classifications)
