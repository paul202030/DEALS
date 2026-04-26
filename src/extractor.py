"""LLM extraction with Haiku 4.5.

Cost notes:
- $1/M input, $5/M output. With prompt caching the 1.5K-token system prompt
  costs $0.10/M after the first call instead of $1/M. Per article: roughly
  $0.003-0.004 — call it $1/week at 300 articles/week.
- Cache TTL is 5 min by default, so we want runs to process candidates
  back-to-back rather than in parallel batches. The orchestrator already
  does that.
"""
import json
import logging
from typing import Optional

from anthropic import Anthropic

log = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 600
MAX_INPUT_CHARS = 6000  # ~1500 tokens — keeps long EDGAR filings cheap

SYSTEM_PROMPT = """You extract structured data about US commercial real estate transactions from news articles and SEC filings.

Determine whether the input describes a SPECIFIC commercial real estate acquisition or sale where the buyer is an institutional investor (REIT, private equity, asset manager, pension fund, sovereign wealth fund, family office, large operator, etc.). Output JSON only — no prose, no markdown fences.

Required schema:
{
  "is_real_estate_acquisition": boolean,
  "buyer": string|null,
  "seller": string|null,
  "asset_name": string|null,
  "asset_address": string|null,
  "city": string|null,
  "state": string|null,                       // 2-letter US code
  "property_type": string|null,               // multifamily | office | industrial | retail | hotel | data_center | self_storage | sfr | mixed_use | land | healthcare | other
  "price_usd": integer|null,                  // total deal value, e.g. "$450 million" -> 450000000
  "deal_status": string|null,                 // announced | under_contract | closed | terminated
  "announcement_date": string|null,           // YYYY-MM-DD
  "summary": string                           // one factual sentence
}

Rules:
- Set is_real_estate_acquisition=false for: market commentary, fundraising news, earnings without specific deals, individual home sales, refinancings or loan originations, M&A of operating companies (not asset purchases), insurance/management contracts.
- Use the parent/sponsor name for buyer when the article makes the relationship clear (a Blackstone subsidiary -> "Blackstone"). Otherwise use the entity as named.
- Portfolio deals: asset_name = portfolio descriptor, asset_address = null, city/state = primary metro if mentioned (else null).
- Joint ventures: list the lead acquirer as buyer.
- If price_usd is not disclosed, return null — do not estimate.
- Always populate "summary" even when is_real_estate_acquisition is false (one short sentence describing what the article is about).
- Output strictly valid JSON. No trailing commas, no comments, no extra keys."""


def extract_deal(item: dict, api_key: str) -> Optional[dict]:
    client = Anthropic(api_key=api_key)
    content = (item.get("content") or "")[:MAX_INPUT_CHARS]
    user = (
        f"Source: {item.get('source_type')}\n"
        f"URL: {item.get('url')}\n"
        f"Title: {item.get('title')}\n"
        f"Published: {item.get('published')}\n\n"
        f"Content:\n{content}"
    )

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user}],
        )
    except Exception as e:  # noqa: BLE001
        log.warning("API call failed for %s: %s", item.get("url"), e)
        return None

    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    if text.startswith("```"):
        # Defensive: strip a fence even though we asked for none.
        first = text.find("\n")
        last = text.rfind("```")
        if first != -1 and last > first:
            text = text[first + 1:last].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        log.warning("JSON parse failed for %s: %s — head=%s", item.get("url"), e, text[:200])
        return None
