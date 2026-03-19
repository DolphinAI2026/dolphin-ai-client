import json

with open("form_config_after.json", 'r', encoding='utf-8') as f:
    fc = json.load(f)

comps = fc.get('detailPage', {}).get('formComponents', [])

# 找子表
for comp in comps:
    if comp.get('componentType') == 'FORM_WIDGET_SON_TABLE':
        print("📋 子表新增属性的值:\n")
        
        new_attrs = [
            'basedFields', 'chooseType', 'layout', 'mobileDisplayStyle',
            'mobileDisplayfields', 'mobileSonTableColumnFixed', 
            'mobileSonTableFormSettings', 'modelName', 'sonQueryCondition',
            'sonTableDocNumComponents', 'sonTableTabSwitch', 'sonTableTabsList',
            'tableAddedPosition', 'tableOrderType', 'tableOrders',
            'webSonTableColumnFixed'
        ]
        
        for attr in new_attrs:
            if attr in comp:
                val = comp[attr]
                if isinstance(val, (list, dict)) and len(str(val)) > 100:
                    print(f"  {attr}: <复杂对象>")
                else:
                    print(f"  {attr}: {val}")
        
        break
