"""跨 Builder、Control Plane 和桌面本地数据域的显式路由。

数据域可以同时存在。该模块只负责把功能域和执行位置解析成权威来源，
不执行隐式 fallback，也不负责发起远程请求。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DataAuthority(StrEnum):
    CONTROL_PLANE = "control_plane"
    BUILDER = "builder"
    DESKTOP_LOCAL = "desktop_local"


class DataDomain(StrEnum):
    CODE = "code"
    BUILDER = "builder"
    PLATFORM_CAPABILITY = "platform_capability"
    PERSONAL_CONFIG = "personal_config"


class DataExecution(StrEnum):
    REMOTE = "remote"
    LOCAL = "local"


@dataclass(frozen=True)
class DataRoute:
    """单次读取/写入允许使用的权威来源。"""

    domain: DataDomain
    execution: DataExecution
    authority: DataAuthority
    allow_read_cache: bool = False


def resolve_data_route(
    domain: DataDomain | str,
    *,
    execution: DataExecution | str = DataExecution.REMOTE,
    source: DataAuthority | str | None = None,
) -> DataRoute:
    """解析数据路由。

    ``source`` 只允许选择当前域的合法来源；不传时使用该域的默认权威。
    本地和远程不会互相覆盖，远程不可用时只能读取明确标记的只读缓存。
    """

    resolved_domain = DataDomain(domain)
    resolved_execution = DataExecution(execution)
    requested = DataAuthority(source) if source is not None else None

    if resolved_domain is DataDomain.CODE:
        default = (
            DataAuthority.DESKTOP_LOCAL
            if resolved_execution is DataExecution.LOCAL
            else DataAuthority.CONTROL_PLANE
        )
        allowed = {DataAuthority.CONTROL_PLANE, DataAuthority.DESKTOP_LOCAL}
        cacheable = default is DataAuthority.CONTROL_PLANE
    elif resolved_domain is DataDomain.BUILDER:
        default = DataAuthority.BUILDER
        allowed = {DataAuthority.BUILDER, DataAuthority.DESKTOP_LOCAL}
        cacheable = True
    elif resolved_domain is DataDomain.PLATFORM_CAPABILITY:
        default = DataAuthority.CONTROL_PLANE
        allowed = {DataAuthority.CONTROL_PLANE, DataAuthority.DESKTOP_LOCAL}
        cacheable = True
    else:
        default = DataAuthority.DESKTOP_LOCAL
        allowed = {DataAuthority.BUILDER, DataAuthority.DESKTOP_LOCAL}
        cacheable = True

    authority = requested or default
    if authority not in allowed:
        raise ValueError(
            f"data source {authority.value!r} is not valid for {resolved_domain.value!r}"
        )
    if authority is DataAuthority.DESKTOP_LOCAL:
        cacheable = False

    return DataRoute(
        domain=resolved_domain,
        execution=resolved_execution,
        authority=authority,
        allow_read_cache=cacheable,
    )


def is_local_authority(value: DataAuthority | str) -> bool:
    return DataAuthority(value) is DataAuthority.DESKTOP_LOCAL
