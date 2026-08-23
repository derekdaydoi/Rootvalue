from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "sw.js").read_text(encoding="utf-8")


class ServiceWorkerContractTests(unittest.TestCase):
    def test_first_install_seeds_canonical_data_assets(self) -> None:
        for asset in (
            "./data/rootvalue.json",
            "./data/market.json",
            "./data/global.json",
            "./data/company_dashboard.json",
            "./content/knowledge.json",
        ):
            self.assertIn(f"'{asset}'", SOURCE)
        self.assertIn("cache.addAll([...SHELL_ASSETS, ...DATA_ASSETS])", SOURCE)

    def test_runtime_cache_normalizes_legacy_timestamp_parameter(self) -> None:
        self.assertIn("url.searchParams.delete('t')", SOURCE)
        self.assertIn("normalizedDataRequest(request)", SOURCE)

    def test_cache_writes_are_awaited_and_cleanup_is_namespaced(self) -> None:
        self.assertRegex(SOURCE, r"await\s+cache\.put\(")
        self.assertIn("key.startsWith(CACHE_PREFIX)", SOURCE)
        self.assertIsNone(
            re.search(r"filter\([^)]*key\s*!==\s*CACHE_NAME[^)]*\)\s*\.map\(key\s*=>\s*caches\.delete", SOURCE),
            "cache cleanup must not delete unrelated applications' caches",
        )


if __name__ == "__main__":
    unittest.main()
