from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
WATCHLIST_PATH = ROOT / "config" / "watchlist.json"
FOUNDATION_CONFIG_PATH = ROOT / "config" / "foundation.json"
FOUNDATION_DIR = ROOT / "data" / "foundation"
COMPANY_DIR = FOUNDATION_DIR / "companies"
MACRO_PATH = FOUNDATION_DIR / "macro.json"
MANIFEST_PATH = FOUNDATION_DIR / "manifest.json"

NOW = datetime.now(timezone.utc)
TODAY = NOW.date().isoformat()
API_KEY_PRESENT = bool(os.getenv("VNSTOCK_API_KEY", "").strip())
# Guest mode is 20 req/min; authenticated community is higher. Keep a safety margin.
RATE_SECONDS = 1.4 if API_KEY_PRESENT else 4.0
_LAST_PROVIDER_CALL = 0.0


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def provider_call(fn: Callable[[], Any]) -> Any:
    global _LAST_PROVIDER_CALL
    elapsed = time.monotonic() - _LAST_PROVIDER_CALL
    if _LAST_PROVIDER_CALL and elapsed < RATE_SECONDS:
        time.sleep(RATE_SECONDS - elapsed)
    result = fn()
    _LAST_PROVIDER_CALL = time.monotonic()
    return result


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
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def df_payload(df: pd.DataFrame | None, max_rows: int = 5000) -> dict[str, Any]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return {"columns": [], "rows": [], "row_count": 0}
    safe = df.copy()
    if not isinstance(safe.index, pd.RangeIndex):
        safe = safe.reset_index()
    safe = safe.head(max_rows)
    return {
        "columns": [str(c) for c in safe.columns],
        "rows": [[jsonable(v) for v in row] for row in safe.itertuples(index=False, name=None)],
        "row_count": int(len(safe)),
    }


def extract_years(df: pd.DataFrame | None) -> list[int]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    years: set[int] = set()
    for col in df.columns:
        for token in re.findall(r"(?<!\d)(20\d{2})(?!\d)", str(col)):
            years.add(int(token))
    candidate_cols = [c for c in df.columns if str(c).lower() in {"year", "period", "time", "date", "quarter"}]
    for col in candidate_cols:
        for value in df[col].head(500).tolist():
            for token in re.findall(r"(?<!\d)(20\d{2})(?!\d)", str(value)):
                years.add(int(token))
    return sorted(years)


def report_method(obj: Any, report: str) -> Callable[..., pd.DataFrame]:
    candidates = [report]
    if report == "ratio":
        candidates = ["ratio", "ratios"]
    for name in candidates:
        fn = getattr(obj, name, None)
        if callable(fn):
            return fn
    raise AttributeError(f"No method for report={report}")


def invoke_report(fundamental: Any, symbol: str, report: str, period: str) -> pd.DataFrame:
    # Prefer symbol-bound Unified UI. Fall back to property-style Unified UI used by some builds.
    errors: list[str] = []
    try:
        obj = fundamental.equity(symbol)
        fn = report_method(obj, report)
        for kwargs in (
            {"period": period, "lang": "vi", "dropna": False},
            {"period": period, "lang": "vi"},
            {"period": period},
        ):
            try:
                return fn(**kwargs)
            except TypeError as exc:
                errors.append(str(exc))
    except Exception as exc:
        errors.append(str(exc))

    proxy = getattr(fundamental, "equity", None)
    if proxy is not None:
        for name in ([report, "ratios"] if report == "ratio" else [report]):
            fn = getattr(proxy, name, None)
            if not callable(fn):
                continue
            for kwargs in (
                {"symbol": symbol, "period": period, "lang": "vi", "dropna": False},
                {"symbol": symbol, "period": period},
            ):
                try:
                    return fn(**kwargs)
                except TypeError as exc:
                    errors.append(str(exc))
    raise RuntimeError("; ".join(errors[-4:]) or f"Unable to fetch {symbol} {report} {period}")


def get_fundamental_provider() -> tuple[Any, str, str]:
    try:
        from vnstock_data import Fundamental  # type: ignore

        return Fundamental(), "vnstock_data", "MAS via Vnstock Data"
    except Exception:
        from vnstock import Fundamental

        mode = "authenticated-community" if API_KEY_PRESENT else "guest"
        return Fundamental(), "vnstock", f"MAS via Vnstock community ({mode})"


def fetch_company(fundamental: Any, provider_name: str, source_label: str, symbol: str, config: dict[str, Any]) -> dict[str, Any]:
    reports: dict[str, Any] = {"annual": {}, "quarterly": {}}
    warnings: list[str] = []
    annual_years: set[int] = set()
    quarterly_years: set[int] = set()

    for report in ("balance_sheet", "income_statement", "cash_flow", "ratio"):
        for period, bucket in (("year", "annual"), ("quarter", "quarterly")):
            try:
                frame = provider_call(lambda s=symbol, r=report, p=period: invoke_report(fundamental, s, r, p))
                years = extract_years(frame)
                if bucket == "annual":
                    annual_years.update(years)
                else:
                    quarterly_years.update(years)
                reports[bucket][report] = {
                    "status": "ok",
                    "years": years,
                    "data": df_payload(frame),
                }
            except Exception as exc:
                warnings.append(f"{bucket}.{report}: {exc}")
                reports[bucket][report] = {"status": "error", "error": str(exc), "years": [], "data": {"columns": [], "rows": [], "row_count": 0}}

    annual_count = len(annual_years)
    target = int(config.get("annual_min_periods", 8))
    status = "ready" if annual_count >= target else ("partial" if annual_count else "error")
    return {
        "schema_version": "1.0.0",
        "symbol": symbol,
        "generated_at": NOW.isoformat(),
        "provider": provider_name,
        "source": source_label,
        "provenance": "secondary_normalized_provider",
        "access_mode": "api-key" if API_KEY_PRESENT else "guest",
        "coverage": {
            "annual_years": sorted(annual_years),
            "annual_periods": annual_count,
            "minimum_annual_periods": target,
            "minimum_met": annual_count >= target,
            "quarterly_years": sorted(quarterly_years),
            "quarterly_target_periods": int(config.get("quarterly_target_periods", 32)),
        },
        "status": status,
        "reports": reports,
        "warnings": warnings,
        "policy": "No synthetic values. Missing periods remain missing.",
    }


def preserve_better_company(path: Path, fresh: dict[str, Any]) -> dict[str, Any]:
    old = load_json(path, {})
    old_n = int(old.get("coverage", {}).get("annual_periods", 0) or 0)
    new_n = int(fresh.get("coverage", {}).get("annual_periods", 0) or 0)
    if old_n > new_n:
        old["last_refresh_error"] = f"New fetch had only {new_n} annual periods; kept older snapshot with {old_n}."
        old["last_attempt_at"] = NOW.isoformat()
        return old
    return fresh


def parse_official_table(url: str, label: str) -> dict[str, Any]:
    try:
        response = requests.get(url, timeout=25, headers={"User-Agent": "Rootvalue/1.0 personal-research"})
        response.raise_for_status()
        tables = pd.read_html(response.text)
        usable = [t for t in tables if isinstance(t, pd.DataFrame) and not t.empty]
        return {
            "status": "ok" if usable else "empty",
            "label": label,
            "url": url,
            "source": "State Bank of Vietnam official website",
            "provenance": "primary_official",
            "fetched_at": NOW.isoformat(),
            "tables": [df_payload(t, 100) for t in usable[:5]],
        }
    except Exception as exc:
        return {
            "status": "error",
            "label": label,
            "url": url,
            "source": "State Bank of Vietnam official website",
            "provenance": "primary_official",
            "fetched_at": NOW.isoformat(),
            "error": str(exc),
            "tables": [],
        }


def macro_dataset(fn: Callable[[], pd.DataFrame], source: str, frequency: str) -> dict[str, Any]:
    try:
        frame = provider_call(fn)
        return {
            "status": "ok" if isinstance(frame, pd.DataFrame) and not frame.empty else "empty",
            "source": source,
            "provenance": "secondary_normalized_provider",
            "frequency": frequency,
            "data": df_payload(frame, 10000),
        }
    except Exception as exc:
        return {"status": "error", "source": source, "provenance": "secondary_normalized_provider", "frequency": frequency, "error": str(exc), "data": {"columns": [], "rows": [], "row_count": 0}}


def fetch_macro(config: dict[str, Any]) -> dict[str, Any]:
    start = str(config.get("macro_start", "2018-01-01"))
    start_month = start[:7]
    end_month = TODAY[:7]
    datasets: dict[str, Any] = {}
    provider = None
    provider_error = None
    try:
        from vnstock_data import Macro  # type: ignore

        provider = Macro()
    except Exception as exc:
        provider_error = str(exc)

    if provider is not None:
        src = "Vnstock Data Macro normalized feeds"
        currency = provider.currency()
        economy = provider.economy()
        datasets = {
            "exchange_rate": macro_dataset(lambda: currency.exchange_rate(start=start, end=TODAY, period="day"), src, "day"),
            "interbank_rate": macro_dataset(lambda: currency.interbank_rate(start=start, end=TODAY, period="day"), src, "day"),
            "policy_rate": macro_dataset(lambda: currency.policy_rate(start=start, end=TODAY), src, "event/day"),
            "omo": macro_dataset(lambda: currency.omo(start=start, end=TODAY), src, "day/event"),
            "deposit_rate": macro_dataset(lambda: currency.deposit_rate(period="month", start=start_month, end=end_month), src, "month"),
            "credit": macro_dataset(lambda: economy.credit(start=start_month, end=end_month, period="month"), src, "month"),
            "money_supply": macro_dataset(lambda: economy.money_supply(start=start_month, end=end_month, period="month"), src, "month"),
            "cpi": macro_dataset(lambda: economy.cpi(start=start_month, end=end_month, period="month"), src, "month"),
            "trade": macro_dataset(lambda: economy.import_export(start=start_month, end=end_month, period="month"), src, "month"),
            "fdi": macro_dataset(lambda: economy.fdi(start=start_month, end=end_month, period="month"), src, "month"),
            "industry_prod": macro_dataset(lambda: economy.industry_prod(start=start_month, end=end_month, period="month"), src, "month"),
            "retail": macro_dataset(lambda: economy.retail(start=start_month, end=end_month, period="month"), src, "month"),
        }

    official_cfg = config.get("official_sbv_sources", {})
    official = {
        "money_supply_deposits": parse_official_table(official_cfg.get("money_supply_deposits", ""), "Tổng phương tiện thanh toán và tiền gửi") if official_cfg.get("money_supply_deposits") else {"status": "missing_config"},
        "omo_latest": parse_official_table(official_cfg.get("omo", ""), "Nghiệp vụ thị trường mở") if official_cfg.get("omo") else {"status": "missing_config"},
    }

    required = list(config.get("policy", {}).get("macro_state_requires", []))
    available = [key for key in required if datasets.get(key, {}).get("status") == "ok"]
    missing = [key for key in required if key not in available]
    return {
        "schema_version": "1.0.0",
        "generated_at": NOW.isoformat(),
        "history_start": start,
        "historical_provider": "vnstock_data" if provider is not None else None,
        "historical_provider_error": provider_error,
        "datasets": datasets,
        "official_checks": official,
        "coverage": {
            "required_for_state": required,
            "available": available,
            "missing": missing,
            "state_ready": len(missing) == 0,
        },
        "state_engine": {
            "status": "data_ready" if len(missing) == 0 else "blocked_by_missing_history",
            "note": "Rootvalue does not assign SBV regime/probabilities until required historical series are present and validated against official SBV publications.",
        },
    }


def main() -> None:
    watchlist = load_json(WATCHLIST_PATH, {})
    config = load_json(FOUNDATION_CONFIG_PATH, {})
    symbols = [str(s).upper() for s in watchlist.get("fundamental_symbols", [])]
    COMPANY_DIR.mkdir(parents=True, exist_ok=True)

    provider_name = None
    source_label = None
    fundamental_error = None
    company_summary: list[dict[str, Any]] = []
    try:
        fundamental, provider_name, source_label = get_fundamental_provider()
        for symbol in symbols:
            path = COMPANY_DIR / f"{symbol}.json"
            try:
                fresh = fetch_company(fundamental, provider_name, source_label, symbol, config)
                final = preserve_better_company(path, fresh)
                save_json(path, final)
                company_summary.append({
                    "symbol": symbol,
                    "status": final.get("status"),
                    "annual_periods": final.get("coverage", {}).get("annual_periods", 0),
                    "minimum_met": final.get("coverage", {}).get("minimum_met", False),
                    "provider": final.get("provider"),
                })
            except Exception as exc:
                old = load_json(path, {})
                if old:
                    old["last_refresh_error"] = str(exc)
                    old["last_attempt_at"] = NOW.isoformat()
                    save_json(path, old)
                    company_summary.append({"symbol": symbol, "status": "stale", "annual_periods": old.get("coverage", {}).get("annual_periods", 0), "minimum_met": old.get("coverage", {}).get("minimum_met", False), "provider": old.get("provider")})
                else:
                    company_summary.append({"symbol": symbol, "status": "error", "annual_periods": 0, "minimum_met": False, "error": str(exc)})
    except Exception as exc:
        fundamental_error = str(exc)

    macro = fetch_macro(config)
    save_json(MACRO_PATH, macro)

    min_ready = sum(1 for row in company_summary if row.get("minimum_met"))
    manifest = {
        "schema_version": "1.0.0",
        "generated_at": NOW.isoformat(),
        "history_target": {
            "start": config.get("history_start"),
            "annual_min_periods": config.get("annual_min_periods", 8),
            "quarterly_target_periods": config.get("quarterly_target_periods", 32),
        },
        "access": {
            "vnstock_api_key_present": API_KEY_PRESENT,
            "fundamental_provider": provider_name,
            "fundamental_source": source_label,
            "fundamental_error": fundamental_error,
            "note": "Authenticated community access is required for up to 8 financial periods; vnstock_data is preferred when available for longer history.",
        },
        "companies": company_summary,
        "company_qc": {
            "requested": len(symbols),
            "minimum_8y_ready": min_ready,
            "all_minimum_ready": bool(symbols) and min_ready == len(symbols),
        },
        "macro_qc": macro.get("coverage", {}),
        "foundation_ready": bool(symbols) and min_ready == len(symbols) and bool(macro.get("coverage", {}).get("state_ready")),
        "policy": "Data foundation is READY only when every configured company has >=8 annual periods and every required SBV-state historical series is present.",
    }
    save_json(MANIFEST_PATH, manifest)
    print(json.dumps({"foundation_ready": manifest["foundation_ready"], "company_8y_ready": f"{min_ready}/{len(symbols)}", "macro_state_ready": macro.get("coverage", {}).get("state_ready")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
