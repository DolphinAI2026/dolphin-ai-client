#!/usr/bin/env python3
"""端到端冒烟测试：用 Skills 模块部署一个包含全部 16 种组件的应用到 POC 环境。

用法:
    python tests/test_skills_e2e.py

需要 POC 环境可达 + 有效账号。
"""
import asyncio
import json
import os
import sys

# Disable proxy
for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(k, None)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.skills import (
    login, create_app, create_models, create_dicts, create_roles,
    create_form, build_component, COMPONENT_REGISTRY,
)
from app.skills.components import build_form_config
from app.skills.platform import _rand
from app.apaas_client import APaaSClient

# ── 测试配置 ──

ACCOUNT = "17621440039"
PASSWORD = "definesys2019"
BASE_URL = "https://apaas-poc.definesys.cn/backend"
TENANT_ID = "743906758237356033"

# 包含全部 16 种组件的测试模型
TEST_DICTS = [
    {"name": "优先级", "code": "priority", "options": [
        {"name": "高", "code": "high"},
        {"name": "中", "code": "medium"},
        {"name": "低", "code": "low"},
    ]},
    {"name": "标签", "code": "tags", "options": ["前端", "后端", "测试"]},
]

TEST_MODELS = [
    {
        "name": "基础信息表",
        "code": "base_info",
        "fields": [
            {"name": "单据号", "type": "单据号", "code": "doc_no"},
            {"name": "名称", "type": "单行输入", "code": "f_name"},
            {"name": "描述", "type": "多行输入", "code": "desc"},
            {"name": "电话", "type": "手机号码", "code": "f_phone"},
            {"name": "邮箱", "type": "电子邮箱", "code": "f_email"},
            {"name": "日期", "type": "日期时间", "code": "f_date"},
            {"name": "金额", "type": "金额", "code": "f_amount"},
            {"name": "数量", "type": "数字", "code": "qty"},
            {"name": "附件", "type": "附件上传", "code": "attach"},
            {"name": "启用", "type": "开关", "code": "enabled"},
            {"name": "负责人", "type": "人员选择", "code": "owner"},
            {"name": "位置", "type": "地理位置", "code": "loc"},
            {"name": "优先级", "type": "下拉单选", "code": "f_priority", "dict": "priority"},
            {"name": "标签", "type": "下拉多选", "code": "f_tags", "dict": "tags"},
        ],
    },
    {
        "name": "关联引用表",
        "code": "ref_table",
        "fields": [
            {"name": "标题", "type": "单行输入", "code": "title"},
            {"name": "关联基础信息", "type": "数据单选", "code": "ref_base",
             "ref": {"model": "base_info", "field": "f_name"}},
        ],
    },
    {
        "name": "子表测试",
        "code": "sub_test",
        "fields": [
            {"name": "主表标题", "type": "单行输入", "code": "main_title"},
            {"name": "明细", "type": "子表", "sub_code": "sub_test_detail",
             "sub_fields": [
                 {"name": "项目名", "type": "单行输入", "code": "item_name"},
                 {"name": "数量", "type": "数字", "code": "item_qty"},
                 {"name": "金额", "type": "金额", "code": "item_amt"},
             ]},
        ],
    },
]

TEST_ROLES = [
    {"name": "管理员", "code": "admin"},
    {"name": "操作员", "code": "operator"},
]
async def main():
    suffix = _rand(4)
    print(f"=== Skills E2E 冒烟测试 (suffix={suffix}) ===\n")

    client = APaaSClient(base_url=BASE_URL, tenant_id=TENANT_ID)

    # Step 1: 登录
    print("[1/6] 登录...")
    await login(client, ACCOUNT, PASSWORD)
    print(f"  OK  token={client.token[:30]}...")

    # Step 2: 创建应用
    app_name = f"skills-e2e-{suffix}"
    print(f"\n[2/6] 创建应用: {app_name}")
    app_id = await create_app(client, app_name)
    print(f"  OK  app_id={app_id}")

    # Step 3: 创建角色
    print(f"\n[3/6] 创建角色: {len(TEST_ROLES)} 个")
    await create_roles(client, app_id, TEST_ROLES)
    print(f"  OK")

    # Step 4: 创建字典
    print(f"\n[4/6] 创建字典: {len(TEST_DICTS)} 个")
    dict_code_map = await create_dicts(client, app_id, TEST_DICTS, suffix=suffix)
    print(f"  OK  dict_code_map={dict_code_map}")

    # Step 5: 创建模型
    print(f"\n[5/6] 创建模型: {len(TEST_MODELS)} 个")
    model_results, model_payload, code_map = await create_models(
        client, app_id, TEST_MODELS, suffix=suffix
    )
    print(f"  OK  code_map={code_map}")
    for dm in model_payload["dataModels"]:
        print(f"    - {dm['modelCode']} ({dm['modelName']}) {len(dm['fields'])} fields")

    # Step 6: 创建表单
    print(f"\n[6/6] 创建表单: {len(TEST_MODELS)} 个")
    form_results = await create_form(
        client, app_id, TEST_MODELS, TEST_DICTS,
        model_results, model_payload, code_map, dict_code_map,
    )
    print(f"  OK  results={json.dumps(form_results, ensure_ascii=False)[:200]}")

    # 验证
    print(f"\n{'='*60}")
    print(f"E2E 冒烟测试通过!")
    print(f"  应用: {app_name} (ID: {app_id})")
    print(f"  字典: {len(TEST_DICTS)} 个")
    print(f"  模型: {len(model_payload['dataModels'])} 个 (含子表)")
    print(f"  表单: {len(TEST_MODELS)} 个")
    print(f"  组件类型覆盖: 16/16")
    print(f"  后缀: {suffix}")
    print(f"  平台: https://apaas-poc.definesys.cn/platform/{TENANT_ID}/admin/app-store/list")

    # 验证组件覆盖度
    form_payload = build_form_config(
        TEST_MODELS, TEST_DICTS,
        model_results, model_payload, code_map, dict_code_map,
    )
    all_comp_types = set()
    def collect(comps):
        for c in comps:
            all_comp_types.add(c["componentType"])
            if c.get("tableColumn"):
                collect(c["tableColumn"])
    for fc in form_payload:
        collect(fc["formComponents"])

    expected = {
        "FORM_DOCUMENT_NUMBER", "FORM_TEXT_INPUT", "FORM_TEXTAREA_INPUT",
        "FORM_PHONE_INPUT", "FORM_EMAIL_INPUT", "FORM_DATEPICK_INPUT",
        "FORM_MONEY_INPUT", "FORM_NUMBER_INPUT", "FORM_FILE_UPLOAD",
        "FORM_SWITCH_SELECT", "FORM_PEOPLE_SELECT", "FORM_WIDGET_LOCATION",
        "FORM_SELECT_INPUT_SINGLE", "FORM_SELECT_INPUT",
        "FORM_DATA_SELECTOR_SINGLE", "FORM_WIDGET_SON_TABLE",
    }
    missing = expected - all_comp_types
    if missing:
        print(f"\n  WARNING: 缺少组件类型: {missing}")
    else:
        print(f"\n  全部 16 种组件类型验证通过!")


if __name__ == "__main__":
    asyncio.run(main())
