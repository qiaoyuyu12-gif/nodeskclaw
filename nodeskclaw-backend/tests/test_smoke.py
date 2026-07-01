def test_smoke() -> None:
    assert True


def test_delete_skill_route_exists():
    """确保 DELETE /instances/{id}/skills/{name} 路由已注册。"""
    from app.main import app

    routes = {r.path for r in app.routes}
    assert "/api/v1/instances/{instance_id}/skills/{skill_name}" in routes
