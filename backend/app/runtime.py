"""统一运行时门面 — desktop vs web 的唯一判定/路径中心。

⚠️ is_frozen() 与 is_desktop() 语义不对称, 不可互换:
  - is_frozen() = "已打成单文件二进制, 无可用 venv 解释器"(PyInstaller 冻结态)。
    run_python 必须用它: 只有冻结态才走 sidecar --run-script(execute_run_python
    仅在 frozen 时写 tmp 文件)。dev 桌面态(DESKTOP_MODE=1 但非 frozen)有真 venv,
    必须走 `python -c`, 误用 is_desktop() 会带空 tmp_path 走 --run-script 而崩。
  - is_desktop() = "桌面拓扑"(含 dev 裸跑), = DESKTOP_MODE==1 或 frozen。
    用于信任边界(非桌面=共享后端跑 assert)、前端 SPA 托管、skill 根定位。

env 真相源 = desktop_sidecar.build_env(壳)写, 本模块(核心)读。新增任何桌面差异
判断一律加到这里; 禁止在 backend/app 其它文件裸读 DESKTOP_MODE / sys.frozen /
_MEIPASS(有 grep-CI 守卫拦截)。

DATABASE_URL 契约(不在本模块逻辑内, 仅记录): 桌面 = 本地 sqlite(build_env 写
DATABASE_URL=sqlite+aiosqlite:///<data_dir>/app.db), web = MySQL。config.
_normalize_database_url 适配 sqlite 路径。存储后端 desktop≠web, 勿假设统一。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ── env-key 名字常量(与 desktop_sidecar.build_env 共用, 锁死壳↔核心契约) ──
ENV_DESKTOP_MODE = "DESKTOP_MODE"
ENV_SIDECAR_DATA_DIR = "SIDECAR_DATA_DIR"
ENV_WORKSPACE_ROOT = "APAAS_WORKSPACE_ROOT"
ENV_SERVER_DATA_DIR = "RUIJING_SERVER_DATA_DIR"
ENV_FRONTEND_DIR = "DESKTOP_FRONTEND_DIR"

_HOME_DATA_DIR_NAME = ".ruijing-builder"


def is_frozen() -> bool:
    """PyInstaller 冻结态(无可用 venv 解释器)。见模块 docstring 的不对称警告。"""
    return bool(getattr(sys, "frozen", False))


def is_desktop() -> bool:
    """桌面拓扑(含 dev 裸跑): DESKTOP_MODE==1 或已冻结。"""
    return os.environ.get(ENV_DESKTOP_MODE) == "1" or is_frozen()


def desktop_data_dir() -> Path:
    """桌面 data_dir: SIDECAR_DATA_DIR > APAAS_WORKSPACE_ROOT.parent > ~/.ruijing-builder。

    真相源 = build_env 经 --data-dir 注入。绝不猜测; 从 build_env 无条件导出的
    APAAS_WORKSPACE_ROOT 反推 .parent, 与 sidecar 实际使用目录严格一致。
    """
    data_dir = os.environ.get(ENV_SIDECAR_DATA_DIR)
    if data_dir:
        return Path(data_dir)
    ws = os.environ.get(ENV_WORKSPACE_ROOT)
    if ws:
        return Path(ws).parent
    return Path.home() / _HOME_DATA_DIR_NAME


def server_data_dir() -> Path | None:
    """Web 服务端数据根(RUIJING_SERVER_DATA_DIR), 未设返 None。"""
    v = os.environ.get(ENV_SERVER_DATA_DIR)
    return Path(v) if v else None


def desktop_frontend_dir() -> Path:
    """桌面前端 SPA 目录: DESKTOP_FRONTEND_DIR > _MEIPASS/frontend_dist > repo frontend/dist-desktop。"""
    explicit = os.environ.get(ENV_FRONTEND_DIR)
    if explicit:
        return Path(explicit)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "frontend_dist"
    return Path(__file__).resolve().parents[2] / "frontend" / "dist-desktop"


def is_federation() -> bool:
    """桌面登录是否走 federation(转发公网账号服务)vs 本地 authority。

    真相源 = settings.public_account_base_url(build_env 注入公网 URL; 空=本地 authority)。
    """
    from app.config import settings
    return bool(settings.public_account_base_url)
