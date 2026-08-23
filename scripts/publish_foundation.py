from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = ROOT / "data" / "foundation"
OUT = ROOT / "data" / "rootvalue.json"
MARKET = ROOT / "data" / "market.json"
WATCHLIST = ROOT / "config" / "watchlist.json"


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def semantic_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {key: semantic_payload(value) for key, value in payload.items() if key != "generated_at"}
    if isinstance(payload, list):
        return [semantic_payload(value) for value in payload]
    return payload


def save(path: Path, payload: Any) -> bool:
    previous = load(path, None)
    if previous is not None and semantic_payload(previous) == semantic_payload(payload):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return True


def source_period_key(value: Any) -> tuple[int, int, int, str]:
    text = str(value or "")
    full = re.search(r"(20\d{2})-(\d{2})-(\d{2})", text)
    if full:
        return (*[int(part) for part in full.groups()], text)
    quarter = re.search(r"(?i)(20\d{2})-?Q([1-4])", text)
    if quarter:
        year, value_quarter = (int(part) for part in quarter.groups())
        return year, value_quarter * 3, 0, text
    month = re.search(r"(20\d{2})-(\d{2})", text)
    if month:
        year, value_month = (int(part) for part in month.groups())
        return year, value_month, 0, text
    year = re.search(r"(20\d{2})", text)
    return (int(year.group(1)), 0, 0, text) if year else (0, 0, 0, text)


def latest_source_value(values: list[Any]) -> str | None:
    usable = [str(value) for value in values if value]
    return max(usable, key=source_period_key) if usable else None


def macro_source_as_of(macro: dict[str, Any], metrics: list[dict[str, Any]]) -> str | None:
    source_dates = [metric.get("as_of") for metric in metrics]
    source_dates.extend(
        node.get("source_as_of") or node.get("as_of")
        for node in macro.get("datasets", {}).values()
        if isinstance(node, dict)
        and node.get("status") in {"ok", "stale"}
        and node.get("data", {}).get("rows")
    )
    return latest_source_value(source_dates)


def merge_market_health(
    market: dict[str, Any],
    warnings: list[str],
    errors: list[str],
    limit: int = 12,
) -> None:
    """Surface bounded canonical-market refresh diagnostics in root health."""
    health = market.get("health") if isinstance(market.get("health"), dict) else {}
    warning_messages = list(health.get("warnings") or [])
    error_messages = list(health.get("errors") or [])
    if market.get("last_error"):
        warning_messages.append(market["last_error"])
    attempt = market.get("last_refresh_attempt")
    if isinstance(attempt, dict):
        warning_messages.extend(attempt.get("errors") or [])

    for message in list(dict.fromkeys(str(value) for value in warning_messages if value))[:limit]:
        warnings.append(f"Market refresh: {message}")
    target = errors if market.get("status") == "error" else warnings
    for message in list(dict.fromkeys(str(value) for value in error_messages if value))[:limit]:
        target.append(f"Market refresh: {message}")


def latest_sbv_by_dataset(history: dict[str, Any]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for observation in history.get("observations") or []:
        if not isinstance(observation, dict):
            continue
        dataset = str(observation.get("dataset") or "")
        if not dataset:
            continue
        candidate_key = (
            source_period_key(
                observation.get("source_observation_date")
                or observation.get("source_as_of")
                or observation.get("source_date")
            ),
            str(observation.get("fetched_at") or ""),
            str(observation.get("observation_key") or ""),
        )
        current = latest.get(dataset)
        current_key = (
            source_period_key(
                current.get("source_observation_date")
                or current.get("source_as_of")
                or current.get("source_date")
            ),
            str(current.get("fetched_at") or ""),
            str(current.get("observation_key") or ""),
        ) if current else None
        if current_key is None or candidate_key > current_key:
            latest[dataset] = observation
    return latest


def sbv_metrics(history: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    latest_by_dataset = latest_sbv_by_dataset(history)
    source = "State Bank of Vietnam official website"
    specs = [
        ("sbv_omo_awarded", "omo_latest", "omo_awarded_bn_vnd", "Tỷ đồng"),
        ("sbv_omo_rate", "omo_latest", "omo_rate_pct", "%/năm"),
        ("sbv_m2_growth", "money_supply_deposits", "m2_growth_ytd_pct", "%"),
        ("sbv_corp_deposit_growth", "money_supply_deposits", "corp_deposit_growth_ytd_pct", "%"),
        ("sbv_household_deposit_growth", "money_supply_deposits", "household_deposit_growth_ytd_pct", "%"),
    ]
    metrics = []
    for key, dataset, field, unit in specs:
        latest = latest_by_dataset.get(dataset, {})
        value = latest.get(field)
        if value is None:
            continue
        metrics.append({
            "key": key,
            "value": value,
            "unit": unit,
            "as_of": latest.get("source_observation_date") or latest.get("source_as_of") or latest.get("source_date"),
            "fetched_at": latest.get("fetched_at") or latest.get("captured_at"),
            "source": latest.get("source") or source,
            "provenance": latest.get("provenance") or "primary_official_observation",
            "dataset": dataset,
        })
    current: dict[str, Any] = {
        "datasets": latest_by_dataset,
        "source_observation_dates": {
            dataset: node.get("source_observation_date") or node.get("source_as_of") or node.get("source_date")
            for dataset, node in latest_by_dataset.items()
        },
    }
    # Preserve the flat value contract for consumers while keeping dates dataset-specific.
    for node in latest_by_dataset.values():
        for field, value in node.items():
            if field.startswith(("m2_", "corp_", "household_", "omo_")):
                current[field] = value
    return metrics, current


def main() -> None:
    previous = load(OUT, {})
    manifest = load(FOUNDATION / "manifest.json", {})
    macro = load(FOUNDATION / "macro.json", {})
    history = load(FOUNDATION / "sbv_history.json", {"status": "empty", "observations": []})
    watch = load(WATCHLIST, {})

    company_rows: dict[str, Any] = {}
    company_source_dates: list[str] = []
    company_fetch_times: list[str] = []
    for symbol in [str(x).upper() for x in watch.get("fundamental_symbols", [])]:
        item = load(FOUNDATION / "companies" / f"{symbol}.json", {})
        if not item:
            continue
        annual = item.get("reports", {}).get("annual", {})
        report_meta = {}
        for bucket, reports in item.get("reports", {}).items():
            report_meta[bucket] = {}
            for report, node in reports.items():
                report_meta[bucket][report] = {
                    key: node.get(key)
                    for key in (
                        "status", "years", "periods", "source_as_of", "fetched_at", "provider", "source",
                        "provenance", "refresh_status", "last_attempt_at", "last_refresh_error", "error", "fallback",
                    )
                    if node.get(key) is not None
                }
        source_as_of = item.get("source_as_of")
        if source_as_of:
            company_source_dates.append(str(source_as_of))
        report_fetch_times = [
            str(node.get("fetched_at"))
            for reports in item.get("reports", {}).values()
            for node in reports.values()
            if node.get("fetched_at")
        ]
        fetched_at = max(report_fetch_times) if report_fetch_times else item.get("generated_at")
        if fetched_at:
            company_fetch_times.append(str(fetched_at))
        company_rows[symbol] = {
            "symbol": symbol,
            "status": item.get("status"),
            "coverage": item.get("coverage", {}),
            "provider": item.get("provider"),
            "source": item.get("source"),
            "source_as_of": source_as_of,
            "fetched_at": fetched_at,
            "last_attempt_at": item.get("last_attempt_at"),
            "last_refresh_error": item.get("last_refresh_error"),
            "stale_reports": item.get("stale_reports", []),
            "warnings": item.get("warnings", []),
            "report_meta": report_meta,
            "reports": {
                "balance_sheet": annual.get("balance_sheet", {}).get("data", {"columns": [], "rows": []}),
                "income_statement": annual.get("income_statement", {}).get("data", {"columns": [], "rows": []}),
                "cash_flow": annual.get("cash_flow", {}).get("data", {"columns": [], "rows": []}),
                "ratio": annual.get("ratio", {}).get("data", {"columns": [], "rows": []}),
            },
        }

    missing_core = macro.get("coverage", {}).get("missing", [])
    metrics, current_sbv = sbv_metrics(history)
    macro_as_of = macro_source_as_of(macro, metrics)
    warnings: list[str] = []
    errors: list[str] = []
    if not manifest.get("access", {}).get("vnstock_api_key_present"):
        warnings.append("VNSTOCK_API_KEY is not configured; community guest mode may expose fewer than 8 annual periods.")
    stale_macro = list(macro.get("coverage", {}).get("stale", []))
    if not macro.get("coverage", {}).get("state_ready") and missing_core:
        warnings.append("SBV historical state layer is not ready: " + ", ".join(missing_core))
    if stale_macro:
        warnings.append("Macro datasets retained as stale last-known-good: " + ", ".join(stale_macro))
    official_refresh = macro.get("official_refresh") or {}
    if official_refresh.get("status") == "warning":
        refresh_warnings = official_refresh.get("warnings") or []
        warnings.append(
            "SBV official refresh is stale; last-known-good data was retained"
            + (": " + "; ".join(map(str, refresh_warnings)) if refresh_warnings else ".")
        )
    elif official_refresh.get("status") == "error":
        errors.append("SBV official refresh failed structural validation")
    if history.get("status") == "empty":
        warnings.append("SBV official observation history has not started accumulating.")
    elif history.get("status") != "accumulating":
        warnings.append("SBV official observation history is only partially populated across required datasets.")
    for row in manifest.get("companies", []):
        if not row.get("minimum_met"):
            warnings.append(f"{row.get('symbol')}: annual history {row.get('annual_periods', 0)}/8")
        if row.get("status") == "error":
            errors.append(f"{row.get('symbol')}: financial history fetch failed")
        if row.get("status") == "partial" and row.get("last_refresh_error"):
            warnings.append(f"{row.get('symbol')}: latest refresh retained stale data")

    current_market = load(MARKET, {})
    if not current_market:
        current_market = previous.get("market", {})
    if not current_market:
        current_market = {"status": "not_run", "as_of": None, "source": None, "index": {}, "rows": [], "picks": [], "methodology": {}}
    merge_market_health(current_market, warnings, errors)

    ready = bool(manifest.get("foundation_ready"))
    snapshot = {
        "schema_version": "1.2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_status": "ok" if ready and not errors and current_market.get("status") == "ok" else "partial",
        "meta": {
            "principle": "Missing data stays missing. Rootvalue never fabricates financial or macro values.",
            "foundation_ready": ready,
            "history_target": manifest.get("history_target", {}),
        },
        "foundation": manifest,
        "macro": {
            "status": "ok" if macro.get("coverage", {}).get("state_ready") else "partial",
            "as_of": macro_as_of,
            "fetched_at": macro.get("generated_at"),
            "source": [value for value in ["State Bank of Vietnam official website", macro.get("historical_provider")] if value],
            "metrics": metrics,
            "datasets": macro.get("datasets", {}),
            "official_checks": macro.get("official_checks", {}),
            "official_validation": macro.get("official_validation", {}),
            "official_refresh": official_refresh,
            "coverage": macro.get("coverage", {}),
            "missing_core": missing_core,
            "reaction_engine_status": "data_ready" if macro.get("coverage", {}).get("state_ready") else "framework_only",
            "sbv_current": current_sbv,
            "sbv_history": history,
        },
        "market": current_market,
        "companies": {
            "status": "ok" if company_rows and all(v.get("coverage", {}).get("minimum_met") for v in company_rows.values()) else "partial",
            "as_of": latest_source_value(company_source_dates),
            "fetched_at": max(company_fetch_times) if company_fetch_times else manifest.get("generated_at"),
            "source": manifest.get("access", {}).get("fundamental_source"),
            "limitations": "Rootvalue requires at least 8 annual periods for a company to pass foundation QC.",
            "rows": company_rows,
        },
        "health": {"errors": errors, "warnings": warnings},
    }
    changed = save(OUT, snapshot)
    print(f"published foundation -> data/rootvalue.json; ready={ready}; companies={len(company_rows)}; sbv_observations={len(history.get('observations') or [])}; changed={changed}")


if __name__ == "__main__":
    main()
