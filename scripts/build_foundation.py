from __future__ import annotations

import json
import math
import os
import re
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

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
REQUIRED_ANNUAL_REPORTS = ("balance_sheet", "income_statement", "cash_flow")
VOLATILE_FIELDS = {"generated_at", "fetched_at", "last_attempt_at"}
MACRO_DATASET_FREQUENCIES = {
    "exchange_rate": "day",
    "interbank_rate": "day",
    "policy_rate": "event/day",
    "omo": "day/event",
    "deposit_rate": "month",
    "credit": "month",
    "money_supply": "month",
    "cpi": "month",
    "trade": "month",
    "fdi": "month",
    "industry_prod": "month",
    "retail": "month",
}
OFFICIAL_SBV_OWNED_FIELDS = (
    "official_checks",
    "official_validation",
    "official_refresh",
)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def semantic_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: semantic_payload(value)
            for key, value in payload.items()
            if key not in VOLATILE_FIELDS
        }
    if isinstance(payload, list):
        return [semantic_payload(value) for value in payload]
    return payload


def save_json(path: Path, payload: Any) -> bool:
    previous = load_json(path, None)
    if previous is not None and semantic_payload(previous) == semantic_payload(payload):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return True


def public_error(value: Any, limit: int = 320) -> str:
    text = re.sub(r"https?://\S+", "<redacted-url>", str(value or ""))
    names = r"api[_ -]?key|access[_ -]?token|token|authorization|client[_ -]?secret"
    quoted = re.compile(rf"(?i)([\"']?(?:{names})[\"']?\s*[:=]\s*)([\"'])(.*?)(\2)")
    text = quoted.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>{match.group(2)}", text)
    text = re.sub(rf"(?i)([\"']?(?:{names})[\"']?\s*[:=]\s*)(?:Bearer\s+)?[^\s,;}}\]]+", r"\1<redacted>", text)
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] or "provider error"


def provider_call(fn: Callable[[], Any]) -> Any:
    global _LAST_PROVIDER_CALL
    elapsed = time.monotonic() - _LAST_PROVIDER_CALL
    if _LAST_PROVIDER_CALL and elapsed < RATE_SECONDS:
        time.sleep(RATE_SECONDS - elapsed)
    try:
        return fn()
    finally:
        # Failed requests also consume provider quota and must participate in throttling.
        _LAST_PROVIDER_CALL = time.monotonic()


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


def extract_periods(df: pd.DataFrame | None) -> list[str]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    periods: set[str] = set()
    pattern = re.compile(r"(?<!\d)(20\d{2}(?:[-_/ ]?Q[1-4])?)(?!\d)", flags=re.I)
    for col in df.columns:
        periods.update(match.upper().replace("_", "-").replace("/", "-").replace(" ", "-") for match in pattern.findall(str(col)))
    return sorted(periods, key=lambda value: (int(value[:4]), int(value[-1]) if "Q" in value else 0, value))


def dataframe_source_as_of(df: pd.DataFrame | None) -> str | None:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    working = df.reset_index() if not isinstance(df.index, pd.RangeIndex) else df
    candidate_columns = [
        column
        for column in working.columns
        if any(
            token in norm
            for token in ("date", "time", "period", "year", "month", "quarter", "index", "ngày", "tháng")
            for norm in [str(column).strip().lower()]
        )
    ]
    candidates: list[tuple[tuple[int, int, int, int], str]] = []
    for column in candidate_columns:
        for value in working[column].dropna().tail(2000).tolist():
            text = str(value).strip()
            full = re.search(r"(?<!\d)(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", text)
            if full:
                year, month, day = (int(part) for part in full.groups())
                try:
                    normalized = datetime(year, month, day).date().isoformat()
                    candidates.append(((year, month, day, 3), normalized))
                except ValueError:
                    pass
                continue
            quarter = re.search(r"(?i)(?<!\d)(20\d{2})[-_/ ]?Q([1-4])(?!\d)", text)
            if quarter:
                year, value_quarter = (int(part) for part in quarter.groups())
                candidates.append(((year, value_quarter * 3, 0, 2), f"{year}-Q{value_quarter}"))
                continue
            month = re.search(r"(?<!\d)(20\d{2})[-/.](\d{1,2})(?!\d)", text)
            if month:
                year, value_month = (int(part) for part in month.groups())
                if 1 <= value_month <= 12:
                    candidates.append(((year, value_month, 0, 1), f"{year}-{value_month:02d}"))
                continue
            year = re.fullmatch(r"20\d{2}", text)
            if year:
                value_year = int(text)
                candidates.append(((value_year, 0, 0, 0), text))
    return max(candidates, default=((), None), key=lambda item: item[0])[1]


def report_years(node: dict[str, Any]) -> set[int]:
    if node.get("status") != "ok" or not node.get("data", {}).get("rows"):
        return set()
    return {int(year) for year in node.get("years", []) if str(year).isdigit()}


def recompute_company_quality(item: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    annual = item.get("reports", {}).get("annual", {})
    target = int(config.get("annual_min_periods", 8) or 8)
    per_report = {
        report: sorted(report_years(annual.get(report, {})))
        for report in (*REQUIRED_ANNUAL_REPORTS, "ratio")
    }
    required_sets = [set(per_report[report]) for report in REQUIRED_ANNUAL_REPORTS]
    common = sorted(set.intersection(*required_sets)) if required_sets and all(required_sets) else []
    union = sorted(set.union(*required_sets)) if required_sets else []
    required_ready = {
        report: len(per_report[report]) >= target
        for report in REQUIRED_ANNUAL_REPORTS
    }
    minimum_met = len(common) >= target and all(required_ready.values())
    available_required = sum(bool(per_report[report]) for report in REQUIRED_ANNUAL_REPORTS)
    stale_reports = [
        f"{bucket}.{report}"
        for bucket, reports in item.get("reports", {}).items()
        for report, node in reports.items()
        if node.get("refresh_status") == "stale"
    ]
    item["coverage"] = {
        **item.get("coverage", {}),
        "annual_years": common,
        "annual_union_years": union,
        "annual_periods": len(common),
        "minimum_annual_periods": target,
        "minimum_met": minimum_met,
        "required_annual_reports": list(REQUIRED_ANNUAL_REPORTS),
        "required_reports_ready": required_ready,
        "annual_years_by_report": per_report,
        "quarterly_target_periods": int(config.get("quarterly_target_periods", 32)),
    }
    item["source_as_of"] = str(max(union)) if union else None
    item["stale_reports"] = stale_reports
    item["status"] = "ready" if minimum_met and not stale_reports else ("partial" if available_required else "error")
    return item


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
    quarterly_years: set[int] = set()

    for report in ("balance_sheet", "income_statement", "cash_flow", "ratio"):
        for period, bucket in (("year", "annual"), ("quarter", "quarterly")):
            try:
                frame = provider_call(lambda s=symbol, r=report, p=period: invoke_report(fundamental, s, r, p))
                years = extract_years(frame)
                periods = extract_periods(frame)
                if bucket == "quarterly":
                    quarterly_years.update(years)
                has_rows = isinstance(frame, pd.DataFrame) and not frame.empty
                reports[bucket][report] = {
                    "status": "ok" if has_rows else "empty",
                    "years": years,
                    "periods": periods,
                    "source_as_of": periods[-1] if periods else (str(years[-1]) if years else None),
                    "fetched_at": NOW.isoformat(),
                    "provider": provider_name,
                    "source": source_label,
                    "provenance": "secondary_normalized_provider",
                    "refresh_status": "fresh" if has_rows else "empty",
                    "data": df_payload(frame),
                }
            except Exception as exc:
                message = public_error(exc)
                warnings.append(f"{bucket}.{report}: {message}")
                reports[bucket][report] = {
                    "status": "error",
                    "error": message,
                    "years": [],
                    "periods": [],
                    "source_as_of": None,
                    "fetched_at": NOW.isoformat(),
                    "provider": provider_name,
                    "source": source_label,
                    "provenance": "secondary_normalized_provider",
                    "refresh_status": "failed",
                    "data": {"columns": [], "rows": [], "row_count": 0},
                }

    item = {
        "schema_version": "1.0.0",
        "symbol": symbol,
        "generated_at": NOW.isoformat(),
        "provider": provider_name,
        "source": source_label,
        "provenance": "secondary_normalized_provider",
        "access_mode": "api-key" if API_KEY_PRESENT else "guest",
        "coverage": {
            "quarterly_years": sorted(quarterly_years),
            "quarterly_target_periods": int(config.get("quarterly_target_periods", 32)),
        },
        "reports": reports,
        "warnings": warnings,
        "policy": "No synthetic values. Missing periods remain missing.",
    }
    return recompute_company_quality(item, config)


def report_quality(node: dict[str, Any]) -> tuple[int, int, int, int]:
    years = report_years(node)
    rows = node.get("data", {}).get("rows") or []
    return (
        1 if node.get("status") == "ok" and rows else 0,
        len(years),
        max(years) if years else 0,
        len(rows),
    )


def preserve_better_company(path: Path, fresh: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    old = load_json(path, {})
    if not old:
        return fresh

    merged = deepcopy(fresh)
    stale_messages: list[str] = []
    for bucket in ("annual", "quarterly"):
        for report in ("balance_sheet", "income_statement", "cash_flow", "ratio"):
            old_node = old.get("reports", {}).get(bucket, {}).get(report, {})
            new_node = fresh.get("reports", {}).get(bucket, {}).get(report, {})
            if report_quality(old_node) <= report_quality(new_node):
                continue
            kept = deepcopy(old_node)
            kept["refresh_status"] = "stale"
            kept["last_attempt_at"] = NOW.isoformat()
            reason = new_node.get("error") or f"new quality {report_quality(new_node)} below stored {report_quality(old_node)}"
            kept["last_refresh_error"] = public_error(reason)
            merged.setdefault("reports", {}).setdefault(bucket, {})[report] = kept
            stale_messages.append(f"{bucket}.{report}: kept last-known-good report")

    if stale_messages:
        merged["last_attempt_at"] = NOW.isoformat()
        merged["last_refresh_error"] = "; ".join(stale_messages)
        merged["warnings"] = list(dict.fromkeys([*merged.get("warnings", []), *stale_messages]))
    return recompute_company_quality(merged, config)


def mark_company_stale(item: dict[str, Any], error: Any, config: dict[str, Any]) -> dict[str, Any]:
    stale = deepcopy(item)
    message = public_error(error)
    for reports in stale.get("reports", {}).values():
        if not isinstance(reports, dict):
            continue
        for node in reports.values():
            if not isinstance(node, dict):
                continue
            node["refresh_status"] = "stale"
            node["last_attempt_at"] = NOW.isoformat()
            node["last_refresh_error"] = message
    stale["last_refresh_error"] = message
    stale["last_attempt_at"] = NOW.isoformat()
    stale["refresh_status"] = "stale"
    return recompute_company_quality(stale, config)


def parse_official_table(url: str, label: str) -> dict[str, Any]:
    try:
        import requests

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
            "error": public_error(exc),
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
            "source_as_of": dataframe_source_as_of(frame),
            "fetched_at": NOW.isoformat(),
            "refresh_status": "fresh" if isinstance(frame, pd.DataFrame) and not frame.empty else "empty",
            "data": df_payload(frame, 10000),
        }
    except Exception as exc:
        return {"status": "error", "source": source, "provenance": "secondary_normalized_provider", "frequency": frequency, "source_as_of": None, "fetched_at": NOW.isoformat(), "refresh_status": "failed", "error": public_error(exc), "data": {"columns": [], "rows": [], "row_count": 0}}


def macro_error_dataset(error: Any, source: str, frequency: str) -> dict[str, Any]:
    return {
        "status": "error",
        "source": source,
        "provenance": "secondary_normalized_provider",
        "frequency": frequency,
        "source_as_of": None,
        "fetched_at": NOW.isoformat(),
        "refresh_status": "failed",
        "error": public_error(error),
        "data": {"columns": [], "rows": [], "row_count": 0},
    }


def macro_dataset_row_count(node: dict[str, Any]) -> int:
    rows = node.get("data", {}).get("rows")
    return len(rows) if isinstance(rows, list) else 0


def macro_dataset_usable(node: dict[str, Any]) -> bool:
    return node.get("status") in {"ok", "stale"} and macro_dataset_row_count(node) > 0


def macro_source_period_key(value: Any) -> tuple[int, int, int, str]:
    text = str(value or "")
    full = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if full:
        return (*[int(part) for part in full.groups()], text)
    quarter = re.search(r"(?i)(20\d{2})[-_/ ]?Q([1-4])", text)
    if quarter:
        year, value_quarter = (int(part) for part in quarter.groups())
        return year, value_quarter * 3, 0, text
    month = re.search(r"(20\d{2})[-/.](\d{1,2})", text)
    if month:
        year, value_month = (int(part) for part in month.groups())
        return year, value_month, 0, text
    year = re.search(r"(20\d{2})", text)
    return (int(year.group(1)), 0, 0, text) if year else (0, 0, 0, text)


def macro_dataset_regression(previous: dict[str, Any], fresh: dict[str, Any]) -> str | None:
    if not macro_dataset_usable(previous) or not macro_dataset_usable(fresh):
        return None
    previous_rows = macro_dataset_row_count(previous)
    fresh_rows = macro_dataset_row_count(fresh)
    if fresh_rows < previous_rows:
        return f"fresh history shrank from {previous_rows} to {fresh_rows} rows"
    previous_as_of = previous.get("source_as_of")
    fresh_as_of = fresh.get("source_as_of")
    if previous_as_of and not fresh_as_of:
        return f"fresh history lost source_as_of={previous_as_of}"
    if previous_as_of and fresh_as_of and macro_source_period_key(fresh_as_of) < macro_source_period_key(previous_as_of):
        return f"fresh source_as_of regressed from {previous_as_of} to {fresh_as_of}"
    return None


def stale_macro_dataset(previous: dict[str, Any], error: Any) -> dict[str, Any]:
    kept = deepcopy(previous)
    kept["status"] = "stale"
    kept["refresh_status"] = "stale"
    kept["last_attempt_at"] = NOW.isoformat()
    kept["last_refresh_error"] = public_error(error)
    kept.pop("error", None)
    return kept


def macro_coverage(datasets: dict[str, Any], required: list[str]) -> dict[str, Any]:
    available = [key for key in required if macro_dataset_usable(datasets.get(key, {}))]
    fresh = [
        key
        for key in required
        if datasets.get(key, {}).get("status") == "ok"
        and datasets.get(key, {}).get("refresh_status") == "fresh"
        and macro_dataset_row_count(datasets.get(key, {})) > 0
    ]
    stale = [key for key in available if datasets.get(key, {}).get("status") == "stale"]
    missing = [key for key in required if key not in available]
    history_ready = len(missing) == 0
    fresh_state_ready = history_ready and len(fresh) == len(required)
    return {
        "required_for_state": required,
        "available": available,
        "fresh_available": fresh,
        "fresh": fresh,
        "stale": stale,
        "missing": missing,
        "history_ready": history_ready,
        "state_usable": history_ready,
        "state_ready": fresh_state_ready,
        "fresh_state_ready": fresh_state_ready,
    }


def merge_macro_snapshot(
    previous: dict[str, Any],
    fresh: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    previous_datasets = previous.get("datasets", {}) if isinstance(previous.get("datasets"), dict) else {}
    attempted_datasets = fresh.get("datasets", {}) if isinstance(fresh.get("datasets"), dict) else {}
    merged_datasets: dict[str, Any] = {}
    preserved: list[str] = []
    regressions: list[str] = []
    refresh_errors: dict[str, str] = {}
    keys = list(dict.fromkeys([*MACRO_DATASET_FREQUENCIES, *previous_datasets, *attempted_datasets]))

    for key in keys:
        old_node = previous_datasets.get(key, {})
        attempt = attempted_datasets.get(key)
        if not isinstance(attempt, dict):
            attempt = macro_error_dataset(
                fresh.get("historical_provider_error") or "dataset was not returned by provider refresh",
                str(old_node.get("source") or "Vnstock Data Macro normalized feeds"),
                str(old_node.get("frequency") or MACRO_DATASET_FREQUENCIES.get(key, "unknown")),
            )

        regression = macro_dataset_regression(old_node, attempt)
        if regression and macro_dataset_usable(old_node):
            message = f"{key}: {regression}; kept last-known-good dataset"
            merged_datasets[key] = stale_macro_dataset(old_node, message)
            preserved.append(key)
            regressions.append(message)
            refresh_errors[key] = public_error(message)
        elif macro_dataset_usable(attempt):
            current = deepcopy(attempt)
            current["status"] = "ok"
            current["refresh_status"] = "fresh"
            current.pop("error", None)
            current.pop("last_refresh_error", None)
            current.pop("last_attempt_at", None)
            merged_datasets[key] = current
        elif macro_dataset_usable(old_node):
            reason = attempt.get("error") or f"provider returned status={attempt.get('status', 'missing')}"
            merged_datasets[key] = stale_macro_dataset(old_node, reason)
            preserved.append(key)
            refresh_errors[key] = public_error(reason)
        else:
            merged_datasets[key] = deepcopy(attempt)
            if attempt.get("status") != "ok":
                refresh_errors[key] = public_error(attempt.get("error") or f"status={attempt.get('status', 'missing')}")

    required = [str(key) for key in config.get("policy", {}).get("macro_state_requires", [])]
    coverage = macro_coverage(merged_datasets, required)
    provider_error = fresh.get("historical_provider_error")
    if provider_error:
        provider_status = "unavailable"
    elif preserved or any(node.get("status") != "ok" for node in attempted_datasets.values()):
        provider_status = "partial"
    else:
        provider_status = "fresh"

    merged = deepcopy(fresh)
    merged["datasets"] = merged_datasets
    merged["historical_provider"] = (
        fresh.get("historical_provider")
        or (previous.get("historical_provider") if any(macro_dataset_usable(node) for node in merged_datasets.values()) else None)
    )
    merged["historical_provider_status"] = provider_status
    merged["historical_refresh_errors"] = refresh_errors
    merged["last_attempt_at"] = NOW.isoformat()
    merged["preserved_datasets"] = preserved
    merged["coverage_regressions"] = regressions
    merged["coverage"] = coverage
    merged["state_engine"] = {
        "status": (
            "blocked_by_missing_history"
            if coverage["missing"]
            else "data_ready_stale"
            if coverage["stale"]
            else "data_ready"
        ),
        "note": (
            "Required historical series are usable but at least one is retained last-known-good data."
            if coverage["history_ready"] and coverage["stale"]
            else "Rootvalue does not assign SBV regime/probabilities until required historical series are present and validated against official SBV publications."
        ),
    }
    # The daily official-SBV workflow is the sole writer for these nodes.
    # Weekly company/macro refreshes must preserve them byte-for-byte in value,
    # even if a caller accidentally supplies replacement nodes in ``fresh``.
    for field in OFFICIAL_SBV_OWNED_FIELDS:
        merged.pop(field, None)
        if field in previous:
            merged[field] = deepcopy(previous[field])
    return merged


def fetch_macro(config: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
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
        provider_error = public_error(exc)

    if provider is not None:
        src = "Vnstock Data Macro normalized feeds"
        currency = None
        economy = None
        currency_error = None
        economy_error = None
        try:
            currency = provider_call(lambda: provider.currency())
        except Exception as exc:
            currency_error = public_error(exc)
        try:
            economy = provider_call(lambda: provider.economy())
        except Exception as exc:
            economy_error = public_error(exc)

        currency_specs: dict[str, tuple[str, Callable[[], pd.DataFrame]]] = {}
        if currency is not None:
            currency_specs = {
                "exchange_rate": ("day", lambda: currency.exchange_rate(start=start, end=TODAY, period="day")),
                "interbank_rate": ("day", lambda: currency.interbank_rate(start=start, end=TODAY, period="day")),
                "policy_rate": ("event/day", lambda: currency.policy_rate(start=start, end=TODAY)),
                "omo": ("day/event", lambda: currency.omo(start=start, end=TODAY)),
                "deposit_rate": ("month", lambda: currency.deposit_rate(period="month", start=start_month, end=end_month)),
            }
        for key, frequency in {
            "exchange_rate": "day", "interbank_rate": "day", "policy_rate": "event/day",
            "omo": "day/event", "deposit_rate": "month",
        }.items():
            datasets[key] = macro_dataset(currency_specs[key][1], src, frequency) if key in currency_specs else macro_error_dataset(currency_error or "currency domain unavailable", src, frequency)

        economy_specs: dict[str, tuple[str, Callable[[], pd.DataFrame]]] = {}
        if economy is not None:
            economy_specs = {
                "credit": ("month", lambda: economy.credit(start=start_month, end=end_month, period="month")),
                "money_supply": ("month", lambda: economy.money_supply(start=start_month, end=end_month, period="month")),
                "cpi": ("month", lambda: economy.cpi(start=start_month, end=end_month, period="month")),
                "trade": ("month", lambda: economy.import_export(start=start_month, end=end_month, period="month")),
                "fdi": ("month", lambda: economy.fdi(start=start_month, end=end_month, period="month")),
                "industry_prod": ("month", lambda: economy.industry_prod(start=start_month, end=end_month, period="month")),
                "retail": ("month", lambda: economy.retail(start=start_month, end=end_month, period="month")),
            }
        for key in ("credit", "money_supply", "cpi", "trade", "fdi", "industry_prod", "retail"):
            datasets[key] = macro_dataset(economy_specs[key][1], src, "month") if key in economy_specs else macro_error_dataset(economy_error or "economy domain unavailable", src, "month")

    for key, frequency in MACRO_DATASET_FREQUENCIES.items():
        if key not in datasets:
            datasets[key] = macro_error_dataset(
                provider_error or "historical macro provider unavailable",
                "Vnstock Data Macro normalized feeds",
                frequency,
            )

    fresh = {
        "schema_version": "1.0.0",
        "generated_at": NOW.isoformat(),
        "history_start": start,
        "historical_provider": "vnstock_data" if provider is not None else None,
        "historical_provider_error": provider_error,
        "datasets": datasets,
    }
    return merge_macro_snapshot(previous or {}, fresh, config)


def company_summary_row(symbol: str, item: dict[str, Any]) -> dict[str, Any]:
    coverage = item.get("coverage", {})
    current_ready = bool(coverage.get("minimum_met")) and item.get("status") == "ready"
    return {
        "symbol": symbol,
        "status": item.get("status", "error"),
        "annual_periods": coverage.get("annual_periods", 0),
        "minimum_met": bool(coverage.get("minimum_met")),
        "ready_for_foundation": current_ready,
        "required_reports_ready": coverage.get("required_reports_ready", {}),
        "stale_reports": item.get("stale_reports", []),
        "source_as_of": item.get("source_as_of"),
        "generated_at": item.get("generated_at"),
        "last_attempt_at": item.get("last_attempt_at"),
        "last_refresh_error": public_error(item.get("last_refresh_error")) if item.get("last_refresh_error") else None,
        "provider": item.get("provider"),
    }


def main() -> None:
    watchlist = load_json(WATCHLIST_PATH, {})
    config = load_json(FOUNDATION_CONFIG_PATH, {})
    symbols = [str(s).upper() for s in watchlist.get("fundamental_symbols", [])]
    COMPANY_DIR.mkdir(parents=True, exist_ok=True)

    provider_name = None
    source_label = None
    fundamental_error = None
    try:
        fundamental, provider_name, source_label = get_fundamental_provider()
        for symbol in symbols:
            path = COMPANY_DIR / f"{symbol}.json"
            try:
                fresh = fetch_company(fundamental, provider_name, source_label, symbol, config)
                final = preserve_better_company(path, fresh, config)
                if not save_json(path, final):
                    final = load_json(path, final)
            except Exception as exc:
                old = load_json(path, {})
                message = public_error(exc)
                if old:
                    save_json(path, mark_company_stale(old, message, config))
    except Exception as exc:
        fundamental_error = public_error(exc)
        for symbol in symbols:
            path = COMPANY_DIR / f"{symbol}.json"
            old = load_json(path, {})
            if not old:
                continue
            save_json(path, mark_company_stale(old, fundamental_error, config))

    company_summary: list[dict[str, Any]] = []
    for symbol in symbols:
        item = load_json(COMPANY_DIR / f"{symbol}.json", {})
        if item:
            company_summary.append(company_summary_row(symbol, item))
        else:
            company_summary.append({
                "symbol": symbol,
                "status": "error",
                "annual_periods": 0,
                "minimum_met": False,
                "ready_for_foundation": False,
                "error": fundamental_error or "company snapshot missing",
            })

    previous_macro = load_json(MACRO_PATH, {})
    macro = fetch_macro(config, previous_macro)
    if not save_json(MACRO_PATH, macro):
        macro = load_json(MACRO_PATH, macro)

    min_ready = sum(1 for row in company_summary if row.get("ready_for_foundation"))
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
            "fundamental_error": public_error(fundamental_error) if fundamental_error else None,
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
        "policy": "Data foundation is READY only when every required annual report has >=8 common periods for every configured company and every required SBV-state historical series is present.",
    }
    save_json(MANIFEST_PATH, manifest)
    print(json.dumps({"foundation_ready": manifest["foundation_ready"], "company_8y_ready": f"{min_ready}/{len(symbols)}", "macro_state_ready": macro.get("coverage", {}).get("state_ready")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
