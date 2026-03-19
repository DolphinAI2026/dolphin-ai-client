import asyncio
import sys
sys.path.insert(0, '.')

from app.apaas_client import APaaSClient

async def main():
    client = APaaSClient()
    await client.login("17621440039", "definesys2019")
    
    APP_ID = "821693297817812992"
    
    # 1. 查询菜单列表
    print("📋 查询菜单列表...")
    menus = await client.query_menus(APP_ID)
    
    # 找到一个表单
    form_menus = []
    def collect(items):
        for item in items:
            if item.get('menuType') == 'MODEL' and item.get('formId'):
                form_menus.append(item)
            collect(item.get('submenus', []) or item.get('children', []) or [])
    collect(menus)
    
    if not form_menus:
        print("❌ 没有找到表单")
        return
    
    print(f"✅ 找到 {len(form_menus)} 个表单")
    for fm in form_menus[:5]:
        print(f"  - {fm['menuName']} (formId: {fm['formId']})")
    
    # 2. 查询第一个表单的详情
    test_form = form_menus[0]
    print(f"\n🔍 查询表单详情: {test_form['menuName']}")
    form_config = await client.query_form_config(APP_ID, test_form['formId'])
    
    # 检查表单结构
    components = form_config.get('detailPage', {}).get('formComponents', [])
    print(f"✅ 表单有 {len(components)} 个组件")
    
    # 检查 modelField 格式
    print("\n📝 检查组件 modelField:")
    for i, comp in enumerate(components[:5]):
        ct = comp.get('componentType', '')
        label = comp.get('label', '')
        mf = comp.get('modelField', '')
        print(f"  {i+1}. [{ct}] {label} → {mf}")
    
    # 检查 allModelCodes
    all_codes = form_config.get('allModelCodes', [])
    print(f"\n🗄️ allModelCodes: {all_codes}")
    
    # 3. 尝试保存（不做修改，只是验证能否保存）
    print(f"\n💾 测试保存表单...")
    try:
        await client.save_form_config(APP_ID, form_config)
        print("✅ 表单保存成功")
    except Exception as e:
        print(f"❌ 表单保存失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
