"""错误消息常量

集中后端抛出的标准错误文案，避免散落在各处。

⚠️ 兼容性约束（改动前必读）
    前端靠字符串片段匹配判断 Token 过期态：
    - frontend/src/utils/request.ts:45 匹配 "Token已过期或无效"
    - frontend/src/views/ChatPage.vue 多处匹配 "Token已过期或无效" / "重新连接APaaS平台"
    后端多处也靠字符串匹配做重试决策：
    - backend/app/routes/applications.py:1547 匹配 "Token已过期或无效"
    - backend/app/routes/applications.py:1763 / generation_steps.py:1001 匹配 "Token已过期"

    本文件的常量值刻意保持与历史文案完全一致，以免破坏现有匹配逻辑。
    未来若要调整文案（例如加空格或 i18n），必须同步更新所有匹配点，
    推荐的迁移路径是改用 HTTP 状态码 + 专用 header，让文案不再参与判断。
"""

from __future__ import annotations


# ── APaaS 平台 Token 相关 ─────────────────────────────────────────
# 初次或普通场景下的过期提示
APAAS_TOKEN_EXPIRED = "Token已过期或无效，请重新连接APaaS平台"

# 有保存凭证但自动刷新失败时的提示
APAAS_TOKEN_REFRESH_FAILED = "Token已过期且自动刷新失败，请在项目设置中重新连接平台"

# 自动刷新尚未尝试（未保存密码等），引导用户去项目设置手动处理
APAAS_TOKEN_EXPIRED_PROJECT = "Token已过期，请在项目设置中重新连接平台"

# 分步执行链路在步骤执行期间检测到 Token 失效
APAAS_TOKEN_EXPIRED_STEP = "APaaS平台Token已过期，请在环境管理中重新登录"

# 生成 / 上线链路统一的 Token 过期提示
APAAS_TOKEN_EXPIRED_GENERIC = "APaaS平台Token已过期，请重新连接平台后再试"

# 自动刷新失败、当前场景倾向指向"上线/发布"链路
APAAS_LOGIN_FAILED = "平台登录失效，请重新连接APaaS平台"


# ── 前端与后端共享的匹配片段 ────────────────────────────────────
# 这些子串出现在 detail/error_msg 中即视为"平台 Token 失效"。
# 放在这里是让匹配点有一个显式入口，便于将来一次性迁移。
APAAS_TOKEN_MARKERS = (
    "Token已过期或无效",
    "Token已过期",
    "重新连接APaaS平台",
)


def is_apaas_token_error(message: str | None) -> bool:
    """判断一条错误消息是否属于 APaaS 平台 Token 失效。

    用法：
        if is_apaas_token_error(detail):
            # 走重试 / 提示重登链路
            ...
    """
    if not message:
        return False
    return any(marker in message for marker in APAAS_TOKEN_MARKERS)


# ── 系统内部选择 Token（与 APaaS 平台 Token 无关）─────────────
# 用户登录后选择租户时签发的 intermediate JWT。
SELECT_TOKEN_INVALID = "无效的选择 Token"
SELECT_TOKEN_EXPIRED = "选择 Token 已过期或无效"
