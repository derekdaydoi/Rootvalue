from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MACRO = ROOT / "data" / "foundation" / "macro.json"
HISTORY = ROOT / "data" / "foundation" / "sbv_history.json"


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def num(v: Any) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
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
        return float(raw)
    except Exception:
        return None


def first_table(node: dict[str, Any]) -> dict[str, Any]:
    tables = node.get("tables") or []
    return tables[0] if tables else {"columns": [], "rows": []}


def money_metrics(official: dict[str, Any]) -> dict[str, Any]:
    table = first_table(official.get("money_supply_deposits", {}))
    result: dict[str, Any] = {}
    for row in table.get("rows", []):
        if not row:
            continue
        label = str(row[0] or "").lower()
        balance = num(row[1]) if len(row) > 1 else None
        growth = num(row[2]) if len(row) > 2 else None
        if "tổng phương tiện thanh toán" in label:
            result.update({"m2_balance_bn_vnd": balance, "m2_growth_ytd_pct": growth})
        elif "tckt" in label or "tổ chức kinh tế" in label:
            result.update({"corp_deposit_bn_vnd": balance, "corp_deposit_growth_ytd_pct": growth})
        elif "dân cư" in label:
            result.update({"household_deposit_bn_vnd": balance, "household_deposit_growth_ytd_pct": growth})
    return result


def omo_metrics(official: dict[str, Any]) -> dict[str, Any]:
    table = first_table(official.get("omo_latest", {}))
    total = None
    rates: list[float] = []
    terms: list[dict[str, Any]] = []
    for row in table.get("rows", []):
        if not row:
            continue
        label = str(row[0] or "").strip()
        volume = num(row[2]) if len(row) > 2 else None
        rate = num(row[3]) if len(row) > 3 else None
        if "tổng cộng" in label.lower():
            total = volume
        elif label.startswith("-"):
            if rate is not None and 0 <= rate <= 20:
                rates.append(rate)
            terms.append({"term": label.lstrip("- "), "awarded_bn_vnd": volume, "rate_pct": rate})
    return {
        "omo_awarded_bn_vnd": total,
        "omo_rate_pct": median(rates) if rates else None,
        "omo_terms": terms,
    }


def main() -> None:
    macro = load(MACRO, {})
    official = macro.get("official_checks", {})
    now = datetime.now(timezone.utc)
    snapshot = {
        "captured_at": now.isoformat(),
        "capture_date": now.date().isoformat(),
        "provenance": "primary_official_capture",
        "source": "State Bank of Vietnam official website",
        **money_metrics(official),
        **omo_metrics(official),
    }

    has_signal = any(snapshot.get(k) is not None for k in (
        "m2_balance_bn_vnd", "m2_growth_ytd_pct", "corp_deposit_growth_ytd_pct",
        "household_deposit_growth_ytd_pct", "omo_awarded_bn_vnd", "omo_rate_pct"
    ))
    history = load(HISTORY, {"schema_version": "1.0.0", "observations": []})
    observations = list(history.get("observations") or [])
    if has_signal:
        observations = [x for x in observations if x.get("capture_date") != snapshot["capture_date"]]
        observations.append(snapshot)
        observations.sort(key=lambda x: x.get("capture_date") or "")
        observations = observations[-730:]

    history = {
        "schema_version": "1.0.0",
        "generated_at": now.isoformat(),
        "status": "accumulating" if observations else "empty",
        "history_type": "official daily capture history",
        "warning": "This is not yet a 2018-backfilled series. It accumulates verified SBV observations from the date Rootvalue started capturing them.",
        "observations": observations,
    }
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"status": history["status"], "observations": len(observations), "latest": snapshot if has_signal else None}, ensure_ascii=False))


if __name__ == "__main__":
    main()
