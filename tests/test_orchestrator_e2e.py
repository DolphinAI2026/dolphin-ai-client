#!/usr/bin/env python3
"""编排器端到端测试：用 run_full_build 一键部署，验证 SSE 事件流完整性。

用法:
    python tests/test_orchestrator_e2e.py

验证 run_full_build 的完整事件流：
  stage 0 (解析) → stage -1 (创建应用) → stage 1 (公共资源) → stage 2 (业务表单) → stage 3 (Dashboard) → complete
"""
import asyncio
import os
import sys

for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(k, None)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.skills import login, run_full_build
from app.skills.platform import _rand
from app.apaas_client import APaaSClient

BASE_URL = "https://apaas-poc.definesys.cn/backend"
TENANT_ID = "743906758237356033"
ACCOUNT = "17621440039"
PASSWORD = "definesys2019"

# 简化配置：2 个表单 + 1 个字典 + 1 个角色
CONFIG = {
    "data": {
        "roles": [{"name": "测试员", "code": "tester"}],
        "dicts": [{"name": "状态", "code": "orch_status", "options": [
            {"name": "进行中", "code": "ongoing"},
            {"name": "已完成", "code": "done"},
        ]}],
        "models": [
            {"name": "任务表", "code": "orch_task", "fields": [
                {"name": "任务名", "type": "单行输入", "code": "task_name"},
                {"name": "状态", "type": "下拉单选", "code": "task_status", "dict": "orch_status"},
                {"name": "截止日期", "type": "日期时间", "code": "deadline"},
            ]},
            {"name": "日志表", "code": "orch_log", "fields": [
                {"name": "内容", "type": "多行输入", "code": "content"},
                {"name": "时间", "type": "日期时间", "code": "log_time"},
            ]},
        ],
    }
}


async def main():
    suffix = _rand(4)
    print(f"=== Orchestrator E2E 测试 (suffix={suffix}) ===\n")

    client = APaaSClient(base_url=BASE_URL, tenant_id=TENANT_ID)
    await login(client, ACCOUNT, PASSWORD)
    print(f"登录成功\n")

    app_name = f"orch-e2e-{suffix}"
    events = []
    stages_seen = set()
    errors = []

    async for event in run_full_build(client, CONFIG, app_name=app_name):
        events.append(event)
        stage = event.get("stage")
        status = event.get("status")
        step = event.get("step", event.get("message", ""))

        if stage is not None:
            stages_seen.add(stage)

        icon = {"running": "⏳", "done": "✅", "error": "❌"}.get(status, "📌")
        print(f"  {icon} stage={stage} status={status} | {step}")

        if status == "error":
            errors.append(step)

    # 验证事件流
    print(f"\n{'='*60}")
    print(f"事件总数: {len(events)}")
    print(f"经过的 stages: {sorted(stages_seen)}")

    # 检查关键 stages
    expected_stages = {0, -1, 1, 2, 3}
    missing_stages = expected_stages - stages_seen
    if missing_stages:
        print(f"WARNING: 缺少 stages: {missing_stages}")

    # 检查是否有 complete 事件
    complete = [e for e in events if e.get("type") == "complete"]
    if complete:
        print(f"app_id: {complete[0].get('app_id')}")
        print(f"\nOrchestrator E2E 测试通过!")
    else:
        print(f"\nWARNING: 未收到 complete 事件")

    if errors:
        print(f"\n错误列表:")
        for e in errors:
            print(f"  - {e}")


if __name__ == "__main__":
    asyncio.run(main())
