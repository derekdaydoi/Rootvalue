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


def call_unified_balance_sheet(fun: Any, symbol: str, period: str) -> pd.DataFrame:
    errors: list[str] = []
    try:
        obj = fun.equity(symbol)
        fn = obj.balance_sheet
        for kwargs in (
            {"period": period, "orient": "report", "dropna": False},
            {"period": period, "orient": "report"},
            {"period": period, "dropna": False},
            {"period": period},
        ):
            try:
                df = fn(**kwargs)
                if isinstance(df, pd.DataFrame) and not df.empty:
                    return df
            except Exception as exc:
                errors.append(str(exc))
    except Exception as exc:
        errors.append(str(exc))
    raise RuntimeError("Unified UI empty: " + "; ".join(errors[-4:]))


def call_legacy_balance_sheet(symbol: str, period: str) -> tuple[pd.DataFrame, str]:
    # Vnstock's official v4 documentation still exposes the legacy Finance facade.
    # Keep it only as a resilience fallback when Unified UI returns an empty balance sheet.
    errors: list[str] = []
    try:
        from vnstock import Finance  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"Finance import unavailable: {exc}")

    for source in ("KBS", "VCI"):
        try:
            finance = Finance(symbol=symbol, source=source)
            fn = finance.balance_sheet
            for kwargs in (
                {"period": period, "lang": "vi", "dropna": False},
                {"period": period, "lang": "vi"},
                {"period": period},
            ):
                try:
                    df = fn(**kwargs)
                    if isinstance(df, pd.DataFrame) and not df.empty:
                        return df, source
                except Exception as exc:
                    errors.append(f"{source}:{exc}")
        except Exception as exc:
            errors.append(f"{source}:{exc}")
    raise RuntimeError("Legacy Finance empty: " + "; ".join(errors[-6:]))


def repair_balance_sheet(fun: Any, symbol: str, period: str) -> tuple[pd.DataFrame, str]:
    try:
        return call_unified_balance_sheet(fun, symbol, period), "Unified UI"
    except Exception as first:
        try:
            df, source = call_legacy_balance_sheet(symbol, period)
            return df, f"Legacy Finance/{source}"
        except Exception as second:
            raise RuntimeError(f"{first}; {second}")


def main() -> None:
    from vnstock import Fundamental

    watch = load(WATCHLIST, {})
    symbols = [str(x).upper() for x in watch.get("fundamental_symbols", [])]
    fun = Fundamental()
    repaired: list[str] = []
    failures: list[str] = []

    for symbol in symbols:
        path = COMPANY_DIR / f"{symbol}.json"
        item = load(path, {})
        if not item:
            continue
        if item.get("provider") == "vnstock":
            mode = "authenticated" if API_KEY_PRESENT else "guest"
            item["source"] = f"KBS/VCI via Vnstock community ({mode})"

        for bucket, period in (("annual", "year"), ("quarterly", "quarter")):
            bs = item.get("reports", {}).get(bucket, {}).get("balance_sheet", {})
            if bs.get("data", {}).get("rows"):
                continue
            try:
                time.sleep(RATE_SECONDS)
                df, fallback = repair_balance_sheet(fun, symbol, period)
                ys = years(df)
                item["reports"][bucket]["balance_sheet"] = {
                    "status": "ok",
                    "years": ys,
                    "data": payload(df),
                    "fallback": fallback,
                }
                if bucket == "annual":
                    merged = sorted(set(item.get("coverage", {}).get("annual_years", [])) | set(ys))
                    item["coverage"]["annual_years"] = merged
                    item["coverage"]["annual_periods"] = len(merged)
                    minimum = int(item["coverage"].get("minimum_annual_periods", 8) or 8)
                    item["coverage"]["minimum_met"] = len(merged) >= minimum
                    item["status"] = "ready" if item["coverage"]["minimum_met"] else "partial"
                else:
                    merged_q = sorted(set(item.get("coverage", {}).get("quarterly_years", [])) | set(ys))
                    item["coverage"]["quarterly_years"] = merged_q
                item["last_repair_at"] = datetime.now(timezone.utc).isoformat()
                repaired.append(f"{symbol}:{bucket}:{fallback}")
            except Exception as exc:
                message = f"{bucket}.balance_sheet fallback: {exc}"
                warnings = item.setdefault("warnings", [])
                if message not in warnings:
                    warnings.append(message)
                failures.append(f"{symbol}:{bucket}: {exc}")
        save(path, item)

    print(json.dumps({"repaired": repaired, "failures": failures}, ensure_ascii=False))


if __name__ == "__main__":
    main()
