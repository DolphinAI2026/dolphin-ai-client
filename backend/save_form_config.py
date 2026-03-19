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
    
    print("🔍 查询表单完整配置...")
    fc = await client.query_form_config(APP_ID, FORM_ID)
    
    # 保存到文件
    output_file = "form_config_before.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(fc, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 配置已保存到: {output_file}")
    print(f"\n基本信息:")
    print(f"  表单名称: {fc.get('formName')}")
    print(f"  表单编码: {fc.get('formCode')}")
    print(f"  组件数量: {len(fc.get('detailPage', {}).get('formComponents', []))}")
    print(f"  allModelCodes: {fc.get('allModelCodes')}")

if __name__ == "__main__":
    asyncio.run(main())
