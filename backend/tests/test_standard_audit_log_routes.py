from app.main import app


def test_audit_log_query_route_is_read_only_and_registered():
    routes = {
        (route.path, tuple(sorted(getattr(route, "methods", None) or [])))
        for route in app.routes
    }
    assert ("/api/audit-logs", ("GET",)) in routes
    assert not any(path == "/api/audit-logs" and method != ("GET",) for path, method in routes)
