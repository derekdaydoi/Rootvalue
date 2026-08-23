from __future__ import annotations

import inspect
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_foundation as foundation  # noqa: E402
import publish_foundation as publisher  # noqa: E402


def dataset(
    values: list[float],
    *,
    source_as_of: str = "2026-07",
    status: str = "ok",
) -> dict[str, object]:
    rows = [[f"2026-{index + 1:02d}", value] for index, value in enumerate(values)]
    return {
        "status": status,
        "refresh_status": "fresh" if status == "ok" else status,
        "source": "Vnstock Data Macro normalized feeds",
        "frequency": "month",
        "source_as_of": source_as_of,
        "fetched_at": "2026-08-20T00:00:00+00:00",
        "data": {"columns": ["period", "value"], "rows": rows, "row_count": len(rows)},
    }


def failed_dataset(message: str) -> dict[str, object]:
    return {
        "status": "error",
        "refresh_status": "failed",
        "error": message,
        "data": {"columns": [], "rows": [], "row_count": 0},
    }


class MacroPreservationTests(unittest.TestCase):
    def test_weekly_macro_refresh_never_fetches_or_mutates_official_sbv_nodes(self) -> None:
        official_nodes = {
            "official_checks": {
                "money_supply_deposits": {
                    "status": "ok",
                    "source_date": "2026-08-19",
                    "tables": [{"columns": ["x"], "rows": [[1]]}],
                    "fetched_at": "2026-08-20T00:00:00+00:00",
                },
                "omo_latest": {
                    "status": "ok",
                    "source_date": "2026-08-19",
                    "tables": [{"columns": ["x"], "rows": [[2]]}],
                },
            },
            "official_validation": {
                "status": "pass",
                "datasets": {"money_supply_deposits": {"status": "pass"}},
            },
            "official_refresh": {
                "status": "warning",
                "datasets": {"omo_latest": {"kept_last_known_good": True}},
                "last_attempt_at": "2026-08-21T00:00:00+00:00",
            },
        }
        previous = {
            "historical_provider": "vnstock_data",
            "datasets": {"credit": dataset([1.0, 2.0])},
            **deepcopy(official_nodes),
        }
        config = {
            "official_sbv_sources": {
                "money_supply_deposits": "https://must-not-be-called.example/money",
                "omo": "https://must-not-be-called.example/omo",
            },
            "policy": {"macro_state_requires": ["credit"]},
        }

        with (
            mock.patch.dict(sys.modules, {"vnstock_data": None}),
            mock.patch.object(
                foundation,
                "parse_official_table",
                side_effect=AssertionError("weekly foundation attempted an official SBV fetch"),
            ) as official_fetch,
        ):
            result = foundation.fetch_macro(config, deepcopy(previous))

        official_fetch.assert_not_called()
        self.assertNotIn("parse_official_table", inspect.getsource(foundation.fetch_macro))
        for field in foundation.OFFICIAL_SBV_OWNED_FIELDS:
            self.assertEqual(result[field], official_nodes[field])
            self.assertEqual(
                foundation.semantic_payload(result[field]),
                foundation.semantic_payload(official_nodes[field]),
            )

    def test_macro_merge_rejects_fresh_attempt_to_overwrite_official_sbv_nodes(self) -> None:
        official_nodes = {
            "official_checks": {"owner": "daily-sbv", "payload": [1, 2, 3]},
            "official_validation": {"status": "pass", "marker": "keep"},
            "official_refresh": {"status": "warning", "marker": "keep"},
        }
        previous = {
            "datasets": {"credit": dataset([1.0])},
            **deepcopy(official_nodes),
        }
        attempted = {
            "datasets": {"credit": dataset([2.0, 3.0])},
            "official_checks": {"owner": "weekly-overwrite"},
            "official_validation": {"status": "fail"},
            "official_refresh": {"status": "error"},
        }

        result = foundation.merge_macro_snapshot(
            previous,
            attempted,
            {"policy": {"macro_state_requires": ["credit"]}},
        )

        for field in foundation.OFFICIAL_SBV_OWNED_FIELDS:
            self.assertEqual(result[field], official_nodes[field])

    def test_provider_unavailable_preserves_prior_good_dataset(self) -> None:
        previous = {
            "historical_provider": "vnstock_data",
            "datasets": {"credit": dataset([1.0, 2.0])},
        }
        config = {
            "official_sbv_sources": {},
            "policy": {"macro_state_requires": ["credit"]},
        }

        with mock.patch.dict(sys.modules, {"vnstock_data": None}):
            result = foundation.fetch_macro(config, deepcopy(previous))

        kept = result["datasets"]["credit"]
        self.assertEqual(kept["status"], "stale")
        self.assertEqual(kept["refresh_status"], "stale")
        self.assertEqual(kept["data"], previous["datasets"]["credit"]["data"])
        self.assertIn("last_attempt_at", kept)
        self.assertIn("last_refresh_error", kept)
        self.assertEqual(result["historical_provider"], "vnstock_data")
        self.assertEqual(result["historical_provider_status"], "unavailable")
        self.assertTrue(result["coverage"]["history_ready"])
        self.assertFalse(result["coverage"]["state_ready"])
        self.assertEqual(result["coverage"]["stale"], ["credit"])

    def test_partial_fresh_results_merge_per_dataset(self) -> None:
        previous = {
            "historical_provider": "vnstock_data",
            "datasets": {
                "credit": dataset([1.0, 2.0], source_as_of="2026-06"),
                "cpi": dataset([3.0, 4.0], source_as_of="2026-06"),
            },
        }
        attempted = {
            "historical_provider": "vnstock_data",
            "historical_provider_error": None,
            "datasets": {
                "credit": dataset([10.0, 11.0, 12.0], source_as_of="2026-07"),
                "cpi": failed_dataset("temporary CPI failure"),
            },
            "official_checks": {},
        }
        config = {"policy": {"macro_state_requires": ["credit", "cpi"]}}

        result = foundation.merge_macro_snapshot(previous, attempted, config)

        self.assertEqual(result["datasets"]["credit"]["status"], "ok")
        self.assertEqual(result["datasets"]["credit"]["data"], attempted["datasets"]["credit"]["data"])
        self.assertEqual(result["datasets"]["cpi"]["status"], "stale")
        self.assertEqual(result["datasets"]["cpi"]["data"], previous["datasets"]["cpi"]["data"])
        self.assertEqual(result["coverage"]["available"], ["credit", "cpi"])
        self.assertEqual(result["coverage"]["fresh_available"], ["credit"])
        self.assertEqual(result["coverage"]["stale"], ["cpi"])
        self.assertTrue(result["coverage"]["history_ready"])
        self.assertFalse(result["coverage"]["state_ready"])
        self.assertEqual(result["state_engine"]["status"], "data_ready_stale")

    def test_coverage_regression_keeps_history_but_blocks_fresh_readiness(self) -> None:
        previous = {
            "historical_provider": "vnstock_data",
            "datasets": {
                "credit": dataset([1.0, 2.0, 3.0], source_as_of="2026-07"),
                "cpi": dataset([4.0, 5.0], source_as_of="2026-07"),
            },
        }
        attempted = {
            "historical_provider": "vnstock_data",
            "historical_provider_error": None,
            "datasets": {
                "credit": dataset([99.0], source_as_of="2026-08"),
                "cpi": failed_dataset("CPI unavailable"),
            },
            "official_checks": {},
        }
        config = {"policy": {"macro_state_requires": ["credit", "cpi"]}}

        result = foundation.merge_macro_snapshot(previous, attempted, config)

        self.assertEqual(result["datasets"]["credit"]["data"], previous["datasets"]["credit"]["data"])
        self.assertEqual(set(result["preserved_datasets"]), {"credit", "cpi"})
        self.assertTrue(any("credit" in message and "shrank" in message for message in result["coverage_regressions"]))
        self.assertEqual(result["coverage"]["available"], ["credit", "cpi"])
        self.assertEqual(result["coverage"]["missing"], [])
        self.assertTrue(result["coverage"]["history_ready"])
        self.assertTrue(result["coverage"]["state_usable"])
        self.assertFalse(result["coverage"]["state_ready"])

    def test_publisher_uses_source_date_from_stale_usable_dataset(self) -> None:
        macro = {
            "datasets": {
                "credit": dataset([1.0], source_as_of="2026-06", status="stale"),
                "cpi": dataset([2.0], source_as_of="2026-07"),
            }
        }

        self.assertEqual(publisher.macro_source_as_of(macro, []), "2026-07")
        macro["datasets"]["cpi"] = failed_dataset("down")
        self.assertEqual(publisher.macro_source_as_of(macro, []), "2026-06")

    def test_publisher_surfaces_stale_market_attempt_in_root_health(self) -> None:
        market = {
            "status": "stale",
            "last_error": "market refresh incomplete: 56/57",
            "last_refresh_attempt": {
                "errors": ["market:ABC:provider timeout"],
            },
            "health": {
                "errors": [],
                "warnings": ["missing=ABC; kept last-known-good snapshot"],
            },
        }
        warnings: list[str] = []
        errors: list[str] = []

        publisher.merge_market_health(market, warnings, errors)

        self.assertEqual(errors, [])
        self.assertTrue(any("56/57" in item for item in warnings))
        self.assertTrue(any("provider timeout" in item for item in warnings))
        self.assertTrue(all(item.startswith("Market refresh:") for item in warnings))


if __name__ == "__main__":
    unittest.main()
