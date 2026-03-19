import asyncio
import sys
import json
sys.path.insert(0, '.')

async def main():
    # 读取配置文件
    with open("form_config_before.json", 'r', encoding='utf-8') as f:
        fc_before = json.load(f)
    
    with open("form_config_after.json", 'r', encoding='utf-8') as f:
        fc_after = json.load(f)
    
    comps_before = fc_before.get('detailPage', {}).get('formComponents', [])
    comps_after = fc_after.get('detailPage', {}).get('formComponents', [])
    
    # 找子表组件
    subtable_before = None
    subtable_after = None
    
    for comp in comps_before:
        if comp.get('componentType') == 'FORM_WIDGET_SON_TABLE':
            subtable_before = comp
            break
    
    for comp in comps_after:
        if comp.get('componentType') == 'FORM_WIDGET_SON_TABLE':
            subtable_after = comp
            break
    
    if subtable_before and subtable_after:
        print("📋 子表组件变化:\n")
        
        keys_before = set(subtable_before.keys())
        keys_after = set(subtable_after.keys())
        
        new_keys = keys_after - keys_before
        removed_keys = keys_before - keys_after
        
        print(f"  之前: {len(keys_before)} 个属性")
        print(f"  之后: {len(keys_after)} 个属性")
        
        if new_keys:
            print(f"\n  ➕ 新增属性:")
            for k in sorted(new_keys):
                print(f"     - {k}")
        
        if removed_keys:
            print(f"\n  ➖ 移除属性:")
            for k in sorted(removed_keys):
                print(f"     - {k}")
        
        # 检查子表列的变化
        cols_before = subtable_before.get('tableColumn', [])
        cols_after = subtable_after.get('tableColumn', [])
        
        print(f"\n  子表列数: {len(cols_before)} → {len(cols_after)}")
        
        if cols_before and cols_after:
            col_before = cols_before[0]
            col_after = cols_after[0]
            
            col_keys_before = set(col_before.keys())
            col_keys_after = set(col_after.keys())
            
            col_new = col_keys_after - col_keys_before
            col_removed = col_keys_before - col_keys_after
            
            print(f"\n  子表列属性:")
            print(f"    之前: {len(col_keys_before)} 个")
            print(f"    之后: {len(col_keys_after)} 个")
            
            if col_new:
                print(f"\n    ➕ 新增:")
                for k in sorted(col_new):
                    print(f"       - {k}: {col_after[k]}")
            
            if col_removed:
                print(f"\n    ➖ 移除:")
                for k in sorted(col_removed):
                    print(f"       - {k}")

if __name__ == "__main__":
    asyncio.run(main())
