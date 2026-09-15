"""Server-side capability boundaries for platform-specific workflows."""

PLATFORM_CAPABILITIES: dict[str, frozenset[str]] = {
    "boss": frozenset({"collect", "score", "greet", "deliver", "monitor"}),
    "zhilian": frozenset({"collect", "score", "greet", "deliver", "monitor"}),
    "51job": frozenset({"collect", "score", "greet", "deliver", "monitor"}),
    "liepin": frozenset({"collect", "score", "greet", "deliver", "monitor"}),
}

PLATFORM_DISPLAY_NAMES: dict[str, str] = {
    "boss": "BOSS 直聘",
    "zhilian": "智联招聘",
    "51job": "前程无忧",
    "liepin": "猎聘",
}


def platform_supports(platform: str, capability: str) -> bool:
    return capability in PLATFORM_CAPABILITIES.get(str(platform), frozenset())
