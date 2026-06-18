"""接缝守卫: 桌面运行时信号只允许在 app/runtime.py 内裸读。

backend/app 其它文件碰桌面差异一律走 app.runtime 门面(is_desktop/is_frozen/
desktop_data_dir/desktop_frontend_dir/is_federation)。防止 DESKTOP_MODE /
sys.frozen / _MEIPASS 再次散落进共享核心。
"""
import re
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[1] / "app"

# 匹配真实代码用法, 不误伤 docstring/注释里的散文(那些不含 os.environ.get(/getattr(sys 等)。
_PATTERNS = [
    re.compile(r'os\.environ\.get\(\s*["\']DESKTOP_MODE'),
    re.compile(r'os\.environ\[\s*["\']DESKTOP_MODE'),
    re.compile(r'getattr\(\s*_?sys\s*,\s*["\']frozen'),
    re.compile(r'\b_?sys\.frozen\b'),
    re.compile(r'\b_?sys\._MEIPASS\b'),
]


def test_no_bare_desktop_signals_outside_runtime():
    offenders = []
    for f in _APP_DIR.rglob("*.py"):
        if f.name == "runtime.py":
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if any(p.search(line) for p in _PATTERNS):
                offenders.append(f"{f.relative_to(_APP_DIR)}:{i}: {stripped}")
    assert not offenders, (
        "桌面运行时信号必须走 app.runtime 门面, 不要在以下位置裸读:\n"
        + "\n".join(offenders)
    )
