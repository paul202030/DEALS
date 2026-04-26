"""SEC EDGAR collector — recent 8-K filings mentioning real-estate transactions.

Uses EDGAR's full-text search (efts.sec.gov) rather than a curated CIK list,
so it picks up private filers like BREIT and SREIT alongside public REITs.

SEC requires an identifiable User-Agent. Set EDGAR_UA env var to your own
contact info or leave the default.

If the EDGAR search API ever changes shape, this is the file to adjust.
"""
import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import List

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

UA = os.environ.get("EDGAR_UA", "ReDealTracker research-tool@example.com")
HEADERS = {"User-Agent": UA, "Accept": "application/json"}
SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

# Different ways acquisitions show up in 8-K language. Each query is one
# search-index call; results are deduped via seen_items.
QUERIES = [
    '"completed the acquisition of"',
    '"agreed to acquire"',
    '"acquired" "portfolio"',
    '"acquired" "property" OR "properties"',
    '"closed on the acquisition"',
]


def _hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _strip_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "meta", "link", "head"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())


def collect_edgar(conn, days_back: int = 3) -> List[dict]:
    out: List[dict] = []
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days_back)
    now_iso = datetime.now(timezone.utc).isoformat()

    for q in QUERIES:
        params = {
            "q": q,
            "forms": "8-K",
            "dateRange": "custom",
            "startdt": start.strftime("%Y-%m-%d"),
            "enddt": end.strftime("%Y-%m-%d"),
        }
        try:
            log.info("EDGAR search: %s", q)
            r = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            log.warning("EDGAR search failed (%s): %s", q, e)
            continue

        hits = data.get("hits", {}).get("hits", [])
        log.info("  %d hits", len(hits))
        for hit in hits:
            src = hit.get("_source", {})
            hit_id = hit.get("_id", "")
            ciks = src.get("ciks", [])
            adsh = src.get("adsh", "")
            if not ciks or not adsh or ":" not in hit_id:
                continue
            cik = int(ciks[0])
            accno = adsh.replace("-", "")
            doc = hit_id.split(":", 1)[1]
            doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accno}/{doc}"

            h = _hash(doc_url)
            if conn.execute("SELECT 1 FROM seen_items WHERE url_hash=?", (h,)).fetchone():
                continue

            names = src.get("display_names") or []
            title = (names[0] if names else "8-K") + " — 8-K"

            try:
                fr = requests.get(doc_url, headers={"User-Agent": UA}, timeout=30)
                if fr.status_code != 200:
                    continue
                text = _strip_html(fr.text)[:8000]
            except Exception as e:  # noqa: BLE001
                log.warning("fetch failed %s: %s", doc_url, e)
                continue

            out.append(
                {
                    "url": doc_url,
                    "source_type": "edgar",
                    "title": title,
                    "content": text,
                    "published": src.get("file_date", ""),
                }
            )
            conn.execute(
                "INSERT OR IGNORE INTO seen_items (url_hash, url, source_type, seen_at) VALUES (?, ?, ?, ?)",
                (h, doc_url, "edgar", now_iso),
            )
            time.sleep(0.12)  # SEC fair-use: ≤10 req/s

        conn.commit()
        time.sleep(0.5)

    return out
