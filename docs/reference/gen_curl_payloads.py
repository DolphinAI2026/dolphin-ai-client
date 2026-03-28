#!/usr/bin/env python3
"""Generate curl commands for creating the complex form on POC platform"""
import json, sys, os, random, string

sys.path.insert(0, os.path.dirname(__file__))
from gen_afterservice import DICTS

with open(os.path.join(os.path.dirname(__file__), "afterservice_config.json"), encoding="utf-8") as f:
    CONFIG = json.load(f)

SUFFIX = ''.join(random.choices(string.ascii_lowercase, k=4))
BASE = "https://apaas-poc.definesys.cn/backend/xdap-app"
TENANT_ID = "743906758237356033"
NEEDED = ["service_order", "engineer", "part_info", "service_record_parts", "service_record"]

def suffixed(config, sfx):
    import copy
    cfg = copy.deepcopy(config)
    code_map = {}
    for m in cfg["dataModels"]:
        old = m["modelCode"]
        new = f"{old}_{sfx}"
        code_map[old] = new
        m["modelCode"] = new
    for fc in cfg["formConfigs"]:
        fc["formCode"] = f"{fc['formCode']}_{sfx}"
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

cfg, code_map = suffixed(CONFIG, SUFFIX)
form_config = next(fc for fc in cfg["formConfigs"] if fc["formCode"] == f"service_record_form_{SUFFIX}")

# Collect needed dicts
dict_codes = set()
def scan(comps):
    for c in comps:
        dsc = c.get("dictionarySelectConfig")
        if dsc: dict_codes.add(dsc["dictionaryCode"])
        if c.get("tableColumn"): scan(c["tableColumn"])
scan(form_config["formComponents"])

# Output JSON payloads to temp files
outdir = os.path.join(os.path.dirname(__file__), "tmp_payloads")
os.makedirs(outdir, exist_ok=True)

# Dict payload
dict_payload = []
for code in sorted(dict_codes):
    opts = DICTS.get(code, [])
    dict_payload.append({
        "appId": "__APP_ID__",
        "dictionaryCode": code,
        "dictionaryName": code,
        "dictionaryOptions": [{"optionName": o["label"], "optionCode": o["id"], "displayOrder": i+1, "remarks": ""} for i, o in enumerate(opts)]
    })
with open(f"{outdir}/dict.json", "w") as f:
    json.dump(dict_payload, f, ensure_ascii=False)

# Model payload
needed_codes = [f"{m}_{SUFFIX}" for m in NEEDED]
models = [m for m in cfg["dataModels"] if m["modelCode"] in needed_codes]
model_payload = {"appId": "__APP_ID__", "datasourceId": "", "dataModels": [{**m, "appId": "__APP_ID__"} for m in models]}
with open(f"{outdir}/model.json", "w") as f:
    json.dump(model_payload, f, ensure_ascii=False)

# Form payload
with open(f"{outdir}/form.json", "w") as f:
    json.dump([form_config], f, ensure_ascii=False)

print(f"Suffix: {SUFFIX}")
print(f"Dict codes: {sorted(dict_codes)}")
print(f"Models: {[m['modelCode'] for m in models]}")
print(f"Form: {form_config['formCode']} ({len(form_config['formComponents'])} components)")
print(f"\nPayloads written to {outdir}/")
print(f"  dict.json, model.json, form.json")
print(f"\nReplace __APP_ID__ with actual app ID before sending.")
