import asyncio
import sys
sys.path.insert(0, '.')

from app.apaas_client import APaaSClient

async def main():
    client = APaaSClient()
    await client.login("17621440039", "definesys2019")
    
    APP_ID = "821693297817812992"
    
    print("🔍 查询所有模型...")
    models = await client.query_models(APP_ID)
    
    print(f"✅ 找到 {len(models)} 个模型\n")
    
    # 找出字段数为0的模型
    empty_models = []
    for m in models:
        mc = m.get('modelCode', '')
        mn = m.get('modelName', '')
        fields = m.get('fields', [])
        field_count = len(fields)
        
        if field_count == 0:
            empty_models.append((mn, mc))
            print(f"❌ {mn} ({mc}): 0 个字段")
        elif mc.endswith('_6eiv'):
            print(f"✅ {mn} ({mc}): {field_count} 个字段")
    
    if empty_models:
        print(f"\n⚠️ 发现 {len(empty_models)} 个空模型")
        print("这些模型需要重新创建或添加字段")

if __name__ == "__main__":
    asyncio.run(main())
