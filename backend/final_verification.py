import asyncio
import sys
sys.path.insert(0, '.')

from app.apaas_client import APaaSClient

async def main():
    client = APaaSClient()
    await client.login("17621440039", "definesys2019")
    
    APP_ID = "821693297817812992"
    
    print("🎯 最终验证\n")
    
    # 1. 检查所有模型
    print("📊 模型统计:")
    models = await client.query_models(APP_ID)
    total_fields = sum(len(m.get('fields', [])) for m in models)
    print(f"   ✅ {len(models)} 个模型，共 {total_fields} 个字段\n")
    
    # 2. 检查所有表单
    print("📋 表单统计:")
    menus = await client.query_menus(APP_ID)
    form_menus = []
    def collect(items):
        for item in items:
            if item.get('menuType') == 'MODEL' and item.get('formId'):
                form_menus.append(item)
            collect(item.get('submenus', []) or item.get('children', []) or [])
    collect(menus)
    
    print(f"   ✅ {len(form_menus)} 个表单")
    
    # 3. 验证每个表单
    print("\n🔍 验证表单配置:")
    all_valid = True
    for fm in form_menus:
        fc = await client.query_form_config(APP_ID, fm['formId'])
        comps = fc.get('detailPage', {}).get('formComponents', [])
        all_codes = fc.get('allModelCodes', [])
        
        # 检查 allModelCodes 中的模型是否存在
        model_by_code = {m.get('modelCode'): m for m in models}
        missing_models = [mc for mc in all_codes if mc not in model_by_code]
        
        if missing_models:
            print(f"   ❌ {fm['menuName']}: 缺少模型 {missing_models}")
            all_valid = False
        else:
            print(f"   ✅ {fm['menuName']}")
    
    if all_valid:
        print("\n🎉 所有表单配置正确！")
    else:
        print("\n⚠️ 部分表单有问题")

if __name__ == "__main__":
    asyncio.run(main())
