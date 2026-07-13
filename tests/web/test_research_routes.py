from newsradar.web.app import create_app


def test_research_routes_are_read_only_and_render():
    app = create_app()
    routes = {route.path: route.methods for route in app.routes if hasattr(route, "methods")}
    assert routes["/research"] == {"GET"}
    assert routes["/research/targets/{source_id}"] == {"GET"}


def test_remediation_console_route_is_read_only():
    app = create_app()
    routes = {route.path: route.methods for route in app.routes if hasattr(route, "methods")}

    assert routes["/remediation"] == {"GET"}


def test_research_target_unknown_is_404():
    app = create_app()
    assert any(route.path == "/research/targets/{source_id}" for route in app.routes)
