from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_data_contracts as contracts  # noqa: E402


class PrimitiveContractTests(unittest.TestCase):
    def test_finite_rejects_boolean_nan_and_infinity(self) -> None:
        self.assertTrue(contracts.finite(0))
        self.assertTrue(contracts.finite(1.25))
        self.assertFalse(contracts.finite(True))
        self.assertFalse(contracts.finite(math.nan))
        self.assertFalse(contracts.finite(math.inf))

    def test_public_errors_are_scanned_for_credentials(self) -> None:
        payload = {"provider_error": "request failed; api_key=should-not-be-public"}
        values = list(contracts.public_error_strings(payload, "snapshot"))

        self.assertEqual(values[0][0], "snapshot.provider_error")
        self.assertIsNotNone(contracts.SECRET_PATTERN.search(values[0][1]))

    def test_quoted_bearer_header_is_detected_but_redacted_value_is_safe(self) -> None:
        leaked = "headers={'Authorization': 'Bearer abcdef1234567890'}"
        safe = "headers={'Authorization': 'Bearer <redacted>'}"

        self.assertIsNotNone(contracts.SECRET_PATTERN.search(leaked))
        self.assertIsNone(contracts.SECRET_PATTERN.search(safe))

    def test_credentials_inside_health_error_arrays_are_scanned(self) -> None:
        payload = {"health": {"errors": ["Bearer abcdef1234567890"]}}
        values = list(contracts.public_error_strings(payload, "snapshot"))

        self.assertEqual(values, [("snapshot.health.errors[0]", "Bearer abcdef1234567890")])
        self.assertIsNotNone(contracts.SECRET_PATTERN.search(values[0][1]))


class SnapshotContractTests(unittest.TestCase):
    def test_stale_valid_official_snapshot_is_usable_but_not_silent(self) -> None:
        macro = {
            "official_validation": {
                "status": "pass",
                "datasets": {
                    "money_supply_deposits": {"status": "pass"},
                    "omo_latest": {"status": "pass"},
                },
            },
            "official_refresh": {"status": "warning"},
        }
        errors: list[str] = []
        notes: list[str] = []

        contracts.validate_macro(macro, errors, notes)

        self.assertEqual(errors, [])
        self.assertTrue(any("last-known-good" in note for note in notes))

    def test_invalid_official_snapshot_is_fatal(self) -> None:
        macro = {
            "official_validation": {
                "status": "fail",
                "datasets": {
                    "money_supply_deposits": {"status": "fail"},
                    "omo_latest": {"status": "pass"},
                },
            },
            "official_refresh": {"status": "error"},
        }
        errors: list[str] = []
        notes: list[str] = []

        contracts.validate_macro(macro, errors, notes)

        self.assertTrue(any("validation is not pass" in error for error in errors))
        self.assertTrue(any("money_supply_deposits" in error for error in errors))
        self.assertTrue(any("refresh status" in error for error in errors))

    def test_partial_market_cannot_publish_ranked_picks(self) -> None:
        market = {
            "status": "partial",
            "rows": [{"symbol": "FPT", "as_of": "2026-08-19", "rank_current": 1}],
            "picks": [{"symbol": "FPT"}],
        }
        watch = {"symbols": [{"symbol": "FPT"}, {"symbol": "VNM"}]}
        errors: list[str] = []
        notes: list[str] = []

        contracts.validate_market(market, watch, errors, notes)

        self.assertTrue(any("publishes picks" in error for error in errors))
        self.assertTrue(any("partial" in note for note in notes))

    def test_stale_full_universe_may_keep_last_known_good_picks(self) -> None:
        market = {
            "status": "stale",
            "as_of": "2026-08-19",
            "rows": [
                {"symbol": "FPT", "as_of": "2026-08-19", "rank_current": 1, "state": "Neutral"},
                {"symbol": "VNM", "as_of": "2026-08-19", "rank_current": 2, "state": "Neutral"},
            ],
            "picks": [{"symbol": "FPT"}],
        }
        watch = {"symbols": [{"symbol": "FPT"}, {"symbol": "VNM"}]}
        errors: list[str] = []
        notes: list[str] = []

        contracts.validate_market(market, watch, errors, notes)

        self.assertEqual(errors, [])
        self.assertTrue(any("last-known-good" in note for note in notes))

    def test_market_selection_cannot_claim_structural_leadership(self) -> None:
        row = {
            "symbol": "FPT",
            "sector": "Technology",
            "as_of": "2026-08-19",
            "rank_current": 1,
            "sector_rank": 1,
            "selection_type": "Leader",
        }
        market = {
            "status": "ok",
            "rows": [row],
            "picks": [row],
            "selection_by_sector": {"Technology": [row]},
        }
        watch = {"symbols": [{"symbol": "FPT"}]}
        errors: list[str] = []
        notes: list[str] = []

        contracts.validate_market(market, watch, errors, notes)

        self.assertTrue(any("misleading/unknown" in error for error in errors))

    def test_root_market_must_match_canonical_market_snapshot(self) -> None:
        root = {
            "pipeline_status": "partial",
            "generated_at": "2026-08-19T00:00:00+00:00",
            "health": {"errors": [], "warnings": []},
            "market": {"status": "not_run", "as_of": None, "rows": []},
        }
        market = {
            "status": "ok",
            "as_of": "2026-08-19",
            "rows": [{"symbol": "FPT"}],
        }
        errors: list[str] = []

        contracts.validate_root_snapshot(root, market, errors)

        self.assertTrue(any("not synchronized" in error for error in errors))
        self.assertTrue(any("row count differs" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
