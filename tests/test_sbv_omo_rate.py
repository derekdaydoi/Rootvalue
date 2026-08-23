from __future__ import annotations

import contextlib
import copy
import io
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_sbv_history as history  # noqa: E402
import repair_sbv_official as official  # noqa: E402


def omo_node(rows: list[list[object]]) -> dict[str, object]:
    return {
        "status": "ok",
        "source_date": "2026-08-22",
        "schema_fingerprint": "omo-live-shape",
        "http_succeeded": True,
        "transient_error": False,
        "tables": [
            {
                "columns": [
                    "Loại hình",
                    "Khối lượng trúng thầu (Tỷ đồng)",
                    "Lãi suất trúng thầu (%/năm)",
                ],
                "rows": rows,
                "row_count": len(rows),
            }
        ],
    }


class OmoCanonicalRateTests(unittest.TestCase):
    def test_zero_volume_placeholders_do_not_erase_executed_rate(self) -> None:
        node = omo_node(
            [
                ["- Kỳ hạn 16 ngày", 4526.61, 4.5],
                ["- Kỳ hạn 35 ngày", 0, 0],
                ["- Kỳ hạn 63 ngày", 0, 0],
                ["- Kỳ hạn 91 ngày", 0, 0],
                ["Tổng cộng", 4526.61, None],
            ]
        )

        metrics = history.omo_metrics({"omo_latest": node})

        self.assertEqual(metrics["omo_awarded_bn_vnd"], 4526.61)
        self.assertEqual(metrics["omo_rate_pct"], 4.5)
        self.assertEqual(len(metrics["omo_terms"]), 4)
        self.assertEqual(official.omo_dataset_validation(node)["status"], "pass")

    def test_positive_volume_term_without_valid_rate_fails_contract(self) -> None:
        node = omo_node(
            [
                ["- Kỳ hạn 16 ngày", 4526.61, None],
                ["- Kỳ hạn 35 ngày", 0, None],
                ["Tổng cộng", 4526.61, None],
            ]
        )

        metrics = history.omo_metrics({"omo_latest": node})
        validation = official.omo_dataset_validation(node)

        self.assertIsNone(metrics["omo_rate_pct"])
        self.assertEqual(validation["status"], "fail")
        self.assertTrue(
            any("positive-volume" in error for error in validation["errors"]),
            validation["errors"],
        )

    def test_mixed_executed_rates_remain_term_level_only(self) -> None:
        node = omo_node(
            [
                ["- Kỳ hạn 16 ngày", 1000, 4.5],
                ["- Kỳ hạn 35 ngày", 500, 4.75],
                ["- Kỳ hạn 63 ngày", 0, 0],
                ["Tổng cộng", 1500, None],
            ]
        )

        metrics = history.omo_metrics({"omo_latest": node})

        self.assertIsNone(metrics["omo_rate_pct"])
        self.assertEqual(official.omo_dataset_validation(node)["status"], "pass")

    def test_corrected_derived_rate_replaces_old_same_table_date_observation(self) -> None:
        node = omo_node(
            [
                ["- Kỳ hạn 16 ngày", 4526.61, 4.5],
                ["- Kỳ hạn 35 ngày", 0, 0],
                ["- Kỳ hạn 63 ngày", 0, 0],
                ["- Kỳ hạn 91 ngày", 0, 0],
                ["Tổng cộng", 4526.61, None],
            ]
        )
        current_metrics = history.omo_metrics({"omo_latest": node})
        old_metrics = copy.deepcopy(current_metrics)
        old_metrics["omo_rate_pct"] = None
        old_metrics["omo_rate_policy"] = (
            "single official awarded rate only; mixed term rates remain in omo_terms"
        )
        old_observation = history.build_dataset_snapshot(
            "omo_latest",
            node["source_date"],
            node["schema_fingerprint"],
            "2026-08-23T00:00:00+00:00",
            old_metrics,
        )
        self.assertIsNotNone(old_observation)
        # Reproduce the pre-fix content-derived table identifier persisted on disk.
        old_observation["source_table_id"] = (
            f"omo_latest:{node['schema_fingerprint']}:"
            f"{old_observation['observation_key'][:12]}"
        )
        stored: dict[str, object] = {}

        def fake_load(path: Path, default: object) -> object:
            if path == history.MACRO:
                return {
                    "official_checks": {"omo_latest": copy.deepcopy(node)},
                    "official_validation": {
                        "status": "partial",
                        "datasets": {"omo_latest": {"status": "pass", "errors": []}},
                    },
                }
            if path == history.HISTORY:
                return {
                    "schema_version": "1.2.0",
                    "observations": [copy.deepcopy(old_observation)],
                }
            return copy.deepcopy(default)

        def fake_save(path: Path, payload: dict[str, object]) -> bool:
            self.assertEqual(path, history.HISTORY)
            stored.update(copy.deepcopy(payload))
            return True

        with (
            mock.patch.object(history, "load", side_effect=fake_load),
            mock.patch.object(history, "save_if_changed", side_effect=fake_save),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            history.main()

        omo_observations = [
            item
            for item in stored["observations"]
            if item.get("dataset") == "omo_latest"
        ]
        self.assertEqual(len(omo_observations), 1)
        self.assertEqual(omo_observations[0]["omo_rate_pct"], 4.5)
        self.assertEqual(
            omo_observations[0]["source_table_id"],
            f"omo_latest:{node['schema_fingerprint']}",
        )

    def test_same_date_different_source_table_is_preserved(self) -> None:
        first = history.build_dataset_snapshot(
            "omo_latest",
            "2026-08-22",
            "schema-a",
            "2026-08-23T00:00:00+00:00",
            {
                "omo_awarded_bn_vnd": 1000,
                "omo_rate_pct": 4.5,
                "omo_terms": [],
                "omo_rate_policy": "fixture",
            },
        )
        second = history.build_dataset_snapshot(
            "omo_latest",
            "2026-08-22",
            "schema-b",
            "2026-08-23T00:00:00+00:00",
            {
                "omo_awarded_bn_vnd": 1000,
                "omo_rate_pct": 4.5,
                "omo_terms": [],
                "omo_rate_policy": "fixture",
            },
        )
        observations: list[dict[str, object]] = []

        self.assertTrue(history.append_unique(observations, first))
        self.assertTrue(history.append_unique(observations, second))
        self.assertEqual(len(observations), 2)


if __name__ == "__main__":
    unittest.main()
