from __future__ import annotations
import httpx
import time
import base64
import json
from typing import Optional, Any
from urllib.parse import parse_qsl, urlsplit
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

import logging
import threading

logger = logging.getLogger(__name__)

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
                raise Exception("Token已过期或无效，请重新连接APaaS平台")

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

        async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
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
        """批量创建数据模型 — /common/resource/v2/appModel"""
        # 调试：打印所有字段编码
        for dm in payload.get("dataModels", []):
            field_codes = [f.get("fieldCode") for f in dm.get("fields", [])]
            logger.info(f"创建模型 {dm.get('modelName')} [{dm.get('modelCode')}] 字段: {field_codes}")
        result = await self._post_resource("/common/resource/v2/appModel", payload, app_id)
        return result if isinstance(result, list) else []

    async def create_form_config(self, app_id: str, payload: list) -> list:
        """批量创建表单配置 — /common/resource/formConfig"""
        logger.info(f"创建表单: {[p.get('formName') for p in payload]}")
        result = await self._post_resource("/common/resource/formConfig", payload, app_id)
        if isinstance(result, list):
            for r in result:
                if isinstance(r, dict):
                    logger.info(f"表单返回: formName={r.get('formName')}, formCode={r.get('formCode')}, menuId={r.get('menuId')}, id={r.get('id')}")
        return result if isinstance(result, list) else []

    async def create_process_config(self, app_id: str, payload: list) -> dict:
        return await self._post_resource("/common/resource/processConfig", payload, app_id)

    async def save_process_config(self, app_id: str, payload: dict) -> dict:
        """用平台内部 save API 创建/保存流程（需要完整的 nodes + edges + bpmn）"""
        url = f"{self.base_url}/xdap-app/process/save/processConfig"
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
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
        return await self._post_resource("/common/resource/formPermission", payload, app_id)

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
        url = f"{self.base_url}/xdap-app/dataModel/query/modelWithField"
        payload = {"appId": app_id}
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms, request_body=_to_json(payload))

            if data.get("code") == "ok":
                models = data.get("table", [])
                # 平台返回的字段在 dataModelFields 中，统一转换为 fields
                for m in models:
                    if 'dataModelFields' in m and 'fields' not in m:
                        m['fields'] = m['dataModelFields']
                logger.info(f"查询到 {len(models)} 个模型: {[m.get('modelCode') for m in models]}")
                return models
            return []

    async def query_dicts(self, app_id: str) -> list:
        """查询应用下的所有数据字典"""
        url = f"{self.base_url}/xdap-app/dataDictionary/query/dataDictionaryList"
        payload = {"keyword": "", "appId": app_id}
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
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

        async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
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

        async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
            response = await client.post(url, headers=self._get_headers(app_id), json=payload)
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()

            _log_response(url, response.status_code, data, elapsed_ms)

            if data.get("code") != "ok":
                raise Exception(data.get("message", "添加字典选项失败"))
            return data

    async def create_menu(self, app_id: str, menu_name: str, form_id: str, menu_order: int = 0) -> dict:
        """创建表单菜单 — /menu/save/menu"""
        url = f"{self.base_url}/xdap-app/menu/save/menu"
        payload = {
            "appId": app_id,
            "menuName": menu_name,
            "menuType": "MODEL",
            "menuOrder": menu_order,
            "menuDisplay": "ALL",
            "formId": form_id,
            "menuIcon": "userInfo",
        }
        _log_request("POST", url, payload)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
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

        async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
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

    async def query_form_config(self, app_id: str, form_id: str) -> dict:
        """查询表单的完整配置"""
        url = f"{self.base_url}/xdap-app/v2/form/query/formContext?formId={form_id}"
        _log_request("GET", url)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
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

    async def save_form_config(self, app_id: str, form_config: dict) -> dict:
        """保存表单配置（全量更新）"""
        url = f"{self.base_url}/xdap-app/formConfig/save/formConfigDetail"
        _log_request("POST", url, form_config)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
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
