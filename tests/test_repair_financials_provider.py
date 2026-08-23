from __future__ import annotations

import contextlib
import io
import json
import sys
import types
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import repair_financials as repair  # noqa: E402


class RepairProviderCallTests(unittest.TestCase):
    def setUp(self) -> None:
        repair._LAST_PROVIDER_CALL = 0.0
        repair._GUEST_BACKOFF_USED = False
        repair._GUEST_PROVIDER_BLOCKED = False

    def test_guest_system_exit_waits_once_then_retries_successfully(self) -> None:
        request = mock.Mock(side_effect=[SystemExit("guest limit 20/20"), "ok"])

        with (
            mock.patch.object(repair, "API_KEY_PRESENT", False),
            mock.patch.object(repair, "RATE_SECONDS", 0.0),
            mock.patch.object(repair.time, "sleep") as sleep,
        ):
            result = repair.provider_call(request)

        self.assertEqual(result, "ok")
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(repair.GUEST_BACKOFF_SECONDS)

    def test_second_system_exit_becomes_recordable_failure_and_stops_requests(self) -> None:
        request = mock.Mock(
            side_effect=[SystemExit("guest limit 20/20"), SystemExit("still limited")]
        )

        with (
            mock.patch.object(repair, "API_KEY_PRESENT", False),
            mock.patch.object(repair, "RATE_SECONDS", 0.0),
            mock.patch.object(repair.time, "sleep") as sleep,
        ):
            with self.assertRaises(repair.ProviderTerminatedError) as raised:
                repair.provider_call(request)

            blocked_request = mock.Mock(return_value="must not run")
            with self.assertRaises(repair.ProviderTerminatedError):
                repair.provider_call(blocked_request)

        self.assertIsInstance(raised.exception, RuntimeError)
        self.assertNotIsInstance(raised.exception, SystemExit)
        self.assertIn("one 65-second retry", str(raised.exception))
        self.assertEqual(request.call_count, 2)
        blocked_request.assert_not_called()
        sleep.assert_called_once_with(repair.GUEST_BACKOFF_SECONDS)

    def test_authenticated_system_exit_is_recorded_without_guest_backoff(self) -> None:
        request = mock.Mock(side_effect=SystemExit("provider terminated"))

        with (
            mock.patch.object(repair, "API_KEY_PRESENT", True),
            mock.patch.object(repair, "RATE_SECONDS", 0.0),
            mock.patch.object(repair.time, "sleep") as sleep,
        ):
            with self.assertRaises(repair.ProviderTerminatedError):
                repair.provider_call(request)

        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()

    def test_main_records_provider_initialization_exit_instead_of_terminating(self) -> None:
        fake_vnstock = types.ModuleType("vnstock")

        class ExitingFundamental:
            def __init__(self) -> None:
                raise SystemExit("guest limit 20/20")

        fake_vnstock.Fundamental = ExitingFundamental
        output = io.StringIO()

        with (
            mock.patch.dict(sys.modules, {"vnstock": fake_vnstock}),
            mock.patch.object(repair, "API_KEY_PRESENT", False),
            mock.patch.object(repair, "RATE_SECONDS", 0.0),
            mock.patch.object(repair.time, "sleep"),
            contextlib.redirect_stdout(output),
        ):
            repair.main()

        result = json.loads(output.getvalue())
        self.assertEqual(result["repaired"], [])
        self.assertEqual(len(result["failures"]), 1)
        self.assertIn("provider initialization", result["failures"][0])
        self.assertIn("one 65-second retry", result["failures"][0])

    def test_successful_fallback_repair_refreshes_manifest_readiness(self) -> None:
        years = list(range(2018, 2026))

        def report(status: str = "ok") -> dict[str, object]:
            has_data = status == "ok"
            return {
                "status": status,
                "years": years if has_data else [],
                "source_as_of": "2025" if has_data else None,
                "data": {
                    "columns": ["metric"],
                    "rows": [["fixture"]] if has_data else [],
                    "row_count": 1 if has_data else 0,
                },
                "refresh_status": "fresh" if has_data else "empty",
            }

        company_path = repair.COMPANY_DIR / "FPT.json"
        store = {
            repair.WATCHLIST: {"fundamental_symbols": ["FPT"]},
            repair.FOUNDATION_CONFIG: {
                "annual_min_periods": 8,
                "quarterly_target_periods": 32,
            },
            company_path: {
                "symbol": "FPT",
                "status": "partial",
                "reports": {
                    "annual": {
                        "balance_sheet": report("empty"),
                        "income_statement": report(),
                        "cash_flow": report(),
                        "ratio": report(),
                    },
                    "quarterly": {"balance_sheet": report()},
                },
                "coverage": {},
            },
            repair.MANIFEST: {
                "companies": [{"symbol": "FPT", "annual_periods": 0}],
                "company_qc": {
                    "requested": 1,
                    "minimum_8y_ready": 0,
                    "all_minimum_ready": False,
                },
                "macro_qc": {"state_ready": True},
                "foundation_ready": False,
            },
        }

        def fake_load(path: Path, default: object) -> object:
            return deepcopy(store.get(path, default))

        def fake_save(path: Path, value: object) -> None:
            store[path] = deepcopy(value)

        fake_vnstock = types.ModuleType("vnstock")

        class Fundamental:
            pass

        fake_vnstock.Fundamental = Fundamental
        repaired_frame = repair.pd.DataFrame(
            [["fixture", *range(8)]],
            columns=["metric", *[str(year) for year in years]],
        )
        output = io.StringIO()

        with (
            mock.patch.dict(sys.modules, {"vnstock": fake_vnstock}),
            mock.patch.object(repair, "load", side_effect=fake_load),
            mock.patch.object(repair, "save", side_effect=fake_save),
            mock.patch.object(repair, "provider_call", side_effect=lambda fn: fn()),
            mock.patch.object(
                repair,
                "call_unified_balance_sheet",
                side_effect=RuntimeError("fixture primary path unavailable"),
            ) as unified_call,
            mock.patch.object(
                repair, "call_legacy_balance_sheet", return_value=(repaired_frame, "KBS")
            ) as legacy_call,
            contextlib.redirect_stdout(output),
        ):
            repair.main()

        result = json.loads(output.getvalue())
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["repaired"], ["FPT:annual:Legacy Finance/KBS"])
        self.assertTrue(result["manifest_changed"])
        unified_call.assert_called_once()
        legacy_call.assert_called_once_with("FPT", "year")

        company = store[company_path]
        self.assertEqual(company["coverage"]["annual_periods"], 8)
        self.assertTrue(company["coverage"]["minimum_met"])
        self.assertEqual(company["status"], "ready")

        manifest = store[repair.MANIFEST]
        self.assertEqual(manifest["companies"][0]["annual_periods"], 8)
        self.assertTrue(manifest["companies"][0]["minimum_met"])
        self.assertTrue(manifest["companies"][0]["ready_for_foundation"])
        self.assertEqual(
            manifest["companies"][0]["required_reports_ready"],
            {"balance_sheet": True, "income_statement": True, "cash_flow": True},
        )
        self.assertEqual(manifest["companies"][0]["source_as_of"], "2025")
        self.assertEqual(manifest["company_qc"]["minimum_8y_ready"], 1)
        self.assertTrue(manifest["company_qc"]["all_minimum_ready"])
        self.assertTrue(manifest["foundation_ready"])


if __name__ == "__main__":
    unittest.main()
