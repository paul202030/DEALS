"""Cheap keyword pre-filter — runs before any LLM call.

Goal: drop ~75% of incoming items so we only spend tokens on plausible
real-estate transactions. Recall matters more than precision here; the LLM
catches false positives downstream.

An item passes if it contains:
  - a transaction verb (acquired, purchased, sold, ...) AND
  - either a real-estate noun OR an explicit dollar amount
"""
import re

_TXN = re.compile(
    r"\b("
    r"acquir(?:ed|es|ing|ition)|"
    r"purchas(?:ed|es|ing|e)|"
    r"sold|sale of|"
    r"closed on|closing on|"
    r"completed (?:its|the)? ?(?:acquisition|purchase|sale)|"
    r"agreed to (?:acquire|purchase|buy|sell)|"
    r"under contract|"
    r"dispos(?:ed|al|ition) of|"
    r"divest(?:ed|ment|iture)?"
    r")\b",
    re.I,
)

_RE_NOUN = re.compile(
    r"\b("
    r"apartment|multifamily|multi-family|"
    r"office (?:building|tower|campus|complex|portfolio)|"
    r"industrial|warehouse|logistics|distribution center|fulfillment center|"
    r"retail|shopping (?:center|mall)|outlet|strip (?:mall|center)|power center|"
    r"hotel|hospitality|resort|"
    r"data ?center|"
    r"self.?storage|"
    r"single.family rental|build.to.rent|btr|sfr|"
    r"medical office|life science|"
    r"real estate|REIT|"
    r"property|properties|portfolio|"
    r"square (?:feet|ft)|sq\.? ?ft|sf\b|"
    r"\b\d{2,4}\s+(?:units|doors|keys|beds)"
    r")\b",
    re.I,
)

_DOLLAR = re.compile(
    r"(\$\s?\d{1,4}(?:[,.]\d+)?\s?(?:million|billion|m\b|b\b|mm\b))",
    re.I,
)


def is_candidate(item: dict) -> bool:
    text = f"{item.get('title', '')}\n{item.get('content', '')}"
    if not text.strip():
        return False
    has_txn = bool(_TXN.search(text))
    if not has_txn:
        return False
    has_re = bool(_RE_NOUN.search(text))
    has_dollar = bool(_DOLLAR.search(text))
    return has_re or has_dollar
