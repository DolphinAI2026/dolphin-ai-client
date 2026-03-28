#!/usr/bin/env python3
"""Deploy ALL 15 forms of 全球售后系统 to the aPaaS platform."""
import asyncio, json, sys, os, random, string, copy, time

# Disable proxy
for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(k, None)

import httpx, base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding as rsa_padding
from cryptography.hazmat.backends import default_backend

sys.path.insert(0, os.path.dirname(__file__))

BASE_URL = "https://apaas-poc.definesys.cn/backend"
TENANT_ID = "743906758237356033"
PUBLIC_KEY_B64 = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA97JYGwwqg4ixYVrPHTmj"
    "FmknoRC0mqwA3kQRkGfYqAlMAuTb6GfXgLukkqbJP9OgT54FGiydFNf9Pkk8ReuO"
    "n5aaMZULZmes9rvrSzAuxj6o/I3U159XAoBChnt6USCTJ4BtAv4x/dk5W4fuMBqU"
    "AX9M38W/cbzbF8Y5KfCJRWv4+MYDgxvUlFRoxhXuTLyXpihocd3N1YOaDJ1+Ktwg"
    "2DdTBs8/IhNwdKFgEgZ3AmQPpLdJAcAhtI1vgFD/mwcnJpcvFGI60qs5KusmwgQs"
    "NDddax9h9tbaKEheH5qmgLbp6Dn7mbXeToHZx+l8uYOBVMUJvp6x+RgOTkEGYNo"
    "F7wIDAQAB"
)


class SimpleClient:
    """Standalone aPaaS client without pydantic dependency."""
    def __init__(self):
        self.token = None

    def _ts(self):
        return str(int(time.time() * 1000))

    def _headers(self, app_id=None):
        h = {"Content-Type": "application/json", "xdaptenantid": TENANT_ID, "xdaptimestamp": self._ts()}
        if self.token: h["xdaptoken"] = self.token
        if app_id: h["appid"] = app_id
        return h

    async def login(self, account, password):
        pem_lines = [PUBLIC_KEY_B64[i:i+64] for i in range(0, len(PUBLIC_KEY_B64), 64)]
        pem = "-----BEGIN PUBLIC KEY-----\n" + "\n".join(pem_lines) + "\n-----END PUBLIC KEY-----"
        key = serialization.load_pem_public_key(pem.encode(), backend=default_backend())
        enc = base64.b64encode(key.encrypt(password.encode(), rsa_padding.PKCS1v15())).decode()
        async with httpx.AsyncClient(verify=False, timeout=15.0) as c:
            r = await c.post(f"{BASE_URL}/xdap-admin/user/login", headers={"Content-Type": "application/json"},
                json={"account": account, "password": enc, "type": "account", "tenantId": TENANT_ID, "loginType": "MANAGE"})
            d = r.json()
            if d.get("code") == "ok":
                self.token = d["data"]["token"]
            else:
                raise Exception(d.get("message", "登录失败"))

    async def _post(self, path, payload, app_id=None):
        async with httpx.AsyncClient(verify=False, timeout=60.0) as c:
            r = await c.post(f"{BASE_URL}/xdap-app{path}", headers=self._headers(app_id), json=payload)
            r.raise_for_status()
            d = r.json()
            if d.get("code") in ("ok", 200): return d.get("data") or {}
            raise Exception(d.get("message", "API失败"))

    async def create_app(self, name, code, desc=""):
        async with httpx.AsyncClient(verify=False, timeout=15.0) as c:
            r = await c.post(f"{BASE_URL}/xdap-app/apaasApplications/addApp",
                json={"appName": name, "appCode": code, "appDesc": desc, "appType": "CUSTOM"},
                headers=self._headers())
            d = r.json()
            if d.get("code") == "ok": return d.get("data", {})
            raise Exception(f"创建应用失败: {d.get('message')}")

    async def query_app_list(self):
        async with httpx.AsyncClient(verify=False, timeout=15.0) as c:
            r = await c.get(f"{BASE_URL}/xdap-app/apaasApplications/queryAppList",
                headers=self._headers(), params={"page": 1, "pageSize": 200})
            d = r.json()
            return d.get("table", []) if d.get("code") == "ok" else []

    async def create_dicts(self, app_id, payload):
        return await self._post("/common/resource/appDict", payload, app_id)

    async def create_models(self, app_id, payload):
        return await self._post("/common/resource/v2/appModel", payload, app_id)

    async def create_form_config(self, app_id, payload):
        return await self._post("/common/resource/formConfig", payload, app_id)

with open(os.path.join(os.path.dirname(__file__), "afterservice_config.json"), encoding="utf-8") as f:
    CONFIG = json.load(f)

from gen_afterservice import DICTS

SUFFIX = ''.join(random.choices(string.ascii_lowercase, k=4))


def add_suffix(config, suffix):
    cfg = copy.deepcopy(config)
    code_map = {}
    for m in cfg["dataModels"]:
        old = m["modelCode"]
        new = f"{old}_{suffix}"
        code_map[old] = new
        m["modelCode"] = new
    for fc in cfg["formConfigs"]:
        fc["formCode"] = f"{fc['formCode']}_{suffix}"
        fc["allModelCodes"] = [code_map.get(c, c) for c in fc["allModelCodes"]]
        def upd(comps):
            for c in comps:
                mf = c.get("modelField", "")
                if "." in mf:
                    mc, field = mf.split(".", 1)
                    if mc in code_map:
                        c["modelField"] = f"{code_map[mc]}.{field}"
                ds = c.get("dataSelectorConfig")
                if ds and ds.get("otherModelCode") in code_map:
                    ds["otherModelCode"] = code_map[ds["otherModelCode"]]
                if c.get("tableColumn"):
                    upd(c["tableColumn"])
        upd(fc["formComponents"])
        for key in ("queryConditions", "queryList"):
            items = fc.get("listPageView", {}).get(key, [])
            for i, mf in enumerate(items):
                if "." in mf:
                    mc, field = mf.split(".", 1)
                    if mc in code_map:
                        items[i] = f"{code_map[mc]}.{field}"
    return cfg, code_map


def collect_all_dict_codes(form_configs):
    codes = set()
    def scan(comps):
        for c in comps:
            dsc = c.get("dictionarySelectConfig")
            if dsc:
                codes.add(dsc["dictionaryCode"])
            if c.get("tableColumn"):
                scan(c["tableColumn"])
    for fc in form_configs:
        scan(fc["formComponents"])
    return codes


def build_dict_payload(app_id, dict_codes):
    result = []
    for code in sorted(dict_codes):
        options = DICTS.get(code, [])
        result.append({
            "appId": app_id,
            "dictionaryCode": code,
            "dictionaryName": code,
            "dictionaryOptions": [
                {"optionName": o["label"], "optionCode": o["id"],
                 "displayOrder": i + 1, "remarks": ""}
                for i, o in enumerate(options)
            ]
        })
    return result


async def main():
    client = SimpleClient()

    # 1. Login
    print(">>> 登录...")
    await client.login("17621440039", "definesys2019")
    print(f"    Token: {client.token[:40]}...")

    # 2. Create app
    app_code = f"afterservice{SUFFIX}"
    app_name = f"全球售后系统_{SUFFIX}"
    print(f">>> 创建应用: {app_name} (code: {app_code})")
    try:
        app_data = await client.create_app(app_name, app_code, "全球售后系统完整部署测试")
        app_id = str(app_data) if isinstance(app_data, str) else str(app_data.get("id", app_data.get("appId", "")))
    except Exception as e:
        if "已存在" in str(e) or "重复" in str(e):
            apps = await client.query_app_list()
            app_id = next((str(a["id"]) for a in apps if a.get("appCode") == app_code), None)
            if not app_id:
                raise
            print(f"    应用已存在，复用")
        else:
            raise
    print(f"    App ID: {app_id}  Suffix: {SUFFIX}")

    # 3. Apply suffix
    cfg, code_map = add_suffix(CONFIG, SUFFIX)
    print(f"    模型编码映射: {len(code_map)} 个")

    # 4. Collect and create dictionaries
    dict_codes = collect_all_dict_codes(cfg["formConfigs"])
    print(f"\n>>> 创建数据字典: {len(dict_codes)} 个")
    dict_payload = build_dict_payload(app_id, dict_codes)
    try:
        await client.create_dicts(app_id, dict_payload)
        print(f"    已创建 {len(dict_payload)} 个字典")
    except Exception as e:
        print(f"    字典创建警告: {e}")

    # 5. Create ALL models (batch)
    all_models = cfg["dataModels"]
    print(f"\n>>> 创建数据模型: {len(all_models)} 个")
    for m in all_models:
        print(f"    - {m['modelCode']} ({m['modelName']}) {len(m['fields'])} 字段")
    model_payload = {
        "appId": app_id,
        "datasourceId": "",
        "dataModels": [{**m, "appId": app_id} for m in all_models]
    }
    try:
        model_results = await client.create_models(app_id, model_payload)
        print(f"    模型创建结果: {json.dumps(model_results, ensure_ascii=False)[:200]}")
    except Exception as e:
        print(f"    模型创建错误: {e}")
        # Try one by one
        print("    尝试逐个创建...")
        for m in all_models:
            single_payload = {
                "appId": app_id,
                "datasourceId": "",
                "dataModels": [{**m, "appId": app_id}]
            }
            try:
                await client.create_models(app_id, single_payload)
                print(f"      ✓ {m['modelCode']}")
            except Exception as e2:
                print(f"      ✗ {m['modelCode']}: {e2}")

    # 6. Create ALL form configs (batch)
    all_forms = cfg["formConfigs"]
    print(f"\n>>> 创建表单配置: {len(all_forms)} 个")
    for fc in all_forms:
        print(f"    - {fc['formCode']} ({fc['formName']}) {len(fc['formComponents'])} 组件")

    # Create forms in batches of 5 to avoid timeout
    batch_size = 5
    for i in range(0, len(all_forms), batch_size):
        batch = all_forms[i:i+batch_size]
        batch_names = [f['formName'] for f in batch]
        print(f"\n    批次 {i//batch_size + 1}: {batch_names}")
        try:
            results = await client.create_form_config(app_id, batch)
            print(f"      结果: {json.dumps(results, ensure_ascii=False)[:300]}")
        except Exception as e:
            print(f"      批次错误: {e}")
            # Try one by one
            for fc in batch:
                try:
                    await client.create_form_config(app_id, [fc])
                    print(f"        ✓ {fc['formName']}")
                except Exception as e2:
                    print(f"        ✗ {fc['formName']}: {e2}")

    # Summary
    print(f"\n{'='*60}")
    print(f">>> 部署完成!")
    print(f"    应用: {app_name} (ID: {app_id})")
    print(f"    字典: {len(dict_codes)} 个")
    print(f"    模型: {len(all_models)} 个")
    print(f"    表单: {len(all_forms)} 个")
    print(f"    后缀: {SUFFIX}")
    print(f"    平台地址: https://apaas-poc.definesys.cn/platform/{TENANT_ID}/admin/app-store/list")


if __name__ == "__main__":
    asyncio.run(main())
