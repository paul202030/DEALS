"""SQLite schema + connection helper.

The DB is committed to the repo (data/deals.db). At ~1KB per deal that's
~5MB after a couple thousand deals, well within Git's comfort zone.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "deals.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer TEXT NOT NULL,
    buyer_normalized TEXT,
    seller TEXT,
    asset_name TEXT,
    asset_address TEXT,
    city TEXT,
    state TEXT,
    property_type TEXT,
    price_usd INTEGER,
    deal_status TEXT,
    announcement_date TEXT,
    raw_summary TEXT,
    first_seen TEXT NOT NULL,
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS deal_sources (
    deal_id INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    PRIMARY KEY (deal_id, source_url),
    FOREIGN KEY (deal_id) REFERENCES deals(id)
);

-- Tracks every URL we've seen so we never re-fetch or re-extract.
CREATE TABLE IF NOT EXISTS seen_items (
    url_hash TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    seen_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_deals_buyer ON deals(buyer_normalized);
CREATE INDEX IF NOT EXISTS idx_deals_state ON deals(state);
CREATE INDEX IF NOT EXISTS idx_deals_date ON deals(first_seen);
CREATE INDEX IF NOT EXISTS idx_seen_at ON seen_items(seen_at);
"""


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
