"""RSS feed collector.

Polls a YAML-configured list of trade-press feeds. Returns only items not
yet seen — anything new gets recorded in seen_items so we never re-process.
RSS gives us title + summary in a single fetch, no per-item HTTP needed,
which keeps this stage fast and free.
"""
import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import feedparser
import yaml

log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "sources.yaml"
USER_AGENT = "ReDealTracker/0.1 (+https://github.com/yourname/re-deal-tracker)"


def _hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _strip(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "").strip()


def _load_feeds() -> List[str]:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f).get("rss_feeds", [])


def collect_rss(conn) -> List[dict]:
    feeds = _load_feeds()
    out: List[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    for url in feeds:
        try:
            log.info("fetching feed %s", url)
            d = feedparser.parse(url, agent=USER_AGENT)
            if d.bozo:
                log.warning("feed parse warning %s: %s", url, d.bozo_exception)
            for entry in d.entries:
                link = entry.get("link")
                if not link:
                    continue
                h = _hash(link)
                if conn.execute("SELECT 1 FROM seen_items WHERE url_hash=?", (h,)).fetchone():
                    continue

                title = entry.get("title", "")
                summary = entry.get("summary", "") or entry.get("description", "")
                # Some feeds include full text in content[].value
                full = ""
                if "content" in entry and entry.content:
                    full = entry.content[0].value
                body = _strip(full or summary)
                content = f"{title}\n\n{body}"

                out.append(
                    {
                        "url": link,
                        "source_type": "rss",
                        "title": title,
                        "content": content,
                        "published": entry.get("published") or entry.get("updated") or "",
                    }
                )
                conn.execute(
                    "INSERT OR IGNORE INTO seen_items (url_hash, url, source_type, seen_at) VALUES (?, ?, ?, ?)",
                    (h, link, "rss", now),
                )
            conn.commit()
            time.sleep(0.5)  # be polite to publishers
        except Exception as e:  # noqa: BLE001
            log.warning("feed %s failed: %s", url, e)
            continue

    return out
