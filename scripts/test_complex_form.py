#!/usr/bin/env python3
"""Test: login to POC, create app with dicts + models + form (service_record)"""
import asyncio, json, sys, os, random, string
# Disable proxy for direct connection to aPaaS
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.apaas_client import APaaSClient

BASE_URL = "https://apaas-poc.definesys.cn/backend"
TENANT_ID = "743906758237356033"

with open(os.path.join(os.path.dirname(__file__), "afterservice_config.json"), encoding="utf-8") as f:
    CONFIG = json.load(f)

# gen_afterservice.py 里的 DICTS
from gen_afterservice import DICTS

NEEDED_MODELS = ["service_order", "engineer", "part_info", "service_record_parts", "service_record"]
SUFFIX = ''.join(random.choices(string.ascii_lowercase, k=4))

def add_suffix_to_config(config, suffix):
    """Add suffix to all model codes and update references in form components"""
    import copy
    cfg = copy.deepcopy(config)
    # Build old→new model code mapping
    code_map = {}
    for m in cfg["dataModels"]:
        old = m["modelCode"]
        new = f"{old}_{suffix}"
        code_map[old] = new
        m["modelCode"] = new
    # Update form configs
    for fc in cfg["formConfigs"]:
        fc["formCode"] = f"{fc['formCode']}_{suffix}"
        fc["allModelCodes"] = [code_map.get(c, c) for c in fc["allModelCodes"]]
        def update_components(comps):
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
                    update_components(c["tableColumn"])
        update_components(fc["formComponents"])
        for key in ("queryConditions", "queryList"):
            items = fc.get("listPageView", {}).get(key, [])
            for i, mf in enumerate(items):
                if "." in mf:
                    mc, field = mf.split(".", 1)
                    if mc in code_map:
                        items[i] = f"{code_map[mc]}.{field}"
    return cfg

def collect_dict_codes(form_config):
    """Collect all dictionary codes referenced by a form config"""
    codes = set()
    def scan(components):
        for c in components:
            dsc = c.get("dictionarySelectConfig")
            if dsc:
                codes.add(dsc["dictionaryCode"])
            if c.get("tableColumn"):
                scan(c["tableColumn"])
    scan(form_config["formComponents"])
    return codes

def build_dict_payload(app_id, dict_codes):
    """Build appDict API payload for the given dictionary codes"""
    result = []
    for code in dict_codes:
        options = DICTS.get(code, [])
        dict_options = []
        for i, opt in enumerate(options):
            dict_options.append({
                "optionName": opt["label"],
                "optionCode": opt["id"],
                "displayOrder": i + 1,
                "remarks": ""
            })
        result.append({
            "appId": app_id,
            "dictionaryCode": code,
            "dictionaryName": code,
            "dictionaryOptions": dict_options
        })
    return result

async def main():
    client = APaaSClient(base_url=BASE_URL, tenant_id=TENANT_ID)

    # 1. Login
    print(">>> Logging in...")
    await client.login("17621440039", "definesys2019")
    print(f"    Token: {client.token[:40]}...")

    # 2. Create test app (new code to avoid conflict)
    print(">>> Creating test app...")
    try:
        app_data = await client.create_app("售后测试v2", "afterservicetest02", "含字典的完整测试")
        app_id = str(app_data) if isinstance(app_data, str) else str(app_data.get("id", app_data.get("appId", "")))
    except Exception as e:
        if "已存在" in str(e) or "重复" in str(e):
            apps = await client.query_app_list()
            app_id = next((str(a["id"]) for a in apps if a.get("appCode") == "afterservicetest02"), None)
            if not app_id:
                raise
        else:
            raise
    print(f"    App ID: {app_id}  (suffix: {SUFFIX})")

    # Apply suffix to avoid model code conflicts
    suffixed = add_suffix_to_config(CONFIG, SUFFIX)

    # 3. Find the form config
    form_config = next(fc for fc in suffixed["formConfigs"] if fc["formCode"] == f"service_record_form_{SUFFIX}")

    # 4. Create dictionaries first
    dict_codes = collect_dict_codes(form_config)
    print(f">>> Creating dictionaries: {dict_codes}")
    dict_payload = build_dict_payload(app_id, dict_codes)
    try:
        await client.create_dicts(app_id, dict_payload)
        print(f"    Created {len(dict_payload)} dictionaries")
    except Exception as e:
        print(f"    Dict creation warning: {e}")

    # 5. Create data models
    print(">>> Creating data models...")
    needed_suffixed = [f"{m}_{SUFFIX}" for m in NEEDED_MODELS]
    models_to_create = [m for m in suffixed["dataModels"] if m["modelCode"] in needed_suffixed]
    model_payload = {
        "appId": app_id,
        "datasourceId": "",
        "dataModels": [{**m, "appId": app_id} for m in models_to_create]
    }
    print(f"    Models: {[m['modelCode'] for m in models_to_create]}")
    model_results = await client.create_models(app_id, model_payload)
    print(f"    Model results: {json.dumps(model_results, ensure_ascii=False)[:200]}")

    # 6. Create form config
    print(">>> Creating form config...")
    print(f"    Form: {form_config['formName']} ({len(form_config['formComponents'])} components)")
    form_results = await client.create_form_config(app_id, [form_config])
    print(f"    Form results: {json.dumps(form_results, ensure_ascii=False)[:300]}")

    print(f"\n>>> DONE! App: 售后测试v2 (ID: {app_id})")
    print(f"    https://apaas-poc.definesys.cn/platform/{TENANT_ID}/admin/app-store/list")

if __name__ == "__main__":
    asyncio.run(main())
