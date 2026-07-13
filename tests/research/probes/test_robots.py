from newsradar.research.probes.robots import allowed


def test_robots_uses_longest_allow_rule_and_wildcards() -> None:
    robots = "User-agent: *\nDisallow: /private/*\nAllow: /private/public$\n"
    assert allowed(robots, "/private/public")
    assert not allowed(robots, "/private/secret")
