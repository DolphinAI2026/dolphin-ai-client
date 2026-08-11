from __future__ import annotations

import pytest

from app.system_assistant.policy import validate_governance_policy


@pytest.mark.parametrize("policy", ["legacy", "shadow"])
def test_b0_policy_accepts_legacy_and_shadow(policy):
    assert validate_governance_policy(policy) == policy


def test_enforce_fails_with_fixed_startup_code():
    with pytest.raises(RuntimeError, match="SYSTEM_ASSISTANT_ENFORCE_NOT_READY"):
        validate_governance_policy("enforce")


@pytest.mark.parametrize("current,minimum", [(0, 1), (1, 0), (1, 2)])
def test_invalid_policy_revisions_block_startup(current, minimum):
    with pytest.raises(RuntimeError, match="SYSTEM_ASSISTANT_POLICY_REVISION_INVALID"):
        validate_governance_policy(
            "shadow", policy_revision=current, min_policy_revision=minimum
        )
