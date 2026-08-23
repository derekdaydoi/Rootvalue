from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "global.json"
NOW = datetime.now(timezone.utc)
HEADERS = {"User-Agent": "Rootvalue/1.0 personal-research (github.com/derekdaydoi/Rootvalue)"}

SERIES = {
    "fed_funds_effective": {"id": "DFF", "label": "Fed funds effective", "unit": "%", "frequency": "daily", "source": "Federal Reserve / FRED"},
    "fed_total_assets": {"id": "WALCL", "label": "Fed total assets", "unit": "USD mn", "frequency": "weekly", "source": "Federal Reserve H.4.1 / FRED"},
    "fed_overnight_rrp": {"id": "RRPONTSYD", "label": "Fed overnight reverse repo", "unit": "USD bn", "frequency": "daily", "source": "New York Fed / FRED"},
    "broad_dollar": {"id": "DTWEXBGS", "label": "Broad U.S. dollar index", "unit": "index", "frequency": "daily", "source": "Federal Reserve H.10 / FRED"},
    "us_2y": {"id": "DGS2", "label": "U.S. Treasury 2Y", "unit": "%", "frequency": "daily", "source": "U.S. Treasury / FRED"},
    "us_10y": {"id": "DGS10", "label": "U.S. Treasury 10Y", "unit": "%", "frequency": "daily", "source": "U.S. Treasury / FRED"},
    "vix": {"id": "VIXCLS", "label": "VIX", "unit": "index", "frequency": "daily", "source": "CBOE / FRED"},
    "wti": {"id": "DCOILWTICO", "label": "WTI crude oil", "unit": "USD/bbl", "frequency": "daily", "source": "EIA / FRED"},
}

RSS_FEEDS = [
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    ("ECB", "https://www.ecb.europa.eu/rss/press.html"),
]


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def public_error(value: Any, limit: int = 320) -> str:
    text = re.sub(r"https?://\S+", "<redacted-url>", str(value or ""))
    names = r"api[_ -]?key|access[_ -]?token|token|authorization|client[_ -]?secret"
    quoted = re.compile(rf"(?i)([\"']?(?:{names})[\"']?\s*[:=]\s*)([\"'])(.*?)(\2)")
    text = quoted.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>{match.group(2)}", text)
    text = re.sub(rf"(?i)([\"']?(?:{names})[\"']?\s*[:=]\s*)(?:Bearer\s+)?[^\s,;}}\]]+", r"\1<redacted>", text)
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", text)
    return re.sub(r"\s+", " ", text).strip()[:limit] or "source error"


def semantic_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: semantic_payload(value)
            for key, value in payload.items()
            if key not in {"generated_at", "last_attempt_at"}
        }
    if isinstance(payload, list):
        return [semantic_payload(value) for value in payload]
    return payload


def write_if_changed(path: Path, payload: dict[str, Any]) -> bool:
    previous = load(path, None)
    if previous is not None and semantic_payload(previous) == semantic_payload(payload):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return True


def with_source_freshness(node: dict[str, Any], frequency: str) -> dict[str, Any]:
    enriched = dict(node)
    try:
        source_date = datetime.fromisoformat(str(node.get("as_of"))[:10]).date()
        age = max((NOW.date() - source_date).days, 0)
    except Exception:
        age = None
    threshold = 14 if frequency == "weekly" else 7
    enriched["source_age_days"] = age
    enriched["freshness"] = "current" if age is not None and age <= threshold else "stale"
    enriched["stale_after_days"] = threshold
    if enriched.get("status") == "ok" and enriched["freshness"] == "stale":
        enriched["status"] = "stale"
    return enriched


def coverage_status(
    series: dict[str, Any],
    feeds: list[dict[str, Any]],
    news: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    ok_series = sum(1 for node in series.values() if node.get("status") == "ok")
    usable_series = sum(
        1
        for node in series.values()
        if node.get("status") in {"ok", "stale"} and node.get("history")
    )
    fresh_feeds = sum(1 for feed in feeds if feed.get("status") == "ok")
    all_required_fresh = ok_series == len(SERIES) and fresh_feeds == len(RSS_FEEDS)
    status = "ok" if all_required_fresh else ("partial" if usable_series or news else "error")
    coverage = {
        "required_series": len(SERIES),
        "fresh_series": ok_series,
        "usable_series": usable_series,
        "required_feeds": len(RSS_FEEDS),
        "fresh_feeds": fresh_feeds,
        "all_required_fresh": all_required_fresh,
    }
    return status, coverage


def to_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if not value or value == ".":
        return None
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def fetch_fred_series(series_id: str) -> dict[str, Any]:
    import requests

    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = requests.get(url, timeout=30, headers=HEADERS)
    r.raise_for_status()
    reader = csv.DictReader(io.StringIO(r.text))
    points: list[dict[str, Any]] = []
    for row in reader:
        date = row.get("DATE") or row.get("observation_date") or next(iter(row.values()), None)
        value = row.get(series_id)
        if value is None and len(row) >= 2:
            value = list(row.values())[1]
        number = to_float(value)
        if date and number is not None:
            points.append({"date": str(date), "value": number})
    if not points:
        raise RuntimeError(f"No usable observations for {series_id}")
    points = points[-420:]
    latest = points[-1]
    prev = points[-2] if len(points) > 1 else None
    return {
        "status": "ok",
        "series_id": series_id,
        "as_of": latest["date"],
        "latest": latest["value"],
        "previous": prev["value"] if prev else None,
        "change": latest["value"] - prev["value"] if prev else None,
        "history": points,
        "url": f"https://fred.stlouisfed.org/series/{series_id}",
    }


def text(node: ET.Element | None, tag: str) -> str:
    if node is None:
        return ""
    found = node.find(tag)
    return (found.text or "").strip() if found is not None and found.text else ""


def clean_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


def fetch_rss(source: str, url: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        import requests

        r = requests.get(url, timeout=30, headers=HEADERS)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
        output: list[dict[str, Any]] = []
        for item in items[:12]:
            title = text(item, "title")
            link = text(item, "link")
            date = text(item, "pubDate") or text(item, "date")
            desc = clean_html(text(item, "description"))[:320]
            if title:
                output.append({"source": source, "title": title, "url": link, "published": date, "summary": desc})
        return output, {"source": source, "url": url, "status": "ok", "items": len(output)}
    except Exception as exc:
        return [], {"source": source, "url": url, "status": "error", "error": public_error(exc), "items": 0}


def main(normalize_only: bool = False) -> None:
    previous = load(OUT, {})
    if normalize_only:
        if not previous:
            raise SystemExit("data/global.json is missing; cannot normalize stored freshness")
        normalized_series = {
            key: with_source_freshness(node, SERIES.get(key, {}).get("frequency", "daily"))
            for key, node in previous.get("series", {}).items()
        }
        status, coverage = coverage_status(
            normalized_series,
            list(previous.get("feeds", [])),
            list(previous.get("news", [])),
        )
        normalized = {
            **previous,
            "status": status,
            "coverage": coverage,
            "series": normalized_series,
        }
        changed = write_if_changed(OUT, normalized)
        print(json.dumps({"mode": "normalize-only", "status": status, "coverage": coverage, "changed": changed}, ensure_ascii=False))
        return

    previous_series = previous.get("series", {})
    series: dict[str, Any] = {}
    errors: list[str] = []
    for key, meta in SERIES.items():
        try:
            node = fetch_fred_series(meta["id"])
            node.update({k: v for k, v in meta.items() if k != "id"})
            series[key] = with_source_freshness(node, meta["frequency"])
        except Exception as exc:
            message = public_error(exc)
            errors.append(f"{key}: {message}")
            old = previous_series.get(key, {})
            if old.get("history") and old.get("as_of"):
                kept = with_source_freshness(old, meta["frequency"])
                kept.update({"status": "stale", "last_error": message, "last_attempt_at": NOW.isoformat()})
                series[key] = kept
            else:
                series[key] = {"status": "error", **meta, "error": message}

    news: list[dict[str, Any]] = []
    feeds: list[dict[str, Any]] = []
    previous_news: dict[str, list[dict[str, Any]]] = {}
    for item in previous.get("news", []):
        previous_news.setdefault(str(item.get("source") or ""), []).append(item)
    previous_feeds = {str(item.get("source") or ""): item for item in previous.get("feeds", [])}
    for source, url in RSS_FEEDS:
        items, health = fetch_rss(source, url)
        if health.get("status") == "ok":
            news.extend(items)
        elif previous_news.get(source):
            news.extend(previous_news[source])
            old_health = previous_feeds.get(source, {})
            health = {
                **old_health,
                **health,
                "status": "stale",
                "items": len(previous_news[source]),
                "last_attempt_at": NOW.isoformat(),
            }
        feeds.append(health)

    # Preserve source ordering and cap payload. We deliberately do not machine-summarize headlines.
    news = news[:24]
    status, coverage = coverage_status(series, feeds, news)
    payload = {
        "schema_version": "1.0.0",
        "generated_at": NOW.isoformat(),
        "status": status,
        "freshness_class": "near-real-time / source-release cadence",
        "accuracy_policy": "Official/primary releases are preferred. Rootvalue stores source dates separately from fetch time and never labels delayed official statistics as real-time.",
        "coverage": coverage,
        "series": series,
        "news": news,
        "feeds": feeds,
        "errors": errors,
    }
    changed = write_if_changed(OUT, payload)
    print(json.dumps({"status": payload["status"], "series_ok": f"{coverage['fresh_series']}/{len(SERIES)}", "series_usable": f"{coverage['usable_series']}/{len(SERIES)}", "feeds_ok": f"{coverage['fresh_feeds']}/{len(RSS_FEEDS)}", "news": len(news), "errors": errors, "changed": changed}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh or normalize the Rootvalue global snapshot.")
    parser.add_argument(
        "--normalize-only",
        action="store_true",
        help="Recompute stored source freshness and top-level status without network calls.",
    )
    args = parser.parse_args()
    main(normalize_only=args.normalize_only)
