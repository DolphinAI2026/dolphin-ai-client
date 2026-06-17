import io
import zipfile
import pytest

from app.routes import skills as sk


def _zip_bytes(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def test_validate_and_extract_good_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    data = _zip_bytes({"SKILL.md": "---\nname: s1\ndescription: d\n---\n步骤", "helper.py": "print(1)"})
    name = sk._extract_user_skill_zip(data)
    assert name == "s1"
    assert (tmp_path / "skills" / "user" / "s1" / "SKILL.md").is_file()


def test_reject_zip_without_skill_md(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    with pytest.raises(ValueError):
        sk._extract_user_skill_zip(_zip_bytes({"readme.txt": "x"}))


def test_reject_zip_slip(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    with pytest.raises(ValueError):
        sk._extract_user_skill_zip(_zip_bytes({"../evil.py": "x", "SKILL.md": "---\nname: e\ndescription: d\n---\n"}))


def test_delete_user_only(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    (tmp_path / "skills" / "platform" / "p1").mkdir(parents=True)
    (tmp_path / "skills" / "platform" / "p1" / "SKILL.md").write_text("---\nname: p1\ndescription: d\n---\n", encoding="utf-8")
    with pytest.raises(ValueError):
        sk._delete_user_skill("p1")  # platform 只读


def test_skips_macosx_resource_fork(tmp_path, monkeypatch):
    """Finder 打包的 __MACOSX/._SKILL.md 不能被误选去 parse，垃圾也不落盘。"""
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    data = _zip_bytes({
        "myskill/__MACOSX_placeholder": "",  # 占位，确保顺序不影响
        "__MACOSX/myskill/._SKILL.md": "\x00\x05\x16\x07garbage applefork",
        "myskill/SKILL.md": "---\nname: real\ndescription: d\n---\n步骤",
        "myskill/helper.py": "print(1)",
        "myskill/.DS_Store": "junk",
        "__MACOSX/myskill/._helper.py": "junk",
    })
    name = sk._extract_user_skill_zip(data)
    assert name == "real"
    sdir = tmp_path / "skills" / "user" / "real"
    assert (sdir / "SKILL.md").is_file()
    assert (sdir / "helper.py").is_file()
    assert not (sdir / ".DS_Store").exists()
    assert not (sdir / "._helper.py").exists()
    assert not (tmp_path / "skills" / "user" / "__MACOSX").exists()


def test_bad_zip_raises_value_error(tmp_path, monkeypatch):
    """非 zip 字节 → ValueError（路由层据此回 400 而非 500）。"""
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    with pytest.raises(ValueError):
        sk._extract_user_skill_zip(b"this is not a zip file at all")


def test_zip_slip_leaves_nothing_on_disk(tmp_path, monkeypatch):
    """zip-slip 被拒后不留半个 skill（原子落盘）。"""
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    # SKILL.md 合法在前，恶意路径在后：旧实现会先写 SKILL.md 再抛。
    data = _zip_bytes({
        "SKILL.md": "---\nname: e\ndescription: d\n---\n",
        "good.py": "print(1)",
        "../evil.py": "x",
    })
    with pytest.raises(ValueError):
        sk._extract_user_skill_zip(data)
    assert not (tmp_path / "skills" / "user" / "e").exists()
    assert not (tmp_path / "skills" / "user" / ".e.tmp").exists()


def test_reject_nested_subdirectories(tmp_path, monkeypatch):
    """嵌套子目录被拒（scan/use_skill 非递归，避免静默失配）。"""
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    data = _zip_bytes({
        "SKILL.md": "---\nname: n\ndescription: d\n---\n",
        "sub/helper.py": "print(1)",
    })
    with pytest.raises(ValueError):
        sk._extract_user_skill_zip(data)
    assert not (tmp_path / "skills" / "user" / "n").exists()


def test_user_cannot_shadow_platform_skill(tmp_path, monkeypatch):
    """同名平台预置技能不可被用户上传覆盖（信任边界）。"""
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    (tmp_path / "skills" / "platform" / "p1").mkdir(parents=True)
    (tmp_path / "skills" / "platform" / "p1" / "SKILL.md").write_text(
        "---\nname: p1\ndescription: d\n---\n", encoding="utf-8"
    )
    data = _zip_bytes({"SKILL.md": "---\nname: p1\ndescription: evil\n---\nbad"})
    with pytest.raises(ValueError):
        sk._extract_user_skill_zip(data)
    # 平台版未被动过。
    assert (tmp_path / "skills" / "platform" / "p1" / "SKILL.md").read_text(
        encoding="utf-8"
    ).find("evil") == -1


def test_reupload_clears_stale_files(tmp_path, monkeypatch):
    """重传新版会清掉旧版残留文件，不让孤儿文件泄进 workspace。"""
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    v1 = _zip_bytes({
        "SKILL.md": "---\nname: s\ndescription: d\n---\n",
        "old_helper.py": "print(1)",
    })
    sk._extract_user_skill_zip(v1)
    sdir = tmp_path / "skills" / "user" / "s"
    assert (sdir / "old_helper.py").is_file()
    v2 = _zip_bytes({
        "SKILL.md": "---\nname: s\ndescription: d2\n---\n",
        "new_helper.py": "print(2)",
    })
    sk._extract_user_skill_zip(v2)
    assert (sdir / "new_helper.py").is_file()
    assert not (sdir / "old_helper.py").exists()


# ── 路由层（TestClient）：能抓到 BadZipFile→500 这类回归 ──

def _client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.deps import get_auth_context

    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    app = FastAPI()
    app.include_router(sk.router)
    app.dependency_overrides[get_auth_context] = lambda: object()
    return TestClient(app)


def test_route_corrupt_zip_returns_400(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/skills", files={"file": ("bad.zip", b"not a zip", "application/zip")})
    assert resp.status_code == 400


def test_route_valid_zip_returns_name(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    data = _zip_bytes({"SKILL.md": "---\nname: r1\ndescription: d\n---\n", "helper.py": "print(1)"})
    resp = client.post("/skills", files={"file": ("s.zip", data, "application/zip")})
    assert resp.status_code == 200
    assert resp.json()["name"] == "r1"


def test_route_delete_platform_returns_400(tmp_path, monkeypatch):
    (tmp_path / "skills" / "platform" / "p1").mkdir(parents=True)
    (tmp_path / "skills" / "platform" / "p1" / "SKILL.md").write_text(
        "---\nname: p1\ndescription: d\n---\n", encoding="utf-8"
    )
    client = _client(tmp_path, monkeypatch)
    resp = client.delete("/skills/p1")
    assert resp.status_code == 400
