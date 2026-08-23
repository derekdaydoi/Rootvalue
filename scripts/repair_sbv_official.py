from __future__ import annotations

import argparse
import json
import hashlib
import math
import re
import unicodedata
from calendar import monthrange
from copy import deepcopy
from datetime import date, datetime, timezone
from html import unescape
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "foundation.json"
MACRO = ROOT / "data" / "foundation" / "macro.json"
VOLATILE_FIELDS = {"generated_at", "fetched_at", "last_attempt_at"}
RETRYABLE_HTTP_STATUS = {408, 425, 429}


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def public_error(value: Any, limit: int = 320) -> str:
    """Return a bounded provider error with URLs and credential-like values removed."""
    text = re.sub(r"https?://\S+", "<redacted-url>", str(value or ""))
    names = (
        r"api[_ -]?key|access[_ -]?token|refresh[_ -]?token|id[_ -]?token|token|"
        r"authorization|client[_ -]?secret|password|secret"
    )
    quoted = re.compile(rf"(?i)([\"']?(?:{names})[\"']?\s*[:=]\s*)([\"'])(.*?)(\2)")
    text = quoted.sub(
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>{match.group(2)}",
        text,
    )
    text = re.sub(
        r"(?i)\b(Bearer|Basic|Token)\s+[A-Za-z0-9._~+/=-]+",
        r"\1 <redacted>",
        text,
    )
    text = re.sub(
        rf"(?i)([\"']?(?:{names})[\"']?\s*[:=]\s*)(?:Bearer\s+)?[^\s,;}}\]]+",
        r"\1<redacted>",
        text,
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] or "provider error"


def semantic_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: semantic_payload(item)
            for key, item in value.items()
            if key not in VOLATILE_FIELDS
        }
    if isinstance(value, list):
        return [semantic_payload(item) for item in value]
    return value


def save_if_changed(path: Path, value: Any) -> bool:
    previous = load(path, None)
    if previous is not None and semantic_payload(previous) == semantic_payload(value):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    return True


def jsonable(v: Any) -> Any:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    if hasattr(v, "item"):
        try:
            v = v.item()
        except Exception:
            pass
    return v if isinstance(v, (str, int, float, bool)) else str(v)


def payload(df: pd.DataFrame) -> dict[str, Any]:
    return {
        "columns": [str(c) for c in df.columns],
        "rows": [[jsonable(v) for v in row] for row in df.itertuples(index=False, name=None)],
        "row_count": int(len(df)),
    }


def plain(v: Any) -> str:
    text = unicodedata.normalize("NFKD", str(v or ""))
    return re.sub(r"\s+", " ", "".join(ch for ch in text if not unicodedata.combining(ch)).lower()).strip()


def iso_date(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def extract_source_date(html: str) -> tuple[str | None, str | None]:
    # The page body often contains the actual observation date while a compact
    # DD.MM.YY value in the title is only a publication label. Prefer the
    # explicit Vietnamese full-year body form to avoid selecting the wrong year.
    visible_text = re.sub(r"<[^>]+>", " ", unescape(html or ""))
    visible_text = re.sub(r"\s+", " ", visible_text).strip()
    normalized_text = plain(visible_text)
    full_date = re.search(
        r"\bngay\s*(\d{1,2})\s*thang\s*(\d{1,2})\s*nam\s*(20\d{2})\b",
        normalized_text,
    )
    if full_date:
        day, month, year = (int(value) for value in full_date.groups())
        value = iso_date(year, month, day)
        if value:
            return value, "Vietnamese body date: Ngày DD tháng MM năm YYYY"

    candidates = [
        (r'"datePublished"\s*:\s*"(20\d{2})-(\d{2})-(\d{2})', "datePublished"),
        (r'<time[^>]+datetime=["\'](20\d{2})-(\d{2})-(\d{2})', "time.datetime"),
        (
            r"(?:ngay\s*(?:dang|cap nhat)?|cap nhat)\D{0,40}(\d{1,2})[./-](\d{1,2})[./-](20\d{2})",
            "dated page label",
        ),
    ]
    for pattern, evidence in candidates:
        search_text = html if evidence in {"datePublished", "time.datetime"} else normalized_text
        match = re.search(pattern, search_text, re.IGNORECASE)
        if not match:
            continue
        parts = [int(value) for value in match.groups()]
        if evidence in {"datePublished", "time.datetime"}:
            value = iso_date(parts[0], parts[1], parts[2])
        else:
            value = iso_date(parts[2], parts[1], parts[0])
        if value:
            return value, evidence

    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html or "")
    if title_match:
        normalized_title = plain(unescape(re.sub(r"<[^>]+>", " ", title_match.group(1))))
        compact_date = re.search(r"\b(\d{1,2})[.]([01]?\d)[.](\d{2})\b", normalized_title)
        if compact_date:
            day, month, short_year = (int(value) for value in compact_date.groups())
            value = iso_date(2000 + short_year, month, day)
            if value:
                return value, "two-digit dotted title date"

    month_match = re.search(
        r"(?:den|tai)?\s*thang\s*(\d{1,2})\s*[/-]\s*(20\d{2})",
        normalized_text,
    )
    if month_match:
        month, year = (int(value) for value in month_match.groups())
        if 1 <= month <= 12:
            return iso_date(year, month, monthrange(year, month)[1]), "source month end"
    return None, None


def schema_fingerprint(tables: list[dict[str, Any]]) -> str | None:
    if not tables:
        return None
    columns = [table.get("columns", []) for table in tables]
    raw = json.dumps(columns, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def number(v: Any) -> float | None:
    if isinstance(v, (int, float)):
        value = float(v)
        return value if math.isfinite(value) else None
    try:
        raw = str(v).strip().replace(" ", "")
        if not raw:
            return None
        if "," in raw and "." in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif "," in raw:
            raw = raw.replace(",", ".")
        value = float(raw)
        return value if math.isfinite(value) else None
    except Exception:
        return None


def fetch_failure(
    url: str,
    label: str,
    error: Any,
    *,
    failure_kind: str,
    transient: bool,
    http_succeeded: bool,
    http_status: int | None = None,
) -> dict[str, Any]:
    return {
        "status": "error",
        "label": label,
        "url": url,
        "source": "State Bank of Vietnam official website",
        "provenance": "primary_official",
        "numeric_locale": "vi-VN: decimal comma, thousands dot",
        "source_date": None,
        "source_date_evidence": None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "schema_fingerprint": None,
        "tables": [],
        "failure_kind": failure_kind,
        "transient_error": transient,
        "http_succeeded": http_succeeded,
        "http_status": http_status,
        "error": public_error(error),
    }


def classify_request_failure(exc: Exception, requests_module: Any) -> tuple[bool, str, int | None]:
    """Classify only explicitly retryable transport/HTTP failures as transient."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    try:
        http_status = int(status) if status is not None else None
    except (TypeError, ValueError):
        http_status = None

    if http_status is not None:
        retryable = http_status in RETRYABLE_HTTP_STATUS or 500 <= http_status <= 599
        return (
            retryable,
            "transient_http_error" if retryable else "hard_http_error",
            http_status,
        )

    exception_namespace = getattr(requests_module, "exceptions", None)
    transient_types = tuple(
        exception_type
        for exception_type in (
            getattr(exception_namespace, "ConnectionError", None),
            getattr(exception_namespace, "Timeout", None),
        )
        if isinstance(exception_type, type)
    )
    if transient_types and isinstance(exc, transient_types):
        return True, "transient_transport_error", None
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True, "transient_transport_error", None
    return False, "hard_request_error", None


def fetch_tables(url: str, label: str) -> dict[str, Any]:
    if not str(url or "").strip():
        return fetch_failure(
            url,
            label,
            "official SBV source URL is not configured",
            failure_kind="configuration_error",
            transient=False,
            http_succeeded=False,
        )

    try:
        import requests
    except Exception as exc:
        return fetch_failure(
            url,
            label,
            exc,
            failure_kind="dependency_import_error",
            transient=True,
            http_succeeded=False,
        )

    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Rootvalue/1.0 personal-research"})
        r.raise_for_status()
    except Exception as exc:
        transient, failure_kind, http_status = classify_request_failure(exc, requests)
        return fetch_failure(
            url,
            label,
            exc,
            failure_kind=failure_kind,
            transient=transient,
            http_succeeded=False,
            http_status=http_status,
        )

    try:
        # SBV tables use Vietnamese formatting: 20.414.616 and 4,99.
        # Explicit locale parsing avoids dangerous conversions such as 4,99 -> 499.
        tables = pd.read_html(StringIO(r.text), decimal=",", thousands=".")
        usable = [t for t in tables if isinstance(t, pd.DataFrame) and not t.empty]
        table_payloads = [payload(t) for t in usable[:5]]
        source_date, date_evidence = extract_source_date(r.text)
        return {
            "status": "ok" if usable else "empty",
            "label": label,
            "url": url,
            "source": "State Bank of Vietnam official website",
            "provenance": "primary_official",
            "numeric_locale": "vi-VN: decimal comma, thousands dot",
            "source_date": source_date,
            "source_date_evidence": date_evidence,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "schema_fingerprint": schema_fingerprint(table_payloads),
            "tables": table_payloads,
            "failure_kind": None,
            "transient_error": False,
            "http_succeeded": True,
        }
    except Exception as exc:
        # The server responded successfully, so parser/schema failures are a
        # hard data-quality failure rather than a transient source outage.
        return fetch_failure(
            url,
            label,
            exc,
            failure_kind="content_parse_error",
            transient=False,
            http_succeeded=True,
        )


def validation_check(errors: list[str], **details: Any) -> dict[str, Any]:
    unique = list(dict.fromkeys(errors))
    return {
        "status": "pass" if not unique else "fail",
        "errors": unique,
        **details,
    }


def common_validation_checks(node: dict[str, Any]) -> dict[str, dict[str, Any]]:
    source_errors: list[str] = []
    if node.get("status") != "ok":
        source_errors.append(f"source status is {node.get('status', 'missing')}")

    date_errors: list[str] = []
    source_date = node.get("source_date")
    parsed_date = None
    if not source_date:
        date_errors.append("source observation/publication date is missing")
    else:
        try:
            parsed_date = datetime.fromisoformat(str(source_date).replace("Z", "+00:00")).date()
            if parsed_date > datetime.now(timezone.utc).date():
                date_errors.append("source date is in the future")
        except (TypeError, ValueError):
            date_errors.append("source date is invalid")

    schema_errors: list[str] = []
    if not node.get("schema_fingerprint"):
        schema_errors.append("schema fingerprint is missing")

    tables = node.get("tables")
    table_errors: list[str] = []
    if not isinstance(tables, list) or not tables:
        table_errors.append("official table is missing")
    elif not any(
        isinstance(table, dict) and table.get("columns") and table.get("rows")
        for table in tables
    ):
        table_errors.append("official table has no usable columns/rows")

    return {
        "source": validation_check(source_errors, source_status=node.get("status", "missing")),
        "date": validation_check(
            date_errors,
            source_date=source_date,
            parsed_date=parsed_date.isoformat() if parsed_date else None,
        ),
        "schema": validation_check(
            schema_errors,
            schema_fingerprint=node.get("schema_fingerprint"),
        ),
        "table": validation_check(table_errors, table_count=len(tables or [])),
    }


def money_dataset_validation(node: dict[str, Any]) -> dict[str, Any]:
    checks = common_validation_checks(node)
    table_errors = list(checks["table"]["errors"])
    numeric_errors: list[str] = []
    matched_schema = False
    values_by_label: dict[str, tuple[float | None, float | None]] = {}

    for table in node.get("tables") or []:
        columns = table.get("columns") or []
        normalized = [plain(column) for column in columns]
        label_idx = next((i for i, value in enumerate(normalized) if "chi tieu" in value), 0)
        balance_idx = next((i for i, value in enumerate(normalized) if "so du" in value), None)
        growth_idx = next((i for i, value in enumerate(normalized) if "toc" in value), None)
        if balance_idx is None or growth_idx is None:
            continue
        matched_schema = True
        for row in table.get("rows") or []:
            label = plain(row[label_idx] if label_idx < len(row) else "")
            metric_key = None
            if "tong phuong tien thanh toan" in label:
                metric_key = "m2"
            elif "tckt" in label or "to chuc kinh te" in label:
                metric_key = "corporate_deposits"
            elif "dan cu" in label:
                metric_key = "household_deposits"
            if metric_key:
                balance = number(row[balance_idx]) if balance_idx < len(row) else None
                growth = number(row[growth_idx]) if growth_idx < len(row) else None
                values_by_label[metric_key] = (balance, growth)

    required = {"m2", "corporate_deposits", "household_deposits"}
    if not matched_schema:
        table_errors.append("required balance/growth columns are missing")
    missing_labels = sorted(required - set(values_by_label))
    if missing_labels:
        table_errors.append(f"expected rows are incomplete: {', '.join(missing_labels)}")

    for label in sorted(required):
        balance, growth = values_by_label.get(label, (None, None))
        if balance is None:
            numeric_errors.append(f"{label} balance is not numeric")
        elif balance < 0:
            numeric_errors.append(f"{label} balance fails sanity check: {balance}")
        if growth is None:
            numeric_errors.append(f"{label} growth is not numeric")
        elif abs(growth) > 100:
            numeric_errors.append(f"{label} growth fails sanity check: {growth}")

    checks["table"] = validation_check(
        table_errors,
        table_count=len(node.get("tables") or []),
        required_rows=sorted(required),
        observed_rows=sorted(values_by_label),
    )
    checks["numeric"] = validation_check(
        numeric_errors,
        numeric_row_count=sum(
            1 for balance, growth in values_by_label.values() if balance is not None and growth is not None
        ),
    )
    errors = [error for check in checks.values() for error in check["errors"]]
    return {
        "status": "pass" if not errors else "fail",
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "warnings": [],
    }


def omo_dataset_validation(node: dict[str, Any]) -> dict[str, Any]:
    checks = common_validation_checks(node)
    table_errors = list(checks["table"]["errors"])
    numeric_errors: list[str] = []
    matched_schema = False
    term_rows = 0
    total_rows = 0
    numeric_rates = 0
    positive_term_rows = 0
    numeric_positive_rates = 0
    numeric_term_volumes = 0
    numeric_totals = 0

    for table in node.get("tables") or []:
        columns = table.get("columns") or []
        normalized = [plain(column) for column in columns]
        label_idx = next((i for i, value in enumerate(normalized) if "loai hinh" in value), 0)
        volume_idx = next((i for i, value in enumerate(normalized) if "khoi luong" in value), None)
        rate_idx = next((i for i, value in enumerate(normalized) if "lai suat" in value), None)
        if volume_idx is None or rate_idx is None:
            continue
        matched_schema = True
        for row in table.get("rows") or []:
            raw_label = str(row[label_idx] or "") if label_idx < len(row) else ""
            label = plain(raw_label)
            volume = number(row[volume_idx]) if volume_idx < len(row) else None
            rate = number(row[rate_idx]) if rate_idx < len(row) else None
            is_term = "ky han" in label and (
                raw_label.lstrip().startswith("-") or volume is not None or rate is not None
            )
            if is_term:
                term_rows += 1
                if volume is None:
                    numeric_errors.append(f"term volume is not numeric: {label or 'unknown term'}")
                else:
                    numeric_term_volumes += 1
                    if volume < 0:
                        numeric_errors.append(f"term volume fails sanity check: {volume}")
                    elif volume > 0:
                        positive_term_rows += 1
                if rate is not None:
                    numeric_rates += 1
                    if not 0 <= rate <= 20:
                        numeric_errors.append(f"term rate fails sanity check: {rate}")
                    elif volume is not None and volume > 0:
                        numeric_positive_rates += 1
                elif volume is not None and volume > 0:
                    numeric_errors.append(
                        f"positive-volume term rate is not numeric: {label or 'unknown term'}"
                    )
            elif "tong cong" in label:
                total_rows += 1
                if volume is None:
                    numeric_errors.append("total awarded volume is not numeric")
                else:
                    numeric_totals += 1
                    if volume < 0:
                        numeric_errors.append(f"total volume fails sanity check: {volume}")

    if not matched_schema:
        table_errors.append("required volume/rate columns are missing")
    if not term_rows:
        table_errors.append("expected term rows are missing")
    if not total_rows:
        table_errors.append("expected total row is missing")
    if positive_term_rows and numeric_positive_rates != positive_term_rows:
        numeric_errors.append("not every positive-volume OMO term has a valid rate")
    if term_rows and not numeric_term_volumes:
        numeric_errors.append("no numeric OMO term volumes")
    if total_rows and not numeric_totals:
        numeric_errors.append("no numeric OMO total volume")

    checks["table"] = validation_check(
        table_errors,
        table_count=len(node.get("tables") or []),
        term_rows=term_rows,
        total_rows=total_rows,
    )
    checks["numeric"] = validation_check(
        numeric_errors,
        numeric_rates=numeric_rates,
        positive_term_rows=positive_term_rows,
        numeric_positive_rates=numeric_positive_rates,
        numeric_term_volumes=numeric_term_volumes,
        numeric_totals=numeric_totals,
    )
    errors = [error for check in checks.values() for error in check["errors"]]
    return {
        "status": "pass" if not errors else "fail",
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "warnings": [],
    }


def validate_official(official: dict[str, Any]) -> dict[str, Any]:
    """Validate each official dataset independently, then derive an aggregate status."""
    datasets = {
        "money_supply_deposits": money_dataset_validation(
            official.get("money_supply_deposits") or {}
        ),
        "omo_latest": omo_dataset_validation(official.get("omo_latest") or {}),
    }
    passed = sum(result["status"] == "pass" for result in datasets.values())
    status = "pass" if passed == len(datasets) else "partial" if passed else "fail"
    errors = [
        f"{key}: {error}"
        for key, result in datasets.items()
        for error in result["errors"]
    ]
    return {
        "status": status,
        "datasets": datasets,
        "errors": list(dict.fromkeys(errors)),
        "warnings": [],
        "validated_source_dates": {
            key: (official.get(key) or {}).get("source_date")
            for key in datasets
        },
        "policy": (
            "Each official SBV dataset is promoted independently only when its own "
            "source date, schema, table shape and numeric values pass validation."
        ),
    }


def validate_dataset(dataset: str, node: dict[str, Any]) -> dict[str, Any]:
    if dataset == "money_supply_deposits":
        return money_dataset_validation(node)
    if dataset == "omo_latest":
        return omo_dataset_validation(node)
    raise ValueError(f"unsupported official SBV dataset: {dataset}")


def reconcile_refresh(
    existing: dict[str, Any],
    fetched: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Preserve last-known-good data only for transient fetch failures.

    A successful HTTP response with invalid date/schema/table/numeric content
    remains a hard failure. This prevents a changed upstream page from being
    silently treated like an ordinary network outage.
    """
    effective: dict[str, Any] = {}
    dataset_refresh: dict[str, Any] = {}
    warnings: list[str] = []
    hard_failure = False
    attempted_at = datetime.now(timezone.utc).isoformat()

    for dataset in ("money_supply_deposits", "omo_latest"):
        candidate = deepcopy(fetched.get(dataset) or {})
        previous = deepcopy(existing.get(dataset) or {})
        candidate_validation = validate_dataset(dataset, candidate)
        transient = bool(candidate.get("transient_error"))

        if transient:
            previous_validation = validate_dataset(dataset, previous)
            error = public_error(candidate.get("error") or "transient official-source failure")
            kept_last_known_good = previous_validation.get("status") == "pass"
            if kept_last_known_good:
                current = previous
                current["refresh_status"] = "stale"
                current["last_attempt_at"] = candidate.get("fetched_at") or attempted_at
                current["last_refresh_error"] = error
                effective[dataset] = current
            else:
                effective[dataset] = candidate

            warning = (
                f"{dataset}: transient refresh failed; "
                + ("kept last-known-good official dataset" if kept_last_known_good else "no last-known-good official dataset exists")
            )
            warnings.append(warning)
            dataset_refresh[dataset] = {
                "status": "warning",
                "failure_kind": candidate.get("failure_kind") or "transient_fetch_error",
                "kept_last_known_good": kept_last_known_good,
                "last_attempt_at": candidate.get("fetched_at") or attempted_at,
                "error": error,
            }
            continue

        if candidate_validation.get("status") == "pass":
            candidate["refresh_status"] = "fresh"
            candidate.pop("last_attempt_at", None)
            candidate.pop("last_refresh_error", None)
            effective[dataset] = candidate
            dataset_refresh[dataset] = {
                "status": "ok",
                "failure_kind": None,
                "kept_last_known_good": False,
                "source_observation_date": candidate.get("source_date"),
            }
            continue

        # Configuration errors and successful-but-invalid responses are hard
        # failures. Do not downgrade them to a stale-data warning.
        hard_failure = True
        effective[dataset] = candidate
        dataset_refresh[dataset] = {
            "status": "error",
            "failure_kind": candidate.get("failure_kind") or "validation_error",
            "kept_last_known_good": False,
            "http_succeeded": candidate.get("http_succeeded"),
            "errors": candidate_validation.get("errors") or ["official validation failed"],
        }

    status = "error" if hard_failure else "warning" if warnings else "ok"
    refresh = {
        "status": status,
        "last_attempt_at": attempted_at,
        "datasets": dataset_refresh,
        "warnings": warnings,
        "policy": (
            "Transient import/network failures retain last-known-good official data; "
            "successful HTTP responses must pass date, schema, table and numeric validation."
        ),
    }
    return effective, refresh, hard_failure


def main(validate_existing: bool = False) -> int:
    macro = load(MACRO, {})
    if validate_existing:
        official = deepcopy(macro.get("official_checks") or {})
        validation = validate_official(official)
        # Offline validation may update only its derived validation result. It
        # must not rewrite source payloads or refresh-state metadata.
        macro["official_validation"] = validation
        changed = save_if_changed(MACRO, macro)
        print(
            json.dumps(
                {
                    **validation,
                    "mode": "validate_existing",
                    "official_refresh": "not_attempted",
                    "changed": changed,
                },
                ensure_ascii=False,
            )
        )
        return 0 if validation.get("status") == "pass" else 1

    cfg = load(CONFIG, {})
    urls = cfg.get("official_sbv_sources", {})
    fetched = {
        "money_supply_deposits": fetch_tables(
            urls.get("money_supply_deposits", ""),
            "Tổng phương tiện thanh toán và tiền gửi",
        ),
        "omo_latest": fetch_tables(
            urls.get("omo", ""),
            "Nghiệp vụ thị trường mở",
        ),
    }
    official, refresh, hard_failure = reconcile_refresh(
        macro.get("official_checks") or {},
        fetched,
    )
    validation = validate_official(official)
    macro["official_checks"] = official
    macro["official_validation"] = validation
    macro["official_refresh"] = refresh
    changed = save_if_changed(MACRO, macro)
    print(
        json.dumps(
            {
                **validation,
                "mode": "fetch_and_validate",
                "official_refresh": refresh["status"],
                "refresh": refresh,
                "changed": changed,
            },
            ensure_ascii=False,
        )
    )
    return 1 if hard_failure else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch/validate SBV tables or validate the stored official snapshots offline."
    )
    parser.add_argument(
        "--validate-existing",
        action="store_true",
        help="Validate data/foundation/macro.json without making network requests.",
    )
    args = parser.parse_args()
    raise SystemExit(main(validate_existing=args.validate_existing))
