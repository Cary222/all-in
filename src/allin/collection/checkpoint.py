"""Word-level checkpoint policy shared by the DOM/API collectors.

A checkpoint lets a later run skip a ``(city, keyword)`` combination that
already finished inside the validity window. Raising the window avoids re-hitting
a platform for work that is already done; lowering it trades some redundant
requests for fresher coverage. Because the same switch also suppresses a
user-initiated re-collection, it is an explicit per-platform setting
(``platforms.<platform>.search.resume_ttl_hours``) with a documented default.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DEFAULT_RESUME_TTL_HOURS = 24
MAX_RESUME_TTL_HOURS = 720
# ``0`` disables checkpoint reuse: every run searches from the first page.
CHECKPOINT_DISABLED_TTL_HOURS = 0


def resolve_resume_ttl_hours(config: Mapping[str, Any] | None, platform: str) -> int:
    """Return the checkpoint window in hours for ``platform``.

    ``0`` means checkpoint reuse is disabled. The platform value under
    ``platforms.<platform>.search.resume_ttl_hours`` wins; the legacy top-level
    ``search.resume_ttl_hours`` is consulted only when the platform value is
    absent. ``load_config`` always materialises the platform block, so a plain
    ``elif`` fallback on the platform dict could never run for real config.
    """
    cfg = config if isinstance(config, Mapping) else {}
    raw: Any = None
    platforms = cfg.get("platforms")
    if isinstance(platforms, Mapping):
        platform_cfg = platforms.get(platform)
        if isinstance(platform_cfg, Mapping):
            search_cfg = platform_cfg.get("search")
            if isinstance(search_cfg, Mapping):
                raw = search_cfg.get("resume_ttl_hours")
    if raw is None:
        legacy_search = cfg.get("search")
        if isinstance(legacy_search, Mapping):
            raw = legacy_search.get("resume_ttl_hours")
    if raw is None:
        return DEFAULT_RESUME_TTL_HOURS
    try:
        hours = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_RESUME_TTL_HOURS
    if hours == CHECKPOINT_DISABLED_TTL_HOURS:
        return CHECKPOINT_DISABLED_TTL_HOURS
    # Only an explicit 0 disables reuse: a negative value is a typo, and must not
    # silently switch the guard off.
    return max(1, min(hours, MAX_RESUME_TTL_HOURS))
