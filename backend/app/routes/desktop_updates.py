"""桌面端自动更新托管(account-service 专用)。

- GET /desktop-updates/latest.json  → Tauri updater 拉的 manifest(不鉴权)
- GET /desktop-updates/{filename}   → 下发签名包 .app.tar.gz(不鉴权, 文件名白名单)
- POST /desktop-updates/admin/publish → 平台管理员发版上传

文件落 settings.desktop_updates_dir(account-service 挂 PVC /data)。
GET 不鉴权:更新产物是公开物,靠 minisign 签名防篡改。
"""
import datetime
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
_SAFE_NAME = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*\."
    r"(app\.tar\.gz|app\.tar\.gz\.sig|exe|exe\.sig|exe\.zip|exe\.zip\.sig|"
    r"msi|msi\.sig|msi\.zip|msi\.zip\.sig|json)$"
)


def _updates_dir() -> Path:
    return Path(settings.desktop_updates_dir)


_MAC_PKG_RE = re.compile(r"^ruijing-(.+)-(aarch64|x86_64)\.app\.tar\.gz$")
_WIN_PKG_RE = re.compile(r"^ruijing-(.+)-windows-(x86_64|aarch64)(?:-setup)?\.(exe|msi)(?:\.zip)?$")


def _parse_package_name(name: str) -> tuple[str, str] | None:
    """Return (version, package_key) for packages shown in release history."""
    m = _MAC_PKG_RE.match(name)
    if m:
        return m.group(1), m.group(2)
    m = _WIN_PKG_RE.match(name)
    if m:
        return m.group(1), f"windows_{m.group(2)}"
    return None


def _ver_key(v: str) -> list:
    """语义化版本排序键: '0.2.10' > '0.2.9'。"""
    out = []
    for p in str(v).split("."):
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return out


def _iso_from_mtime(mtime: float) -> str:
    if not mtime:
        return ""
    return datetime.datetime.fromtimestamp(mtime, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_history(d: Path, parsed: dict) -> None:
    """发版时把本版的 version/notes/pub_date 记入 history.json(按版本留存说明)。"""
    hf = d / "history.json"
    hist = {}
    if hf.is_file():
        try:
            hist = json.loads(hf.read_text(encoding="utf-8"))
        except ValueError:
            hist = {}
    hist[str(parsed["version"])] = {
        "notes": parsed.get("notes", ""),
        "pub_date": parsed.get("pub_date", ""),
    }
    tmp = d / "history.json.part"
    tmp.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
    tmp.replace(hf)


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

    _record_history(d, parsed)  # 记发版历史
    return {"ok": True, "manifest_version": parsed["version"], "packages": written}


@router.get("/admin/history")
async def list_history(ctx: Annotated[AuthContext, Depends(get_auth_context)]):
    """平台管理员查看发版历史。合并 history.json(留存的说明)+ 磁盘上的包文件
    (补全过去未记说明的版本), 按版本号降序。仅 is_platform_admin。"""
    if not ctx.user.is_platform_admin:
        raise HTTPException(status_code=403, detail="仅平台管理员可查看")
    d = _updates_dir()

    hist = {}
    hf = d / "history.json"
    if hf.is_file():
        try:
            hist = json.loads(hf.read_text(encoding="utf-8"))
        except ValueError:
            hist = {}

    # 从包文件聚合每个版本有哪些架构 + 最新 mtime(给没记 history 的旧版本兜底日期)
    from_files: dict[str, dict] = {}
    if d.is_dir():
        for f in d.glob("ruijing-*"):
            parsed = _parse_package_name(f.name)
            if not parsed:
                continue
            ver, arch = parsed
            e = from_files.setdefault(ver, {"archs": set(), "mtime": 0.0})
            e["archs"].add(arch)
            try:
                e["mtime"] = max(e["mtime"], f.stat().st_mtime)
            except OSError:
                pass

    latest_ver = None
    lf = d / "latest.json"
    if lf.is_file():
        try:
            latest_ver = str(json.loads(lf.read_text(encoding="utf-8")).get("version") or "") or None
        except ValueError:
            latest_ver = None

    out = []
    for ver in set(from_files) | set(hist):
        h = hist.get(ver, {})
        archs = from_files.get(ver, {}).get("archs", set())
        out.append({
            "version": ver,
            "notes": h.get("notes", ""),
            "published_at": h.get("pub_date") or _iso_from_mtime(from_files.get(ver, {}).get("mtime", 0.0)),
            "is_latest": ver == latest_ver,
            "packages": {
                "aarch64": f"ruijing-{ver}-aarch64.app.tar.gz" if "aarch64" in archs else None,
                "x86_64": f"ruijing-{ver}-x86_64.app.tar.gz" if "x86_64" in archs else None,
                "windows_x86_64": f"ruijing-{ver}-windows-x86_64-setup.exe" if "windows_x86_64" in archs else None,
                "windows_aarch64": f"ruijing-{ver}-windows-aarch64-setup.exe" if "windows_aarch64" in archs else None,
            },
        })
    out.sort(key=lambda x: _ver_key(x["version"]), reverse=True)
    return out
