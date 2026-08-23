from __future__ import annotations

import json
import math
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FOUNDATION = DATA / "foundation"
CORE_REPORTS = ("balance_sheet", "income_statement", "cash_flow")
MARKET_NUMERIC_FIELDS = (
    "close",
    "return_1d",
    "return_20d",
    "rs_20d_vs_vnindex",
    "rs_20d_vs_vnindex_5d_ago",
    "volume_participation_5d_vs_20d",
    "range_position_20d",
)
SECRET_PATTERN = re.compile(
    r"(?:"
    r"\b(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret|authorization)\b"
    r"\s*['\"]?\s*[:=]\s*['\"]?\s*"
    r"(?:bearer\s+(?!<redacted>)[a-z0-9._~+/=-]{6,}"
    r"|(?!bearer\b|<redacted>)[a-z0-9._~+/=-]{6,})"
    r"|\bbearer\s+(?!<redacted>)[a-z0-9._~+/=-]{8,}"
    r")",
    flags=re.I,
)


def load_json(path: Path, errors: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing JSON file: {path.relative_to(ROOT)}")
    except Exception as exc:
        errors.append(f"invalid JSON {path.relative_to(ROOT)}: {exc}")
    return {}


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}", raw):
            return date.fromisoformat(raw + "-01")
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None


def ensure_timestamp(value: Any, context: str, errors: list[str], *, required: bool = True) -> None:
    if not value:
        if required:
            errors.append(f"{context}: timestamp missing")
        return
    parsed = parse_date(value)
    if parsed is None:
        errors.append(f"{context}: invalid date/timestamp {value!r}")
    elif parsed > datetime.now(timezone.utc).date() + timedelta(days=1):
        errors.append(f"{context}: timestamp is in the future ({value})")


def public_error_strings(node: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if isinstance(value, str) and any(token in str(key).lower() for token in ("error", "warning")):
                yield child, value
            yield from public_error_strings(value, child)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            child = f"{path}[{index}]"
            if isinstance(value, str) and any(token in path.lower() for token in ("error", "warning")):
                yield child, value
            else:
                yield from public_error_strings(value, child)


def validate_market(market: dict[str, Any], watch: dict[str, Any], errors: list[str], notes: list[str]) -> None:
    rows = market.get("rows")
    if not isinstance(rows, list):
        errors.append("market.rows must be a list")
        return
    if rows:
        ensure_timestamp(market.get("as_of"), "market.as_of", errors)

    configured = [str(x.get("symbol", "")).upper() for x in watch.get("symbols", []) if x.get("symbol")]
    symbols = [str(row.get("symbol", "")).upper() for row in rows]
    full_universe = bool(configured) and set(symbols) == set(configured)
    if any(not symbol for symbol in symbols):
        errors.append("market row with missing symbol")
    if len(symbols) != len(set(symbols)):
        errors.append("market.rows contains duplicate symbols")

    if market.get("status") == "ok" and not full_universe:
        missing = sorted(set(configured) - set(symbols))
        extra = sorted(set(symbols) - set(configured))
        errors.append(f"market status=ok but universe differs; missing={missing}, extra={extra}")
    elif len(symbols) < len(configured):
        notes.append(f"market coverage is partial: {len(symbols)}/{len(configured)}")
    if market.get("status") == "stale":
        notes.append("market snapshot is stale; values and picks are last-known-good")

    ranks: list[int] = []
    for row in rows:
        symbol = str(row.get("symbol") or "?")
        ensure_timestamp(row.get("as_of"), f"market.{symbol}.as_of", errors)
        for field in MARKET_NUMERIC_FIELDS:
            value = row.get(field)
            if value is not None and not finite(value):
                errors.append(f"market.{symbol}.{field} must be finite or null")
        position = row.get("range_position_20d")
        if finite(position) and not 0 <= float(position) <= 1:
            errors.append(f"market.{symbol}.range_position_20d outside [0,1]")
        participation = row.get("volume_participation_5d_vs_20d")
        if finite(participation) and float(participation) < 0:
            errors.append(f"market.{symbol}.volume_participation_5d_vs_20d is negative")
        rank = row.get("rank_current")
        if rank is not None:
            if not isinstance(rank, int) or rank < 1:
                errors.append(f"market.{symbol}.rank_current must be a positive integer or null")
            else:
                ranks.append(rank)
        sparkline = row.get("sparkline") or []
        if not isinstance(sparkline, list) or any(value is not None and not finite(value) for value in sparkline):
            errors.append(f"market.{symbol}.sparkline must contain only finite numbers or null")
        if row.get("state") not in {"Leading", "Improving", "Neutral", "Weakening"}:
            errors.append(f"market.{symbol}.state is invalid")

    if ranks and (len(ranks) != len(set(ranks)) or sorted(ranks) != list(range(1, len(ranks) + 1))):
        errors.append("market.rank_current must be unique and contiguous")

    picks = market.get("picks") or []
    pick_symbols = [str(row.get("symbol") or "") for row in picks]
    if len(pick_symbols) != len(set(pick_symbols)):
        errors.append("market.picks contains duplicate symbols")
    if picks and market.get("status") not in {"ok", "stale"}:
        errors.append("market publishes picks while universe status is neither ok nor stale")
    if picks and not full_universe:
        errors.append("market publishes picks from an incomplete configured universe")
    for pick in picks:
        if pick.get("symbol") not in symbols:
            errors.append(f"market pick {pick.get('symbol')} is not present in rows")

    allowed_selection_types = {"RelativeStrengthLeader", "AbnormalMovement"}
    selected_by_sector = market.get("selection_by_sector") or {}
    if not isinstance(selected_by_sector, dict):
        errors.append("market.selection_by_sector must be an object")
        selected_by_sector = {}
    abnormal_min = 3
    abnormal_text = str((market.get("selection_method") or {}).get("abnormal") or "")
    match = re.search(r">=\s*(\d+)", abnormal_text)
    if match:
        abnormal_min = int(match.group(1))
    row_by_symbol = {str(row.get("symbol") or ""): row for row in rows}
    for sector, selected in selected_by_sector.items():
        if not isinstance(selected, list):
            errors.append(f"market.selection_by_sector.{sector} must be a list")
            continue
        types = [str(item.get("selection_type") or "") for item in selected]
        unknown = sorted(set(types) - allowed_selection_types)
        if unknown:
            errors.append(f"market selection uses misleading/unknown types in {sector}: {unknown}")
        if types.count("RelativeStrengthLeader") > 3:
            errors.append(f"market selection has more than 3 relative-strength leaders in {sector}")
        if types.count("AbnormalMovement") > 2:
            errors.append(f"market selection has more than 2 abnormal movements in {sector}")
        selected_symbols = [str(item.get("symbol") or "") for item in selected]
        if len(selected_symbols) != len(set(selected_symbols)):
            errors.append(f"market selection contains duplicate symbols in {sector}")
        for item in selected:
            symbol = str(item.get("symbol") or "")
            canonical = row_by_symbol.get(symbol)
            if canonical is None or str(canonical.get("sector") or "Other") != str(sector):
                errors.append(f"market selection {sector}.{symbol} is outside its canonical peer group")
            selection_type = item.get("selection_type")
            if selection_type == "RelativeStrengthLeader" and int(item.get("sector_rank") or 999) > 3:
                errors.append(f"market selection {sector}.{symbol} is labelled RS leader below rank 3")
            if selection_type == "AbnormalMovement":
                delta = item.get("rank_delta")
                if not isinstance(delta, int) or abs(delta) < abnormal_min:
                    errors.append(f"market selection {sector}.{symbol} does not meet abnormal rank threshold")


def validate_global(global_data: dict[str, Any], errors: list[str], notes: list[str]) -> None:
    series = global_data.get("series")
    if not isinstance(series, dict) or not series:
        errors.append("global.series must be a non-empty object")
        return
    for key, node in series.items():
        if not isinstance(node, dict):
            errors.append(f"global.series.{key} must be an object")
            continue
        status = node.get("status")
        history = node.get("history") or []
        if status in {"ok", "stale"} and not history:
            errors.append(f"global.series.{key} status={status} without history")
            continue
        dates: list[str] = []
        for index, point in enumerate(history):
            when = point.get("date") if isinstance(point, dict) else None
            value = point.get("value") if isinstance(point, dict) else None
            ensure_timestamp(when, f"global.series.{key}.history[{index}].date", errors)
            if not finite(value):
                errors.append(f"global.series.{key}.history[{index}].value must be finite")
            dates.append(str(when))
        if dates and (dates != sorted(dates) or len(dates) != len(set(dates))):
            errors.append(f"global.series.{key}.history dates must be sorted and unique")
        if history:
            last = history[-1]
            if node.get("as_of") != last.get("date") or node.get("latest") != last.get("value"):
                errors.append(f"global.series.{key} latest/as_of does not match final history point")
        if status == "stale":
            notes.append(f"global series stale: {key}")

    allowed_news_hosts = {
        "www.federalreserve.gov",
        "federalreserve.gov",
        "www.ecb.europa.eu",
        "ecb.europa.eu",
    }
    for index, item in enumerate(global_data.get("news") or []):
        url = str(item.get("url") or "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in allowed_news_hosts:
            errors.append(f"global.news[{index}] URL is not an approved HTTPS source: {url!r}")


def report_payload(item: dict[str, Any], bucket: str, report: str) -> dict[str, Any]:
    return item.get("reports", {}).get(bucket, {}).get(report, {}) or {}


def report_rows(payload: dict[str, Any]) -> list[Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    rows = data.get("rows") if isinstance(data, dict) else []
    return rows if isinstance(rows, list) else []


def validate_foundation(manifest: dict[str, Any], errors: list[str], notes: list[str]) -> None:
    companies = manifest.get("companies") or []
    for summary in companies:
        symbol = str(summary.get("symbol") or "")
        if not symbol:
            errors.append("foundation manifest company without symbol")
            continue
        item = load_json(FOUNDATION / "companies" / f"{symbol}.json", errors)
        if not item:
            continue
        for bucket in ("annual", "quarterly"):
            for report, payload in (item.get("reports", {}).get(bucket, {}) or {}).items():
                status = payload.get("status")
                data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
                columns = data.get("columns") if isinstance(data, dict) else []
                rows = report_rows(payload)
                if not isinstance(columns, list):
                    errors.append(f"{symbol}.{bucket}.{report}.columns must be a list")
                    columns = []
                if len([str(column) for column in columns]) != len(set(str(column) for column in columns)):
                    errors.append(f"{symbol}.{bucket}.{report} contains duplicate columns")
                for index, row in enumerate(rows):
                    if not isinstance(row, list) or len(row) != len(columns):
                        errors.append(f"{symbol}.{bucket}.{report}.rows[{index}] width differs from columns")
                if status == "ok" and not rows:
                    errors.append(f"{symbol}.{bucket}.{report} status=ok but rows are empty")
                if status == "empty" and rows:
                    errors.append(f"{symbol}.{bucket}.{report} status=empty but rows are present")
        for report in CORE_REPORTS:
            payload = report_payload(item, "annual", report)
            if not report_rows(payload):
                notes.append(f"foundation coverage missing: {symbol}.{report}.annual")

    macro_qc = manifest.get("macro_qc") or {}
    if manifest.get("foundation_ready"):
        if not companies or not all(bool(row.get("minimum_met")) for row in companies):
            errors.append("foundation_ready=true while a company minimum is not met")
        if not macro_qc.get("state_ready"):
            errors.append("foundation_ready=true while macro_qc.state_ready is false")
    else:
        notes.append("foundation coverage is intentionally not READY")


def validate_sbv_history(history: dict[str, Any], errors: list[str], notes: list[str]) -> None:
    observations = history.get("observations") or []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(observations):
        source_date = item.get("source_observation_date") or item.get("source_as_of")
        table_id = str(item.get("source_table_id") or item.get("dataset") or "")
        if source_date:
            ensure_timestamp(source_date, f"sbv_history.observations[{index}].source_date", errors)
            key = (str(source_date), table_id)
            if key in seen:
                errors.append(f"duplicate SBV source observation {key}")
            seen.add(key)
        elif history.get("schema_version") not in {"1.0.0", 1}:
            errors.append(f"sbv_history observation {index} lacks a source observation date")
        else:
            notes.append("legacy SBV capture exists without a verified source date")


def validate_dashboard(dashboard: dict[str, Any], errors: list[str], notes: list[str]) -> None:
    companies = dashboard.get("companies")
    if not isinstance(companies, dict):
        errors.append("company_dashboard.companies must be an object")
        return
    for symbol, company in companies.items():
        for frequency in ("annual", "quarterly"):
            block = company.get(frequency) or {}
            for name, points in (block.get("series") or {}).items():
                if not isinstance(points, list):
                    errors.append(f"dashboard.{symbol}.{frequency}.{name} must be a list")
                    continue
                periods: list[str] = []
                for index, point in enumerate(points):
                    if not isinstance(point, dict) or not point.get("period") or not finite(point.get("value")):
                        errors.append(f"dashboard.{symbol}.{frequency}.{name}[{index}] invalid point")
                        continue
                    periods.append(str(point["period"]))
                if len(periods) != len(set(periods)):
                    errors.append(f"dashboard.{symbol}.{frequency}.{name} has duplicate periods")
            availability = block.get("report_availability") or {}
            if frequency == "annual" and not all(availability.get(name) for name in CORE_REPORTS):
                notes.append(f"dashboard coverage partial: {symbol}.{frequency}")


def validate_root_snapshot(root: dict[str, Any], market: dict[str, Any], errors: list[str]) -> None:
    if root.get("pipeline_status") not in {"ok", "partial", "error", "not_run"}:
        errors.append("rootvalue.pipeline_status is invalid")
    ensure_timestamp(root.get("generated_at"), "rootvalue.generated_at", errors)
    health = root.get("health") or {}
    if not isinstance(health.get("errors", []), list) or not isinstance(health.get("warnings", []), list):
        errors.append("rootvalue.health errors/warnings must be lists")

    embedded = root.get("market") or {}
    if market:
        if embedded.get("status") != market.get("status") or embedded.get("as_of") != market.get("as_of"):
            errors.append("rootvalue.market is not synchronized with data/market.json")
        if len(embedded.get("rows") or []) != len(market.get("rows") or []):
            errors.append("rootvalue.market row count differs from data/market.json")


def validate_macro(macro: dict[str, Any], errors: list[str], notes: list[str]) -> None:
    validation = macro.get("official_validation") or {}
    if validation.get("status") != "pass":
        errors.append("foundation.macro official SBV validation is not pass")
    datasets = validation.get("datasets")
    if not isinstance(datasets, dict):
        errors.append("foundation.macro official SBV validation lacks per-dataset results")
    else:
        for name in ("money_supply_deposits", "omo_latest"):
            if (datasets.get(name) or {}).get("status") != "pass":
                errors.append(f"foundation.macro official SBV dataset {name} is not pass")

    refresh = macro.get("official_refresh") or {}
    refresh_status = refresh.get("status")
    if refresh_status not in {"ok", "warning"}:
        errors.append("foundation.macro official SBV refresh status is not usable")
    elif refresh_status == "warning":
        notes.append("official SBV refresh stale: last-known-good retained")


def validate_all() -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    root = load_json(DATA / "rootvalue.json", errors)
    market = load_json(DATA / "market.json", errors)
    global_data = load_json(DATA / "global.json", errors)
    dashboard = load_json(DATA / "company_dashboard.json", errors)
    manifest = load_json(FOUNDATION / "manifest.json", errors)
    macro = load_json(FOUNDATION / "macro.json", errors)
    sbv_history = load_json(FOUNDATION / "sbv_history.json", errors)
    watch = load_json(ROOT / "config" / "watchlist.json", errors)

    if market:
        validate_market(market, watch, errors, notes)
    if global_data:
        validate_global(global_data, errors, notes)
    if manifest:
        validate_foundation(manifest, errors, notes)
    if macro:
        validate_macro(macro, errors, notes)
    if sbv_history:
        validate_sbv_history(sbv_history, errors, notes)
    if dashboard:
        validate_dashboard(dashboard, errors, notes)
    if root:
        validate_root_snapshot(root, market, errors)

    for name, node in (
        ("rootvalue", root),
        ("market", market),
        ("global", global_data),
        ("foundation", manifest),
        ("foundation_macro", macro),
    ):
        for path, value in public_error_strings(node, name):
            if SECRET_PATTERN.search(value):
                errors.append(f"{path} may expose a credential")

    return errors, sorted(set(notes))


def main() -> int:
    errors, notes = validate_all()
    if errors:
        print("Rootvalue data-contract QA: FAIL")
        for error in errors:
            print(f" - {error}")
        if notes:
            print("Coverage notes (non-fatal):")
            for note in notes:
                print(f" - {note}")
        return 1

    print("Rootvalue data-contract QA: PASS")
    for note in notes:
        print(f" - {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
