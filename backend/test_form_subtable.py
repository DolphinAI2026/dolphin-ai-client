import asyncio
import sys
import json
sys.path.insert(0, '.')

from app.apaas_client import APaaSClient

async def main():
    client = APaaSClient()
    await client.login("17621440039", "definesys2019")
    
    APP_ID = "821693297817812992"
    FORM_ID = "69b8bf478057aede4f89ab15"
    
    print(f"🔍 查询表单详情: {FORM_ID}")
    form_config = await client.query_form_config(APP_ID, FORM_ID)
    
    # 基本信息
    form_name = form_config.get('formName', '')
    all_codes = form_config.get('allModelCodes', [])
    print(f"📝 表单名称: {form_name}")
    print(f"🗄️ allModelCodes: {all_codes}")
    
    # 检查表单结构
    components = form_config.get('detailPage', {}).get('formComponents', [])
    print(f"✅ 表单有 {len(components)} 个组件\n")
    
    # 检查所有组件
    print("📋 组件列表:")
    for i, comp in enumerate(components):
        ct = comp.get('componentType', '')
        label = comp.get('label', '')
        mf = comp.get('modelField', '')
        
        if ct == 'FORM_WIDGET_SON_TABLE':
            print(f"  {i+1}. [子表] {label}")
            sub_cols = comp.get('tableColumn', [])
            print(f"     子表有 {len(sub_cols)} 列:")
            for j, col in enumerate(sub_cols[:5]):
                col_label = col.get('label', '')
                col_mf = col.get('modelField', '')
                col_type = col.get('componentType', '')
                print(f"       {j+1}. [{col_type}] {col_label} → {col_mf}")
            if len(sub_cols) > 5:
                print(f"       ... 还有 {len(sub_cols) - 5} 列")
        else:
            print(f"  {i+1}. [{ct}] {label} → {mf}")
    
    # 测试保存
    print(f"\n💾 测试保存表单...")
    try:
        await client.save_form_config(APP_ID, form_config)
        print("✅ 表单保存成功")
    except Exception as e:
        print(f"❌ 表单保存失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
