"""断点续采有效期（resume_ttl_hours）解析测试。

覆盖共享解析器本身，以及它与 load_config 默认值基底的交互：
DEFAULTS 不得预置该字段，否则平台级值恒非空，顶层 legacy 回退会静默失效。
"""

from __future__ import annotations

import pytest

from allin.collection.checkpoint import (
    DEFAULT_RESUME_TTL_HOURS,
    MAX_RESUME_TTL_HOURS,
    resolve_resume_ttl_hours,
)
from allin.config import DEFAULTS, _deep_copy_dict, _deep_merge


def _loaded(user_config: dict) -> dict:
    """复现 load_config 的合并顺序：DEFAULTS 基底 + 用户配置。"""
    merged = _deep_copy_dict(DEFAULTS)
    _deep_merge(merged, user_config)
    return merged


class TestResolveResumeTtlHours:
    def test_missing_falls_back_to_default(self) -> None:
        assert resolve_resume_ttl_hours({}, "zhilian") == DEFAULT_RESUME_TTL_HOURS

    def test_none_config_falls_back_to_default(self) -> None:
        assert resolve_resume_ttl_hours(None, "zhilian") == DEFAULT_RESUME_TTL_HOURS

    def test_platform_value_wins(self) -> None:
        config = {"platforms": {"zhilian": {"search": {"resume_ttl_hours": 48}}}}
        assert resolve_resume_ttl_hours(config, "zhilian") == 48

    def test_zero_disables_checkpoint(self) -> None:
        config = {"platforms": {"zhilian": {"search": {"resume_ttl_hours": 0}}}}
        assert resolve_resume_ttl_hours(config, "zhilian") == 0

    def test_negative_is_treated_as_invalid_not_disabled(self) -> None:
        # A negative value is a typo; it must not silently switch the guard off.
        config = {"platforms": {"zhilian": {"search": {"resume_ttl_hours": -5}}}}
        assert resolve_resume_ttl_hours(config, "zhilian") == 1

    def test_clamped_to_max(self) -> None:
        config = {"platforms": {"zhilian": {"search": {"resume_ttl_hours": 9999}}}}
        assert resolve_resume_ttl_hours(config, "zhilian") == MAX_RESUME_TTL_HOURS

    def test_invalid_value_falls_back_to_default(self) -> None:
        config = {"platforms": {"zhilian": {"search": {"resume_ttl_hours": "abc"}}}}
        assert resolve_resume_ttl_hours(config, "zhilian") == DEFAULT_RESUME_TTL_HOURS

    def test_legacy_top_level_search_is_read_when_platform_absent(self) -> None:
        assert resolve_resume_ttl_hours({"search": {"resume_ttl_hours": 72}}, "zhilian") == 72

    def test_platform_value_overrides_legacy_search(self) -> None:
        config = {
            "search": {"resume_ttl_hours": 72},
            "platforms": {"zhilian": {"search": {"resume_ttl_hours": 12}}},
        }
        assert resolve_resume_ttl_hours(config, "zhilian") == 12

    def test_platforms_are_isolated(self) -> None:
        config = {"platforms": {"zhilian": {"search": {"resume_ttl_hours": 12}}}}
        assert resolve_resume_ttl_hours(config, "51job") == DEFAULT_RESUME_TTL_HOURS


class TestDefaultsDoNotShadowLegacyFallback:
    """DEFAULTS 是运行时配置的基底，不是纯兜底。

    一旦它预置 resume_ttl_hours，平台级取值就恒非空，顶层 search 回退将永不生效
    —— 与旧实现里那个永不执行的 elif 分支是同一种失效方式。
    """

    @pytest.mark.parametrize("platform", ["zhilian", "51job", "liepin"])
    def test_defaults_do_not_prefill_resume_ttl_hours(self, platform: str) -> None:
        search = DEFAULTS["platforms"][platform]["search"]
        assert "resume_ttl_hours" not in search

    @pytest.mark.parametrize("platform", ["zhilian", "51job", "liepin"])
    def test_legacy_search_still_reachable_after_merge(self, platform: str) -> None:
        merged = _loaded({"search": {"resume_ttl_hours": 1}})
        assert resolve_resume_ttl_hours(merged, platform) == 1

    @pytest.mark.parametrize("platform", ["zhilian", "51job", "liepin"])
    def test_untouched_config_resolves_to_default_after_merge(self, platform: str) -> None:
        merged = _loaded({})
        assert resolve_resume_ttl_hours(merged, platform) == DEFAULT_RESUME_TTL_HOURS
