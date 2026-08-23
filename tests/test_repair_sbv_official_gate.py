from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import repair_sbv_official as sbv  # noqa: E402


def valid_money() -> dict[str, object]:
    return {
        "status": "ok",
        "label": "Money",
        "url": "https://sbv.example/money",
        "source": "State Bank of Vietnam official website",
        "provenance": "primary_official",
        "source_date": "2026-08-19",
        "source_date_evidence": "fixture",
        "fetched_at": "2026-08-20T00:00:00+00:00",
        "schema_fingerprint": "money-schema",
        "http_succeeded": True,
        "transient_error": False,
        "tables": [
            {
                "columns": ["Chỉ tiêu", "Số dư", "Tốc độ tăng"],
                "rows": [
                    ["Tổng phương tiện thanh toán", 20_000_000, 5.2],
                    ["Tiền gửi của TCKT", 8_000_000, 4.1],
                    ["Tiền gửi của dân cư", 7_000_000, 6.3],
                ],
                "row_count": 3,
            }
        ],
    }


def valid_omo() -> dict[str, object]:
    return {
        "status": "ok",
        "label": "OMO",
        "url": "https://sbv.example/omo",
        "source": "State Bank of Vietnam official website",
        "provenance": "primary_official",
        "source_date": "2026-08-19",
        "source_date_evidence": "fixture",
        "fetched_at": "2026-08-20T00:00:00+00:00",
        "schema_fingerprint": "omo-schema",
        "http_succeeded": True,
        "transient_error": False,
        "tables": [
            {
                "columns": ["Loại hình", "Khối lượng trúng thầu", "Lãi suất"],
                "rows": [
                    ["- Kỳ hạn 7 ngày", 1_000, 4.5],
                    ["Tổng cộng", 1_000, None],
                ],
                "row_count": 2,
            }
        ],
    }


def transient_failure(message: str = "temporary network outage") -> dict[str, object]:
    return {
        "status": "error",
        "source_date": None,
        "schema_fingerprint": None,
        "tables": [],
        "fetched_at": "2026-08-21T00:00:00+00:00",
        "failure_kind": "transient_fetch_error",
        "transient_error": True,
        "http_succeeded": False,
        "error": message,
    }


class OfficialRefreshGateTests(unittest.TestCase):
    def test_fetch_classifies_dependency_and_network_errors_as_transient(self) -> None:
        with mock.patch.dict(sys.modules, {"requests": None}):
            import_failure = sbv.fetch_tables("https://sbv.example/table", "fixture")

        class FakeConnectionError(Exception):
            pass

        class FakeTimeout(Exception):
            pass

        fake_requests = types.ModuleType("requests")
        fake_requests.exceptions = types.SimpleNamespace(
            ConnectionError=FakeConnectionError,
            Timeout=FakeTimeout,
        )
        fake_requests.get = mock.Mock(side_effect=FakeConnectionError("connection reset"))
        with mock.patch.dict(sys.modules, {"requests": fake_requests}):
            network_failure = sbv.fetch_tables("https://sbv.example/table", "fixture")

        self.assertTrue(import_failure["transient_error"])
        self.assertEqual(import_failure["failure_kind"], "dependency_import_error")
        self.assertFalse(import_failure["http_succeeded"])
        self.assertTrue(network_failure["transient_error"])
        self.assertEqual(network_failure["failure_kind"], "transient_transport_error")
        self.assertFalse(network_failure["http_succeeded"])

    def test_http_404_is_hard_but_429_and_503_are_transient(self) -> None:
        class FakeConnectionError(Exception):
            pass

        class FakeTimeout(Exception):
            pass

        class FakeHTTPError(Exception):
            def __init__(self, response: object) -> None:
                super().__init__(f"HTTP {response.status_code}")
                self.response = response

        class Response:
            text = ""

            def __init__(self, status_code: int) -> None:
                self.status_code = status_code

            def raise_for_status(self) -> None:
                raise FakeHTTPError(self)

        def fetched_http_failure(status_code: int) -> dict[str, object]:
            fake_requests = types.ModuleType("requests")
            fake_requests.exceptions = types.SimpleNamespace(
                ConnectionError=FakeConnectionError,
                Timeout=FakeTimeout,
                HTTPError=FakeHTTPError,
            )
            fake_requests.get = mock.Mock(return_value=Response(status_code))
            with mock.patch.dict(sys.modules, {"requests": fake_requests}):
                return sbv.fetch_tables("https://sbv.example/table", "fixture")

        hard_404 = fetched_http_failure(404)
        self.assertFalse(hard_404["transient_error"])
        self.assertEqual(hard_404["failure_kind"], "hard_http_error")
        self.assertEqual(hard_404["http_status"], 404)
        code, _, printed = self.run_refresh(
            {
                "official_checks": {
                    "money_supply_deposits": valid_money(),
                    "omo_latest": valid_omo(),
                }
            },
            [hard_404, valid_omo()],
        )
        self.assertEqual(code, 1)
        self.assertEqual(printed["official_refresh"], "error")

        for status_code in (429, 503):
            with self.subTest(status_code=status_code):
                retryable = fetched_http_failure(status_code)
                self.assertTrue(retryable["transient_error"])
                self.assertEqual(retryable["failure_kind"], "transient_http_error")
                self.assertEqual(retryable["http_status"], status_code)
                code, _, printed = self.run_refresh(
                    {
                        "official_checks": {
                            "money_supply_deposits": valid_money(),
                            "omo_latest": valid_omo(),
                        }
                    },
                    [retryable, valid_omo()],
                )
                self.assertEqual(code, 0)
                self.assertEqual(printed["official_refresh"], "warning")

    def test_fetch_classifies_post_http_parse_error_as_hard_failure(self) -> None:
        class Response:
            text = "<html><body>invalid table</body></html>"

            @staticmethod
            def raise_for_status() -> None:
                return None

        fake_requests = types.ModuleType("requests")
        fake_requests.get = mock.Mock(return_value=Response())
        with (
            mock.patch.dict(sys.modules, {"requests": fake_requests}),
            mock.patch.object(sbv.pd, "read_html", side_effect=ValueError("parse failed")),
        ):
            failure = sbv.fetch_tables("https://sbv.example/table", "fixture")

        self.assertFalse(failure["transient_error"])
        self.assertEqual(failure["failure_kind"], "content_parse_error")
        self.assertTrue(failure["http_succeeded"])

    def run_refresh(
        self,
        macro: dict[str, object],
        fetched: list[dict[str, object]],
        *,
        validate_existing: bool = False,
    ) -> tuple[int, dict[str, object], dict[str, object]]:
        config = {
            "official_sbv_sources": {
                "money_supply_deposits": "https://sbv.example/money",
                "omo": "https://sbv.example/omo",
            }
        }
        stored: dict[str, object] = {}

        def fake_load(path: Path, default: object) -> object:
            if path == sbv.MACRO:
                return copy.deepcopy(macro)
            if path == sbv.CONFIG:
                return copy.deepcopy(config)
            return copy.deepcopy(default)

        def fake_save(path: Path, value: object) -> bool:
            self.assertEqual(path, sbv.MACRO)
            stored.update(copy.deepcopy(value))
            return value != macro

        output = io.StringIO()
        fetch = mock.Mock(side_effect=[copy.deepcopy(node) for node in fetched])
        with (
            mock.patch.object(sbv, "load", side_effect=fake_load),
            mock.patch.object(sbv, "save_if_changed", side_effect=fake_save),
            mock.patch.object(sbv, "fetch_tables", fetch),
            contextlib.redirect_stdout(output),
        ):
            exit_code = sbv.main(validate_existing=validate_existing)

        printed = json.loads(output.getvalue())
        if validate_existing:
            fetch.assert_not_called()
        return exit_code, stored, printed

    def test_transient_failure_keeps_last_known_good_and_returns_warning(self) -> None:
        previous_money = valid_money()
        macro = {
            "sentinel": {"untouched": True},
            "official_checks": {
                "money_supply_deposits": copy.deepcopy(previous_money),
                "omo_latest": valid_omo(),
            },
        }

        code, stored, printed = self.run_refresh(
            macro,
            [transient_failure(), valid_omo()],
        )

        self.assertEqual(code, 0)
        self.assertEqual(printed["official_refresh"], "warning")
        self.assertEqual(stored["official_refresh"]["status"], "warning")
        kept = stored["official_checks"]["money_supply_deposits"]
        self.assertEqual(kept["tables"], previous_money["tables"])
        self.assertEqual(kept["source_date"], previous_money["source_date"])
        self.assertEqual(kept["status"], "ok")
        self.assertEqual(kept["refresh_status"], "stale")
        self.assertIn("last_refresh_error", kept)
        self.assertTrue(
            stored["official_refresh"]["datasets"]["money_supply_deposits"][
                "kept_last_known_good"
            ]
        )
        self.assertEqual(stored["official_validation"]["status"], "pass")
        self.assertEqual(stored["sentinel"], {"untouched": True})

    def test_successful_http_invalid_content_is_a_hard_failure(self) -> None:
        cases: dict[str, tuple[dict[str, object], str]] = {}

        missing_date = valid_money()
        missing_date["source_date"] = None
        cases["date"] = (missing_date, "date")

        missing_schema = valid_money()
        missing_schema["schema_fingerprint"] = None
        cases["schema"] = (missing_schema, "schema")

        missing_table = valid_money()
        missing_table["status"] = "empty"
        missing_table["tables"] = []
        cases["table"] = (missing_table, "table")

        invalid_number = valid_money()
        invalid_number["tables"][0]["rows"][0][2] = 499
        cases["numeric"] = (invalid_number, "numeric")

        for label, (candidate, failed_check) in cases.items():
            with self.subTest(label=label):
                code, stored, printed = self.run_refresh(
                    {
                        "official_checks": {
                            "money_supply_deposits": valid_money(),
                            "omo_latest": valid_omo(),
                        }
                    },
                    [candidate, valid_omo()],
                )

                self.assertEqual(code, 1)
                self.assertEqual(printed["official_refresh"], "error")
                validation = stored["official_validation"]["datasets"][
                    "money_supply_deposits"
                ]
                self.assertEqual(validation["status"], "fail")
                self.assertEqual(validation["checks"][failed_check]["status"], "fail")

    def test_validate_existing_only_updates_derived_validation(self) -> None:
        macro = {
            "sentinel": {"untouched": True},
            "official_checks": {
                "money_supply_deposits": valid_money(),
                "omo_latest": valid_omo(),
            },
            "official_validation": {"status": "old"},
            "official_refresh": {"status": "warning", "marker": "preserve"},
        }
        original_without_validation = copy.deepcopy(macro)
        original_without_validation.pop("official_validation")

        code, stored, printed = self.run_refresh(
            macro,
            [],
            validate_existing=True,
        )

        stored_without_validation = copy.deepcopy(stored)
        stored_without_validation.pop("official_validation")
        self.assertEqual(code, 0)
        self.assertEqual(printed["official_refresh"], "not_attempted")
        self.assertEqual(stored_without_validation, original_without_validation)
        self.assertEqual(stored["official_validation"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
