from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_company_dashboard as dashboard  # noqa: E402


def table(*rows: dict[str, object]) -> dict[str, object]:
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return {
        "columns": columns,
        "rows": [[row.get(column) for column in columns] for row in rows],
    }


class SelectorTests(unittest.TestCase):
    def test_exact_provider_id_wins_over_broader_text_match(self) -> None:
        rows = [
            {
                "item_id": "cash_flow_from_operating_before_changes_in_operating_assets_and_liabilities",
                "item": "Cash flow from operating activities before working-capital changes",
                "2025": 29,
            },
            {
                "item_id": "operating_cash_flow",
                "item": "Net cash flow from operating activities",
                "2025": 55,
            },
        ]

        selected = dashboard.choose_row(
            rows,
            ids=["operating_cash_flow"],
            contains=["cash flow from operating"],
            prefer=["before working-capital changes"],
        )

        self.assertIs(selected, rows[1])

    def test_preference_term_cannot_create_a_candidate(self) -> None:
        rows = [{"item_id": "unrelated", "item": "Parent company result", "2025": 1}]

        selected = dashboard.choose_row(
            rows,
            ids=["operating_cash_flow"],
            contains=["net cash flow from operating"],
            prefer=["parent company"],
        )

        self.assertIsNone(selected)


class DerivationTests(unittest.TestCase):
    def test_provider_capex_id_produces_signed_fcf(self) -> None:
        reports = {
            "cash_flow": {
                "data": table(
                    {
                        "item_id": "operating_cash_flow",
                        "item": "Net operating cash flow",
                        "2024": 100,
                        "2025": 120,
                    },
                    {
                        "item_id": "payment_for_fixed_assets_constructions_and_other_long_term_assets",
                        "item": "Payments for fixed assets",
                        "2024": -30,
                        "2025": -50,
                    },
                )
            }
        }

        result = dashboard.build_frequency(reports)

        self.assertEqual(
            result["series"]["fcf"],
            [{"period": "2024", "value": 70.0}, {"period": "2025", "value": 70.0}],
        )

    def test_missing_debt_or_asset_component_stays_missing(self) -> None:
        reports = {
            "balance_sheet": {
                "data": table(
                    {"item_id": "total_assets", "item": "Total assets", "2025": 100},
                    {"item_id": "cash", "item": "Cash", "2025": 20},
                    {"item_id": "short_term_receivables", "item": "Receivables", "2025": 10},
                    {"item_id": "inventories", "item": "Inventories", "2025": 15},
                    {"item_id": "fixed_assets", "item": "Fixed assets", "2025": 30},
                    {"item_id": "short_term_debt", "item": "Short-term debt", "2025": 12},
                )
            }
        }

        result = dashboard.build_frequency(reports)

        self.assertEqual(result["series"]["total_debt"], [])
        self.assertFalse(result["reconciliation"]["total_debt_components_complete"])
        self.assertEqual(result["asset_mix"]["other"], [])
        self.assertEqual(result["reconciliation"]["asset_mix"][0]["status"], "incomplete")
        self.assertIn("cip", result["reconciliation"]["asset_mix"][0]["missing_components"])

    def test_published_source_rows_drive_cfo_and_capex(self) -> None:
        tcb = json.loads(
            (ROOT / "data" / "foundation" / "companies" / "TCB.json").read_text(encoding="utf-8")
        )
        annual = tcb["reports"]["annual"]
        result = dashboard.build_frequency(annual)
        cashflow_rows = dashboard.report_rows(annual["cash_flow"]["data"])
        exact_cfo = dashboard.row_series(
            dashboard.choose_row(cashflow_rows, ids=["operating_cash_flow"])
        )

        self.assertTrue(exact_cfo, "TCB snapshot must retain the authoritative operating_cash_flow row")
        self.assertEqual(result["series"]["cfo"], exact_cfo)

        for symbol in ("FPT", "GMD", "HPG", "MWG", "VNM"):
            company = json.loads(
                (ROOT / "data" / "foundation" / "companies" / f"{symbol}.json").read_text(
                    encoding="utf-8"
                )
            )
            built = dashboard.build_frequency(company["reports"]["annual"])
            self.assertTrue(built["series"]["capex"], f"{symbol} CAPEX must not be dropped")
            self.assertTrue(built["series"]["fcf"], f"{symbol} FCF must not be dropped")


if __name__ == "__main__":
    unittest.main()
