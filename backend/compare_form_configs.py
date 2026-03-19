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
    
    print("🔍 查询保存后的表单配置...")
    fc_after = await client.query_form_config(APP_ID, FORM_ID)
    
    # 保存到文件
    output_file = "form_config_after.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(fc_after, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 新配置已保存到: {output_file}\n")
    
    # 读取之前的配置
    with open("form_config_before.json", 'r', encoding='utf-8') as f:
        fc_before = json.load(f)
    
    print("📊 基本信息对比:")
    print(f"  表单名称: {fc_before.get('formName')} → {fc_after.get('formName')}")
    print(f"  组件数量: {len(fc_before.get('detailPage', {}).get('formComponents', []))} → {len(fc_after.get('detailPage', {}).get('formComponents', []))}")
    
    # 对比第一个组件
    comps_before = fc_before.get('detailPage', {}).get('formComponents', [])
    comps_after = fc_after.get('detailPage', {}).get('formComponents', [])
    
    if comps_before and comps_after:
        comp_before = comps_before[0]
        comp_after = comps_after[0]
        
        keys_before = set(comp_before.keys())
        keys_after = set(comp_after.keys())
        
        new_keys = keys_after - keys_before
        removed_keys = keys_before - keys_after
        
        print(f"\n📋 第一个组件属性变化:")
        print(f"  之前: {len(keys_before)} 个属性")
        print(f"  之后: {len(keys_after)} 个属性")
        
        if new_keys:
            print(f"\n  ➕ 新增属性 ({len(new_keys)} 个):")
            for k in sorted(new_keys):
                print(f"     - {k}: {comp_after[k]}")
        
        if removed_keys:
            print(f"\n  ➖ 移除属性 ({len(removed_keys)} 个):")
            for k in sorted(removed_keys):
                print(f"     - {k}")
        
        # 检查值变化的属性
        changed = []
        for k in keys_before & keys_after:
            if comp_before[k] != comp_after[k]:
                changed.append(k)
        
        if changed:
            print(f"\n  🔄 值变化的属性 ({len(changed)} 个):")
            for k in changed[:5]:
                print(f"     - {k}:")
                print(f"       before: {comp_before[k]}")
                print(f"       after:  {comp_after[k]}")
            if len(changed) > 5:
                print(f"     ... 还有 {len(changed) - 5} 个")

if __name__ == "__main__":
    asyncio.run(main())
