from unittest import TestCase

from allin.collection.capabilities import platform_supports


class PlatformCapabilityTests(TestCase):
    def test_all_platforms_support_full_capabilities(self):
        for platform in ("boss", "zhilian", "51job", "liepin"):
            for capability in ("collect", "score", "greet", "deliver", "monitor"):
                self.assertTrue(platform_supports(platform, capability), f"{platform} should support {capability}")

    def test_unknown_platform_unsupported(self):
        for capability in ("collect", "score", "greet", "deliver", "monitor"):
            self.assertFalse(platform_supports("unknown", capability))
