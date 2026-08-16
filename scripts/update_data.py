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
SCHEMA_VERSION = "1.0.0"
UTC_NOW = datetime.now(timezone.utc)
TODAY = UTC_NOW.date()


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
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        x = float(value)
        return x if math.isfinite(x) else None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (pd.Timedelta,)):
        return str(value)
    if pd.isna(value):
        return None
    return str(value)


def df_payload(df: pd.DataFrame | None, max_rows: int = 160) -> dict[str, Any]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return {"columns": [], "rows": []}
    safe = df.copy().head(max_rows)
    columns = [str(c) for c in safe.columns]
    rows = []
    for row in safe.itertuples(index=False, name=None):
        rows.append([jsonable(v) for v in row])
    return {"columns": columns, "rows": rows}


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
    index_ret_20d = ending_return(index_frame, 20) if index_frame is not None else None
    index_ret_20d_prev = ending_return(index_frame, 20, offset=5) if index_frame is not None else None
    rs_20d = None if ret_20d is None or index_ret_20d is None else ret_20d - index_ret_20d
    rs_20d_prev = None if ret_20d_prev is None or index_ret_20d_prev is None else ret_20d_prev - index_ret_20d_prev
    tail20 = frame.tail(20)
    low20 = finite(tail20["low"].min())
    high20 = finite(tail20["high"].max())
    range_pos = None
    if close is not None and low20 is not None and high20 is not None and high20 > low20:
        range_pos = (close - low20) / (high20 - low20)
    vol20 = finite(tail20["volume"].mean())
    vol5 = finite(frame.tail(5)["volume"].mean())
    participation = None if vol20 in (None, 0) or vol5 is None else vol5 / vol20
    return {
        "as_of": frame.iloc[-1]["date"].date().isoformat(),
        "close": close,
        "return_1d": ret_1d,
        "return_20d": ret_20d,
        "rs_20d_vs_vnindex": rs_20d,
        "rs_20d_vs_vnindex_5d_ago": rs_20d_prev,
        "volume_participation_5d_vs_20d": participation,
        "range_position_20d": range_pos,
        "sparkline": [finite(v) for v in frame.tail(30)["close"].tolist()],
    }


def latest_row(df: pd.DataFrame, column: str, value: str) -> pd.Series | None:
    if df is None or df.empty or column not in df.columns:
        return None
    match = df[df[column].astype(str).str.upper() == value.upper()]
    return match.iloc[0] if not match.empty else None


def preserve_previous(previous: dict[str, Any], key: str, error: str) -> dict[str, Any]:
    old = previous.get(key)
    if isinstance(old, dict) and old.get("status") in {"ok", "partial", "stale"}:
        kept = dict(old)
        kept["status"] = "stale"
        kept["last_error"] = error
        return kept
    return {"status": "error", "as_of": None, "last_error": error}


def fetch_market(config: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    from vnstock.ui import Market

    market = Market()
    start = (TODAY - timedelta(days=170)).isoformat()
    end = (TODAY + timedelta(days=1)).isoformat()
    index_df = normalize_ohlcv(market.index("VNINDEX").ohlcv(start=start, end=end, interval="1D"))
    index_summary = market_metrics(index_df)

    rows: list[dict[str, Any]] = []
    for item in config["symbols"]:
        symbol = item["symbol"].upper()
        try:
            frame = normalize_ohlcv(market.equity(symbol).ohlcv(start=start, end=end, interval="1D"))
            metric = market_metrics(frame, index_df)
            metric.update({"symbol": symbol, "sector": item.get("sector", "")})
            rows.append(metric)
        except Exception as exc:
            warnings.append(f"market {symbol}: {exc}")

    current = sorted([r for r in rows if r.get("rs_20d_vs_vnindex") is not None], key=lambda r: r["rs_20d_vs_vnindex"], reverse=True)
    previous_rank = sorted([r for r in rows if r.get("rs_20d_vs_vnindex_5d_ago") is not None], key=lambda r: r["rs_20d_vs_vnindex_5d_ago"], reverse=True)
    cur_rank = {r["symbol"]: i + 1 for i, r in enumerate(current)}
    old_rank = {r["symbol"]: i + 1 for i, r in enumerate(previous_rank)}
    n = max(len(current), 1)
    lead_cut = max(2, math.ceil(n * 0.25))
    for row in rows:
        cr = cur_rank.get(row["symbol"])
        pr = old_rank.get(row["symbol"])
        delta = None if cr is None or pr is None else pr - cr
        row["rank_current"] = cr
        row["rank_5d_ago"] = pr
        row["rank_delta"] = delta
        if cr is not None and cr <= lead_cut:
            state = "Leading"
        elif delta is not None and delta >= 2:
            state = "Improving"
        elif delta is not None and delta <= -2:
            state = "Weakening"
        else:
            state = "Neutral"
        row["state"] = state

    return {
        "status": "ok" if len(rows) == len(config["symbols"]) else "partial",
        "as_of": index_summary.get("as_of"),
        "source": "Vnstock 4.0.4 community / Market Unified UI",
        "universe_note": config.get("market_universe_note"),
        "methodology": {
            "rs_20d": "stock 20-session return minus VNINDEX 20-session return",
            "rank_current": "cross-sectional rank inside the configured V1 watchlist only",
            "rank_delta": "rank 5 sessions ago minus current rank; positive means improving",
            "participation": "5-session average volume divided by 20-session average volume; volume proxy, not proof of cash transfer",
            "range_position": "(close - 20D low) / (20D high - 20D low)",
        },
        "index": index_summary,
        "rows": rows,
    }


def fetch_retail_macro(warnings: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    from vnstock import Retail

    metrics: list[dict[str, Any]] = []
    sources = ["Vietcombank and SJC/BTMC via Vnstock Retail community"]
    retail = Retail()

    try:
        fx = retail.exchange_rate()
        row = latest_row(fx, "currency", "USD")
        if row is not None:
            metrics.append(
                {
                    "key": "usd_vcb_sell",
                    "label": "USD/VND VCB sell",
                    "value": finite(row.get("sell")),
                    "unit": "VND/USD",
                    "as_of": jsonable(row.get("time")),
                    "source": "Vietcombank via Vnstock Retail",
                    "interpretation": "FX market proxy; not SBV central rate",
                }
            )
    except Exception as exc:
        warnings.append(f"retail FX: {exc}")

    try:
        gold = retail.gold(source="sjc")
        if gold is not None and not gold.empty:
            row = gold.iloc[0]
            metrics.append(
                {
                    "key": "gold_sjc_sell",
                    "label": "SJC gold sell",
                    "value": finite(row.get("sell")),
                    "unit": "source unit",
                    "as_of": jsonable(row.get("time")),
                    "source": "SJC via Vnstock Retail",
                    "interpretation": "domestic defensive-asset proxy",
                }
            )
    except Exception as exc:
        warnings.append(f"retail gold: {exc}")

    return metrics, sources


def fetch_optional_sponsor_macro(warnings: list[str]) -> tuple[dict[str, Any], list[str]]:
    datasets: dict[str, Any] = {}
    sources: list[str] = []
    try:
        from vnstock_data import Macro  # optional sponsor package; not installed by public workflow

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
                datasets[key] = df_payload(fn(), max_rows=120)
            except Exception as exc:
                warnings.append(f"sponsor macro {key}: {exc}")
        if datasets:
            sources.append("Vnstock Data sponsor Macro Unified UI")
    except Exception:
        warnings.append("vnstock_data sponsor package not installed: core SBV/interbank/OMO layer remains intentionally unavailable in public V1")
    return datasets, sources


def fetch_macro(warnings: list[str]) -> dict[str, Any]:
    metrics, sources = fetch_retail_macro(warnings)
    datasets, sponsor_sources = fetch_optional_sponsor_macro(warnings)
    sources.extend(sponsor_sources)
    missing_core = [
        "SBV central exchange rate",
        "Interbank O/N",
        "OMO outstanding/rate",
        "SBV bills outstanding",
        "Treasury liquidity proxy",
        "Credit growth",
        "Deposit growth",
    ]
    if datasets.get("interbank_rate", {}).get("rows"):
        missing_core.remove("Interbank O/N")
    if datasets.get("omo", {}).get("rows"):
        missing_core.remove("OMO outstanding/rate")
    if datasets.get("credit", {}).get("rows"):
        missing_core.remove("Credit growth")
    return {
        "status": "partial",
        "as_of": UTC_NOW.isoformat(),
        "source": sources,
        "metrics": metrics,
        "datasets": datasets,
        "missing_core": missing_core,
        "reaction_engine_status": "framework_only" if missing_core else "data_ready",
        "note": "Rootvalue V1 does not assign SBV scenario probabilities until the core liquidity variables are wired and schema-validated.",
    }


def fetch_companies(config: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    from vnstock import Fundamental

    fundamental = Fundamental()
    companies: dict[str, Any] = {}
    for symbol in config.get("fundamental_symbols", []):
        eq = fundamental.equity(symbol)
        reports: dict[str, Any] = {}
        report_calls: list[tuple[str, Callable[[], pd.DataFrame]]] = [
            ("balance_sheet", lambda eq=eq: eq.balance_sheet(period="year")),
            ("income_statement", lambda eq=eq: eq.income_statement(period="year")),
            ("cash_flow", lambda eq=eq: eq.cash_flow(period="year")),
            ("ratio", lambda eq=eq: eq.ratio(period="year")),
        ]
        for name, fn in report_calls:
            try:
                reports[name] = df_payload(fn(), max_rows=220)
            except Exception as exc:
                warnings.append(f"fundamental {symbol} {name}: {exc}")
                reports[name] = {"columns": [], "rows": [], "error": str(exc)}
            time.sleep(1.05)
        companies[symbol] = {
            "symbol": symbol,
            "period": "year",
            "reports": reports,
            "note": "Raw normalized provider output is retained in V1. Semantic accounting mappings are not guessed.",
        }
    ok_reports = sum(1 for c in companies.values() for r in c["reports"].values() if r.get("rows"))
    total_reports = max(len(companies) * 4, 1)
    status = "ok" if ok_reports == total_reports else ("partial" if ok_reports else "error")
    return {
        "status": status,
        "as_of": UTC_NOW.isoformat(),
        "source": "Vnstock 4.0.4 community / Fundamental Unified UI",
        "limitations": "Community data is limited to a small number of financial periods unless authenticated/upgraded; V1 exposes this instead of pretending to have a 10-year history.",
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
        },
    }

    try:
        snapshot["market"] = fetch_market(config, warnings)
    except Exception as exc:
        errors.append(f"market: {exc}")
        snapshot["market"] = preserve_previous(previous, "market", str(exc))

    try:
        snapshot["macro"] = fetch_macro(warnings)
    except Exception as exc:
        errors.append(f"macro: {exc}")
        snapshot["macro"] = preserve_previous(previous, "macro", str(exc))

    try:
        snapshot["companies"] = fetch_companies(config, warnings)
    except Exception as exc:
        errors.append(f"companies: {exc}")
        snapshot["companies"] = preserve_previous(previous, "companies", str(exc))

    statuses = [snapshot.get(k, {}).get("status") for k in ("market", "macro", "companies")]
    if all(s == "ok" for s in statuses):
        pipeline_status = "ok"
    elif any(s in {"ok", "partial", "stale"} for s in statuses):
        pipeline_status = "partial"
    else:
        pipeline_status = "error"
    snapshot["pipeline_status"] = pipeline_status
    snapshot["health"] = {"errors": errors, "warnings": warnings}

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(f"Rootvalue snapshot written: {OUT_PATH} | status={pipeline_status} | warnings={len(warnings)} | errors={len(errors)}")


if __name__ == "__main__":
    main()
