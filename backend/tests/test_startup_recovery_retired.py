from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_retired_coding_sessions_recovery_is_not_wired_into_startup():
    main_source = (BACKEND_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    retired_module = BACKEND_ROOT / "app" / "startup_recovery.py"

    assert "sweep_dead_coding_sessions" not in main_source
    assert "app.startup_recovery" not in main_source
    assert not retired_module.exists()
