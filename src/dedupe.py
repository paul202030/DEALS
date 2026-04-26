"""Deduplication.

A single deal (e.g. KKR buys industrial portfolio for $850M) typically
hits us via 3-5 sources: the 8-K, a press release wire, and 2-3 trade pubs.
We want to collapse those into one row with multiple source URLs.

Heuristic: same normalized buyer + price within 2% = same deal. This is
robust because (buyer, price) is high-entropy enough that a collision is
almost certainly the same transaction.

Edge cases to be aware of:
- Two unrelated deals from the same buyer at the same price in the same
  window: rare but possible (institutional buyers do same-size acquisitions).
  Mitigation: also require asset name OR city overlap if available.
- Price not disclosed: we can't dedupe by price. Falls back to (buyer, asset_name).
"""
import re
from typing import Optional


_SUFFIX = re.compile(
    r"\b(inc|llc|lp|llp|ltd|corp|corporation|trust|reit|holdings|"
    r"partners|capital|management|group|company|co|n\.?v\.?|s\.?a\.?)\b\.?",
    re.I,
)


def normalize_buyer(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.lower()
    s = _SUFFIX.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = " ".join(s.split())
    return s


def find_duplicate(conn, deal: dict) -> Optional[int]:
    buyer_norm = normalize_buyer(deal.get("buyer"))
    if not buyer_norm:
        return None
    price = deal.get("price_usd")

    if price:
        lo = int(price * 0.98)
        hi = int(price * 1.02)
        rows = conn.execute(
            """
            SELECT id, asset_name, city
            FROM deals
            WHERE buyer_normalized = ?
              AND price_usd BETWEEN ? AND ?
              AND first_seen >= datetime('now', '-60 days')
            """,
            (buyer_norm, lo, hi),
        ).fetchall()
        for row in rows:
            # If we have an asset hint on either side, require some overlap.
            new_asset = (deal.get("asset_name") or "").lower()
            new_city = (deal.get("city") or "").lower()
            old_asset = (row["asset_name"] or "").lower()
            old_city = (row["city"] or "").lower()
            if new_asset and old_asset:
                if _share_token(new_asset, old_asset):
                    return row["id"]
                continue
            if new_city and old_city:
                if new_city == old_city:
                    return row["id"]
                continue
            # No asset/city info on either side — buyer + tight price match is enough.
            return row["id"]
        return None

    # No price: fall back to (buyer, asset_name) within 30 days.
    asset = deal.get("asset_name")
    if not asset:
        return None
    rows = conn.execute(
        """
        SELECT id, asset_name FROM deals
        WHERE buyer_normalized = ?
          AND first_seen >= datetime('now', '-30 days')
        """,
        (buyer_norm,),
    ).fetchall()
    target = asset.lower()
    for row in rows:
        if row["asset_name"] and _share_token(row["asset_name"].lower(), target):
            return row["id"]
    return None


def _share_token(a: str, b: str) -> bool:
    """Loose check: do these strings share any meaningful token?"""
    stop = {"the", "a", "an", "of", "at", "in", "on", "and", "portfolio", "properties"}
    ta = {t for t in re.findall(r"[a-z0-9]+", a) if len(t) > 2 and t not in stop}
    tb = {t for t in re.findall(r"[a-z0-9]+", b) if len(t) > 2 and t not in stop}
    return bool(ta & tb)
