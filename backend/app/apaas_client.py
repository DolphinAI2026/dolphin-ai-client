from __future__ import annotations
import asyncio
import httpx
import time
import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Any
from urllib.parse import parse_qsl, urlsplit
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

import logging
import threading

from app.error_messages import APAAS_TOKEN_EXPIRED

logger = logging.getLogger(__name__)
DESKTOP_API_DEBUG_LOG = Path.home() / "Desktop" / "apaas_api_debug.log"

# 查询所有模型的字段时，同时在飞的 query_model_fields 请求上限。
# 10 是经验值：既能把串行的等待时间压下来，又不会触发 APaaS 平台限流。
# 如果未来平台端扩容/收紧了速率限制，调整这个常量即可。
QUERY_MODEL_FIELDS_CONCURRENCY = 10

# 单次 APaaS HTTP 调用超时（秒）。原默认 60s 在大表单（>50 字段 / 复杂 detail page）
# 经常被卡断，但平台其实会异步把保存做完——前端看到 "timeout exceeded" 失败、
# 刷新后却发现表单已建好。180s 给大 payload 留出余量。慢节点可继续上调。
APAAS_HTTP_TIMEOUT = 180.0

# ---------------------------------------------------------------------------
# API 调用日志收集器（线程安全）
# ---------------------------------------------------------------------------

_call_log_buffer: list = []
_call_log_lock = threading.Lock()


def collect_call_log(
    method: str, url: str, request_body: str,
    status: int, response_body: str,
    success: bool, error: str, elapsed_ms: float,
):
    """将一条 API 调用记录追加到缓冲区"""
    with _call_log_lock:
        _call_log_buffer.append({
            "method": method,
            "url": url,
            "request_body": request_body[:2000] if request_body else None,
            "response_status": status,
            "response_body": response_body[:2000] if response_body else None,
            "success": success,
            "error_message": error,
            "elapsed_ms": int(elapsed_ms),
        })


def flush_call_logs() -> list:
    """取出并清空缓冲区，返回累积的日志列表"""
    with _call_log_lock:
        logs = _call_log_buffer.copy()
        _call_log_buffer.clear()
    return logs


def _to_json(obj: Any) -> str:
    """将对象转为 JSON 字符串（不截断）"""
    if isinstance(obj, str):
        return obj
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _append_desktop_api_debug_log(event: str, payload: dict[str, Any]) -> None:
    """将关键 APaaS 调用单独落到桌面，方便手工联调时直接查看。"""
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "event": event,
        **payload,
    }
    try:
        DESKTOP_API_DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with DESKTOP_API_DEBUG_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False))
            fh.write("\n")
    except Exception as exc:
        logger.warning("写入桌面 APaaS 调试日志失败: %s", exc)


def _encode_security_info(app_id: str) -> str:
    payload = json.dumps({"appId": str(app_id)}, ensure_ascii=False, separators=(",", ":"))
    return base64.b64encode(payload.encode("utf-8")).decode("utf-8")


def _first_non_empty(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value
            continue
        return value
    return ""


def _normalize_model_field(raw_field: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(raw_field)

    field_id = _first_non_empty(raw_field, "id", "fieldId", "modelFieldId")
    field_code = _first_non_empty(raw_field, "fieldCode", "code", "columnCode", "name")
    field_name = _first_non_empty(raw_field, "fieldName", "name", "columnName", "displayName", "fieldLabel")
    field_type = _first_non_empty(raw_field, "fieldType", "dataType", "databaseFieldType", "dbType")
    dict_code = _first_non_empty(raw_field, "dictionaryCode", "dictCode", "dictionary_code")
    ref_model_code = _first_non_empty(raw_field, "refModelCode", "referenceModelCode", "targetModelCode")
    ref_field_code = _first_non_empty(raw_field, "refFieldCode", "referenceFieldCode", "targetFieldCode")
    max_length = _first_non_empty(raw_field, "maxLength", "length", "columnLength")

    normalized["id"] = field_id
    normalized["fieldCode"] = field_code
    normalized["fieldName"] = field_name or field_code
    normalized["fieldType"] = field_type or "STRING"
    normalized["dictionaryCode"] = dict_code
    normalized["refModelCode"] = ref_model_code
    normalized["refFieldCode"] = ref_field_code
    if max_length != "":
        normalized["maxLength"] = max_length

    return normalized


def _log_request(method: str, url: str, payload: Any = None, params: Any = None):
    """记录请求日志"""
    logger.info(f">>> APaaS API 请求: {method} {url}")
    if params is not None:
        logger.info(f"    参数: {_to_json(params)}")
    if payload is not None:
        logger.info(f"    请求体: {_to_json(payload)}")


def _extract_query_params(url: str) -> Optional[dict[str, str]]:
    """从 URL 中提取 query 参数，便于统一打印日志。"""
    query_items = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
    return query_items or None


def _log_response(
    url: str, status: int, data: Any, elapsed_ms: float,
    method: str = "POST", request_body: str | None = None,
):
    """记录响应日志，同时追加到持久化缓冲区"""
    code = data.get("code") if isinstance(data, dict) else None
    message = data.get("message") if isinstance(data, dict) else None
    success = code == "ok" or code == 200

    if success:
        logger.info(f"<<< APaaS API 响应: {status} OK ({elapsed_ms:.0f}ms) - {url.split('/')[-1]}")
        if isinstance(data, dict) and "data" in data:
            logger.debug(f"    响应数据: {_to_json(data.get('data'))}")
    else:
        logger.warning(f"<<< APaaS API 响应: {status} FAILED ({elapsed_ms:.0f}ms) - code={code}, message={message}")
        logger.warning(f"    完整响应: {_to_json(data)}")

    # 持久化到缓冲区
    response_body = _to_json(data) if data else None
    collect_call_log(
        method=method,
        url=url,
        request_body=request_body,
        status=status,
        response_body=response_body,
        success=success,
        error=str(message) if not success and message else "",
        elapsed_ms=elapsed_ms,
    )

# POC环境RSA公钥（getPublicKey接口需要认证，硬编码避免鸡生蛋问题）
DEFAULT_PUBLIC_KEY_B64 = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA97JYGwwqg4ixYVrPHTmj"
    "FmknoRC0mqwA3kQRkGfYqAlMAuTb6GfXgLukkqbJP9OgT54FGiydFNf9Pkk8ReuO"
    "n5aaMZULZmes9rvrSzAuxj6o/I3U159XAoBChnt6USCTJ4BtAv4x/dk5W4fuMBqU"
    "AX9M38W/cbzbF8Y5KfCJRWv4+MYDgxvUlFRoxhXuTLyXpihocd3N1YOaDJ1+Ktwg"
    "2DdTBs8/IhNwdKFgEgZ3AmQPpLdJAcAhtI1vgFD/mwcnJpcvFGI60qs5KusmwgQs"
    "NDddax9h9tbaKEheH5qmgLbp6Dn7mbXeToHZx+l8uYOBVMUJvp6x+RgOTkEGYNo"
    "F7wIDAQAB"
)


def _b64_to_pem(b64_key: str) -> str:
    """将Base64公钥转为PEM格式"""
    lines = [b64_key[i:i+64] for i in range(0, len(b64_key), 64)]
    return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(lines) + "\n-----END PUBLIC KEY-----"


class APaaSClient:
    def __init__(self, base_url: Optional[str] = None, tenant_id: Optional[str] = None, token: Optional[str] = None):
        from app.config import settings
        self.base_url = (base_url or settings.apaas_base_url).rstrip("/")
        self.tenant_id = tenant_id or settings.apaas_tenant_id
        self.token = token
        self.user_id = None

    def _get_timestamp(self) -> str:
        return str(int(time.time() * 1000))

    def _get_headers(self, app_id: Optional[str] = None) -> dict:
        headers = {
            "Content-Type": "application/json",
            "xdaptenantid": self.tenant_id,
            "xdaptimestamp": self._get_timestamp()
        }
        if self.token:
            headers["xdaptoken"] = self.token
        if app_id:
            headers["appid"] = app_id
        return headers

    def _encrypt_password(self, password: str, public_key_b64: str) -> str:
        """RSA PKCS1v15 加密密码"""
        pem = _b64_to_pem(public_key_b64)
        public_key = serialization.load_pem_public_key(pem.encode(), backend=default_backend())
        encrypted = public_key.encrypt(password.encode(), padding.PKCS1v15())
        return base64.b64encode(encrypted).decode()

    async def login(self, account: str, password: str, public_key_b64: Optional[str] = None) -> dict:
        """RSA加密登录得帆云平台"""
        pk = public_key_b64 or DEFAULT_PUBLIC_KEY_B64
        encrypted_password = self._encrypt_password(password, pk)

        url = f"{self.base_url}/xdap-admin/user/login"
        payload = {
            "account": account,
            "password": "******",  # 日志中隐藏密码
            "type": "account",
            "tenantId": self.tenant_id,
            "loginType": "MANAGE"
        }
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=45.0) as client:
            response = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "account": account,
                    "password": encrypted_password,
                    "type": "account",
                    "tenantId": self.tenant_id,
                    "loginType": "MANAGE"
                }
            )
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms, method="POST", request_body=_to_json(payload))

            if data.get("code") == "ok":
                self.token = data["data"]["token"]
                user = data["data"].get("user", {})
                self.user_id = str(user.get("id", ""))
                logger.info(f"登录成功 - user_id: {self.user_id}")
                return data["data"]
            else:
                raise Exception(data.get("message", "登录失败"))

    async def test_connection(self) -> dict:
        """测试连接：用当前token调一个轻量接口验证是否有效"""
        url = f"{self.base_url}/xdap-app/apaasApplications/queryAppList"
        params = {"page": 1, "pageSize": 1}
        _log_request("GET", url, params=params)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=45.0) as client:
            response = await client.get(url, headers=self._get_headers(), params=params)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms, method="GET")

            if data.get("code") == "ok":
                logger.info("连接测试成功")
                return {"status": "ok", "message": "连接成功"}
            else:
                raise Exception(data.get("message", "连接失败"))

    async def create_app(self, app_name: str, app_code: str, description: str = "") -> dict:
        """创建应用"""
        if not self.token:
            raise Exception("未设置token，请先调用login()或在初始化时传入token")

        url = f"{self.base_url}/xdap-app/apaasApplications/addApp"
        payload = {
            "appName": app_name,
            "appCode": app_code,
            "appDesc": description,
            "appType": "CUSTOM"
        }
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=45.0) as client:
            response = await client.post(url, json=payload, headers=self._get_headers())
            elapsed_ms = (time.time() - start) * 1000

            if response.status_code == 401:
                logger.error(f"401 Unauthorized - token可能已过期或无效")
                raise Exception(APAAS_TOKEN_EXPIRED)

            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms, method="POST", request_body=_to_json(payload))

            if data.get("code") == "ok":
                logger.info(f"应用创建成功: {app_name} (id={data.get('data', {}).get('id')})")
                return data.get("data", {})
            else:
                raise Exception(f"创建应用失败: {data.get('message')}")

    @property
    def _manage_url(self) -> str:
        return f"{self.base_url}/xdap-app"

    async def _post_resource(self, path: str, payload: dict, app_id: Optional[str] = None) -> dict:
        """通用资源创建方法"""
        url = f"{self._manage_url}{path}"
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(
                url,
                headers=self._get_headers(app_id=app_id),
                json=payload
            )
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms, method="POST", request_body=_to_json(payload))

            code = data.get("code")
            # 平台API返回 code:"ok" 或 code:200 表示成功
            if code == "ok" or code == 200:
                return data.get("data") or {}
            else:
                raise Exception(data.get("message", "API调用失败"))

    async def create_roles(self, app_id: str, roles: list) -> dict:
        return await self._post_resource("/common/resource/appRole", roles, app_id)

    async def create_dicts(self, app_id: str, dicts: list) -> dict:
        return await self._post_resource("/common/resource/appDict", dicts, app_id)

    async def create_models(self, app_id: str, payload: dict) -> list:
        """批量创建数据模型 — /common/resource/v2/appModel

        失败时（尤其平台返回"字段编码与数据库关键字重复"这类无字段名的笼统错误）
        会自动用 safe_field_code 模拟一遍，找出疑似真凶并把诊断信息塞进 raise 的
        Exception 里，让上层 add_error 直接冒泡到前端的"创建模型: X 失败"展示。
        """
        # 调试：打印所有字段编码
        for dm in payload.get("dataModels", []):
            field_codes = [f.get("fieldCode") for f in dm.get("fields", [])]
            logger.info(f"创建模型 {dm.get('modelName')} [{dm.get('modelCode')}] 字段: {field_codes}")
        try:
            result = await self._post_resource("/common/resource/v2/appModel", payload, app_id)
            return result if isinstance(result, list) else []
        except Exception as exc:
            # apaas 平台对字段编码冲突 / 保留字 / 重名等错误统一返回笼统 message，
            # 不告诉具体哪个字段。这里用本地保留字表 + safe_field_code 反查找出真凶
            # 并把诊断信息附在 Exception message 上（前端 add_error 能直接看到）。
            msg = str(exc)
            if any(kw in msg for kw in ("关键字", "重复", "字段编码", "reserved", "duplicate")):
                try:
                    from app.lowcode_standards import _RESERVED_FIELD_CODES, safe_field_code
                except Exception:
                    _RESERVED_FIELD_CODES, safe_field_code = set(), None  # 兜底，没诊断也不能崩
                diag_lines: list[str] = []
                # 完整 payload dump 到 server log（方便用户翻日志精确定位）
                full_dump_lines: list[str] = []
                for dm in payload.get("dataModels", []):
                    model_code = (dm.get("modelCode") or "").strip()
                    model_name = (dm.get("modelName") or "").strip() or "?"
                    fields = dm.get("fields", []) or []
                    full_dump_lines.append(
                        f"  • 模型「{model_name}」({model_code}) 共 {len(fields)} 字段: "
                        + ", ".join((f.get("fieldCode") or "?") for f in fields)
                    )
                    seen: set[str] = set()
                    for f in fields:
                        fc = (f.get("fieldCode") or "").strip()
                        fn = (f.get("fieldName") or "").strip() or fc or "?"
                        if not fc:
                            continue
                        # 1) 本地保留字命中
                        if fc.lower() in _RESERVED_FIELD_CODES:
                            suggested = (
                                safe_field_code(fc, model_code=model_code, field_name=fn, used_codes=set(seen))
                                if safe_field_code else f"{model_code}_{fc}".strip("_") or fc
                            )
                            diag_lines.append(
                                f"模型「{model_name}」字段「{fn}」编码 `{fc}` 是平台保留字，建议改为 `{suggested}`"
                            )
                            seen.add(suggested)
                            continue
                        # 2) 模型内字段编码重名
                        if fc in seen:
                            diag_lines.append(f"模型「{model_name}」字段编码 `{fc}` 在同一模型内重复出现")
                        else:
                            seen.add(fc)
                logger.error(
                    "create_models 失败 — 平台返回: %s\n传入字段编码:\n%s\n本地诊断 (%d 条):\n%s",
                    msg,
                    "\n".join(full_dump_lines) or "  （payload 为空）",
                    len(diag_lines),
                    "\n".join(f"  - {d}" for d in diag_lines) or "  （未在本地保留字表里找到匹配；可能是 modelCode 冲突 / 字段名重复 / 平台特有保留字，请在 server log 中比对完整 fieldCode 列表）",
                )
                if diag_lines:
                    head = "; ".join(diag_lines[:3])
                    more = f"（共 {len(diag_lines)} 条，详见后端日志）" if len(diag_lines) > 3 else ""
                    raise Exception(f"{msg} — 疑似真凶（整字段命中保留字表）: {head}{more}") from exc

                # 整字段没命中本地表 → token 级扫描：按 _ 切分 fieldCode 找含保留字 token 的字段
                # 同时 flag 业务上常见的 apaas 平台疑似内置字段（approver_id / applicant_id / status / type 等
                # 单 token 字段以及审批流相关字段名）— 这些是历史撞库高频项。
                # 这里融合 _doc_helpers.py:SYSTEM_FIELD_CODES（已知 apaas 系统列）+ 高频审批流字段。
                APAAS_BUILTIN_SUSPECTS = {
                    # 来自 _doc_helpers.SYSTEM_FIELD_CODES 的已知系统列
                    "id", "pk",
                    "create_time", "created_at", "update_time", "updated_at",
                    "create_by", "created_by", "update_by", "updated_by",
                    "deleted", "deleted_at", "tenant_id", "org_id",
                    "approval_status", "audit_status", "process_status",
                    # apaas 平台流程模块自动管理的字段 — 业务表单不应该设计这些
                    # 实测 2026-05-06：approver_id 是真凶。低代码平台自带审批流/审核管理，
                    # 流程节点会自动注入 approver_id / approval_time / approval_status / approval_note
                    # 等字段，业务模型 md 里包含这些字段会撞库。
                    "approver_id", "approver", "applicant_id", "applicant",
                    "approval_time", "approval_note", "approval_user_id",
                    "create_user_id", "update_user_id",
                    "is_deleted", "version",
                }
                # apaas 流程模块保留前缀 — `approval_*` 整个命名空间归平台流程节点管理
                # 注意：`application_*` **不是**保留前缀（实测确认 application_id 是用户自定义业务字段，没问题）
                APAAS_RESERVED_PREFIXES = ("approval_",)
                token_susp: list[str] = []
                builtin_susp: list[str] = []
                prefix_susp: list[str] = []
                for dm in payload.get("dataModels", []):
                    model_name = (dm.get("modelName") or "?").strip()
                    for f in dm.get("fields", []) or []:
                        fc = (f.get("fieldCode") or "").strip()
                        fn = (f.get("fieldName") or fc or "?").strip()
                        if not fc:
                            continue
                        fc_low = fc.lower()
                        # apaas 内置字段嫌疑（整字段命中）
                        if fc_low in APAAS_BUILTIN_SUSPECTS:
                            builtin_susp.append(f"模型「{model_name}」字段「{fn}」编码 `{fc}`")
                            continue
                        # apaas 保留前缀（application_* / approval_*）
                        for p in APAAS_RESERVED_PREFIXES:
                            if fc_low.startswith(p):
                                prefix_susp.append(
                                    f"模型「{model_name}」字段「{fn}」编码 `{fc}` 命中 apaas 保留前缀 `{p}`"
                                )
                                break
                        else:
                            # token 级保留字命中（仅当未命中保留前缀时检查，避免重复）
                            tokens = fc_low.split("_")
                            bad_tokens = [t for t in tokens if t in _RESERVED_FIELD_CODES]
                            if bad_tokens:
                                token_susp.append(
                                    f"模型「{model_name}」字段「{fn}」编码 `{fc}` 含保留字 token: {','.join(bad_tokens)}"
                                )

                all_fields_dump = "; ".join(
                    f"{dm.get('modelName')}({dm.get('modelCode')}): "
                    + ", ".join((f.get("fieldCode") or "?") for f in dm.get("fields", []) or [])
                    for dm in payload.get("dataModels", [])
                )
                logger.error(
                    "create_models 失败 — 扫描结果: 内置嫌疑 %d 条, 保留前缀嫌疑 %d 条, token 嫌疑 %d 条\n"
                    "内置嫌疑:\n%s\n保留前缀嫌疑:\n%s\ntoken 嫌疑:\n%s\n字段列表: [%s]",
                    len(builtin_susp), len(prefix_susp), len(token_susp),
                    "\n".join(f"  - {s}" for s in builtin_susp) or "  （无）",
                    "\n".join(f"  - {s}" for s in prefix_susp) or "  （无）",
                    "\n".join(f"  - {s}" for s in token_susp) or "  （无）",
                    all_fields_dump,
                )

                # 优先报 apaas 内置嫌疑（命中率最高 — approver_id / approval_time / approval_note 等流程字段）
                if builtin_susp:
                    head = "; ".join(builtin_susp[:5])
                    more = f"（共 {len(builtin_susp)} 个）" if len(builtin_susp) > 5 else ""
                    raise Exception(
                        f"{msg} — 高度疑似 apaas 平台内置字段冲突: {head}{more} "
                        f"— **根因**: apaas 低代码平台自带流程管理（审批/审核），"
                        f"`approver_id` / `approval_time` / `approval_status` / `approval_note` / `applicant_id` "
                        f"这类字段由平台流程节点自动注入和管理，**业务数据模型不应该设计这些字段**。"
                        f"请回 dolphin 让 agent 从 md 的数据模型部分**删除**这些审批/流程字段，"
                        f"流程相关需求改为在 apaas 流程节点配置（不是表单字段）里实现。"
                    ) from exc

                # 二级：apaas 保留前缀（approval_*）— 整个命名空间被平台流程模块占用
                if prefix_susp:
                    head = "; ".join(prefix_susp[:5])
                    more = f"（共 {len(prefix_susp)} 个）" if len(prefix_susp) > 5 else ""
                    raise Exception(
                        f"{msg} — 字段命中 apaas 流程模块保留前缀（approval_*）: {head}{more} "
                        f"— **根因**: `approval_*` 整个命名空间由 apaas 流程模块管理（审批人/时间/状态/备注），"
                        f"业务模型 md 里不应包含这些字段。请回 dolphin 让 agent **删除** `approval_*` 系列字段，"
                        f"如有审批需求，在应用的「流程配置」节点里设置而不是写到表单字段里。"
                        f"完整字段: [{all_fields_dump}]"
                    ) from exc

                if token_susp:
                    head = "; ".join(token_susp[:3])
                    more = f"（共 {len(token_susp)} 个）" if len(token_susp) > 3 else ""
                    raise Exception(
                        f"{msg} — token 级扫描可疑（按 _ 切分含 SQL/平台保留字 token）: {head}{more} "
                        f"— 请让 agent 改写 md，避免字段编码以 status/type/code/date/time/note/file/user/no/id 等"
                        f"单字 token 结尾。完整字段: [{all_fields_dump}]"
                    ) from exc

                # 都没命中 → apaas 用了我们完全没收录的保留字
                raise Exception(
                    f"{msg} — 本地保留字表 + token 扫描 + apaas 内置嫌疑都未命中。"
                    f"实际传给 apaas 的 fieldCode: [{all_fields_dump}] "
                    f"— 这串字段全规避了本地已知规则，说明 apaas 平台用了我们完全没收录的保留字。"
                    f"请把这串字段发回研发，配合 server log 反推平台规则补 _RESERVED_FIELD_CODES。"
                ) from exc
            raise

    async def create_form_config(self, app_id: str, payload: list) -> list:
        """批量创建表单配置 — /common/resource/formConfig"""
        logger.info(f"创建表单: {[p.get('formName') for p in payload]}")
        _append_desktop_api_debug_log(
            "create_form_config.request",
            {
                "app_id": app_id,
                "path": "/common/resource/formConfig",
                "form_names": [p.get("formName") for p in payload if isinstance(p, dict)],
                "request_payload": payload,
            },
        )
        try:
            result = await self._post_resource("/common/resource/formConfig", payload, app_id)
        except Exception as exc:
            _append_desktop_api_debug_log(
                "create_form_config.error",
                {
                    "app_id": app_id,
                    "path": "/common/resource/formConfig",
                    "request_payload": payload,
                    "error": str(exc),
                },
            )
            raise
        if isinstance(result, list):
            for r in result:
                if isinstance(r, dict):
                    logger.info(f"表单返回: formName={r.get('formName')}, formCode={r.get('formCode')}, menuId={r.get('menuId')}, id={r.get('id')}")
        _append_desktop_api_debug_log(
            "create_form_config.response",
            {
                "app_id": app_id,
                "path": "/common/resource/formConfig",
                "response_payload": result,
            },
        )
        return result if isinstance(result, list) else []

    async def create_process_config(self, app_id: str, payload: list) -> dict:
        return await self._post_resource("/common/resource/processConfig", payload, app_id)

    async def save_process_config(self, app_id: str, payload: dict) -> dict:
        """用平台内部 save API 创建/保存流程（需要完整的 nodes + edges + bpmn）"""
        url = f"{self.base_url}/xdap-app/process/save/processConfig"
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            headers = self._get_headers(app_id)
            response = await client.post(url, headers=headers, json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms, method="POST", request_body=_to_json(payload))

            if data.get("code") not in ("ok",):
                raise Exception(data.get("message", "保存流程失败"))
            return data

    async def create_form_permissions(self, app_id: str, payload: list) -> dict:
        _append_desktop_api_debug_log(
            "create_form_permissions.request",
            {
                "app_id": app_id,
                "path": "/common/resource/formPermission",
                "permission_count": len(payload) if isinstance(payload, list) else 0,
                "request_payload": payload,
            },
        )
        try:
            result = await self._post_resource("/common/resource/formPermission", payload, app_id)
        except Exception as exc:
            _append_desktop_api_debug_log(
                "create_form_permissions.error",
                {
                    "app_id": app_id,
                    "path": "/common/resource/formPermission",
                    "request_payload": payload,
                    "error": str(exc),
                },
            )
            raise
        _append_desktop_api_debug_log(
            "create_form_permissions.response",
            {
                "app_id": app_id,
                "path": "/common/resource/formPermission",
                "response_payload": result,
            },
        )
        return result

    async def update_role(self, app_id: str, role_id: str, role_code: str, role_name: str,
                          app_name: str = "", enable_group_param: str = "DISABLE",
                          role_params: list | None = None) -> dict:
        """更新单个角色（POST /xdap-app/roles/edit/role）。

        参考 incremental_executor._update_role 的真实 endpoint 调用。
        """
        url = f"{self.base_url}/xdap-app/roles/edit/role"
        payload = {
            "roleId": role_id,
            "appId": app_id,
            "roleCode": role_code,
            "roleName": role_name,
            "useScope": app_name or "",
            "internalResource": True,
            "enableGroupParam": enable_group_param,
            "roleNameI18nAssociated": False,
            "roleNameI18nResourceCode": "",
            "roleNameI18n": {},
            "roleParams": role_params or [],
        }
        _log_request("POST", url, payload)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, request_body=_to_json(payload))
            if data.get("code") not in ("ok", 200):
                raise Exception(data.get("message", "更新角色失败"))
            return data

    async def delete_role(self, app_id: str, role_id: str) -> dict:
        """删除单个角色（POST /xdap-app/roles/delete/role）。"""
        url = f"{self.base_url}/xdap-app/roles/delete/role"
        payload = {"roleId": role_id}
        _log_request("POST", url, payload)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, request_body=_to_json(payload))
            if data.get("code") not in ("ok", 200):
                raise Exception(data.get("message", "删除角色失败"))
            return data

    async def query_roles(self, app_id: str, keyword: str = "") -> list:
        """查询应用角色列表"""
        url = f"{self.base_url}/xdap-app/roles/query/rolesList"
        payload = {
            "keyWord": keyword,
            "appId": app_id,
            "appQueryFlag": True,
        }
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms)

            if data.get("code") == "ok":
                return data.get("data", [])
            return []

    async def query_app_detail(self, app_id: str) -> dict:
        """查询单个应用详情（从应用列表中按 appId 过滤）"""
        apps = await self.query_app_list()
        for app in apps:
            if str(app.get("id", "")) == str(app_id) or str(app.get("appId", "")) == str(app_id):
                return app
        return {}

    # ─── 自开发资源相关 5 个方法（合并自 auth-refactor-phase-1）─────────────

    async def enable_self_dev_config(self, app_id: str, status: str = "ENABLE") -> dict:
        """开启 / 关闭应用的自开发配置开关。

        endpoint: GET /xdap-app/sourceRelation/update
        status: 'ENABLE' | 'DISABLE'

        前端入口：apaas 平台「应用详情 → 高级设置 → 自开发配置」开关。
        开启后才能调 attach_apaas_source_relation 把自开发包关联到应用。
        """
        url = f"{self.base_url}/xdap-app/sourceRelation/update"
        params = {"timestamp": self._get_timestamp(), "appId": app_id, "status": status}
        _log_request("GET", url, params=params)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=self._get_headers(app_id), params=params)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms)
            if data.get("code") not in ("ok", 200):
                raise Exception(data.get("message", f"开启自开发配置失败 (status={status})"))
            logger.info(f"应用自开发配置 {status}: app_id={app_id}")
            return data

    async def query_app_dev_kits(
        self,
        app_id: str,
        file_name: str = "",
        file_type: str = "",
        page_size: int = 50,
    ) -> list:
        """列出当前租户下可关联的自开发包（zip）— 含 id / fileName / fileType / size。

        endpoint: POST /xdap-app/selfdevelopment/query/allDevelopmentKit
        body: {"keyWord": "<filename or prefix>", "page": 1, "pageSize": N}

        attach_apaas_source_relation 需要 zip 的 **id**，所以先调本方法做
        fileName → id 反查；调用方按 fileName 精准匹配。
        """
        url = f"{self.base_url}/xdap-app/selfdevelopment/query/allDevelopmentKit"
        payload = {"keyWord": file_name or "", "page": 1, "pageSize": page_size}
        _log_request("POST", url, payload)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, request_body=_to_json(payload))
            if data.get("code") != "ok":
                return []
            kits = data.get("table") or (data.get("data") or {}).get("list") or []
            return kits if isinstance(kits, list) else []

    async def attach_apaas_source_relation(
        self,
        app_id: str,
        object_ids: list[str],
        object_type: str = "DEVELOPMENT_KIT",
    ) -> dict:
        """把已上传到平台的自开发包关联到应用的「自开发资源」。

        endpoint: POST /xdap-app/apaasSourceRelation/save

        前置：app 必须先开 enable_self_dev_config(ENABLE)，否则 save 后看不到。
        后续：要看到组件生效，必须 deploy_app 重发版本（自开发变更不立即生效）。
        """
        if not object_ids:
            raise ValueError("object_ids 不能为空")
        url = f"{self.base_url}/xdap-app/apaasSourceRelation/save"
        params = {"timestamp": self._get_timestamp()}
        payload = {
            "objectType": object_type,
            "appId": app_id,
            "objectIds": [str(i) for i in object_ids],
        }
        _log_request("POST", url, payload, params=params)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(
                url, headers=self._get_headers(app_id), params=params, json=payload,
            )
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, request_body=_to_json(payload))
            if data.get("code") not in ("ok", 200):
                raise Exception(data.get("message", "保存自开发资源关联失败"))
            logger.info(f"自开发资源关联保存成功: app_id={app_id} ids={object_ids}")
            return data

    async def save_app_access(
        self,
        app_id: str,
        object_type: str = "ALL",
        object_ids: list[str] | None = None,
    ) -> dict:
        """配置应用访问对象（即"谁能进这个应用"）。

        平台默认应用部署完不开放访问，必须显式调一次。

        object_type:
          - "ALL"：开放给租户内全部用户（推荐，object_ids 留空）
          - "ROLE" / "DEPT" / "USER"：object_ids 填具体 id 列表
        """
        url = f"{self.base_url}/xdap-app/appAccess/save"
        params = {"timestamp": self._get_timestamp()}
        payload = {
            "appId": str(app_id),
            "objectType": object_type,
            "objectIds": list(object_ids or []),
        }
        _log_request("POST", url, payload, params=params)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(
                url, headers=self._get_headers(app_id=app_id),
                params=params, json=payload,
            )
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="POST", request_body=_to_json(payload))
            if data.get("code") not in ("ok", 200):
                raise Exception(data.get("message", "配置应用访问权限失败"))
            logger.info(f"应用访问权限已开放: app_id={app_id}, object_type={object_type}")
            return data.get("data") or {"ok": True}

    async def create_self_dev_menu(
        self,
        app_id: str,
        menu_name: str,
        link_url: str,
        parent_id: str = "",
        menu_icon: str = "userInfo",
        icon_color: str = "#027AFF",
        menu_display: str = "PC",
        menu_order: int | None = None,
    ) -> dict:
        """创建自开发页面菜单 — POST /menu/save/menu (menuType=CUSTOM)。

        跟 create_menu 区别：
          - menuType: "CUSTOM"（自开发） vs "MENU/MODEL"（普通表单菜单）
          - linkUrl: "apaas-custom-xxx"（自开发组件注册名） vs formId
        """
        url = f"{self.base_url}/xdap-app/menu/save/menu"
        payload = {
            "appId": app_id,
            "menuName": menu_name,
            "menuNameI18nResourceCode": "",
            "menuNameI18nAssociated": False,
            "menuNameI18n": {},
            "menuIcon": menu_icon,
            "datasourceId": "",
            "datasourceName": "",
            "menuModelType": "DATABASE",
            "menuDisplay": menu_display,
            "iconColor": icon_color,
            "cusIconStatus": "DISABLE",
            "newWindowStatus": "DISABLE",
            "menuCustomIcon": "",
            "linkUrl": link_url,
            "menuType": "CUSTOM",
        }
        if parent_id:
            payload["parentId"] = str(parent_id)
        if menu_order is not None:
            payload["menuOrder"] = int(menu_order)
        _log_request("POST", url, payload)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, request_body=_to_json(payload))
            if data.get("code") not in ("ok", 200):
                raise Exception(data.get("message", "创建自开发菜单失败"))
            logger.info(f"自开发菜单创建成功: app_id={app_id} name={menu_name}")
            return data

    # ─── /自开发资源 ─────────────────────────────────────────────────

    async def deploy_app(self, app_id: str, version: str, abstract: str = "") -> dict:
        """发布应用

        Args:
            app_id: 应用 ID
            version: 发布版本号（如 "1.0.1"）
            abstract: 版本摘要
        """
        url = f"{self.base_url}/xdap-app/deploy/deployApplication"
        params = {"timestamp": self._get_timestamp()}
        payload = {
            "appId": app_id,
            "appVersion": version,
            "appAbstract": abstract,
        }
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=120.0) as client:
            response = await client.post(
                url, headers=self._get_headers(app_id), json=payload, params=params
            )
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms, request_body=_to_json(payload))

            if data.get("code") not in ("ok", 200):
                raise Exception(data.get("message", "发布应用失败"))
            logger.info(f"应用发布成功: app_id={app_id}, version={version}")
            return data

    async def query_app_list(self, page: int = 1, page_size: int = 200) -> list:
        """查询得帆云平台应用列表"""
        url = f"{self.base_url}/xdap-app/apaasApplications/queryAppList"
        params = {"page": page, "pageSize": page_size, "keyword": "", "status": ""}
        _log_request("GET", url, params=params)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=45.0) as client:
            response = await client.get(url, headers=self._get_headers(), params=params)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms, method="GET")

            if data.get("code") == "ok":
                result = data.get("table", [])
                logger.info(f"查询到 {len(result)} 个应用")
                return result if isinstance(result, list) else []
            return []

    async def query_models(self, app_id: str) -> list:
        """查询应用下的所有数据模型（含字段）"""
        ts = self._get_timestamp()
        url = f"{self.base_url}/xdap-app/dataModel/query/list"
        params = {
            "SECURITY_INFO": _encode_security_info(app_id),
            "timestamp": ts,
        }
        payload = {
            "page": 1,
            "pageSize": 1000,
            "keyWord": "",
            "modelType": "",
            "appId": app_id,
        }
        _log_request("POST", url, payload, params=params)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), params=params, json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms, request_body=_to_json(payload))

            if data.get("code") != "ok":
                return []

            payload_data = data.get("data") or {}
            models = payload_data.get("list") or data.get("table") or []
            if not isinstance(models, list):
                return []

            # 并发查询每个模型的字段，避免原先串行 await 导致的 N * RTT 累计等待。
            # 用 Semaphore 限流防止触发平台端速率限制；单个查询失败不影响整批。
            semaphore = asyncio.Semaphore(QUERY_MODEL_FIELDS_CONCURRENCY)

            async def _fetch_fields(model_id: str) -> list:
                if not model_id:
                    return []
                async with semaphore:
                    try:
                        return await self.query_model_fields(app_id, model_id)
                    except Exception as exc:
                        logger.warning("query_model_fields 失败 (dataModelId=%s): %s", model_id, exc)
                        return []

            model_ids = [
                str(model.get("id", model.get("dataModelId", "")) or "").strip()
                for model in models
            ]
            fields_by_index = await asyncio.gather(
                *[_fetch_fields(mid) for mid in model_ids]
            )

            normalized_models = []
            for model, model_id, fields in zip(models, model_ids, fields_by_index):
                normalized = dict(model)
                normalized["id"] = model_id or model.get("id")
                normalized["modelCode"] = model.get("modelCode", model.get("code", ""))
                normalized["modelName"] = model.get("modelName", model.get("name", ""))
                normalized["fields"] = fields
                normalized["dataModelFields"] = fields
                normalized_models.append(normalized)

            logger.info(f"查询到 {len(normalized_models)} 个模型: {[m.get('modelCode') for m in normalized_models]}")
            return normalized_models

    async def query_all_model_codes(self) -> list[dict]:
        """查询租户全部模型（不按 appId 过滤，仅返回 code/name/appId 这些轻字段）。

        用于首次部署前的"模型 code 冲突预检"——避免新建时和平台其他应用撞 code。
        不拉字段，比 query_models 快很多。
        """
        ts = self._get_timestamp()
        url = f"{self.base_url}/xdap-app/dataModel/query/list"
        params = {"timestamp": ts}
        payload = {
            "page": 1,
            "pageSize": 5000,
            "keyWord": "",
            "modelType": "",
            "appId": "",
        }
        _log_request("POST", url, payload, params=params)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(), params=params, json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, request_body=_to_json(payload))
            if data.get("code") != "ok":
                logger.warning(f"query_all_model_codes 返回非 ok: {data.get('message')}")
                return []
            payload_data = data.get("data") or {}
            raw_models = payload_data.get("list") or data.get("table") or []
            if not isinstance(raw_models, list):
                return []
            result = []
            for m in raw_models:
                if not isinstance(m, dict):
                    continue
                code = str(m.get("modelCode", m.get("code", "")) or "").strip()
                if not code:
                    continue
                result.append({
                    "code": code,
                    "name": str(m.get("modelName", m.get("name", "")) or "").strip(),
                    "app_id": str(m.get("appId", "") or "").strip(),
                    "app_name": str(m.get("appName", "") or "").strip(),
                })
            logger.info(f"租户模型总数: {len(result)}")
            return result

    async def query_model_fields(self, app_id: str, data_model_id: str) -> list:
        """查询单个模型下的字段列表"""
        resolved_id = str(data_model_id or "").strip()
        if not resolved_id:
            return []

        ts = self._get_timestamp()
        url = f"{self.base_url}/xdap-app/modelField/query"
        params = {
            "SECURITY_INFO": _encode_security_info(app_id),
            "timestamp": ts,
        }
        payload = {
            "dataModelId": resolved_id,
            "page": 1,
            "pageSize": 1000,
        }
        _log_request("POST", url, payload, params=params)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), params=params, json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms, request_body=_to_json(payload))

            if data.get("code") != "ok":
                return []

            payload_data = data.get("data") or {}
            fields = payload_data.get("list") or data.get("table") or []
            normalized_fields = [_normalize_model_field(field) for field in fields] if isinstance(fields, list) else []
            logger.debug("查询模型字段成功: dataModelId=%s, count=%s", resolved_id, len(normalized_fields))
            return normalized_fields

    async def query_dicts(self, app_id: str) -> list:
        """查询应用下的所有数据字典"""
        url = f"{self.base_url}/xdap-app/dataDictionary/query/dataDictionaryList"
        payload = {"keyword": "", "appId": app_id}
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms)

            if data.get("code") == "ok":
                dicts = data.get("table", [])
                logger.info(f"查询到 {len(dicts)} 个字典: {[d.get('dictionaryCode') for d in dicts]}")
                return dicts
            return []

    async def query_dict_options(self, app_id: str, dict_id: str) -> list:
        """查询字典的所有选项"""
        url = f"{self.base_url}/xdap-app/dataDictionary/query/dictionaryValueList"
        payload = {"dictionaryId": dict_id}
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms)

            if data.get("code") == "ok":
                options = data.get("table", [])
                logger.debug(f"查询到字典 {dict_id} 的 {len(options)} 个选项")
                return options
            return []

    async def add_dict_option(self, app_id: str, dict_id: str, option_code: str, option_name: str, display_order: int = 0) -> dict:
        """为字典添加一个选项"""
        url = f"{self.base_url}/xdap-app/dataDictionary/add/dictionaryValue"
        payload = {
            "appId": app_id,
            "dictionaryId": dict_id,
            "valueCode": option_code,
            "valueName": option_name,
            "valueNameI18nAssociated": False,
            "valueNameI18nResourceCode": "",
            "valueNameI18n": {},
            "displayOrder": display_order,
            "valueDescribe": "",
            "valueStatus": "ENABLE",
            "valueMulticolor": "#027AFF"
        }
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms)

            if data.get("code") != "ok":
                raise Exception(data.get("message", "添加字典选项失败"))
            return data

    async def query_all_app_menus(self, app_id: str) -> list:
        """查询应用所有菜单详情（字段比 manageAppMenu 更完整）"""
        return await self._post_resource("/menu/query/allAppMenu", {"appId": app_id}, app_id)

    async def resolve_default_menu_datasource(self, app_id: str, form_id: str = "") -> tuple[str, str]:
        """解析应用菜单默认数据源绑定信息"""
        resolved_form_id = str(form_id or "").strip()
        if resolved_form_id:
            try:
                detail = await self.query_detail_page_config(app_id, resolved_form_id)
                model_list = detail.get("modelWithFieldVoList") or []
                for model in model_list:
                    datasource_id = str(
                        model.get("modelDataSource")
                        or model.get("datasourceId")
                        or ""
                    ).strip()
                    if datasource_id:
                        return datasource_id, "DEFAULT_DATASOURCE"
            except Exception as exc:
                logger.warning(f"查询表单详情失败，无法从 formId={resolved_form_id} 解析数据源绑定: {exc}")

        try:
            menus = await self.query_all_app_menus(app_id)
        except Exception as exc:
            logger.warning(f"查询应用完整菜单失败，无法自动补齐数据源绑定: {exc}")
            return "", ""

        for menu in menus if isinstance(menus, list) else []:
            datasource_id = str(menu.get("datasourceId") or "").strip()
            datasource_code = str(menu.get("datasourceCode") or "").strip()
            if datasource_id:
                return datasource_id, datasource_code
        return "", ""

    async def create_menu(
        self,
        app_id: str,
        menu_name: str,
        form_id: str,
        menu_order: int = 0,
        menu_id: str = "",
        datasource_id: str = "",
        datasource_code: str = "",
    ) -> dict:
        """创建或更新表单菜单 — /menu/save/menu
        如果传了 menu_id，则更新已有菜单（改名）；否则创建新菜单。
        """
        url = f"{self.base_url}/xdap-app/menu/save/menu"
        resolved_datasource_id = str(datasource_id or "").strip()
        resolved_datasource_code = str(datasource_code or "").strip()
        if not resolved_datasource_id:
            resolved_datasource_id, resolved_datasource_code = await self.resolve_default_menu_datasource(app_id, form_id=form_id)

        payload = {
            "appId": app_id,
            "menuName": menu_name,
            "menuType": "MODEL",
            "menuOrder": menu_order,
            "menuDisplay": "ALL",
            "formId": form_id,
            "menuIcon": "userInfo",
            "cusIconStatus": "DISABLE",
            "newWindowStatus": "DISABLE",
            "cusModelPageStatus": "DISABLE",
            "menuNameI18nAssociated": False,
            "iconColor": "#027AFF",
        }
        if resolved_datasource_id:
            payload["menuModelType"] = "DATABASE"
            payload["datasourceId"] = resolved_datasource_id
            if resolved_datasource_code:
                payload["datasourceCode"] = resolved_datasource_code
        if menu_id:
            payload["id"] = menu_id
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms)

            if data.get("code") == "ok":
                logger.info(f"菜单创建成功: {menu_name}")
                return data.get("data", {})
            raise Exception(data.get("message", "创建菜单失败"))

    async def query_menus(self, app_id: str) -> list:
        """查询应用的菜单列表（包含表单）"""
        url = f"{self.base_url}/xdap-app/menu/query/manageAppMenu"
        payload = {"appId": app_id}
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms)

            if data.get("code") == "ok":
                menus = data.get("data", [])
                logger.info(f"查询到 {len(menus)} 个菜单")
                return menus
            return []

    async def query_form_views(self, app_id: str, form_id: str) -> list:
        """查询表单的列表视图清单（拿 tabId）。

        endpoint: GET /xdap-app/form/query/listPageViewIdsByFormId
        返回: [{tabId, tabName/name}, ...]
        listPageBusinessData 接口必须传 tabId，所以这是数据查询前置必调接口。

        合并自 auth-refactor-phase-1 — 给 ai-chat/cowork 提供"获取应用表单视图"能力。
        """
        ts = self._get_timestamp()
        url = f"{self.base_url}/xdap-app/form/query/listPageViewIdsByFormId"
        params = {"formId": form_id, "appId": app_id, "timestamp": ts}
        _log_request("GET", url, params=params)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=self._get_headers(app_id), params=params)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="GET")
            if data.get("code") != "ok":
                return []
            views = data.get("data") or data.get("table") or []
            return views if isinstance(views, list) else []

    async def query_form_components(self, app_id: str, form_id: str) -> list:
        """查询表单的所有组件配置（uuid → label 映射 + 下拉选项）。

        endpoint: GET /xdap-app/formConfig/query/listAllComponents
        返回: [{uuid, label, componentType, boCode, businessObjectComponentType,
                chooseOptions?, dictionaryChooseOptions?}, ...]

        关键用途：listPageBusinessData 返回的行数据 key 是 component uuid（不是
        字段名）。前端 vue 写表头 / 渲染下拉时必须用本接口的映射。

        合并自 auth-refactor-phase-1。
        """
        ts = self._get_timestamp()
        url = f"{self.base_url}/xdap-app/formConfig/query/listAllComponents"
        params = {"formId": form_id, "appId": app_id, "timestamp": ts}
        _log_request("GET", url, params=params)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=self._get_headers(app_id), params=params)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="GET")
            if data.get("code") != "ok":
                return []
            comps = data.get("data") or data.get("table") or []
            return comps if isinstance(comps, list) else []

    async def query_form_config(self, app_id: str, form_id: str) -> dict:
        """查询表单的完整配置"""
        url = f"{self.base_url}/xdap-app/v2/form/query/formContext?formId={form_id}"
        _log_request("GET", url)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=self._get_headers(app_id))
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms, method="GET")

            if data.get("code") == "ok":
                form_config = data.get("data", {}).get("simpleFormConfig", {})
                logger.info(f"查询表单配置成功: formId={form_id}")
                return form_config
            raise Exception(data.get("message", "查询表单配置失败"))

    async def query_detail_page_config(self, app_id: str, form_id: str) -> dict:
        """查询表单详情页完整配置（含组件、子表列、选项、权限）

        调用 detailPageConfigById 接口，返回比 formContext 更丰富的数据：
        - detailPage.formComponents: 完整组件列表（含 chooseOptions、documentNumRules 等）
        - modelWithFieldVoList: 所有关联模型及字段的 DB 定义
        - advancedPermissionGroups: 数据权限配置
        - operationPermissionGroups: 操作权限配置
        """
        ts = self._get_timestamp()
        url = (
            f"{self.base_url}/xdap-app/formConfig/query/"
            f"detailPageConfigById?timestamp={ts}&formId={form_id}&appId={app_id}"
        )
        _log_request("GET", url)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=self._get_headers(app_id))
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms, method="GET")

            if data.get("code") == "ok":
                result = data.get("data", {})
                logger.info(
                    f"查询详情页配置成功: formId={form_id}, "
                    f"models={len(result.get('modelWithFieldVoList', []))}"
                )
                return result
            raise Exception(data.get("message", "查询详情页配置失败"))

    async def save_form_config(self, app_id: str, form_config: dict) -> dict:
        """保存表单配置（全量更新）"""
        url = f"{self.base_url}/xdap-app/formConfig/save/formConfigDetail"
        logger.info(
            "save_form_config payload (formName=%s, formId=%s):\n%s",
            form_config.get("formName", ""),
            form_config.get("id", ""),
            _to_json(form_config),
        )
        _log_request("POST", url, form_config)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=form_config)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms)

            if data.get("code") != "ok":
                raise Exception(data.get("message", "保存表单配置失败"))
            logger.info(f"保存表单配置成功: formName={form_config.get('formName')}")
            return data

    async def update_form_component(self, app_id: str, form_id: str, component_label: str, updates: dict) -> dict:
        """更新表单中指定组件的属性"""
        logger.info(f"更新表单组件: formId={form_id}, label={component_label}, updates={_to_json(updates)}")

        # 查询表单配置
        form_config = await self.query_form_config(app_id, form_id)
        components = form_config.get('detailPage', {}).get('formComponents', [])

        # 找到并更新组件
        found = False
        for comp in components:
            if comp.get('label') == component_label:
                comp.update(updates)
                found = True
                logger.info(f"找到并更新组件: {component_label}")
                break

        if not found:
            logger.warning(f"未找到标签为 '{component_label}' 的组件")
            raise Exception(f"未找到标签为 '{component_label}' 的组件")

        # 保存
        return await self.save_form_config(app_id, form_config)
