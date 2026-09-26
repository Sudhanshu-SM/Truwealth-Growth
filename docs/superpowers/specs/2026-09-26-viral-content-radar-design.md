# Truwealth Viral Content Radar — Design

- **Date:** 2026-09-26
- **Status:** Design approved in brainstorming; spec pending user review
- **Scope:** v1 suggestion pipeline (detect trending Indian finance topics, email briefs with angles)

## 1. Problem

Truwealth is an Indian financial advisory firm. Its founder wants to post on LinkedIn, X and Instagram about finance topics while they are trending. Finance buzz in India (market moves, RBI/SEBI decisions, tax changes, IPO frenzies, scams) rises and dies within hours, so a suggestion that arrives after the peak is useless.

The radar polls free public signals every 15 minutes, works out which finance topics are spiking, and emails the founder a brief: what is trending, the evidence, how urgent it is, which content angles fit each platform, and the compliance points to respect.

## 2. Decisions

| Area | Decision |
|---|---|
| Market | India. English and Hindi signals |
| Founder posts on | LinkedIn, X, Instagram |
| Alerts | Email: instant HOT alert plus a daily digest at 08:00 IST |
| Output | Brief + angles only. No post drafts or scripts in v1 |
| Topics | Personal finance, Markets & macro, Wealth/HNI, Trading & stocks (education framing only) |
| Budget | $0/month |
| X signal | Public trend mirrors only (trends24.in, getdaytrends.com). No X API, no cookie scraping |
| Detection | Fixed topic list plus new-phrase spike detection. No ML models |
| Hosting | GitHub Actions, public repository, every 15 minutes |
| Presentation | No color coding or emoji markers anywhere. All labels are plain text |
| Regulatory status (assumption) | Truwealth is a SEBI-registered Investment Adviser (INA number). If it is an AMFI-registered distributor (ARN) or another category, the compliance notes in section 11 must change |

## 3. Success criteria

1. **Speed:** a spike visible in the sources produces a HOT email within 30 minutes in the typical case (15-minute cadence plus GitHub schedule delay). Signals only visible on the X mirrors arrive within 75 minutes.
2. **Noise:** at most 4 HOT emails per IST day. A topic alerts at most once per 12 hours unless its heat doubles.
3. **Reliability:** the digest arrives daily; a missing digest means the radar is broken. A failing source never stops a run.
4. **Cost:** $0/month.
5. **Compliance-aware:** every brief carries a compliance label and notes. Restricted topics only receive education-safe angles.

## 4. Non-goals (v1)

Post drafts or Reel scripts; LLM-generated text; Instagram or LinkedIn data collection; paid APIs; X cookie scraping; dashboards; auto-posting; engagement feedback loop. Phase 2 candidates are listed in section 15.

## 5. Architecture

```
GitHub Actions, cron every 15 min
  python -m radar run
    1. restore radar.db from the Actions cache
    2. collectors, each isolated          -> list[Signal]
    3. store new items, match to topics (topics.yaml), detect new-phrase spikes
    4. scorer: per-topic values -> heat -> stage -> alert decisions
    5. briefs: evidence + angles + compliance
    6. emailer: send HOT emails (or write out/*.html with --dry-run)
    7. prune radar.db, save it back to the cache

GitHub Actions, cron 02:30 UTC (08:00 IST)
  python -m radar digest
```

### Module layout

```
radar/
  __main__.py        CLI: run [--dry-run] | digest [--dry-run]
  config.py          load and validate YAML config
  models.py          Signal, Topic, Angle, Brief dataclasses
  http.py            shared httpx client: 10 s timeout, 1 retry, browser User-Agent
  store.py           SQLite schema, queries, pruning
  timeutil.py        UTC/IST helpers (IST is a fixed UTC+05:30 offset; India has no DST)
  collectors/
    __init__.py      registry; runs collectors concurrently with per-collector isolation
    google_trends.py
    google_news.py
    news_feeds.py
    regulators.py
    x_trends.py
    youtube.py
    reddit.py
    markets.py
  events.py          events.yaml -> upcoming events (digest only)
  matcher.py         text -> topic ids
  phrases.py         n-grams, burst detection, emerging topics
  scorer.py          values, baselines, heat, stage, alert decisions
  hooks.py           video title -> angle type (format scoreboard)
  briefs.py          assemble Brief objects
  emailer.py         render (Jinja2) and send (SMTP), or write out/*.html
  templates/         hot.html, hot.txt, digest.html, digest.txt
config/
  settings.yaml      thresholds, weights, priors, caps, cooldowns
  topics.yaml        ~47 topics
  angles.yaml        15 angle types
  sources.yaml       feeds, Google News queries, subreddits, tickers and thresholds
  channels.yaml      ~100 Indian finance YouTube creators
  events.yaml        dated events
tests/
  fixtures/          saved real responses (RSS, HTML, JSON)
  test_*.py
.github/workflows/   radar.yml, digest.yml, ci.yml
requirements.txt     httpx, feedparser, selectolax, PyYAML, Jinja2
requirements-dev.txt pytest
README.md, .gitignore
```

### Unit boundaries

| Unit | Does | Depends on |
|---|---|---|
| collectors/* | Fetch one source, return `list[Signal]` | http, config, store (rotation state, last-fetch times) |
| matcher | Map text to topic ids | topics.yaml |
| phrases | Count phrases, find bursts, create or refresh emerging topics | store, matcher |
| scorer | Compute topic values, heat, stage; decide alerts | store, settings |
| hooks | Classify a title into an angle type | none |
| briefs | Build a Brief for a topic | store, angles.yaml, hooks |
| emailer | Render and deliver HOT and digest emails | templates, SMTP |

Every collector module exposes a pure `parse(raw, ...) -> list[Signal]` function (tested against fixtures) and `collect(ctx) -> list[Signal]`, which fetches and then calls `parse`. `ctx` carries the HTTP client, config, store, current UTC time and run index.

## 6. Data model

```python
@dataclass
class Signal:
    source: str            # collector id, e.g. "google_news", "trends24", "youtube"
    source_type: str       # news | search_trend | x_trend | video | forum | market | regulator
    feed: str              # outlet/feed id, e.g. "et_markets", "gn:tax", "r/IndiaInvestments"
    title: str
    url: str | None
    published_at: datetime | None   # UTC
    text: str = ""         # summary/description used for matching
    lang: str = "en"       # en | hi
    metrics: dict[str, float] = field(default_factory=dict)
```

Metrics by source type: `search_trend` {approx_traffic}; `x_trend` {rank}; `video` {views, outlier, age_h, is_short}; `forum` {rising_rank}; `market` {pct_move}.

**Item identity:** news items use `sha1("news" + normalized title)`, where normalization lowercases, strips a trailing " - Source" suffix and collapses whitespace. This dedupes the same headline arriving from Google News and a direct feed. Videos use the YouTube video id. Everything else uses `sha1(url)`. Google Trends and X trend entries use `sha1(source + title + IST hour)`, so each appearance counts once per hour.

### SQLite tables (timestamps are ISO-8601 UTC)

| Table | Purpose | Retention |
|---|---|---|
| `items(id PK, source, source_type, feed, title, url, published_at, first_seen_at, lang, metrics_json)` | Dedupe and evidence links | 3 days |
| `item_topics(item_id, topic_id, PK(item_id, topic_id))` | Item-to-topic mapping | With items |
| `videos(video_id PK, channel_id, title, published_at, duration_s, is_short, views, checked_at, outlier)` | Tracked YouTube videos | 30 days |
| `channel_baselines(channel_id, fmt, median_views, updated_at, PK(channel_id, fmt))` | Creator normals per format | Refreshed daily |
| `runs(run_at PK, ist_hour)` | Every completed run, for implicit-zero baselines | 8 days |
| `topic_values(run_at, topic_id, source_type, value, PK(run_at, topic_id, source_type))` | Non-zero per-run values | 8 days |
| `topic_heat(run_at, topic_id, heat, stage, n_sources, PK(run_at, topic_id))` | Heat history (rows only when heat > 0) | 8 days |
| `episodes(topic_id PK, started_at, below_watch_runs)` | Current episode per topic | Deleted when the episode ends |
| `alerts(id PK, topic_id, kind, sent_at, heat, subject)` | kind = `hot` or `capped`; cooldown, daily cap, digest | 30 days |
| `phrase_counts(hour, phrase, items, feeds, PK(hour, phrase))` | Hourly phrase frequency; only phrases with 2+ items in the hour | 8 days |
| `emerging_topics(topic_id PK, phrase, bucket, risk, created_at, last_seen_at)` | Auto-created topics | 48 h after last_seen |
| `source_health(source PK, last_ok_at, last_error_at, last_error, consecutive_failures)` | Digest health section | Kept |
| `kv(key PK, value)` | Run index, last-fetch times, market event dedupe keys, YouTube quota counter | Kept |

Expected database size: under 20 MB.

## 7. Collectors

**Common rules**
- All HTTP goes through the shared client: 10 s timeout, one retry after 2 s on timeout, connection error or 5xx, browser-like User-Agent, UTF-8 decoding.
- A collector exception is caught by the registry, logged (collector id and error class only), recorded in `source_health`, and the run continues.
- Items published more than 24 h ago are ignored, except YouTube videos, which are tracked for 7 days.
- Collectors run concurrently in a thread pool (max 8 workers). Target run time is under 2 minutes.

| Collector | Endpoint | Cadence | Emits |
|---|---|---|---|
| google_trends | `https://trends.google.com/trending/rss?geo=IN` | Every run | `search_trend` per trending item. Text = news item titles. `approx_traffic` parsed from "20K+" to 20000 |
| google_news | `https://news.google.com/rss/search?q=<query>+when:1h&hl=en-IN&gl=IN&ceid=IN:en`; Hindi queries use `hl=hi&gl=IN&ceid=IN:hi` | Every run, 11 queries | `news`. Outlet parsed from the "Headline - Source" title |
| news_feeds | 12 finance-section RSS feeds (below) | Every run | `news` |
| regulators | `https://rbi.org.in/pressreleases_rss.xml`, `https://www.sebi.gov.in/sebirss.xml` | Every run | `regulator` for items not seen before |
| x_trends | `https://trends24.in/india/`; fallback `https://getdaytrends.com/india/` | When 55+ min since last success | `x_trend` for the current top 50 with rank |
| youtube | Channel RSS `https://www.youtube.com/feeds/videos.xml?channel_id=<id>`; YouTube Data API `videos.list` | Every run | `video` for tracked videos up to 7 days old |
| reddit | `https://www.reddit.com/r/<sub>/rising/.rss` | Every run, best-effort | `forum` with `rising_rank` |
| markets | `https://query1.finance.yahoo.com/v8/finance/chart/<symbol>?interval=5m&range=1d` | Every run | `market` when a move crosses its threshold |

### google_news queries (sources.yaml, initial)

1. `"mutual fund" OR SIP OR NFO OR "index fund" OR ELSS`
2. `"income tax" OR ITR OR "tax regime" OR "capital gains" OR TDS OR GST`
3. `"home loan" OR EMI OR "credit card" OR CIBIL OR "fixed deposit" OR insurance`
4. `EPFO OR NPS OR PPF OR pension OR retirement OR UPI`
5. `Sensex OR Nifty OR "stock market" OR "Dalal Street"`
6. `RBI OR "repo rate" OR inflation OR rupee OR "gold price" OR "crude oil"`
7. `IPO OR GMP OR "F&O" OR SEBI OR multibagger`
8. `PMS OR AIF OR NRI OR "estate planning" OR "family office" OR REIT`
9. `site:moneycontrol.com` (Moneycontrol's own RSS has been frozen since April 2024)
10. Hindi: `शेयर बाजार OR सेंसेक्स OR निफ्टी OR आईपीओ`
11. Hindi: `म्यूचुअल फंड OR आयकर OR आरबीआई OR सोना`

### news_feeds (sources.yaml)

| Feed id | URL |
|---|---|
| et_markets | `https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms` |
| et_wealth | `https://economictimes.indiatimes.com/wealth/rssfeeds/837555174.cms` |
| et_mf | `https://economictimes.indiatimes.com/mf/rssfeeds/359241701.cms` |
| mint_markets | `https://www.livemint.com/rss/markets` |
| mint_money | `https://www.livemint.com/rss/money` |
| bs_markets | `https://www.business-standard.com/rss/markets-106.rss` |
| bs_finance | `https://www.business-standard.com/rss/finance-103.rss` |
| bs_economy | `https://www.business-standard.com/rss/economy-102.rss` |
| cnbctv18_market | `https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml` |
| cnbctv18_economy | `https://www.cnbctv18.com/commonfeeds/v1/cne/rss/economy.xml` |
| cnbctv18_pf | `https://www.cnbctv18.com/commonfeeds/v1/cne/rss/personal-finance.xml` |
| ndtvprofit | `https://feeds.feedburner.com/ndtvprofit-latest` |

### regulators

Only items not already in `items` and published within 24 h become signals. A regulator item affects scoring only if the matcher maps it to a topic; routine unmatched releases (for example, penalties on co-operative banks) are stored but ignored.

### x_trends

Parses the most recent hourly list (top 50, in rank order). If trends24 fails or yields no trends, getdaytrends is tried in the same run.

### youtube

- `channels.yaml` entries: `{id, name, lang}`. It is seeded with about 100 Indian personal-finance and markets creators, each verified by fetching its RSS during implementation.
- **Rotation:** channels are split into 3 groups by position in the file; run N fetches group `N % 3`, so each channel's RSS is checked every 45 minutes.
- New videos from RSS published within 7 days are added to `videos`.
- **Every run:** `videos.list` (part=snippet,statistics,contentDetails; 50 ids per call) refreshes views and duration for all tracked videos. `is_short` = duration of 180 s or less.
- **Baselines:** once per day per channel. Median views of the channel's RSS videos older than 3 days, computed separately for shorts and long videos. If a format has fewer than 3 such videos, use the channel's all-format median. If the channel has fewer than 3 in total, it gets no outlier score.
- **Outlier score** = `views / (median_views * f(age_h))`, where `f(age_h) = clamp(sqrt(age_h / 72), 0.15, 1.0)`. This is a heuristic and is tunable in settings.
- **Quota:** at most 30 `videos.list` calls per run, typically about 1,500 units/day. A daily counter in `kv` stops API calls at 8,000 units (the free quota is 10,000).
- If `YOUTUBE_API_KEY` is missing, the collector is disabled and the rest of the radar still works.

### reddit

Initial subreddits: IndiaInvestments, personalfinanceindia, IndianStockMarket, IndianStreetBets, FIREIndia, CreditCardsIndia, IndiaTax, StockMarketIndia. Requests are spaced 3 s apart. A 429 stops Reddit for the rest of the run; a 403 is recorded as a failure. Unauthenticated JSON has been blocked since May 2026 and RSS carries no scores, so position in the rising feed is the only velocity proxy. Failures from GitHub runner IPs are expected at times.

### markets

| Symbol | Meaning | Threshold | Topic |
|---|---|---|---|
| `^NSEI` | Nifty 50 | ±1.5% | market_moves |
| `^BSESN` | Sensex | ±1.5% | market_moves |
| `^NSEBANK` | Bank Nifty | ±2.0% | market_moves |
| `^INDIAVIX` | India VIX | +10% | market_moves |
| `GC=F` | Gold futures | ±2.0% | gold_price |
| `INR=X` | USD/INR | ±0.5% | rupee_forex |
| `^GSPC` | S&P 500 | ±2.0% | us_fed_global |

`pct_move = (regularMarketPrice - chartPreviousClose) / chartPreviousClose * 100`. A signal is emitted only if `regularMarketTime` is within the last 30 minutes (fresh session data), and at most once per symbol, direction and trading date (dedupe key in `kv`). Example title: "Nifty 50 down 2.1% today".

### events (digest only)

`events.yaml` entries: `{date, date_end (optional), name, topic}`. Initial entries:
- RBI MPC decisions: 2026-10-07, 2026-12-04, 2027-02-05.
- US FOMC decisions: 2026-10-28 and 2026-12-09 (US time; the result lands late night or early morning IST).
- Union Budget: 2027-02-01 (expected).
- Advance tax due: 2026-12-15, 2027-03-15.
- Financial year end and tax-saving deadline: 2027-03-31.
- Q2 FY27 results season: 2026-10-10 to 2026-11-14.

Events never change heat.

## 8. Topics and matching

`topics.yaml` schema:

```yaml
- id: gold_price
  name: Gold & silver prices
  bucket: markets          # personal_finance | markets | wealth | trading
  risk: careful            # general | careful | restricted
  keywords: [gold price, gold rate, silver price, gold etf, sovereign gold bond, सोना, चांदी]
  angles: [data_compare, history_lesson, myth_bust, should_you, explainer]
```

`topics.yaml` also holds `finance_vocab` (words that mark finance context, used in section 9) and `stock_vocab` (words that make an emerging topic restricted).

### Initial topics (47)

| Bucket | Topics (risk) |
|---|---|
| Personal finance (14) | sip_mutual_funds (careful), income_tax (general), itr_filing (general), capital_gains_tax (careful), insurance (careful), loans_emi (general), credit_cards (general), credit_score (general), retirement_pension (careful), fixed_income_savings (careful), upi_payments (general), scams_fraud (general), salary_budgeting (general), home_buying (careful) |
| Markets & macro (15) | market_moves (careful), rbi_policy (general), inflation (general), union_budget (general), gst (general), gold_price (careful), rupee_forex (general), crude_oil (general), us_fed_global (general), tariffs_trade (general), fii_dii_flows (careful), gdp_economy (general), banking_news (general), sebi_regulation (general), ipo_buzz (restricted) |
| Wealth / HNI (9) | pms_aif (careful), estate_succession (general), nri_investing (general), real_estate_vs_equity (careful), global_investing (careful), bonds_debt (careful), unlisted_esop (careful), rich_list_wealth (general), hni_tax_planning (general) |
| Trading & stocks (9) | fno_trading (restricted), stock_moves (restricted), smallcap_penny (restricted), corporate_actions (restricted), earnings_results (restricted), trading_psychology (careful), short_seller_fraud (restricted), finfluencers (general), crypto (restricted) |

### Matching rules

- The matched text is the title plus the first 500 characters of `text`, Unicode NFC-normalized, with whitespace collapsed.
- Latin keywords match case-insensitively on word boundaries (`(?<![a-z0-9])kw(?![a-z0-9])`), so "ipo" does not match "hippo".
- Keywords written in ALL CAPS with 4 or fewer characters (SIP, NPS, UPI, GST, EMI, PPF) match case-sensitively.
- Devanagari keywords match as substrings.
- An item can match several topics.

## 9. New-phrase spike detection

**Input:** titles of items first seen in this run: news, videos, forum posts, regulator items, plus Google Trends and X trend entries (hourly identity, section 6).

1. **Tokenize:** lowercase Latin text and keep Devanagari tokens. Split on punctuation, but keep `&` inside tokens (F&O). Drop pure numbers and 1-character tokens.
2. **Chunk:** split each title at stopwords (English stopwords plus boilerplate: live, updates, today, latest, news, check, know, here, why, what, how, says, said, will, may, top, day, week, amid, after, over, you, your, this, that, big, more, than).
3. **N-grams:** build 2-3 word phrases within each chunk. Also add whole Google Trends titles and X trend names (including hashtags) as phrases. Ignore phrases shorter than 5 characters and phrases on the settings blocklist (for example "share price", "stock market today", "sensex today", "top gainers", "top losers", "market live").
4. **Count:** add this run's per-phrase item and distinct-feed counts to `phrase_counts` for the current IST hour.
5. **Burst ratio:** `c2h` = items containing the phrase in the current and previous hour buckets. `baseline = max(7-day hourly average, same-IST-hour average over the previous 7 days, 0.25)`. `ratio = (c2h / 2) / baseline`. The same-hour term suppresses phrases that recur daily, such as market-open headlines.
6. **Emerging if** `ratio >= 4`, `c2h >= 3`, the items span 2 or more distinct feeds, and the phrase has **finance context**. Finance context means at least 50% of its items come from finance-only sources (news_feeds, google_news, youtube, reddit, regulators), or at least 50% contain a `finance_vocab` word.
7. **Subsumption:** if 80% or more of a shorter phrase's items also contain a longer phrase, keep only the longer one. If two phrases share 80% or more of their items, keep the one with more items.
8. **Mapping:** if 60% or more of the phrase's items match a single topic, the phrase is attached to that topic and shown in its brief as a spiking phrase. Otherwise it creates or refreshes the emerging topic `emerging:<slug>`:
   - name: the phrase in title case;
   - bucket: the most common bucket among its items' matched topics (default markets);
   - risk: restricted if any item contains a `stock_vocab` word (shares, stock, ipo, nse, bse, target, stake, listing), otherwise careful;
   - angles: the education-safe set.
9. Emerging topics are scored like static topics. Their items are those whose normalized title contains the phrase. They use a news prior of μ0 = 0.5, σ0 = 1.0 and expire 48 h after last activity.

## 10. Scoring, stages and alert rule

Computed every run for every static and emerging topic.

### Values (z-scored sources)

| Source | Value |
|---|---|
| news | Distinct news items matched to the topic, published (or first seen, when no date) in the last 60 min |
| youtube | Sum of `min(outlier, 10)` over matched videos up to 48 h old with outlier ≥ 1.5 |
| forum | Matched posts currently in the Reddit rising feeds |

Only non-zero values are stored. Baselines treat runs without a row as zero.

### Baseline and z-score

Samples are the topic's values over the previous 7 days from runs whose IST hour is h-1, h or h+1 (the current hour h). This covers about 84 runs and handles daily seasonality. With n samples, mean m and variance v:

- `mu = (n*m + P*mu0) / (n + P)`
- `sigma^2 = (n*v + P*sigma0^2) / (n + P)`
- `sigma_eff = max(sigma, floor)`
- `z = (value - mu) / sigma_eff` if `value >= min_value`, else 0

where `P = 48`. The priors mean that with no history the radar behaves as if it had fixed thresholds. This is the warm-up mechanism.

| Source | mu0 | sigma0 | floor | min_value | weight |
|---|---|---|---|---|---|
| news | 1.0 | 1.5 | 1.0 | 3 | 1.0 |
| youtube | 0.3 | 1.0 | 1.0 | 1.5 | 0.8 |
| forum | 0.2 | 0.8 | 0.8 | 2 | 0.5 |

### Bonuses (sources that are spikes by definition)

For each bonus type, take the max over the topic's signals.

| Type | Condition | Points |
|---|---|---|
| search_trend | Topic matched in Google Trending India right now | approx_traffic ≥ 500K: 5; ≥ 100K: 4; ≥ 20K: 3; else 2 |
| x_trend | Matched in the latest X India top 50 (fetch no older than 75 min) | rank 1-10: 4; 11-25: 3; 26-50: 2 |
| market | Threshold crossed, event no older than 6 h | 3; move ≥ 2× threshold: 4 |
| regulator | New matched RBI/SEBI item no older than 6 h | 2 |

### Heat and source count

- `H = 1.0*clip(z_news, 0, 6) + 0.8*clip(z_youtube, 0, 6) + 0.5*clip(z_forum, 0, 6) + sum(bonuses)`
- `n_sources` = number of source types with z ≥ 2 or bonus > 0.

### Stages

Thresholds: watch `W = 4.0`, hot `T = 6.0`.

- **Episode:** starts at the first run with H ≥ W; ends after 4 consecutive runs with H < W.

Stages are evaluated in this order; the first that applies wins:

1. **Quiet:** not in an episode.
2. **Fading:** H < W while the episode is still open, or H < previous H < the one before (two consecutive declines).
3. **Emerging:** H ≥ previous H and episode age ≤ 2 h.
4. **Peaking:** anything else in an episode.

### HOT alert rule (all must hold)

1. H ≥ T and H ≥ previous H.
2. n_sources ≥ 2, or a single bonus ≥ 3.
3. Stage is Emerging or Peaking.
4. No HOT alert for this topic in the last 12 h, or H ≥ 2 × the heat at the last alert.
5. Fewer than 4 HOT alerts sent today (IST date). Otherwise record `kind = capped` for the digest instead of sending.

When several topics qualify in one run they are processed in descending heat order. Urgency text: Emerging means "post within 3h"; Peaking means "post within 1h".

**Worked examples (used as tests)**
- **Gold record:** news 14 items/hr against mu 2, sigma 1.5 gives z 8, clipped to 6; Google Trending 50K+ adds 3; gold futures +2.3% adds 3. H = 12, n_sources = 3: HOT.
- **Slow drift:** news 4 items/hr against mu 2, sigma 1.5 gives z 1.33. H = 1.33: Quiet, no alert.

All thresholds, weights, priors, caps and cooldowns live in `settings.yaml`.

## 11. Briefs, angles, compliance

### Brief contents (in order)

1. Topic name, bucket, compliance label, stage and urgency.
2. **Headline:** the most recent matched news title, or the trending title.
3. **Why now:** up to 6 evidence lines, each with a number and a link. For example:
   - "Google Trends India: 'gold rate' 50K+ searches, trending since 09:40 IST"
   - "News: 14 articles in the last hour (normally about 2)"
   - "X India trending: #GoldPrice, rank 9"
   - "YouTube: '<title>' by <creator>, 4.1x their normal views (Short)"
   - "Reddit: 3 posts rising in r/IndiaInvestments"
   - "Market: gold futures +2.3% today"
   - "Regulator: SEBI, <title>"
4. **Spiking phrases** attached to the topic, if any.
5. **Angles:** the top 3 angle types, each with its LinkedIn, X and Instagram format and one filled hook.
6. **Hooks working right now:** up to 3 matched YouTube videos from the last 72 h with outlier ≥ 2.0: title, creator, Short or long, score, link.
7. **Compliance:** label and notes (below).

### Angle playbook (angles.yaml)

```yaml
- id: myth_bust
  name: Myth vs fact
  education_safe: true
  formats:
    linkedin: "Text post: 3 myths, one line each, plus the fact (150-250 words)"
    x: "Thread: one myth per post, 5-6 posts"
    instagram: "Reel 30-45 s 'Myth or fact?' or 7-slide carousel"
  hooks:
    - "Everyone's talking about {topic}. Here's what most people get wrong."
    - "3 myths about {topic} I hear every week."
```

There are 15 angle types. Education-safe types are marked with *.

hot_take_news, explainer*, before_after_rule*, myth_bust*, data_compare, history_lesson*, mistakes_list*, checklist*, faq*, red_flags*, should_you, what_if_calculator, contrarian_take, timeline*, poll*

Hook placeholders are `{topic}` (topic name or phrase) and `{headline}`. Poll hooks ask about behaviour, never price predictions.

### Angle selection

- **Candidates:** the topic's `angles` list. For restricted topics, only education-safe types.
- **Score:** scoreboard multiplier × stage weight.
  - Scoreboard multiplier: the angle type's median YouTube outlier score over 7 days, across shorts and long videos combined, or 1.0 if it has fewer than 3 videos.
  - Stage weight: Emerging gives ×1.3 to hot_take_news, explainer and before_after_rule. Peaking gives ×1.3 to myth_bust, data_compare, contrarian_take and mistakes_list. Everything else is ×1.0.
- **Pick:** the top 3. Ties go to the earlier entry in the topic's list.

### Format scoreboard (hooks.py)

Each tracked video title is classified by ordered, case-insensitive regex rules (English plus common Hinglish); the first match wins, and a title matching nothing is `other`. Initial rule order:

1. red_flags (red flag, beware, warning, fraud, scam, dhokha, savdhan)
2. mistakes_list (mistake, galti, avoid, never do, don't, mat karo)
3. myth_bust (myth, truth, sach, reality, lie)
4. data_compare (vs, versus, compare, comparison, better than)
5. before_after_rule (new rule, naya niyam, rule change, old vs new)
6. hot_take_news (breaking, just in, big news, announced, badi khabar)
7. history_lesson (history, last time, since 19xx/20xx, years of data, N saal)
8. what_if_calculator (a ₹/rs/lakh/crore amount together with month/year/salary/sip/emi; calculate; kitna)
9. should_you (should you, should i, kya ... chahiye, worth it, right time)
10. contrarian_take (unpopular, nobody tells, no one tells, overrated, wrong)
11. checklist (checklist, steps, things to, tips, before you)
12. faq (questions, faq, asked, answered, sawal)
13. explainer (explained, what is, kya hai, how ... works, kaise, basics, guide)
14. timeline (what happened, timeline, story of, full story)

The rules are refined against fixtures during implementation. For each angle type × format with 3 or more videos in the last 7 days, the scoreboard records the median outlier score and an example title.

### Compliance labels (plain text, no colors)

| Label | Notes shown in the brief |
|---|---|
| General | News or education. Keep it factual; no product pitch needed. |
| Careful | Involves products, rates or returns. No return promises and no "guaranteed", "assured" or "risk-free" language. Label example numbers as illustrations. Show past performance only if PaRRVA-verified. If a security or fund is named, add: "The securities quoted are for illustration only and are not recommendatory." |
| Restricted | Education only. No buy/sell/hold, target or stop-loss, and no tips or free calls. Do not combine price data less than 30 days old with forward-looking statements (SEBI price-data norms, effective 1 Jul 2026). Name securities only as illustrations, with the illustration disclaimer. |

**Footer on every email.** `settings.yaml` holds `firm.name` and `firm.sebi_reg_no`. When both are set, the footer quotes them verbatim; otherwise it says "your registered name and SEBI registration number".

> Before posting: put the registered name and SEBI registration number at the start of every securities-market post and in the profile bio (SEBI, from 1 May 2026). Include "Investment in securities market are subject to market risks. Read all the related documents carefully before investing." No testimonials, no "SEBI-approved" claims, no superlatives such as "best" or "No. 1 adviser". Archive posts for 5 years. SEBI approved a new Common Advertisement Code on 24 Sep 2026 (circular pending), so confirm current rules with your compliance adviser.

## 12. Email

- **Transport:** SMTP `smtp.gmail.com:587` with STARTTLS, logging in with `SMTP_USER` / `SMTP_APP_PASSWORD`. Use a dedicated Google account with 2-Step Verification and an app password. Recipients come from `ALERT_TO` (comma-separated). Gmail's free limit is 500 recipients per day.
- **Style:** neutral styling (black and grey text, simple tables), no colors that carry meaning, no emoji. HTML plus a plain-text alternative.
- **HOT email:** subject `HOT [<bucket name>] <topic name>: <headline truncated to 60 chars> — post within <N>h`. Bucket names are Personal finance, Markets & macro, Wealth/HNI, Trading & stocks. The body is the brief (section 11) followed by the footer.
- **Digest:** subject `Radar digest <DD Mon> — <N> trends`. Sections:
  1. **Top trends, last 24 h (up to 10):** topic, peak heat, current stage, alert status (sent / capped / none), one evidence line, link.
  2. **Near misses (up to 5):** topics whose peak heat reached W or more without a HOT alert.
  3. **Format scoreboard:** the top 5 angle type × format rows by median outlier score over 7 days, each with an example title.
  4. **Coming up (next 7 days):** events with 2 prep angle ideas from the event topic's angles.
  5. **Source health:** sources failing for 6 h or more, or "All sources OK".
- **Dry run:** `--dry-run` writes `out/<UTC timestamp>-<kind>-<topic>.html` and prints the subjects. No SMTP.
- **Send failure:** a HOT email is retried once. If it still fails, the alert is not recorded, so the next run retries it, and the current run exits non-zero after finishing its other work.

## 13. Operations

### Workflows

- **radar.yml**
  - Triggers: `schedule: cron "4,19,34,49 * * * *"` (off-peak minutes reduce GitHub delay) and `workflow_dispatch`.
  - `concurrency: {group: radar-state, cancel-in-progress: false}`. ubuntu-latest, `timeout-minutes: 10`.
  - Steps: checkout → setup-python 3.12 with pip cache → `pip install -r requirements.txt` → `actions/cache/restore` (path `radar.db`, key `radar-db-${{ github.run_id }}-${{ github.run_attempt }}`, restore-keys `radar-db-`) → `python -m radar run` → `actions/cache/save` (`if: always()`, same key).
- **digest.yml**
  - Triggers: `schedule: cron "30 2 * * *"` and `workflow_dispatch`.
  - Same concurrency group and cache restore/save; runs `python -m radar digest`.
  - `permissions: actions: write`. On day 1 of each month it runs `gh workflow enable radar.yml` and `gh workflow enable digest.yml`, so GitHub's 60-day inactivity auto-disable for scheduled workflows in public repos never triggers.
- **ci.yml:** on push and pull_request, run `pytest`.

### Secrets and logging

- Repository secrets: `YOUTUBE_API_KEY` (restricted to YouTube Data API v3 in Google Cloud), `SMTP_USER`, `SMTP_APP_PASSWORD`, `ALERT_TO`. They are passed only to the steps that need them.
- Workflow logs are public. Log counts, topic ids and source health only. Never print secrets, recipients or email bodies.

### State

`radar.db` lives in the Actions cache and is pruned every run (retention per section 6). If the cache is lost, the radar starts a fresh database and the priors (section 10) keep alerting sane while baselines rebuild over about 2 days.

### Error handling summary

| Failure | Behaviour |
|---|---|
| One collector errors or times out | Logged, `source_health` updated, run continues |
| Reddit 429 | Reddit skipped for the rest of the run |
| YouTube key missing or quota counter reached | YouTube API calls skipped; RSS-only data not scored |
| Malformed item | Item skipped and counted in logs |
| All collectors fail in one run | Run exits non-zero; GitHub emails the repo owner |
| HOT email send fails twice | Alert not recorded (retried next run); run exits non-zero |
| Source failing for 6 h or more | Listed in the digest's Source health section |
| Database missing or corrupt | Fresh schema created; priors cover warm-up |

## 14. Testing

- **Framework:** pytest. Tests never touch the network.
- **Parser tests:** each collector's `parse` is tested against real responses saved during implementation: `google_trends_in.xml`, `google_news_markets.xml`, `et_markets.xml`, `trends24_india.html`, `getdaytrends_india.html`, `youtube_channel.xml`, `youtube_videos_list.json`, `reddit_rising.xml`, `yahoo_chart_nsei.json`, `rbi_press.xml`, `sebi.xml`.
- **Unit tests:**
  - matcher: word boundaries, the ALL-CAPS rule, Devanagari, multiple topics.
  - phrases: tokenize, chunk, burst ratio, same-hour baseline, finance context, subsumption, mapping to topic vs emerging.
  - scorer: priors and hour window, implicit zeros, bonuses, heat, stages, alert rule.
  - hooks: classifier ordering.
  - briefs: angle selection respects risk, hooks filled, compliance notes.
  - emailer: subject formats, all sections present, no emoji in rendered output.
  - store: schema creation, pruning.
- **Scenario tests (synthetic run sequences through scorer):**
  1. A sharp spike produces exactly one HOT alert.
  2. A slow drift produces none.
  3. A fading topic produces none.
  4. The same topic 3 h after an alert is suppressed by the cooldown, unless its heat has doubled.
  5. Five qualifying topics in one IST day produce 4 HOT alerts and 1 capped.
  6. The two worked examples in section 10.
- **Acceptance:** `python -m radar run --dry-run` on the local machine produces briefs from live sources; the first scheduled GitHub run succeeds; the first digest arrives.

## 15. Phase 2 (out of scope here)

- Instagram Business Discovery collector for creator Reel views (needs a Meta app and an Instagram professional account).
- LLM-written angles and post drafts.
- X API pay-per-use trends (about $0.01 per request, roughly $7/month hourly).
- SerpApi Google Trends with the Business & Finance category.
- Feedback buttons in emails to tune thresholds.

## 16. References (research of 2026-09-26)

- Google Trends RSS: https://trends.google.com/trending/rss?geo=IN
- YouTube quota costs: https://developers.google.com/youtube/v3/determine_quota_cost ; revision history: https://developers.google.com/youtube/v3/revision_history
- X API pricing (pay-per-use): https://docs.x.com/x-api/getting-started/pricing
- Reddit unauthenticated JSON blocked, RSS working: https://dev.to/listwright/reddits-json-returns-403-in-2026-the-rss-feeds-still-answer-1gg5
- LinkedIn scraping litigation (Proxycurl): https://www.socialmediatoday.com/news/linkedin-wins-legal-case-data-scrapers-proxycurl/756101/
- SEBI Master Circular for Investment Advisers (27 Jun 2025): https://www.sebi.gov.in/legal/master-circulars/jun-2025/master-circular-for-investment-advisers_94821.html
- SEBI registered name and number on social media (Feb 2026): https://www.sebi.gov.in/legal/circulars/feb-2026/ease-of-doing-investment-eodi-disclosure-of-registered-name-and-registration-number-by-sebi-regulated-entities-and-their-agents-on-social-media-platforms-smps-_100005.html
- SEBI price data for educational purposes (May 2026): https://www.sebi.gov.in/legal/circulars/may-2026/norms-for-sharing-and-usage-of-price-data-for-educational-purposes_101293.html
- SEBI PaRRVA: https://www.sebi.gov.in/legal/circulars/apr-2025/recognition-and-operationalization-of-past-risk-and-return-verification-agency-parrva-_93321.html
- SEBI Board decisions of 24 Sep 2026 (Common Advertisement Code): https://www.sebi.gov.in/media-and-notifications/press-releases/sep-2026/key-decisions-taken-in-the-sebi-board-meeting-dated-24th-september-2026_104725.html
- RBI MPC schedule FY2026-27: https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=62422
- FOMC calendar: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
