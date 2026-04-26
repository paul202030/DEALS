"""Real estate deal tracker — pipeline entry point.

Runs end-to-end: collect from sources, keyword pre-filter, LLM extract,
dedupe, persist to SQLite, render static HTML.

Designed for a GitHub Actions cron every 4–6 hours.
"""
import logging
import os
import sys

from src.collectors.edgar import collect_edgar
from src.collectors.rss import collect_rss
from src.db import get_db, init_db
from src.dedupe import find_duplicate, normalize_buyer
from src.extractor import extract_deal
from src.filters import is_candidate
from src.render import render_site

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("main")

MIN_DEAL_SIZE_USD = 20_000_000


def main() -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("ANTHROPIC_API_KEY not set")
        return 1

    init_db()
    conn = get_db()

    # 1. Collect ------------------------------------------------------------
    log.info("collecting from sources")
    items = []
    items.extend(collect_rss(conn))
    items.extend(collect_edgar(conn))
    log.info("collected %d new items", len(items))
    if not items:
        render_site(conn)
        return 0

    # 2. Pre-filter (free, regex) -------------------------------------------
    candidates = [i for i in items if is_candidate(i)]
    log.info("after keyword filter: %d candidates (%.0f%% kept)",
             len(candidates), 100 * len(candidates) / max(1, len(items)))

    # 3. Extract via Haiku 4.5 (the only paid step) -------------------------
    new_deals = 0
    merged = 0
    for item in candidates:
        try:
            deal = extract_deal(item, api_key)
        except Exception as e:  # noqa: BLE001
            log.warning("extractor crashed on %s: %s", item.get("url"), e)
            continue
        if not deal or not deal.get("is_real_estate_acquisition"):
            continue
        price = deal.get("price_usd") or 0
        if price < MIN_DEAL_SIZE_USD:
            continue
        if not deal.get("buyer"):
            continue

        # 4. Dedupe ---------------------------------------------------------
        existing_id = find_duplicate(conn, deal)
        if existing_id:
            conn.execute(
                "INSERT OR IGNORE INTO deal_sources (deal_id, source_url, source_type) VALUES (?, ?, ?)",
                (existing_id, item["url"], item["source_type"]),
            )
            conn.execute(
                "UPDATE deals SET last_updated = datetime('now') WHERE id = ?",
                (existing_id,),
            )
            merged += 1
            continue

        # New deal
        cur = conn.execute(
            """
            INSERT INTO deals (
                buyer, buyer_normalized, seller, asset_name, asset_address,
                city, state, property_type, price_usd, deal_status,
                announcement_date, raw_summary, first_seen, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (
                deal.get("buyer"),
                normalize_buyer(deal.get("buyer")),
                deal.get("seller"),
                deal.get("asset_name"),
                deal.get("asset_address"),
                deal.get("city"),
                _state(deal.get("state")),
                deal.get("property_type"),
                deal.get("price_usd"),
                deal.get("deal_status") or "announced",
                deal.get("announcement_date"),
                deal.get("summary"),
            ),
        )
        conn.execute(
            "INSERT INTO deal_sources (deal_id, source_url, source_type) VALUES (?, ?, ?)",
            (cur.lastrowid, item["url"], item["source_type"]),
        )
        new_deals += 1

    conn.commit()
    log.info("inserted %d new deals, merged %d into existing", new_deals, merged)

    # 5. Render -------------------------------------------------------------
    render_site(conn)
    log.info("done")
    return 0


def _state(s):
    if not s:
        return None
    s = s.strip().upper()
    return s[:2] if len(s) >= 2 else None


if __name__ == "__main__":
    sys.exit(main())
