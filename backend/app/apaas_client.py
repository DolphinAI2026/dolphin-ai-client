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


class NotImplementedAPaaSError(Exception):
    """平台没实现该 endpoint (404/405) — 调用方应降级到 fallback 文案.

    2026-05-26 (PR3 reviewer P1 #1): 替代原来的字符串子串 `if "NOT_IMPLEMENTED" in msg`
    脆弱判断, 走 isinstance 强类型. 调用方:
      try:
          await client.update_app(...)
      except NotImplementedAPaaSError:
          # 友好降级
    """
    def __init__(self, endpoint: str, http_status: int):
        self.endpoint = endpoint
        self.http_status = http_status
        super().__init__(f"NOT_IMPLEMENTED: 平台没有 {endpoint} 端点 (HTTP {http_status})")
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


def _normalize_business_event_list(resp: Any) -> dict:
    """规整 apaas /event/query/list 响应为 {table:[...], total:N}。

    apaas 把事件放在【顶层 table/total】(trial 实测), 不是包在 data 里。老代码
    `return data.get("data") or {}` —— 响应没有 data 键 → 永远空 → 业务事件查不到。
    这里优先取顶层 table/records/list, 个别环境若包了一层 data 也兜底。
    """
    if not isinstance(resp, dict):
        return {"table": [], "total": 0}
    table = resp.get("table") or resp.get("records") or resp.get("list")
    total = resp.get("total")
    if table is None:
        inner = resp.get("data")
        if isinstance(inner, dict):
            table = inner.get("table") or inner.get("records") or inner.get("list")
            if total is None:
                total = inner.get("total")
        elif isinstance(inner, list):
            table = inner
    table = table if isinstance(table, list) else []
    if not isinstance(total, int):
        total = len(table)
    return {"table": table, "total": total}


def _normalize_apaas_user_records(resp: Any) -> list[dict[str, Any]]:
    """Normalize aPaaS user query responses into a list of user dicts.

    /xdap-admin/user/query/userList returns a top-level JSON array in current
    trial docs, while some platform APIs wrap records in table/data/list.
    """
    if isinstance(resp, list):
        return [item for item in resp if isinstance(item, dict)]
    if not isinstance(resp, dict):
        return []

    for value in (
        resp.get("table"),
        resp.get("records"),
        resp.get("list"),
        resp.get("data"),
    ):
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _normalize_apaas_user_records(value)
            if nested:
                return nested

    if resp.get("id") or resp.get("userId") or resp.get("username") or resp.get("userName"):
        return [resp]
    return []


def _extract_form_id_from_config(form_config: dict[str, Any]) -> str:
    if not isinstance(form_config, dict):
        return ""
    for source in (
        form_config,
        form_config.get("simpleFormConfig") if isinstance(form_config.get("simpleFormConfig"), dict) else {},
        form_config.get("detailPage") if isinstance(form_config.get("detailPage"), dict) else {},
    ):
        if not isinstance(source, dict):
            continue
        form_id = str(source.get("id") or source.get("formId") or "").strip()
        if form_id:
            return form_id
    return ""


def _iter_exportable_components(form_config: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(form_config, dict):
        return []

    candidates = [
        form_config.get("detailPage", {}).get("formComponents")
        if isinstance(form_config.get("detailPage"), dict)
        else None,
        form_config.get("formComponents"),
        form_config.get("components"),
    ]
    components = next((item for item in candidates if isinstance(item, list)), [])
    out: list[dict[str, Any]] = []

    def walk(items: list[Any]) -> None:
        for item in items or []:
            if not isinstance(item, dict):
                continue
            comp_type = str(item.get("componentType") or "").strip()
            if comp_type == "FORM_WIDGET_SON_TABLE":
                table_columns = item.get("tableColumn")
                if isinstance(table_columns, list):
                    walk(table_columns)
                continue
            comp_uuid = str(item.get("uuid") or item.get("id") or "").strip()
            label = str(item.get("label") or item.get("name") or comp_uuid).strip()
            if not comp_uuid or not label:
                continue
            out.append({
                "isChosen": True,
                "uuid": comp_uuid,
                "label": label,
                "componentType": comp_type or "FORM_TEXT_INPUT",
                "chosen": True,
            })

    walk(components)
    system_components = [
        ("createdBy", "创建人", "FORM_PEOPLE_SELECT"),
        ("lastUpdatedBy", "更新人", "FORM_PEOPLE_SELECT"),
        ("creationDate", "创建时间", "FORM_DATEPICK_INPUT"),
        ("status", "状态", "FORM_RADIO_INPUT"),
        ("lastUpdateDate", "更新时间", "FORM_DATEPICK_INPUT"),
        ("approverList", "下个审批人", "FORM_PEOPLE_SELECT"),
    ]
    existing = {str(item.get("uuid") or "") for item in out}
    for comp_uuid, label, comp_type in system_components:
        if comp_uuid in existing:
            continue
        out.append({
            "isChosen": True,
            "uuid": comp_uuid,
            "label": label,
            "componentType": comp_type,
            "chosen": True,
        })
    return out


def _existing_export_template_id(form_config: dict[str, Any]) -> str:
    if not isinstance(form_config, dict):
        return ""
    for source in (
        form_config.get("excelExportConfig"),
        form_config.get("detailPage", {}).get("excelExportConfig")
        if isinstance(form_config.get("detailPage"), dict)
        else None,
    ):
        if not isinstance(source, dict):
            continue
        templates = source.get("exportTemplateDetailPojoList")
        if not isinstance(templates, list):
            continue
        for template in templates:
            if isinstance(template, dict):
                template_id = str(template.get("excelTemplateID") or "").strip()
                if template_id:
                    return template_id
    return ""


def build_default_excel_import_config() -> dict[str, Any]:
    return {
        "enableImport": True,
        "importStatus": "COMPLETED",
        "enableFieldUpdate": False,
        "enableDocNumAutoGenerate": False,
        "excelUpdateFields": [],
        "autoGenerateDocNumFields": [],
        "sonTables": [],
        "importExceptionData": "BEEMPTY",
        "customSplit": "",
        "enableCustomSplit": False,
    }


def build_default_excel_export_config(form_config: dict[str, Any]) -> dict[str, Any]:
    template_id = _existing_export_template_id(form_config) or str(int(time.time() * 1000))
    return {
        "enableExport": True,
        "exportTemplateDetailPojoList": [{
            "excelTemplateID": template_id,
            "excelTemplateName": "CUSTOM_TEMPLATE_NAME",
            "ExcelTemplateType": "CUSTOM_TEMPLATE",
            "enableExport": True,
            "permissionObjects": [{
                "permissionObjectType": "ALL_USER",
                "permissionObjectDisplayName": "全部人员",
                "permissionRange": {"rangeType": "ALL"},
            }],
            "exportComponentDetailPojoList": _iter_exportable_components(form_config),
            "excelTemplateType": "CUSTOM_TEMPLATE",
        }],
    }


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


# aPaaS 逻辑 fieldType 别名 → 平台合法码。2026-06-22 真机实测: 平台只认 STRING/NUM/
# BIG_TEXT/DATE/DATETIME/BOOLEAN; 传 "TEXT" 之类平台不识别 → 字段建成"类型为空"(编辑器
# 类型下拉空白)。agent 常传 TEXT/NUMBER/INT 等同义词, 在此归一到合法码。
_APAAS_FIELD_TYPE_ALIASES = {
    "TEXT": "BIG_TEXT", "LONGTEXT": "BIG_TEXT", "CLOB": "BIG_TEXT",
    "TEXTAREA": "BIG_TEXT", "RICHTEXT": "BIG_TEXT", "RICH_TEXT": "BIG_TEXT",
    "BIGTEXT": "BIG_TEXT",
    "NUMBER": "NUM", "INT": "NUM", "INTEGER": "NUM", "BIGINT": "NUM",
    "DOUBLE": "NUM", "DECIMAL": "NUM", "FLOAT": "NUM", "NUMERIC": "NUM",
    "VARCHAR": "STRING", "CHAR": "STRING", "STR": "STRING",
    "BOOL": "BOOLEAN",
    "TIMESTAMP": "DATETIME",
}


def _normalize_apaas_field_type(field_type: str) -> str:
    """把 agent/调用方传的 fieldType 归一到平台合法逻辑码(TEXT→BIG_TEXT 等)。"""
    ft = (field_type or "STRING").strip().upper()
    return _APAAS_FIELD_TYPE_ALIASES.get(ft, ft)


def _db_type_for_field_type(field_type: str) -> str:
    """aPaaS 逻辑 fieldType → databaseFieldType(存储类型)。

    复用 canonical normalize_database_field_type:它能正确处理 STRING→varchar /
    TEXT·BIG_TEXT→text / DATE→date / DATETIME→datetime / BOOLEAN→int,只漏认
    aPaaS 逻辑码 "NUM"(会误落 varchar)→ 在此特判。

    NUM→"double":2026-06-22 真机读 apaas-trial 实测,平台自己的 NUM 字段
    databaseFieldType 全是 "double"(不是 decimal/int);照搬平台口径最稳。

    用于 add_model_field 未显式传 database_field_type 时按字段类型推导,避免大文本/
    数字/日期字段统统被建成 VARCHAR(平台字段编辑器类型显示空、原生设计器误渲染)。
    """
    ft = (field_type or "STRING").strip().upper()
    if ft in ("NUM", "NUMBER"):
        return "double"
    from app.lowcode_standards import normalize_database_field_type
    return normalize_database_field_type(field_type or "STRING", component_type=field_type or "STRING")


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
    success = code == "ok" or code == 200 or (isinstance(data, list) and 200 <= status < 400)

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
        self.tenant_id = (tenant_id or "").strip()
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

    async def query_users_by_ids(self, user_ids: list[str], app_id: Optional[str] = None) -> list[dict[str, Any]]:
        """按 aPaaS userId 批量查询用户信息。

        endpoint: POST /xdap-admin/user/query/userList
        body: ["<userId>", ...]

        注意：该接口在 xdap-admin 下，请求体是 JSON 数组，当前 trial 文档返回
        顶层数组而不是 {code, data} 包装。
        """
        cleaned_ids = [str(uid).strip() for uid in user_ids if str(uid or "").strip()]
        if not cleaned_ids:
            return []

        url = f"{self.base_url}/xdap-admin/user/query/userList"
        payload = cleaned_ids
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000

            if response.status_code == 401:
                logger.error("401 Unauthorized - token可能已过期或无效")
                raise Exception(APAAS_TOKEN_EXPIRED)

            response.raise_for_status()
            data = response.json()
            _log_response(
                url,
                response.status_code,
                data,
                elapsed_ms,
                method="POST",
                request_body=_to_json(payload),
            )

            if isinstance(data, dict) and data.get("code") not in (None, "ok", 200):
                raise Exception(data.get("message", "查询用户信息失败"))
            return _normalize_apaas_user_records(data)

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

    async def update_app(
        self,
        apaas_app_id: str,
        app_name: str = "",
        description: str = "",
        icon_svg: str = "",
    ) -> dict:
        """改 aPaaS 应用基本信息（名称 / 描述 / 图标）。

        平台真实 endpoint 在 v1 抓包没复现 — 这里按 addApp 的对称路径
        `POST /xdap-app/apaasApplications/update` 试调。404/405 时抛
        `NotImplementedAPaaSError` 让调用方按类型降级。

        任意字段空串表示不改；非空才进 payload。

        2026-05-26 (PR3 reviewer P1 #4): icon 改单字段 `appIcon` 优先,
        避免双字段 payload 撞平台严格 schema 校验 400.

        ⚠️ SECURITY (PR3 reviewer #8): icon_svg 字段透传到平台未做 sanitize.
        SVG 内可塞 `<script>` / `onload="..."` 等可执行内容. 平台 UI 是否在渲染
        时做 XSS 防御未知. **调用方应只接受可信源的 SVG** (用户上传走 sanitize-svg
        库 / Allowed-tag 白名单 / 或限制为 base64 PNG). 当前 MCP 工具开放给
        ConfigAssistant agent 调用 — agent 不应自己生成 SVG, 必须用户明确提供.
        """
        if not self.token:
            raise Exception("未设置token，请先调用login()或在初始化时传入token")

        url = f"{self.base_url}/xdap-app/apaasApplications/update"
        payload: dict = {"id": apaas_app_id}
        if app_name.strip():
            payload["appName"] = app_name.strip()
        if description.strip():
            payload["appDesc"] = description.strip()
        if icon_svg.strip():
            # PR3 reviewer P1 #4: 单字段 appIcon — 跟 addApp 抓包对称.
            # 若平台 schema 不认会返业务错, 上层降级提示用户.
            payload["appIcon"] = icon_svg.strip()

        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=45.0) as client:
            response = await client.post(url, json=payload, headers=self._get_headers(app_id=apaas_app_id))
            elapsed_ms = (time.time() - start) * 1000

            if response.status_code == 401:
                logger.error("401 Unauthorized - token可能已过期或无效 (update_app)")
                raise Exception(APAAS_TOKEN_EXPIRED)

            # PR3 reviewer P1 #1: 404/405 抛 typed exception 让调用方 isinstance 判
            if response.status_code in (404, 405):
                raise NotImplementedAPaaSError(
                    endpoint="/xdap-app/apaasApplications/update",
                    http_status=response.status_code,
                )

            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms, method="POST", request_body=_to_json(payload))

            if data.get("code") in ("ok", 200):
                logger.info(f"应用更新成功: id={apaas_app_id}")
                return data.get("data") or {}
            else:
                raise Exception(f"更新应用失败: {data.get('message')}")

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

                # 整字段没命中本地表 → 仅扫描已知 apaas 内置字段 / 保留前缀。
                # 不做 token 级扫描：`customer_id`、`visit_time`、`plan_status` 这类业务字段
                # 虽然包含 id/time/status 等短 token，但并不是平台保留字段。
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

                all_fields_dump = "; ".join(
                    f"{dm.get('modelName')}({dm.get('modelCode')}): "
                    + ", ".join((f.get("fieldCode") or "?") for f in dm.get("fields", []) or [])
                    for dm in payload.get("dataModels", [])
                )
                logger.error(
                    "create_models 失败 — 扫描结果: 内置嫌疑 %d 条, 保留前缀嫌疑 %d 条\n"
                    "内置嫌疑:\n%s\n保留前缀嫌疑:\n%s\n字段列表: [%s]",
                    len(builtin_susp), len(prefix_susp),
                    "\n".join(f"  - {s}" for s in builtin_susp) or "  （无）",
                    "\n".join(f"  - {s}" for s in prefix_susp) or "  （无）",
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
                        f"请回外部 让 agent 从 md 的数据模型部分**删除**这些审批/流程字段，"
                        f"流程相关需求改为在 apaas 流程节点配置（不是表单字段）里实现。"
                    ) from exc

                # 二级：apaas 保留前缀（approval_*）— 整个命名空间被平台流程模块占用
                if prefix_susp:
                    head = "; ".join(prefix_susp[:5])
                    more = f"（共 {len(prefix_susp)} 个）" if len(prefix_susp) > 5 else ""
                    raise Exception(
                        f"{msg} — 字段命中 apaas 流程模块保留前缀（approval_*）: {head}{more} "
                        f"— **根因**: `approval_*` 整个命名空间由 apaas 流程模块管理（审批人/时间/状态/备注），"
                        f"业务模型 md 里不应包含这些字段。请回外部 让 agent **删除** `approval_*` 系列字段，"
                        f"如有审批需求，在应用的「流程配置」节点里设置而不是写到表单字段里。"
                        f"完整字段: [{all_fields_dump}]"
                    ) from exc

                # 都没命中 → apaas 用了我们完全没收录的保留字
                raise Exception(
                    f"{msg} — 本地保留字表 + apaas 内置字段 / 保留前缀诊断都未命中。"
                    f"实际传给 apaas 的 fieldCode: [{all_fields_dump}] "
                    f"— 这串字段未命中已知规则，可能是 modelCode 冲突、字段显示名重复、"
                    f"或 apaas 平台用了我们未收录的保留字；请配合 server log 精确反推，"
                    f"不要仅因字段编码包含 customer/id/time/status/no 等业务 token 就改写。"
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

    async def query_process_config(self, app_id: str, process_id: str) -> dict:
        """拉单个流程详情。

        当前 aPaaS 前端实际使用:
        GET /xdap-app/process/query/processConfigDetail?processId=...&appId=...

        老路径保留兜底:
        1. POST /xdap-app/process/query/processConfig  body {processId}
        2. POST /xdap-app/process/queryById            body {processId / id}

        都失败返 {ok: False, error_code, message}. 上游 (MCP / endpoint) 拿到失败
        返友好降级 ("apaas process detail API 未公开, 请用本地 definition + 部署").
        """
        detail_url = f"{self.base_url}/xdap-app/process/query/processConfigDetail"
        detail_params = {
            "processId": process_id,
            "appId": app_id,
            "processVersion": "false",
        }
        sec_info = base64.b64encode(json.dumps({"appId": app_id}).encode()).decode().rstrip("=")
        params = {"SECURITY_INFO": sec_info, "timestamp": self._get_timestamp()}
        urls_to_try = [
            f"{self.base_url}/xdap-app/process/query/processConfig",
            f"{self.base_url}/xdap-app/process/queryById",
        ]
        last_err = ""
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            _log_request("GET", detail_url, params=detail_params)
            start = time.time()
            try:
                response = await client.get(
                    detail_url,
                    headers=self._get_headers(app_id),
                    params=detail_params,
                )
                elapsed_ms = (time.time() - start) * 1000
                data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                _log_response(detail_url, response.status_code, data, elapsed_ms, method="GET")
                if response.status_code == 200 and isinstance(data, dict) and data.get("code") in ("ok", 200):
                    return {"ok": True, "data": data.get("data") or {}}
                last_err = f"{detail_url}: code={data.get('code')} msg={data.get('message')}"
            except Exception as exc:
                last_err = f"{detail_url}: {exc}"

            for url in urls_to_try:
                payload = {"processId": process_id, "id": process_id, "appId": app_id}
                _log_request("POST", url, payload, params=params)
                start = time.time()
                try:
                    response = await client.post(url, headers=self._get_headers(app_id), params=params, json=payload)
                    elapsed_ms = (time.time() - start) * 1000
                    data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                    _log_response(url, response.status_code, data, elapsed_ms, method="POST", request_body=_to_json(payload))
                    if response.status_code == 200 and isinstance(data, dict) and data.get("code") in ("ok", 200):
                        return {"ok": True, "data": data.get("data") or {}}
                    last_err = f"{url}: code={data.get('code')} msg={data.get('message')}"
                except Exception as exc:
                    last_err = f"{url}: {exc}"
                    continue
        return {"ok": False, "error_code": "PROCESS_QUERY_NOT_AVAILABLE", "message": f"apaas 流程详情 API 试 2 路径都失败: {last_err}"}

    async def list_processes(self, app_id: str) -> list:
        """列应用的所有流程 — GET /xdap-app/process/query/processList?appId={id}.

        2026-05-27 实测发现: apaas 这个 endpoint **GET** (不是 POST), 用 query string
        传 appId. 返完整 process 对象数组, 含 processName / processCode / id /
        formId / menuId / nodes / edges. 4 个 trial app 都验过.

        其他流程相关 URL 全 404 (process/list / process/queryByAppId 都不存在),
        只有这个 query/processList 工作.
        """
        url = f"{self.base_url}/xdap-app/process/query/processList"
        params = {"appId": app_id}
        _log_request("GET", url, params=params)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=self._get_headers(app_id), params=params)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="GET")
            if data.get("code") != "ok":
                raise Exception(data.get("message", "list_processes 失败"))
            processes = data.get("data") or []
            logger.info(f"查询到 {len(processes)} 个流程")
            return processes

    async def save_process_config(self, app_id: str, payload: dict) -> dict:
        """用平台内部 save API 创建/保存流程（需要完整的 nodes + edges + bpmn）"""
        url = f"{self.base_url}/xdap-app/process/save/processConfig"
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            headers = self._get_headers(app_id)

            async def _post_save(body_payload: dict, *, started_at: float) -> dict:
                response = await client.post(url, headers=headers, json=body_payload)
                elapsed_ms = (time.time() - started_at) * 1000
                # 不用 response.raise_for_status()：它在读响应体之前就抛，把 apaas 的 500
                # 真错因（哪个字段 null / NPE 堆栈）丢掉，调用方只看到通用 "Server error 500"
                # 根本没法定位（实测 /process/save/processConfig 500 长期不可调试）。
                # 非 2xx 时显式捕获平台响应体并带进异常。
                if response.status_code >= 400:
                    body = (response.text or "")[:2000]
                    _log_response(
                        url,
                        response.status_code,
                        body,
                        elapsed_ms,
                        method="POST",
                        request_body=_to_json(body_payload),
                    )
                    raise Exception(
                        f"保存流程失败：apaas 返回 HTTP {response.status_code}。平台错误详情：{body}"
                    )
                data = response.json()

                _log_response(
                    url,
                    response.status_code,
                    data,
                    elapsed_ms,
                    method="POST",
                    request_body=_to_json(body_payload),
                )

                if data.get("code") not in ("ok",):
                    raise Exception(data.get("message", "保存流程失败"))
                return data

            async def _ensure_menu_process_binding(save_data: dict) -> None:
                process_config = save_data.get("data") if isinstance(save_data.get("data"), dict) else None
                process_id = str(
                    (process_config or {}).get("id")
                    or payload.get("id")
                    or payload.get("processId")
                    or ""
                ).strip()
                menu_id = str(
                    (process_config or {}).get("menuId")
                    or payload.get("menuId")
                    or ""
                ).strip()
                if not process_id or not menu_id:
                    return
                try:
                    await self.bind_menu_process(app_id, menu_id, process_id)
                except Exception as exc:  # noqa: BLE001 - flow is saved; surface binding issue in logs.
                    logger.warning(
                        "save_process_config: 流程已保存但菜单 processId 绑定失败 "
                        "(app_id=%s, menu_id=%s, process_id=%s): %s",
                        app_id,
                        menu_id,
                        process_id,
                        exc,
                    )

            data = await _post_save(payload, started_at=start)
            await _ensure_menu_process_binding(data)
            return data

    async def save_simple_rule(self, app_id: str, menu_id: str, rule_config: dict) -> dict:
        """保存流程条件边使用的 aPaaS simpleRule.

        平台流程边的 processRule 必须引用已落库的 simpleRuleId；前端也是先调
        /xdap-app/rule/save/simpleRule，再把返回 id 放进 processRule 后保存流程。
        """
        url = f"{self.base_url}/xdap-app/rule/save/simpleRule"
        payload = dict(rule_config or {})
        payload["menuId"] = menu_id
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            if response.status_code >= 400:
                body = (response.text or "")[:2000]
                _log_response(url, response.status_code, body, elapsed_ms, method="POST", request_body=_to_json(payload))
                raise Exception(
                    f"保存流程条件规则失败：apaas 返回 HTTP {response.status_code}。平台错误详情：{body}"
                )
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="POST", request_body=_to_json(payload))
            if data.get("code") not in ("ok",):
                raise Exception(data.get("message", "保存流程条件规则失败"))
            return data.get("data") or {}

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

    async def query_advanced_form_permission(self, app_id: str, form_id: str) -> dict:
        """Query the designer's advanced permission config for a form.

        This mirrors the platform UI endpoint:
        GET /xdap-app/formConfig/query/advancedFormPermissionByFormId
        """
        ts = self._get_timestamp()
        url = f"{self.base_url}/xdap-app/formConfig/query/advancedFormPermissionByFormId"
        params = {"timestamp": ts, "formId": form_id, "reproduce": "DISABLE"}
        _log_request("GET", url, params=params)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=self._get_headers(app_id), params=params)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="GET")
            if data.get("code") not in ("ok", 200):
                raise Exception(data.get("message", "查询高级表单权限失败"))
            return data.get("data") or {}

    async def update_dict(self, app_id: str, dict_id: str, dict_code: str, dict_name: str,
                          describe: str = "", multicolor_status: str = "ENABLE") -> dict:
        """更新字典基本信息（POST /xdap-app/dataDictionary/edit/dataDictionary/fromApp）。"""
        url = f"{self.base_url}/xdap-app/dataDictionary/edit/dataDictionary/fromApp"
        payload = {
            "id": dict_id, "appId": app_id,
            "dictionaryCode": dict_code, "dictionaryName": dict_name,
            "dictionaryDescribe": describe,
            "dictionaryStatus": "ENABLE",
            "dictionaryMulticolorStatus": multicolor_status,
            "internalResource": True,
            "dictionaryNameI18nAssociated": False,
            "dictionaryNameI18nResourceCode": "",
            "dictionaryNameI18n": {},
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
                raise Exception(data.get("message", "更新字典失败"))
            return data

    async def update_dict_option(self, app_id: str, dict_id: str, option_id: str,
                                 value_code: str, value_name: str,
                                 display_order: int = 0, describe: str = "",
                                 multicolor: str = "#027AFF") -> dict:
        """更新字典选项（POST /xdap-app/dataDictionary/edit/dictionaryValue/fromApp）。"""
        url = f"{self.base_url}/xdap-app/dataDictionary/edit/dictionaryValue/fromApp"
        payload = {
            "id": option_id, "appId": app_id, "dictionaryId": dict_id,
            "valueCode": value_code, "valueName": value_name,
            "valueNameI18nAssociated": False,
            "valueNameI18nResourceCode": "", "valueNameI18n": {},
            "displayOrder": display_order, "valueDescribe": describe,
            "valueStatus": "ENABLE", "valueMulticolor": multicolor,
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
                raise Exception(data.get("message", "更新字典选项失败"))
            return data

    async def update_model(self, app_id: str, model_id: str, model_code: str, model_name: str,
                           app_name: str = "", model_data_source: str = "") -> dict:
        """更新模型基本信息（POST /xdap-app/dataModel/update）。

        注意：不能改字段，字段走 add_model_field / update_model_field 单独管理。
        """
        url = f"{self.base_url}/xdap-app/dataModel/update"
        payload = {
            "id": model_id, "appId": app_id,
            "modelCode": model_code, "modelName": model_name,
            "modelType": "DATABASE", "modelDataSource": model_data_source,
            "useScope": app_name, "internalResource": True,
            "interfaceType": "CUSTOM", "createType": "NEWCREATE",
            "apiVersion": "V2", "generateType": "NEWCREATE",
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
                raise Exception(data.get("message", "更新模型失败"))
            return data

    async def add_model_field(self, app_id: str, model_id: str, model_code: str,
                              field_code: str, field_name: str,
                              field_type: str = "STRING",
                              database_field_type: str = "",
                              max_length: int = 255,
                              comment: str = "") -> dict:
        """给已有模型加一个字段（POST /xdap-app/modelField/add）。

        field_type: STRING / NUM / DATE / DATETIME / BOOLEAN / TEXT / BIG_TEXT 等
        database_field_type: 存储类型(varchar/text/decimal/date/datetime…)。留空(默认)
            时按 field_type 自动推导 —— 否则大文本/数字/日期会统统被建成 VARCHAR,
            平台字段编辑器类型显示空、原生设计器误渲染(见 _db_type_for_field_type)。
        慎用 approver_id / approval_* 等 apaas 流程保留字 — 平台会 422 拦。
        """
        url = f"{self.base_url}/xdap-app/modelField/add"
        field_type = _normalize_apaas_field_type(field_type)  # TEXT→BIG_TEXT 等, 否则平台类型为空
        db_field_type = database_field_type or _db_type_for_field_type(field_type)
        payload = {
            "dataModelId": model_id, "modelId": model_id,
            "modelCode": model_code, "appId": app_id,
            "fieldCode": field_code, "fieldName": field_name,
            "fieldType": field_type, "databaseFieldType": db_field_type,
            "fieldStatus": "ENABLE", "fieldComment": comment or "",
            "maxLength": max_length,
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
                raise Exception(data.get("message", "添加字段失败"))
            return data

    async def update_model_field(self, app_id: str, model_id: str, field_id: str,
                                 field_code: str, field_name: str,
                                 field_type: str | None = None,
                                 max_length: int | None = None,
                                 field_status: str = "ENABLE",
                                 comment: str | None = None) -> dict:
        """更新模型字段（POST /xdap-app/modelField/update/fromApp）。

        field_type 改类型时 apaas 行为：可能影响存量数据，建议走"禁用 + 新建"两步
        （field_status='DISABLE' + add_model_field）。本工具不强制，由 agent 决策。

        field_status='DISABLE' 即"禁用字段"（apaas 不能真删字段，只能禁用）。
        """
        url = f"{self.base_url}/xdap-app/modelField/update/fromApp"
        payload: dict = {
            "id": field_id, "modelId": model_id, "appId": app_id,
            "fieldCode": field_code, "fieldName": field_name,
            "fieldStatus": field_status,
        }
        if field_type is not None:
            # TEXT→BIG_TEXT 归一 + 同步存储类型, 否则 fieldType 平台不认 / 与 databaseFieldType
            # 不一致 → 字段建坏(平台编辑器类型显示空)。真机实测 update/fromApp 带二者可正常更新。
            field_type = _normalize_apaas_field_type(field_type)
            payload["fieldType"] = field_type
            payload["databaseFieldType"] = _db_type_for_field_type(field_type)
        if max_length is not None: payload["maxLength"] = max_length
        if comment is not None: payload["fieldComment"] = comment
        _log_request("POST", url, payload)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, request_body=_to_json(payload))
            if data.get("code") not in ("ok", 200):
                raise Exception(data.get("message", "更新字段失败"))
            return data

    async def delete_menu(self, app_id: str, menu_id: str, menu_name: str = "") -> dict:
        """删除菜单（POST /xdap-app/menu/delete/menu）— 普通菜单/表单菜单/自开发菜单都用这个。

        删除表单菜单会联动删表单本身（apaas 内部）。
        """
        url = f"{self.base_url}/xdap-app/menu/delete/menu"
        payload = {"id": menu_id, "appId": app_id, "menuName": menu_name or ""}
        _log_request("POST", url, payload)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, request_body=_to_json(payload))
            if data.get("code") not in ("ok", 200):
                raise Exception(data.get("message", "删除菜单失败"))
            return data

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

    async def query_operate_logs(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        filters: Optional[dict[str, Any]] = None,
    ) -> dict:
        """查询低代码租户操作日志。"""
        url = f"{self.base_url}/xdap-app/operateLog/query/operateLogs"
        payload = {
            "page": page,
            "pageSize": page_size,
            "order": "DESC",
            "operationUsers": [],
            "functionMenu": "",
            "operationType": "",
            "operationObject": "",
        }
        payload.update({k: v for k, v in (filters or {}).items() if v not in (None, "")})
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(
                url,
                headers=self._get_headers(),
                json=payload,
            )
            elapsed_ms = (time.time() - start) * 1000
            if response.status_code == 401:
                logger.error("401 Unauthorized - token可能已过期或无效")
                raise Exception(APAAS_TOKEN_EXPIRED)
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms, method="POST", request_body=_to_json(payload))
            if isinstance(data, dict) and data.get("code") not in (None, "ok", 200):
                raise Exception(data.get("message", "查询操作日志失败"))
            return data if isinstance(data, dict) else {"data": data}

    async def query_models(self, app_id: str, with_fields: bool = True) -> list:
        """查询应用下的所有数据模型.

        with_fields=True (默认, 向后兼容): 同时并发拉每个模型的字段.
        with_fields=False: 只返模型列表 (id/modelCode/modelName), 不给每个模型捞字段 ——
          用于只需"查重 / 找 model_id"的场景。避免 N 个模型 × 每步都全量捞字段
          = O(N²) 的 modelField/query 风暴 (实测 112 模型生成打了 1.3 万次冗余查询, ~6.5h)。
          调用方真需要某个模型的字段时, 自己按 model_id 单独 query_model_fields (懒加载)。
        """
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

            model_ids = [
                str(model.get("id", model.get("dataModelId", "")) or "").strip()
                for model in models
            ]
            if with_fields:
                # 并发查询每个模型的字段，避免原先串行 await 导致的 N * RTT 累计等待。
                # 用 Semaphore 限流防止触发平台端速率限制；单个查询失败不影响整批。
                # ⚠️ O(N²) 警告：仅在真需要全量字段时传 with_fields=True；查重/找 id 用 False。
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

                fields_by_index = await asyncio.gather(
                    *[_fetch_fields(mid) for mid in model_ids]
                )
            else:
                # 懒加载模式：不给每个模型捞字段（调用方按需 query_model_fields(model_id)）
                fields_by_index = [[] for _ in model_ids]

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

    async def disable_dict(self, app_id: str, dict_id: str) -> dict:
        """禁用字典（apaas 没真 delete，禁用是终态）。

        GET /xdap-app/dataDictionary/disable/dataDictionary?id=...
        """
        url = f"{self.base_url}/xdap-app/dataDictionary/disable/dataDictionary?id={dict_id}"
        _log_request("GET", url)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=self._get_headers(app_id))
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="GET")
            if data.get("code") not in ("ok", 200):
                raise Exception(data.get("message", "禁用字典失败"))
            logger.info(f"禁用字典成功: dict_id={dict_id}")
            return data

    async def disable_dict_option(self, app_id: str, option_id: str) -> dict:
        """禁用字典选项（apaas 没真 delete）。

        GET /xdap-app/dataDictionary/disable/dictionaryValue?id=...
        """
        url = f"{self.base_url}/xdap-app/dataDictionary/disable/dictionaryValue?id={option_id}"
        _log_request("GET", url)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=self._get_headers(app_id))
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="GET")
            if data.get("code") not in ("ok", 200):
                raise Exception(data.get("message", "禁用字典选项失败"))
            logger.info(f"禁用字典选项成功: option_id={option_id}")
            return data

    async def query_business_data(
        self,
        app_id: str,
        form_id: str,
        tab_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """查询表单运行时业务数据（用户提交的应用数据行，分页）。

        POST /xdap-app/business/v2/query/listPageBusinessData
        （这是表单"列表页"页面背后的真接口，跟 dev_scene_runtime_api.py 里
         给自开发包用的写法一致）

        参数：
          - formId / tabId 必传（tabId 即表单视图 id，调 query_form_views 拿默认 tab）
          - page / pageSize 默认 1 / 20，pageSize 上限 200
          - appId 不传（走 header xdapappid，平台自己拿）
        """
        url = f"{self.base_url}/xdap-app/business/v2/query/listPageBusinessData"
        payload = {
            "formId": form_id,
            "tabId": tab_id,
            "page": int(page),
            "pageSize": int(page_size),
            "selectorFilterConditionList": [],
            "filterConditionGroup": [],
            "orders": [],
            "type": "initialize",
        }
        _log_request("POST", url, payload)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            try:
                data = response.json()
            except Exception:
                body_preview = response.text[:500] if response.text else "(empty body)"
                _log_response(url, response.status_code, {"raw_body_preview": body_preview},
                              elapsed_ms, method="POST", request_body=_to_json(payload))
                raise Exception(
                    f"查询业务数据失败（HTTP {response.status_code}，非 JSON 响应）：{body_preview}"
                )

            _log_response(url, response.status_code, data, elapsed_ms, method="POST",
                          request_body=_to_json(payload))

            if response.status_code >= 400 or data.get("code") not in ("ok", 200):
                raise Exception(
                    f"查询业务数据失败 (HTTP {response.status_code}, code={data.get('code')}): "
                    f"{data.get('message') or data.get('msg') or 'unknown'} | full={_to_json(data)[:300]}"
                )
            return data  # 平台直接返 {code, data:[...], total:N}，不嵌套

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

    async def bind_menu_process(
        self,
        app_id: str,
        menu_id: str,
        process_id: str,
    ) -> dict:
        """Bind a MODEL menu to its workflow processId.

        Runtime form submission resolves the active approval flow through the
        menu's processId. Saving processConfig creates the process, but some
        API paths do not backfill this menu field automatically.
        """
        resolved_menu_id = str(menu_id or "").strip()
        resolved_process_id = str(process_id or "").strip()
        if not resolved_menu_id or not resolved_process_id:
            raise Exception("menu_id 和 process_id 都不能为空")

        menus = await self.query_menus(app_id)
        target = None

        def _walk(nodes):
            nonlocal target
            for n in nodes or []:
                if not isinstance(n, dict):
                    continue
                if str(n.get("id") or n.get("menuId") or "") == resolved_menu_id:
                    target = n
                    return
                children = n.get("submenus") or n.get("children") or n.get("subMenus") or n.get("menuList")
                if children:
                    _walk(children)
                if target is not None:
                    return

        _walk(menus or [])
        if not target:
            raise Exception(f"找不到 menu_id={resolved_menu_id} 的菜单")

        current_process_id = str(target.get("processId") or "").strip()
        if current_process_id == resolved_process_id:
            return {"id": resolved_menu_id, "processId": resolved_process_id, "unchanged": True}

        payload = {
            k: v for k, v in target.items()
            if k not in ("submenus", "children", "subMenus", "menuList")
        }
        payload["processId"] = resolved_process_id
        payload.setdefault("appId", app_id)
        payload.setdefault("menuNameI18nResourceCode", "")
        payload.setdefault("menuNameI18n", {})
        payload.setdefault("menuCustomIcon", "")
        payload.setdefault("datasourceName", "")

        url = f"{self.base_url}/xdap-app/menu/save/menu"
        _log_request(
            "POST",
            url,
            {
                "_summary": "bind menu processId",
                "menu_id": resolved_menu_id,
                "old_process_id": current_process_id,
                "new_process_id": resolved_process_id,
            },
        )
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms)
            if data.get("code") != "ok":
                raise Exception(data.get("message", "绑定菜单流程失败"))

        verify_menus = await self.query_menus(app_id)
        verified = None

        def _verify(nodes):
            nonlocal verified
            for n in nodes or []:
                if not isinstance(n, dict):
                    continue
                if str(n.get("id") or n.get("menuId") or "") == resolved_menu_id:
                    verified = n
                    return
                children = n.get("submenus") or n.get("children") or n.get("subMenus") or n.get("menuList")
                if children:
                    _verify(children)
                if verified is not None:
                    return

        _verify(verify_menus or [])
        verified_process_id = str((verified or {}).get("processId") or "").strip()
        if verified_process_id != resolved_process_id:
            raise Exception(
                f"菜单流程绑定未生效: menu_id={resolved_menu_id}, "
                f"expected={resolved_process_id}, actual={verified_process_id or '<empty>'}"
            )
        logger.info("菜单流程绑定成功: menu_id=%s process_id=%s", resolved_menu_id, resolved_process_id)
        return {"id": resolved_menu_id, "processId": resolved_process_id, "unchanged": False}

    # 2026-05-25: 菜单分组 + 移动菜单到分组. 平台 /xdap-app/menu/save/menu endpoint
    # 同时支持 menuType=GROUP (分组) 和 parentId (挂到 group 下).
    async def create_menu_group(
        self,
        app_id: str,
        group_name: str,
        menu_order: int = 0,
        parent_id: str = "",
    ) -> dict:
        """创建菜单分组 (menuType=GROUP, 无 formId). 可选 parent_id 嵌套到另一个分组下.

        2026-05-25: payload 跟 super-agents-dev saveAppMenu 对齐 — 含 i18n / customIcon
        / datasourceName 等占位字段, 否则平台 save 返 ok 但 query 不到 (静默丢)。
        """
        url = f"{self.base_url}/xdap-app/menu/save/menu"
        payload = {
            "appId": app_id,
            "menuName": group_name,
            "menuNameI18nResourceCode": "",
            "menuNameI18nAssociated": False,
            "menuNameI18n": {},
            "menuType": "GROUP",
            "menuDisplay": "ALL",
            "menuOrder": menu_order,
            "menuIcon": "userInfo",
            "menuCustomIcon": "",
            "iconColor": "#027AFF",
            "datasourceId": "",
            "datasourceName": "",
            "datasourceCode": "",
            "menuModelType": "",
            "cusIconStatus": "DISABLE",
            "cusModelPageStatus": "DISABLE",
            "newWindowStatus": "DISABLE",
        }
        if parent_id and parent_id.strip():
            payload["parentId"] = parent_id.strip()
        _log_request("POST", url, payload)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms)
            if data.get("code") == "ok":
                logger.info(f"菜单分组创建成功: {group_name}")
                return data.get("data", {}) or {}
            raise Exception(data.get("message", "创建菜单分组失败"))

    async def rename_menu(
        self,
        app_id: str,
        menu_id: str,
        new_name: str,
    ) -> dict:
        """改菜单名 — POST /xdap-app/menu/save/menu (普通菜单 + GROUP 通用).

        save/menu 接受 menuName 更新 (verified). 流程: query 拿 target 完整字段 → 替换
        menuName → save → verify menuName 真改了.
        """
        # 1. 拿 target 完整原始字段
        menus = await self.query_menus(app_id)
        target = None

        def _walk(nodes):
            nonlocal target
            for n in nodes or []:
                if not isinstance(n, dict):
                    continue
                if str(n.get("id") or n.get("menuId") or "") == str(menu_id):
                    target = n
                    return
                if n.get("submenus"):
                    _walk(n["submenus"])

        _walk(menus or [])
        if not target:
            raise Exception(f"找不到 menu_id={menu_id} 的菜单")

        # 2. 构 payload — verbatim 透传 + 改 menuName + i18n 占位 (super-agents 兼容)
        payload = {
            k: v for k, v in target.items()
            if k not in ("submenus", "children", "subMenus", "menuList")
        }
        payload["menuName"] = new_name.strip()
        payload.setdefault("menuNameI18nResourceCode", "")
        payload.setdefault("menuNameI18n", {})
        payload.setdefault("menuCustomIcon", "")
        payload.setdefault("datasourceName", "")

        url = f"{self.base_url}/xdap-app/menu/save/menu"
        _log_request("POST", url, {"_summary": "menu rename",
                                    "menu_id": menu_id,
                                    "old_name": target.get("menuName"),
                                    "new_name": new_name})
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms)
            if data.get("code") != "ok":
                raise Exception(data.get("message", "改菜单名失败"))

        # 3. verify
        verify_menus = await self.query_menus(app_id)

        def _verify(nodes):
            for n in nodes or []:
                if str(n.get("id") or n.get("menuId") or "") == str(menu_id):
                    return n.get("menuName")
                if n.get("submenus"):
                    r = _verify(n["submenus"])
                    if r is not None:
                        return r
            return None

        actual = _verify(verify_menus or [])
        if actual != new_name.strip():
            raise Exception(
                f"save 返 ok 但 menuName 未持久化: expected={new_name!r} actual={actual!r}"
            )
        logger.info(f"菜单 {menu_id} 改名 → 「{new_name}」 (verified)")
        return {"menu_id": menu_id, "menu_name": new_name.strip(), "verified": True}

    async def update_self_dev_menu_link_url(
        self,
        app_id: str,
        menu_id: str,
        link_url: str,
        menu_type: str = "",
        confirmed: bool = False,
    ) -> dict:
        """更新自开发菜单 linkUrl — POST /xdap-app/menu/save/menu.

        平台的 save/menu 带 id 时是更新。这里先 query_menus 拿完整原始字段，
        再只覆盖 linkUrl，避免丢 menuName/menuIcon/menuOrder/owner 等平台字段。
        如果现有 linkUrl 与目标 linkUrl 不一致，默认只返回确认请求；调用方确认
        这是同一菜单切换到新包后，再传 confirmed=True 真正更新。
        menu_type 默认保留原值；确需强制时可传 CUSTOM/MENU。
        """
        menus = await self.query_menus(app_id)
        target = None

        def _walk(nodes):
            nonlocal target
            for n in nodes or []:
                if not isinstance(n, dict):
                    continue
                if str(n.get("id") or n.get("menuId") or "") == str(menu_id):
                    target = n
                    return
                kids = n.get("submenus") or n.get("children") or []
                if kids:
                    _walk(kids)

        _walk(menus or [])
        if not target:
            raise Exception(f"找不到 menu_id={menu_id} 的菜单")

        old_link_url = str(target.get("linkUrl") or target.get("link_url") or "")
        if old_link_url and old_link_url != link_url.strip() and not confirmed:
            return {
                "needs_confirmation": True,
                "menu_id": menu_id,
                "menu_name": str(target.get("menuName") or target.get("menu_name") or ""),
                "old_link_url": old_link_url,
                "link_url": link_url.strip(),
                "message": "该菜单当前指向另一个自开发包，需用户确认后再更新 linkUrl。",
            }

        payload = {
            k: v for k, v in target.items()
            if k not in ("submenus", "children", "subMenus", "menuList")
        }
        payload["appId"] = app_id
        payload["id"] = str(target.get("id") or target.get("menuId") or menu_id)
        payload["linkUrl"] = link_url.strip()
        if menu_type.strip():
            payload["menuType"] = menu_type.strip()

        payload.setdefault("menuNameI18nResourceCode", "")
        payload.setdefault("menuNameI18nAssociated", False)
        payload.setdefault("menuNameI18n", {})
        payload.setdefault("menuIcon", "dashboard")
        payload.setdefault("datasourceId", "")
        payload.setdefault("datasourceName", "")
        payload.setdefault("linkContent", "")
        payload.setdefault("linkMobileUrl", "")
        payload.setdefault("linkMobileContent", "")
        payload.setdefault("custom", "")
        payload.setdefault("menuModelType", "DATABASE")
        payload.setdefault("cusIconStatus", "DISABLE")
        payload.setdefault("cusModelPageStatus", "DISABLE")
        payload.setdefault("menuCustomIcon", "")
        payload.setdefault("newWindowStatus", "DISABLE")
        payload.setdefault("menuDisplay", "PC")
        payload.setdefault("iconColor", "#027AFF")

        url = f"{self.base_url}/xdap-app/menu/save/menu"
        _log_request("POST", url, {
            "_summary": "self-dev menu linkUrl update",
            "menu_id": menu_id,
            "old_link_url": old_link_url,
            "new_link_url": link_url.strip(),
            "menu_type": payload.get("menuType"),
        })
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms)
            if data.get("code") != "ok":
                raise Exception(data.get("message", "更新自开发菜单 linkUrl 失败"))

        verify_menus = await self.query_menus(app_id)

        def _verify(nodes):
            for n in nodes or []:
                if str(n.get("id") or n.get("menuId") or "") == str(menu_id):
                    return str(n.get("linkUrl") or n.get("link_url") or "")
                kids = n.get("submenus") or n.get("children") or []
                if kids:
                    found = _verify(kids)
                    if found is not None:
                        return found
            return None

        actual = _verify(verify_menus or [])
        if actual != link_url.strip():
            raise Exception(
                f"save 返 ok 但 linkUrl 未持久化: expected={link_url!r} actual={actual!r}"
            )
        logger.info(f"菜单 {menu_id} linkUrl: {old_link_url} → {link_url.strip()} (verified)")
        return {
            "menu_id": menu_id,
            "old_link_url": old_link_url,
            "link_url": link_url.strip(),
            "menu_type": payload.get("menuType"),
            "verified": True,
        }

    async def update_menu_parent(
        self,
        app_id: str,
        menu_id: str,
        parent_id: str = "",
        menu_order: int = 0,
    ) -> dict:
        """改菜单的父分组 — 用平台真 reorder 端点 POST /xdap-app/menu/queue/appMenu.

        2026-05-25 v2: 之前用 /xdap-app/menu/save/menu 返 ok 但 parentId 静默不持久化.
        挖 platform app.*.js bundle 发现真端点是 `/xdap-app/menu/queue/appMenu`
        (前端常量 MENU_LIST_DROP_SORT — 拖拽排序专用), body 是**完整菜单树**
        (含 submenus 嵌套). 实证 trial 100% 通, 验证 parent_id 真持久化.

        parent_id="" = 移到根; parent_id=<group_id> = 挂到该 group 下.
        """
        # 1. 拿当前菜单完整树 (manageAppMenu, 含 GROUP + 嵌套 submenus)
        menus = await self.query_menus(app_id)

        # 2. 平铺找 target, 从原位置摘出
        target: dict | None = None

        def _walk_remove(nodes: list) -> list:
            """递归遍历 + 把 target menu 从原位置摘走 (从 root 或 group submenus)."""
            nonlocal target
            cleaned = []
            for n in nodes or []:
                if not isinstance(n, dict):
                    continue
                if str(n.get("id") or n.get("menuId") or "") == str(menu_id):
                    target = n
                    continue
                copy = dict(n)
                kids = n.get("submenus") or n.get("children") or []
                copy["submenus"] = _walk_remove(kids) if kids else []
                cleaned.append(copy)
            return cleaned

        new_tree = _walk_remove(menus or [])
        if not target:
            raise Exception(f"找不到 menu_id={menu_id} 的菜单, 无法更新父分组")

        # 3. 更新 target 的 parentId/menuOrder, 子菜单不嵌孙
        target_copy = dict(target)
        target_copy["parentId"] = parent_id.strip() if parent_id else ""
        target_copy["menuOrder"] = menu_order
        target_copy["submenus"] = []

        # 4. 插入到目标位置
        pid = parent_id.strip() if parent_id else ""
        if pid:
            def _insert(nodes: list) -> bool:
                for n in nodes:
                    if str(n.get("id") or n.get("menuId") or "") == pid:
                        n.setdefault("submenus", []).append(target_copy)
                        return True
                    if n.get("submenus") and _insert(n["submenus"]):
                        return True
                return False

            if not _insert(new_tree):
                raise Exception(f"找不到目标 group menu_id={pid}")
        else:
            new_tree.append(target_copy)

        # 5. POST 完整树到 queue/appMenu (平台真 reorder 端点)
        url = f"{self.base_url}/xdap-app/menu/queue/appMenu"
        _log_request("POST", url, {"_summary": "menu reorder (full tree)",
                                    "tree_root_count": len(new_tree),
                                    "target_menu_id": menu_id, "target_parent_id": pid or "root"})
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=new_tree)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms)
            if data.get("code") != "ok":
                raise Exception(data.get("message", "更新菜单父分组失败"))

        # 6. verify — 平台对全树 reorder 一般立刻持久化, 但 paranoid check
        verify_menus = await self.query_menus(app_id)

        def _verify_walk(nodes):
            for n in nodes or []:
                if str(n.get("id") or n.get("menuId") or "") == str(menu_id):
                    return str(n.get("parentId") or "")
                if n.get("submenus"):
                    sub = _verify_walk(n["submenus"])
                    if sub is not None:
                        return sub
            return None

        actual_parent = _verify_walk(verify_menus or [])
        if str(actual_parent or "") != pid:
            raise Exception(
                f"queue/appMenu 返 ok 但 parentId 未持久化: expected={pid!r} actual={actual_parent!r}"
            )
        logger.info(f"菜单 {menu_id} 父分组 → {pid or '根'} (queue/appMenu verified)")
        return {"menu_id": menu_id, "parent_id": pid, "verified": True}

    # ───────────────────── 业务事件 (research-business-event-api.md v2) ─────────────────────
    # 9 个 endpoint 实证, 这里实现 6 个高频. 详 docs/research-business-event-api.md 第 5 节.

    async def list_business_events(self, app_id: str, keyword: str = "",
                                    page: int = 1, page_size: int = 20) -> dict:
        """列应用业务事件 — GET /xdap-app/event/query/list."""
        url = f"{self.base_url}/xdap-app/event/query/list"
        params = {"appId": app_id, "keyword": keyword, "page": page, "pageSize": page_size}
        _log_request("GET", url, params)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=self._get_headers(app_id), params=params)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="GET")
            if data.get("code") != "ok":
                raise Exception(data.get("message", "查询业务事件失败"))
            # apaas 把事件放顶层 {total, table:[...]}, 不是 data 里 —— 规整后路由才取得到。
            return _normalize_business_event_list(data)

    async def get_business_event_detail(self, event_id: str, app_id: str) -> dict:
        """查事件详情 (含完整 DAG) — GET /xdap-app/event/query/detail."""
        url = f"{self.base_url}/xdap-app/event/query/detail"
        params = {"eventId": event_id, "appId": app_id}
        _log_request("GET", url, params)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=self._get_headers(app_id), params=params)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="GET")
            if data.get("code") != "ok":
                raise Exception(data.get("message", "查询业务事件详情失败"))
            return data.get("data") or {}

    async def create_business_event(self, app_id: str, event_name: str,
                                     event_type: str = "EVENT_OPERATION") -> dict:
        """创建事件 metadata stub — POST /xdap-app/event/add/event.

        返结构含 id (eventId 24hex). 后续 get_business_event_detail 拿 stub 完整 DAG
        (平台自动填好 boCodeBORelationProperties 等元数据), agent 改 trigger / 加节点
        后调 save_business_event 持久化.
        """
        url = f"{self.base_url}/xdap-app/event/add/event"
        payload = {
            "appId": app_id,
            "eventType": event_type,
            "eventName": event_name,
            "version": "v3.0",
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
                raise Exception(data.get("message", "创建业务事件失败"))
            return data.get("data") or {}

    async def save_business_event(self, event_data: dict, app_id: str) -> dict:
        """保存事件完整 DAG — POST /xdap-app/event/save/event.

        event_data 是从 get_business_event_detail 拿到的完整结构 + agent 修改后传回.
        包括 triggerNodeNd / eventNodeNdList / endNode + 顶层元数据.
        """
        url = f"{self.base_url}/xdap-app/event/save/event"
        _log_request("POST", url, {
            "_summary": "event save (full DAG)",
            "eventName": event_data.get("eventName"),
            "eventType": event_data.get("eventType"),
            "nodes_count": len(event_data.get("eventNodeNdList") or []),
        })
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=event_data)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms)
            if data.get("code") != "ok":
                raise Exception(data.get("message", "保存业务事件失败"))
            return data.get("data") or {}

    async def delete_business_event(self, event_id: str, app_id: str) -> dict:
        """删除事件 — GET /xdap-app/event/del/event ⚠️ 是 GET 不是 DELETE."""
        url = f"{self.base_url}/xdap-app/event/del/event"
        params = {"eventId": event_id, "appId": app_id}
        _log_request("GET", url, params)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=self._get_headers(app_id), params=params)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="GET")
            if data.get("code") != "ok":
                raise Exception(data.get("message", "删除业务事件失败"))
            return data.get("data") or {}

    async def list_form_menus_for_event(self, app_id: str) -> list:
        """列应用所有表单菜单, 给 agent 选 triggerFormId — GET /xdap-app/menu/queryAllFormMenu?eventFlag=true."""
        url = f"{self.base_url}/xdap-app/menu/queryAllFormMenu"
        params = {"appId": app_id, "eventFlag": "true"}
        _log_request("GET", url, params)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=self._get_headers(app_id), params=params)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="GET")
            if data.get("code") != "ok":
                raise Exception(data.get("message", "查询表单菜单失败"))
            raw = data.get("data") or []
            # 平台返结构可能含嵌套, 平铺出来给 agent 用
            out = []
            def _walk(nodes):
                for n in nodes or []:
                    if not isinstance(n, dict):
                        continue
                    if n.get("formId") or n.get("bocCode"):
                        out.append({
                            "menu_id": str(n.get("id") or n.get("menuId") or ""),
                            "menu_name": n.get("menuName") or "",
                            "form_id": str(n.get("formId") or ""),
                            "boc_code": str(n.get("bocCode") or n.get("boCode") or ""),
                        })
                    _walk(n.get("submenus") or n.get("children") or [])
            _walk(raw if isinstance(raw, list) else [raw])
            return out

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
            raise Exception(f"manageAppMenu 返回失败: code={data.get('code')}, message={data.get('message') or data.get('msg') or data}")

    async def query_all_form_configs(self, app_id: str, *, page_size: int = 500) -> list:
        """列应用所有表单配置 — GET /xdap-app/formConfig/query/allFormConfigList。

        这是「表单管理」列表页的数据源:每条含 id(=formId) / formName(表单实体名) /
        formCode。**formName 是「表单名称」列展示的实体名**(2026-06-18 浏览器实证),
        老应用建表时 formConfigDetail 同步失败会停在平台默认占位「我的待办」。
        repair_form_entity_names 用它检测哪些表单实体名是占位、需修。

        响应结构防御:data 可能直接是 list,或 {list/rows/records/data: [...]}。
        """
        ts = self._get_timestamp()
        url = f"{self.base_url}/xdap-app/formConfig/query/allFormConfigList"
        params = {"appId": app_id, "page": 1, "pageSize": page_size, "timestamp": ts}
        _log_request("GET", url, params=params)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=self._get_headers(app_id), params=params)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="GET")
            if data.get("code") not in ("ok", None) and data.get("status") not in (200, "200", None):
                return []
            body = data.get("data")
            if isinstance(body, list):
                return body
            if isinstance(body, dict):
                for key in ("list", "rows", "records", "data", "table"):
                    rows = body.get(key)
                    if isinstance(rows, list):
                        return rows
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

    async def query_form_context_config(self, app_id: str, form_id: str) -> dict:
        """查询可直接保存的 simpleFormConfig。

        formConfig/save/formConfigDetail 要求提交 v2/form/query/formContext 返回的
        simpleFormConfig 完整对象；detailPageConfigById 返回的结构能读详情，但部分
        元信息（如 formName）保存后不会生效。
        """
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
                result = data.get("data", {})
                simple = result.get("simpleFormConfig") if isinstance(result, dict) else None
                if isinstance(simple, dict):
                    logger.info("查询表单上下文配置成功: formId=%s", form_id)
                    return simple
                if isinstance(result, dict):
                    return result
            raise Exception(data.get("message", "查询表单上下文配置失败"))

    async def query_list_page_config(self, app_id: str, form_id: str) -> dict:
        """查询表单列表设计配置 (列表 tab 设的查询条件 + 列字段).

        2026-05-27 T2 实测: detailPageConfigById / formContext 都**不返**
        listPageView 数据 — 列设计配置走独立 endpoint:
            POST /xdap-app/formConfig/query/listPageConfigById?timestamp=...
            body: { formId, appId }

        返:
          - listPageViews[]: 每个 view 含:
              tabId, tabName, formId,
              queryConditions[]: { uuid, boCode, label, componentType, filterType }
              queryLists[]: { uuid, label, componentType, displayFlag, alignmentType }
          - defaultQueryLists[]: 默认列字段池
        """
        ts = self._get_timestamp()
        url = (
            f"{self.base_url}/xdap-app/formConfig/query/"
            f"listPageConfigById?timestamp={ts}"
        )
        payload = {"formId": form_id, "appId": app_id}
        _log_request("POST", url, payload)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="POST")
            if data.get("code") == "ok":
                return data.get("data", {})
            raise Exception(data.get("message", "查询列表设计配置失败"))

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
            form_id = _extract_form_id_from_config(form_config)
            if form_id:
                await self.ensure_form_excel_io_config(app_id, form_id, form_config)
            return data

    async def ensure_form_excel_io_config(self, app_id: str, form_id: str, form_config: dict) -> dict:
        """保存表单后统一开启 Excel 导入/导出配置。"""
        result = {"import": None, "export": None}
        try:
            result["import"] = await self.update_excel_import_config(
                app_id,
                form_id,
                build_default_excel_import_config(),
            )
        except Exception as exc:
            logger.warning("更新 Excel 导入配置失败 (formId=%s): %s", form_id, exc)
        try:
            result["export"] = await self.update_excel_export_config(
                app_id,
                form_id,
                build_default_excel_export_config(form_config),
            )
        except Exception as exc:
            logger.warning("更新 Excel 导出配置失败 (formId=%s): %s", form_id, exc)
        return result

    async def update_excel_import_config(self, app_id: str, form_id: str, excel_import_config: dict) -> dict:
        """更新表单 Excel 导入配置。"""
        ts = self._get_timestamp()
        url = f"{self.base_url}/xdap-app/formConfig/update/excelImportConfig?timestamp={ts}"
        payload = {"id": form_id, "excelImportConfig": excel_import_config}
        _log_request("POST", url, payload)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="POST")
            if data.get("code") != "ok":
                raise Exception(data.get("message", "更新 Excel 导入配置失败"))
            return data

    async def update_excel_export_config(self, app_id: str, form_id: str, excel_export_config: dict) -> dict:
        """更新表单 Excel 导出配置。"""
        ts = self._get_timestamp()
        url = f"{self.base_url}/xdap-app/formConfig/update/excelExportConfig?timestamp={ts}"
        payload = {"id": form_id, "excelExportConfig": excel_export_config}
        _log_request("POST", url, payload)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="POST")
            if data.get("code") != "ok":
                raise Exception(data.get("message", "更新 Excel 导出配置失败"))
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

    # ───────────────────────────────────────────────────────────
    # Business Events 补全 — 3 个旧版没有的方法
    # （旧的 6 个在 1826-1959 行：list_business_events / get_business_event_detail /
    #   create_business_event / save_business_event / delete_business_event /
    #   list_form_menus_for_event；保留不动）
    # ───────────────────────────────────────────────────────────

    async def list_business_events_in_tenant(self, page: int = 1, page_size: int = 20, keyword: str = "") -> dict:
        """租户业务事件中心 list — POST /xdap-app/event/query/allEventList

        跨应用聚合的只读视图。返回 {table:[{eventId, appName, eventCode, callbackUrl, ...}], total}
        """
        url = f"{self.base_url}/xdap-app/event/query/allEventList"
        payload = {"page": page, "pageSize": page_size, "keyword": keyword or ""}
        _log_request("POST", url, payload)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="POST", request_body=_to_json(payload))
            if data.get("code") != "ok":
                raise Exception(data.get("message", "查租户业务事件列表失败"))
            return {"table": data.get("table") or [], "total": data.get("total") or 0}

    async def query_business_event_trees(self, app_id: str) -> list:
        """应用业务事件分类树 — GET /xdap-app/event/queryTrees

        左侧分类菜单（外部触发 / 定时触发 / 表单触发 等分组）的 tree 结构
        """
        url = f"{self.base_url}/xdap-app/event/queryTrees"
        params = {"appId": app_id}
        _log_request("GET", url, params)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=self._get_headers(app_id), params=params)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="GET")
            if data.get("code") != "ok":
                raise Exception(data.get("message", "查业务事件分类树失败"))
            return data.get("data") or []

    async def list_business_event_execution_history(
        self, event_id: str, app_id: str, page: int = 1, page_size: int = 10,
        status: str = "", before_time: str = "", end_time: str = "",
    ) -> dict:
        """查业务事件执行历史 — POST /xdap-app/event/query/exeHistory/list

        返回 {table:[{触发时间/执行时长/触发方式/触发人/状态/...}], total}
        status: ENABLE/DISABLE 过滤；beforeTime/endTime: 时间区间过滤（"YYYY-MM-DD HH:mm:ss"）
        """
        url = f"{self.base_url}/xdap-app/event/query/exeHistory/list"
        payload = {
            "page": page, "pageSize": page_size, "status": status or "",
            "beforeTime": before_time or "", "endTime": end_time or "",
            "eventId": event_id,
        }
        _log_request("POST", url, payload)
        start = time.time()
        async with httpx.AsyncClient(verify=False, timeout=APAAS_HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms, method="POST", request_body=_to_json(payload))
            if data.get("code") != "ok":
                raise Exception(data.get("message", "查业务事件执行历史失败"))
            return {"table": data.get("table") or [], "total": data.get("total") or 0}
