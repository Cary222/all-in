import unittest

from allin.collection.capabilities import PLATFORM_CAPABILITIES, platform_supports


class PlatformCapabilitiesTests(unittest.TestCase):
    def test_boss_has_full_capabilities(self):
        for cap in ("collect", "score", "greet", "deliver", "monitor"):
            self.assertTrue(platform_supports("boss", cap))

    def test_all_four_platforms_have_full_capabilities(self):
        for platform in ("boss", "zhilian", "51job", "liepin"):
            for cap in ("collect", "score", "greet", "deliver", "monitor"):
                self.assertTrue(platform_supports(platform, cap), f"{platform} should support {cap}")

    def test_unknown_platform_supports_nothing(self):
        self.assertFalse(platform_supports("unknown", "collect"))
        self.assertFalse(platform_supports("nonexistent", "score"))

    def test_unknown_capability_returns_false(self):
        self.assertFalse(platform_supports("boss", "nonexistent"))

    def test_capability_map_keys(self):
        self.assertEqual(
            set(PLATFORM_CAPABILITIES),
            {"boss", "zhilian", "51job", "liepin"},
        )


if __name__ == "__main__":
    unittest.main()