from __future__ import annotations

import json
import hashlib
import math
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MACRO = ROOT / "data" / "foundation" / "macro.json"
HISTORY = ROOT / "data" / "foundation" / "sbv_history.json"
DATASETS = ("money_supply_deposits", "omo_latest")
MONEY_FIELDS = (
    "m2_balance_bn_vnd",
    "m2_growth_ytd_pct",
    "corp_deposit_bn_vnd",
    "corp_deposit_growth_ytd_pct",
    "household_deposit_bn_vnd",
    "household_deposit_growth_ytd_pct",
)
OMO_FIELDS = (
    "omo_awarded_bn_vnd",
    "omo_rate_pct",
    "omo_terms",
    "omo_rate_policy",
)
DATASET_FIELDS = {
    "money_supply_deposits": MONEY_FIELDS,
    "omo_latest": OMO_FIELDS,
}


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def num(v: Any) -> float | None:
    if isinstance(v, (int, float)):
        value = float(v)
        return value if math.isfinite(value) else None
    if v is None:
        return None
    try:
        raw = str(v).strip().replace(" ", "")
        if not raw:
            return None
        # repair_sbv_official normally normalizes these already.
        if "," in raw and "." in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif "," in raw:
            raw = raw.replace(",", ".")
        value = float(raw)
        return value if math.isfinite(value) else None
    except Exception:
        return None


def plain(v: Any) -> str:
    text = unicodedata.normalize("NFKD", str(v or ""))
    return re.sub(r"\s+", " ", "".join(ch for ch in text if not unicodedata.combining(ch)).lower()).strip()


def money_metrics(official: dict[str, Any]) -> dict[str, Any]:
    best: dict[str, Any] = {}
    for table in (official.get("money_supply_deposits") or {}).get("tables") or []:
        columns = [plain(column) for column in table.get("columns") or []]
        label_idx = next((i for i, value in enumerate(columns) if "chi tieu" in value), 0)
        balance_idx = next((i for i, value in enumerate(columns) if "so du" in value), None)
        growth_idx = next((i for i, value in enumerate(columns) if "toc" in value), None)
        result: dict[str, Any] = {}
        for row in table.get("rows") or []:
            if not row or balance_idx is None or growth_idx is None:
                continue
            label = plain(row[label_idx] if label_idx < len(row) else "")
            balance = num(row[balance_idx]) if balance_idx < len(row) else None
            growth = num(row[growth_idx]) if growth_idx < len(row) else None
            if "tong phuong tien thanh toan" in label:
                result.update({"m2_balance_bn_vnd": balance, "m2_growth_ytd_pct": growth})
            elif "tckt" in label or "to chuc kinh te" in label:
                result.update({"corp_deposit_bn_vnd": balance, "corp_deposit_growth_ytd_pct": growth})
            elif "dan cu" in label:
                result.update({"household_deposit_bn_vnd": balance, "household_deposit_growth_ytd_pct": growth})
        if len(result) > len(best):
            best = result
    return best


def omo_metrics(official: dict[str, Any]) -> dict[str, Any]:
    best: dict[str, Any] = {}
    best_score = -1
    for table in (official.get("omo_latest") or {}).get("tables") or []:
        columns = [plain(column) for column in table.get("columns") or []]
        label_idx = next((i for i, value in enumerate(columns) if "loai hinh" in value), 0)
        volume_idx = next((i for i, value in enumerate(columns) if "khoi luong" in value), None)
        rate_idx = next((i for i, value in enumerate(columns) if "lai suat" in value), None)
        if volume_idx is None or rate_idx is None:
            continue
        total = None
        awarded_rates: list[float] = []
        invalid_awarded_rate = False
        terms: list[dict[str, Any]] = []
        for row in table.get("rows") or []:
            if not row:
                continue
            label = str(row[label_idx] or "").strip() if label_idx < len(row) else ""
            volume = num(row[volume_idx]) if volume_idx < len(row) else None
            rate = num(row[rate_idx]) if rate_idx < len(row) else None
            normalized_label = plain(label)
            if "tong cong" in normalized_label:
                total = volume
            elif "ky han" in normalized_label and (
                label.lstrip().startswith("-") or volume is not None or rate is not None
            ):
                # SBV tables retain zero-volume term placeholders, commonly with a
                # displayed rate of 0.  Those are not executed OMO rates and must
                # not dilute the rate paid on terms that actually won an award.
                if volume is not None and volume > 0:
                    if rate is not None and 0 <= rate <= 20:
                        awarded_rates.append(rate)
                    else:
                        invalid_awarded_rate = True
                terms.append({"term": label.lstrip("- "), "awarded_bn_vnd": volume, "rate_pct": rate})
        score = len(terms) + int(total is not None)
        if score > best_score:
            best_score = score
            best = {
                "omo_awarded_bn_vnd": total,
                "omo_rate_pct": (
                    awarded_rates[0]
                    if awarded_rates
                    and not invalid_awarded_rate
                    and len(set(awarded_rates)) == 1
                    else None
                ),
                "omo_terms": terms,
                "omo_rate_policy": (
                    "single official rate across positive-awarded terms only; "
                    "zero-volume placeholders are excluded and mixed executed rates remain in omo_terms"
                ),
            }
    return best


def observation_signature(snapshot: dict[str, Any]) -> str:
    material = {
        "dataset": snapshot.get("dataset"),
        "source_observation_date": snapshot.get("source_observation_date"),
        "schema_fingerprint": snapshot.get("schema_fingerprint"),
        "values": {
            key: snapshot.get(key)
            for key in DATASET_FIELDS.get(str(snapshot.get("dataset")), ())
            if key in snapshot
        },
    }
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def source_table_identity(dataset: str, schema_fingerprint: Any) -> str:
    """Identify one official table independently of its derived metric values."""
    return f"{dataset}:{schema_fingerprint}"


def dataset_has_signal(dataset: str, metrics: dict[str, Any]) -> bool:
    if dataset == "money_supply_deposits":
        return any(metrics.get(key) is not None for key in MONEY_FIELDS)
    if dataset == "omo_latest":
        return any(
            metrics.get(key) is not None
            for key in ("omo_awarded_bn_vnd", "omo_rate_pct")
        ) or bool(metrics.get("omo_terms"))
    return False


def build_dataset_snapshot(
    dataset: str,
    source_date: Any,
    schema_fingerprint: Any,
    fetched_at: Any,
    metrics: dict[str, Any],
    *,
    source: str = "State Bank of Vietnam official website",
    migration_origin: str | None = None,
) -> dict[str, Any] | None:
    """Create one source-dated observation containing fields from one dataset only."""
    if dataset not in DATASET_FIELDS or not source_date or not schema_fingerprint:
        return None
    try:
        parsed_date = datetime.fromisoformat(str(source_date).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None

    permitted = {
        key: metrics.get(key)
        for key in DATASET_FIELDS[dataset]
        if key in metrics
    }
    if not dataset_has_signal(dataset, permitted):
        return None
    snapshot = {
        "dataset": dataset,
        "source_date": parsed_date.isoformat(),
        "source_observation_date": parsed_date.isoformat(),
        "source_as_of": parsed_date.isoformat(),
        # Compatibility alias: always the source date, never the fetch date.
        "capture_date": parsed_date.isoformat(),
        "fetched_at": fetched_at,
        "schema_fingerprint": str(schema_fingerprint),
        "provenance": "primary_official_observation",
        "source": source or "State Bank of Vietnam official website",
        **permitted,
    }
    if migration_origin:
        snapshot["migration_origin"] = migration_origin
    signature = observation_signature(snapshot)
    snapshot["observation_key"] = signature
    # The table identity must remain stable when extraction logic corrects a
    # derived value.  observation_key still fingerprints the versioned content.
    snapshot["source_table_id"] = source_table_identity(dataset, schema_fingerprint)
    return snapshot


def canonical_dataset_observation(item: dict[str, Any]) -> dict[str, Any] | None:
    dataset = str(item.get("dataset") or "")
    schema = item.get("schema_fingerprint")
    if not schema and isinstance(item.get("schema_fingerprints"), dict):
        schema = item["schema_fingerprints"].get(dataset)
    source_date = (
        item.get("source_observation_date")
        or item.get("source_as_of")
        or item.get("source_date")
    )
    metrics = {key: item.get(key) for key in DATASET_FIELDS.get(dataset, ()) if key in item}
    return build_dataset_snapshot(
        dataset,
        source_date,
        schema,
        item.get("fetched_at"),
        metrics,
        source=str(item.get("source") or "State Bank of Vietnam official website"),
        migration_origin=item.get("migration_origin"),
    )


def split_legacy_observation(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Split a source-dated legacy combined record; capture-dated records stay quarantined."""
    source_dates = item.get("source_dates")
    schema_fingerprints = item.get("schema_fingerprints")
    if not isinstance(source_dates, dict) or not isinstance(schema_fingerprints, dict):
        return []
    migrated: list[dict[str, Any]] = []
    for dataset in DATASETS:
        metrics = {
            key: item.get(key)
            for key in DATASET_FIELDS[dataset]
            if key in item
        }
        snapshot = build_dataset_snapshot(
            dataset,
            source_dates.get(dataset),
            schema_fingerprints.get(dataset),
            item.get("fetched_at"),
            metrics,
            source=str(item.get("source") or "State Bank of Vietnam official website"),
            migration_origin="legacy_combined_observation",
        )
        if snapshot:
            migrated.append(snapshot)
    return migrated


def quarantine_record(item: dict[str, Any], reason: str) -> dict[str, Any]:
    result = dict(item)
    result.pop("quarantine_key", None)
    result.setdefault("quarantine_reason", reason)
    raw = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    result["quarantine_key"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return result


def append_unique(
    observations: list[dict[str, Any]],
    snapshot: dict[str, Any],
) -> bool:
    """Upsert one derived version per dataset/date/source-table identity."""
    identity = (
        snapshot.get("dataset"),
        snapshot.get("source_observation_date"),
        snapshot.get("source_table_id"),
    )
    for index, item in enumerate(observations):
        existing_identity = (
            item.get("dataset"),
            item.get("source_observation_date"),
            item.get("source_table_id"),
        )
        if identity != existing_identity:
            continue
        if item.get("observation_key") == snapshot.get("observation_key"):
            return False
        observations[index] = snapshot
        return True
    observations.append(snapshot)
    return True


def semantic_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {key: semantic_payload(value) for key, value in payload.items() if key != "generated_at"}
    if isinstance(payload, list):
        return [semantic_payload(value) for value in payload]
    return payload


def save_if_changed(path: Path, payload: dict[str, Any]) -> bool:
    previous = load(path, None)
    if previous is not None and semantic_payload(previous) == semantic_payload(payload):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return True


def main() -> None:
    macro = load(MACRO, {})
    official = macro.get("official_checks", {})
    validation = macro.get("official_validation", {})
    now = datetime.now(timezone.utc)
    history = load(HISTORY, {"schema_version": "1.2.0", "observations": []})
    existing = list(history.get("observations") or [])
    quarantined = list(history.get("quarantined_legacy_observations") or [])
    observations: list[dict[str, Any]] = []

    for item in existing:
        if not isinstance(item, dict):
            continue
        if item.get("dataset"):
            canonical = canonical_dataset_observation(item)
            if canonical:
                append_unique(observations, canonical)
            else:
                quarantined.append(
                    quarantine_record(item, "invalid dataset-specific source metadata")
                )
        else:
            for migrated in split_legacy_observation(item):
                append_unique(observations, migrated)
            quarantined.append(
                quarantine_record(
                    item,
                    "legacy combined observation retained for audit after deterministic split",
                )
            )

    normalized_quarantine = [
        quarantine_record(
            item,
            "legacy observation lacks verifiable per-dataset source metadata",
        )
        for item in quarantined
        if isinstance(item, dict)
    ]
    quarantine_by_key = {item["quarantine_key"]: item for item in normalized_quarantine}
    quarantined = [quarantine_by_key[key] for key in sorted(quarantine_by_key)]

    metrics_by_dataset = {
        "money_supply_deposits": money_metrics(official),
        "omo_latest": omo_metrics(official),
    }
    validation_by_dataset = validation.get("datasets") or {}
    candidates: dict[str, dict[str, Any]] = {}
    blocked_reasons: list[str] = []
    dataset_status: dict[str, Any] = {}
    for dataset in DATASETS:
        node = official.get(dataset) or {}
        result = validation_by_dataset.get(dataset) or {}
        eligible = result.get("status") == "pass"
        snapshot = None
        if eligible:
            snapshot = build_dataset_snapshot(
                dataset,
                node.get("source_date"),
                node.get("schema_fingerprint"),
                node.get("fetched_at"),
                metrics_by_dataset[dataset],
                source=str(node.get("source") or "State Bank of Vietnam official website"),
            )
            if snapshot:
                append_unique(observations, snapshot)
                candidates[dataset] = snapshot
            else:
                eligible = False
                blocked_reasons.append(f"{dataset}: validated table could not be extracted")
        if not eligible and not snapshot:
            errors = result.get("errors") or ["independent official validation did not pass"]
            blocked_reasons.extend(f"{dataset}: {error}" for error in errors)
        dataset_status[dataset] = {
            "status": "pass" if snapshot else "fail",
            "validation_status": result.get("status", "missing"),
            "source_observation_date": node.get("source_date"),
            "schema_fingerprint": node.get("schema_fingerprint"),
            "errors": result.get("errors") or ([] if snapshot else ["validation result is missing"]),
        }

    observations.sort(
        key=lambda item: (
            item.get("source_observation_date") or "",
            item.get("dataset") or "",
            item.get("observation_key") or "",
        )
    )
    trimmed: list[dict[str, Any]] = []
    for dataset in DATASETS:
        dataset_items = [item for item in observations if item.get("dataset") == dataset]
        trimmed.extend(dataset_items[-730:])
    observations = sorted(
        trimmed,
        key=lambda item: (
            item.get("source_observation_date") or "",
            item.get("dataset") or "",
            item.get("observation_key") or "",
        ),
    )
    observation_datasets = {item.get("dataset") for item in observations}
    history_status = (
        "accumulating"
        if observation_datasets == set(DATASETS)
        else "partial"
        if observations
        else "empty"
    )

    history = {
        "schema_version": "1.2.0",
        "generated_at": now.isoformat(),
        "status": history_status,
        "validation_status": validation.get("status", "missing"),
        "history_type": "official per-dataset source-dated observation history",
        "warning": (
            "This is not a 2018-backfilled series. Money/deposit and OMO records are "
            "independent; fetch dates are audit metadata and never observation dates."
        ),
        "blocked_reasons": list(dict.fromkeys(blocked_reasons)),
        "dataset_status": dataset_status,
        "observations": observations,
        "quarantined_legacy_observations": quarantined,
    }
    changed = save_if_changed(HISTORY, history)
    print(
        json.dumps(
            {
                "status": history["status"],
                "validation_status": history["validation_status"],
                "observations": len(observations),
                "observations_by_dataset": {
                    dataset: sum(item.get("dataset") == dataset for item in observations)
                    for dataset in DATASETS
                },
                "quarantined": len(quarantined),
                "changed": changed,
                "latest_by_dataset": candidates,
            },
            # Keep workflow/local status output portable across non-UTF-8 consoles.
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
