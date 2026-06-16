"""桌面端自动更新托管(account-service 专用)。

- GET /desktop-updates/latest.json  → Tauri updater 拉的 manifest(不鉴权)
- GET /desktop-updates/{filename}   → 下发签名包 .app.tar.gz(不鉴权, 文件名白名单)
- POST /desktop-updates/admin/publish → 平台管理员发版上传

文件落 settings.desktop_updates_dir(account-service 挂 PVC /data)。
GET 不鉴权:更新产物是公开物,靠 minisign 签名防篡改。
"""
import json
import os
import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.config import settings
from app.deps import AuthContext, get_auth_context

router = APIRouter(prefix="/desktop-updates", tags=["desktop-updates"])

# 只允许下载更新包 / sig / manifest。挡掉路径穿越与任意文件读取。
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.(app\.tar\.gz|app\.tar\.gz\.sig|json)$")


def _updates_dir() -> Path:
    return Path(settings.desktop_updates_dir)


@router.get("/latest.json")
async def latest_json():
    f = _updates_dir() / "latest.json"
    if not f.is_file():
        raise HTTPException(status_code=404, detail="no update manifest")
    return JSONResponse(content=json.loads(f.read_text(encoding="utf-8")))


@router.get("/{filename}")
async def get_package(filename: str):
    if not _SAFE_NAME.match(filename):
        raise HTTPException(status_code=400, detail="bad filename")
    f = _updates_dir() / filename
    # 二次防穿越: 解析后必须仍在更新目录内
    try:
        f.resolve().relative_to(_updates_dir().resolve())
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail="bad path")
    if not f.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(str(f))


@router.post("/admin/publish")
async def publish_update(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    manifest: Annotated[str, Form()],
    packages: Annotated[list[UploadFile] | None, File()] = None,
):
    """平台管理员发版: 写 manifest + 包到更新目录。仅 is_platform_admin。"""
    if not ctx.user.is_platform_admin:
        raise HTTPException(status_code=403, detail="仅平台管理员可发版")
    try:
        parsed = json.loads(manifest)
    except ValueError:
        raise HTTPException(status_code=400, detail="manifest 不是合法 JSON")
    if not isinstance(parsed, dict) or "version" not in parsed or "platforms" not in parsed:
        raise HTTPException(status_code=400, detail="manifest 缺 version/platforms")

    d = _updates_dir()
    d.mkdir(parents=True, exist_ok=True)
    written = []
    for up in (packages or []):
        name = os.path.basename(up.filename or "")
        if not _SAFE_NAME.match(name) or name == "latest.json":
            raise HTTPException(status_code=400, detail=f"包名非法: {name}")
        data = await up.read()
        tmp = d / (name + ".part")
        tmp.write_bytes(data)
        tmp.replace(d / name)  # 原子 rename
        written.append(name)

    # manifest 最后写(原子), 保证拉到 manifest 时包已就位
    tmp = d / "latest.json.part"
    tmp.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
    tmp.replace(d / "latest.json")
    return {"ok": True, "manifest_version": parsed["version"], "packages": written}
