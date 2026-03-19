import asyncio
import sys
import random
import string
sys.path.insert(0, '.')

from app.apaas_client import APaaSClient

async def main():
    client = APaaSClient()
    await client.login("17621440039", "definesys2019")
    
    APP_ID = "821693297817812992"
    FORM_ID = "69b8bf478057aede4f89ab15"
    SUFFIX = "6eiv"
    
    # 1. 查询表单信息
    print("🔍 查询表单信息...")
    fc = await client.query_form_config(APP_ID, FORM_ID)
    form_name = fc.get('formName', '')
    print(f"   表单名称: {form_name}")
    
    # 2. 删除表单（通过删除菜单）
    print(f"\n🗑️ 删除表单...")
    menus = await client.query_menus(APP_ID)
    menu_id = None
    def find_menu(items):
        nonlocal menu_id
        for item in items:
            if item.get('formId') == FORM_ID:
                menu_id = item.get('id')
                return
            find_menu(item.get('submenus', []) or item.get('children', []) or [])
    find_menu(menus)
    
    if menu_id:
        # 删除菜单的API
        import httpx
        async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
            response = await http.post(
                f"{client.base_url}/xdap-app/menu/delete/menu",
                headers=client._get_headers(APP_ID),
                json={"id": menu_id}
            )
            if response.json().get('code') == 'ok':
                print(f"   ✅ 删除成功")
            else:
                print(f"   ❌ 删除失败: {response.json()}")
    else:
        print(f"   ⚠️ 未找到菜单")
    
    # 3. 重新创建表单
    print(f"\n📝 重新创建表单...")
    
    # 查询模型字段
    models = await client.query_models(APP_ID)
    model_by_code = {m.get('modelCode'): m for m in models}
    
    main_model_code = f"elab_quotation_approval_{SUFFIX}"
    sub_model_code = f"table_elab_quotation_{SUFFIX}"
    
    main_model = model_by_code.get(main_model_code)
    sub_model = model_by_code.get(sub_model_code)
    
    if not main_model:
        print(f"   ❌ 主模型不存在: {main_model_code}")
        return
    if not sub_model:
        print(f"   ❌ 子表模型不存在: {sub_model_code}")
        return
    
    # 构建表单组件
    components = []
    query_conditions = []
    query_list = []
    listable = 0
    
    # 主模型字段
    for f in main_model.get('fields', []):
        fn = f.get('fieldName', '')
        fc = f.get('fieldCode', '')
        if not fn or not fc:
            continue
        
        comp = {
            "componentType": "FORM_TEXT_INPUT",
            "label": fn,
            "modelField": f"{main_model_code}.{fc}",
        }
        components.append(comp)
        
        if listable < 6:
            mf = f"{main_model_code}.{fc}"
            if listable < 4:
                query_conditions.append(mf)
            query_list.append(mf)
            listable += 1
    
    # 子表
    sub_cols = []
    for f in sub_model.get('fields', []):
        fn = f.get('fieldName', '')
        fc = f.get('fieldCode', '')
        if not fn or not fc:
            continue
        
        sub_cols.append({
            "componentType": "FORM_TEXT_INPUT",
            "label": fn,
            "modelField": f"{sub_model_code}.{fc}",
        })
    
    if sub_cols:
        components.append({
            "componentType": "FORM_WIDGET_SON_TABLE",
            "label": "配额批准书明细",
            "tableColumn": sub_cols,
        })
    
    # 创建表单
    form_payload = [{
        "formName": form_name,
        "formCode": f"form_{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}",
        "allModelCodes": [main_model_code],
        "formComponents": components,
        "listPageView": {
            "queryConditions": query_conditions,
            "queryList": query_list,
        }
    }]
    
    try:
        result = await client.create_form_config(APP_ID, form_payload)
        print(f"   ✅ 创建成功")
        if isinstance(result, list) and result:
            new_form_id = result[0].get('id', '')
            print(f"   新 formId: {new_form_id}")
    except Exception as e:
        print(f"   ❌ 创建失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
