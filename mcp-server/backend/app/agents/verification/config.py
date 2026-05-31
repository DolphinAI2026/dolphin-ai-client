"""VerificationAgent 运行参数。"""
from __future__ import annotations

from app.config import settings

MAX_TURNS: int = settings.verification_max_turns
"""BaseAgent 主循环上限（架构文档 § 5.2）；通过 VERIFICATION_MAX_TURNS 环境变量覆盖"""

MAX_AUTO_FIX_ROUNDS: int = 2
"""AC 失败后自动触发 CodingAgent 重跑的最大次数（架构文档 § 12.1 第 9 条）"""

GREP_MAX_MATCHES: int = 40
"""单次 grep 返回的最大匹配数，防止 context 爆炸"""

READ_MAX_BYTES: int = 16_000
"""单文件读取字节上限"""

# AC 判定的 confidence 阈值
AC_CONFIDENCE_HIGH: float = 0.85
"""≥ 此值判定结果可信"""
AC_CONFIDENCE_LOW: float = 0.5
"""< 此值标注"需要人工审核"（overall_status 不会变 passed）"""
