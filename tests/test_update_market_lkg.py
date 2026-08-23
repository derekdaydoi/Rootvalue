from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import update_market  # noqa: E402


class MarketLastKnownGoodTests(unittest.TestCase):
    def test_last_attempt_timestamp_is_semantic_for_repeated_failures(self) -> None:
        first = {
            "generated_at": "2026-08-22T00:00:00+00:00",
            "status": "stale",
            "last_error": "same provider failure",
            "last_attempt_at": "2026-08-22T01:00:00+00:00",
        }
        regenerated = {**first, "generated_at": "2026-08-23T00:00:00+00:00"}
        retried = {
            **regenerated,
            "last_attempt_at": "2026-08-23T01:00:00+00:00",
        }

        self.assertEqual(update_market.semantic_payload(first), update_market.semantic_payload(regenerated))
        self.assertNotEqual(update_market.semantic_payload(first), update_market.semantic_payload(retried))

    def test_partial_fetch_keeps_full_57_row_snapshot_and_picks(self) -> None:
        symbols = [f"S{i:02d}" for i in range(1, 58)]
        config = {
            "symbols": [{"symbol": symbol, "sector": "Test"} for symbol in symbols],
            "pick_limit": 20,
        }
        rows = [
            {
                "symbol": symbol,
                "sector": "Test",
                "as_of": "2026-08-22",
                "rank_current": index,
                "state": "Neutral",
            }
            for index, symbol in enumerate(symbols, start=1)
        ]
        previous = {
            "schema_version": "1.1.0",
            "generated_at": "2026-08-22T01:00:00+00:00",
            "status": "ok",
            "as_of": "2026-08-22",
            "index": {"as_of": "2026-08-22"},
            "rows": rows,
            "picks": rows[:20],
            "selection_by_sector": {"Test": rows[:5]},
            "selection_status": "ready",
            "health": {"errors": [], "warnings": []},
        }
        attempted = {
            "status": "partial",
            "as_of": "2026-08-23",
            "index": {"as_of": "2026-08-23"},
            "rows": rows[:-1],
        }

        stored: dict[str, object] = {}

        def partial_fetch(_config: dict[str, object], warnings: list[str]) -> dict[str, object]:
            warnings.append("market:S57:provider timeout")
            return attempted

        def fake_read(path: Path, default: object) -> object:
            if path == update_market.CONFIG:
                return config
            return stored or previous

        def fake_save(_path: Path, payload: object) -> bool:
            stored.update(json.loads(json.dumps(payload)))
            return True

        with (
            mock.patch.object(update_market, "read_json", side_effect=fake_read),
            mock.patch.object(update_market, "save", side_effect=fake_save),
            mock.patch.object(update_market, "fetch_market", side_effect=partial_fetch),
            redirect_stdout(io.StringIO()),
        ):
            update_market.main()

        self.assertEqual(stored["status"], "stale")
        self.assertEqual(stored["generated_at"], previous["generated_at"])
        self.assertEqual(stored["rows"], previous["rows"])
        self.assertEqual(stored["picks"], previous["picks"])
        self.assertEqual(stored["selection_by_sector"], previous["selection_by_sector"])
        attempt = stored["last_refresh_attempt"]
        self.assertEqual(attempt["coverage"]["observed"], 56)
        self.assertEqual(attempt["coverage"]["expected"], 57)
        self.assertEqual(attempt["missing_symbols"], ["S57"])
        self.assertEqual(attempt["errors"], ["market:S57:provider timeout"])
        self.assertIn("kept last-known-good snapshot", stored["last_error"])


if __name__ == "__main__":
    unittest.main()
