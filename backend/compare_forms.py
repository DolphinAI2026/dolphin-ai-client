import asyncio
import sys
import json
sys.path.insert(0, '.')

from app.apaas_client import APaaSClient

async def main():
    client = APaaSClient()
    await client.login("17621440039", "definesys2019")
    
    APP_ID = "821693297817812992"
    
    # 查询两个表单
    OLD_FORM_ID = "69b8bf478057aede4f89ab15"  # 脚本创建的旧表单
    NEW_FORM_ID = "69b8c73b8057aede4f89abb4"  # 我们重新创建的表单
    
    print("🔍 对比两个表单的组件配置...\n")
    
    old_fc = await client.query_form_config(APP_ID, OLD_FORM_ID)
    new_fc = await client.query_form_config(APP_ID, NEW_FORM_ID)
    
    old_comps = old_fc.get('detailPage', {}).get('formComponents', [])
    new_comps = new_fc.get('detailPage', {}).get('formComponents', [])
    
    print(f"旧表单组件数: {len(old_comps)}")
    print(f"新表单组件数: {len(new_comps)}\n")
    
    # 对比第一个组件的所有属性
    if old_comps and new_comps:
        print("📋 第一个组件的属性对比:")
        old_comp = old_comps[0]
        new_comp = new_comps[0]
        
        print(f"\n旧表单组件 keys: {sorted(old_comp.keys())}")
        print(f"\n新表单组件 keys: {sorted(new_comp.keys())}")
        
        # 找出缺少的属性
        old_keys = set(old_comp.keys())
        new_keys = set(new_comp.keys())
        
        missing = old_keys - new_keys
        extra = new_keys - old_keys
        
        if missing:
            print(f"\n❌ 新表单缺少的属性: {missing}")
            for k in missing:
                print(f"   {k}: {old_comp[k]}")
        
        if extra:
            print(f"\n➕ 新表单多出的属性: {extra}")

if __name__ == "__main__":
    asyncio.run(main())
