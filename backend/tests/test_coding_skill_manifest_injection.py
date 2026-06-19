from pathlib import Path

from app.coding import pipeline
from app.ai_chat.skills import Skill


def test_manifest_suffix_appends_available_skills(monkeypatch):
    monkeypatch.setattr(
        "app.ai_chat.skills.SkillRegistry.scan",
        lambda self: [Skill(name="demo", description="演示技能", dir=Path("/x"), source="user")],
    )
    suffix = pipeline._coding_skill_manifest_suffix()
    assert "可用技能" in suffix
    assert "demo" in suffix


def test_manifest_suffix_empty_when_no_skills(monkeypatch):
    monkeypatch.setattr("app.ai_chat.skills.SkillRegistry.scan", lambda self: [])
    assert pipeline._coding_skill_manifest_suffix() == ""


def test_manifest_suffix_swallows_errors(monkeypatch):
    def _boom(self):
        raise RuntimeError("scan failed")

    monkeypatch.setattr("app.ai_chat.skills.SkillRegistry.scan", _boom)
    assert pipeline._coding_skill_manifest_suffix() == ""
