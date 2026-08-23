from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COMPANY_DIR = ROOT / "data" / "foundation" / "companies"
WATCHLIST = ROOT / "config" / "watchlist.json"
FOUNDATION_CONFIG = ROOT / "config" / "foundation.json"
MANIFEST = ROOT / "data" / "foundation" / "manifest.json"
API_KEY_PRESENT = bool(os.getenv("VNSTOCK_API_KEY", "").strip())
RATE_SECONDS = 1.4 if API_KEY_PRESENT else 4.0
GUEST_BACKOFF_SECONDS = 65.0
_LAST_PROVIDER_CALL = 0.0
_GUEST_BACKOFF_USED = False
_GUEST_PROVIDER_BLOCKED = False
REQUIRED_ANNUAL_REPORTS = ("balance_sheet", "income_statement", "cash_flow")


class ProviderTerminatedError(RuntimeError):
    """Convert provider ``SystemExit`` into a normal, recordable failure."""


def _provider_attempt(fn: Callable[[], Any]) -> Any:
    """Throttle and execute exactly one provider request.

    Some Vnstock guest-limit paths raise ``SystemExit`` instead of an ordinary
    exception. Letting that escape terminates the entire GitHub Actions step,
    so translate it here while still counting the failed call against the
    request-rate budget.
    """
    global _LAST_PROVIDER_CALL
    elapsed = time.monotonic() - _LAST_PROVIDER_CALL
    if _LAST_PROVIDER_CALL and elapsed < RATE_SECONDS:
        time.sleep(RATE_SECONDS - elapsed)
    try:
        return fn()
    except SystemExit as exc:
        detail = str(exc).strip() or "provider requested process exit"
        raise ProviderTerminatedError(detail) from exc
    finally:
        _LAST_PROVIDER_CALL = time.monotonic()


def provider_call(fn: Callable[[], Any]) -> Any:
    """Run a provider request with one bounded guest-quota recovery attempt."""
    global _GUEST_BACKOFF_USED, _GUEST_PROVIDER_BLOCKED
    if _GUEST_PROVIDER_BLOCKED:
        raise ProviderTerminatedError(
            "provider guest quota remained unavailable after the bounded retry"
        )
    try:
        return _provider_attempt(fn)
    except ProviderTerminatedError as first_error:
        if API_KEY_PRESENT or _GUEST_BACKOFF_USED:
            raise first_error
        _GUEST_BACKOFF_USED = True
        # Guest quota is measured per minute. A single bounded wait crosses
        # that window without turning an upstream outage into an endless job.
        time.sleep(GUEST_BACKOFF_SECONDS)
        try:
            return _provider_attempt(fn)
        except ProviderTerminatedError as retry_error:
            _GUEST_PROVIDER_BLOCKED = True
            raise ProviderTerminatedError(
                "provider guest quota remained unavailable after one 65-second retry: "
                f"{retry_error}"
            ) from retry_error


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


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
    stale_reports = [
        f"{bucket}.{report}"
        for bucket, reports in item.get("reports", {}).items()
        for report, node in reports.items()
        if node.get("refresh_status") == "stale"
    ]
    minimum_met = len(common) >= target and all(required_ready.values())
    available_required = sum(bool(per_report[report]) for report in REQUIRED_ANNUAL_REPORTS)
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


def normalize_empty_report_statuses(item: dict[str, Any]) -> list[str]:
    """Repair the historical contract bug that labelled empty provider results as OK."""
    changes: list[str] = []
    for bucket, reports in item.get("reports", {}).items():
        if not isinstance(reports, dict):
            continue
        for report, node in reports.items():
            if not isinstance(node, dict):
                continue
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            rows = data.get("rows") if isinstance(data.get("rows"), list) else []
            if "row_count" in data and data.get("row_count") != len(rows):
                data["row_count"] = len(rows)
                changes.append(f"{bucket}.{report}.row_count")
            if node.get("status") == "ok" and not rows:
                node["status"] = "empty"
                node["refresh_status"] = "empty"
                node["years"] = []
                node["periods"] = []
                node["source_as_of"] = None
                changes.append(f"{bucket}.{report}.status")
    return changes


def refresh_manifest_from_companies(symbols: list[str] | None = None) -> bool:
    """Synchronize manifest company QC after company snapshots change."""
    manifest = load(MANIFEST, {})
    if not manifest:
        return False
    if symbols is None:
        watch = load(WATCHLIST, {})
        symbols = [str(value).upper() for value in watch.get("fundamental_symbols", [])]

    company_summary: list[dict[str, Any]] = []
    for symbol in symbols:
        item = load(COMPANY_DIR / f"{symbol}.json", {})
        coverage = item.get("coverage", {})
        ready = bool(coverage.get("minimum_met")) and item.get("status") == "ready"
        company_summary.append({
            "symbol": symbol,
            "status": item.get("status", "error"),
            "annual_periods": coverage.get("annual_periods", 0),
            "minimum_met": bool(coverage.get("minimum_met")),
            "ready_for_foundation": ready,
            "required_reports_ready": coverage.get("required_reports_ready", {}),
            "stale_reports": item.get("stale_reports", []),
            "source_as_of": item.get("source_as_of"),
            "generated_at": item.get("generated_at"),
            "last_attempt_at": item.get("last_attempt_at"),
            "last_refresh_error": item.get("last_refresh_error"),
            "provider": item.get("provider"),
        })

    ready_count = sum(1 for row in company_summary if row["ready_for_foundation"])
    updated_manifest = {
        **manifest,
        "companies": company_summary,
        "company_qc": {
            "requested": len(symbols),
            "minimum_8y_ready": ready_count,
            "all_minimum_ready": bool(symbols) and ready_count == len(symbols),
        },
        "foundation_ready": (
            bool(symbols)
            and ready_count == len(symbols)
            and bool(manifest.get("macro_qc", {}).get("state_ready"))
        ),
        "policy": "Data foundation is READY only when every required annual report has >=8 common periods for every configured company and every required SBV-state historical series is present.",
    }
    if updated_manifest == manifest:
        return False
    save(MANIFEST, updated_manifest)
    return True


def normalize_existing_snapshots() -> dict[str, Any]:
    watch = load(WATCHLIST, {})
    config = load(FOUNDATION_CONFIG, {})
    symbols = [str(value).upper() for value in watch.get("fundamental_symbols", [])]
    changed_files: list[str] = []
    normalized_nodes: list[str] = []
    for symbol in symbols:
        path = COMPANY_DIR / f"{symbol}.json"
        original = load(path, {})
        if not original:
            continue
        item = json.loads(json.dumps(original))
        changes = normalize_empty_report_statuses(item)
        item = recompute_company_quality(item, config)
        if item != original:
            save(path, item)
            changed_files.append(path.name)
        normalized_nodes.extend(f"{symbol}:{change}" for change in changes)

    if refresh_manifest_from_companies(symbols):
        changed_files.append(str(MANIFEST.relative_to(ROOT)))
    return {"mode": "normalize-only", "changed_files": changed_files, "normalized_nodes": normalized_nodes}


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
        obj = provider_call(lambda: fun.equity(symbol))
        fn = obj.balance_sheet
        for kwargs in (
            {"period": period, "orient": "report", "dropna": False},
            {"period": period, "orient": "report"},
            {"period": period, "dropna": False},
            {"period": period},
        ):
            try:
                df = provider_call(lambda kwargs=kwargs: fn(**kwargs))
                if isinstance(df, pd.DataFrame) and not df.empty:
                    return df
            except ProviderTerminatedError:
                raise
            except Exception as exc:
                errors.append(str(exc))
    except ProviderTerminatedError:
        raise
    except Exception as exc:
        errors.append(str(exc))
    raise RuntimeError("Unified UI empty: " + "; ".join(errors[-4:]))


def call_legacy_balance_sheet(symbol: str, period: str) -> tuple[pd.DataFrame, str]:
    # Vnstock's official v4 documentation still exposes the legacy Finance facade.
    # Keep it only as a resilience fallback when Unified UI returns an empty balance sheet.
    errors: list[str] = []
    try:
        from vnstock import Finance  # type: ignore
    except SystemExit as exc:
        detail = str(exc).strip() or "provider requested process exit during import"
        raise ProviderTerminatedError(detail) from exc
    except Exception as exc:
        raise RuntimeError(f"Finance import unavailable: {exc}")

    for source in ("KBS", "VCI"):
        try:
            finance = provider_call(lambda source=source: Finance(symbol=symbol, source=source))
            fn = finance.balance_sheet
            for kwargs in (
                {"period": period, "lang": "vi", "dropna": False},
                {"period": period, "lang": "vi"},
                {"period": period},
            ):
                try:
                    df = provider_call(lambda kwargs=kwargs: fn(**kwargs))
                    if isinstance(df, pd.DataFrame) and not df.empty:
                        return df, source
                except ProviderTerminatedError:
                    raise
                except Exception as exc:
                    errors.append(f"{source}:{exc}")
        except ProviderTerminatedError:
            raise
        except Exception as exc:
            errors.append(f"{source}:{exc}")
    raise RuntimeError("Legacy Finance empty: " + "; ".join(errors[-6:]))


def repair_balance_sheet(fun: Any, symbol: str, period: str) -> tuple[pd.DataFrame, str]:
    try:
        return call_unified_balance_sheet(fun, symbol, period), "Unified UI"
    except ProviderTerminatedError:
        raise
    except Exception as first:
        try:
            df, source = call_legacy_balance_sheet(symbol, period)
            return df, f"Legacy Finance/{source}"
        except Exception as second:
            raise RuntimeError(f"{first}; {second}")


def main(normalize_only: bool = False) -> None:
    if normalize_only:
        print(json.dumps(normalize_existing_snapshots(), ensure_ascii=False))
        return

    from build_foundation import public_error

    try:
        from vnstock import Fundamental
    except SystemExit as exc:
        failure = ProviderTerminatedError(
            str(exc).strip() or "provider requested process exit during import"
        )
        print(json.dumps({
            "repaired": [],
            "failures": [f"provider import: {public_error(failure)}"],
        }, ensure_ascii=False))
        return

    watch = load(WATCHLIST, {})
    foundation_config = load(FOUNDATION_CONFIG, {})
    symbols = [str(x).upper() for x in watch.get("fundamental_symbols", [])]
    repaired: list[str] = []
    failures: list[str] = []
    try:
        fun = provider_call(Fundamental)
    except ProviderTerminatedError as exc:
        failures.append(f"provider initialization: {public_error(exc)}")
        print(json.dumps({"repaired": repaired, "failures": failures}, ensure_ascii=False))
        return

    for symbol in symbols:
        path = COMPANY_DIR / f"{symbol}.json"
        item = load(path, {})
        if not item:
            continue
        for bucket, period in (("annual", "year"), ("quarterly", "quarter")):
            bs = item.get("reports", {}).get(bucket, {}).get("balance_sheet", {})
            if bs.get("data", {}).get("rows"):
                continue
            try:
                df, fallback = repair_balance_sheet(fun, symbol, period)
                ys = years(df)
                item["reports"][bucket]["balance_sheet"] = {
                    "status": "ok",
                    "years": ys,
                    "source_as_of": str(ys[-1]) if ys else None,
                    "data": payload(df),
                    "fallback": fallback,
                    "provider": "vnstock",
                    "source": f"{fallback} via Vnstock community",
                    "provenance": "secondary_normalized_provider",
                    "refresh_status": "fresh",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
                if bucket == "quarterly":
                    merged_q = sorted(set(item.get("coverage", {}).get("quarterly_years", [])) | set(ys))
                    item["coverage"]["quarterly_years"] = merged_q
                item["last_repair_at"] = datetime.now(timezone.utc).isoformat()
                repaired.append(f"{symbol}:{bucket}:{fallback}")
            except Exception as exc:
                message = f"{bucket}.balance_sheet fallback: {public_error(exc)}"
                warnings = item.setdefault("warnings", [])
                if message not in warnings:
                    warnings.append(message)
                failures.append(f"{symbol}:{bucket}: {public_error(exc)}")
        item = recompute_company_quality(item, foundation_config)
        save(path, item)

    manifest_changed = refresh_manifest_from_companies(symbols)
    print(json.dumps({
        "repaired": repaired,
        "failures": failures,
        "manifest_changed": manifest_changed,
    }, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Repair or normalize stored company financial reports.")
    parser.add_argument(
        "--normalize-only",
        action="store_true",
        help="Apply deterministic stored-data contract repairs without calling external providers.",
    )
    args = parser.parse_args()
    main(normalize_only=args.normalize_only)
