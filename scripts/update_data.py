from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "watchlist.json"
OUT_PATH = ROOT / "data" / "rootvalue.json"
SCHEMA_VERSION = "1.1.0"
UTC_NOW = datetime.now(timezone.utc)
TODAY = UTC_NOW.date()
HAS_VNSTOCK_KEY = bool(os.getenv("VNSTOCK_API_KEY", "").strip())

# Vnstock guest mode can stop the entire process when its rate ceiling is reached.
# A generous interval is intentional: correctness > refresh speed for this research tool.
# With a free Community API key, the interval can be reduced safely.
RATE_SECONDS = 1.5 if HAS_VNSTOCK_KEY else 7.0
_LAST_CALL = 0.0


def provider_call(fn: Callable[[], Any]) -> Any:
    global _LAST_CALL
    elapsed = time.monotonic() - _LAST_CALL
    if _LAST_CALL and elapsed < RATE_SECONDS:
        time.sleep(RATE_SECONDS - elapsed)
    result = fn()
    _LAST_CALL = time.monotonic()
    return result


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def finite(value: Any) -> float | None:
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        x = float(value)
        return x if math.isfinite(x) else None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, pd.Timedelta):
        return str(value)
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def df_payload(df: pd.DataFrame | None, max_rows: int = 260) -> dict[str, Any]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return {"columns": [], "rows": []}
    safe = df.copy()
    if not isinstance(safe.index, pd.RangeIndex):
        safe = safe.reset_index()
    safe = safe.head(max_rows)
    return {
        "columns": [str(c) for c in safe.columns],
        "rows": [[jsonable(v) for v in row] for row in safe.itertuples(index=False, name=None)],
    }


def annual_period_count(payload: dict[str, Any]) -> int:
    columns = [str(c) for c in payload.get("columns", [])]
    ignore = {"item", "item_en", "unit", "ticker", "symbol", "index"}
    periods = [c for c in columns if c.lower() not in ignore]
    year_like = [c for c in periods if any(ch.isdigit() for ch in c)]
    return len(year_like) if year_like else len(periods)


def pick_column(df: pd.DataFrame, names: list[str]) -> str | None:
    lookup = {str(c).strip().lower(): c for c in df.columns}
    for name in names:
        if name.lower() in lookup:
            return lookup[name.lower()]
    return None


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValueError("empty OHLCV")
    date_col = pick_column(df, ["time", "date", "trading_date", "datetime"])
    close_col = pick_column(df, ["close", "close_price", "price"])
    high_col = pick_column(df, ["high", "high_price"])
    low_col = pick_column(df, ["low", "low_price"])
    volume_col = pick_column(df, ["volume", "total_volume", "match_volume"])
    if not all([date_col, close_col, high_col, low_col, volume_col]):
        raise ValueError(f"unexpected OHLCV schema: {list(df.columns)}")
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col], errors="coerce"),
            "close": pd.to_numeric(df[close_col], errors="coerce"),
            "high": pd.to_numeric(df[high_col], errors="coerce"),
            "low": pd.to_numeric(df[low_col], errors="coerce"),
            "volume": pd.to_numeric(df[volume_col], errors="coerce"),
        }
    )
    out = out.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates("date")
    if len(out) < 25:
        raise ValueError(f"insufficient daily bars: {len(out)}")
    return out.reset_index(drop=True)


def ending_return(frame: pd.DataFrame, window: int, offset: int = 0) -> float | None:
    end_i = len(frame) - 1 - offset
    start_i = end_i - window
    if start_i < 0 or end_i < 0:
        return None
    start = finite(frame.iloc[start_i]["close"])
    end = finite(frame.iloc[end_i]["close"])
    if start in (None, 0) or end is None:
        return None
    return end / start - 1


def market_metrics(frame: pd.DataFrame, index_frame: pd.DataFrame | None = None) -> dict[str, Any]:
    close = finite(frame.iloc[-1]["close"])
    prev = finite(frame.iloc[-2]["close"])
    ret_1d = None if close is None or prev in (None, 0) else close / prev - 1
    ret_20d = ending_return(frame, 20)
    ret_20d_prev = ending_return(frame, 20, offset=5)
    idx_ret = ending_return(index_frame, 20) if index_frame is not None else None
    idx_ret_prev = ending_return(index_frame, 20, offset=5) if index_frame is not None else None
    rs_now = None if ret_20d is None or idx_ret is None else ret_20d - idx_ret
    rs_prev = None if ret_20d_prev is None or idx_ret_prev is None else ret_20d_prev - idx_ret_prev
    tail20 = frame.tail(20)
    low20 = finite(tail20["low"].min())
    high20 = finite(tail20["high"].max())
    position = None
    if close is not None and low20 is not None and high20 is not None and high20 > low20:
        position = (close - low20) / (high20 - low20)
    vol20 = finite(tail20["volume"].mean())
    vol5 = finite(frame.tail(5)["volume"].mean())
    participation = None if vol20 in (None, 0) or vol5 is None else vol5 / vol20
    return {
        "as_of": frame.iloc[-1]["date"].date().isoformat(),
        "close": close,
        "return_1d": ret_1d,
        "return_20d": ret_20d,
        "rs_20d_vs_vnindex": rs_now,
        "rs_20d_vs_vnindex_5d_ago": rs_prev,
        "volume_participation_5d_vs_20d": participation,
        "range_position_20d": position,
        "sparkline": [finite(v) for v in frame.tail(30)["close"].tolist()],
    }


def preserve_previous(previous: dict[str, Any], key: str, error: str) -> dict[str, Any]:
    old = previous.get(key)
    if isinstance(old, dict) and old.get("status") in {"ok", "partial", "stale"}:
        kept = dict(old)
        kept["status"] = "stale"
        kept["last_error"] = error
        return kept
    return {"status": "error", "as_of": None, "last_error": error}


def market_index_ohlcv(market: Any, symbol: str, start: str, end: str) -> pd.DataFrame:
    try:
        return market.index.ohlcv(symbol=symbol, start=start, end=end, interval="1D")
    except (AttributeError, TypeError):
        return market.index(symbol).ohlcv(start=start, end=end, interval="1D")


def market_equity_ohlcv(market: Any, symbol: str, start: str, end: str) -> pd.DataFrame:
    try:
        return market.equity.ohlcv(symbol=symbol, start=start, end=end, interval="1D")
    except (AttributeError, TypeError):
        return market.equity(symbol).ohlcv(start=start, end=end, interval="1D")


def fetch_market(config: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    from vnstock import Market

    market = Market()
    start = (TODAY - timedelta(days=190)).isoformat()
    end = (TODAY + timedelta(days=1)).isoformat()
    index_df = normalize_ohlcv(provider_call(lambda: market_index_ohlcv(market, "VNINDEX", start, end)))
    index_summary = market_metrics(index_df)

    rows: list[dict[str, Any]] = []
    for item in config["symbols"]:
        symbol = item["symbol"].upper()
        try:
            frame = normalize_ohlcv(provider_call(lambda s=symbol: market_equity_ohlcv(market, s, start, end)))
            metric = market_metrics(frame, index_df)
            metric.update({"symbol": symbol, "sector": item.get("sector", "")})
            rows.append(metric)
        except Exception as exc:
            warnings.append(f"market:{symbol}:{exc}")

    current = sorted([r for r in rows if r.get("rs_20d_vs_vnindex") is not None], key=lambda r: r["rs_20d_vs_vnindex"], reverse=True)
    prior = sorted([r for r in rows if r.get("rs_20d_vs_vnindex_5d_ago") is not None], key=lambda r: r["rs_20d_vs_vnindex_5d_ago"], reverse=True)
    cur_rank = {r["symbol"]: i + 1 for i, r in enumerate(current)}
    old_rank = {r["symbol"]: i + 1 for i, r in enumerate(prior)}
    lead_cut = max(2, math.ceil(max(len(current), 1) * 0.25))
    for row in rows:
        cr, pr = cur_rank.get(row["symbol"]), old_rank.get(row["symbol"])
        delta = None if cr is None or pr is None else pr - cr
        row.update({"rank_current": cr, "rank_5d_ago": pr, "rank_delta": delta})
        if cr is not None and cr <= lead_cut:
            row["state"] = "Leading"
        elif delta is not None and delta >= 2:
            row["state"] = "Improving"
        elif delta is not None and delta <= -2:
            row["state"] = "Weakening"
        else:
            row["state"] = "Neutral"

    return {
        "status": "ok" if len(rows) == len(config["symbols"]) else "partial",
        "as_of": index_summary.get("as_of"),
        "source": "Vnstock community / Market Unified UI",
        "universe_note": config.get("market_universe_note"),
        "methodology": {
            "rs_20d": "stock 20-session return minus VNINDEX 20-session return",
            "rank_current": "cross-sectional rank inside the configured V1 watchlist only",
            "rank_delta": "rank 5 sessions ago minus current rank; positive means improving",
            "participation": "5-session average volume / 20-session average volume; volume proxy, not proof of cash transfer",
            "range_position": "(close - 20D low) / (20D high - 20D low)",
        },
        "index": index_summary,
        "rows": rows,
    }


def fetch_retail_macro(warnings: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    from vnstock import Retail

    metrics: list[dict[str, Any]] = []
    retail = Retail()
    try:
        fx = provider_call(retail.exchange_rate)
        if isinstance(fx, pd.DataFrame) and not fx.empty and "currency" in fx.columns:
            usd = fx[fx["currency"].astype(str).str.upper() == "USD"]
            if not usd.empty:
                row = usd.iloc[0]
                metrics.append({"key": "usd_vcb_sell", "label": "USD/VND VCB", "value": finite(row.get("sell")), "unit": "VND/USD", "as_of": jsonable(row.get("time")), "source": "Vietcombank via Vnstock Retail", "interpretation": "fx_proxy"})
    except Exception as exc:
        warnings.append(f"macro:fx:{exc}")
    try:
        gold = provider_call(lambda: retail.gold(source="sjc"))
        if isinstance(gold, pd.DataFrame) and not gold.empty:
            row = gold.iloc[0]
            metrics.append({"key": "gold_sjc_sell", "label": "SJC", "value": finite(row.get("sell")), "unit": "provider unit", "as_of": jsonable(row.get("time")), "source": "SJC via Vnstock Retail", "interpretation": "defensive_asset_proxy"})
    except Exception as exc:
        warnings.append(f"macro:gold:{exc}")
    return metrics, ["Vietcombank + SJC via Vnstock Retail community"]


def fetch_optional_sponsor_macro(warnings: list[str]) -> tuple[dict[str, Any], list[str]]:
    datasets: dict[str, Any] = {}
    try:
        from vnstock_data import Macro
    except Exception:
        warnings.append("macro:sponsor-package-not-installed")
        return datasets, []

    macro = Macro()
    calls: dict[str, Callable[[], pd.DataFrame]] = {
        "interbank_rate": lambda: macro.currency().interbank_rate(period="day", length=90),
        "policy_rate": lambda: macro.currency().policy_rate(),
        "omo": lambda: macro.currency().omo(),
        "credit": lambda: macro.economy().credit(period="month", length=24),
        "money_supply": lambda: macro.economy().money_supply(period="month", length=24),
        "cpi": lambda: macro.economy().cpi(period="month", length=24),
        "trade": lambda: macro.economy().import_export(period="month", length=24),
    }
    for key, fn in calls.items():
        try:
            datasets[key] = df_payload(provider_call(fn), 120)
        except Exception as exc:
            warnings.append(f"macro:{key}:{exc}")
    return datasets, (["Vnstock Data sponsor Macro Unified UI"] if datasets else [])


def fetch_macro(warnings: list[str]) -> dict[str, Any]:
    metrics, sources = fetch_retail_macro(warnings)
    datasets, sponsor_sources = fetch_optional_sponsor_macro(warnings)
    sources.extend(sponsor_sources)
    missing = ["SBV central exchange rate", "Interbank O/N", "OMO outstanding/rate", "SBV bills outstanding", "Treasury liquidity proxy", "Credit growth", "Deposit growth"]
    if datasets.get("interbank_rate", {}).get("rows") and "Interbank O/N" in missing:
        missing.remove("Interbank O/N")
    if datasets.get("omo", {}).get("rows") and "OMO outstanding/rate" in missing:
        missing.remove("OMO outstanding/rate")
    if datasets.get("credit", {}).get("rows") and "Credit growth" in missing:
        missing.remove("Credit growth")
    return {
        "status": "partial",
        "as_of": UTC_NOW.isoformat(),
        "source": sources,
        "metrics": metrics,
        "datasets": datasets,
        "missing_core": missing,
        "reaction_engine_status": "framework_only" if missing else "data_ready",
    }


def fundamental_report(fundamental: Any, symbol: str, report: str) -> pd.DataFrame:
    proxy = fundamental.equity
    property_methods = {
        "balance_sheet": "balance_sheet",
        "income_statement": "income_statement",
        "cash_flow": "cash_flow",
        "ratio": "ratios",
    }
    method = property_methods[report]
    kwargs = {"period": "year", "orient": "report"}
    try:
        return getattr(proxy, method)(symbol=symbol, **kwargs)
    except (AttributeError, TypeError):
        obj = fundamental.equity(symbol)
        fallback = "ratio" if report == "ratio" and not hasattr(obj, "ratios") else method
        try:
            return getattr(obj, fallback)(**kwargs)
        except TypeError:
            return getattr(obj, fallback)(period="year")


def fetch_companies(config: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    from vnstock import Fundamental

    fundamental = Fundamental()
    companies: dict[str, Any] = {}
    for symbol in config.get("fundamental_symbols", []):
        reports: dict[str, Any] = {}
        counts: list[int] = []
        for name in ("balance_sheet", "income_statement", "cash_flow", "ratio"):
            try:
                payload = df_payload(provider_call(lambda s=symbol, n=name: fundamental_report(fundamental, s, n)))
                reports[name] = payload
                c = annual_period_count(payload)
                if c:
                    counts.append(c)
            except Exception as exc:
                warnings.append(f"fundamental:{symbol}:{name}:{exc}")
                reports[name] = {"columns": [], "rows": [], "error": str(exc)}
        annual_periods = max(counts) if counts else 0
        companies[symbol] = {
            "symbol": symbol,
            "period": "year",
            "reports": reports,
            "history": {
                "annual_periods": annual_periods,
                "target_years": 8,
                "minimum_years": 5,
                "meets_minimum": annual_periods >= 5,
                "access_mode": "community_key" if HAS_VNSTOCK_KEY else "guest",
            },
        }

    ok = sum(1 for c in companies.values() for r in c["reports"].values() if r.get("rows"))
    total = max(len(companies) * 4, 1)
    status = "ok" if ok == total else ("partial" if ok else "error")
    history_periods = [c["history"]["annual_periods"] for c in companies.values() if c["history"]["annual_periods"]]
    return {
        "status": status,
        "as_of": UTC_NOW.isoformat(),
        "source": "Vnstock community / Fundamental Unified UI",
        "access_mode": "community_key" if HAS_VNSTOCK_KEY else "guest",
        "history_target_years": 8,
        "history_min_periods_observed": min(history_periods) if history_periods else 0,
        "history_max_periods_observed": max(history_periods) if history_periods else 0,
        "limitations": "Vnstock community guest mode exposes up to 4 financial periods; authenticated Community access can expose up to 8 periods. Rootvalue reports actual coverage per company.",
        "rows": companies,
    }


def main() -> None:
    config = read_json(CONFIG_PATH, {})
    previous = read_json(OUT_PATH, {})
    warnings: list[str] = []
    errors: list[str] = []
    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": UTC_NOW.isoformat(),
        "pipeline_status": "partial",
        "meta": {
            "principle": "Missing data stays missing. No fabricated financial or macro values.",
            "market_universe": "V1 validation watchlist",
            "python": os.sys.version.split()[0],
            "vnstock_auth": "community_key" if HAS_VNSTOCK_KEY else "guest",
            "provider_interval_seconds": RATE_SECONDS,
        },
    }

    # Fundamentals first because long-history company analysis is the primary V1 requirement.
    for key, fn in (
        ("companies", lambda: fetch_companies(config, warnings)),
        ("market", lambda: fetch_market(config, warnings)),
        ("macro", lambda: fetch_macro(warnings)),
    ):
        try:
            snapshot[key] = fn()
        except Exception as exc:
            errors.append(f"{key}:{exc}")
            snapshot[key] = preserve_previous(previous, key, str(exc))

    statuses = [snapshot.get(k, {}).get("status") for k in ("market", "macro", "companies")]
    snapshot["pipeline_status"] = "ok" if all(s == "ok" for s in statuses) else ("partial" if any(s in {"ok", "partial", "stale"} for s in statuses) else "error")
    snapshot["health"] = {"errors": errors, "warnings": warnings}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(f"Rootvalue snapshot: status={snapshot['pipeline_status']} warnings={len(warnings)} errors={len(errors)} auth={'key' if HAS_VNSTOCK_KEY else 'guest'}")


if __name__ == "__main__":
    main()
