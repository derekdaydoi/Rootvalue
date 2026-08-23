from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from update_data import fetch_market, public_error, read_json

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "watchlist.json"
OUT = ROOT / "data" / "market.json"
MIN_UNIVERSE_COMPLETENESS = 1.0
ABNORMAL_RANK_DELTA_MIN = 3


def semantic_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: semantic_payload(value)
            for key, value in payload.items()
            if key != "generated_at"
        }
    if isinstance(payload, list):
        return [semantic_payload(value) for value in payload]
    return payload


def save(path: Path, payload: Any) -> bool:
    previous = read_json(path, None)
    if previous is not None and semantic_payload(previous) == semantic_payload(payload):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return True


def configured_symbols(config: dict[str, Any]) -> list[str]:
    return [
        str(item.get("symbol", "")).upper()
        for item in config.get("symbols", [])
        if item.get("symbol")
    ]


def build_universe_coverage(market: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    expected_symbols = configured_symbols(config)
    observed_symbols = {str(item.get("symbol", "")).upper() for item in market.get("rows", [])}
    expected_count = len(expected_symbols)
    observed_count = len(observed_symbols)
    completeness = observed_count / expected_count if expected_count else 0.0
    materially_complete = (
        bool(expected_count)
        and market.get("status") == "ok"
        and completeness >= MIN_UNIVERSE_COMPLETENESS
    )
    return {
        "expected": expected_count,
        "observed": observed_count,
        "completeness": completeness,
        "missing_symbols": [symbol for symbol in expected_symbols if symbol not in observed_symbols],
        "minimum_for_picks": MIN_UNIVERSE_COMPLETENESS,
        "materially_complete": materially_complete,
    }


def is_usable_full_snapshot(market: Any, config: dict[str, Any]) -> bool:
    if not isinstance(market, dict) or market.get("status") not in {"ok", "stale"}:
        return False
    rows = market.get("rows")
    picks = market.get("picks")
    selected_by_sector = market.get("selection_by_sector", {})
    if not isinstance(rows, list) or not isinstance(picks, list) or not isinstance(selected_by_sector, dict):
        return False
    expected = configured_symbols(config)
    observed = [str(row.get("symbol", "")).upper() for row in rows if isinstance(row, dict)]
    if not expected or len(observed) != len(expected) or len(observed) != len(set(observed)):
        return False
    if set(observed) != set(expected):
        return False
    observed_set = set(observed)
    return all(
        isinstance(pick, dict) and str(pick.get("symbol", "")).upper() in observed_set
        for pick in picks
    )


def preserve_last_known_good(
    previous: dict[str, Any],
    attempted: dict[str, Any],
    coverage: dict[str, Any],
    attempt_warnings: list[str],
    attempted_at: str,
) -> dict[str, Any]:
    missing = list(coverage.get("missing_symbols", []))
    missing_text = ", ".join(missing) if missing else "none reported"
    message = (
        f"market refresh incomplete: {coverage.get('observed', 0)}/{coverage.get('expected', 0)}; "
        f"missing={missing_text}; kept last-known-good snapshot"
    )
    attempted_errors = list(dict.fromkeys(str(item) for item in attempt_warnings if item))
    if not attempted_errors:
        attempted_errors = [message]

    kept = deepcopy(previous)
    previous_health = previous.get("health") if isinstance(previous.get("health"), dict) else {}
    previous_errors = list(previous_health.get("errors", []))
    previous_warnings = list(previous_health.get("warnings", []))
    kept["status"] = "stale"
    kept["last_error"] = message
    kept["last_attempt_at"] = attempted_at
    kept["last_refresh_attempt"] = {
        "status": attempted.get("status") or "partial",
        "as_of": attempted.get("as_of"),
        "last_attempt_at": attempted_at,
        "coverage": coverage,
        "missing_symbols": missing,
        "errors": attempted_errors,
    }
    kept["health"] = {
        "errors": previous_errors,
        "warnings": list(dict.fromkeys([*previous_warnings, *attempt_warnings, message])),
    }
    return kept


def build_sector_selection(
    rows: list[dict[str, Any]],
    limit: int,
    abnormal_rank_delta_min: int = ABNORMAL_RANK_DELTA_MIN,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    sectors: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        sectors.setdefault(str(row.get("sector") or "Other"), []).append(row)

    selected_by_sector: dict[str, list[dict[str, Any]]] = {}
    for sector, items in sectors.items():
        ranked = sorted(
            items,
            key=lambda r: (
                r.get("rs_20d_vs_vnindex") is None,
                -(r.get("rs_20d_vs_vnindex") if r.get("rs_20d_vs_vnindex") is not None else -999),
            ),
        )
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
        abnormals = [
            r for r in abnormal_pool
            if r.get("rank_delta") is not None and abs(int(r["rank_delta"])) >= abnormal_rank_delta_min
        ][:2]

        output: list[dict[str, Any]] = []
        output.extend(
            {
                **row,
                "selection_type": "RelativeStrengthLeader",
                "selection_basis": "Top relative strength inside the configured peer group; not a structural sector-leadership claim.",
            }
            for row in leaders
        )
        output.extend(
            {
                **row,
                "selection_type": "AbnormalMovement",
                "selection_basis": f"Absolute five-session rank change >= {abnormal_rank_delta_min} inside the configured universe.",
            }
            for row in abnormals
        )
        selected_by_sector[sector] = output

    # Round-robin keeps the homepage from being dominated by one large sector.
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


def apply_selection_policy(
    market: dict[str, Any],
    config: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    coverage = build_universe_coverage(market, config)
    market["universe_coverage"] = coverage
    if coverage["materially_complete"]:
        picks, by_sector = build_sector_selection(market.get("rows", []), int(config.get("pick_limit", 20)))
        selection_status = "ready"
    else:
        picks, by_sector = [], {}
        selection_status = "blocked_incomplete_universe"
        message = f"market universe incomplete: {coverage['observed']}/{coverage['expected']}; picks withheld"
        if message not in warnings:
            warnings.append(message)
    market["picks"] = picks
    market["selection_by_sector"] = by_sector
    market["selection_status"] = selection_status
    market["selection_method"] = {
        "leader": "Top 3 relative-strength names inside each configured economic peer group; this is not a structural sector-leadership classification.",
        "abnormal": f"Up to two non-leaders with absolute five-session rank change >= {ABNORMAL_RANK_DELTA_MIN}; participation and relative strength break ties.",
        "purpose": "Attention allocation only; not a buy/sell recommendation or investment score.",
    }
    return market


def main(normalize_only: bool = False) -> None:
    config = read_json(CONFIG, {})
    previous = read_json(OUT, {})
    warnings: list[str] = []
    errors: list[str] = []

    if normalize_only:
        if not previous:
            raise SystemExit("data/market.json is missing; cannot normalize stored selection")
        warnings = list(previous.get("health", {}).get("warnings", []))
        errors = list(previous.get("health", {}).get("errors", []))
        market = apply_selection_policy(previous, config, warnings)
        market["schema_version"] = "1.1.0"
        market["health"] = {"errors": errors, "warnings": warnings}
        changed = save(OUT, market)
        print(json.dumps({"mode": "normalize-only", "status": market.get("status"), "picks": len(market.get("picks", [])), "changed": changed}, ensure_ascii=False))
        return

    try:
        attempted_at = datetime.now(timezone.utc).isoformat()
        market = fetch_market(config, warnings)
        attempted_coverage = build_universe_coverage(market, config)
        if not attempted_coverage["materially_complete"] and is_usable_full_snapshot(previous, config):
            market = preserve_last_known_good(previous, market, attempted_coverage, warnings, attempted_at)
        else:
            market = apply_selection_policy(market, config, warnings)
            market["schema_version"] = "1.1.0"
            market["generated_at"] = attempted_at
            market["health"] = {"errors": errors, "warnings": warnings}
        changed = save(OUT, market)
    except Exception as exc:
        message = public_error(exc)
        errors.append(f"market:{message}")
        if previous:
            previous["status"] = "stale"
            previous["last_error"] = message
            previous["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
            previous["health"] = {"errors": errors, "warnings": warnings}
            changed = save(OUT, previous)
        else:
            changed = save(
                OUT,
                {
                    "schema_version": "1.1.0",
                    "status": "error",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "as_of": None,
                    "index": {},
                    "rows": [],
                    "picks": [],
                    "selection_by_sector": {},
                    "health": {"errors": errors, "warnings": warnings},
                },
            )

    current = read_json(OUT, {})
    print(
        json.dumps(
            {
                "market_status": current.get("status"),
                "market_rows": len(current.get("rows", [])),
                "picks": len(current.get("picks", [])),
                "warnings": len(current.get("health", {}).get("warnings", [])),
                "errors": current.get("health", {}).get("errors", []),
                "changed": locals().get("changed", False),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh or normalize the Rootvalue market selection snapshot.")
    parser.add_argument(
        "--normalize-only",
        action="store_true",
        help="Reapply selection policy to the stored market snapshot without provider calls.",
    )
    args = parser.parse_args()
    main(normalize_only=args.normalize_only)
