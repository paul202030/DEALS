# RE Deal Tracker

A small, frugal pipeline that surfaces newly announced US institutional commercial real estate transactions ($20M+) within hours of the announcement. Designed to run for under $3/week on the Anthropic API and free on GitHub.

## What it does

Every 6 hours, a GitHub Actions cron runs the pipeline:

1. **Collects** new items from CRE trade-press RSS feeds and recent SEC EDGAR 8-K filings.
2. **Pre-filters** with regex (transaction verbs + real-estate nouns + dollar amounts) to drop ~75% of noise before any LLM call.
3. **Extracts** structured deal data using Claude Haiku 4.5 with prompt caching: buyer, seller, asset, location, type, price, status.
4. **Dedupes** by normalized buyer + price within 2% (a single deal usually shows up across 3-5 sources).
5. **Renders** a static HTML page deployed to GitHub Pages with sortable, filterable deal feed.

The SQLite database (`data/deals.db`) is committed back to the repo on every run, so history is preserved and the site is always reproducible.

## Cost

| Line item | Estimate |
|---|---|
| Claude Haiku 4.5 ($1/M in, $5/M out, 90% off cached input) | ~$0.80–1.20/week |
| GitHub Actions cron | $0 (well within free tier) |
| GitHub Pages hosting | $0 |
| SEC EDGAR + RSS feeds | $0 |
| **Total** | **<$2/week** |

Math: ~300-500 candidate items/week reach the LLM after pre-filtering. Each call is ~2,500 input tokens (mostly cached system prompt) + ~300 output tokens. With caching, that's ~$0.003-0.004/item.

If the bill creeps up, switch on the [Batch API](https://docs.claude.com/en/docs/build-with-claude/batch-processing) in `src/extractor.py` for a flat 50% discount in exchange for ~5min latency.

## Coverage

Targets the **majority** of $20M+ deals — not every one. Coverage by source category:

- **Public REIT acquisitions** → caught via EDGAR 8-Ks (Item 1.01 / 2.01).
- **Non-traded REIT and private fund acquisitions** (BREIT, SREIT, Ares, etc.) → also EDGAR.
- **Private institutional deals** (PE, family offices, foreign capital) → caught via trade-press RSS.

What's likely missed: deals that close quietly with no press release and no SEC filing trigger (some smaller portfolio bolt-ons), and deals reported only behind paywalls (Real Estate Alert, paywalled CoStar). Adding paid sources would push coverage up but blow the budget.

## Setup

### 1. Fork or clone this repo

```bash
git clone <this-repo> re-deal-tracker
cd re-deal-tracker
```

### 2. Get an Anthropic API key

Sign up at <https://console.anthropic.com>, then add a couple dollars of credit. Add the key as a GitHub repo secret:

- Settings → Secrets and variables → Actions → New repository secret
- Name: `ANTHROPIC_API_KEY`
- Value: `sk-ant-...`

Optionally also add `EDGAR_UA` with your contact email — SEC EDGAR's terms require an identifiable User-Agent.

### 3. Enable GitHub Pages

- Settings → Pages → Source: **GitHub Actions**

### 4. Enable Actions write permissions

- Settings → Actions → General → Workflow permissions → **Read and write permissions**

### 5. Trigger the first run

- Actions tab → "Track deals" → Run workflow

After 5-10 minutes you'll have a populated database and a published feed at `https://<your-username>.github.io/<repo-name>/`.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python main.py
open docs/index.html  # macOS, or `xdg-open` on Linux
```

## Architecture

```
sources/        →  pre-filter   →  Haiku 4.5    →  dedupe   →  SQLite  →  static HTML
(RSS + EDGAR)     (regex, free)    (paid step)     (free)      (free)     (GitHub Pages)
```

```
.
├── main.py                       # pipeline orchestrator
├── src/
│   ├── db.py                     # SQLite schema
│   ├── filters.py                # keyword pre-filter
│   ├── extractor.py              # Haiku 4.5 extraction
│   ├── dedupe.py                 # buyer+price collapse
│   ├── render.py                 # static HTML generator
│   └── collectors/
│       ├── rss.py                # trade-press feeds
│       └── edgar.py              # SEC 8-K full-text search
├── config/sources.yaml           # feed list (edit this)
├── data/deals.db                 # SQLite, committed
├── docs/index.html               # GitHub Pages output
├── .github/workflows/run.yml     # 6-hour cron
└── requirements.txt
```

## Tuning knobs

- **Deal size threshold**: change `MIN_DEAL_SIZE_USD` in `main.py`. Lower it to $5M to capture more, raise it to $50M to focus on landmarks. Lower thresholds increase volume and cost roughly linearly.
- **Cron frequency**: edit `.github/workflows/run.yml`. Every 4 hours doubles latency-to-signal and stays in the free tier. Hourly is overkill for 6-12 hour news cycles.
- **Sources**: add RSS feeds in `config/sources.yaml` (no code changes needed). Useful additions: regional pubs (`bizjournals.com` city feeds), specific firms' press release pages, BusinessWire/PRNewswire category feeds.
- **Dedupe strictness**: `find_duplicate` in `src/dedupe.py` uses 2% price tolerance. Tighten to 1% for high-volume deals if you see false merges, or loosen to 5% if rounding in trade press causes splits.
- **Extraction prompt**: in `src/extractor.py`. Tweak the schema or rules for your use case (e.g. add a "lender" field, or a confidence score).

## Known limitations

1. Some RSS feeds rate-limit aggressive polling. The 6-hour cadence is well within polite ranges; don't drop it below hourly.
2. EDGAR full-text search misses filings that don't use the canonical phrases ("acquired", "completed the acquisition of", etc.). Add more queries in `src/collectors/edgar.py` if you find gaps.
3. The deduper assumes price is reliable. If a source rounds aggressively (e.g. "$400M" vs "$412.5M"), the 2% tolerance may not catch the merge — extraction-time normalization would help.
4. Buyer entity resolution is light. "Blackstone Real Estate Income Trust" and "BREIT" both deduplicate to the same normalized form, but more obscure subsidiaries might not. For tighter rollups, maintain a manual alias table.

## License

MIT — do whatever you want.
