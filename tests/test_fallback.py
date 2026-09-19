import unittest

from backend.app.providers import FallbackChain, ProviderError


class FallbackTests(unittest.TestCase):
    def test_primary_failure_uses_secondary(self):
        calls = []

        def primary():
            calls.append("primary")
            raise ProviderError("simulated outage")

        def secondary():
            calls.append("secondary")
            return {"ok": True}

        result = FallbackChain("video", [("primary-video", primary), ("secondary-video", secondary)]).run()
        self.assertEqual(result.provider, "secondary-video")
        self.assertEqual(result.value, {"ok": True})
        self.assertEqual(calls, ["primary", "secondary"])

    def test_retry_budget_blocks_after_three_attempts(self):
        def unavailable():
            raise ProviderError("down")

        chain = FallbackChain("audio", [("one", unavailable), ("two", unavailable), ("three", unavailable), ("four", unavailable)])
        with self.assertRaises(ProviderError) as error:
            chain.run()
        self.assertIn("after 3 attempts", str(error.exception))
