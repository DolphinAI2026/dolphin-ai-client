"""aPaaS 平台 token 验签 + 用户身份解析。

aPaaS 平台 token 协议（实测 trial 2026-05-10）
==============================================
- token 形态：JWT HS512，载荷 `{iat, exp, xdapuserid}`（无 tenant，无 role）
- token 传递：HTTP header `xdaptoken: <jwt>`（不是 Bearer）
- 验证端点：`POST /xdap-admin/user/info` + xdaptoken header
  - 200 → token 有效，返 `{isPlatformAdmin, isPlatformUser, tenantInfos:[{tenantId,tenantName,isTenantAdmin},...]}`
  - 401 → token 无效或过期

ai-builder 不验签（因为没共享 secret，且 apaas HS512 secret 在 apaas 服务器端），
而是**间接验签**：调 /user/info 返 200 即等价于 token 真签 + 未过期 + 用户存在。
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


def decode_apaas_jwt_unsigned(token: str) -> Optional[dict]:
    """解 apaas JWT payload（不验签），拿 xdapuserid + iat/exp。

    本函数仅用于先把 user_id 抽出来打日志 / 选参数；真验证靠 validate()。
    解失败返 None。
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None


async def validate_apaas_token(
    apaas_token: str,
    apaas_base_url: str,
    apaas_tenant_id: str,
) -> Optional[dict]:
    """调 apaas /xdap-admin/user/info 间接验签。

    Args:
        apaas_token: 待验证的 apaas JWT
        apaas_base_url: 形如 `https://apaas-trial.definesys.cn/backend`（结尾不带 /）
        apaas_tenant_id: 调 /user/info 时 xdaptenantid header；任意用户所属租户都行，
                         apaas 会按 token 里 xdapuserid 拿对应身份信息

    Returns:
        dict | None: 成功返 `{user_id, is_platform_admin, is_platform_user, tenants: [...]}`；
                     失败返 None。
    """
    if not apaas_token or not apaas_base_url:
        return None

    # 先解 user_id（不验签）
    payload = decode_apaas_jwt_unsigned(apaas_token)
    if not payload:
        logger.warning("apaas token decode failed (not a valid JWT)")
        return None
    apaas_user_id = payload.get("xdapuserid")
    exp = payload.get("exp")
    if not apaas_user_id:
        logger.warning("apaas token has no xdapuserid claim")
        return None
    if exp and exp < int(time.time()):
        logger.info("apaas token expired (exp=%s)", exp)
        return None

    # 调 /user/info 验签
    url = apaas_base_url.rstrip("/") + "/xdap-admin/user/info"
    headers = {
        "xdaptoken": apaas_token,
        "xdaptenantid": str(apaas_tenant_id or ""),
        "xdaptimestamp": str(int(time.time() * 1000)),
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(verify=False, timeout=15) as c:
            r = await c.post(url, headers=headers, json={})
    except Exception as exc:
        logger.warning("apaas /user/info network error: %s", exc)
        return None

    if r.status_code == 401:
        logger.info("apaas token rejected (401 Unauthorized)")
        return None
    if r.status_code != 200:
        logger.warning(
            "apaas /user/info HTTP %s: %s", r.status_code, (r.text or "")[:200]
        )
        return None

    try:
        data = r.json()
    except Exception:
        logger.warning("apaas /user/info non-JSON: %s", (r.text or "")[:200])
        return None

    return {
        "user_id": str(apaas_user_id),
        "is_platform_admin": bool(data.get("isPlatformAdmin")),
        "is_platform_user": bool(data.get("isPlatformUser")),
        "tenants": data.get("tenantInfos") or [],
        "raw": data,
    }


async def fetch_apaas_user_account(
    apaas_token: str,
    apaas_base_url: str,
    apaas_tenant_id: str,
    apaas_user_id: str,
) -> Optional[str]:
    """调 /xdap-app/user/select/queryAllUsers 拿当前用户的 account 字段（即 username）。

    apaas /user/info 不返 account，但前端展示需要。可选，失败返 None 不阻塞流程。
    """
    if not apaas_user_id:
        return None
    url = apaas_base_url.rstrip("/") + "/xdap-app/user/select/queryAllUsers"
    headers = {
        "xdaptoken": apaas_token,
        "xdaptenantid": str(apaas_tenant_id or ""),
        "xdaptimestamp": str(int(time.time() * 1000)),
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(verify=False, timeout=20) as c:
            r = await c.post(url, headers=headers, json={"page": 1, "pageSize": 100000})
            if r.status_code != 200:
                return None
            d = r.json()
            if d.get("code") != "ok":
                return None
            for row in d.get("table") or []:
                if str(row.get("id")) == str(apaas_user_id):
                    return row.get("account")
    except Exception as exc:
        logger.warning("apaas queryAllUsers failed: %s", exc)
    return None
