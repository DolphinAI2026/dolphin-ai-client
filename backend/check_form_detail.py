import asyncio
import sys
import json
sys.path.insert(0, '.')

from app.apaas_client import APaaSClient

async def main():
    client = APaaSClient()
    await client.login("17621440039", "definesys2019")
    
    APP_ID = "821693297817812992"
    FORM_ID = "69b8c73b8057aede4f89abb4"
    
    print("🔍 查询表单完整配置...\n")
    fc = await client.query_form_config(APP_ID, FORM_ID)
    
    print(f"📝 表单名称: {fc.get('formName')}")
    print(f"📋 表单编码: {fc.get('formCode')}")
    print(f"🗄️ allModelCodes: {fc.get('allModelCodes')}\n")
    
    # 检查组件
    components = fc.get('detailPage', {}).get('formComponents', [])
    print(f"📦 组件列表 ({len(components)} 个):")
    
    for i, comp in enumerate(components, 1):
        ct = comp.get('componentType', '')
        label = comp.get('label', '')
        
        if ct == 'FORM_WIDGET_SON_TABLE':
            sub_cols = comp.get('tableColumn', [])
            print(f"  {i}. [子表] {label} ({len(sub_cols)} 列)")
            for j, col in enumerate(sub_cols[:3], 1):
                print(f"      {j}. {col.get('label')} → {col.get('modelField')}")
            if len(sub_cols) > 3:
                print(f"      ... 还有 {len(sub_cols) - 3} 列")
        else:
            mf = comp.get('modelField', '')
            print(f"  {i}. [{ct}] {label} → {mf}")
    
    # 检查列表页配置
    list_page = fc.get('listPageView', {})
    print(f"\n📊 列表页配置:")
    print(f"  查询条件: {list_page.get('queryConditions', [])[:3]}")
    print(f"  列表字段: {list_page.get('queryList', [])[:3]}")

if __name__ == "__main__":
    asyncio.run(main())
