import asyncio
import sys
sys.path.insert(0, '.')

from app.apaas_client import APaaSClient

async def main():
    client = APaaSClient()
    await client.login("17621440039", "definesys2019")
    
    APP_ID = "821693297817812992"
    
    # 查询脚本创建的其他表单
    menus = await client.query_menus(APP_ID)
    
    form_menus = []
    def collect(items):
        for item in items:
            if item.get('menuType') == 'MODEL' and item.get('formId'):
                form_menus.append(item)
            collect(item.get('submenus', []) or item.get('children', []) or [])
    collect(menus)
    
    # 找一个简单的表单
    for fm in form_menus:
        if fm['menuName'] == '行业':
            print(f"🔍 检查表单: {fm['menuName']}")
            fc = await client.query_form_config(APP_ID, fm['formId'])
            comps = fc.get('detailPage', {}).get('formComponents', [])
            
            if comps:
                comp = comps[0]
                print(f"\n组件: {comp.get('label')}")
                print(f"有 labelI18n: {'labelI18n' in comp}")
                print(f"有 placeholderI18n: {'placeholderI18n' in comp}")
                
                if 'labelI18n' in comp:
                    print(f"\nlabelI18n 结构:")
                    print(f"  {comp['labelI18n']}")
            break

if __name__ == "__main__":
    asyncio.run(main())
