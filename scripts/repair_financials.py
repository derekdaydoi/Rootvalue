from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COMPANY_DIR = ROOT / "data" / "foundation" / "companies"
WATCHLIST = ROOT / "config" / "watchlist.json"
API_KEY_PRESENT = bool(os.getenv("VNSTOCK_API_KEY", "").strip())
RATE_SECONDS = 1.4 if API_KEY_PRESENT else 4.0


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def payload(df: pd.DataFrame) -> dict[str, Any]:
    safe = df.copy()
    if not isinstance(safe.index, pd.RangeIndex):
        safe = safe.reset_index()
    rows = []
    for row in safe.itertuples(index=False, name=None):
        out = []
        for value in row:
            try:
                if pd.isna(value):
                    out.append(None)
                    continue
            except Exception:
                pass
            if hasattr(value, "item"):
                try:
                    value = value.item()
                except Exception:
                    pass
            out.append(value if isinstance(value, (str, int, float, bool)) or value is None else str(value))
        rows.append(out)
    return {"columns": [str(c) for c in safe.columns], "rows": rows, "row_count": len(rows)}


def years(df: pd.DataFrame) -> list[int]:
    found = set()
    for col in df.columns:
        text = str(col)
        for y in range(2000, 2100):
            if str(y) in text:
                found.add(y)
    return sorted(found)


def call_balance_sheet(fun: Any, symbol: str) -> pd.DataFrame:
    attempts = []
    # Free Vnstock 4.x documentation supports both utility and symbol-bound syntax.
    try:
        fn = fun.equity.balance_sheet
        for kwargs in (
            {"symbol": symbol, "period": "year", "orient": "report"},
            {"symbol": symbol, "period": "year"},
        ):
            try:
                df = fn(**kwargs)
                if isinstance(df, pd.DataFrame) and not df.empty:
                    return df
            except Exception as exc:
                attempts.append(str(exc))
    except Exception as exc:
        attempts.append(str(exc))

    try:
        obj = fun.equity(symbol)
        fn = obj.balance_sheet
        for kwargs in (
            {"period": "year", "orient": "report"},
            {"period": "year"},
        ):
            try:
                df = fn(**kwargs)
                if isinstance(df, pd.DataFrame) and not df.empty:
                    return df
            except Exception as exc:
                attempts.append(str(exc))
    except Exception as exc:
        attempts.append(str(exc))

    raise RuntimeError("balance_sheet fallback returned empty; " + "; ".join(attempts[-4:]))


def main() -> None:
    from vnstock import Fundamental

    watch = load(WATCHLIST, {})
    symbols = [str(x).upper() for x in watch.get("fundamental_symbols", [])]
    fun = Fundamental()
    repaired = []
    failures = []

    for symbol in symbols:
        path = COMPANY_DIR / f"{symbol}.json"
        item = load(path, {})
        if not item:
            continue
        # Correct provenance for the community provider. Current free Unified UI routes financials through KBS.
        if item.get("provider") == "vnstock":
            mode = "authenticated" if API_KEY_PRESENT else "guest"
            item["source"] = f"KBS via Vnstock community ({mode})"
        annual_bs = item.get("reports", {}).get("annual", {}).get("balance_sheet", {})
        if annual_bs.get("data", {}).get("rows"):
            save(path, item)
            continue
        try:
            time.sleep(RATE_SECONDS)
            df = call_balance_sheet(fun, symbol)
            ys = years(df)
            item["reports"]["annual"]["balance_sheet"] = {"status": "ok", "years": ys, "data": payload(df), "fallback": "Vnstock community default dropna/orient"}
            merged = sorted(set(item.get("coverage", {}).get("annual_years", [])) | set(ys))
            item["coverage"]["annual_years"] = merged
            item["coverage"]["annual_periods"] = len(merged)
            minimum = int(item["coverage"].get("minimum_annual_periods", 8) or 8)
            item["coverage"]["minimum_met"] = len(merged) >= minimum
            item["status"] = "ready" if item["coverage"]["minimum_met"] else "partial"
            item["last_repair_at"] = datetime.now(timezone.utc).isoformat()
            repaired.append(symbol)
        except Exception as exc:
            item.setdefault("warnings", []).append(f"annual.balance_sheet fallback: {exc}")
            failures.append(f"{symbol}: {exc}")
        save(path, item)

    print(json.dumps({"repaired": repaired, "failures": failures}, ensure_ascii=False))


if __name__ == "__main__":
    main()
