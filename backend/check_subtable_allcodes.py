import asyncio
import sys
sys.path.insert(0, '.')

from app.apaas_client import APaaSClient

async def main():
    client = APaaSClient()
    await client.login("17621440039", "definesys2019")
    
    APP_ID = "821693297817812992"
    
    # 查询所有表单，找带子表的
    print("🔍 查询所有表单的 allModelCodes...")
    menus = await client.query_menus(APP_ID)
    
    form_menus = []
    def collect(items):
        for item in items:
            if item.get('menuType') == 'MODEL' and item.get('formId'):
                form_menus.append(item)
            collect(item.get('submenus', []) or item.get('children', []) or [])
    collect(menus)
    
    for fm in form_menus:
        fc = await client.query_form_config(APP_ID, fm['formId'])
        all_codes = fc.get('allModelCodes', [])
        comps = fc.get('detailPage', {}).get('formComponents', [])
        
        # 检查是否有子表
        has_subtable = any(c.get('componentType') == 'FORM_WIDGET_SON_TABLE' for c in comps)
        
        if has_subtable:
            print(f"\n📋 {fm['menuName']}")
            print(f"   allModelCodes: {all_codes}")
            
            # 找出子表引用的模型
            for c in comps:
                if c.get('componentType') == 'FORM_WIDGET_SON_TABLE':
                    sub_cols = c.get('tableColumn', [])
                    if sub_cols:
                        first_mf = sub_cols[0].get('modelField', '')
                        if '.' in first_mf:
                            sub_model = first_mf.split('.')[0]
                            in_all = sub_model in all_codes
                            print(f"   子表 '{c.get('label')}' 使用模型: {sub_model} {'✅' if in_all else '❌ 不在 allModelCodes'}")

if __name__ == "__main__":
    asyncio.run(main())
