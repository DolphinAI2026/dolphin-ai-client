from app.ai_chat.agent import _append_skill_manifest


def test_append_when_skills_present(monkeypatch):
    from app.ai_chat import skills as skmod
    monkeypatch.setattr(skmod.SkillRegistry, "scan", lambda self: [skmod.Skill("a", "甲", __import__("pathlib").Path("/x"), "user", [])])
    messages = [{"role": "system", "content": "BASE"}]
    _append_skill_manifest(messages)
    assert "可用技能" in messages[0]["content"]
    assert messages[0]["content"].startswith("BASE")


def test_noop_when_empty(monkeypatch):
    from app.ai_chat import skills as skmod
    monkeypatch.setattr(skmod.SkillRegistry, "scan", lambda self: [])
    messages = [{"role": "system", "content": "BASE"}]
    _append_skill_manifest(messages)
    assert messages[0]["content"] == "BASE"
