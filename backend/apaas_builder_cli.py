"""
aPaaS Builder CLI

命令行工具，用于从配置文件创建/更新 aPaaS 应用

使用方式:
    apaas-builder create config.yaml
    apaas-builder validate config.yaml
    apaas-builder generate "创建资产管理系统..."
"""

import asyncio
import sys
import json
import yaml
import click
from pathlib import Path
from typing import Optional

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 延迟导入，避免加载 config.py
from app.app_config_schema import AppConfig, EXAMPLE_YAML

import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@click.group()
def cli():
    """aPaaS Builder - 得帆云应用构建工具"""
    pass


@cli.command()
@click.argument('config_file', type=click.Path(exists=True))
@click.option('--account', '-a', required=True, help='aPaaS 账号')
@click.option('--password', '-p', required=True, help='aPaaS 密码')
@click.option('--base-url', default='https://apaas-poc.definesys.cn/backend', help='aPaaS Base URL')
@click.option('--tenant-id', default='743906758237356033', help='租户 ID')
@click.option('--output', '-o', type=click.Path(), help='保存进度文件路径')
def create(config_file: str, account: str, password: str, base_url: str, tenant_id: str, output: Optional[str]):
    """从配置文件创建 aPaaS 应用"""
    asyncio.run(_create_app(config_file, account, password, base_url, tenant_id, output))


async def _create_app(config_file: str, account: str, password: str, base_url: str, tenant_id: str, output: Optional[str]):
    """创建应用的异步实现"""
    try:
        # 延迟导入
        from app.apaas_client import APaaSClient
        from app.app_executor import AppExecutor

        # 1. 加载配置
        click.echo(f"📄 加载配置文件: {config_file}")
        config = _load_config(config_file)

        # 2. 验证配置
        click.echo("✓ 配置验证通过")

        # 3. 登录 aPaaS
        click.echo(f"🔐 登录 aPaaS 平台...")
        client = APaaSClient(base_url=base_url, tenant_id=tenant_id)
        await client.login(account, password)
        click.echo(f"✓ 登录成功")

        # 4. 执行创建
        click.echo(f"\n🚀 开始创建应用: {config.name}\n")
        executor = AppExecutor(client)
        progress = await executor.execute(config)

        # 5. 保存进度
        if output:
            output_path = Path(output)
        else:
            output_path = Path(f"/tmp/{config.name.replace(' ', '_')}_progress.json")

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)

        click.echo(f"\n✅ 应用创建成功!")
        click.echo(f"📊 进度文件: {output_path}")
        click.echo(f"🆔 App ID: {progress['app_id']}")
        click.echo(f"📝 App Code: {progress['app_code']}")

        # 6. 生成访问链接
        access_url = f"https://apaas-poc.definesys.cn/platform/{tenant_id}/admin/app-store/list"
        click.echo(f"🔗 访问地址: {access_url}")

    except Exception as e:
        click.echo(f"\n❌ 创建失败: {str(e)}", err=True)
        logger.exception("创建应用时发生错误")
        sys.exit(1)


@cli.command()
@click.argument('config_file', type=click.Path(exists=True))
def validate(config_file: str):
    """验证配置文件格式"""
    try:
        click.echo(f"📄 验证配置文件: {config_file}")
        config = _load_config(config_file)

        click.echo(f"\n✓ 配置验证通过\n")
        click.echo(f"应用名称: {config.name}")
        click.echo(f"数据字典: {len(config.dicts)} 个")
        click.echo(f"数据模型: {len(config.models)} 个")
        click.echo(f"表单配置: {len(config.forms)} 个")

        # 显示详细信息
        if config.dicts:
            click.echo(f"\n字典列表:")
            for d in config.dicts:
                click.echo(f"  - {d.name} ({d.code}): {len(d.options)} 个选项")

        if config.models:
            click.echo(f"\n模型列表:")
            for m in config.models:
                click.echo(f"  - {m.name} ({m.code}): {len(m.fields)} 个字段")

    except Exception as e:
        click.echo(f"\n❌ 验证失败: {str(e)}", err=True)
        sys.exit(1)


@cli.command()
def example():
    """显示配置文件示例"""
    click.echo("# aPaaS 应用配置示例\n")
    click.echo(EXAMPLE_YAML)


@cli.command()
@click.argument('output_file', type=click.Path())
def init(output_file: str):
    """生成配置文件模板"""
    output_path = Path(output_file)

    if output_path.exists():
        if not click.confirm(f"文件 {output_file} 已存在，是否覆盖?"):
            return

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(EXAMPLE_YAML)

    click.echo(f"✓ 配置模板已生成: {output_file}")


@cli.command()
@click.argument('requirement', type=str)
@click.option('--output', '-o', type=click.Path(), default='app_config.yaml', help='输出配置文件路径')
def generate(requirement: str, output: str):
    """从自然语言需求生成配置文件（需要 AI）"""
    click.echo("⚠️  此功能需要 AI 支持")
    click.echo(f"需求: {requirement}")
    click.echo(f"\n请使用 Claude Code CLI 或其他 AI 工具生成配置文件")
    click.echo(f"然后使用: apaas-builder create {output}")


def _load_config(config_file: str) -> AppConfig:
    """加载并验证配置文件"""
    path = Path(config_file)

    if path.suffix in ['.yaml', '.yml']:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    elif path.suffix == '.json':
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        raise ValueError(f"不支持的文件格式: {path.suffix}，请使用 .yaml 或 .json")

    # 使用 Pydantic 验证
    config = AppConfig(**data)
    return config


if __name__ == '__main__':
    cli()
