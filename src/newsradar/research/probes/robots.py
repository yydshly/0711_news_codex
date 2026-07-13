from __future__ import annotations

import re


def allowed(text: str, path: str, user_agent: str = "newsradar-research") -> bool:
    """Small deterministic robots evaluator: longest Allow/Disallow match wins."""
    groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []
    for raw in text.splitlines() + [""]:
        line = raw.split("#", 1)[0].strip()
        key, _, value = line.partition(":")
        key, value = key.lower().strip(), value.strip()
        if key == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif key in {"allow", "disallow"} and agents and value:
            rules.append((key == "allow", value))
    if agents or rules:
        groups.append((agents, rules))
    matching = [
        (
            max(
                (len(agent) for agent in group if agent == "*" or agent in user_agent.lower()),
                default=0,
            ),
            rules,
        )
        for group, rules in groups
        if any(agent == "*" or agent in user_agent.lower() for agent in group)
    ]
    candidates = max(matching, key=lambda item: item[0])[1] if matching else []
    matches = [
        (allow, rule)
        for allow, rule in candidates
        if re.match("^" + re.escape(rule).replace(r"\*", ".*").replace(r"\$", "$"), path)
    ]
    if not matches:
        return True
    allow, _ = max(matches, key=lambda item: (len(item[1]), item[0]))
    return allow
