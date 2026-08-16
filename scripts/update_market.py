from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from update_data import fetch_market, read_json

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "watchlist.json"
OUT = ROOT / "data" / "rootvalue.json"


def save(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def build_sector_selection(rows: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    sectors: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        sectors.setdefault(str(row.get("sector") or "Other"), []).append(row)

    selected_by_sector: dict[str, list[dict[str, Any]]] = {}
    for sector, items in sectors.items():
        ranked = sorted(items, key=lambda r: (r.get("rs_20d_vs_vnindex") is None, -(r.get("rs_20d_vs_vnindex") or -999)))
        for i, row in enumerate(ranked, start=1):
            row["sector_rank"] = i

        leaders = ranked[: min(3, len(ranked))]
        leader_symbols = {r.get("symbol") for r in leaders}
        abnormal_pool = [r for r in ranked if r.get("symbol") not in leader_symbols]
        abnormal_pool.sort(
            key=lambda r: (
                -(abs(r.get("rank_delta")) if r.get("rank_delta") is not None else -1),
                -(abs((r.get("volume_participation_5d_vs_20d") or 1) - 1)),
                -(abs(r.get("rs_20d_vs_vnindex") or 0)),
            )
        )
        abnormals = [r for r in abnormal_pool if r.get("rank_delta") is not None][:2]

        output: list[dict[str, Any]] = []
        for row in leaders:
            output.append({**row, "selection_type": "Leader"})
        for row in abnormals:
            output.append({**row, "selection_type": "Abnormal"})
        selected_by_sector[sector] = output

    # Round-robin sectors so the homepage does not get dominated by banks or brokers.
    ordered_sectors = sorted(selected_by_sector)
    flat: list[dict[str, Any]] = []
    for slot in range(5):
        for sector in ordered_sectors:
            items = selected_by_sector[sector]
            if slot < len(items):
                flat.append(items[slot])
                if len(flat) >= limit:
                    return flat, selected_by_sector
    return flat, selected_by_sector


def main() -> None:
    config = read_json(CONFIG, {})
    snapshot = read_json(OUT, {})
    warnings: list[str] = []
    errors: list[str] = []

    try:
        market = fetch_market(config, warnings)
        picks, by_sector = build_sector_selection(market.get("rows", []), int(config.get("pick_limit", 20)))
        market["picks"] = picks
        market["selection_by_sector"] = by_sector
        market["selection_method"] = {
            "leader": "Top 3 relative-strength names inside each configured sector.",
            "abnormal": "Two non-leaders with the largest absolute 5-session rank change; participation and RS break ties.",
            "purpose": "Attention allocation only, not a buy/sell recommendation or investment score.",
        }
        snapshot["market"] = market
    except Exception as exc:
        errors.append(f"market:{exc}")
        old = snapshot.get("market", {})
        if old:
            old["status"] = "stale"
            old["last_error"] = str(exc)
            snapshot["market"] = old
        else:
            snapshot["market"] = {"status": "error", "as_of": None, "index": {}, "rows": [], "picks": [], "last_error": str(exc)}

    health = snapshot.setdefault("health", {"errors": [], "warnings": []})
    prior_errors = [x for x in health.get("errors", []) if not str(x).startswith("market:")]
    prior_warnings = [x for x in health.get("warnings", []) if not str(x).startswith("market:")]
    health["errors"] = prior_errors + errors
    health["warnings"] = prior_warnings + warnings
    snapshot["generated_at"] = datetime.now(timezone.utc).isoformat()

    statuses = [snapshot.get(k, {}).get("status") for k in ("market", "macro", "companies")]
    snapshot["pipeline_status"] = "ok" if all(s == "ok" for s in statuses) else "partial"
    save(OUT, snapshot)
    print(json.dumps({
        "market_status": snapshot.get("market", {}).get("status"),
        "market_rows": len(snapshot.get("market", {}).get("rows", [])),
        "picks": len(snapshot.get("market", {}).get("picks", [])),
        "warnings": len(warnings),
        "errors": errors,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
