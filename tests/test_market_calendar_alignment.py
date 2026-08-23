from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import update_data  # noqa: E402


def normalized_frame(dates: pd.DatetimeIndex, closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "close": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "volume": [1_000 + index * 10 for index in range(len(closes))],
        }
    )


def provider_frame(dates: pd.DatetimeIndex, closes: list[float]) -> pd.DataFrame:
    frame = normalized_frame(dates, closes)
    return frame.rename(columns={"date": "time"})


class MarketCalendarAlignmentTests(unittest.TestCase):
    def test_metrics_use_common_dates_when_internal_sessions_differ(self) -> None:
        dates = pd.bdate_range("2026-06-01", periods=36)
        index_closes = [100.0 + index * index / 10 for index in range(len(dates))]
        missing_internal = 12
        stock_dates = dates.delete(missing_internal)
        stock_closes = [50.0 + index * 1.5 for index in range(len(stock_dates))]
        stock = normalized_frame(stock_dates, stock_closes)
        benchmark = normalized_frame(dates, index_closes)

        metric = update_data.market_metrics(stock, benchmark)
        aligned_index_closes = [
            value for index, value in enumerate(index_closes) if index != missing_internal
        ]
        stock_20d = stock_closes[-1] / stock_closes[-21] - 1
        index_20d = aligned_index_closes[-1] / aligned_index_closes[-21] - 1

        self.assertEqual(metric["as_of"], dates[-1].date().isoformat())
        self.assertAlmostEqual(metric["return_1d"], stock_closes[-1] / stock_closes[-2] - 1)
        self.assertAlmostEqual(metric["return_20d"], stock_20d)
        self.assertAlmostEqual(metric["rs_20d_vs_vnindex"], stock_20d - index_20d)

    def test_fetch_excludes_ticker_missing_latest_index_session(self) -> None:
        dates = pd.bdate_range("2026-06-01", periods=36)
        index_closes = [1_000.0 + index * 2 for index in range(len(dates))]
        live_closes = [100.0 + index for index in range(len(dates) - 1)]
        live_dates = dates.delete(10)
        halted_dates = dates[:-1]
        halted_closes = [80.0 + index for index in range(len(halted_dates))]
        frames = {
            "LIVE": provider_frame(live_dates, live_closes),
            "HALT": provider_frame(halted_dates, halted_closes),
        }
        fake_vnstock = types.ModuleType("vnstock")
        fake_vnstock.Market = lambda: object()
        warnings: list[str] = []
        config = {
            "symbols": [
                {"symbol": "LIVE", "sector": "Test"},
                {"symbol": "HALT", "sector": "Test"},
            ]
        }

        with (
            mock.patch.dict(sys.modules, {"vnstock": fake_vnstock}),
            mock.patch.object(update_data, "provider_call", side_effect=lambda fn: fn()),
            mock.patch.object(
                update_data,
                "market_index_ohlcv",
                return_value=provider_frame(dates, index_closes),
            ),
            mock.patch.object(
                update_data,
                "market_equity_ohlcv",
                side_effect=lambda _market, symbol, _start, _end: frames[symbol],
            ),
        ):
            market = update_data.fetch_market(config, warnings)

        self.assertEqual(market["status"], "partial")
        self.assertEqual(market["as_of"], dates[-1].date().isoformat())
        self.assertEqual([row["symbol"] for row in market["rows"]], ["LIVE"])
        self.assertEqual(market["rows"][0]["rank_current"], 1)
        self.assertTrue(
            any(
                warning.startswith("market:HALT:")
                and "does not match VNINDEX snapshot date" in warning
                for warning in warnings
            )
        )


if __name__ == "__main__":
    unittest.main()
