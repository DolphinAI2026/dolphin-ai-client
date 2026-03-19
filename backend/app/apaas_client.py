from __future__ import annotations
import httpx
import time
import base64
from typing import Optional
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

import logging

logger = logging.getLogger(__name__)

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
        self.base_url = base_url or settings.apaas_base_url
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

        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            response = await client.post(
                f"{self.base_url}/xdap-admin/user/login",
                headers={"Content-Type": "application/json"},
                json={
                    "account": account,
                    "password": encrypted_password,
                    "type": "account",
                    "tenantId": self.tenant_id,
                    "loginType": "MANAGE"
                }
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") == "ok":
                self.token = data["data"]["token"]
                user = data["data"].get("user", {})
                self.user_id = str(user.get("id", ""))
                logger.info(f"登录成功 - token已设置: {bool(self.token)}, user_id: {self.user_id}")
                return data["data"]
            else:
                logger.error(f"登录失败: {data.get('message')}")
                raise Exception(data.get("message", "登录失败"))

    async def test_connection(self) -> dict:
        """测试连接：用当前token调一个轻量接口验证是否有效"""
        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            response = await client.get(
                f"{self.base_url}/xdap-app/apaasApplications/queryAppList",
                headers=self._get_headers(),
                params={"page": 1, "pageSize": 1}
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") == "ok":
                return {"status": "ok", "message": "连接成功"}
            else:
                raise Exception(data.get("message", "连接失败"))

    async def create_app(self, app_name: str, app_code: str, description: str = "") -> dict:
        """创建应用"""
        if not self.token:
            raise Exception("未设置token，请先调用login()或在初始化时传入token")

        headers = self._get_headers()
        logger.info(f"创建应用请求 - app_name: {app_name}, token存在: {bool(self.token)}")

        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            response = await client.post(
                f"{self.base_url}/xdap-app/apaasApplications/addApp",
                json={
                    "appName": app_name,
                    "appCode": app_code,
                    "appDesc": description,
                    "appType": "CUSTOM"
                },
                headers=headers
            )

            if response.status_code == 401:
                logger.error(f"401 Unauthorized - token可能已过期或无效")
                logger.error(f"Response: {response.text}")
                raise Exception("Token已过期或无效，请重新连接APaaS平台")

            response.raise_for_status()
            data = response.json()
            if data.get("code") == "ok":
                return data.get("data", {})
            else:
                raise Exception(f"创建应用失败: {data.get('message')}")

    @property
    def _manage_url(self) -> str:
        return f"{self.base_url}/xdap-app"

    async def _post_resource(self, path: str, payload: dict, app_id: Optional[str] = None) -> dict:
        """通用资源创建方法"""
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            url = f"{self._manage_url}{path}"
            response = await client.post(
                url,
                headers=self._get_headers(app_id=app_id),
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            code = data.get("code")
            logger.info(f"API {path} response: code={code}, data_keys={list(data.keys()) if isinstance(data, dict) else type(data)}")
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
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            headers = self._get_headers(app_id)
            response = await client.post(
                f"{self.base_url}/xdap-app/process/save/processConfig",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") not in ("ok",):
                raise Exception(data.get("message", "保存流程失败"))
            return data

    async def create_form_permissions(self, app_id: str, payload: list) -> dict:
        return await self._post_resource("/common/resource/formPermission", payload, app_id)

    async def query_app_list(self, page: int = 1, page_size: int = 200) -> list:
        """查询得帆云平台应用列表"""
        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            response = await client.get(
                f"{self.base_url}/xdap-app/apaasApplications/queryAppList",
                headers=self._get_headers(),
                params={"page": page, "pageSize": page_size, "keyword": "", "status": ""}
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") == "ok":
                result = data.get("table", [])
                return result if isinstance(result, list) else []
            return []

    async def query_models(self, app_id: str) -> list:
        """查询应用下的所有数据模型（含字段）"""
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/xdap-app/dataModel/query/modelWithField",
                headers=self._get_headers(app_id),
                json={"appId": app_id}
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") == "ok":
                models = data.get("table", [])
                # 平台返回的字段在 dataModelFields 中，统一转换为 fields
                for m in models:
                    if 'dataModelFields' in m and 'fields' not in m:
                        m['fields'] = m['dataModelFields']
                return models
            return []

    async def query_dicts(self, app_id: str) -> list:
        """查询应用下的所有数据字典"""
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/xdap-app/dataDictionary/query/dataDictionaryList",
                headers=self._get_headers(app_id),
                json={"keyword": "", "appId": app_id}
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") == "ok":
                return data.get("table", [])
            return []

    async def query_dict_options(self, app_id: str, dict_id: str) -> list:
        """查询字典的所有选项"""
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/xdap-app/dataDictionary/query/dictionaryValueList",
                headers=self._get_headers(app_id),
                json={"dictionaryId": dict_id}
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") == "ok":
                return data.get("table", [])
            return []

    async def add_dict_option(self, app_id: str, dict_id: str, option_code: str, option_name: str, display_order: int = 0) -> dict:
        """为字典添加一个选项"""
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
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/xdap-app/dataDictionary/add/dictionaryValue",
                headers=self._get_headers(app_id),
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") != "ok":
                raise Exception(data.get("message", "添加字典选项失败"))
            return data

    async def create_menu(self, app_id: str, menu_name: str, form_id: str, menu_order: int = 0) -> dict:
        """创建表单菜单 — /menu/save/menu"""
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/xdap-app/menu/save/menu",
                headers=self._get_headers(app_id),
                json={
                    "appId": app_id,
                    "menuName": menu_name,
                    "menuType": "MODEL",
                    "menuOrder": menu_order,
                    "menuDisplay": "ALL",
                    "formId": form_id,
                    "menuIcon": "userInfo",
                }
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") == "ok":
                return data.get("data", {})
            raise Exception(data.get("message", "创建菜单失败"))

    async def query_menus(self, app_id: str) -> list:
        """查询应用的菜单列表（包含表单）"""
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/xdap-app/menu/query/manageAppMenu",
                headers=self._get_headers(app_id),
                json={"appId": app_id}
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") == "ok":
                return data.get("data", [])
            return []

    async def query_form_config(self, app_id: str, form_id: str) -> dict:
        """查询表单的完整配置"""
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/xdap-app/v2/form/query/formContext?formId={form_id}",
                headers=self._get_headers(app_id)
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") == "ok":
                return data.get("data", {}).get("simpleFormConfig", {})
            raise Exception(data.get("message", "查询表单配置失败"))

    async def save_form_config(self, app_id: str, form_config: dict) -> dict:
        """保存表单配置（全量更新）"""
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/xdap-app/formConfig/save/formConfigDetail",
                headers=self._get_headers(app_id),
                json=form_config
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") != "ok":
                raise Exception(data.get("message", "保存表单配置失败"))
            return data

    async def update_form_component(self, app_id: str, form_id: str, component_label: str, updates: dict) -> dict:
        """更新表单中指定组件的属性"""
        # 查询表单配置
        form_config = await self.query_form_config(app_id, form_id)
        components = form_config.get('detailPage', {}).get('formComponents', [])

        # 找到并更新组件
        found = False
        for comp in components:
            if comp.get('label') == component_label:
                comp.update(updates)
                found = True
                break

        if not found:
            raise Exception(f"未找到标签为 '{component_label}' 的组件")

        # 保存
        return await self.save_form_config(app_id, form_config)
