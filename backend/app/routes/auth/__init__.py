"""auth 包 — 认证与租户管理路由。

外部 import 兼容层（纯搬移，零行为变化）：
  from app.routes.auth import get_auth_context, AuthContext  # harness.py
  from app.routes.auth import login                          # mcp_platform.py
  main.py: auth.router

测试文件也直接 import 内部函数和类，全部在此 re-export。
"""
import sys as _sys
from fastapi import APIRouter

# ── re-exports: app.deps ──────────────────────────────────────────────────────
from app.deps import get_auth_context, AuthContext  # noqa: F401

# ── 子模块加载（import 时触发子模块进 sys.modules）────────────────────────────
# 注意：import A.B.C as X 会把子模块同时写入 parent.__dict__[C] = submod。
# 加载完后再把关键名称覆盖成函数，确保 from auth import login 拿到函数，
# 而 import app.routes.auth.login（走 sys.modules）仍能拿到子模块。
import app.routes.auth.login  # noqa: E402
import app.routes.auth.settings  # noqa: E402
import app.routes.auth.tenants_admin  # noqa: E402
import app.routes.auth.tenant_members  # noqa: E402
import app.routes.auth.web_console_session  # noqa: E402

_login_module = _sys.modules["app.routes.auth.login"]
_settings_module = _sys.modules["app.routes.auth.settings"]
_tenants_admin_module = _sys.modules["app.routes.auth.tenants_admin"]
_tenant_members_module = _sys.modules["app.routes.auth.tenant_members"]
_web_console_session_module = _sys.modules["app.routes.auth.web_console_session"]

# ── re-exports: login 模块 ────────────────────────────────────────────────────
# 端点函数
from app.routes.auth.login import (  # noqa: F401
    select_tenant,
    exchange_apaas_token,
    switch_tenant,
    switch_control_plane_code_tenant,
)
# 内部 helpers（测试用）
from app.routes.auth.login import (  # noqa: F401
    _is_allowed_apaas_base_url,
    _ensure_apaas_tenant,
    _try_apaas_login_flow,
    _apaas_membership_role_preference,
    _sync_user_membership,
    _tenant_item_name,
)
# Pydantic 模型（测试用）
from app.routes.auth.login import (  # noqa: F401
    ExchangeApaasTokenRequest,
    ExchangeApaasTokenResponse,
    TenantSwitchRequest,
    ControlPlaneCodeTenantSwitchRequest,
)

# ── re-exports: tenants_admin 模块 ────────────────────────────────────────────
from app.routes.auth.tenants_admin import (  # noqa: F401
    list_all_tenants,
    create_new_tenant,
    tenant_dashboard,
    update_tenant,
    delete_tenant,
    get_tenant_usage_endpoint,
    update_tenant_status,
    set_my_default_tenant,
    bind_user_apaas_account,
    admin_reset_user_password,
    list_platform_users,
    list_my_tenants,
    list_users,
    list_tenant_roles,
    list_tenant_users,
    invite_tenant_user,
    update_tenant_user_status,
    update_tenant_user_role,
    get_me,
)
from app.routes.auth.tenants_admin import (  # noqa: F401
    UpdateTenantUserStatusRequest,
    UpdateTenantUserRoleRequest,
    InviteTenantUserRequest,
    TenantCreateRequest,
    TenantStatusRequest,
    TenantUpdateRequest,
    TenantAdminItem,
    BindApaasAccountRequest,
    ResetPasswordRequest,
)

# ── re-exports: tenant_members 模块 ───────────────────────────────────────────
from app.routes.auth.tenant_members import (  # noqa: F401
    list_tenant_members,
    list_roles_for_tenant,
    add_tenant_member,
    update_tenant_member_role,
    remove_tenant_member,
)
from app.routes.auth.tenant_members import (  # noqa: F401
    TenantMemberAddRequest,
    TenantMemberItem,
    TenantMemberRoleUpdateRequest,
)

# ── 主 router ─────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/auth", tags=["认证"])

# 挂载顺序重要：保证最终路由表与拆分前完全一致。
router.include_router(_login_module.router)
router.include_router(_web_console_session_module.router)
router.include_router(_settings_module.public_router)
router.include_router(_tenants_admin_module.router)
router.include_router(_tenant_members_module.router)

# ── 覆盖 login 属性为函数 ─────────────────────────────────────────────────────
# import app.routes.auth.login（不带 as）会把子模块写入 auth.__dict__['login']。
# 这里把它覆盖成 login 函数，使 `from app.routes.auth import login` 拿到函数。
# `import app.routes.auth.login as m`（走 sys.modules）不受影响，仍能拿到子模块。
login = _login_module.login  # noqa: F811
