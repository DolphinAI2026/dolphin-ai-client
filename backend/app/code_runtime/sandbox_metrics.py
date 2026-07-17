from __future__ import annotations

from itertools import product


_RENEW_RESULTS = ("success", "failure")
_RENEW_REASONS = (
    "sandbox_session_expired",
    "sandbox_session_invalid",
    "sandbox_launch_token_expired",
    "sandbox_launch_token_invalid",
    "joined",
    "login_required",
    "workspace_forbidden",
    "sandbox_unavailable",
    "workspace_temporarily_unavailable",
    "manual",
    "other",
)
_REPLAY_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "OTHER")
_REPLAY_RESULTS = ("success", "failure", "skipped", "other")
_ORPHAN_STAGES = ("bootstrap", "commit", "other")
_HARD_FAILURE_REASONS = (
    "login_required",
    "workspace_forbidden",
    "sandbox_unavailable",
    "workspace_temporarily_unavailable",
    "other",
)
_CLEANUP_RESULTS = ("success", "failure", "other")


def _label(value: str, allowed: tuple[str, ...], fallback: str = "other") -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in allowed else fallback


def _series(name: str, **labels: str) -> str:
    if not labels:
        return name
    rendered = ",".join(
        f'{key}="{value}"'
        for key, value in sorted(labels.items())
    )
    return f"{name}{{{rendered}}}"


class SandboxAuthMetricsRegistry:
    def __init__(self) -> None:
        self._counters: dict[str, float] = {}
        for result, reason in product(_RENEW_RESULTS, _RENEW_REASONS):
            self._counters[_series(
                "sandbox_auth_renew_total",
                result=result,
                reason=reason,
            )] = 0.0
        self._counters["sandbox_auth_singleflight_join_total"] = 0.0
        for method, result in product(_REPLAY_METHODS, _REPLAY_RESULTS):
            self._counters[_series(
                "sandbox_auth_replay_total",
                method=method,
                result=result,
            )] = 0.0
        for stage in _ORPHAN_STAGES:
            self._counters[_series(
                "sandbox_auth_orphan_session_total",
                stage=stage,
            )] = 0.0
        for reason in _HARD_FAILURE_REASONS:
            self._counters[_series(
                "sandbox_auth_hard_failure_total",
                reason=reason,
            )] = 0.0
        for result in _CLEANUP_RESULTS:
            self._counters[_series(
                "sandbox_builder_url_cleanup_total",
                result=result,
            )] = 0.0
        self._renew_duration_count = 0
        self._renew_duration_sum = 0.0

    def record_renew(self, result: str, reason: str, duration_seconds: float) -> None:
        result = _label(result, _RENEW_RESULTS, "failure")
        reason = _label(reason, _RENEW_REASONS)
        self._counters[_series(
            "sandbox_auth_renew_total",
            result=result,
            reason=reason,
        )] += 1
        self._renew_duration_count += 1
        self._renew_duration_sum += max(0.0, float(duration_seconds))

    def record_singleflight_join(self) -> None:
        self._counters["sandbox_auth_singleflight_join_total"] += 1

    def record_replay(self, method: str, result: str) -> None:
        method = _label(str(method or "").upper(), _REPLAY_METHODS, "OTHER")
        result = _label(result, _REPLAY_RESULTS)
        self._counters[_series(
            "sandbox_auth_replay_total",
            method=method,
            result=result,
        )] += 1

    def record_orphan(self, stage: str) -> None:
        stage = _label(stage, _ORPHAN_STAGES)
        self._counters[_series(
            "sandbox_auth_orphan_session_total",
            stage=stage,
        )] += 1

    def record_hard_failure(self, reason: str) -> None:
        reason = _label(reason, _HARD_FAILURE_REASONS)
        self._counters[_series(
            "sandbox_auth_hard_failure_total",
            reason=reason,
        )] += 1

    def record_builder_url_cleanup(self, result: str) -> None:
        result = _label(result, _CLEANUP_RESULTS)
        self._counters[_series(
            "sandbox_builder_url_cleanup_total",
            result=result,
        )] += 1

    def snapshot(self) -> dict[str, float]:
        snapshot = dict(self._counters)
        snapshot["sandbox_auth_renew_duration_count"] = float(
            self._renew_duration_count
        )
        snapshot["sandbox_auth_renew_duration_sum"] = self._renew_duration_sum
        return snapshot

    def render(self) -> str:
        lines = [
            "# TYPE sandbox_auth_renew_total counter",
            "# TYPE sandbox_auth_renew_duration summary",
            "# TYPE sandbox_auth_singleflight_join_total counter",
            "# TYPE sandbox_auth_replay_total counter",
            "# TYPE sandbox_auth_orphan_session_total counter",
            "# TYPE sandbox_auth_hard_failure_total counter",
            "# TYPE sandbox_builder_url_cleanup_total counter",
        ]
        snapshot = self.snapshot()
        lines.extend(
            f"{name} {value:g}"
            for name, value in sorted(snapshot.items())
        )
        return "\n".join(lines) + "\n"


sandbox_auth_metrics = SandboxAuthMetricsRegistry()
