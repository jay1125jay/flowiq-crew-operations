#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import kovo_official_pdf_backfill as base


def candidate_urls(season: str, game_no: int) -> list[str]:
    # Older KOVO DB BANK seasons used more than one filename shape.
    # Keep the current padded convention first, then try legacy unpadded names.
    names = [
        f"A_{season}{base.GPART}{game_no:03d}.pdf",
        f"A_{season}{base.GPART}{game_no}.pdf",
    ]
    out = []
    seen = set()
    for name in names:
        url = f"{base.BASE}/{name}"
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def fetch_one(season: str, game_no: int):
    for url in candidate_urls(season, game_no):
        raw = base.fetch_pdf(url, timeout=15, retries=1)
        if not raw:
            continue
        event = base.parse_pdf(raw, season, game_no, url)
        if event:
            event["provider_kind"] = "OFFICIAL_POSTGAME_REPORT_LEGACY_URL"
            event["result"]["source"] = "KOVO_DBBANK_OFFICIAL_LEGACY_URL"
            return game_no, event, url
    return game_no, None, None


def scan_season(season: str, max_game: int, workers: int = 6):
    rows = []
    matched_urls = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as ex:
        futs = {ex.submit(fetch_one, season, n): n for n in range(1, max_game + 1)}
        for fut in as_completed(futs):
            try:
                _, event, url = fut.result()
            except Exception:
                event = None
                url = None
            if event:
                rows.append(event)
                matched_urls.append(url)
    rows.sort(key=lambda e: (e["start_timestamp"], e["id"]))
    return rows, {
        "season": season,
        "scanned": max_game,
        "parsed_events": len(rows),
        "legacy_url_hits": sum(1 for u in matched_urls if u and not u.endswith("001.pdf")),
        "status": "PASS" if rows else "FAIL",
    }


def run(seasons: list[str], max_game: int, workers: int):
    state = base.load_state()
    done = set(state.get("completed_seed_seasons") or [])
    reports = []
    events = []

    for season in seasons:
        if season in done:
            reports.append({"season": season, "status": "SKIP_COMPLETE", "parsed_events": 0})
            continue
        rows, meta = scan_season(season, max_game, workers)
        reports.append(meta)
        events.extend(rows)
        if meta["status"] == "PASS":
            done.add(season)

    merge = base.merge_events(events) if events else {"changed_files": 0, "added": 0, "replaced": 0}
    state["completed_seed_seasons"] = sorted(done, reverse=True)
    state["last_run"] = datetime.now(base.KST).isoformat()
    state["last_legacy_reports"] = reports
    state["last_legacy_merge"] = merge
    base.save_state(state)

    ok = all(r.get("status") in ("PASS", "SKIP_COMPLETE") for r in reports)
    print(json.dumps({
        "KOVO_LEGACY_PDF_BACKFILL": "PASS" if ok else "PARTIAL",
        "reports": reports,
        "events": len(events),
        "merge": merge,
    }, ensure_ascii=False))


def self_test():
    urls = candidate_urls("015", 2)
    assert urls[0].endswith("A_015201002.pdf")
    assert urls[1].endswith("A_0152012.pdf")
    print(json.dumps({"KOVO_LEGACY_SELF_TEST": "PASS", "urls": urls}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--seasons", default="014")
    ap.add_argument("--max-game", type=int, default=260)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    seasons = [x.strip() for x in args.seasons.split(",") if x.strip()]
    run(seasons, args.max_game, args.workers)


if __name__ == "__main__":
    main()
